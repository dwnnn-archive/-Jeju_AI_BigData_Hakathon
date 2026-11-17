from datetime import date

import httpx
import pytest

from app.providers.jejuhub_weather import (
    day_mean_temperature,
    fetch_altitudes,
    fetch_day,
    lowland_names,
    read_cached_day,
    write_cached_day,
)
from scripts.check_hub_weather import (
    asos_daily_means,
    calibration_bias,
    crosscheck,
)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def obs(name, temp):
    return {"observatoryName": name, "averageTemperature": temp}


def test_fetch_day_sends_search_date_and_returns_rows():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(
            200, json={"totCnt": 1, "hasMore": False, "data": [obs("중문", "9.1000")]}
        )

    rows = fetch_day("KEY", date(2024, 3, 15), client=client_for(handler))
    assert seen["searchDate"] == "20240315" and rows[0]["observatoryName"] == "중문"


def test_fetch_day_rejects_bad_shape_and_hides_key():
    with pytest.raises(RuntimeError, match="no data list"):
        fetch_day(
            "K", date(2024, 1, 1), client=client_for(lambda r: httpx.Response(200, json={"x": 1}))
        )

    def boom(request):
        raise httpx.ConnectTimeout("t", request=request)

    with pytest.raises(RuntimeError) as err:
        fetch_day("SECRET", date(2024, 1, 1), client=client_for(boom))
    assert "SECRET" not in str(err.value)


def test_altitudes_keep_lowest_duplicate_and_skip_bad_rows():
    body = {
        "hasMore": False,
        "data": [
            {"observatoryName": "강정", "seaLevelAltitude": "143.0"},
            {"observatoryName": "강정", "seaLevelAltitude": "141.84"},
            {"observatoryName": "윗세오름", "seaLevelAltitude": "1665.71"},
            {"observatoryName": "고장", "seaLevelAltitude": "없음"},
            {"seaLevelAltitude": "5"},
        ],
    }
    alts = fetch_altitudes("K", client=client_for(lambda r: httpx.Response(200, json=body)))
    assert alts == {"강정": 141.84, "윗세오름": 1665.71}
    assert lowland_names(alts) == set()  # 둘 다 100 m 이상
    assert lowland_names({"대정": 2.6, "어리목": 967.8}) == {"대정"}


def test_day_mean_uses_only_chosen_stations_and_needs_enough_of_them():
    names = {"a", "b", "c", "d", "e"}
    rows = [obs(n, "10.0") for n in names] + [obs("높은곳", "-5.0")]
    assert day_mean_temperature(rows, names) == pytest.approx(10.0)  # 고지대는 섞이지 않는다
    assert day_mean_temperature(rows[:3], names) is None  # 5곳 미만이면 쓰지 않는다
    bad = [obs("a", ""), obs("b", None), obs("c", "x"), obs("d", "8"), obs("e", "12")]
    assert day_mean_temperature(bad, names, min_stations=2) == pytest.approx(10.0)
    assert day_mean_temperature([], names) is None


def test_cache_roundtrip_keeps_empty_days_and_ignores_broken_files(tmp_path):
    d = date(2025, 4, 1)
    assert read_cached_day(tmp_path, d) is None
    write_cached_day(tmp_path, d, [])
    assert read_cached_day(tmp_path, d) == []  # 비어 있던 날도 저장본으로 인정
    (tmp_path / "20250402.json").write_text("{broken", encoding="utf-8")
    assert read_cached_day(tmp_path, date(2025, 4, 2)) is None
    (tmp_path / "20250403.json").write_text('{"a": 1}', encoding="utf-8")
    assert read_cached_day(tmp_path, date(2025, 4, 3)) is None


def test_crosscheck_reports_bias_correlation_and_errors():
    asos = {date(2024, 1, d): float(d) for d in range(1, 11)}
    hub = {d: v - 0.5 for d, v in asos.items()}  # 일정하게 0.5℃ 낮음
    out = crosscheck(hub, asos)
    assert out["days"] == 10 and out["correlation"] == pytest.approx(1.0)
    assert out["bias_c"] == pytest.approx(-0.5) and out["mae_c"] == pytest.approx(0.5)
    assert out["max_abs_diff_c"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        crosscheck({date(2024, 1, 1): 1.0}, {date(2024, 1, 1): 1.0})


def test_calibration_bias_uses_only_the_given_year():
    asos = {date(2024, 6, 1): 20.0, date(2024, 6, 2): 22.0, date(2025, 1, 1): 5.0}
    hub = {date(2024, 6, 1): 19.0, date(2024, 6, 2): 21.0, date(2025, 1, 1): 0.0}
    assert calibration_bias(hub, asos, 2024) == pytest.approx(-1.0)  # 2025 값은 섞이지 않는다
    with pytest.raises(ValueError):
        calibration_bias(hub, asos, 2030)


def test_asos_daily_means_need_enough_hours():
    full = {(date(2024, 1, 1), h): 10.0 for h in range(24)}
    partial = {(date(2024, 1, 2), h): 5.0 for h in range(19)}  # 20시간 미만
    out = asos_daily_means({**full, **partial})
    assert out == {date(2024, 1, 1): 10.0}
