from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.rules import (
    BOUNDARY_RATIO,
    CRITICAL_RATIO,
    WARNING_RATIO,
    allocate,
    evaluate,
    is_boundary,
    risk_level,
)
from app.domain.schemas import AnalysisRequest, EnergyHour, validate_day

DAY = date(2026, 11, 14)


def series(value):
    return [EnergyHour(date=DAY, hour=h, mwh=value) for h in range(24)]


@pytest.mark.parametrize(
    "generation,risk",
    [
        (0, "NORMAL"),
        (39.9, "NORMAL"),  # 비율 0.399
        (40, "CAUTION"),  # 비율 0.40 (경계선)
        (44.9, "CAUTION"),
        (45, "CRITICAL"),  # 비율 0.45
        (73, "CRITICAL"),
    ],
)
def test_risk_thresholds_use_generation_to_demand_ratio(generation, risk):
    result = evaluate(series(generation), series(100), DAY)
    assert result["risk"] == risk
    assert result["peak_ratio"] == pytest.approx(generation / 100)
    # 잉여(흡수 대상)는 수요의 40% 경계선을 넘는 발전량이다.
    assert result["peak_surplus_mwh"] == pytest.approx(max(0.0, generation - 40))
    assert len(result["hourly"]) == 24
    assert result["thresholds"]["warning_ratio"] == WARNING_RATIO


def test_real_curtailment_scale_is_detected_where_the_old_rule_saw_nothing():
    # 수요 700 MWh, 발전량 320 MWh: 발전량이 수요보다 작아 옛 규칙(발전량 - 수요)은 잉여 0이었다.
    # 제주 출력제한은 수요의 절반에 못 미쳐도 걸리므로 새 규칙은 이를 CRITICAL로 본다.
    result = evaluate(series(320), series(700), DAY)
    assert max(0.0, 320 - 700) == 0  # 옛 규칙
    assert result["risk"] == "CRITICAL"
    assert result["peak_surplus_mwh"] == pytest.approx(320 - 0.40 * 700)


def test_peak_hour_is_the_hour_with_the_largest_surplus_and_risk_is_per_hour():
    generation = series(100)
    generation[3] = generation[3].model_copy(update={"mwh": 400})
    result = evaluate(generation, series(700), DAY)
    assert result["peak_hour"] == 3
    assert result["hourly"][3]["risk"] == "CRITICAL" and result["hourly"][0]["risk"] == "NORMAL"
    assert result["hourly"][3]["ratio"] == pytest.approx(400 / 700)


def test_boundary_band_is_just_below_the_critical_ratio():
    assert is_boundary(BOUNDARY_RATIO) and is_boundary(CRITICAL_RATIO)
    assert not is_boundary(0.42) and not is_boundary(0.451)
    assert BOUNDARY_RATIO < CRITICAL_RATIO and risk_level(0.44) == "CAUTION"


def test_non_positive_demand_is_rejected():
    with pytest.raises(ValueError, match="Demand"):
        evaluate(series(10), series(0), DAY)


def test_deficit_is_not_negative_surplus():
    assert evaluate(series(0), series(100), DAY)["peak_surplus_mwh"] == 0


def test_peak_allocation_conserves_energy_and_reports_residual():
    result = allocate(230)
    assert result["allocated_mwh"] == pytest.approx({"bess": 37.7, "vpp": 30, "p2x": 3.3, "ev": 40})
    assert result["absorbed_mwh"] == pytest.approx(111.0)
    assert result["residual_mwh"] == pytest.approx(119.0)
    assert result["absorbed_mwh"] + result["residual_mwh"] == pytest.approx(230)
    assert result["absorption_pct"] == pytest.approx(111.0 / 230 * 100)
    assert result["hydrogen_kg"] == pytest.approx(42.9)


def test_priority_and_zero_allocation():
    assigned = allocate(80)["allocated_mwh"]
    assert assigned == pytest.approx({"bess": 37.7, "vpp": 30, "p2x": 3.3, "ev": 9.0})
    assert allocate(0)["absorption_pct"] == 0


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_energy_is_rejected(value):
    with pytest.raises(ValidationError):
        EnergyHour(date=DAY, hour=0, mwh=value)
    with pytest.raises(ValueError):
        allocate(value)


def test_duplicate_missing_and_wrong_date_are_rejected():
    for rows in [
        series(1)[:-1],
        series(1)[:-1] + [series(1)[0]],
        [r.model_copy(update={"date": date(2026, 11, 15)}) for r in series(1)],
    ]:
        with pytest.raises(ValueError):
            validate_day(rows, DAY)


def test_unknown_input_fields_and_bad_coordinates_cannot_silently_pass():
    with pytest.raises(ValidationError):
        AnalysisRequest(date=DAY, scenario="typo")
    with pytest.raises(ValidationError):
        AnalysisRequest(date=DAY, region="seoul")
    with pytest.raises(ValidationError):
        AnalysisRequest(date=DAY, forced_surplus=999)


def test_notification_prints_allocation_without_long_decimals():
    from app.tools.tool6_notification import _allocated_line

    line = _allocated_line({"bess": 37.7, "vpp": 30, "p2x": 30.0, "ev": 108.99402234045442})
    assert line == "BESS 37.7 / VPP 30 / P2X 30 / EV 109"
    assert _allocated_line({"bess": 0.0, "ev": 12.34}) == "BESS 0 / EV 12.3"
