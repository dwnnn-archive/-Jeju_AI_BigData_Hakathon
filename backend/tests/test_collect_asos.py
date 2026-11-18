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


def test_collect_current_month_stops_at_yesterday_and_refetches(tmp_path, monkeypatch):
    from datetime import timedelta

    import pytest
    from pydantic import SecretStr

    from scripts import collect_asos

    today = datetime.now(KST)
    if today.day == 1:
        pytest.skip("on the 1st the current month has no finished day yet")
    calls = []

    class FakeProvider:
        def __init__(self, key, client):
            pass

        def fetch(self, stn, first, last):
            calls.append((first, last))
            return [AsosHour(first, stn, 1.0, 2.0, None, None)]

    class FakeSettings:
        asos_api_key = SecretStr("k")

    monkeypatch.setattr(collect_asos, "AsosProvider", FakeProvider)
    monkeypatch.setattr(collect_asos, "Settings", FakeSettings)
    monkeypatch.setattr(collect_asos, "JEJU_STATIONS", {"gosan": 185})
    monkeypatch.setattr(collect_asos.time, "sleep", lambda s: None)
    ym = f"{today.year}-{today.month:02d}"

    collect_asos.collect(ym, ym, tmp_path, pause=0)
    collect_asos.collect(ym, ym, tmp_path, pause=0)  # unfinished month is fetched again

    assert len(calls) == 2
    yesterday = (today - timedelta(days=1)).date()
    assert all(last.date() == yesterday and last.hour == 23 for _, last in calls)


def test_covers_month_detects_unfinished_month_file(tmp_path):
    from scripts.collect_asos import covers_month

    path = tmp_path / "185_2026-10.csv"
    last = datetime(2026, 10, 31, 23, tzinfo=KST)
    rows = [AsosHour(datetime(2026, 10, 30, 23, tzinfo=KST), 185, 1.0, 2.0, None, None)]
    write_rows(path, rows)
    assert not covers_month(path, last)  # ends on the 30th: month was unfinished when saved
    end = AsosHour(datetime(2026, 10, 31, 22, tzinfo=KST), 185, 1.0, 2.0, None, None)
    write_rows(path, [*rows, end])
    assert covers_month(path, last)
    assert not covers_month(tmp_path / "missing.csv", last)


def test_recent_range_includes_previous_month_at_month_start():
    from scripts.collect_asos import recent_range

    assert recent_range(datetime(2026, 12, 1, 3, tzinfo=KST)) == ("2026-10", "2026-11")
    assert recent_range(datetime(2026, 12, 2, 3, tzinfo=KST)) == ("2026-11", "2026-12")
    assert recent_range(datetime(2027, 1, 2, 3, tzinfo=KST)) == ("2026-12", "2027-01")
