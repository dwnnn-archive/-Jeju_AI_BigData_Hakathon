import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.schemas import AnalysisRequest

REGIONS = {"제주": "jeju", "한림": "hallim", "조천": "jocheon", "행원": "haengwon"}
COORDINATES = {
    "jeju": (33.4996, 126.5312),
    "hallim": (33.410, 126.267),
    "jocheon": (33.535, 126.634),
    "haengwon": (33.556, 126.811),
}


def parse_request(request: AnalysisRequest, today: date | None = None) -> AnalysisRequest:
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    query = request.query or ""
    dates = {date.fromisoformat(s) for s in re.findall(r"\d{4}-\d{2}-\d{2}", query)}
    if "내일" in query:
        dates.add(today + timedelta(days=1))
    if "오늘" in query:
        dates.add(today)
    if len(dates) > 1 or (dates and request.date and request.date not in dates):
        raise ValueError("Specify one unambiguous analysis date")
    target = request.date or (next(iter(dates)) if dates else None)
    if target is None:
        raise ValueError("Provide date or a query containing 오늘/내일/YYYY-MM-DD")
    regions = {value for key, value in REGIONS.items() if key in query and key != "제주"}
    if len(regions) > 1 or (regions and request.region and request.region not in regions):
        raise ValueError("Specify one unambiguous Jeju region")
    region = request.region or (next(iter(regions)) if regions else "jeju")
    return request.model_copy(update={"date": target, "region": region})
