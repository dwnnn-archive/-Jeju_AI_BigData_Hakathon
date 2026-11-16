"""기상청 초단기실황·초단기예보 어댑터 (VilageFcstInfoService_2.0).

활용가이드와 실제 호출로 확인한 규격:
- 초단기실황(getUltraSrtNcst): 매시 정각 자료, 10분 이후 호출. 항목 T1H(기온 ℃), WSD(풍속 m/s) 등.
  하늘상태(SKY)는 없다.
- 초단기예보(getUltraSrtFcst): 매시 30분 생성, 45분 이후 호출. 기준 시각의 다음 정시부터 6시간.
  예: 기준 20:30 → 21:00 ~ 02:00. 항목 T1H, WSD, SKY(1/3/4) 등. **풍속·기온이 정수로 온다.**
- 시각은 단기예보와 같은 방식으로 fcstTime HH00 → HH시로 읽는다.
- ±900 이상은 결측이므로 오류로 처리한다. 실황은 현재 정시 한 시점뿐이라 같은 날 지난 시간의
  실측 이력은 이 API로 얻을 수 없다.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

from app.providers.kma import KMA_BASE_URL, KST, MISSING_LIMIT, fetch_items

NCST_OPERATION = "getUltraSrtNcst"
FCST_OPERATION = "getUltraSrtFcst"


@dataclass(frozen=True)
class HourObs:
    """한 시간의 풍속·기온(·하늘상태). sky는 실황에는 없어 None이다."""

    date: date
    hour: int
    wind_ms: float
    temperature_c: float
    sky: int | None = None


def observation_base(now: datetime) -> tuple[str, str]:
    """초단기실황 발표(base) 일자·시각. 정시 자료는 10분 이후 제공된다."""
    t = now.astimezone(KST) - timedelta(minutes=10)
    return t.strftime("%Y%m%d"), t.strftime("%H00")


def forecast_base(now: datetime) -> tuple[str, str]:
    """초단기예보 발표(base) 일자·시각(HH30). 45분 이후 제공된다."""
    t = now.astimezone(KST) - timedelta(minutes=45)
    return t.strftime("%Y%m%d"), t.strftime("%H30")


def _number(raw: str) -> float:
    value = float(raw)
    if abs(value) >= MISSING_LIMIT:
        raise ValueError("KMA returned a missing value")
    return value


class KmaNowcastProvider:
    def __init__(
        self,
        key: str,
        client: httpx.Client,
        base_url: str = KMA_BASE_URL,
        auth_param: str = "authKey",
        recorder=None,
    ):
        self.recorder = recorder  # recorder(source, nx, ny, base_date, base_time, items)
        self.key, self.client = key, client
        self.base_url, self.auth_param = base_url.rstrip("/"), auth_param

    def _items(self, operation: str, nx: int, ny: int, base: tuple[str, str]) -> list[dict]:
        params = {"base_date": base[0], "base_time": base[1], "nx": nx, "ny": ny}
        items = fetch_items(
            self.client, f"{self.base_url}/{operation}", self.auth_param, self.key, params, 200, 3
        )
        if self.recorder:
            source = "ultra_ncst" if operation == NCST_OPERATION else "ultra_fcst"
            self.recorder(source, nx, ny, base[0], base[1], items)
        return items

    def raw_observation(self, nx: int, ny: int, now: datetime) -> list[dict]:
        """초단기실황 원본 항목 전체(저장용)."""
        return self._items(NCST_OPERATION, nx, ny, observation_base(now))

    def raw_forecast(self, nx: int, ny: int, now: datetime) -> list[dict]:
        """초단기예보 원본 항목 전체(저장용)."""
        return self._items(FCST_OPERATION, nx, ny, forecast_base(now))

    def observation(self, nx: int, ny: int, now: datetime) -> HourObs:
        """가장 최근 정시의 풍속·기온 실황."""
        values: dict[str, float] = {}
        when: tuple[date, int] | None = None
        for item in self._items(NCST_OPERATION, nx, ny, observation_base(now)):
            if item["category"] in ("WSD", "T1H"):
                values[item["category"]] = _number(item["obsrValue"])
                when = (
                    datetime.strptime(item["baseDate"], "%Y%m%d").date(),
                    int(str(item["baseTime"])[:2]),
                )
        if when is None or set(values) != {"WSD", "T1H"}:
            raise ValueError("Nowcast observation is missing wind or temperature")
        return HourObs(when[0], when[1], values["WSD"], values["T1H"])

    def forecast(self, nx: int, ny: int, now: datetime) -> list[HourObs]:
        """이후 6시간의 풍속·기온·하늘상태 예보(시각순)."""
        slots: dict[tuple[date, int], dict[str, float]] = {}
        for item in self._items(FCST_OPERATION, nx, ny, forecast_base(now)):
            category = item["category"]
            if category not in ("WSD", "T1H", "SKY"):
                continue
            time = str(item["fcstTime"])
            if len(time) != 4 or time[2:] != "00":
                raise ValueError("KMA ultra-short forecast must use hourly timestamps")
            key = (datetime.strptime(item["fcstDate"], "%Y%m%d").date(), int(time[:2]))
            slot = slots.setdefault(key, {})
            if category in slot:
                raise ValueError("Duplicate KMA category/hour")
            slot[category] = _number(item["fcstValue"])
        rows = []
        for (d, hour), v in sorted(slots.items()):
            if set(v) != {"WSD", "T1H", "SKY"}:
                raise ValueError("Ultra-short forecast hour is missing a category")
            rows.append(HourObs(d, hour, v["WSD"], v["T1H"], int(v["SKY"])))
        if not rows:
            raise ValueError("Ultra-short forecast returned no hours")
        return rows
