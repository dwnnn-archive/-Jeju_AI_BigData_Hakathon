import csv
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("xgboost")

from app.domain.schemas import WeatherHour
from app.tools.tool2_predict_generation import model_prediction
from scripts.train_model import train


def dataset(path, duplicate=False):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "wind_ms",
                "temperature_c",
                "irradiance_wm2",
                "wind_capacity_mw",
                "solar_capacity_mw",
                "generation_mwh",
            ],
        )
        writer.writeheader()
        for i in range(72):
            t = datetime(2026, 11, 1, tzinfo=timezone(timedelta(hours=9)))
            t += timedelta(hours=0 if duplicate else i)
            writer.writerow(
                {
                    "timestamp": t.isoformat(),
                    "wind_ms": 12,
                    "temperature_c": 25,
                    "irradiance_wm2": 0,
                    "wind_capacity_mw": 70,
                    "solar_capacity_mw": 30,
                    "generation_mwh": 70,
                }
            )


def test_training_saves_loadable_model_with_temporal_holdout(tmp_path):
    path, model = tmp_path / "input.csv", tmp_path / "model.json"
    dataset(path)
    report = train(path, model)
    assert report["train_rows"] == 57
    assert report["test_rows"] == 15
    assert report["mae_mwh"] < 1
    assert report["validation"] == "chronological_holdout"
    assert report["train_end"] < report["test_start"]
    weather = [
        WeatherHour(
            date="2026-11-14", hour=h, wind_ms=12, temperature_c=25, sky=1, irradiance_wm2=0
        )
        for h in range(24)
    ]
    prediction = model_prediction(model, weather, 70, 30)
    assert len(prediction) == 24
    assert prediction[0].mwh == pytest.approx(70, abs=1)


def test_training_rejects_duplicate_timestamps(tmp_path):
    path = tmp_path / "input.csv"
    dataset(path, duplicate=True)
    with pytest.raises(ValueError, match="timestamp"):
        train(path, tmp_path / "model.json")


def test_training_rejects_intervals_not_aligned_to_kst_hours(tmp_path):
    path = tmp_path / "input.csv"
    dataset(path)
    path.write_text(path.read_text().replace("+09:00", "+05:30"))
    with pytest.raises(ValueError, match="hour"):
        train(path, tmp_path / "model.json")
