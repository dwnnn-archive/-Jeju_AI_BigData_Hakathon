import json

from app.core.config import ROOT
from app.domain.schemas import EnergyHour, WeatherHour
from app.providers.kma import estimate_irradiance

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


# 시연 수요는 제주 평균 수요(약 700 MWh)로 고정한다. 정오 발전량만 시나리오별로 바꾸고
# 나머지 시간은 수요의 25%(비율 0.25, NORMAL)다. 시나리오 값은 발전량/수요 비율로 환산하면
# normal 0.30, boundary 0.44(CRITICAL 직전), critical 0.73이다.
DEMO_DEMAND_MWH = 700
DEMO_BASE_GENERATION_MWH = 175


def demand(target):
    return [EnergyHour(date=target, hour=h, mwh=DEMO_DEMAND_MWH) for h in range(24)]


def intraday_generation(target, scenario, check_no):
    """당일 점검 시연값. 시나리오에 따로 없으면 하루 전과 같은 값을 쓴다."""
    spec = SCENARIOS[scenario]
    peaks = spec.get("intraday_peak_generation_mwh") or spec["peak_generation_mwh"]
    peak = peaks[min(max(check_no, 1) - 1, len(peaks) - 1)]
    return [
        EnergyHour(date=target, hour=h, mwh=peak if h == 12 else DEMO_BASE_GENERATION_MWH)
        for h in range(24)
    ]


def generation(target, scenario, refresh):
    peaks = SCENARIOS[scenario]["peak_generation_mwh"]
    peak = peaks[min(refresh, len(peaks) - 1)]
    return [
        EnergyHour(date=target, hour=h, mwh=peak if h == 12 else DEMO_BASE_GENERATION_MWH)
        for h in range(24)
    ]
