from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.providers.kma_nowcast import (
    KmaNowcastProvider,
    forecast_base,
    observation_base,
)

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 11, 16, 21, 41, tzinfo=KST)


def test_base_times_follow_publication_delay():
    assert observation_base(NOW) == ("20261116", "2100")  # 정시 자료는 10분 뒤부터
    assert forecast_base(NOW) == ("20261116", "2030")  # 초단기예보는 45분 뒤부터
    assert forecast_base(datetime(2026, 11, 16, 7, 50, tzinfo=KST)) == ("20261116", "0730")
    assert forecast_base(datetime(2026, 11, 16, 7, 30, tzinfo=KST)) == ("20261116", "0630")
    # 자정 직후에는 전날 23:30 발표분을 쓴다
    assert forecast_base(datetime(2026, 11, 16, 0, 20, tzinfo=KST)) == ("20261115", "2330")


def _fcst_items(skip=None, hours=((16, 21), (16, 22), (16, 23), (17, 0), (17, 1), (17, 2))):
    items = []
    for day, hour in hours:
        for category, value in (("WSD", "3"), ("T1H", "17"), ("SKY", "4"), ("LGT", "0")):
            if category == skip:
                continue
            items.append(
                {
                    "baseDate": "20261116",
                    "baseTime": "2030",
                    "category": category,
                    "fcstDate": f"202611{day}",
                    "fcstTime": f"{hour:02d}00",
                    "fcstValue": value,
                }
            )
    return items


def _ncst_items(wsd="1.7", t1h="17.3"):
    return [
        {"baseDate": "20261116", "baseTime": "2100", "category": c, "obsrValue": v}
        for c, v in (("T1H", t1h), ("WSD", wsd), ("REH", "60"))
    ]


def _provider(fcst, ncst, seen=None):
    def handler(req):
        op = req.url.path.rsplit("/", 1)[-1]
        items = fcst if op == "getUltraSrtFcst" else ncst
        if seen is not None:
            seen.append((op, dict(req.url.params)))
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                    "body": {"items": {"item": items}, "totalCount": len(items)},
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return KmaNowcastProvider("k", client, "https://example.test/svc", "serviceKey")


def test_observation_and_forecast_are_parsed_with_base_params():
    seen = []
    provider = _provider(_fcst_items(), _ncst_items(), seen)
    obs = provider.observation(46, 35, NOW)
    assert (obs.date, obs.hour, obs.wind_ms, obs.temperature_c, obs.sky) == (
        date(2026, 11, 16),
        21,
        1.7,
        17.3,
        None,
    )
    rows = provider.forecast(46, 35, NOW)
    assert [(r.date.day, r.hour) for r in rows] == [
        (16, 21),
        (16, 22),
        (16, 23),
        (17, 0),
        (17, 1),
        (17, 2),
    ]
    assert rows[0].wind_ms == 3 and rows[0].temperature_c == 17 and rows[0].sky == 4
    ops = {op: p for op, p in seen}
    assert (ops["getUltraSrtNcst"]["base_date"], ops["getUltraSrtNcst"]["base_time"]) == (
        "20261116",
        "2100",
    )
    assert (ops["getUltraSrtFcst"]["base_time"], ops["getUltraSrtFcst"]["nx"]) == ("2030", "46")
    assert "serviceKey" in ops["getUltraSrtFcst"] and "authKey" not in ops["getUltraSrtFcst"]


@pytest.mark.parametrize("missing", ["WSD", "T1H", "SKY"])
def test_forecast_hour_without_required_category_is_rejected(missing):
    with pytest.raises(ValueError):
        _provider(_fcst_items(skip=missing), _ncst_items()).forecast(46, 35, NOW)


def test_missing_marker_and_non_hourly_times_and_empty_results_are_rejected():
    bad = _fcst_items()
    bad[0] = {**bad[0], "fcstValue": "-999"}
    with pytest.raises(ValueError, match="missing"):
        _provider(bad, _ncst_items()).forecast(46, 35, NOW)
    half = _fcst_items()
    half[0] = {**half[0], "fcstTime": "2130"}
    with pytest.raises(ValueError, match="hourly"):
        _provider(half, _ncst_items()).forecast(46, 35, NOW)
    with pytest.raises(ValueError):
        _provider([], _ncst_items()).forecast(46, 35, NOW)
    with pytest.raises(ValueError):
        _provider(_fcst_items(), _ncst_items(wsd="999")).observation(46, 35, NOW)
    with pytest.raises(ValueError, match="missing wind or temperature"):
        _provider(_fcst_items(), [i for i in _ncst_items() if i["category"] != "T1H"]).observation(
            46, 35, NOW
        )
