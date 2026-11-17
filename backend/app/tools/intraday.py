"""당일 점검: 하루 전 예보 위에 초단기실황·초단기예보를 덧씌운다.

하루 전 계획이 "정상"인 날만 당일에 다시 점검한다(최대 2회, 예: 07:45, 10:45).
점검 시각 now 의 시간 h0 기준으로 하루 24시간의 날씨를 다음처럼 이어 붙인다.
- h0 이전: 하루 전 예보 그대로(이미 지난 시간이라 판정에서도 제외한다).
- h0: 초단기실황(풍속·기온 실측), 하늘상태는 초단기예보 또는 하루 전 예보.
- h0+1 ~ h0+6: 초단기예보(풍속·기온·하늘상태). 정수로 와서 단기예보보다 거칠다.
- 그 뒤: 하루 전 예보 그대로.
같은 날 지난 시간의 실측 이력은 초단기실황으로 얻을 수 없다(현재 정시 한 시점뿐이다).
"""

from datetime import date, timedelta

from app.domain.schemas import WeatherHour, validate_day
from app.providers.kma import estimate_irradiance
from app.providers.kma_nowcast import HourObs

# 하루 전 예보로 쓸 발표분: 전날 23시(그날 00시부터 24시간을 모두 덮는 마지막 발표)
DAY_AHEAD_BASE_TIME = "2300"


def previous_evening_base(target: date) -> tuple[str, str]:
    return (target - timedelta(days=1)).strftime("%Y%m%d"), DAY_AHEAD_BASE_TIME


def blend_weather(
    day_ahead: list[WeatherHour],
    observation: HourObs | None,
    ultra: list[HourObs],
    target: date,
) -> tuple[list[WeatherHour], dict[int, str]]:
    """(24시간 날씨, 시간별 출처). 출처는 day_ahead / ultra / nowcast."""
    rows = {w.hour: w for w in validate_day(day_ahead, target)}
    sources = {h: "day_ahead" for h in rows}
    for u in ultra:
        if u.date != target:
            continue  # 자정을 넘은 다음 날 예보는 쓰지 않는다
        sky = u.sky if u.sky is not None else rows[u.hour].sky
        rows[u.hour] = rows[u.hour].model_copy(
            update={
                "wind_ms": u.wind_ms,
                "temperature_c": u.temperature_c,
                "sky": sky,
                "irradiance_wm2": estimate_irradiance(u.hour, sky),
            }
        )
        sources[u.hour] = "ultra"
    if observation is not None and observation.date == target:
        base = rows[observation.hour]
        rows[observation.hour] = base.model_copy(
            update={"wind_ms": observation.wind_ms, "temperature_c": observation.temperature_c}
        )
        sources[observation.hour] = "nowcast"
    return [rows[h] for h in sorted(rows)], sources
