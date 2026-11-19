import httpx
import pytest

from app.core.config import Settings
from app.providers.jejuhub_ev import (
    ev_capacity,
    fetch_stations,
    load_snapshot,
    parse_station,
    save_snapshot,
)
from app.tools.bundle import ToolBundle


def row(name="A", slow=2, fast=1, start="00:00", end="23:59"):
    return {
        "chargingPlace": name,
        "chargingPlaceDetail": "주차장",
        "startTime": start,
        "endTime": end,
        "chargerCount": slow,
        "quickChargerCount": fast,
        "latitude": 33.2,
        "longitude": 126.5,
        "provider": "제주특별자치도",
        "baseDate": "20200630",
    }


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_collects_all_pages_and_sends_paging():
    seen = []

    def handler(request):
        page = int(request.url.params["number"])
        seen.append((page, request.url.params["limit"]))
        data = [row(f"S{page}-{i}") for i in range(2)]
        return httpx.Response(200, json={"totCnt": 4, "hasMore": page < 2, "data": data})

    stations = fetch_stations("KEY", client=client_for(handler), base_url="https://hub.test/p")
    assert [s.name for s in stations] == ["S1-0", "S1-1", "S2-0", "S2-1"]
    assert seen == [(1, "100"), (2, "100")]


def test_fetch_retries_timeout_and_never_leaks_key():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(RuntimeError) as err:
        fetch_stations("SECRETKEY", client=client_for(handler), base_url="https://hub.test/p")
    assert calls["n"] == 3  # 처음 1회 + 재시도 2회
    assert "SECRETKEY" not in str(err.value)


def test_fetch_recovers_after_transient_server_error():
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"totCnt": 1, "hasMore": False, "data": [row()]})

    assert len(fetch_stations("K", client=client_for(handler), base_url="https://hub.test/p")) == 1


def test_fetch_rejects_client_error_and_bad_shape():
    with pytest.raises(RuntimeError, match="HTTP 401"):
        fetch_stations(
            "K", client=client_for(lambda r: httpx.Response(401)), base_url="https://h/p"
        )
    with pytest.raises(RuntimeError, match="no data list"):
        fetch_stations(
            "K",
            client=client_for(lambda r: httpx.Response(200, json={"hasMore": False})),
            base_url="https://h/p",
        )


def test_capacity_counts_only_open_stations_and_applies_assumptions():
    stations = [
        parse_station(row("always", slow=2, fast=1)),  # 2*7 + 50 = 64 kW
        parse_station(row("daytime", slow=10, fast=0, start="09:00", end="18:00")),  # 70 kW
        parse_station(row("night", slow=4, fast=0, start="22:00", end="06:00")),  # 28 kW
        parse_station(row("broken", slow=9, fast=9, start="??", end="23:59")),  # 해석 불가 → 제외
    ]
    noon = ev_capacity(stations, 12)
    assert noon["stations_open"] == 2
    assert noon["installed_mwh"] == pytest.approx((64 + 70) / 1000)
    assert noon["capacity_mwh"] == pytest.approx((64 + 70) / 1000 * 0.5)
    assert ev_capacity(stations, 23)["stations_open"] == 2  # always + night(자정 넘김)
    assert ev_capacity(stations, 3)["installed_mwh"] == pytest.approx((64 + 28) / 1000)
    assert ev_capacity(stations, 18)["stations_open"] == 1  # 18시는 daytime 종료 18:00이라 제외


def test_capacity_rejects_bad_arguments():
    with pytest.raises(ValueError):
        ev_capacity([], 24)
    with pytest.raises(ValueError):
        ev_capacity([], 12, idle_ratio=1.5)


def test_parse_is_tolerant_of_missing_fields():
    s = parse_station({"chargingPlace": " X "})
    assert (s.name, s.slow_count, s.fast_count, s.start_minute) == ("X", 0, 0, None)
    assert parse_station({"chargerCount": "-3"}).slow_count == 0


def test_snapshot_roundtrip_and_missing_or_broken(tmp_path):
    path = tmp_path / "ev.json"
    assert load_snapshot(path) is None
    save_snapshot([parse_station(row("A"))], path)
    stations, fetched_at = load_snapshot(path)
    assert stations[0].name == "A" and fetched_at
    path.write_text("{broken", encoding="utf-8")
    assert load_snapshot(path) is None


def test_bundle_input_is_none_without_snapshot_and_real_with_it(tmp_path):
    path = tmp_path / "ev.json"
    bundle = ToolBundle(Settings(ev_snapshot_path=path))
    assert bundle.ev_allocation_input(12) is None
    save_snapshot([parse_station(row(slow=2, fast=1))], path)
    got = bundle.ev_allocation_input(12)
    assert got["capacity_mwh"] == pytest.approx(0.064 * 0.5)
    assert got["fetched_at"]


def test_real_world_time_formats_and_restricted_stations():
    # 실제 응답: 앞자리 0 없음("0:00"), 초 포함("24:00:00"), "알 수 없음", 전용 주차장.
    stations = [
        parse_station({**row("24h", slow=2, fast=0), "startTime": "0:00", "endTime": "24:00:00"}),
        parse_station({**row("nine", slow=1, fast=0), "startTime": "9:00", "endTime": "18:00"}),
        parse_station(
            {**row("unknown", slow=5, fast=5), "startTime": "알 수 없음", "endTime": "알 수 없음"}
        ),
        parse_station({**row("resident", slow=9, fast=0), "holiday": "입주민 전용"}),
        parse_station({**row("outsider", slow=9, fast=0), "holiday": "외부인 출입제한"}),
    ]
    assert stations[0].start_minute == 0 and stations[0].end_minute == 1439
    noon = ev_capacity(stations, 12)
    assert noon["stations_open"] == 2  # 24h + nine
    assert noon["slow_chargers"] == 3
    assert noon["stations_hours_unknown"] == 1 and noon["stations_restricted"] == 2
    assert ev_capacity(stations, 23)["stations_open"] == 1  # 23시에는 24h 만
    assert ev_capacity(stations, 0)["stations_open"] == 1


def _st(name, slow, fast, start="0:00", end="24:00:00", holiday="연중무휴"):
    return parse_station(
        {
            "chargingPlace": name,
            "startTime": start,
            "endTime": end,
            "chargerCount": slow,
            "quickChargerCount": fast,
            "holiday": holiday,
            "latitude": 33.1,
            "longitude": 126.4,
        }
    )


def test_top_stations_ranked_by_capacity_and_filtered():
    stations = [
        _st("작은곳", 2, 0),  # 14kW
        _st("급속큰곳", 0, 4),  # 200kW
        _st("완속많은곳", 20, 0),  # 140kW
        _st("낮에만", 50, 50, start="18:00", end="22:00"),  # 12시에는 닫힘
        _st("입주민", 99, 99, holiday="입주민 전용"),  # 일반 이용 불가
        _st("시간불명", 9, 9, start="알 수 없음", end="알 수 없음"),
    ]
    got = ev_capacity(stations, 12, top_n=3)
    names = [t["name"] for t in got["top_stations"]]
    assert names == ["급속큰곳", "완속많은곳", "작은곳"]
    top = got["top_stations"][0]
    # 가정 경로: 설치 용량 x 이용률(0.5)
    assert top["capacity_mwh"] == pytest.approx(0.2 * 0.5)
    assert top["fast_chargers"] == 4 and top["latitude"] == 33.1
    assert sum(t["share"] for t in got["top_stations"]) == pytest.approx(1.0)  # 후보가 3곳뿐
    assert ev_capacity(stations, 12, top_n=2)["top_stations"][1]["name"] == "완속많은곳"
    assert ev_capacity(stations, 12, top_n=0)["top_stations"] == []
    assert ev_capacity(stations, 20, top_n=1)["top_stations"][0]["name"] == "낮에만"


def test_top_stations_empty_when_nothing_is_open():
    got = ev_capacity([_st("닫힘", 3, 3, start="9:00", end="10:00")], 3)
    assert got["top_stations"] == [] and got["capacity_mwh"] == 0


def test_top_station_ties_are_deterministic_by_name():
    stations = [_st("나", 2, 0), _st("가", 2, 0), _st("다", 2, 0)]
    assert [t["name"] for t in ev_capacity(stations, 12)["top_stations"]] == ["가", "나", "다"]


def test_rows_per_charge_type_are_counted_once():
    # 실제 API: 충전 방식별로 행이 나뉘고 충전소 전체 충전기 수가 행마다 반복된다.
    base = {
        "chargingPlace": "의귀융복합충전스테이션",
        "latitude": 33.3,
        "longitude": 126.7,
        "chargerCount": 3,
        "quickChargerCount": 15,
        "startTime": "0:00",
        "endTime": "24:00:00",
    }
    rows = [{**base, "quickChargingType": t} for t in ("DC차데모+AC3상+DC콤보", "DC콤보", "AC완속")]
    other = {**base, "chargingPlace": "다른곳", "chargerCount": 1, "quickChargerCount": 0}

    def handler(request):
        return httpx.Response(200, json={"totCnt": 4, "hasMore": False, "data": rows + [other]})

    stations = fetch_stations("K", client=client_for(handler), base_url="https://h/p")
    assert [s.name for s in stations] == ["의귀융복합충전스테이션", "다른곳"]
    got = ev_capacity(stations, 12)
    assert (got["slow_chargers"], got["fast_chargers"]) == (4, 15)  # 3행이 아니라 한 번만 센다


def test_old_snapshot_with_repeated_rows_is_deduped_on_load(tmp_path):
    import json

    path = tmp_path / "old.json"
    one = parse_station(row("A", slow=2, fast=1)).__dict__
    path.write_text(
        json.dumps({"fetched_at": "x", "stations": [one, dict(one), dict(one)]}), encoding="utf-8"
    )
    stations, _ = load_snapshot(path)
    assert len(stations) == 1


def test_notification_names_top_stations_only_when_hub_data_present():
    from app.tools.tool6_notification import draft_notification

    result = {
        "date": "2026-11-18",
        "peak_hour": 12,
        "risk": "CRITICAL",
        "peak_ratio": 0.5,
        "peak_surplus_mwh": 10.0,
        "thresholds": {"warning_ratio": 0.4},
    }
    plan = {"allocated_mwh": {}, "absorption_pct": 100.0, "residual_mwh": 0.0, "hydrogen_kg": 0.0}
    plain = draft_notification(result, plan)
    assert "충전소" not in plain and "시연 추정치" in plain
    stations = [_st("가", 5, 0), _st("나", 4, 0), _st("다", 3, 0), _st("라", 2, 0)]
    top = ev_capacity(stations, 12)["top_stations"]
    text = draft_notification(result, {**plan, "ev_basis": {"top_stations": top}})
    assert (
        "가, 나, 다" in text
        and "라" not in text.split("충전소(설치 규모 기준):")[1].splitlines()[0]
    )
    assert "VPP는 제주 플러스DR 실적(KPX) 기반 하한" in text and "EV 용량은 제주데이터허브" in text
