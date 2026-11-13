import json

from backend.core.config import ROOT
from backend.domain.schemas import EnergyHour, WeatherHour
from backend.providers.kma import estimate_irradiance

SCENARIOS = json.loads((ROOT / "data/fixtures/scenarios.json").read_text())


def weather(target):
    return [
        WeatherHour(
            date=target,
            hour=h,
            wind_ms=10,
            temperature_c=20,
            sky=1,
            irradiance_wm2=estimate_irradiance(h, 1),
        )
        for h in range(24)
    ]


def demand(target):
    return [EnergyHour(date=target, hour=h, mwh=500) for h in range(24)]


def generation(target, scenario, refresh):
    peaks = SCENARIOS[scenario]["peak_surplus_mwh"]
    peak = peaks[min(refresh, len(peaks) - 1)]
    return [EnergyHour(date=target, hour=h, mwh=500 + peak if h == 12 else 400) for h in range(24)]
