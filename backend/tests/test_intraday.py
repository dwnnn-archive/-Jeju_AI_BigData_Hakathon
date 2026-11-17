from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.core.config import Settings
from app.domain.rules import evaluate
from app.domain.schemas import AnalysisRequest, EnergyHour, WeatherHour
from app.providers.kma_nowcast import HourObs
from app.tools.bundle import ToolBundle
from app.tools.intraday import blend_weather, previous_evening_base

KST = ZoneInfo("Asia/Seoul")
TARGET = date(2026, 11, 17)


def _day_ahead(wind=3.0):
    return [
        WeatherHour(date=TARGET, hour=h, wind_ms=wind, temperature_c=10, sky=1, irradiance_wm2=0)
        for h in range(24)
    ]


def test_previous_evening_base_is_23h_of_the_day_before():
    assert previous_evening_base(date(2026, 11, 17)) == ("20261116", "2300")
    assert previous_evening_base(date(2026, 3, 1)) == ("20260228", "2300")


def test_blend_overlays_nowcast_and_ultra_only_for_their_hours():
    ultra = [HourObs(TARGET, h, 9.0, 12.0, 4) for h in range(8, 14)]
    ultra.append(HourObs(date(2026, 11, 18), 0, 99.0, 99.0, 1))  # 다음 날 예보는 무시
    obs = HourObs(TARGET, 7, 2.0, 9.0)  # 실황에는 하늘상태가 없다
    rows, sources = blend_weather(_day_ahead(), obs, ultra, TARGET)
    assert [r.hour for r in rows] == list(range(24))
    assert (
        sources[7] == "nowcast" and rows[7].wind_ms == 2.0 and rows[7].sky == 1
    )  # 하늘은 하루 전 값
    assert all(sources[h] == "ultra" for h in range(8, 14))
    assert rows[10].wind_ms == 9.0 and rows[10].temperature_c == 12.0 and rows[10].sky == 4
    assert rows[10].irradiance_wm2 > 0  # 하늘상태가 바뀌면 일사량 추정도 다시 계산
    assert sources[0] == "day_ahead" and rows[0].wind_ms == 3.0
    assert sources[14] == "day_ahead" and rows[23].wind_ms == 3.0
    assert len(sources) == 24 and "99.0" not in {str(r.wind_ms) for r in rows}


def test_nowcast_wins_over_ultra_for_the_current_hour():
    ultra = [HourObs(TARGET, 7, 5.0, 11.0, 3)]
    rows, sources = blend_weather(_day_ahead(), HourObs(TARGET, 7, 2.0, 9.0), ultra, TARGET)
    assert sources[7] == "nowcast" and rows[7].wind_ms == 2.0
    assert rows[7].sky == 3  # 하늘상태는 초단기예보 값을 유지


def test_observation_for_another_date_is_ignored():
    rows, sources = blend_weather(
        _day_ahead(), HourObs(date(2026, 11, 16), 7, 1.0, 1.0), [], TARGET
    )
    assert set(sources.values()) == {"day_ahead"} and rows[7].wind_ms == 3.0


def _series(value, hour_values=None):
    values = {h: value for h in range(24)} | (hour_values or {})
    return [EnergyHour(date=TARGET, hour=h, mwh=values[h]) for h in range(24)]


def test_from_hour_ignores_hours_that_already_passed():
    generation = _series(100, {3: 400})  # 새벽 3시에만 높음
    demand = _series(700)
    whole = evaluate(generation, demand, TARGET)
    later = evaluate(generation, demand, TARGET, from_hour=8)
    assert whole["risk"] == "CRITICAL" and whole["peak_hour"] == 3 and whole["from_hour"] == 0
    assert later["risk"] == "NORMAL" and later["peak_hour"] >= 8 and later["from_hour"] == 8
    assert len(later["hourly"]) == 24  # 표에는 24시간 모두 남는다
    assert later["hourly"][3]["risk"] == "CRITICAL"
    for bad in (-1, 24):
        with pytest.raises(ValueError, match="from_hour"):
            evaluate(generation, demand, TARGET, from_hour=bad)


class _Model:
    def __init__(self, per_wind):
        self.per_wind = per_wind

    def predict(self, weather):
        return [
            EnergyHour(date=w.date, hour=w.hour, mwh=w.wind_ms * self.per_wind) for w in weather
        ]


class _Demand:
    def predict(self, weather):
        return [EnergyHour(date=w.date, hour=w.hour, mwh=700) for w in weather]


def _bundle(monkeypatch, ultra_wind=9.0, seen=None):
    bundle = ToolBundle(
        Settings(_env_file=None, jeju_model_dir=Path("g"), jeju_demand_model_dir=Path("d"))
    )
    monkeypatch.setattr(bundle, "_load_generation_model", lambda: _Model(50))  # 풍속 1 m/s당 50 MWh
    monkeypatch.setattr(bundle, "_load_demand_model", lambda: _Demand())

    def day_ahead(request, base=None):
        if seen is not None:
            seen.append(base)
        return _day_ahead(3.0)  # 비율 150/700 = 0.21 → NORMAL

    monkeypatch.setattr(bundle, "_gosan_weather", day_ahead)
    monkeypatch.setattr(bundle, "_jeju_city_weather", day_ahead)
    ultra = [HourObs(TARGET, h, ultra_wind, 10.0, 1) for h in range(8, 14)]
    monkeypatch.setattr(
        bundle, "_nowcast", lambda grid, now: (HourObs(TARGET, 7, 3.0, 10.0), ultra)
    )
    return bundle


def test_intraday_check_turns_a_normal_day_into_a_warning_when_ultra_short_is_windier(monkeypatch):
    seen = []
    bundle = _bundle(monkeypatch, seen=seen)
    request = AnalysisRequest(date=TARGET, region="jeju", mode="live")
    now = datetime(2026, 11, 17, 7, 45, tzinfo=KST)
    out = bundle.intraday_check(request, now)
    # 하루 전 예보만으로는 정상(비율 0.21), 초단기예보는 풍속 9 m/s(450/700=0.64)라 CRITICAL
    assert evaluate(_series(150), _series(700), TARGET)["risk"] == "NORMAL"
    assert out["result"]["risk"] == "CRITICAL" and out["result"]["from_hour"] == 7
    assert out["result"]["peak_ratio"] == pytest.approx(450 / 700)
    assert seen[0] == ("20261116", "2300")  # 하루 전 입력은 전날 23시 발표분
    inputs = out["inputs"]
    assert inputs["day_ahead_base"] == ["20261116", "2300"] and inputs["from_hour"] == 7
    assert inputs["sources"]["7"] == "nowcast" and inputs["sources"]["10"] == "ultra"
    assert inputs["sources"]["20"] == "day_ahead"
    assert len(inputs["generation_weather"]) == len(inputs["demand_weather"]) == 24


def test_intraday_check_stays_normal_when_ultra_short_agrees_with_day_ahead(monkeypatch):
    bundle = _bundle(monkeypatch, ultra_wind=3.0)
    request = AnalysisRequest(date=TARGET, region="jeju", mode="live")
    out = bundle.intraday_check(request, datetime(2026, 11, 17, 7, 45, tzinfo=KST))
    assert out["result"]["risk"] == "NORMAL"


def test_intraday_check_fails_closed_instead_of_falling_back(monkeypatch):
    request = AnalysisRequest(date=TARGET, region="jeju", mode="live")
    now = datetime(2026, 11, 17, 7, 45, tzinfo=KST)
    no_models = ToolBundle(Settings(_env_file=None))
    with pytest.raises(ValueError, match="model_dir_missing"):
        no_models.intraday_check(request, now)
    bundle = _bundle(monkeypatch)

    def broken(grid, when):
        raise ValueError("kma down")

    monkeypatch.setattr(bundle, "_nowcast", broken)
    with pytest.raises(ValueError, match="kma down"):
        bundle.intraday_check(request, now)
    keyless = ToolBundle(Settings(_env_file=None))
    with pytest.raises(ValueError, match="kma_key_missing"):
        keyless._nowcast((46, 35), now)
