"""제주데이터허브 '전기자동차 충전소 정보' API 어댑터.

API 가이드(전기 자동차 충전소 정보 API 가이드 v1.0) 기준.
- 호출: https://open.jejudatahub.net/api/proxy/<데이터 키>/<프로젝트 키>?number=&limit=
  프로젝트 키는 허브 마이페이지의 프로젝트 관리에서 발급한다(환경변수 JEJUHUB_PROJECT_KEY).
- 응답: {"totCnt", "hasMore", "data": [...]}. limit 최대 100.
- 한 충전소 행에 완속·급속 충전기 수(chargerCount, quickChargerCount)와 운영 시간이 있다.

주의: 키가 URL 경로에 들어가므로 예외 메시지나 로그에 URL을 싣지 않는다.
"""

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

KST = ZoneInfo("Asia/Seoul")
JEJUHUB_BASE_URL = "https://open.jejudatahub.net/api/proxy/atDab6t8218btaa122b26DDtbatD86t1"
PAGE_LIMIT = 100
MAX_PAGES = 50

# 충전기 1기의 정격 출력 가정(kW). API에는 용량이 없어 일반적인 값을 쓴다. 가정이다.
DEFAULT_SLOW_KW = 7.0
DEFAULT_FAST_KW = 50.0
# 설치 용량 중 남는 전력을 받아 줄 수 있다고 보는 비율. 실제 이용률 자료가 없어 둔 가정이다.
DEFAULT_IDLE_RATIO = 0.5


_calls = {"n": 0, "log": None}


def enable_call_log(path: Path) -> None:
    """수집 스크립트가 켠다. 허브에 실제로 보낸 요청마다 한 줄(시각, 데이터 키, 결과)을 남기고 횟수를 센다.

    프로젝트 키는 URL 끝에 있으므로 기록하지 않는다. 테스트는 켜지 않아 파일을 만들지 않는다.
    """
    _calls["n"] = 0
    _calls["log"] = path


def call_count() -> int:
    return _calls["n"]


def _record(url: str, result: str) -> None:
    _calls["n"] += 1
    path = _calls["log"]
    if path is None:
        return
    dataset = url.rsplit("/", 1)[0].rsplit("/", 1)[-1]  # 마지막 조각(프로젝트 키)을 뺀 데이터 키
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("\t".join((f"{datetime.now(KST):%Y-%m-%d %H:%M:%S}", dataset, result)) + "\n")


class QuotaExceeded(RuntimeError):
    """허브 API의 하루 호출 한도가 찼다(HTTP 403 "quota is full"). 재시도해도 소용없다."""


@dataclass(frozen=True)
class EvStation:
    name: str
    detail: str
    slow_count: int
    fast_count: int
    start_minute: int | None  # 운영 시작(0~1439). 해석 불가면 None
    end_minute: int | None
    latitude: float | None
    longitude: float | None
    base_date: str
    provider: str
    public: bool = True  # 입주민·직원 전용, 외부인 제한이면 False


def _minutes(raw) -> int | None:
    """"0:00", "09:00", "24:00:00" 같은 값을 하루 중 분(0~1439)으로 바꾼다.

    실제 응답은 가이드 예시(HH:MM)와 달리 앞자리 0이 없거나("0:00") 초가 붙는다("24:00:00").
    24:00 은 하루의 끝이라 1439 로 본다. "알 수 없음" 같은 값은 None.
    """
    try:
        parts = [int(x) for x in str(raw).strip().split(":")]
    except (ValueError, AttributeError):
        return None
    if len(parts) not in (2, 3):
        return None
    hh, mm = parts[0], parts[1]
    if (hh, mm) == (24, 0):
        return 1439
    value = hh * 60 + mm
    return value if 0 <= hh <= 23 and 0 <= mm <= 59 else None


def _count(raw) -> int:
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _float(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# holiday(이용 가능 요일·조건) 값에 이 말이 들어 있으면 일반 이용이 안 되는 곳으로 본다.
_RESTRICTED_WORDS = ("전용", "제한", "외부인")


def parse_station(item: dict) -> EvStation:
    return EvStation(
        name=str(item.get("chargingPlace") or "").strip(),
        detail=str(item.get("chargingPlaceDetail") or "").strip(),
        slow_count=_count(item.get("chargerCount")),
        fast_count=_count(item.get("quickChargerCount")),
        start_minute=_minutes(item.get("startTime")),
        end_minute=_minutes(item.get("endTime")),
        latitude=_float(item.get("latitude")),
        longitude=_float(item.get("longitude")),
        base_date=str(item.get("baseDate") or ""),
        provider=str(item.get("provider") or ""),
        public=not any(w in str(item.get("holiday") or "") for w in _RESTRICTED_WORDS),
    )


def dedupe_stations(stations: list[EvStation]) -> list[EvStation]:
    """같은 충전소를 한 번만 센다.

    API는 충전소를 **충전 방식(완속·급속 종류)별로 한 행씩** 내려 주면서 각 행에 충전소 전체
    충전기 수를 반복해 담는다(예: 한 충전소가 3행이면 같은 "완속 3·급속 15"가 3번). 그대로 더하면
    충전기가 부풀려지므로 이름·위치·충전기 수가 모두 같은 행은 하나로 합친다.
    """
    seen: set[tuple] = set()
    unique: list[EvStation] = []
    for st in stations:
        key = (st.name, st.detail, st.latitude, st.longitude, st.slow_count, st.fast_count)
        if key not in seen:
            seen.add(key)
            unique.append(st)
    return unique


def fetch_stations(
    project_key: str,
    *,
    client: httpx.Client,
    base_url: str = JEJUHUB_BASE_URL,
    retries: int = 2,
) -> list[EvStation]:
    """전체 페이지를 모아 충전소 목록을 돌려준다. 시간 초과·5xx는 재시도한다."""
    stations: list[EvStation] = []
    for page in range(1, MAX_PAGES + 1):
        payload = _get_page(client, f"{base_url}/{project_key}", page, retries)
        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError("Jeju data hub response has no data list")
        stations.extend(parse_station(item) for item in data if isinstance(item, dict))
        if not payload.get("hasMore"):
            return dedupe_stations(stations)
    raise RuntimeError("Jeju data hub returned too many pages")


def _get_page(
    client: httpx.Client, url: str, page: int, retries: int, extra: dict | None = None
) -> dict:
    last = "unknown"
    for _ in range(retries + 1):
        try:
            response = client.get(
                url, params={**(extra or {}), "number": page, "limit": PAGE_LIMIT}
            )
        except httpx.TransportError as exc:  # 시간 초과·연결 실패. 메시지에 URL이 있어 종류만 남긴다.
            last = type(exc).__name__
            _record(url, last)
            continue
        _record(url, str(response.status_code))
        if response.status_code >= 500:
            last = f"HTTP {response.status_code}"
            continue
        if response.status_code == 403 and "quota" in response.text.lower():
            raise QuotaExceeded("Jeju data hub daily quota is full")
        if response.status_code != 200:
            raise RuntimeError(f"Jeju data hub request failed: HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("Jeju data hub response is not JSON") from exc
        if not isinstance(body, dict):
            raise RuntimeError("Jeju data hub response has unexpected shape")
        return body
    raise RuntimeError(f"Jeju data hub request failed after retries: {last}")


def _open_at(station: EvStation, hour: int) -> bool:
    """해당 시(hour시 0분~59분) 내내 운영하는지. 운영 시간을 해석하지 못하면 닫힌 것으로 본다."""
    start, end = station.start_minute, station.end_minute
    if start is None or end is None:
        return False
    first, last = hour * 60, hour * 60 + 59
    if start <= end:
        return start <= first and last <= end
    return first >= start or last <= end  # 자정을 넘기는 운영


def ev_capacity(
    stations: list[EvStation],
    hour: int,
    *,
    slow_kw: float = DEFAULT_SLOW_KW,
    fast_kw: float = DEFAULT_FAST_KW,
    idle_ratio: float = DEFAULT_IDLE_RATIO,
    profile: dict | None = None,
    target_date: date | None = None,
    top_n: int = 5,
) -> dict:
    """해당 시각에 운영 중인 충전기로 1시간 동안 받을 수 있는 전력량(MWh).

    top_n 개의 충전소 순위도 함께 낸다. 이용 패턴(이력)은 충전소별이 아니라 전체 평균이라,
    순위는 **충전소별 설치 규모(충전기 수 x 전력)** 로 매긴다. 충전소별 실제 혼잡도는 반영하지 못한다.
    """
    if not 0 <= hour <= 23:
        raise ValueError("hour must be within 0..23")
    if not 0 <= idle_ratio <= 1:
        raise ValueError("idle_ratio must be within 0..1")
    open_stations = [s for s in stations if s.public and _open_at(s, hour)]
    slow = sum(s.slow_count for s in open_stations)
    fast = sum(s.fast_count for s in open_stations)
    basis: dict = {"basis": "assumption"}
    free = {"slow": idle_ratio, "fast": idle_ratio}
    if profile and profile.get("slow") and profile.get("fast"):
        # 충전 이력 기반: 실제 평균 전력 x (1 - 그 시각 점유율 x 요일 보정).
        factor = 1.0
        if target_date is not None:
            factor = float(profile["weekday_factor"].get("월화수목금토일"[target_date.weekday()], 1.0))
        free = {g: 1 - min(1.0, profile[g]["occupancy"][hour] * factor) for g in ("slow", "fast")}
        slow_kw, fast_kw = profile["slow"]["avg_kw"], profile["fast"]["avg_kw"]
        installed_mwh = (slow * slow_kw + fast * fast_kw) / 1000
        capacity_mwh = (slow * slow_kw * free["slow"] + fast * fast_kw * free["fast"]) / 1000
        basis = {
            "basis": "history_profile",
            "history_months": profile["months"],
            "free_fraction": free,
            "weekday_factor": factor,
        }
    else:
        installed_mwh = (slow * slow_kw + fast * fast_kw) / 1000  # kW x 1h → MWh
        capacity_mwh = installed_mwh * idle_ratio

    def station_mwh(st: EvStation) -> float:
        return (st.slow_count * slow_kw * free["slow"] + st.fast_count * fast_kw * free["fast"]) / 1000

    ranked = sorted(open_stations, key=lambda st: (-station_mwh(st), st.name))[: max(0, top_n)]
    top_stations = [
        {
            "name": st.name,
            "detail": st.detail,
            "slow_chargers": st.slow_count,
            "fast_chargers": st.fast_count,
            "capacity_mwh": station_mwh(st),
            "share": station_mwh(st) / capacity_mwh if capacity_mwh > 0 else 0.0,
            "latitude": st.latitude,
            "longitude": st.longitude,
        }
        for st in ranked
    ]
    return {
        **basis,
        "capacity_mwh": capacity_mwh,
        "installed_mwh": installed_mwh,
        "stations_total": len(stations),
        "stations_open": len(open_stations),
        "stations_hours_unknown": sum(
            1 for s in stations if s.start_minute is None or s.end_minute is None
        ),
        "stations_restricted": sum(1 for s in stations if not s.public),
        "slow_chargers": slow,
        "fast_chargers": fast,
        "base_date": max((s.base_date for s in stations if s.base_date), default=""),
        "hour": hour,
        "top_stations": top_stations,
        "assumptions": {"slow_kw": slow_kw, "fast_kw": fast_kw, "idle_ratio": idle_ratio},
    }


def save_snapshot(stations: list[EvStation], path: Path, now: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "fetched_at": (now or datetime.now(KST)).isoformat(),
        "source": "jejudatahub:전기자동차 충전소 정보",
        "stations": [asdict(s) for s in stations],
    }
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def load_snapshot(path: Path) -> tuple[list[EvStation], str] | None:
    """저장된 목록과 수집 시각. 파일이 없거나 깨졌으면 None."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        stations = dedupe_stations([EvStation(**row) for row in body["stations"]])
        return stations, str(body["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
