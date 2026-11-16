import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.domain.schemas import WeatherHour, validate_day

KST = ZoneInfo("Asia/Seoul")
# 기상청 단기예보 조회서비스(2.0) 활용가이드 기준 (apihub.kma.go.kr).
KMA_BASE_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0"
KMA_OPERATION = "getVilageFcst"
# 가이드: +900 이상, -900 이하 값은 Missing(관측장비 없음/결측).
MISSING_LIMIT = 900
# 가이드: 발표 후 +1~2일은 1시간 간격 정량값, 그 이후(연장 구간)는 3시간 간격 + WSD 정성코드.


def grid_coordinates(lat: float, lon: float) -> tuple[int, int]:
    if not (33 <= lat <= 39 and 124 <= lon <= 132):
        raise ValueError("Coordinates must be in the Korean forecast domain")
    rad = math.pi / 180
    slat1, slat2 = 30 * rad, 60 * rad
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi / 4 + slat2 / 2) / math.tan(math.pi / 4 + slat1 / 2)
    )
    sf = math.tan(math.pi / 4 + slat1 / 2) ** sn * math.cos(slat1) / sn
    ro = 6371.00877 / 5 * sf / math.tan(math.pi / 4 + 38 * rad / 2) ** sn
    ra = 6371.00877 / 5 * sf / math.tan(math.pi / 4 + lat * rad / 2) ** sn
    theta = (lon - 126) * rad * sn
    return math.floor(ra * math.sin(theta) + 43 + 0.5), math.floor(
        ro - ra * math.cos(theta) + 136 + 0.5
    )


def issue_time(now: datetime) -> tuple[str, str]:
    now = now.astimezone(KST) - timedelta(minutes=10)
    candidates = [
        datetime.combine(now.date() - timedelta(days=d), datetime.min.time(), KST)
        + timedelta(hours=h)
        for d in (0, 1)
        for h in (2, 5, 8, 11, 14, 17, 20, 23)
    ]
    selected = max(t for t in candidates if t <= now)
    return selected.strftime("%Y%m%d"), selected.strftime("%H%M")


def estimate_irradiance(hour: int, sky: int) -> float:
    # Proxy only; not a measured irradiance value.
    sun = max(0.0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0
    return sun * 900 * {1: 1, 2: 0.8, 3: 0.6, 4: 0.3}[sky]


def _result_ok(header: dict) -> bool:
    # 가이드 표는 "00", 예제 응답은 "0"을 사용하므로 정수로 정규화해 비교한다.
    try:
        return int(str(header["resultCode"]).strip()) == 0
    except (KeyError, ValueError):
        return False


def fetch_items(
    client: httpx.Client,
    url: str,
    auth_param: str,
    key: str,
    params: dict,
    page_size: int = 1000,
    max_pages: int = 10,
) -> list[dict]:
    """기상청 조회서비스의 모든 페이지를 받아 item 목록으로 합친다(단기·초단기 공용)."""
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        response = client.get(
            url,
            params={
                auth_param: key,
                "dataType": "JSON",
                "numOfRows": page_size,
                "pageNo": page,
                **params,
            },
        )
        response.raise_for_status()
        payload = response.json()["response"]
        if not _result_ok(payload["header"]):
            raise ValueError("KMA returned an unsuccessful result code")
        body = payload["body"]
        items.extend(body["items"]["item"])
        if len(items) >= int(body["totalCount"]):
            return items
    raise ValueError("KMA response exceeded the page limit")


class KmaProvider:
    def __init__(
        self,
        key: str,
        client: httpx.Client,
        base_url: str = KMA_BASE_URL,
        auth_param: str = "authKey",
        page_size: int = 1000,
        max_pages: int = 10,
    ):
        self.key, self.client = key, client
        self.url = f"{base_url.rstrip('/')}/{KMA_OPERATION}"
        self.auth_param, self.page_size, self.max_pages = auth_param, page_size, max_pages

    def _items(self, nx: int, ny: int, base_date: str, base_time: str) -> list[dict]:
        params = {"base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny}
        return fetch_items(
            self.client, self.url, self.auth_param, self.key, params, self.page_size, self.max_pages
        )

    def fetch(
        self,
        target: date,
        lat: float,
        lon: float,
        grid: tuple[int, int] | None = None,
        base: tuple[str, str] | None = None,
    ) -> list[WeatherHour]:
        nx, ny = grid or grid_coordinates(lat, lon)
        base_date, base_time = base or issue_time(datetime.now(KST))
        hours = {}
        for item in self._items(nx, ny, base_date, base_time):
            if item["fcstDate"] != target.strftime("%Y%m%d"):
                continue
            time = str(item["fcstTime"])
            hour, category = int(time[:2]), item["category"]
            if category not in ("WSD", "TMP", "SKY"):
                continue
            if len(time) != 4 or time[2:] != "00":
                raise ValueError("KMA forecast must use hourly timestamps")
            value = float(item["fcstValue"])
            if abs(value) >= MISSING_LIMIT:
                raise ValueError("KMA returned a missing value")
            slot = hours.setdefault(hour, {})
            if category in slot:
                raise ValueError("Duplicate KMA category/hour")
            slot[category] = value
        rows = [
            WeatherHour(
                date=target,
                hour=h,
                wind_ms=v["WSD"],
                temperature_c=v["TMP"],
                sky=int(v["SKY"]),
                irradiance_wm2=estimate_irradiance(h, int(v["SKY"])),
            )
            for h, v in hours.items()
        ]
        return validate_day(rows, target)
