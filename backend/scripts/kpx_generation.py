"""KPX '지역별 시간별 태양광(및 풍력) 발전량' 파일을 제주 시간별 시계열로 정규화한다.

사용:
    python -m scripts.kpx_generation <KPX_CSV_폴더> <출력.csv>

출력 열: timestamp(KST 시작시각), wind_mwh, solar_mwh, wind_usable
배경과 검증 결과는 docs/guides/data-acquisition.md 참고.

파일마다 다른 점을 여기서 흡수한다.
- 구조: 연료원 열이 있는 long, 태양광/풍력 열이 나란한 wide, 태양광만 있는 형태.
- 시간: '시간' 열은 0~23(시작 시각), '거래시간' 열은 1~24(종료 시각)이라 1을 뺀다.
- 단위: 열 이름이 '발전량'(단위 없음)인 2018~2021 파일은 kWh라 1000으로 나눈다.
- 지역명: 제주도/제주/제주특별자치도를 같은 대상으로 본다.
- 겹치는 기간은 20230228 파일을 우선한다(겹침 비교에서 파일 간 값이 일치).
"""

import csv
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
JEJU = {"제주도", "제주", "제주특별자치도"}
# 2024-06 이후 제주 풍력은 KPX 집계가 급락한다(원본 API도 동일). 학습 정답으로 쓰지 않는다.
WIND_USABLE_END = date(2024, 5, 31)
_DATE_COLS = ("거래일자", "거래일")
_REGION_COLS = ("지역", "지역명", "지역세부구분")


def _rank(name: str) -> int:
    if "20230228" in name:
        return 0
    return 1 if re.search(r"20171231|20201231", name) else 2


def _read(path: Path) -> list[dict[str, str]]:
    for enc in ("cp949", "utf-8-sig"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot decode {path.name}")
    rows = list(csv.reader(text.splitlines()))
    header = [c.strip() for c in rows[0]]
    return [dict(zip(header, (v.strip() for v in r), strict=False)) for r in rows[1:] if r]


def _num(raw: str | None) -> float | None:
    if raw is None or raw.strip() == "":
        return None
    return float(raw)


def _pick(row: dict, names: tuple[str, ...]) -> str:
    return next(row[n] for n in names if n in row)


def parse_file(path: Path) -> dict[tuple[date, int], dict[str, float | None]]:
    """(날짜, 0~23시) → {'wind': MWh, 'solar': MWh}. 제주만 반환한다."""
    rows = _read(path)
    if not rows:
        return {}
    cols = set(rows[0])
    out: dict[tuple[date, int], dict[str, float | None]] = {}
    hour_col = "거래시간" if "거래시간" in cols else "시간"
    base = 1 if hour_col == "거래시간" else 0
    fuel_col = "연료원" in cols
    solar_cols = [c for c in cols if "태양광" in c and ("MWh" in c or "Mwh" in c)]
    wind_cols = [c for c in cols if "풍력" in c and ("MWh" in c or "Mwh" in c)]
    value_col = next(
        (c for c in ("전력거래량(MWh)", "발전량(MWh)", "전력거래량", "발전량") if c in cols), None
    )
    kwh = value_col == "발전량"
    for r in rows:
        if _pick(r, _REGION_COLS) not in JEJU:
            continue
        key = (date.fromisoformat(_pick(r, _DATE_COLS)), int(r[hour_col]) - base)
        slot = out.setdefault(key, {})
        if solar_cols and wind_cols:  # wide
            slot["solar"], slot["wind"] = _num(r[solar_cols[0]]), _num(r[wind_cols[0]])
            continue
        fuel = {"태양광": "solar", "풍력": "wind"}[r["연료원"]] if fuel_col else "solar"
        v = _num(r[value_col])
        slot[fuel] = v / 1000 if (kwh and v is not None) else v
    return out


def load_jeju(directory: Path) -> dict[tuple[date, int], dict[str, float | None]]:
    merged: dict[tuple[date, int], dict[str, float | None]] = {}
    for path in sorted(directory.glob("*.csv"), key=lambda p: (_rank(p.name), p.name)):
        for key, vals in parse_file(path).items():
            slot = merged.setdefault(key, {})
            for fuel, v in vals.items():
                if slot.get(fuel) is None and v is not None:
                    slot[fuel] = v
    return merged


def write_csv(series: dict[tuple[date, int], dict[str, float | None]], out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "wind_mwh", "solar_mwh", "wind_usable"])
        for (d, h), v in sorted(series.items()):
            ts = datetime(d.year, d.month, d.day, h, tzinfo=KST).isoformat()
            wind, solar = v.get("wind"), v.get("solar")
            usable = wind is not None and d <= WIND_USABLE_END
            w.writerow(
                [ts, "" if wind is None else wind, "" if solar is None else solar, int(usable)]
            )
    return len(series)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    n = write_csv(load_jeju(Path(argv[1])), Path(argv[2]))
    print(f"wrote {n} hourly rows to {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
