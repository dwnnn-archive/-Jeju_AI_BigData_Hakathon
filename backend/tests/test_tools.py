from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.core.config import Settings
from app.domain.schemas import AnalysisRequest, WeatherHour
from app.providers.kma import KmaProvider, grid_coordinates, issue_time
from app.providers.kpx import KpxProvider
from app.tools.bundle import ToolBundle
from app.tools.tool1_kma_weather import COORDINATES, GRID, parse_request
from app.tools.tool2_predict_generation import load_plants, physical_prediction, wind_factor

DAY = date(2026, 11, 14)


def test_kma_reference_grid_and_issue_delay():
    assert grid_coordinates(37.5665, 126.9780) == (60, 127)
    assert issue_time(datetime(2026, 11, 14, 2, 5, tzinfo=ZoneInfo("Asia/Seoul"))) == (
        "20261113",
        "2300",
    )


@pytest.mark.parametrize("speed,expected", [(0, 0), (3, 0), (12, 1), (24.9, 1), (25, 0)])
def test_wind_cutout_and_rated_output(speed, expected):
    assert wind_factor(speed) == expected


def test_physics_model_units_and_night_solar():
    weather = [
        WeatherHour(date=DAY, hour=h, wind_ms=12, temperature_c=25, sky=1, irradiance_wm2=0)
        for h in range(24)
    ]
    assert physical_prediction(weather, 70, 30)[0].mwh == 70
    weather[12].irradiance_wm2 = 1000
    assert physical_prediction(weather, 70, 30)[12].mwh == 100


def test_manual_correction_upserts_instead_of_double_counting(tmp_path):
    base = tmp_path / "plants.json"
    corrections = tmp_path / "corrections.json"
    base.write_text('[{"id":"a","kind":"wind","capacity_mw":10,"source":"base"}]')
    corrections.write_text('[{"id":"a","kind":"wind","capacity_mw":15,"source":"corrected"}]')
    assert load_plants(base, corrections)[0].capacity_mw == 15


def test_query_resolves_kst_tomorrow_and_region():
    request = parse_request(AnalysisRequest(query="내일 한림 출력제한 분석"), date(2026, 11, 13))
    assert request.date == DAY
    assert request.region == "hallim"
    with pytest.raises(ValueError):
        parse_request(AnalysisRequest(query="언젠가 분석"))
    with pytest.raises(ValueError):
        parse_request(AnalysisRequest(query="2026-11-14 한림 조천 분석"))


def _kma_client(items, code="00", page_size=None, seen=None):
    def handler(req):
        q = req.url.params
        if seen is not None:
            seen.append((str(req.url).split("?")[0], dict(q)))
        size, page = int(q["numOfRows"]), int(q["pageNo"])
        chunk = items[(page - 1) * size : page * size]
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": code, "resultMsg": "NORMAL_SERVICE"},
                    "body": {"items": {"item": chunk}, "totalCount": len(items)},
                }
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _kma_items(wsd="12", tmp="20"):
    return [
        {"fcstDate": "20261114", "fcstTime": f"{h:02d}00", "category": c, "fcstValue": v}
        for h in range(24)
        for c, v in [("WSD", wsd), ("TMP", tmp), ("SKY", "1")]
    ]


def test_kma_parses_all_hours_and_marks_irradiance_estimated():
    seen = []
    rows = KmaProvider("test", _kma_client(_kma_items(), seen=seen)).fetch(
        DAY, 33.5, 126.5, grid=(53, 38)
    )
    assert len(rows) == 24
    assert rows[0].wind_ms == 12
    assert rows[0].irradiance_wm2 == 0
    assert rows[12].irradiance_wm2 > 0
    url, params = seen[0]
    assert url == (
        "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
    )
    assert params["authKey"] == "test" and "serviceKey" not in params
    assert (params["nx"], params["ny"], params["dataType"]) == ("53", "38", "JSON")


def test_kma_accepts_guide_example_result_code_and_paginates():
    seen = []
    client = _kma_client(_kma_items(), code="0", seen=seen)
    rows = KmaProvider("k", client, page_size=20).fetch(DAY, 33.5, 126.5)
    assert len(rows) == 24
    assert len(seen) > 1  # 72 rows / 20 per page


def test_kma_service_key_param_and_custom_base_url():
    seen = []
    KmaProvider(
        "k",
        _kma_client(_kma_items(), seen=seen),
        base_url="https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/",
        auth_param="serviceKey",
    ).fetch(DAY, 33.5, 126.5)
    url, params = seen[0]
    assert url.endswith("/VilageFcstInfoService_2.0/getVilageFcst")
    assert "serviceKey" in params and "authKey" not in params


@pytest.mark.parametrize("bad", ["-999", "999", "900"])
def test_kma_rejects_missing_values(bad):
    with pytest.raises(ValueError):
        KmaProvider("k", _kma_client(_kma_items(tmp=bad))).fetch(DAY, 33.5, 126.5)


def test_kma_rejects_error_result_code():
    with pytest.raises(ValueError):
        KmaProvider("k", _kma_client(_kma_items(), code="03")).fetch(DAY, 33.5, 126.5)


def test_kma_extended_days_with_three_hour_steps_are_rejected():
    items = [
        {"fcstDate": "20261114", "fcstTime": f"{h:02d}00", "category": c, "fcstValue": v}
        for h in range(0, 24, 3)
        for c, v in [("WSD", "2"), ("TMP", "20"), ("SKY", "1")]
    ]
    with pytest.raises(ValueError):
        KmaProvider("k", _kma_client(items)).fetch(DAY, 33.5, 126.5)


def test_official_grid_matches_guide_workbook_and_formula():
    assert grid_coordinates(37.488201, 126.929810) == (59, 125)  # 가이드 C 예제
    assert GRID == {"jeju": (53, 38), "hallim": (48, 36), "jocheon": (55, 39), "haengwon": (59, 38)}
    for region in ("jeju", "hallim", "jocheon"):
        assert grid_coordinates(*COORDINATES[region]) == GRID[region]


def test_kpx_contract_rejects_duplicate_hours():
    rows = [{"date": DAY.isoformat(), "hour": 0, "mwh": 500} for _ in range(24)]
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"hours": rows}))
    )
    with pytest.raises(ValueError):
        KpxProvider("https://example.com/demand", client).fetch(DAY)


def test_live_missing_credentials_falls_back_explicitly_or_fails_closed():
    request = AnalysisRequest(date=DAY, region="jeju", mode="live")
    bundle = ToolBundle(Settings(allow_mock_fallback=True))
    rows, source = bundle.weather(request, 0)
    assert len(rows) == 24
    assert source["simulated"] is True
    assert source["reason"] == "kma_key_missing"
    with pytest.raises(ValueError):
        ToolBundle(Settings(allow_mock_fallback=False)).weather(request, 0)


def test_demo_boundary_refresh_changes_only_demo_forecast():
    bundle = ToolBundle(Settings())
    req = AnalysisRequest(date=DAY, region="jeju", scenario="boundary")
    weather, _ = bundle.weather(req, 0)
    assert bundle.generation(req, weather, 0)[0][12].mwh == 308
    assert bundle.generation(req, weather, 1)[0][12].mwh == 510
