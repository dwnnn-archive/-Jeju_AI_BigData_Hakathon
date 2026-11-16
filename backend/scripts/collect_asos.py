"""제주권 ASOS 시간자료를 기간별로 내려받아 CSV로 저장한다 (학습용 과거 실측 기상).

사용 (backend/ 에서, backend/.env 에 ASOS_API_KEY 필요):
    python -m scripts.collect_asos 2017-01 2024-05 runtime/asos

- 지점: 제주(184) 고산(185) 성산(188) 서귀포(189), 월 단위로 호출한다.
- 월별 파일이 이미 있으면 건너뛰므로 중단 후 같은 명령으로 이어받을 수 있다.
- 병합 결과: <출력폴더>/asos_<지점>.csv (timestamp, wind_ms, temperature_c, irradiance_wm2).
  값이 없거나 품질플래그가 정상이 아닌 칸은 빈 칸이다. 일사량은 낮에만 값이 있다.
- 출력 폴더는 Git에 올리지 않는다(runtime/ 은 .gitignore 대상).
"""

import calendar
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import Settings
from app.providers.asos import JEJU_STATIONS, KST, AsosHour, AsosProvider

FIELDS = ["timestamp", "wind_ms", "temperature_c", "irradiance_wm2"]


def months(start: str, end: str):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _cell(v: float | None) -> str:
    return "" if v is None else repr(round(v, 6))


def write_rows(path: Path, rows: list[AsosHour]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for r in rows:
            w.writerow(
                [
                    r.timestamp.isoformat(),
                    _cell(r.wind_ms),
                    _cell(r.temperature_c),
                    _cell(r.irradiance_wm2),
                ]
            )
    tmp.replace(path)  # 쓰기 도중 중단돼도 불완전한 월 파일이 남지 않는다


def collect(start: str, end: str, out: Path, pause: float = 0.3, retries: int = 3) -> None:
    key = Settings().asos_api_key
    if not key:
        raise SystemExit("ASOS_API_KEY가 backend/.env에 없습니다.")
    done = skipped = 0
    with httpx.Client(timeout=60) as client:
        provider = AsosProvider(key.get_secret_value(), client)
        for name, stn in JEJU_STATIONS.items():
            for y, m in months(start, end):
                path = out / "monthly" / f"{stn}_{y}-{m:02d}.csv"
                if path.exists():
                    skipped += 1
                    continue
                first = datetime(y, m, 1, 0, tzinfo=KST)
                last = datetime(y, m, calendar.monthrange(y, m)[1], 23, tzinfo=KST)
                for attempt in range(1, retries + 1):
                    try:
                        write_rows(path, provider.fetch(stn, first, last))
                        break
                    except (httpx.HTTPError, ValueError) as e:
                        # 메시지에 키가 담긴 URL이 있을 수 있어 종류만 출력한다.
                        print(f"  {name} {y}-{m:02d} 실패 {attempt}/{retries}: {type(e).__name__}")
                        if attempt == retries:
                            # from None: 원인 예외의 URL(키 포함)이 트레이스백에 노출되지 않게 한다.
                            raise SystemExit(
                                f"{name} {y}-{m:02d} 수집 실패. 같은 명령으로 이어받으세요."
                            ) from None
                        time.sleep(2 * attempt)
                done += 1
                print(f"{name}({stn}) {y}-{m:02d} 저장", flush=True)
                time.sleep(pause)
    print(f"수집 {done}건, 기존 {skipped}건 건너뜀")
    merge(start, end, out)


def merge(start: str, end: str, out: Path) -> None:
    for name, stn in JEJU_STATIONS.items():
        rows = []
        for y, m in months(start, end):
            p = out / "monthly" / f"{stn}_{y}-{m:02d}.csv"
            if p.exists():
                with p.open(encoding="utf-8") as f:
                    rows += list(csv.reader(f))[1:]
        rows.sort()
        target = out / f"asos_{name}.csv"
        with target.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            w.writerows(rows)
        print(f"병합 {target.name}: {len(rows)}행")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    collect(argv[1], argv[2], Path(argv[3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
