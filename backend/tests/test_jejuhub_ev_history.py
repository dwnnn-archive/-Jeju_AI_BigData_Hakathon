from datetime import date

import pytest

from app.providers.jejuhub_ev import ev_capacity, parse_station
from app.providers.jejuhub_ev_history import (
    build_profile,
    group_of,
    hours_of,
    load_profile,
    save_profile,
    spread_busy_hours,
    weekday_factors,
)


def monthly_row(category, hour, count, time, kwh, charger="C1", month="202203"):
    return {
        "evChargerCategory": category,
        "evChargerId": charger,
        "baseYearMonth": month,
        "chargingStartHour": str(hour),
        "chargingCount": count,
        "chargingTime": time,
        "chargingAmount": kwh,
    }


def sample_rows():
    return [
        # 완속 1기: 31일 매일 10시에 1시간씩 7kW → 평균 7kW
        monthly_row("완속", 10, 31, "31:00:00", 217.0, "S1"),
        # 급속 1기: 31일 매일 12시에 30분씩 50kW → 평균 50kW
        monthly_row("DC콤보", 12, 31, "15:30:00", 775.0, "F1"),
    ]


def test_parsers():
    assert hours_of("01:30:00") == pytest.approx(1.5)
    assert hours_of("120:00:00") == 120  # 하루를 넘는 합계도 허용
    assert hours_of("알 수 없음") is None
    assert hours_of("1:30") is None
    assert group_of("완속") == "slow"
    assert group_of("DC차데모+AC3상") == "fast" and group_of("AC급속3상") == "fast"


def test_spread_conserves_duration_and_wraps_midnight():
    busy = spread_busy_hours(10, 1.0)
    assert sum(busy.values()) == pytest.approx(1.0)
    assert busy[10] == pytest.approx(0.5) and busy[11] == pytest.approx(0.5)
    late = spread_busy_hours(23, 2.0)  # 자정을 넘기면 0시로 이어진다
    assert sum(late.values()) == pytest.approx(2.0)
    assert 0 in late and 1 in late
    assert sum(spread_busy_hours(5, 99).values()) == pytest.approx(24.0)  # 하루로 제한


def test_build_profile_hand_computed():
    profile = build_profile(sample_rows(), [])
    assert profile["months"] == ["202203"] and profile["rows_used"] == 2
    assert profile["slow"]["avg_kw"] == pytest.approx(7.0)
    assert profile["fast"]["avg_kw"] == pytest.approx(50.0)
    # 완속: 10시에 시작한 1시간 충전이 10시·11시에 0.5씩 걸친다 → 점유율 0.5
    assert profile["slow"]["occupancy"][10] == pytest.approx(0.5)
    assert profile["slow"]["occupancy"][11] == pytest.approx(0.5)
    assert profile["slow"]["occupancy"][3] == 0
    # 급속: 30분 충전, 12시에 0.375 / 13시에 0.125
    assert profile["fast"]["occupancy"][12] == pytest.approx(0.375, abs=1e-6)
    assert profile["fast"]["occupancy"][13] == pytest.approx(0.125, abs=1e-6)
    assert profile["weekday_factor"] == dict.fromkeys("월화수목금토일", 1.0)


def test_build_profile_skips_bad_rows_and_needs_data():
    rows = sample_rows() + [
        monthly_row("완속", 99, 1, "01:00:00", 5.0),  # 시각 범위 밖
        monthly_row("완속", 9, 0, "01:00:00", 5.0),  # 횟수 0
        monthly_row("완속", 9, 1, "알 수 없음", 5.0),
        {"evChargerCategory": "완속"},
    ]
    profile = build_profile(rows, [])
    assert profile["rows_used"] == 2 and profile["rows_skipped"] == 4
    with pytest.raises(ValueError):
        build_profile([], [])


def test_weekday_factors():
    months = ["202203"]  # 2022-03: 화·수·목 5번, 나머지 4번
    occ = {"월": 4, "화": 5, "수": 5, "목": 5, "금": 4, "토": 4, "일": 4}
    flat = [{"baseDayOfTheWeek": w, "chargingCount": n * 10} for w, n in occ.items()]
    assert weekday_factors(flat, months) == {w: pytest.approx(1.0) for w in occ}
    busy_sat = [{**r, "chargingCount": r["chargingCount"] * 2} if r["baseDayOfTheWeek"] == "토" else r for r in flat]
    f = weekday_factors(busy_sat, months)
    assert f["토"] > 1.5 and f["월"] < 1.0
    assert weekday_factors([], months) == dict.fromkeys("월화수목금토일", 1.0)  # 자료 없으면 보정 없음


def stations():
    return [
        parse_station(
            {"chargingPlace": "A", "startTime": "0:00", "endTime": "24:00:00",
             "chargerCount": 2, "quickChargerCount": 1, "holiday": "연중무휴"}
        )
    ]


def test_capacity_uses_history_profile_when_present():
    profile = build_profile(sample_rows(), [])
    got = ev_capacity(stations(), 10, profile=profile, target_date=date(2022, 3, 7))
    assert got["basis"] == "history_profile"
    # 완속 2기 x 7kW x (1-0.5) + 급속 1기 x 50kW x (1-0) = 57 kW
    assert got["capacity_mwh"] == pytest.approx(0.057)
    assert got["free_fraction"]["slow"] == pytest.approx(0.5)
    # 설치 용량은 정격이 아니라 이력의 평균 전력 기준
    assert got["installed_mwh"] == pytest.approx((2 * 7 + 50) / 1000)
    # 가정 경로와 구분된다
    assert ev_capacity(stations(), 10)["basis"] == "assumption"


def test_weekday_factor_lowers_free_capacity_on_busy_days():
    weekday = [{"baseYearMonth": "202203", "baseDayOfTheWeek": w, "chargingCount": 10 * n} for w, n in
               {"월": 4, "화": 5, "수": 5, "목": 5, "금": 4, "토": 8, "일": 4}.items()]
    profile = build_profile(sample_rows(), weekday)
    sat = ev_capacity(stations(), 10, profile=profile, target_date=date(2022, 3, 5))  # 토
    mon = ev_capacity(stations(), 10, profile=profile, target_date=date(2022, 3, 7))  # 월
    assert sat["weekday_factor"] > 1 > mon["weekday_factor"]
    assert sat["capacity_mwh"] < mon["capacity_mwh"]


def test_profile_roundtrip_and_invalid_files(tmp_path):
    path = tmp_path / "p.json"
    assert load_profile(path) is None
    save_profile(build_profile(sample_rows(), []), path)
    assert load_profile(path)["slow"]["avg_kw"] == pytest.approx(7.0)
    path.write_text("{broken", encoding="utf-8")
    assert load_profile(path) is None
    path.write_text('{"slow": null, "fast": null, "weekday_factor": {}}', encoding="utf-8")
    assert load_profile(path) is None  # 한쪽이라도 없으면 쓰지 않는다


def test_quota_error_is_distinct_and_not_retried():
    import httpx

    from app.providers.jejuhub_ev import QuotaExceeded, fetch_stations

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(403, text="Today's quota is full")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(QuotaExceeded):
            fetch_stations("K", client=client, base_url="https://h/p")
    assert calls["n"] == 1  # 한도 초과는 재시도하지 않는다


def test_cached_rows_resumes_and_keeps_earlier_months(tmp_path):
    from app.providers.jejuhub_ev_history import cached_rows

    fetched = []

    def fetch_ok():
        fetched.append(1)
        return [{"a": 1}]

    rows, new = cached_rows(tmp_path, "monthly", "202203", fetch_ok)
    assert rows == [{"a": 1}] and new is True
    rows, new = cached_rows(tmp_path, "monthly", "202203", fetch_ok)  # 두 번째는 저장본
    assert new is False and len(fetched) == 1

    def fetch_fail():
        raise RuntimeError("quota")

    with pytest.raises(RuntimeError):
        cached_rows(tmp_path, "monthly", "202204", fetch_fail)
    assert not (tmp_path / "monthly-202204.json").exists()  # 실패한 달은 파일을 남기지 않는다
    assert (tmp_path / "monthly-202203.json").exists()  # 앞서 받은 달은 그대로


def test_weekday_factor_uses_only_months_present_in_both():
    rows = [monthly_row("완속", 10, 31, "31:00:00", 217.0, "S1", "202203"),
            monthly_row("DC콤보", 12, 31, "15:30:00", 775.0, "F1", "202203")]
    weekday = [{"baseYearMonth": "202204", "baseDayOfTheWeek": "토", "chargingCount": 999}]  # 월별에 없는 달
    profile = build_profile(rows, weekday)
    assert profile["weekday_months"] == []
    assert profile["weekday_factor"] == dict.fromkeys("월화수목금토일", 1.0)


def test_call_log_counts_requests_without_key(tmp_path):
    import httpx

    from app.providers.jejuhub_ev import call_count, enable_call_log, fetch_stations

    log = tmp_path / "calls.log"
    enable_call_log(log)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"totCnt": 0, "hasMore": False, "data": []})
        )
    )
    try:
        fetch_stations("SECRETKEY", client=client, base_url="https://h/p/DATASET")
        assert call_count() == 1
        text = log.read_text(encoding="utf-8")
        assert "DATASET" in text and "200" in text and "SECRETKEY" not in text
    finally:
        enable_call_log(None)


def test_history_script_refuses_too_many_new_months(tmp_path, monkeypatch):
    from scripts import collect_ev_history as c

    monkeypatch.setenv("JEJUHUB_PROJECT_KEY", "K")
    monkeypatch.setenv("EV_PROFILE_PATH", str(tmp_path / "ev_profile.json"))
    assert c.main(["202101", "202102", "202103", "202104"]) == 2
