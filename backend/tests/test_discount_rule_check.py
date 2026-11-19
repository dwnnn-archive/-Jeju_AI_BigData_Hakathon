from datetime import date

from scripts.discount_rule_check import in_window, is_discount_day, summarize


def test_window_uses_spring_and_autumn_months():
    for month in (3, 4, 5, 9, 10):
        assert in_window(date(2026, month, 1)) and in_window(date(2026, month, 28))
    for month in (1, 2, 6, 7, 8, 11, 12):
        assert not in_window(date(2026, month, 15))


def test_discount_day_needs_weekend_or_holiday_inside_the_window():
    assert is_discount_day(date(2026, 4, 18))  # Saturday in spring
    assert is_discount_day(date(2026, 3, 7))  # Saturday, spring window starts in March
    assert not is_discount_day(date(2026, 4, 20))  # Monday
    assert not is_discount_day(date(2026, 7, 4))  # Saturday outside the seasons


def day(iso, actual, hours=(), risk="NORMAL"):
    return {"date": iso, "actual": actual, "actual_hours": list(hours), "risk": risk}


def test_summarize_counts_days_hours_and_agent_hits():
    days = [
        day("2026-04-18", True, [10, 11, 12], "CAUTION"),  # Saturday, hours overlap 11~14
        day("2026-04-19", True, [9], "NORMAL"),  # Sunday, no overlap
        day("2026-04-20", True, [12, 13], "CRITICAL"),  # Monday: weekday, not covered
        day("2026-04-25", False),  # Saturday, no curtailment
        day("2026-07-04", True, [12], "CAUTION"),  # Saturday outside the seasons
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
