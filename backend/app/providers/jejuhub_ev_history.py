"""제주데이터허브 '전기자동차 충전 이력' API(월별·요일별)로 이용 패턴을 만든다.

가이드 기준(2021-01 ~ 2022-06 등 과거 이력, 운영기관 환경부·제주특별자치도 충전기).
- 월별: 충전기 x 월 x **충전 시작 시각** 별 충전 횟수·충전 시간(HH:MM:SS)·충전량(kWh).
- 요일별: 충전기 x 월 x 요일 별 같은 항목. 시간대 정보는 없다.
- 일별: 충전기 x 일 별. 시간·요일 정보가 없어 이용 패턴(점유율)에는 쓰지 않고,
  daily_summary()로 날짜별 변동과 월별 합계 정합성 확인에만 쓴다.

여기서 두 가지를 얻는다.
1. 충전기가 실제로 낸 평균 전력(kW) = 충전량 / 충전 시간. 정격 가정을 대체한다.
2. 시간대별 점유율 = 충전 중인 시간 / 충전기 가용 시간. 이용률 가정을 대체한다.

한계: 이력에 나타난 충전기만 분모에 넣으므로 한 번도 안 쓴 충전기는 빠진다(점유율을 높게 잡는 쪽).
이력은 과거(2021~2022)라 오늘의 이용 수준과 다를 수 있다.
"""

import calendar
import json
from datetime import date
from pathlib import Path

import httpx

from app.providers.jejuhub_ev import _get_page

HUB = "https://open.jejudatahub.net/api/proxy"
MONTHLY_URL = f"{HUB}/DD96616t226D16at11ta92D6DD19DttD"
WEEKDAY_URL = f"{HUB}/71111t11a161tb1Da611Daab2a91912a"
DAILY_URL = f"{HUB}/btb8a6DD29t622tab1ta2t68Db1a682a"
WEEKDAYS = "월화수목금토일"  # date.weekday() 0=월
MAX_PAGES = 400
SPREAD_STEPS = 12
MAX_SESSION_HOURS = 24.0


def fetch_rows(
    project_key: str, base_url: str, params: dict, *, client: httpx.Client, retries: int = 2
) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        body = _get_page(client, f"{base_url}/{project_key}", page, retries, params)
        data = body.get("data")
        if not isinstance(data, list):
            raise RuntimeError("Jeju data hub response has no data list")
        rows.extend(r for r in data if isinstance(r, dict))
        if not body.get("hasMore"):
            return rows
    raise RuntimeError("Jeju data hub returned too many pages")


def cached_rows(cache_dir: Path, kind: str, month: str, fetch) -> tuple[list[dict], bool]:
    """달별 원본을 파일로 저장해 이어받는다. (행, 새로 받았는지). 한도 초과 같은 실패 때 앞서 받은 달을 잃지 않는다."""
    path = cache_dir / f"{kind}-{month}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")), False
    except (OSError, ValueError):
        pass
    rows = fetch()
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # 반쯤 쓰인 파일이 남지 않게 한다
    return rows, True


def hours_of(raw) -> float | None:
    """'HH:MM:SS'(24시간 넘을 수 있음)를 시간 단위 실수로. 해석 불가면 None."""
    try:
        h, m, s = (int(x) for x in str(raw).strip().split(":"))
    except ValueError:
        return None
    return h + m / 60 + s / 3600 if min(h, m, s) >= 0 else None


def charger_key(row: dict) -> str:
    """충전기 1기를 구분하는 키. evChargerId는 충전소 안의 번호(1, 2, ...)라 충전소 ID와 함께 써야 한다."""
    return f"{row.get('evChargingStationId', '')}/{row.get('evChargerId')}"


def group_of(category) -> str:
    """완속은 slow, 나머지(급속 계열 전부)는 fast."""
    return "slow" if str(category).strip() == "완속" else "fast"


def spread_busy_hours(start_hour: int, duration_h: float) -> dict[int, float]:
    """시각 start_hour 안에서 균등하게 시작한 충전 1건이 각 시(0~23)에 차지하는 평균 시간(시간).

    충전 시작 시각만 알고 끝 시각은 모르므로 평균 충전 시간만큼 뒤 시간으로 이어서 나눈다.
    """
    d = min(max(duration_h, 0.0), MAX_SESSION_HOURS)
    busy: dict[int, float] = {}
    for i in range(SPREAD_STEPS):
        start = (i + 0.5) / SPREAD_STEPS
        end = start + d
        k = 0
        while k < end:
            overlap = min(end, k + 1) - max(start, k)
            if overlap > 0:
                hour = (start_hour + k) % 24
                busy[hour] = busy.get(hour, 0.0) + overlap / SPREAD_STEPS
            k += 1
    return busy


def build_profile(monthly: list[dict], weekday: list[dict]) -> dict:
    groups = {
        g: {"busy": [0.0] * 24, "kwh": 0.0, "hours": 0.0, "by_month": {}} for g in ("slow", "fast")
    }
    months: set[str] = set()
    used = skipped = 0
    for r in monthly:
        t = hours_of(r.get("chargingTime"))
        try:
            n = int(r["chargingCount"])
            hour = int(r["chargingStartHour"])
            kwh = float(r["chargingAmount"])
            month = str(r["baseYearMonth"])
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if t is None or n <= 0 or not 0 <= hour <= 23 or t <= 0 or kwh < 0 or len(month) != 6:
            skipped += 1
            continue
        g = groups[group_of(r.get("evChargerCategory"))]
        months.add(month)
        g["by_month"].setdefault(month, set()).add(charger_key(r))
        g["kwh"] += kwh
        g["hours"] += t
        for h, hrs in spread_busy_hours(hour, t / n).items():
            g["busy"][h] += n * hrs
        used += 1
    if not months:
        raise ValueError("no usable monthly rows")

    def charger_days(g) -> float:
        total = 0.0
        for month, ids in g["by_month"].items():
            total += len(ids) * calendar.monthrange(int(month[:4]), int(month[4:]))[1]
        return total

    out = {"months": sorted(months), "rows_used": used, "rows_skipped": skipped}
    for name, g in groups.items():
        denom = charger_days(g)
        if denom <= 0 or g["hours"] <= 0 or g["kwh"] <= 0:
            out[name] = None
            continue
        out[name] = {
            "avg_kw": g["kwh"] / g["hours"],
            "occupancy": [min(1.0, b / denom) for b in g["busy"]],
            "chargers_per_month_avg": sum(len(v) for v in g["by_month"].values())
            / len(g["by_month"]),
        }
    # 요일 보정은 월별·요일별 자료가 모두 있는 달만 쓴다(한쪽만 받은 달이 요일 비율을 왜곡하지 않게).
    both = sorted(months & {str(r.get("baseYearMonth")) for r in weekday})
    out["weekday_months"] = both
    out["weekday_factor"] = weekday_factors(
        [r for r in weekday if str(r.get("baseYearMonth")) in both], both
    )
    return out


def weekday_factors(rows: list[dict], months: list[str]) -> dict[str, float]:
    """요일별 하루 평균 충전 횟수 / 7요일 평균. 자료가 부족하면 모두 1.0."""
    counts = dict.fromkeys(WEEKDAYS, 0.0)
    for r in rows:
        day = str(r.get("baseDayOfTheWeek"))
        if day in counts:
            try:
                counts[day] += max(0, int(r["chargingCount"]))
            except (KeyError, TypeError, ValueError):
                continue
    occurrences = dict.fromkeys(WEEKDAYS, 0)
    for m in months:
        year, month = int(m[:4]), int(m[4:])
        for d in range(1, calendar.monthrange(year, month)[1] + 1):
            occurrences[WEEKDAYS[date(year, month, d).weekday()]] += 1
    per_day = {w: counts[w] / occurrences[w] for w in WEEKDAYS if occurrences[w]}
    mean = sum(per_day.values()) / len(per_day) if per_day else 0
    if len(per_day) != 7 or mean <= 0:
        return dict.fromkeys(WEEKDAYS, 1.0)
    return {w: per_day[w] / mean for w in WEEKDAYS}


def save_profile(profile: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")


def load_profile(path: Path) -> dict | None:
    """저장된 이용 패턴. 파일이 없거나 형식이 맞지 않으면 None."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        for g in ("slow", "fast"):
            if body[g] is None or len(body[g]["occupancy"]) != 24 or body[g]["avg_kw"] <= 0:
                return None
        if not isinstance(body["weekday_factor"], dict):
            return None
        return body
    except (OSError, ValueError, KeyError, TypeError):
        return None


def month_range(month: str) -> dict:
    """'YYYYMM'을 일별 API의 조회 구간(startDate, endDate = YYYYMMDD)으로 바꾼다."""
    last = calendar.monthrange(int(month[:4]), int(month[4:]))[1]
    return {"startDate": f"{month}01", "endDate": f"{month}{last:02d}"}


def _percentile(sorted_values: list[float], q: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def daily_summary(daily: list[dict], monthly: list[dict] | None = None) -> dict:
    """일별 이력으로 날짜별 변동을 요약하고, 월별 이력과 합계가 맞는지 확인한다.

    - 날짜별 총 충전량(kWh)·충전 횟수·충전 중인 충전기 수.
    - 혼잡한 날이 평균의 몇 배인가(p95, 최대), 달력 요일별 평균과 주말/평일 비율.
    - monthly를 주면 같은 달의 충전량·횟수 합계를 비교한다(데이터 정합성).
    """
    days: dict[str, dict] = {}
    skipped = 0
    for r in daily:
        try:
            day = str(r["baseDate"])
            kwh = float(r["chargingAmount"])
            n = int(r["chargingCount"])
            date(int(day[:4]), int(day[4:6]), int(day[6:8]))
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if kwh < 0 or n < 0:
            skipped += 1
            continue
        d = days.setdefault(day, {"kwh": 0.0, "count": 0, "chargers": set()})
        d["kwh"] += kwh
        d["count"] += n
        d["chargers"].add(charger_key(r))
    if not days:
        raise ValueError("no usable daily rows")
    kwh_sorted = sorted(d["kwh"] for d in days.values())
    mean = sum(kwh_sorted) / len(kwh_sorted)
    by_weekday: dict[str, list[float]] = {w: [] for w in WEEKDAYS}
    for day, d in days.items():
        wd = WEEKDAYS[date(int(day[:4]), int(day[4:6]), int(day[6:8])).weekday()]
        by_weekday[wd].append(d["kwh"])
    wd_mean = {w: sum(v) / len(v) for w, v in by_weekday.items() if v}
    weekday_avg = [wd_mean[w] for w in "월화수목금" if w in wd_mean]
    weekend_avg = [wd_mean[w] for w in "토일" if w in wd_mean]
    out = {
        "days": len(days),
        "rows_skipped": skipped,
        "mean_kwh_per_day": mean,
        "p95_ratio": _percentile(kwh_sorted, 0.95) / mean,
        "max_ratio": kwh_sorted[-1] / mean,
        "min_ratio": kwh_sorted[0] / mean,
        "mean_active_chargers_per_day": sum(len(d["chargers"]) for d in days.values()) / len(days),
        "weekday_mean_kwh": wd_mean,
        "weekend_over_weekday": (
            (sum(weekend_avg) / len(weekend_avg)) / (sum(weekday_avg) / len(weekday_avg))
            if weekend_avg and weekday_avg
            else None
        ),
    }
    if monthly is not None:
        m_kwh = sum(float(r.get("chargingAmount") or 0) for r in monthly)
        m_count = sum(int(r.get("chargingCount") or 0) for r in monthly)
        d_kwh = sum(d["kwh"] for d in days.values())
        d_count = sum(d["count"] for d in days.values())
        out["vs_monthly"] = {
            "kwh_daily": d_kwh,
            "kwh_monthly": m_kwh,
            "kwh_diff_pct": (d_kwh - m_kwh) / m_kwh * 100 if m_kwh else None,
            "count_daily": d_count,
            "count_monthly": m_count,
            "count_diff_pct": (d_count - m_count) / m_count * 100 if m_count else None,
        }
    return out
