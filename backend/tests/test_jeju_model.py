import csv
import math
from datetime import date, datetime, timedelta

import pytest

from app.providers.asos import KST
from app.tools.jeju_model import sky_from_cloud_tenths, trend_years
from scripts.build_training_csv import FIELDS, build


def test_sky_mapping_matches_forecast_categories():
    assert [sky_from_cloud_tenths(v) for v in (0, 5, 5.5, 6, 8, 9, 10)] == [1, 1, 3, 3, 3, 4, 4]
    with pytest.raises(ValueError):
        sky_from_cloud_tenths(11)


def test_trend_is_clipped_to_training_maximum():
    assert trend_years(date(2013, 1, 1)) == 0
    assert trend_years(date(2030, 1, 1), trend_max=12.0) == 12.0
    assert trend_years(date(2014, 1, 1), trend_max=12.0) < 1.1


def _write_kpx(directory):
    header = ["거래일자", "거래시간", "지역", "태양광 발전량(MWh)", "풍력 발전량(MWh)"]
    rows = [("2024-05-31", h + 1, "제주도", 1.0 + h, 10.0 + h) for h in range(6)]
    rows += [("2024-06-01", 1, "제주도", 2.0, 0.5)]  # 2024-06부터 풍력은 사용 구간 밖
    (directory / "x20230228.csv").write_text(
        "\n".join([",".join(header)] + [",".join(map(str, r)) for r in rows]), encoding="cp949"
    )


def _write_asos(directory):
    cloud = {0: "4.0", 5: "9.0"}  # 0시 관측 → 1~3시 이어 쓰기, 4시는 3시간 초과, 5시는 새 관측
    lines = ["timestamp,wind_ms,temperature_c,irradiance_wm2,cloud_tenths"]
    for h in range(6):
        t = datetime(2024, 5, 31, h, tzinfo=KST).isoformat()
        lines.append(f"{t},{3 + h},15.0,,{cloud.get(h, '')}")
    t = datetime(2024, 6, 1, 0, tzinfo=KST).isoformat()
    lines.append(f"{t},5,16.0,,")
    (directory / "asos_gosan.csv").write_text("\n".join(lines), encoding="utf-8")


def test_training_csv_joins_marks_usable_wind_and_fills_cloud_briefly(tmp_path):
    kpx, asos = tmp_path / "kpx", tmp_path / "asos"
    kpx.mkdir()
    asos.mkdir()
    _write_kpx(kpx)
    _write_asos(asos)
    out = tmp_path / "train.csv"
    stats = build(kpx, asos, out)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert list(rows[0]) == FIELDS
    assert stats["rows"] == 7 and stats["wind_rows"] == 6 and stats["solar_rows"] == 7
    by_hour = {r["timestamp"][:13]: r for r in rows}
    h0, h3, h4, h5 = (by_hour[f"2024-05-31T0{i}"] for i in (0, 3, 4, 5))
    assert (h0["sky"], h0["cloud_filled"]) == ("1", "0")
    assert (h3["sky"], h3["cloud_filled"]) == ("1", "1")  # 3시간 이내는 직전 관측
    assert (h4["sky"], h4["cloud_filled"]) == ("", "0")  # 4시간째는 비워 둠
    assert (h5["sky"], h5["cloud_filled"]) == ("4", "0")
    assert by_hour["2024-06-01T00"]["wind_usable"] == "0"
    assert by_hour["2024-05-31T00"]["wind_usable"] == "1"


def test_training_csv_fills_curtailment_columns_only_when_history_is_given(tmp_path):
    kpx, asos, curt = tmp_path / "kpx", tmp_path / "asos", tmp_path / "curt"
    for d in (kpx, asos, curt):
        d.mkdir()
    _write_kpx(kpx)
    _write_asos(asos)
    header = "일자,제어지역,누적 시행회차," + ",".join(f"{h}시" for h in range(1, 25))
    (curt / "제주 풍력 출력제어횟수 및 제어량.csv").write_bytes(
        (header + "\n2024-05-31,제주,1," + ",".join(["0"] * 2 + ["40"] + ["0"] * 21)).encode(
            "cp949"
        )
    )
    with_hist, without = tmp_path / "a.csv", tmp_path / "b.csv"
    build(kpx, asos, with_hist, curtailment=curt)
    build(kpx, asos, without)
    a = {r["timestamp"][:13]: r for r in csv.DictReader(with_hist.open(encoding="utf-8"))}
    b = list(csv.DictReader(without.open(encoding="utf-8")))
    assert a["2024-05-31T02"]["wind_curtailed_mwh"] == "40.0"  # 3시(종료) → 2시(시작)
    assert a["2024-05-31T00"]["wind_curtailed_mwh"] == "0.0"  # 이력이 있고 제어 없음
    assert {r["wind_curtailed_mwh"] for r in b} == {""}  # 이력을 안 주면 알 수 없음


# ---- 학습·추론 (xgboost 필요) ----
xgboost = pytest.importorskip("xgboost")

from app.core.config import Settings  # noqa: E402
from app.domain.schemas import AnalysisRequest, WeatherHour  # noqa: E402
from app.tools.bundle import ToolBundle  # noqa: E402
from app.tools.jeju_model import JejuModel  # noqa: E402
from scripts.train_jeju_model import train  # noqa: E402


def _synthetic(path):
    """풍속→풍력은 단조 증가, 태양광은 낮·맑음에 큼. 해마다 20일치만 만든다."""
    lines = [
        ",".join(
            [
                "timestamp",
                "wind_mwh",
                "solar_mwh",
                "wind_usable",
                "wind_ms",
                "temperature_c",
                "cloud_tenths",
                "sky",
                "cloud_filled",
            ]
        )
    ]
    for year in range(2017, 2026):
        for k in range(20):
            day = date(year, 1, 1) + timedelta(days=k * 18)
            for h in range(24):
                wind_ms = 2 + ((k * 7 + h * 3 + year) % 13)
                sky = (1, 3, 4)[(k + h) % 3]
                wind = max(0.0, min(250.0, (wind_ms - 3) * 25))
                sun = max(0.0, math.sin(math.pi * (h - 6) / 12)) if 6 <= h <= 18 else 0.0
                solar = 100 * sun * {1: 1.0, 3: 0.6, 4: 0.3}[sky]
                usable = int(day <= date(2024, 5, 31))
                t = datetime(day.year, day.month, day.day, h, tzinfo=KST).isoformat()
                lines.append(f"{t},{wind},{solar},{usable},{wind_ms},15.0,5.0,{sky},0")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_train_saves_models_that_beat_climatology_and_predict_sensibly(tmp_path):
    data, out = tmp_path / "train.csv", tmp_path / "model"
    _synthetic(data)
    report = train(data, out)
    assert report["validation"] == "chronological_holdout"
    assert report["wind"]["train_period"][1] < report["wind"]["test_period"][0]
    assert report["wind"]["model"]["mae_mwh"] < report["wind"]["climatology_baseline"]["mae_mwh"]
    assert report["solar"]["model"]["mae_mwh"] < report["solar"]["climatology_baseline"]["mae_mwh"]
    assert (out / "wind.json").exists() and (out / "solar.json").exists()

    model = JejuModel(out)
    day = date(2026, 11, 17)  # 학습 기간 밖: 추세는 학습 최댓값으로 고정
    weather = [
        WeatherHour(
            date=day,
            hour=h,
            wind_ms=(3 if h < 12 else 13),
            temperature_c=15,
            sky=1,
            irradiance_wm2=0,
        )
        for h in range(24)
    ]
    wind, solar = model.components(weather)
    assert len(wind) == len(solar) == 24
    assert wind[18] > wind[6] + 100  # 풍속이 오르면 풍력 예측이 오른다
    assert solar[12] > 50 and solar[2] < 5  # 낮에 크고 밤에 작다
    total = model.predict(weather)
    assert total[12].mwh == pytest.approx(wind[12] + solar[12])


def test_bundle_uses_jeju_model_and_fails_closed_when_unavailable(tmp_path, monkeypatch):
    data, out = tmp_path / "train.csv", tmp_path / "model"
    _synthetic(data)
    train(data, out)
    day = date(2026, 11, 17)
    weather = [
        WeatherHour(date=day, hour=h, wind_ms=9, temperature_c=15, sky=1, irradiance_wm2=0)
        for h in range(24)
    ]
    request = AnalysisRequest(date=day, region="jeju", mode="live")

    bundle = ToolBundle(Settings(jeju_model_dir=out))
    monkeypatch.setattr(bundle, "_gosan_weather", lambda req: weather)
    rows, source = bundle.generation(request, weather, 0)
    assert len(rows) == 24 and rows[12].mwh > rows[2].mwh
    assert source["model"] == "xgboost_jeju_total"
    assert source["simulated"] is False and source["validated"] is False  # 승인 차단 유지

    broken = ToolBundle(Settings(jeju_model_dir=tmp_path / "missing"))
    monkeypatch.setattr(broken, "_gosan_weather", lambda req: weather)
    with pytest.raises(ValueError, match="jeju_model_unavailable_or_invalid"):
        broken.generation(request, weather, 0)

    keyless = ToolBundle(Settings(jeju_model_dir=out))  # KMA 키 없음(.env 격리됨)
    with pytest.raises(ValueError, match="jeju_model_unavailable_or_invalid"):
        keyless.generation(request, weather, 0)
