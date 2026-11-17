"""허브 일별 기상(No.756)으로 기상청 관측(ASOS)을 교차검증하고, 수요 모델 입력 기온을 바꿔 비교한다.

실행(backend/ 에서):
  python -m scripts.check_hub_weather <KPX_수요_폴더> [--start 2024-01-01] [--end 2025-12-31]
                                      [--asos-dir runtime/asos] [--out runtime/hub_weather_check.json]
필요: backend/.env 의 JEJUHUB_PROJECT_KEY, ASOS 수집 결과(runtime/asos/asos_jeju.csv),
      수요 비교에는 xgboost(`uv sync --extra ml`)와 KPX 시간별 제주전력수요 파일.

하는 일
1. 날짜별 허브 일별 기상을 받아 runtime/hub_weather/ 에 저장한다(이어받기. 호출 한도가 차면 받은 만큼만 쓴다).
2. 고도 100 m 미만 관측소를 평균한 기온을 ASOS 제주(184) 일평균 기온과 비교한다(상관·편향·오차).
3. 2017~2023 으로 학습한 수요 모델에 입력 기온만 바꿔 검증한다: ASOS(현재 방식) / 허브 / 허브 편향 보정.
   편향은 첫 해(기본 2024)에서 구해 **그 이후 해에만** 적용한다(같은 해에 맞추지 않는다).

한계: 허브 일별 기상은 서비스 입력이 될 수 없다(2025-03 말 이후 비어 있음). 이 분석은 교차검증용이다.
"""

import argparse
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

from app.core.config import Settings
from app.providers.jejuhub_ev import QuotaExceeded, call_count, enable_call_log
from app.providers.jejuhub_weather import (
    day_mean_temperature,
    fetch_altitudes,
    fetch_day,
    lowland_names,
    read_cached_day,
    write_cached_day,
)

TRAIN_END = date(2023, 12, 31)
MIN_ASOS_HOURS = 20  # ASOS 일평균은 시간값이 20개 이상일 때만 쓴다


# ---------- 순수 계산(테스트 대상) ----------
def asos_daily_means(hourly: dict[tuple[date, int], float]) -> dict[date, float]:
    by_day: dict[date, list[float]] = {}
    for (d, _), v in hourly.items():
        by_day.setdefault(d, []).append(v)
    return {d: sum(v) / len(v) for d, v in by_day.items() if len(v) >= MIN_ASOS_HOURS}


def crosscheck(hub: dict[date, float], asos: dict[date, float]) -> dict:
    """허브-ASOS 일평균 기온 비교. 편향 = 허브 - ASOS."""
    days = sorted(set(hub) & set(asos))
    if len(days) < 3:
        raise ValueError("Need at least 3 common days")
    x, y = [hub[d] for d in days], [asos[d] for d in days]
    diff = [a - b for a, b in zip(x, y, strict=True)]
    return {
        "days": len(days),
        "correlation": statistics.correlation(x, y),
        "bias_c": statistics.mean(diff),
        "mae_c": statistics.mean(abs(v) for v in diff),
        "max_abs_diff_c": max(abs(v) for v in diff),
    }


def calibration_bias(hub: dict[date, float], asos: dict[date, float], year: int) -> float:
    """해당 해의 평균 편향(허브 - ASOS). 이 값을 허브 기온에서 빼서 보정한다."""
    days = [d for d in set(hub) & set(asos) if d.year == year]
    if not days:
        raise ValueError(f"No common days in {year}")
    return statistics.mean(hub[d] - asos[d] for d in days)


# ---------- 허브 수집 ----------
def collect_hub(
    settings: Settings, start: date, end: date, cache: Path, refetch_empty: bool
) -> dict:
    key = settings.jejuhub_project_key.get_secret_value()
    alt_path = cache / "stations.json"
    new = cached = 0
    stopped: date | None = None
    with httpx.Client(timeout=settings.http_timeout) as client:
        try:
            altitudes = json.loads(alt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            altitudes = fetch_altitudes(key, client=client)
            cache.mkdir(parents=True, exist_ok=True)
            alt_path.write_text(json.dumps(altitudes, ensure_ascii=False), encoding="utf-8")
        names = lowland_names(altitudes)
        hub: dict[date, float] = {}
        empty_days: list[date] = []
        d = start
        while d <= end:
            rows = read_cached_day(cache, d)
            if rows is None or (not rows and refetch_empty):
                try:
                    rows = fetch_day(key, d, client=client)
                except QuotaExceeded:
                    stopped = d
                    break
                write_cached_day(cache, d, rows)
                new += 1
            else:
                cached += 1
            mean = day_mean_temperature(rows, names)
            if mean is None:
                empty_days.append(d)
            else:
                hub[d] = mean
            d += timedelta(days=1)
    return {
        "hub": hub,
        "empty_days": empty_days,
        "stopped_at": stopped,
        "lowland_stations": sorted(names),
        "fetched": new,
        "cached": cached,
    }


# ---------- 수요 모델 비교 ----------
def demand_validation(
    demand_dir: Path,
    asos_hourly: dict,
    asos_day: dict[date, float],
    hub: dict[date, float],
    calib_year: int,
) -> dict:
    import scripts.train_demand_model as t  # xgboost 가 필요하다
    from app.tools.jeju_model import trend_years

    demand = t.load_demand(demand_dir)
    train_dates = [d for d, _ in demand if date(2017, 1, 1) <= d <= TRAIN_END]
    trend_max = trend_years(max(train_dates))
    train_rows = [
        r
        for r in t.build_rows(demand, asos_hourly, date(2017, 1, 1), trend_max)
        if r[0] <= TRAIN_END
    ]
    model = t._fit(train_rows)
    bias = calibration_bias(hub, asos_day, calib_year)

    def run(temp_of_day, days: list[date]) -> dict:
        temps = {(d, h): temp_of_day(d) for d in days for h in range(24)}
        keep = set(days)
        rows = [r for r in t.build_rows(demand, temps, min(days), trend_max) if r[0] in keep]
        s = t._summary([r[0] for r in rows], [r[3] for r in rows], t._predict(model, rows))
        return {
            "days": len(days),
            "mae_mw": s["mae_mwh"],
            "mape_pct": s["mape_pct"],
            "bias_mw": s["bias_mwh"],
            "daily_peak_mae_mw": s["daily_peak_mae_mwh"],
        }

    result: dict = {"calibration_year": calib_year, "calibration_bias_c": bias, "by_year": {}}
    years = sorted({d.year for d in hub if d > TRAIN_END})
    for year in years:
        days = sorted(d for d in hub if d.year == year and d in asos_day)
        if len(days) < 30:
            continue
        entry = {
            "asos": run(lambda d: asos_day[d], days),
            "hub_raw": run(lambda d: hub[d], days),
        }
        if year > calib_year:
            entry["hub_calibrated"] = run(lambda d: hub[d] - bias, days)
        result["by_year"][str(year)] = entry
    return result


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("demand_dir", type=Path, help="KPX 시간별 제주전력수요 파일 폴더")
    p.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    p.add_argument("--asos-dir", type=Path, default=Path("runtime/asos"))
    p.add_argument("--out", type=Path, default=Path("runtime/hub_weather_check.json"))
    p.add_argument(
        "--refetch-empty",
        action="store_true",
        help="비어 있던 날을 다시 받는다(호출 한도를 크게 쓴다. 2025-03 이후는 원래 비어 있다)",
    )
    a = p.parse_args(argv)
    if a.start <= TRAIN_END:
        print("시작일은 학습 구간(2023-12-31) 이후여야 합니다.", file=sys.stderr)
        return 2
    settings = Settings()
    if settings.jejuhub_project_key is None:
        print("JEJUHUB_PROJECT_KEY가 설정되어 있지 않습니다(backend/.env).", file=sys.stderr)
        return 2
    cache = settings.ev_profile_path.parent / "hub_weather"
    enable_call_log(cache.parent / "hub_calls.log")
    try:
        got = collect_hub(settings, a.start, a.end, cache, a.refetch_empty)
    except RuntimeError as exc:
        print(f"허브 수집 실패: {exc}", file=sys.stderr)
        return 1
    hub = got["hub"]
    print(f"이번 실행 허브 호출 {call_count()}회 (내역: runtime/hub_calls.log)")
    if got["stopped_at"]:
        print(f"{got['stopped_at']}부터 하루 호출 한도로 멈췄습니다. 받은 날까지만 분석합니다.")
    print(
        f"허브 일별 기상: 새로 {got['fetched']}일, 저장본 {got['cached']}일, 사용 가능 {len(hub)}일, "
        f"데이터 없는 날 {len(got['empty_days'])}일"
    )

    import scripts.train_demand_model as t

    asos_hourly = {
        (ts.date(), ts.hour): v["temperature_c"]
        for ts, v in t.read_asos(a.asos_dir / "asos_jeju.csv").items()
        if v["temperature_c"] is not None
    }
    asos_day = asos_daily_means(asos_hourly)
    report: dict = {
        "period": [a.start.isoformat(), a.end.isoformat()],
        "lowland_stations": got["lowland_stations"],
        "hub_days_usable": len(hub),
        "hub_days_empty": len(got["empty_days"]),
        "hub_last_day_with_data": max(hub).isoformat() if hub else None,
        "crosscheck": crosscheck(hub, asos_day),
    }
    c = report["crosscheck"]
    print(
        f"교차검증 {c['days']}일: 상관 {c['correlation']:.4f}, 편향 {c['bias_c']:+.2f}℃, "
        f"MAE {c['mae_c']:.2f}℃, 최대 차이 {c['max_abs_diff_c']:.1f}℃"
    )
    calib_year = a.start.year
    try:
        report["demand"] = demand_validation(a.demand_dir, asos_hourly, asos_day, hub, calib_year)
    except ModuleNotFoundError as exc:
        print(
            f"수요 모델 비교를 건너뜁니다({exc.name} 없음, `uv sync --extra ml`).", file=sys.stderr
        )
    else:
        print(
            f"허브 편향 보정값({calib_year}년 기준): {report['demand']['calibration_bias_c']:+.2f}℃"
        )
        for year, e in report["demand"]["by_year"].items():
            for label, m in e.items():
                print(
                    f"  {year} {label:15s} {m['days']:4d}일  MAE {m['mae_mw']:.2f} MW  "
                    f"MAPE {m['mape_pct']:.2f}%  편향 {m['bias_mw']:+.2f} MW  하루 최대 MAE {m['daily_peak_mae_mw']:.2f}"
                )
    args_out = a.out
    args_out.parent.mkdir(parents=True, exist_ok=True)
    args_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장 → {args_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
