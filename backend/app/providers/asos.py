"""기상청 지상(종관, ASOS) 시간자료 조회서비스 어댑터.

활용가이드(AsosHourlyInfoService / getWthrDataList) 기준. 학습용 과거 실측 기상 수집에 쓴다.
- 전일(D-1)까지만 제공하며 전일 자료는 11시 이후 조회 가능.
- 일사(icsr)는 MJ/m2(시간 적산)이므로 W/m2 평균으로 환산한다.
- 품질플래그: 정상 null, 오류 1, 결측 9. 정상이 아니거나 값이 비면 None으로 둔다.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

KST = ZoneInfo("Asia/Seoul")
ASOS_BASE_URL = "https://apis.data.go.kr/1360000/AsosHourlyInfoService"
ASOS_OPERATION = "getWthrDataList"
# 가이드 첨부 지점코드(제주지방기상청 관할).
JEJU_STATIONS = {"jeju": 184, "gosan": 185, "seongsan": 188, "seogwipo": 189}
MJ_PER_M2_TO_AVG_WM2 = 1_000_000 / 3600  # 1시간 적산(MJ/m2) → 시간 평균(W/m2)


@dataclass(frozen=True)
class AsosHour:
    timestamp: datetime  # KST, 정시
    station_id: int
    wind_ms: float | None
    temperature_c: float | None
    irradiance_wm2: float | None


def _result_ok(header: dict) -> bool:
    try:
        return int(str(header["resultCode"]).strip()) == 0
    except (KeyError, ValueError):
        return False


def _value(item: dict, field: str) -> float | None:
    """값이 비었거나 품질플래그가 정상이 아니면 None.

    가이드는 정상을 null로 적었지만 실제 응답은 2018년 이전 자료에서 정상에 "0"을 쓴다.
    오류 1, 결측 9 이외는 정상으로 본다.
    """
    raw = item.get(field)
    flag = item.get(f"{field}Qcflg")
    if raw in (None, "") or flag not in (None, "", "0"):
        return None
    return float(raw)


def _irradiance(item: dict) -> float | None:
    # 일사(icsr)는 품질플래그 필드가 가이드에 없어 값 유무만 본다.
    raw = item.get("icsr")
    if raw in (None, ""):
        return None
    return float(raw) * MJ_PER_M2_TO_AVG_WM2


class AsosProvider:
    def __init__(
        self,
        key: str,
        client: httpx.Client,
        base_url: str = ASOS_BASE_URL,
        page_size: int = 999,
        max_pages: int = 200,
    ):
        self.key, self.client = key, client
        self.url = f"{base_url.rstrip('/')}/{ASOS_OPERATION}"
        self.page_size, self.max_pages = page_size, max_pages

    def fetch(self, station_id: int, start: datetime, end: datetime) -> list[AsosHour]:
        """start~end(KST, 정시 포함)의 시간자료. end 날짜는 어제 이전이어야 한다."""
        start, end = start.astimezone(KST), end.astimezone(KST)
        yesterday = datetime.now(KST).date() - timedelta(days=1)
        if end.date() > yesterday or start > end:
            raise ValueError("ASOS provides data up to the previous day only")
        rows: list[AsosHour] = []
        seen: set[datetime] = set()
        for item in self._items(station_id, start, end):
            ts = datetime.strptime(item["tm"][:13], "%Y-%m-%d %H").replace(tzinfo=KST)
            if ts in seen:
                raise ValueError("Duplicate ASOS timestamp")
            seen.add(ts)
            rows.append(
                AsosHour(
                    ts,
                    int(item["stnId"]),
                    _value(item, "ws"),
                    _value(item, "ta"),
                    _irradiance(item),
                )
            )
        return sorted(rows, key=lambda r: r.timestamp)

    def _items(self, station_id: int, start: datetime, end: datetime) -> list[dict]:
        items: list[dict] = []
        for page in range(1, self.max_pages + 1):
            response = self.client.get(
                self.url,
                params={
                    "serviceKey": self.key,
                    "dataType": "JSON",
                    "numOfRows": self.page_size,
                    "pageNo": page,
                    "dataCd": "ASOS",
                    "dateCd": "HR",
                    "startDt": start.strftime("%Y%m%d"),
                    "startHh": start.strftime("%H"),
                    "endDt": end.strftime("%Y%m%d"),
                    "endHh": end.strftime("%H"),
                    "stnIds": station_id,
                },
            )
            response.raise_for_status()
            payload = response.json()["response"]
            if not _result_ok(payload["header"]):
                raise ValueError("ASOS returned an unsuccessful result code")
            body = payload["body"]
            items.extend(body["items"]["item"])
            if len(items) >= int(body["totalCount"]):
                return items
        raise ValueError("ASOS response exceeded the page limit")


def previous_day(today: date | None = None) -> date:
    return (today or datetime.now(KST).date()) - timedelta(days=1)
