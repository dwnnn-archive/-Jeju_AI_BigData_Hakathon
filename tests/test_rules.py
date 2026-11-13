from datetime import date

import pytest
from pydantic import ValidationError

from backend.domain.rules import allocate, evaluate
from backend.domain.schemas import AnalysisRequest, EnergyHour, validate_day

DAY = date(2026, 11, 14)


def series(value):
    return [EnergyHour(date=DAY, hour=h, mwh=value) for h in range(24)]


@pytest.mark.parametrize(
    "surplus,risk",
    [
        (0, "NORMAL"),
        (149.9, "NORMAL"),
        (150, "CAUTION"),
        (199.9, "CAUTION"),
        (200, "CRITICAL"),
        (230, "CRITICAL"),
    ],
)
def test_risk_boundaries(surplus, risk):
    result = evaluate(series(surplus + 100), list(reversed(series(100))), DAY)
    assert result["risk"] == risk
    assert result["peak_surplus_mwh"] == pytest.approx(surplus)
    assert len(result["hourly"]) == 24


def test_deficit_is_not_negative_surplus():
    assert evaluate(series(0), series(100), DAY)["peak_surplus_mwh"] == 0


def test_peak_allocation_conserves_energy_and_reports_residual():
    result = allocate(230)
    assert result["allocated_mwh"] == {"bess": 70, "vpp": 30, "p2x": 30, "ev": 40}
    assert result["absorbed_mwh"] == 170
    assert result["residual_mwh"] == 60
    assert result["absorption_pct"] == pytest.approx(170 / 230 * 100)
    assert result["hydrogen_kg"] == 390


def test_priority_and_zero_allocation():
    assert allocate(80)["allocated_mwh"] == {"bess": 70, "vpp": 10, "p2x": 0, "ev": 0}
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
