import math
import random
from datetime import date, datetime, timedelta

import pytest

from app.domain.kr_holidays import (
    FIRST_YEAR,
    LAST_YEAR,
    day_off_context,
    is_covered,
    is_day_off,
    is_public_holiday,
)
from app.tools.demand_model import FEATURES, day_features, day_mean_temperature


def test_holiday_table_has_substitute_and_temporary_holidays():
    assert is_public_holiday(date(2024, 2, 12))  # 설날 대체공휴일
    assert is_public_holiday(date(2024, 10, 1))  # 국군의 날(임시공휴일)
    assert is_public_holiday(date(2025, 1, 27))  # 임시공휴일
    assert not is_public_holiday(date(2024, 5, 31))
    assert is_day_off(date(2024, 6, 1))  # 토요일
    assert not is_day_off(date(2024, 5, 31))  # 금요일
    assert (FIRST_YEAR, LAST_YEAR) == (2007, 2030)
    assert is_covered(date(2026, 11, 17)) and not is_covered(date(2031, 1, 1))


def test_day_off_context_marks_first_and_last_day_of_long_weekends():
    assert day_off_context(date(2024, 5, 31)) == (0, 1)  # 금요일: 다음날 토요일
    assert day_off_context(date(2024, 6, 3)) == (1, 0)  # 월요일: 전날 일요일


def test_features_use_only_day_mean_temperature_and_cap_the_trend():
    temps = {h: float(h) for h in range(24)}  # 평균 11.5
    assert day_mean_temperature(list(temps.values())) == 11.5
    feats = day_features(date(2026, 11, 17), temps, trend_max=10.0)
    assert set(feats) == set(range(24))
    row = dict(zip(FEATURES, feats[5], strict=True))
    assert row["hour"] == 5 and row["temp_day_mean"] == 11.5
    assert row["day_of_week"] == date(2026, 11, 17).weekday()
    assert row["trend_years"] == 10.0  # 학습 최댓값으로 고정
    with pytest.raises(ValueError):
        day_mean_temperature([])


xgboost = pytest.importorskip("xgboost")

from app.core.config import Settings  # noqa: E402
from app.domain.schemas import AnalysisRequest, WeatherHour  # noqa: E402
from app.tools.bundle import ToolBundle  # noqa: E402
from app.tools.demand_model import DemandModel  # noqa: E402
from scripts.train_demand_model import day_type, train  # noqa: E402

START, END = date(2022, 1, 1), date(2023, 12, 31)


def _write_synthetic(demand_dir, asos_dir):
    """수요 = 기준 + |기온-18| 효과 + 평일 + 저녁 피크.

    하루 기온 편차를 넣어서 월·요일 평균으로는 맞출 수 없게 한다.
    """
    rnd = random.Random(1)
    header = ",".join(["날짜"] + [f"{h}시" for h in range(1, 25)])
    demand_lines, asos_lines = (
        [header],
        ["timestamp,wind_ms,temperature_c,irradiance_wm2,cloud_tenths"],
    )
    d = START
    while d <= END:
        anomaly = rnd.gauss(0, 5)
        base_t = 14 + 11 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 110) / 365) + anomaly
        daily = []
        for h in range(24):
            t = base_t + 3 * math.sin(2 * math.pi * (h - 9) / 24)
            stamp = datetime(d.year, d.month, d.day, h, tzinfo=timezone_kst()).isoformat()
            asos_lines.append(f"{stamp},3.0,{t:.2f},,5.0")
            daily.append(t)
        mean = sum(daily) / 24
        work = 0 if is_day_off(d) else 1
        vals = [
            560 + 12 * abs(mean - 18) + 70 * work + (90 if 18 <= h <= 21 else 0) + rnd.gauss(0, 4)
            for h in range(24)
        ]
        demand_lines.append(",".join([d.isoformat()] + [f"{v:.3f}" for v in vals]))
        d += timedelta(days=1)
    (demand_dir / "한국전력거래소_시간별 제주전력수요_20231231.csv").write_bytes(
        "\n".join(demand_lines).encode("cp949")
    )
    (asos_dir / "asos_jeju.csv").write_text("\n".join(asos_lines), encoding="utf-8")


def timezone_kst():
    from datetime import timezone

    return timezone(timedelta(hours=9))


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("demand")
    demand_dir, asos_dir, out = root / "demand", root / "asos", root / "model"
    demand_dir.mkdir()
    asos_dir.mkdir()
    _write_synthetic(demand_dir, asos_dir)
    report = train(demand_dir, asos_dir, out, start=START, train_end=date(2023, 6, 30))
    return report, out


def test_day_type_groups_weekday_saturday_and_sunday_or_holiday():
    assert day_type(date(2024, 5, 31)) == 0  # 금
    assert day_type(date(2024, 6, 1)) == 1  # 토
    assert day_type(date(2024, 6, 2)) == 2  # 일
    assert day_type(date(2024, 2, 12)) == 2  # 월요일이지만 대체공휴일


def test_model_beats_profile_baseline_and_reports_noise_sensitivity(trained):
    report, out = trained
    assert report["validation"] == "chronological_holdout"
    assert report["train_period"][1] < report["test_period"][0]
    assert report["model"]["mae_mwh"] < report["profile_baseline"]["mae_mwh"]
    weak = report["temperature_noise_sensitivity"]["weak"]["mae_mwh"]
    strong = report["temperature_noise_sensitivity"]["strong"]["mae_mwh"]
    assert report["model"]["mae_mwh"] < weak < strong  # 기온 오차가 클수록 나빠진다
    assert set(report["feature_gain_share"]) <= set(FEATURES)
    assert (out / "demand.json").exists() and (out / "meta.json").exists()


def _weather(day, mean_temp):
    return [
        WeatherHour(date=day, hour=h, wind_ms=3, temperature_c=mean_temp, sky=1, irradiance_wm2=0)
        for h in range(24)
    ]


def test_predict_returns_24_hours_and_cold_or_hot_days_use_more_power(trained):
    _, out = trained
    model = DemandModel(out)
    day = date(2026, 11, 17)  # 학습 기간 밖, 추세는 학습 최댓값으로 고정
    mild = model.predict(_weather(day, 18))
    cold = model.predict(_weather(day, 2))
    assert len(mild) == 24 and all(r.mwh > 0 for r in mild)
    assert sum(r.mwh for r in cold) > sum(r.mwh for r in mild) + 24 * 50
    assert mild[19].mwh > mild[3].mwh  # 저녁 피크 > 새벽


def test_bundle_uses_demand_model_and_fails_closed_when_unavailable(trained, tmp_path, monkeypatch):
    _, out = trained
    day = date(2026, 11, 17)
    weather = _weather(day, 12)
    request = AnalysisRequest(date=day, region="jeju", mode="live")

    bundle = ToolBundle(Settings(jeju_demand_model_dir=out))
    monkeypatch.setattr(bundle, "_jeju_city_weather", lambda req: weather)
    rows, source = bundle.demand(request)
    assert len(rows) == 24 and source["model"] == "xgboost_jeju_demand"
    assert source["simulated"] is False and source["validated"] is False

    broken = ToolBundle(Settings(jeju_demand_model_dir=tmp_path / "missing"))
    monkeypatch.setattr(broken, "_jeju_city_weather", lambda req: weather)
    with pytest.raises(ValueError, match="demand_model_unavailable_or_invalid"):
        broken.demand(request)

    keyless = ToolBundle(Settings(jeju_demand_model_dir=out))  # KMA 키 없음(.env 격리됨)
    with pytest.raises(ValueError, match="demand_model_unavailable_or_invalid"):
        keyless.demand(request)

    plain = ToolBundle(Settings())  # 모델도 중계도 없으면 기존 동작(명시적 실패)
    with pytest.raises(ValueError, match="kpx_url_missing"):
        plain.demand(request)
