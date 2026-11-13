import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from backend.domain.schemas import WeatherHour, validate_day

KST = ZoneInfo("Asia/Seoul")
KMA_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"


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


class KmaProvider:
    def __init__(self, key: str, client: httpx.Client):
        self.key, self.client = key, client

    def fetch(self, target: date, lat: float, lon: float) -> list[WeatherHour]:
        nx, ny = grid_coordinates(lat, lon)
        base_date, base_time = issue_time(datetime.now(KST))
        response = self.client.get(
            KMA_URL,
            params={
                "serviceKey": self.key,
                "dataType": "JSON",
                "numOfRows": 3000,
                "pageNo": 1,
                "base_date": base_date,
                "base_time": base_time,
                "nx": nx,
                "ny": ny,
            },
        )
        response.raise_for_status()
        payload = response.json()["response"]
        if str(payload["header"]["resultCode"]) != "00":
            raise ValueError("KMA returned an unsuccessful result code")
        hours = {}
        for item in payload["body"]["items"]["item"]:
            if item["fcstDate"] != target.strftime("%Y%m%d"):
                continue
            time = str(item["fcstTime"])
            if len(time) != 4 or time[2:] != "00":
                raise ValueError("KMA forecast must use hourly timestamps")
            hour, category = int(time[:2]), item["category"]
            if category not in ("WSD", "TMP", "SKY"):
                continue
            slot = hours.setdefault(hour, {})
            if category in slot:
                raise ValueError("Duplicate KMA category/hour")
            slot[category] = float(item["fcstValue"])
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
