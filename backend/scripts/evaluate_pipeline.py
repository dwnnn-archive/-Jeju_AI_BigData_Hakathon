"""과거 날짜로 파이프라인 전체(발전량·수요 모델 + 위험 규칙)를 돌려 실제 출력제한일과 비교한다.

사용 (backend/ 에서, xgboost 필요):
    python -m scripts.evaluate_pipeline <KPX_발전량_폴더> <KPX_수요_폴더> <ASOS_폴더> \\
        <출력제어_zip_또는_폴더> [--start 2023-01-01] [--end 2024-05-30] [--work-dir runtime/e2e]

- 점검 기간을 학습에서 완전히 뺀 모델을 work-dir에 따로 학습한다(풍력·태양광·수요 모두
  --start 이전 데이터만 사용). 서비스가 쓰는 ToolBundle 의 발전량·수요 경로와 rules.evaluate 를
  그대로 호출한다.
- 날씨: 과거 예보 이력이 없어 그날의 ASOS 실측(고산 풍속·기온·전운량, 제주 기온)을
  예보 자리에 넣는다.
  실제 서비스보다 유리한 조건이다.
- 정답: KPX 출력제어 이력에서 하루라도 풍력 또는 태양광 제어가 있으면 "출력제한일".
- 출력제어 이력은 풍력 2024-05-30, 태양광 2024-06-03에서 끝나므로 --end 는 그 이전이어야 한다.
"""

import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from app.core.config import Settings
from app.domain.rules import allocate, evaluate
from app.domain.schemas import AnalysisRequest, Capacities, WeatherHour
from app.tools.bundle import ToolBundle
from app.tools.jeju_model import sky_from_cloud_tenths
from scripts.build_training_csv import build, read_asos
from scripts.kpx_curtailment import load_jeju_curtailment
from scripts.train_demand_model import train as train_demand
from scripts.train_jeju_model import train as train_generation

LEVELS = ("NORMAL", "CAUTION", "CRITICAL")


def asos_by_hour(path: Path) -> dict[tuple[date, int], dict]:
    return {(t.date(), t.hour): v for t, v in read_asos(path).items()}


def day_weather(d: date, gosan: dict, jeju: dict) -> tuple[list, list] | None:
    """(발전량 모델용, 수요 모델용) 하루 날씨. 24시간이 모두 있지 않으면 None."""
    gen, dem = [], []
    for h in range(24):
        g, j = gosan.get((d, h)), jeju.get((d, h))
        if not g or not j or None in (g["wind_ms"], g["temperature_c"], j["temperature_c"]):
            return None
        cloud = g["cloud_tenths"]
        if (
            cloud is None
        ):  # 전운량이 빈 시간은 직전 3시간 안의 관측을 이어 쓴다(학습 CSV와 같은 규칙)
            for back in (1, 2, 3):
                prev = gosan.get((d, h - back)) if h - back >= 0 else None
                if prev and prev["cloud_tenths"] is not None:
                    cloud = prev["cloud_tenths"]
                    break
        if cloud is None:
            return None
        gen.append(
            WeatherHour(
                date=d,
                hour=h,
                wind_ms=g["wind_ms"],
                temperature_c=g["temperature_c"],
                sky=sky_from_cloud_tenths(cloud),
                irradiance_wm2=0,
            )
        )
        dem.append(
            WeatherHour(
                date=d, hour=h, wind_ms=0, temperature_c=j["temperature_c"], sky=1, irradiance_wm2=0
            )
        )
    return gen, dem


def run_day(bundle: ToolBundle, d: date, gen_weather: list, dem_weather: list) -> dict:
    bundle._gosan_weather = lambda request: gen_weather
    bundle._jeju_city_weather = lambda request: dem_weather
    request = AnalysisRequest(date=d, region="jeju", mode="live")
    generation, _ = bundle.generation(request, gen_weather, 0)
    demand, _ = bundle.demand(request)
    result = evaluate(generation, demand, d)
    return {
        "date": d,
        "risk": result["risk"],
        "peak_ratio": result["peak_ratio"],
        "peak_hour": result["peak_hour"],
        "peak_surplus_mwh": result["peak_surplus_mwh"],
        "absorbed_mwh": allocate(result["peak_surplus_mwh"])["absorbed_mwh"],
    }


def _pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    import numpy as np

    return float(np.corrcoef(x, y)[0, 1])


def summarize(days: list[dict]) -> dict:
    """days: run_day 결과 + actual(bool), actual_hours(set), wind_max_mwh, wind_total_mwh."""
    total = len(days)
    actual_days = [d for d in days if d["actual"]]
    out: dict = {"days": total, "actual_curtailment_days": len(actual_days)}
    by_level = {}
    for level in LEVELS:
        subset = [d for d in days if d["risk"] == level]
        hit = [d for d in subset if d["actual"]]
        by_level[level] = {
            "days": len(subset),
            "actual_curtailment_days": len(hit),
            "precision": len(hit) / len(subset) if subset else None,
        }
    out["by_predicted_level"] = by_level
    for name, levels in (
        ("caution_or_above", ("CAUTION", "CRITICAL")),
        ("critical", ("CRITICAL",)),
    ):
        flagged = [d for d in days if d["risk"] in levels]
        caught = [d for d in actual_days if d["risk"] in levels]
        out[name] = {
            "flagged_days": len(flagged),
            "recall": len(caught) / len(actual_days) if actual_days else None,
            "precision": len([d for d in flagged if d["actual"]]) / len(flagged)
            if flagged
            else None,
            "false_alarm_days": len([d for d in flagged if not d["actual"]]),
        }
    # 예측한 피크 시간이 실제 제어 시간과 얼마나 가까운가(적중한 출력제한일만)
    caught = [d for d in actual_days if d["risk"] != "NORMAL" and d["actual_hours"]]
    dist = [min(abs(d["peak_hour"] - h) for h in d["actual_hours"]) for d in caught]
    out["peak_hour_distance"] = {
        "days": len(dist),
        "within_1h": sum(x <= 1 for x in dist) / len(dist) if dist else None,
        "within_2h": sum(x <= 2 for x in dist) / len(dist) if dist else None,
    }
    # 크기: 풍력 제어일에서 예측 잉여 vs 실제 하루 최대 시간당 제어량·하루 합(참고값)
    wind_days = [d for d in days if d["wind_total_mwh"] > 0]
    surplus = [d["peak_surplus_mwh"] for d in wind_days]
    out["magnitude_on_wind_curtailment_days"] = {
        "days": len(wind_days),
        "mean_predicted_peak_surplus_mwh": sum(surplus) / len(surplus) if surplus else None,
        "mean_actual_max_hourly_curtailment_mwh": (
            sum(d["wind_max_mwh"] for d in wind_days) / len(wind_days) if wind_days else None
        ),
        "corr_with_max_hourly": _pearson(surplus, [d["wind_max_mwh"] for d in wind_days]),
        "corr_with_daily_total": _pearson(surplus, [d["wind_total_mwh"] for d in wind_days]),
    }
    flagged = [d for d in days if d["risk"] != "NORMAL"]
    capacity = sum(Capacities().model_dump().values())  # 서비스의 기본 배분 용량 합계(MWh)
    out["allocation"] = {
        "flagged_days": len(flagged),
        "capacity_mwh": capacity,
        "within_capacity": (
            sum(d["peak_surplus_mwh"] <= capacity for d in flagged) / len(flagged)
            if flagged
            else None
        ),
    }
    return out


def evaluate_pipeline(
    kpx_gen_dir: Path,
    kpx_demand_dir: Path,
    asos_dir: Path,
    curtailment: Path,
    work_dir: Path,
    start: date,
    end: date,
) -> dict:
    if start >= end:
        raise ValueError("start must be before end")
    work_dir.mkdir(parents=True, exist_ok=True)
    csv_path = work_dir / "train.csv"
    build(kpx_gen_dir, asos_dir, csv_path, curtailment=curtailment)
    # 점검 기간을 학습에서 뺀다: 풍력·태양광은 start 이전, 수요는 start 하루 전까지.
    train_generation(
        csv_path, work_dir / "generation", wind_test_start=start, solar_test_start=start
    )
    train_demand(
        kpx_demand_dir,
        asos_dir,
        work_dir / "demand",
        start=date(2017, 1, 1),
        train_end=start - timedelta(days=1),
    )
    settings = Settings(
        _env_file=None,
        jeju_model_dir=work_dir / "generation",
        jeju_demand_model_dir=work_dir / "demand",
    )
    bundle = ToolBundle(settings)
    gosan, jeju = (
        asos_by_hour(asos_dir / "asos_gosan.csv"),
        asos_by_hour(asos_dir / "asos_jeju.csv"),
    )
    wind, solar = load_jeju_curtailment(curtailment)
    wind_by_day: dict[date, dict[int, float]] = defaultdict(dict)
    for (d, h), v in wind.items():
        wind_by_day[d][h] = v
    solar_by_day: dict[date, set[int]] = defaultdict(set)
    for d, h in solar:
        solar_by_day[d].add(h)

    days, skipped = [], 0
    d = start
    while d <= end:
        weather = day_weather(d, gosan, jeju)
        if weather is None:
            skipped += 1
        else:
            row = run_day(bundle, d, *weather)
            hours = set(wind_by_day.get(d, {})) | solar_by_day.get(d, set())
            row.update(
                actual=bool(hours),
                actual_hours=hours,
                wind_max_mwh=max(wind_by_day.get(d, {}).values(), default=0.0),
                wind_total_mwh=sum(wind_by_day.get(d, {}).values()),
            )
            days.append(row)
        d += timedelta(days=1)
    report = summarize(days)
    report["period"] = [start.isoformat(), end.isoformat()]
    report["skipped_days_missing_weather"] = skipped
    report["note"] = (
        "Weather is observed (ASOS), not forecast. Models exclude the evaluation period. "
        "Actual curtailment day = any hour of wind or solar curtailment in the KPX history."
    )
    (work_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (work_dir / "days.json").write_text(
        json.dumps(
            [
                {**d, "date": d["date"].isoformat(), "actual_hours": sorted(d["actual_hours"])}
                for d in days
            ],
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("kpx_gen_dir", type=Path)
    p.add_argument("kpx_demand_dir", type=Path)
    p.add_argument("asos_dir", type=Path)
    p.add_argument("curtailment", type=Path)
    p.add_argument("--start", type=date.fromisoformat, default=date(2023, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2024, 5, 30))
    p.add_argument("--work-dir", type=Path, default=Path("runtime/e2e"))
    a = p.parse_args()
    print(
        json.dumps(
            evaluate_pipeline(
                a.kpx_gen_dir,
                a.kpx_demand_dir,
                a.asos_dir,
                a.curtailment,
                a.work_dir,
                a.start,
                a.end,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )
