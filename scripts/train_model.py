"""Train from measured hourly CSV: python -m scripts.train_model input.csv model.json."""

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.domain.schemas import WeatherHour
from backend.tools.tool2_predict_generation import FEATURES


def train(csv_path: Path, model_path: Path) -> dict:
    import numpy as np
    import xgboost as xgb

    rows = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            timestamp = datetime.fromisoformat(row["timestamp"])
            if (
                timestamp.tzinfo is None
                or timestamp.minute
                or timestamp.second
                or timestamp.microsecond
            ):
                raise ValueError("timestamp must be timezone-aware and on the hour")
            timestamp = timestamp.astimezone(ZoneInfo("Asia/Seoul"))
            w = WeatherHour(
                date=timestamp.date(),
                hour=timestamp.hour,
                wind_ms=row["wind_ms"],
                temperature_c=row["temperature_c"],
                sky=1,
                irradiance_wm2=row["irradiance_wm2"],
            )
            wind, solar, target = (
                float(row[k]) for k in ("wind_capacity_mw", "solar_capacity_mw", "generation_mwh")
            )
            if not all(math.isfinite(n) and n >= 0 for n in (wind, solar, target)):
                raise ValueError("Capacity and generation must be finite and nonnegative")
            if target > wind + solar:
                raise ValueError("Hourly energy exceeds nameplate capacity")
            rows.append(
                (
                    timestamp,
                    [w.hour, w.wind_ms, w.temperature_c, w.irradiance_wm2, wind, solar],
                    target,
                )
            )
    rows.sort(key=lambda r: r[0])
    if len({r[0] for r in rows}) != len(rows):
        raise ValueError("Duplicate timestamp")
    if len(rows) < 48:
        raise ValueError("At least 48 distinct hourly rows are required")
    split = int(len(rows) * 0.8)
    x = np.array([r[1] for r in rows])
    y = np.array([r[2] for r in rows])
    training = xgb.DMatrix(x[:split], label=y[:split], feature_names=FEATURES)
    testing = xgb.DMatrix(x[split:], label=y[split:], feature_names=FEATURES)
    model = xgb.train(
        {
            "objective": "reg:squarederror",
            "max_depth": 4,
            "eta": 0.05,
            "seed": 42,
            "nthread": 1,
            "tree_method": "hist",
            "device": "cpu",
        },
        training,
        num_boost_round=100,
    )
    prediction = model.predict(testing)
    report = {
        "train_rows": split,
        "test_rows": len(rows) - split,
        "mae_mwh": float(np.mean(np.abs(prediction - y[split:]))),
        "validation": "chronological_holdout",
        "train_end": rows[split - 1][0].isoformat(),
        "test_start": rows[split][0].isoformat(),
        "features": FEATURES,
        "note": "Metrics describe only the supplied dataset; no operational validation claim.",
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(model_path)
    model_path.with_suffix(".metrics.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("model_path", type=Path)
    args = parser.parse_args()
    print(json.dumps(train(args.csv_path, args.model_path), indent=2))
