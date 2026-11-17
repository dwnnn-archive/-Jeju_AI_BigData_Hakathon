import csv
from datetime import date

import pytest

from scripts.kpx_demand import load_demand, parse_file, write_csv

HOURS = [f"{h}시" for h in range(1, 25)]


def _write(path, header_date, rows, encoding="cp949", extra_blank_col=False):
    header = [header_date] + HOURS + ([""] if extra_blank_col else [])
    lines = [",".join(header)]
    for d, values in rows:
        cells = [d] + [str(v) if not isinstance(v, str) else v for v in values]
        lines.append(",".join(cells + ([""] if extra_blank_col else [])))
    path.write_bytes("\n".join(lines).encode(encoding))


def _day(first, step=1.0):
    return [first + step * i for i in range(24)]


def test_hour_ending_label_becomes_start_hour_and_blank_extra_column_is_ignored(tmp_path):
    f = tmp_path / "한국전력거래소_시간별 제주전력수요_20230228.csv"
    _write(f, "거래일자", [("2023-01-01", _day(500))], extra_blank_col=True)
    s = parse_file(f)
    assert s[(date(2023, 1, 1), 0)] == 500  # 1시 → 0시
    assert s[(date(2023, 1, 1), 23)] == 523  # 24시 → 23시
    assert len(s) == 24


def test_kwh_values_are_converted_and_commas_are_removed(tmp_path):
    f = tmp_path / "한국전력거래소_시간별 제주전력수요_20230930.csv"
    kwh = _day(650000, 1000)
    _write(f, "날짜", [("2023-05-01", kwh)])
    s = parse_file(f)
    assert s[(date(2023, 5, 1), 0)] == 650.0
    g = tmp_path / "한국전력거래소_시간별 제주전력수요_20240930.csv"
    _write(g, "날짜", [("2024-07-01", ['"1,019.690"'] + _day(700)[1:])], encoding="utf-8-sig")
    assert parse_file(g)[(date(2024, 7, 1), 0)] == pytest.approx(1019.69)


def test_overlap_prefers_file_with_later_end_date_and_union_covers_all_days(tmp_path):
    old = tmp_path / "한국전력거래소_시간별 제주전력수요_20210831.csv"
    new = tmp_path / "한국전력거래소_시간별 제주전력수요_20230228.csv"
    _write(old, "거래일자", [("2021-01-01", _day(600)), ("2021-01-02", _day(610))])
    _write(new, "거래일자", [("2021-01-02", _day(615)), ("2021-01-03", _day(620))])
    s = load_demand(tmp_path)
    assert s[(date(2021, 1, 1), 0)] == 600  # 한쪽에만 있는 날
    assert s[(date(2021, 1, 2), 0)] == 615  # 겹치면 최신 파일 값
    assert s[(date(2021, 1, 3), 0)] == 620
    assert len({k[0] for k in s}) == 3


def test_rejects_file_without_all_hour_columns(tmp_path):
    f = tmp_path / "한국전력거래소_시간별 제주전력수요_20240331.csv"
    f.write_text("날짜,1시,2시\n2024-01-01,500,510\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hour columns"):
        parse_file(f)


def test_write_csv_emits_kst_timestamps(tmp_path):
    out = tmp_path / "o.csv"
    assert write_csv({(date(2024, 5, 31), 5): 612.5}, out) == 1
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows == [{"timestamp": "2024-05-31T05:00:00+09:00", "demand_mwh": "612.5"}]
