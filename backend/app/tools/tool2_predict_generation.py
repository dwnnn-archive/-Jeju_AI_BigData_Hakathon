import json
import math
from pathlib import Path

from app.domain.schemas import EnergyHour, Plant, WeatherHour

FEATURES = [
    "hour",
    "wind_ms",
    "temperature_c",
    "irradiance_wm2",
    "wind_capacity_mw",
    "solar_capacity_mw",
]


def wind_factor(speed: float) -> float:
    if not math.isfinite(speed) or speed < 0:
        raise ValueError("Wind speed must be finite and nonnegative")
    if speed < 3 or speed >= 25:
        return 0
    if speed >= 12:
        return 1
    return (speed**3 - 3**3) / (12**3 - 3**3)


def physical_prediction(weather: list[WeatherHour], wind_mw: float, solar_mw: float):
    return [
        EnergyHour(
            date=w.date,
            hour=w.hour,
            mwh=(
                wind_mw * wind_factor(w.wind_ms)
                + solar_mw
                * min(1.0, w.irradiance_wm2 / 1000 * max(0, 1 - 0.004 * (w.temperature_c - 25)))
            ),
        )
        for w in weather
    ]


def load_plants(base: Path, corrections: Path) -> list[Plant]:
    merged = {}
    for path in (base, corrections):
        records = [Plant.model_validate(p) for p in json.loads(path.read_text())]
        if len({p.id for p in records}) != len(records):
            raise ValueError("Duplicate plant IDs within a registry")
        for plant in records:
            merged[plant.id] = plant
    return list(merged.values())


def model_prediction(path: Path, weather, wind_mw, solar_mw):
    import numpy as np
    from xgboost import Booster, DMatrix

    model = Booster()
    model.load_model(path)
    features = np.array(
        [[w.hour, w.wind_ms, w.temperature_c, w.irradiance_wm2, wind_mw, solar_mw] for w in weather]
    )
    prediction = model.predict(DMatrix(features, feature_names=FEATURES))
    if not all(math.isfinite(float(p)) for p in prediction):
        raise ValueError("Model returned non-finite predictions")
    return [
        EnergyHour(date=w.date, hour=w.hour, mwh=min(wind_mw + solar_mw, max(0, float(p))))
        for w, p in zip(weather, prediction, strict=True)
    ]
