"""제주 시간별 수요 예측 모델을 학습하고 KPX 하루전 예측과 비교한다.

사용 (backend/ 에서, xgboost 필요: uv sync --extra ml):
    python -m scripts.train_demand_model <KPX_수요_폴더> <ASOS_폴더> <출력폴더> [--pss-dir <폴더>]

- 정답: scripts.kpx_demand 가 정규화한 제주 실측 수요(MWh).
- 기온: scripts.collect_asos 로 받은 ASOS 제주(184) 실측(서비스에서는 제주시 예보 격자의 기온).
- 입력은 하루 전에 알 수 있는 값뿐이다(달력, 공휴일, 기온). 최근 실측 수요는 쓰지 않는다.
- 검증: --train-end 이전으로 학습, 이후로 검증하는 시간순 홀드아웃.
- 비교: 월 x 요일유형 x 시각 평균(기준선), --pss-dir 를 주면 같은 시간의 KPX 하루전 예측.
- 기온은 실측을 쓰므로 서비스의 예보 기온을 쓰면 실제 성능은 더 낮을 수 있다.
"""

import argparse
import json
import random
from collections import defaultdict
from datetime import date
from pathlib import Path

from app.domain.kr_holidays import is_public_holiday
from app.tools.demand_model import FEATURES, day_features
from app.tools.jeju_model import trend_years
from scripts.build_training_csv import read_asos
from scripts.kpx_demand import load_demand
from scripts.kpx_pss import load_pss
from scripts.train_jeju_model import PARAMS, daily_peak_mae, metrics

PARAMS_DEMAND = {**PARAMS, "max_depth": 6}
ROUNDS = 600
MIN_DAY_HOURS = 20
NOTE = (
    "Metrics use observed temperature (ASOS), not forecasts, and no recent-demand inputs. "
    "Target is KPX generator-side demand. No operational validation claim."
)


def build_rows(demand, temps, start: date, trend_max: float | None):
    """[(date, hour, features, demand_mwh)]. 하루 기온이 MIN_DAY_HOURS시간 미만이면 그 날은 뺀다."""
    by_day: dict[date, dict[int, float]] = defaultdict(dict)
    for (d, h), t in temps.items():
        by_day[d][h] = t
    rows = []
    for d in sorted({k[0] for k in demand}):
        if d < start or len(by_day.get(d, {})) < MIN_DAY_HOURS:
            continue
        for h, f in day_features(d, by_day[d], trend_max).items():
            if (d, h) in demand:
                rows.append((d, h, f, demand[(d, h)]))
    return rows


# 예보 기온 오차 가정: (하루 단위 치우침 표준편차, 매시간 표준편차).
# 실제 예보 오차는 측정하지 못했다.
NOISE_SCENARIOS = {"weak": (1.5, 1.0), "strong": (2.5, 1.5)}
NOISE_SEEDS = 3


def noisy_temperatures(temps, since: date, day_sd: float, hour_sd: float, seed: int):
    """since 이후의 기온에 하루 단위 치우침과 매시간 오차를 더한다(예보 오차 흉내)."""
    rnd = random.Random(seed)
    offset: dict[date, float] = {}
    out = {}
    for (d, h), t in temps.items():
        if d < since:
            out[(d, h)] = t
            continue
        offset.setdefault(d, rnd.gauss(0, day_sd))
        out[(d, h)] = t + offset[d] + rnd.gauss(0, hour_sd)
    return out


def _noise_sensitivity(model, demand, temps, test_start: date, trend_max: float, keep) -> dict:
    """예보 오차를 섞은 기온으로 검증 구간 MAE를 다시 잰다(시드 평균)."""
    import numpy as np

    out = {}
    for name, (day_sd, hour_sd) in NOISE_SCENARIOS.items():
        maes = []
        for seed in range(NOISE_SEEDS):
            noisy = noisy_temperatures(temps, test_start, day_sd, hour_sd, seed)
            rows = [r for r in build_rows(demand, noisy, test_start, trend_max) if keep(r)]
            pred = np.array(_predict(model, rows))
            maes.append(float(np.abs(pred - np.array([r[3] for r in rows])).mean()))
        out[name] = {"day_sd_c": day_sd, "hour_sd_c": hour_sd, "mae_mwh": float(np.mean(maes))}
    return out


def day_type(d: date) -> int:
    """0 평일, 1 토요일, 2 일요일·공휴일."""
    if d.weekday() == 6 or is_public_holiday(d):
        return 2
    return 1 if d.weekday() == 5 else 0


def profile_baseline(train, test):
    """월 x 요일유형 x 시각 평균. 연도 증가 추세는 반영하지 않는다."""
    sums: dict = defaultdict(lambda: [0.0, 0])
    for d, h, _, y in train:
        s = sums[(d.month, day_type(d), h)]
        s[0] += y
        s[1] += 1
    overall = sum(r[3] for r in train) / len(train)
    out = []
    for d, h, _, _ in test:
        s = sums.get((d.month, day_type(d), h))
        out.append(s[0] / s[1] if s else overall)
    return out


def _summary(dates, y, pred) -> dict:
    import numpy as np

    err = np.asarray(pred, dtype=float) - np.asarray(y, dtype=float)
    out = metrics(y, pred)
    out["mape_pct"] = float((np.abs(err) / np.asarray(y)).mean() * 100)
    out["bias_mwh"] = float(err.mean())
    out["daily_peak_mae_mwh"] = daily_peak_mae(dates, y, pred)
    return out


def _by_year(rows, series: dict[str, list[float]]) -> dict:
    import numpy as np

    out = {}
    for year in sorted({r[0].year for r in rows}):
        idx = [i for i, r in enumerate(rows) if r[0].year == year]
        y = np.array([rows[i][3] for i in idx])
        out[str(year)] = {"hours": len(idx)}
        for name, pred in series.items():
            p = np.array([pred[i] for i in idx])
            out[str(year)][name] = {
                "mae_mwh": float(np.abs(p - y).mean()),
                "mape_pct": float((np.abs(p - y) / y).mean() * 100),
                "bias_mwh": float((p - y).mean()),
            }
    return out


def _fit(rows):
    import numpy as np
    import xgboost as xgb

    matrix = xgb.DMatrix(
        np.array([r[2] for r in rows], dtype=float),
        label=np.array([r[3] for r in rows]),
        feature_names=FEATURES,
    )
    return xgb.train(PARAMS_DEMAND, matrix, num_boost_round=ROUNDS)


def _predict(model, rows) -> list[float]:
    import numpy as np
    import xgboost as xgb

    x = np.array([r[2] for r in rows], dtype=float)
    return [float(p) for p in model.predict(xgb.DMatrix(x, feature_names=FEATURES))]


def train(
    demand_dir: Path,
    asos_dir: Path,
    out_dir: Path,
    pss_dir: Path | None = None,
    start: date = date(2017, 1, 1),
    train_end: date = date(2023, 12, 31),
    station: str = "jeju",
    refit_all: bool = False,
) -> dict:
    demand = load_demand(demand_dir)
    asos = read_asos(asos_dir / f"asos_{station}.csv")
    temps = {
        (t.date(), t.hour): v["temperature_c"]
        for t, v in asos.items()
        if v["temperature_c"] is not None
    }
    train_dates = [d for d, _ in demand if start <= d <= train_end]
    if not train_dates:
        raise ValueError("No demand rows in the training period")
    trend_max = trend_years(max(train_dates))  # 추론 때 이 값으로 고정한다
    rows = build_rows(demand, temps, start, trend_max)
    train_rows = [r for r in rows if r[0] <= train_end]
    test = [r for r in rows if r[0] > train_end]
    if min(len(train_rows), len(test)) < 48:
        raise ValueError("Each train/test split needs at least 48 rows")

    model = _fit(train_rows)
    series = {"model": _predict(model, test), "profile": profile_baseline(train_rows, test)}
    dates, y = [r[0] for r in test], [r[3] for r in test]
    report: dict = {
        "train_rows": len(train_rows),
        "test_rows": len(test),
        "train_period": [train_rows[0][0].isoformat(), train_rows[-1][0].isoformat()],
        "test_period": [test[0][0].isoformat(), test[-1][0].isoformat()],
        "model": _summary(dates, y, series["model"]),
        "profile_baseline": _summary(dates, y, series["profile"]),
    }
    compare_rows, compare_series = test, series
    if pss_dir is not None:
        pss = load_pss(pss_dir)
        keep = [i for i, r in enumerate(test) if (r[0], r[1]) in pss]
        compare_rows = [test[i] for i in keep]
        compare_series = {k: [v[i] for i in keep] for k, v in series.items()}
        compare_series["kpx"] = [pss[(r[0], r[1])] for r in compare_rows]
        cd, cy = [r[0] for r in compare_rows], [r[3] for r in compare_rows]
        report["kpx_comparison_rows"] = len(compare_rows)
        report["kpx_forecast"] = _summary(cd, cy, compare_series["kpx"])
        report["model_on_same_rows"] = _summary(cd, cy, compare_series["model"])
    keep_keys = {(r[0], r[1]) for r in compare_rows}
    test_start = test[0][0]
    report["temperature_noise_sensitivity"] = _noise_sensitivity(
        model, demand, temps, test_start, trend_max, lambda r: (r[0], r[1]) in keep_keys
    )
    report["by_year"] = _by_year(compare_rows, compare_series)
    gain = model.get_score(importance_type="gain")
    total = float(sum(gain.values())) or 1.0
    report["feature_gain_share"] = {k: round(float(v) / total, 4) for k, v in sorted(gain.items())}
    report.update({"trend_max": trend_max, "validation": "chronological_holdout", "note": NOTE})

    final = model
    if refit_all:  # 저장 모델만 전체 기간으로 다시 학습한다(보고 지표는 홀드아웃 그대로).
        all_rows = build_rows(demand, temps, start, None)
        # 추세 상한은 실제로 학습에 쓴 마지막 날 기준이다(기온이 없는 날은 학습에서 빠진다).
        all_trend = trend_years(max(r[0] for r in all_rows))
        final = _fit(all_rows)
        report["trend_max"], report["refit_all"] = all_trend, True
        report["refit_period"] = [all_rows[0][0].isoformat(), all_rows[-1][0].isoformat()]
    out_dir.mkdir(parents=True, exist_ok=True)
    final.save_model(out_dir / "demand.json")
    (out_dir / "meta.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("demand_dir", type=Path)
    p.add_argument("asos_dir", type=Path)
    p.add_argument("out_dir", type=Path)
    p.add_argument("--pss-dir", type=Path)
    p.add_argument("--start", type=date.fromisoformat, default=date(2017, 1, 1))
    p.add_argument("--train-end", type=date.fromisoformat, default=date(2023, 12, 31))
    p.add_argument("--station", default="jeju")
    p.add_argument("--refit-all", action="store_true", help="저장 모델을 전체 기간으로 다시 학습")
    a = p.parse_args()
    result = train(
        a.demand_dir, a.asos_dir, a.out_dir, a.pss_dir, a.start, a.train_end, a.station, a.refit_all
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
