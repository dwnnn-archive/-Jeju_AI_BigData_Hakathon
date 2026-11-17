import csv
from datetime import datetime

from app.providers.asos import KST, AsosHour
from scripts.collect_asos import FIELDS, merge, months, write_rows


def test_months_crosses_year_boundary_and_is_inclusive():
    assert list(months("2023-11", "2024-02")) == [(2023, 11), (2023, 12), (2024, 1), (2024, 2)]
    assert list(months("2024-05", "2024-05")) == [(2024, 5)]
    assert list(months("2024-06", "2024-05")) == []


def test_write_rows_blank_for_missing_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "monthly" / "185_2024-05.csv"
    rows = [
        AsosHour(datetime(2024, 5, 1, 0, tzinfo=KST), 185, 6.1, 13.3, None, 4.0),
        AsosHour(datetime(2024, 5, 1, 12, tzinfo=KST), 185, None, 18.0, 500.0, None),
    ]
    write_rows(path, rows)
    got = list(csv.reader(path.open(encoding="utf-8")))
    assert got[0] == FIELDS
    assert got[1] == ["2024-05-01T00:00:00+09:00", "6.1", "13.3", "", "4.0"]
    assert got[2] == ["2024-05-01T12:00:00+09:00", "", "18.0", "500.0", ""]
    assert [p.name for p in path.parent.iterdir()] == ["185_2024-05.csv"]


def test_merge_orders_months_and_skips_missing_ones(tmp_path):
    for ym, hour in (("2024-02", 3), ("2024-01", 5)):
        y, m = map(int, ym.split("-"))
        write_rows(
            tmp_path / "monthly" / f"185_{ym}.csv",
            [AsosHour(datetime(y, m, 1, hour, tzinfo=KST), 185, 1.0, 2.0, None)],
        )
    merge("2024-01", "2024-03", tmp_path)  # 2024-03 파일은 없음
    got = list(csv.reader((tmp_path / "asos_gosan.csv").open(encoding="utf-8")))[1:]
    assert [r[0][:10] for r in got] == ["2024-01-01", "2024-02-01"]
    assert (tmp_path / "asos_jeju.csv").read_text(encoding="utf-8").strip() == ",".join(FIELDS)
