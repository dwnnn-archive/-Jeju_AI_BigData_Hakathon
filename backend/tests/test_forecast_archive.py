import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.core.config import Settings
from app.domain.schemas import AnalysisRequest
from app.providers.kma import KmaProvider
from app.providers.kma_nowcast import KmaNowcastProvider
from app.repositories.forecasts import ForecastArchive
from app.tools.bundle import ToolBundle

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 11, 16, 21, 41, tzinfo=KST)


def _short_items():
    items = []
    for hour in (0, 1):
        for category, value in (("WSD", "7.2"), ("TMP", "18"), ("SKY", "1"), ("PCP", "강수없음")):
            items.append(
                {
                    "category": category,
                    "fcstDate": "20261117",
                    "fcstTime": f"{hour:02d}00",
                    "fcstValue": value,
                }
            )
    return items


def test_issue_is_stored_with_every_category_and_not_duplicated(tmp_path):
    archive = ForecastArchive(tmp_path / "f.sqlite")
    first = archive.record_issue("short", 46, 35, "20261116", "2300", _short_items())
    again = archive.record_issue("short", 46, 35, "20261116", "2300", _short_items())
    assert first == again  # 같은 발표는 다시 쓰지 않는다
    assert archive.counts() == {"issues": 1, "values": 8, "evaluations": 0}
    rows = {(r["valid_hour"], r["category"]): r for r in archive.values(first)}
    assert rows[(0, "WSD")]["value"] == 7.2 and rows[(0, "WSD")]["raw"] == "7.2"
    assert rows[(1, "PCP")]["value"] is None and rows[(1, "PCP")]["raw"] == "강수없음"
    assert rows[(0, "TMP")]["valid_date"] == "2026-11-17"
    other_grid = archive.record_issue("short", 53, 38, "20261116", "2300", _short_items())
    assert other_grid != first and archive.counts()["issues"] == 2


def test_ultra_observation_uses_base_time_as_valid_time(tmp_path):
    archive = ForecastArchive(tmp_path / "f.sqlite")
    items = [
        {"baseDate": "20261116", "baseTime": "2100", "category": "WSD", "obsrValue": "1.7"},
        {"baseDate": "20261116", "baseTime": "2100", "category": "T1H", "obsrValue": "17.3"},
    ]
    issue = archive.record_issue("ultra_ncst", 46, 35, "20261116", "2100", items)
    rows = archive.values(issue)
    assert {(r["valid_date"], r["valid_hour"], r["category"]) for r in rows} == {
        ("2026-11-16", 21, "WSD"),
        ("2026-11-16", 21, "T1H"),
    }
    with pytest.raises(ValueError, match="Unknown"):
        archive.record_issue("nope", 1, 1, "20261116", "2100", [])


def test_evaluation_keeps_result_inputs_and_model_info(tmp_path):
    archive = ForecastArchive(tmp_path / "f.sqlite")
    result = {
        "date": "2026-11-17",
        "risk": "CAUTION",
        "peak_ratio": 0.42,
        "peak_surplus_mwh": 12.5,
        "peak_hour": 12,
        "from_hour": 7,
        "hourly": [{"hour": 0, "ratio": 0.1}],
    }
    archive.record_evaluation(
        "run-1", "intraday", 2, result, {"sources": {"7": "nowcast"}}, {"a": 1}
    )
    [row] = archive.evaluations("run-1")
    assert (row["phase"], row["check_no"], row["risk"], row["from_hour"]) == (
        "intraday",
        2,
        "CAUTION",
        7,
    )
    assert json.loads(row["result_json"])["hourly"][0]["ratio"] == 0.1
    assert json.loads(row["inputs_json"])["sources"]["7"] == "nowcast"
    assert json.loads(row["models_json"]) == {"a": 1}
    assert archive.evaluations("other") == []


def test_safe_methods_never_raise(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("파일이라 폴더를 만들 수 없다")
    archive = ForecastArchive(blocker / "f.sqlite")
    archive.safe_record_issue("short", 1, 1, "20261116", "2300", [])  # 예외 없이 통과
    archive.safe_record_evaluation("r", "day_ahead", 0, {"date": "2026-11-17"})
    with pytest.raises(Exception):  # noqa: B017 - 안전 버전이 아닌 쪽은 오류를 그대로 낸다
        archive.record_issue("short", 1, 1, "20261116", "2300", [])


def _transport(items):
    def handler(req):
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00"},
                    "body": {"items": {"item": items}, "totalCount": len(items)},
                }
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_short_provider_records_the_raw_items_it_fetched():
    calls = []
    items = [
        {"category": c, "fcstDate": "20261117", "fcstTime": f"{h:02d}00", "fcstValue": v}
        for h in range(24)
        for c, v in (("WSD", "5"), ("TMP", "10"), ("SKY", "1"), ("POP", "20"))
    ]
    provider = KmaProvider(
        "k", _transport(items), recorder=lambda *a: calls.append(a), auth_param="serviceKey"
    )
    provider.fetch(date(2026, 11, 17), 33.5, 126.5, grid=(46, 35), base=("20261116", "2300"))
    [(source, nx, ny, bd, bt, recorded)] = calls
    assert (source, nx, ny, bd, bt) == ("short", 46, 35, "20261116", "2300")
    assert len(recorded) == 96 and {i["category"] for i in recorded} == {"WSD", "TMP", "SKY", "POP"}


def test_nowcast_provider_records_observation_and_forecast_separately():
    calls = []
    fcst = [
        {"category": c, "fcstDate": "20261116", "fcstTime": "2200", "fcstValue": v}
        for c, v in (("WSD", "3"), ("T1H", "17"), ("SKY", "4"))
    ]
    ncst = [
        {"baseDate": "20261116", "baseTime": "2100", "category": c, "obsrValue": v}
        for c, v in (("WSD", "1.7"), ("T1H", "17.3"))
    ]

    def handler(req):
        items = fcst if req.url.path.endswith("getUltraSrtFcst") else ncst
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00"},
                    "body": {"items": {"item": items}, "totalCount": len(items)},
                }
            },
        )

    provider = KmaNowcastProvider(
        "k",
        httpx.Client(transport=httpx.MockTransport(handler)),
        recorder=lambda *a: calls.append(a),
    )
    provider.observation(46, 35, NOW)
    provider.forecast(46, 35, NOW)
    assert [(c[0], c[3], c[4]) for c in calls] == [
        ("ultra_ncst", "20261116", "2100"),
        ("ultra_fcst", "20261116", "2030"),
    ]


def test_bundle_archive_follows_settings(tmp_path):
    off = ToolBundle(Settings(_env_file=None, database_path=tmp_path / "a.sqlite"))
    assert off.archive is None  # conftest 가 기본으로 끈다
    on = ToolBundle(
        Settings(_env_file=None, database_path=tmp_path / "b.sqlite", forecast_archive_enabled=True)
    )
    assert on.archive is not None and on.archive.path == tmp_path / "forecasts.sqlite"
    custom = ToolBundle(
        Settings(
            _env_file=None,
            forecast_archive_enabled=True,
            forecast_archive_path=tmp_path / "x" / "custom.sqlite",
        )
    )
    assert custom.archive.path == tmp_path / "x" / "custom.sqlite"
    on.log_evaluation(
        "run-9",
        "day_ahead",
        0,
        {
            "date": "2026-11-17",
            "risk": "NORMAL",
            "peak_ratio": 0.1,
            "peak_surplus_mwh": 0,
            "peak_hour": 3,
        },
    )
    assert on.archive.counts()["evaluations"] == 1
    request = AnalysisRequest(date="2026-11-17", region="jeju", mode="demo")
    assert request.phase == "day_ahead"
