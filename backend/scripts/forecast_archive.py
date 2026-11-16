"""예보 저장 장치 도구: 정기 수집, ML 학습용 표 내보내기, 예보 오차 보고.

사용 (backend/ 에서, backend/.env 에 KMA_API_KEY 필요):
    # 1) 정기 수집: 스케줄러가 몇 시간마다 호출한다
    #    (단기예보 발표는 02/05/08/11/14/17/20/23시, 10분 뒤가 좋다)
    python -m scripts.forecast_archive collect
    # 2) 실측과 맞춰 ML 학습용 표로 내보내기
    #    (ASOS 실측은 scripts.collect_asos 로 받은 monthly 폴더를 읽는다)
    python -m scripts.forecast_archive export runtime/asos runtime/forecast_dataset.csv
    # 3) 예보가 실제로 얼마나 틀렸는지 보고
    python -m scripts.forecast_archive report runtime/asos

- 수집은 같은 발표를 두 번 받아도 한 번만 저장한다(스케줄러가 겹쳐 돌아도 안전하다).
- 저장 파일은 FORECAST_ARCHIVE_PATH(기본: DB 파일 옆 forecasts.sqlite). Git에 올라가지 않는다.
- 기상청은 최근 3일 치 발표분만 다시 주므로 **정기 수집을 계속 돌려야** 이력이 쌓인다.
- 예보 격자와 ASOS 지점 대응: 고산 격자(46,35) = 고산(185), 제주시 격자(53,38) = 제주(184).
  다른 격자는 실측이 없어 관측값 열이 비어 있다.
- ASOS 실측은 전일(D-1) 자료만 제공되므로 평가는 하루 이상 지난 예보부터 가능하다.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import Settings
from app.providers.asos import JEJU_STATIONS, KST
from app.providers.kma import KmaProvider
from app.providers.kma_nowcast import KmaNowcastProvider
from app.repositories.forecasts import ForecastArchive
from app.tools.demand_model import JEJU_CITY_GRID
from app.tools.jeju_model import GOSAN_GRID, sky_from_cloud_tenths
from scripts.build_training_csv import read_asos

GRIDS = {"gosan": GOSAN_GRID, "jeju_city": JEJU_CITY_GRID}
GRID_STATION = {GOSAN_GRID: "gosan", JEJU_CITY_GRID: "jeju"}
OBSERVED = {"WSD": "wind_ms", "TMP": "temperature_c", "T1H": "temperature_c", "SKY": "sky"}
LEAD_BUCKETS = ((0, 2), (3, 6), (7, 12), (13, 24), (25, 48), (49, 999))
DATASET_FIELDS = [
    "source",
    "nx",
    "ny",
    "base_date",
    "base_time",
    "valid_date",
    "valid_hour",
    "lead_hours",
    "category",
    "forecast",
    "raw",
    "observed_wind_ms",
    "observed_temperature_c",
    "observed_sky",
]


def archive_path(settings: Settings) -> Path:
    return settings.forecast_archive_path or settings.database_path.parent / "forecasts.sqlite"


def collect(
    settings: Settings,
    archive: ForecastArchive,
    now: datetime,
    client: httpx.Client | None = None,
) -> dict:
    """두 격자의 단기예보·초단기예보·초단기실황을 받아 저장한다. 실패는 모아서 돌려준다."""
    key = settings.kma_api_key
    if not key or not key.get_secret_value():
        raise ValueError("kma_key_missing")
    own_client = client is None
    client = client or httpx.Client(timeout=settings.http_timeout)
    base = (settings.kma_base_url, settings.kma_auth_param)
    short = KmaProvider(key.get_secret_value(), client, *base, recorder=archive.record_issue)
    ultra = KmaNowcastProvider(key.get_secret_value(), client, *base, recorder=archive.record_issue)
    before = archive.counts()["issues"]
    errors: list[str] = []
    try:
        for name, (nx, ny) in GRIDS.items():
            for label, call in (
                ("short", lambda nx=nx, ny=ny: short.issue(nx, ny, now=now)),
                ("ultra_fcst", lambda nx=nx, ny=ny: ultra.raw_forecast(nx, ny, now)),
                ("ultra_ncst", lambda nx=nx, ny=ny: ultra.raw_observation(nx, ny, now)),
            ):
                try:
                    call()
                except Exception as exc:  # noqa: BLE001 - 한 건이 실패해도 나머지는 계속 받는다
                    # 예외 메시지에 키가 담긴 URL이 있을 수 있어 종류만 남긴다.
                    errors.append(f"{name}/{label}: {type(exc).__name__}")
    finally:
        if own_client:
            client.close()
    return {"new_issues": archive.counts()["issues"] - before, "errors": errors}


def _load_observations(asos_dir: Path) -> dict[tuple[str, str, int], dict]:
    """(지점 이름, 날짜, 시) → 실측. monthly 폴더의 모든 월 파일을 읽는다."""
    out: dict[tuple[str, str, int], dict] = {}
    for name, station in JEJU_STATIONS.items():
        for path in sorted((asos_dir / "monthly").glob(f"{station}_*.csv")):
            for t, v in read_asos(path).items():
                t = t.astimezone(KST)
                cloud = v["cloud_tenths"]
                out[(name, t.date().isoformat(), t.hour)] = {
                    "wind_ms": v["wind_ms"],
                    "temperature_c": v["temperature_c"],
                    "sky": None if cloud is None else sky_from_cloud_tenths(cloud),
                }
    return out


def _lead_hours(issue: dict, value: dict) -> float:
    base = datetime.strptime(issue["base_date"] + issue["base_time"][:4], "%Y%m%d%H%M")
    valid = datetime.strptime(f"{value['valid_date']} {value['valid_hour']:02d}", "%Y-%m-%d %H")
    return (valid - base).total_seconds() / 3600


def export_dataset(archive: ForecastArchive, asos_dir: Path, out: Path) -> int:
    """저장된 예보 전부를 실측과 맞춰 CSV 로 낸다. 반환값은 행 수."""
    observed = _load_observations(asos_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DATASET_FIELDS)
        writer.writeheader()
        for issue in archive.issues():
            station = GRID_STATION.get((issue["nx"], issue["ny"]))
            for value in archive.values(issue["id"]):
                obs = observed.get((station, value["valid_date"], value["valid_hour"])) or {}
                row = {
                    **{k: issue[k] for k in ("source", "nx", "ny", "base_date", "base_time")},
                    "valid_date": value["valid_date"],
                    "valid_hour": value["valid_hour"],
                    "lead_hours": _lead_hours(issue, value),
                    "category": value["category"],
                    "forecast": "" if value["value"] is None else value["value"],
                    "raw": value["raw"],
                    "observed_wind_ms": obs.get("wind_ms", ""),
                    "observed_temperature_c": obs.get("temperature_c", ""),
                    "observed_sky": obs.get("sky", ""),
                }
                writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
                rows += 1
    return rows


def summarize_errors(dataset: Path) -> list[dict]:
    """출처·항목·선행 시간대별 예보 오차(MAE, 편향, SKY는 적중률)."""
    groups: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    with dataset.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            column = OBSERVED.get(r["category"])
            actual = r.get(f"observed_{column}") if column else ""
            if not column or actual in ("", None) or r["forecast"] == "":
                continue
            lead = float(r["lead_hours"])
            bucket = next(((lo, hi) for lo, hi in LEAD_BUCKETS if lo <= lead <= hi), None)
            if bucket is None:
                continue
            groups[(r["source"], r["category"], bucket)].append(
                (float(r["forecast"]), float(actual))
            )
    summary = []
    for (source, category, (lo, hi)), pairs in sorted(groups.items()):
        n = len(pairs)
        if category == "SKY":
            summary.append(
                {
                    "source": source,
                    "category": category,
                    "lead": f"{lo}-{hi}h",
                    "n": n,
                    "accuracy": sum(f == a for f, a in pairs) / n,
                }
            )
        else:
            errs = [f - a for f, a in pairs]
            summary.append(
                {
                    "source": source,
                    "category": category,
                    "lead": f"{lo}-{hi}h",
                    "n": n,
                    "mae": sum(abs(e) for e in errs) / n,
                    "bias": sum(errs) / n,
                }
            )
    return summary


def _print_report(summary: list[dict]) -> None:
    if not summary:
        print(
            "실측과 맞출 수 있는 예보가 아직 없습니다. "
            "저장 후 하루 이상 지나고 ASOS 실측을 받아야 합니다."
        )
        return
    print("출처        항목  선행시간   표본  MAE      편향 / 적중률")
    for s in summary:
        tail = (
            f"적중률 {s['accuracy']:.1%}"
            if "accuracy" in s
            else f"{s['mae']:.2f}   편향 {s['bias']:+.2f}"
        )
        print(f"{s['source']:<11} {s['category']:<4} {s['lead']:<9} {s['n']:>5}  {tail}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect", help="현재 예보를 받아 저장")
    e = sub.add_parser("export", help="실측과 맞춰 학습용 CSV 로 내보내기")
    e.add_argument("asos_dir", type=Path)
    e.add_argument("out", type=Path)
    r = sub.add_parser("report", help="예보 오차 보고")
    r.add_argument("asos_dir", type=Path)
    args = p.parse_args(argv)
    settings = Settings()
    archive = ForecastArchive(archive_path(settings))
    if args.cmd == "collect":
        result = collect(settings, archive, datetime.now(KST))
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["errors"] else 0
    if args.cmd == "export":
        print(f"{export_dataset(archive, args.asos_dir, args.out)}행을 {args.out}에 저장했습니다.")
        return 0
    tmp = Path(args.asos_dir) / "forecast_dataset.tmp.csv"
    export_dataset(archive, args.asos_dir, tmp)
    try:
        _print_report(summarize_errors(tmp))
    finally:
        tmp.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
