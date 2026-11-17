"""제주 전체 단위 풍력·태양광 모델을 학습한다.

사용 (backend/ 에서, xgboost 필요: uv sync --extra ml):
    python -m scripts.train_jeju_model <학습.csv> <출력폴더>

입력은 scripts.build_training_csv 가 만든 CSV. 출력 폴더에 wind.json, solar.json, meta.json 을 쓴다.
- 풍력: wind_usable=1 인 행만. 2023-01-01 이전으로 학습, 이후(~2024-05-31)로 검증.
  정답은 기본이 'KPX 풍력 + 출력제어량'(--wind-label potential). observed 면 KPX 값 그대로.
- 태양광: 2025-01-01 이전으로 학습, 2025년으로 검증.
- 검증은 시간 순서 홀드아웃이며, 비교용으로 월×시각 평균(기후값) 기준선을 함께 계산한다.
- 입력은 ASOS 실측 기상이다. 서비스에서는 단기예보를 쓰므로 실제 성능은 이보다 낮을 수 있다.
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from app.tools.jeju_model import (
    SOLAR_FEATURES,
    WIND_FEATURES,
    solar_features,
    trend_years,
    wind_features,
)

WIND_TEST_START = date(2023, 1, 1)
SOLAR_TEST_START = date(2025, 1, 1)
PARAMS = {
    "objective": "reg:squarederror",
    "max_depth": 5,
    "eta": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "seed": 42,
    "nthread": 1,
    "tree_method": "hist",
    "device": "cpu",
}
ROUNDS = 400
NOTE = (
    "Metrics use observed weather (ASOS), not forecasts. Targets are KPX market-settled "
    "Jeju totals including ESS. No operational validation claim."
)


def _f(raw: str) -> float | None:
    return None if raw == "" else float(raw)


def read_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = datetime.fromisoformat(r["timestamp"])
            rows.append(
                {
                    "date": ts.date(),
                    "hour": ts.hour,
                    "wind_mwh": _f(r["wind_mwh"]),
                    "solar_mwh": _f(r["solar_mwh"]),
                    "wind_usable": r["wind_usable"] == "1",
                    "wind_ms": _f(r["wind_ms"]),
                    "temperature_c": _f(r["temperature_c"]),
                    "sky": _f(r["sky"]),
                    # 출력제어 열은 선택. 없거나 빈 칸이면 제어 없음(0)으로 본다.
                    "wind_curtailed": _f(r.get("wind_curtailed_mwh", "")) or 0.0,
                    "solar_curtailed": r.get("solar_curtailed", "") == "1",
                }
            )
    return rows


def metrics(y, pred) -> dict:
    import numpy as np

    y, pred = np.asarray(y, dtype=float), np.asarray(pred, dtype=float)
    err = pred - y
    ss_res, ss_tot = float((err**2).sum()), float(((y - y.mean()) ** 2).sum())
    return {
        "mae_mwh": float(np.abs(err).mean()),
        "rmse_mwh": float(np.sqrt((err**2).mean())),
        "r2": 1 - ss_res / ss_tot if ss_tot else float("nan"),
        "target_mean_mwh": float(y.mean()),
    }


def daily_peak_mae(dates, y, pred) -> float:
    peak_y, peak_p = defaultdict(float), defaultdict(float)
    for d, a, b in zip(dates, y, pred, strict=True):
        peak_y[d] = max(peak_y[d], a)
        peak_p[d] = max(peak_p[d], b)
    return float(sum(abs(peak_y[d] - peak_p[d]) for d in peak_y) / len(peak_y))


def climatology(train, test):
    """월×시각 평균(기후값) 기준선. train 평균을 test 행에 적용한다."""
    sums: dict = defaultdict(lambda: [0.0, 0])
    for d, h, y in train:
        s = sums[(d.month, h)]
        s[0] += y
        s[1] += 1
    overall = sum(y for _, _, y in train) / len(train)
    return [
        sums[(d.month, h)][0] / sums[(d.month, h)][1] if (d.month, h) in sums else overall
        for d, h, _ in test
    ]


def _fit(train_x, train_y, names):
    import numpy as np
    import xgboost as xgb

    return xgb.train(
        PARAMS,
        xgb.DMatrix(np.array(train_x, dtype=float), label=np.array(train_y), feature_names=names),
        num_boost_round=ROUNDS,
    )


def _predict(model, x, names):
    import numpy as np
    import xgboost as xgb

    return model.predict(xgb.DMatrix(np.array(x, dtype=float), feature_names=names))


def _target_report(model, names, train, test, dates_test, y_test, x_test) -> dict:
    pred = _predict(model, x_test, names)
    base = climatology(
        [(r["date"], r["hour"], r["y"]) for r in train],
        [(r["date"], r["hour"], r["y"]) for r in test],
    )
    importance = model.get_score(importance_type="gain")
    total = float(sum(importance.values())) or 1.0
    return {
        "train_rows": len(train),
        "test_rows": len(test),
        "train_period": [
            min(r["date"] for r in train).isoformat(),
            max(r["date"] for r in train).isoformat(),
        ],
        "test_period": [min(dates_test).isoformat(), max(dates_test).isoformat()],
        "model": {
            **metrics(y_test, pred),
            "daily_peak_mae_mwh": daily_peak_mae(dates_test, y_test, pred),
        },
        "climatology_baseline": {
            **metrics(y_test, base),
            "daily_peak_mae_mwh": daily_peak_mae(dates_test, y_test, base),
        },
        "feature_gain_share": {
            k: round(float(v) / total, 4) for k, v in sorted(importance.items())
        },
    }


def train(
    csv_path: Path,
    out_dir: Path,
    wind_label: str = "potential",
    wind_test_start: date | None = None,
    solar_test_start: date | None = None,
) -> dict:
    """wind_label: potential = KPX 풍력 + 출력제어량(제한이 없었다면), observed = KPX 값 그대로."""
    if wind_label not in ("potential", "observed"):
        raise ValueError("wind_label must be 'potential' or 'observed'")
    rows = read_rows(csv_path)

    wind = [
        {**r, "y": r["wind_mwh"] + (r["wind_curtailed"] if wind_label == "potential" else 0.0)}
        for r in rows
        if r["wind_usable"] and None not in (r["wind_mwh"], r["wind_ms"], r["temperature_c"])
    ]
    # 태양광은 제어량이 없어 보정할 수 없으므로 제어된 시간은 학습·검증에서 뺀다.
    solar = [
        {**r, "y": r["solar_mwh"]}
        for r in rows
        if None not in (r["solar_mwh"], r["sky"], r["temperature_c"]) and not r["solar_curtailed"]
    ]
    wind_split = wind_test_start or WIND_TEST_START
    solar_split = solar_test_start or SOLAR_TEST_START
    w_train = [r for r in wind if r["date"] < wind_split]
    w_test = [r for r in wind if r["date"] >= wind_split]
    s_train = [r for r in solar if r["date"] < solar_split]
    s_test = [r for r in solar if r["date"] >= solar_split]
    if min(len(w_train), len(w_test), len(s_train), len(s_test)) < 48:
        raise ValueError("Each train/test split needs at least 48 rows")

    trend_max = max(trend_years(r["date"]) for r in s_train)

    def wx(rs):
        return [wind_features(r["date"], r["hour"], r["wind_ms"], r["temperature_c"]) for r in rs]

    def sx(rs):
        return [
            solar_features(r["date"], r["hour"], int(r["sky"]), r["temperature_c"], trend_max)
            for r in rs
        ]

    wind_model = _fit(wx(w_train), [r["y"] for r in w_train], WIND_FEATURES)
    solar_model = _fit(sx(s_train), [r["y"] for r in s_train], SOLAR_FEATURES)

    wind_pred = _predict(wind_model, wx(w_test), WIND_FEATURES)
    curtailed = [r["wind_curtailed"] > 0 for r in w_test]
    observed = [r["wind_mwh"] for r in w_test]
    potential = [r["wind_mwh"] + r["wind_curtailed"] for r in w_test]

    def _mae(pairs):
        pairs = list(pairs)
        return float(sum(abs(p - y) for p, y in pairs) / len(pairs)) if pairs else None

    wind_curtailment = {
        "label": wind_label,
        "train_curtailed_hours": sum(r["wind_curtailed"] > 0 for r in w_train),
        "test_curtailed_hours": sum(curtailed),
        "test_mae_curtailed_hours_vs_potential": _mae(
            (p, y) for p, y, c in zip(wind_pred, potential, curtailed, strict=True) if c
        ),
        "test_mae_curtailed_hours_vs_observed": _mae(
            (p, y) for p, y, c in zip(wind_pred, observed, curtailed, strict=True) if c
        ),
        "test_mae_other_hours_vs_observed": _mae(
            (p, y) for p, y, c in zip(wind_pred, observed, curtailed, strict=True) if not c
        ),
    }
    report = {
        "wind": _target_report(
            wind_model,
            WIND_FEATURES,
            w_train,
            w_test,
            [r["date"] for r in w_test],
            [r["y"] for r in w_test],
            wx(w_test),
        ),
        "solar": _target_report(
            solar_model,
            SOLAR_FEATURES,
            s_train,
            s_test,
            [r["date"] for r in s_test],
            [r["y"] for r in s_test],
            sx(s_test),
        ),
        "wind_curtailment": wind_curtailment,
        "solar_trend_max": trend_max,
        "validation": "chronological_holdout",
        "note": NOTE,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    wind_model.save_model(out_dir / "wind.json")
    solar_model.save_model(out_dir / "solar.json")
    (out_dir / "meta.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--wind-label", choices=["potential", "observed"], default="potential")
    args = parser.parse_args()
    report = train(args.csv_path, args.out_dir, args.wind_label)
    print(json.dumps(report, indent=2, ensure_ascii=False))
