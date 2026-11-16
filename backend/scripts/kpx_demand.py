"""KPX '시간별 제주전력수요' 파일들을 시간별 시계열로 정규화한다.

사용: python -m scripts.kpx_demand <KPX_수요_폴더> <출력.csv>
출력 열: timestamp(KST 시작시각), demand_mwh

파일마다 다른 점을 여기서 흡수한다.
- 구조: 날짜 열(`거래일자` 또는 `날짜`) + `1시`~`24시`. 파일에 따라 빈 열이 하나 더 있다.
- 시간: 1시~24시는 거래시간(종료 시각)이라 1을 빼 0~23(시작 시각)으로 바꾼다.
  KPX 하루전 예측(PSS)과 같은 표기임을 확인했다(예측을 이동하면 오차가 커진다).
- 단위: 2023-09 이전 일부 파일은 kWh, 이후는 MWh다.
  값이 KWH_THRESHOLD보다 크면 kWh로 보고 1000으로 나눈다.
  제주 수요는 100~1,200 MWh 범위라 구분이 안전하다.
- 쉼표: `1,019.690`처럼 천 단위 쉼표가 섞인 값이 있다.
- 인코딩: CP949 또는 UTF-8(BOM).
- 겹치는 기간: 파일 이름 끝의 날짜가 늦은 파일(수정정산이 반영된 최신본)을 우선한다.
"""

import csv
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
KWH_THRESHOLD = 20_000
_DATE_COLS = ("거래일자", "날짜", "일자")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Cannot decode demand CSV")


def _end_date(path: Path) -> str:
    match = re.search(r"(\d{8})", path.stem)
    return match.group(1) if match else "00000000"


def _mwh(raw: str) -> float | None:
    raw = raw.strip().replace(",", "")
    if raw == "":
        return None
    value = float(raw)
    return value / 1000 if value > KWH_THRESHOLD else value


def parse_file(path: Path) -> dict[tuple[date, int], float]:
    """(날짜, 0~23시 시작) → MWh."""
    rows = list(csv.reader(_decode(path.read_bytes()).splitlines()))
    header = [c.strip() for c in rows[0]]
    date_col = next(i for i, c in enumerate(header) if c in _DATE_COLS)
    hour_cols = {int(c[:-1]): i for i, c in enumerate(header) if re.fullmatch(r"\d{1,2}시", c)}
    if set(hour_cols) != set(range(1, 25)):
        raise ValueError(f"{path.name}: expected hour columns 1시..24시")
    out: dict[tuple[date, int], float] = {}
    for r in rows[1:]:
        if not r or not r[date_col].strip():
            continue
        d = date.fromisoformat(r[date_col].strip())
        for hour_ending, idx in hour_cols.items():
            value = _mwh(r[idx]) if idx < len(r) else None
            if value is not None:
                out[(d, hour_ending - 1)] = value
    return out


def load_demand(directory: Path) -> dict[tuple[date, int], float]:
    files = sorted(directory.glob("*시간별 제주전력수요*.csv"), key=_end_date, reverse=True)
    merged: dict[tuple[date, int], float] = {}
    for path in files:  # 최신 파일부터 채우고, 이미 있는 키는 덮어쓰지 않는다
        for key, value in parse_file(path).items():
            merged.setdefault(key, value)
    return merged


def write_csv(series: dict[tuple[date, int], float], out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "demand_mwh"])
        for (d, h), v in sorted(series.items()):
            w.writerow([datetime(d.year, d.month, d.day, h, tzinfo=KST).isoformat(), v])
    return len(series)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    n = write_csv(load_demand(Path(argv[1])), Path(argv[2]))
    print(f"wrote {n} hourly rows to {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
