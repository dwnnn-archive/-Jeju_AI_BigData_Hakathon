from datetime import date

from scripts.discount_rule_check import in_window, is_discount_day, summarize


def test_window_uses_2026_season_dates():
    assert in_window(date(2026, 4, 18)) and in_window(date(2026, 5, 31))
    assert not in_window(date(2026, 4, 17)) and not in_window(date(2026, 6, 1))
    assert in_window(date(2026, 9, 5)) and in_window(date(2026, 10, 31))
    assert not in_window(date(2026, 9, 4)) and not in_window(date(2026, 11, 1))


def test_discount_day_needs_weekend_or_holiday_inside_the_window():
    assert is_discount_day(date(2026, 4, 18))  # Saturday
    assert not is_discount_day(date(2026, 4, 20))  # Monday
    assert not is_discount_day(date(2026, 3, 7))  # Saturday outside the window


def day(iso, actual, hours=(), risk="NORMAL"):
    return {"date": iso, "actual": actual, "actual_hours": list(hours), "risk": risk}


def test_summarize_counts_days_hours_and_agent_hits():
    days = [
        day("2026-04-18", True, [10, 11, 12], "CAUTION"),  # Saturday, hours overlap 11~14
        day("2026-04-19", True, [9], "NORMAL"),  # Sunday, no overlap
        day("2026-04-20", True, [12, 13], "CRITICAL"),  # Monday: weekday, not covered
        day("2026-04-25", False),  # Saturday, no curtailment
        day("2026-03-07", True, [12], "CAUTION"),  # Saturday outside the window
    ]
    s = summarize(days)
    assert s["curtailed_days"] == 4
    assert s["curtailed_outside_window"] == 1
    assert s["curtailed_weekdays"] == 1
    assert s["discount_days"] == 3
    assert s["discount_days_with_curtailment"] == 2
    assert s["curtailed_on_discount_days"] == 2
    assert s["curtailed_overlapping_discount_hours"] == 1
    assert s["curtailed_hours_total"] == 7
    assert s["curtailed_hours_covered"] == 2
    assert s["agent_flagged_days"] == 3
