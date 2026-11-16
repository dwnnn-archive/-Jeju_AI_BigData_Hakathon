"""KPX 제주 발전량과 ASOS 실측 기상을 시간 단위로 합쳐 학습용 CSV를 만든다.

사용 (backend/ 에서):
    python -m scripts.build_training_csv <KPX_CSV_폴더> <ASOS_폴더> <출력.csv> [--station gosan]

선행: scripts.kpx_generation 이 읽을 수 있는 KPX 원본 폴더, scripts.collect_asos 가 만든 ASOS 폴더.
출력 열: timestamp, wind_mwh, solar_mwh, wind_usable, wind_ms, temperature_c,
         cloud_tenths, sky, cloud_filled, wind_curtailed_mwh, solar_curtailed
- wind_usable: 풍력 정답으로 쓸 수 있는 구간 표시(2024-05-31까지).
  이후는 KPX 집계가 급락해 제외한다.
- sky: 전운량을 예보의 하늘상태(1/3/4)로 바꾼 값. 전운량이 비는 시간은 직전 관측을
  최대 MAX_FILL_HOURS 시간까지 이어 쓰며 그 경우 cloud_filled=1 이다.
- 기상 열은 한 지점(기본 고산 185)의 값이다. 추론에서도 같은 지점의 예보 격자를 쓴다.
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path

from app.providers.asos import JEJU_STATIONS
from app.tools.jeju_model import sky_from_cloud_tenths
from scripts.kpx_curtailment import load_jeju_curtailment
from scripts.kpx_generation import KST, WIND_USABLE_END, load_jeju

MAX_FILL_HOURS = 3
FIELDS = [
    "timestamp",
    "wind_mwh",
    "solar_mwh",
    "wind_usable",
    "wind_ms",
    "temperature_c",
    "cloud_tenths",
    "sky",
    "cloud_filled",
    "wind_curtailed_mwh",
    "solar_curtailed",
]


def read_asos(path: Path) -> dict[datetime, dict[str, float | None]]:
    out: dict[datetime, dict[str, float | None]] = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[datetime.fromisoformat(r["timestamp"])] = {
                k: (float(r[k]) if r[k] != "" else None)
                for k in ("wind_ms", "temperature_c", "cloud_tenths")
            }
    return out


def build(
    kpx_dir: Path,
    asos_dir: Path,
    out: Path,
    station: str = "gosan",
    curtailment: Path | None = None,
) -> dict[str, int]:
    if station not in JEJU_STATIONS:
        raise ValueError(f"Unknown station: {station}")
    kpx = load_jeju(kpx_dir)
    asos = read_asos(asos_dir / f"asos_{station}.csv")
    # 출력제어 이력을 주면 제어가 없던 시간은 0, 주지 않으면 빈 칸("알 수 없음")으로 둔다.
    curt_wind, curt_solar = load_jeju_curtailment(curtailment) if curtailment else ({}, {})
    stats = {"rows": 0, "wind_rows": 0, "solar_rows": 0, "cloud_filled": 0, "no_weather": 0}
    last_cloud: tuple[datetime, float] | None = None
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for (d, h), v in sorted(kpx.items()):
            ts = datetime(d.year, d.month, d.day, h, tzinfo=KST)
            wx = asos.get(ts)
            if wx is None:
                stats["no_weather"] += 1
                continue
            cloud, filled = wx["cloud_tenths"], 0
            if cloud is not None:
                last_cloud = (ts, cloud)
            elif last_cloud and (ts - last_cloud[0]).total_seconds() <= MAX_FILL_HOURS * 3600:
                cloud, filled = last_cloud[1], 1
            sky = "" if cloud is None else sky_from_cloud_tenths(cloud)
            wind, solar = v.get("wind"), v.get("solar")
            usable = int(wind is not None and d <= WIND_USABLE_END)
            w.writerow(
                [
                    ts.isoformat(),
                    "" if wind is None else wind,
                    "" if solar is None else solar,
                    usable,
                    "" if wx["wind_ms"] is None else wx["wind_ms"],
                    "" if wx["temperature_c"] is None else wx["temperature_c"],
                    "" if cloud is None else cloud,
                    sky,
                    filled,
                    "" if curtailment is None else curt_wind.get((d, h), 0.0),
                    "" if curtailment is None else int((d, h) in curt_solar),
                ]
            )
            stats["rows"] += 1
            stats["wind_rows"] += usable
            stats["solar_rows"] += int(solar is not None)
            stats["cloud_filled"] += filled
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("kpx_dir", type=Path)
    p.add_argument("asos_dir", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--station", default="gosan", choices=sorted(JEJU_STATIONS))
    p.add_argument(
        "--curtailment",
        type=Path,
        help="KPX 제주 출력제어 이력(zip 또는 폴더). 주면 제어 열을 채운다.",
    )
    a = p.parse_args()
    print(build(a.kpx_dir, a.asos_dir, a.out, a.station, a.curtailment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
