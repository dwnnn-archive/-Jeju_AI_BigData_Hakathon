from datetime import date

import pytest

from scripts.evaluate_pipeline import day_weather, summarize


def _day(risk, actual, hour=12, hours=(12,), surplus=50.0, wind_max=40.0, wind_total=100.0):
    return {
        "date": date(2024, 3, 1),
        "risk": risk,
        "peak_hour": hour,
        "peak_surplus_mwh": surplus,
        "actual": actual,
        "actual_hours": set(hours) if actual else set(),
        "wind_max_mwh": wind_max if actual else 0.0,
        "wind_total_mwh": wind_total if actual else 0.0,
    }


def test_summary_counts_precision_recall_and_false_alarms_per_level():
    days = [
        _day("CRITICAL", True),
        _day("CRITICAL", True),
        _day("CRITICAL", False),
        _day("CAUTION", True),
        _day("CAUTION", False),
        _day("NORMAL", True),  # 놓친 출력제한일
        _day("NORMAL", False),
        _day("NORMAL", False),
    ]
    out = summarize(days)
    assert out["days"] == 8 and out["actual_curtailment_days"] == 4
    assert out["by_predicted_level"]["CRITICAL"]["precision"] == pytest.approx(2 / 3)
    assert out["by_predicted_level"]["NORMAL"]["actual_curtailment_days"] == 1
    assert out["caution_or_above"]["recall"] == pytest.approx(3 / 4)
    assert out["caution_or_above"]["precision"] == pytest.approx(3 / 5)
    assert out["caution_or_above"]["false_alarm_days"] == 2
    assert out["critical"]["recall"] == pytest.approx(2 / 4)


def test_peak_hour_distance_only_counts_caught_curtailment_days():
    days = [
        _day("CRITICAL", True, hour=12, hours=(11, 12, 13)),  # 거리 0
        _day("CAUTION", True, hour=9, hours=(12,)),  # 거리 3
        _day("NORMAL", True, hour=12, hours=(12,)),  # 놓친 날은 제외
    ]
    d = summarize(days)["peak_hour_distance"]
    assert d["days"] == 2 and d["within_1h"] == 0.5 and d["within_2h"] == 0.5


def test_magnitude_and_allocation_capacity_summary():
    days = [
        _day("CRITICAL", True, surplus=60, wind_max=30, wind_total=90),
        _day("CRITICAL", True, surplus=120, wind_max=60, wind_total=180),
        _day("CRITICAL", True, surplus=180, wind_max=90, wind_total=270),
        _day("NORMAL", False, surplus=0),
    ]
    out = summarize(days)
    mag = out["magnitude_on_wind_curtailment_days"]
    assert mag["days"] == 3 and mag["mean_predicted_peak_surplus_mwh"] == 120
    assert mag["corr_with_max_hourly"] == pytest.approx(1.0)
    assert out["allocation"]["flagged_days"] == 3
    assert out["allocation"]["capacity_mwh"] == pytest.approx(137.7)
    assert out["allocation"]["within_capacity"] == pytest.approx(2 / 3)


def test_empty_groups_do_not_divide_by_zero():
    out = summarize([_day("NORMAL", False)])
    assert (
        out["caution_or_above"]["recall"] is None and out["caution_or_above"]["precision"] is None
    )
    assert out["magnitude_on_wind_curtailment_days"]["corr_with_max_hourly"] is None


def _obs(**over):
    row = {"wind_ms": 5.0, "temperature_c": 10.0, "cloud_tenths": 2.0}
    row.update(over)
    return row


def test_day_weather_needs_all_24_hours_and_fills_cloud_for_three_hours_only():
    d = date(2024, 3, 1)
    gosan = {(d, h): _obs() for h in range(24)}
    jeju = {(d, h): {"temperature_c": 9.0} for h in range(24)}
    gen, dem = day_weather(d, gosan, jeju)
    assert len(gen) == len(dem) == 24 and gen[0].sky == 1 and dem[0].temperature_c == 9.0

    gosan[(d, 4)] = _obs(cloud_tenths=None)  # 직전 관측(3시)을 이어 씀
    assert day_weather(d, gosan, jeju) is not None
    for h in (4, 5, 6, 7):  # 4시간 연속 빈 값이면 마지막 시간은 이어 쓸 수 없다
        gosan[(d, h)] = _obs(cloud_tenths=None)
    assert day_weather(d, gosan, jeju) is None

    gosan = {(d, h): _obs() for h in range(24)}
    del jeju[(d, 7)]  # 수요 모델용 기온이 한 시간이라도 없으면 그 날은 건너뜀
    assert day_weather(d, gosan, jeju) is None


def test_allocation_sensitivity_share_within_capacity():
    from scripts.allocation_sensitivity import share_within

    days = [{"peak_surplus_mwh": 60}, {"peak_surplus_mwh": 120}, {"peak_surplus_mwh": 180}]
    within, frac, absorbed = share_within(days, lambda d: 100)
    assert within == 1 and frac == pytest.approx(1 / 3)
    assert absorbed == pytest.approx((60 + 100 + 100) / 360)
