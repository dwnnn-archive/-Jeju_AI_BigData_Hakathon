from datetime import datetime, timedelta

import httpx
import pytest

from app.providers.asos import KST, AsosProvider

START = datetime(2025, 1, 20, 0, tzinfo=KST)
END = datetime(2025, 1, 20, 23, tzinfo=KST)


def _item(hour, **over):
    base = {
        "tm": f"2025-01-20 {hour:02d}:00",
        "stnId": "185",
        "ta": "3.6",
        "taQcflg": "",
        "ws": "7.2",
        "wsQcflg": "",
        "icsr": "1.8",
    }
    base.update(over)
    return base


def _client(items, code="00", seen=None):
    def handler(req):
        q = req.url.params
        if seen is not None:
            seen.append(dict(q))
        size, page = int(q["numOfRows"]), int(q["pageNo"])
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": code, "resultMsg": "NORMAL_SERVICE"},
                    "body": {
                        "items": {"item": items[(page - 1) * size : page * size]},
                        "totalCount": len(items),
                    },
                }
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parses_units_and_request_shape():
    seen = []
    rows = AsosProvider("k", _client([_item(h) for h in range(24)], seen=seen)).fetch(
        185, START, END
    )
    assert len(rows) == 24 and rows[0].station_id == 185
    assert rows[0].timestamp == START and rows[0].wind_ms == 7.2
    # 1.8 MJ/m2 per hour → 500 W/m2 average.
    assert rows[0].irradiance_wm2 == pytest.approx(500)
    q = seen[0]
    assert (q["dataCd"], q["dateCd"], q["stnIds"]) == ("ASOS", "HR", "185")
    assert (q["startDt"], q["startHh"], q["endDt"], q["endHh"]) == (
        "20250120",
        "00",
        "20250120",
        "23",
    )


def test_quality_flags_and_blank_values_become_none():
    items = [
        _item(0, wsQcflg="9", ws=""),  # 결측
        _item(1, taQcflg="1"),  # 오류
        _item(2, icsr=""),
        _item(3),
    ]
    rows = AsosProvider("k", _client(items)).fetch(185, START, START + timedelta(hours=3))
    assert rows[0].wind_ms is None and rows[0].temperature_c == 3.6
    assert rows[1].temperature_c is None and rows[1].wind_ms == 7.2
    assert rows[2].irradiance_wm2 is None
    assert rows[3].wind_ms == 7.2


def test_zero_flag_is_normal_for_pre_2019_records():
    # 실제 API: 2017~2018 자료는 정상 플래그가 "0"이다(가이드는 null로 표기).
    rows = AsosProvider("k", _client([_item(0, wsQcflg="0", taQcflg="0")])).fetch(185, START, START)
    assert rows[0].wind_ms == 7.2 and rows[0].temperature_c == 3.6


def test_paginates_and_accepts_guide_example_result_code():
    seen = []
    items = [_item(h) for h in range(24)]
    rows = AsosProvider("k", _client(items, code="0", seen=seen), page_size=10).fetch(
        185, START, END
    )
    assert len(rows) == 24 and len(seen) == 3


def test_rejects_error_code_duplicates_and_today():
    with pytest.raises(ValueError):
        AsosProvider("k", _client([_item(0)], code="03")).fetch(185, START, END)
    with pytest.raises(ValueError):
        AsosProvider("k", _client([_item(0), _item(0)])).fetch(185, START, END)
    now = datetime.now(KST)
    with pytest.raises(ValueError):  # D-1까지만 제공
        AsosProvider("k", _client([])).fetch(185, now - timedelta(hours=1), now)
