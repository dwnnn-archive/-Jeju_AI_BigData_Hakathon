"""제주데이터허브 '일별 기상 정보'(No.756)·'기상관측소 정보'(No.757) API 어댑터.

가이드 기준.
- 일별 기상: `searchDate=YYYYMMDD` 가 필수라 **날짜 하나당 1회 호출**한다. 한 번에 관측소 약 35곳의 일평균 기온·풍속 등이 온다.
- 관측소 정보: 관측소명, 고도 등. 응답의 longitude/latitude 값이 서로 바뀌어 있어(경도 자리에 33.x) 위치는 쓰지 않는다.

확인한 사실(2026-11-17)
- 일별 기상에는 ASOS 4곳(제주·고산·성산·서귀포)이 없고 방재기상관측(AWS) 관측소만 있다.
- 한라산 고지대 관측소(윗세오름 등 해발 1,500 m 이상)가 섞여 있어 전체 평균은 제주 시가지 기온보다 3℃쯤 낮다.
  그래서 고도 100 m 미만 관측소만 평균해 쓴다.
- **2025-03 말 이후는 호출은 되지만 데이터가 비어 있다**("매일 자동 갱신" 표기와 다르다). 서비스 입력으로 쓸 수 없다.
- 키가 URL 경로에 들어가므로 예외 메시지에 URL을 싣지 않는다(_get_page가 처리).
"""

import json
from datetime import date
from pathlib import Path

import httpx

from app.providers.jejuhub_ev import _get_page

HUB = "https://open.jejudatahub.net/api/proxy"
WEATHER_URL = f"{HUB}/1aD5taat1attaa51Db1511b51ab9Da19"
STATION_URL = f"{HUB}/t1bab75a555a15715btaa7a5abaa1aab"
LOWLAND_MAX_ALTITUDE_M = 100.0
MIN_STATIONS = 5  # 하루 평균에 필요한 최소 관측소 수


def fetch_day(project_key: str, day: date, *, client: httpx.Client, retries: int = 2) -> list[dict]:
    body = _get_page(client, f"{WEATHER_URL}/{project_key}", 1, retries, {"searchDate": f"{day:%Y%m%d}"})
    data = body.get("data")
    if not isinstance(data, list):
        raise RuntimeError("Jeju data hub response has no data list")
    return [r for r in data if isinstance(r, dict)]


def fetch_altitudes(project_key: str, *, client: httpx.Client, retries: int = 2) -> dict[str, float]:
    """관측소명 -> 해발 고도(m). 같은 이름이 둘이면 낮은 쪽을 쓴다."""
    altitudes: dict[str, float] = {}
    for page in range(1, 20):
        body = _get_page(client, f"{STATION_URL}/{project_key}", page, retries)
        for r in body.get("data") or []:
            try:
                name, alt = str(r["observatoryName"]), float(r["seaLevelAltitude"])
            except (KeyError, TypeError, ValueError):
                continue
            altitudes[name] = min(alt, altitudes.get(name, alt))
        if not body.get("hasMore"):
            return altitudes
    raise RuntimeError("Jeju data hub returned too many pages")


def lowland_names(altitudes: dict[str, float], max_altitude: float = LOWLAND_MAX_ALTITUDE_M) -> set[str]:
    return {n for n, a in altitudes.items() if a < max_altitude}


def day_mean_temperature(rows: list[dict], names: set[str], min_stations: int = MIN_STATIONS) -> float | None:
    """names 에 속한 관측소의 일평균 기온을 평균한다. 값이 있는 관측소가 min_stations 미만이면 None."""
    values: list[float] = []
    for r in rows:
        if r.get("observatoryName") not in names:
            continue
        try:
            values.append(float(r["averageTemperature"]))
        except (KeyError, TypeError, ValueError):
            continue
    return sum(values) / len(values) if len(values) >= min_stations else None


def read_cached_day(cache_dir: Path, day: date) -> list[dict] | None:
    try:
        rows = json.loads((cache_dir / f"{day:%Y%m%d}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rows if isinstance(rows, list) else None


def write_cached_day(cache_dir: Path, day: date, rows: list[dict]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{day:%Y%m%d}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
