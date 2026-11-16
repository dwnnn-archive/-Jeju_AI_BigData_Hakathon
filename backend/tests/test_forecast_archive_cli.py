import csv
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.core.config import Settings
from app.repositories.forecasts import ForecastArchive
from scripts.forecast_archive import collect, export_dataset, summarize_errors

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 11, 16, 21, 41, tzinfo=KST)


def _settings(**extra):
    return Settings(
        _env_file=None,
        kma_api_key="k",
        kma_base_url="https://example.test/svc",
        kma_auth_param="serviceKey",
        **extra,
    )


def _items(op):
    if op == "getUltraSrtNcst":
        return [
            {"baseDate": "20261116", "baseTime": "2100", "category": c, "obsrValue": v}
            for c, v in (("WSD", "1.7"), ("T1H", "17.3"), ("REH", "60"))
        ]
    if op == "getUltraSrtFcst":
        return [
            {"fcstDate": "20261116", "fcstTime": "2200", "category": c, "fcstValue": v}
            for c, v in (("WSD", "3"), ("T1H", "17"), ("SKY", "4"), ("POP", "0"))
        ]
    return [
        {"fcstDate": "20261117", "fcstTime": f"{h:02d}00", "category": c, "fcstValue": v}
        for h in range(3)
        for c, v in (("WSD", "6.1"), ("TMP", "15"), ("SKY", "3"), ("PCP", "강수없음"))
    ]


def _client(fail=None, seen=None):
    def handler(req):
        op = req.url.path.rsplit("/", 1)[-1]
        if seen is not None:
            seen.append((op, req.url.params["nx"]))
        if op == fail:
            return httpx.Response(500, text="boom")
        items = _items(op)
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


def test_collect_stores_three_sources_for_both_grids_and_is_idempotent(tmp_path):
    archive = ForecastArchive(tmp_path / "f.sqlite")
    seen = []
    result = collect(_settings(), archive, NOW, client=_client(seen=seen))
    assert result == {"new_issues": 6, "errors": []}  # 격자 2개 x (단기, 초단기예보, 초단기실황)
    assert {nx for _, nx in seen} == {"46", "53"}
    sources = {(i["source"], i["nx"]) for i in archive.issues()}
    assert sources == {(s, nx) for s in ("short", "ultra_fcst", "ultra_ncst") for nx in (46, 53)}
    again = collect(_settings(), archive, NOW, client=_client())
    assert again == {"new_issues": 0, "errors": []}  # 스케줄러가 겹쳐 돌아도 중복 저장 없음


def test_collect_keeps_going_when_one_call_fails_and_never_leaks_the_url(tmp_path):
    archive = ForecastArchive(tmp_path / "f.sqlite")
    result = collect(_settings(), archive, NOW, client=_client(fail="getUltraSrtFcst"))
    assert result["new_issues"] == 4
    assert result["errors"] == [
        "gosan/ultra_fcst: HTTPStatusError",
        "jeju_city/ultra_fcst: HTTPStatusError",
    ]
    assert "example.test" not in str(result)


def test_collect_requires_a_key(tmp_path):
    with pytest.raises(ValueError, match="kma_key_missing"):
        collect(Settings(_env_file=None), ForecastArchive(tmp_path / "f.sqlite"), NOW)


def _seed(tmp_path):
    archive = ForecastArchive(tmp_path / "f.sqlite")
    items = [
        {"fcstDate": "20261116", "fcstTime": f"{h:02d}00", "category": c, "fcstValue": v}
        for h in range(3)
        for c, v in (("WSD", "5"), ("TMP", "10"), ("SKY", "1"), ("PCP", "강수없음"))
    ]
    archive.record_issue("short", 46, 35, "20261115", "2300", items)
    archive.record_issue("short", 99, 99, "20261115", "2300", items)  # 실측 지점이 없는 격자
    asos = tmp_path / "asos" / "monthly"
    asos.mkdir(parents=True)
    lines = ["timestamp,wind_ms,temperature_c,irradiance_wm2,cloud_tenths"]
    lines += [f"2026-11-16T{h:02d}:00:00+09:00,4.0,11.0,,7.0" for h in range(3)]
    (asos / "185_2026-11.csv").write_text("\n".join(lines), encoding="utf-8")
    return archive, tmp_path / "asos"


def test_export_joins_forecasts_with_observations_and_lead_hours(tmp_path):
    archive, asos = _seed(tmp_path)
    out = tmp_path / "dataset.csv"
    assert export_dataset(archive, asos, out) == 24  # 발표 2개 x 3시간 x 항목 4개
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    wsd = next(
        r for r in rows if r["category"] == "WSD" and r["nx"] == "46" and r["valid_hour"] == "0"
    )
    assert (wsd["forecast"], wsd["observed_wind_ms"], wsd["lead_hours"]) == ("5.0", "4.0", "1.0")
    sky = next(
        r for r in rows if r["category"] == "SKY" and r["nx"] == "46" and r["valid_hour"] == "1"
    )
    assert (sky["forecast"], sky["observed_sky"], sky["lead_hours"]) == (
        "1.0",
        "3",
        "2.0",
    )  # 전운량 7 -> 3
    pcp = next(r for r in rows if r["category"] == "PCP" and r["nx"] == "46")
    assert pcp["forecast"] == "" and pcp["raw"] == "강수없음"
    other = next(r for r in rows if r["nx"] == "99")
    assert other["observed_wind_ms"] == "" and other["observed_sky"] == ""  # 실측이 없는 격자


def test_error_summary_reports_bias_mae_and_sky_accuracy_by_lead(tmp_path):
    archive, asos = _seed(tmp_path)
    out = tmp_path / "dataset.csv"
    export_dataset(archive, asos, out)
    summary = {(s["category"], s["lead"]): s for s in summarize_errors(out)}
    wsd = summary[("WSD", "0-2h")]
    assert wsd["n"] == 2 and wsd["mae"] == pytest.approx(1.0) and wsd["bias"] == pytest.approx(1.0)
    tmp = summary[("TMP", "0-2h")]
    assert tmp["bias"] == pytest.approx(-1.0)  # 예보 10, 실측 11
    assert summary[("SKY", "0-2h")]["accuracy"] == 0.0  # 예보 1, 실측 3
    assert ("PCP", "0-2h") not in summary  # 비교 대상이 아닌 항목은 제외
