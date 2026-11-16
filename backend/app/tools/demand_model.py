"""제주 시간별 전력수요 예측 모델 (하루 전 예측용).

입력은 하루 전에 알 수 있는 것만 쓴다: 달력(시각, 요일, 공휴일, 월, 연중 일)과 하루 평균 기온.
최근 실측 수요 같은 값은 쓰지 않는다(서비스에 실측 수요를 받는 경로가 없다).
학습(scripts/train_demand_model.py)과 추론이 같은 특징 함수를 써서 입력이 어긋나지 않는다.
학습 기온은 ASOS 제주(184) 실측, 서비스 기온은 제주시 예보 격자(53,38)다.

시간별 기온과 하루 최고·최저 기온은 일부러 쓰지 않는다. 실측 기온에서는 조금 더 정확하지만
예보 오차에 훨씬 민감해서, 오차를 섞어 비교했을 때 하루 평균 기온만 쓰는 쪽이 더 안정적이었다.
"""

import json
import math
from datetime import date
from pathlib import Path

from app.domain.kr_holidays import day_off_context, is_public_holiday
from app.domain.schemas import EnergyHour, WeatherHour
from app.tools.jeju_model import trend_years

FEATURES = [
    "hour",
    "day_of_week",
    "public_holiday",
    "prev_day_off",
    "next_day_off",
    "month",
    "day_of_year",
    "temp_day_mean",
    "trend_years",
]
# 수요 예측에 쓰는 기온 지점: 제주시 단기예보 격자
JEJU_CITY_GRID = (53, 38)


def day_mean_temperature(temps: list[float]) -> float:
    if not temps:
        raise ValueError("At least one temperature is required")
    return sum(temps) / len(temps)


def demand_features(
    d: date, hour: int, temp_day_mean: float, trend_max: float | None
) -> list[float]:
    prev_off, next_off = day_off_context(d)
    return [
        hour,
        d.weekday(),
        int(is_public_holiday(d)),
        prev_off,
        next_off,
        d.month,
        d.timetuple().tm_yday,
        temp_day_mean,
        trend_years(d, trend_max),
    ]


def day_features(
    d: date, temps_by_hour: dict[int, float], trend_max: float | None
) -> dict[int, list[float]]:
    """하루의 시간별 기온(0~23시)에서 시간별 특징을 만든다(기온은 하루 평균만 쓴다)."""
    mean = day_mean_temperature(list(temps_by_hour.values()))
    return {h: demand_features(d, h, mean, trend_max) for h in temps_by_hour}


class DemandModel:
    """<dir>/demand.json, meta.json 을 읽어 제주 시간별 수요(MWh)를 예측한다."""

    def __init__(self, directory: Path):
        from xgboost import Booster

        self.meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        self.booster = Booster()
        self.booster.load_model(directory / "demand.json")

    def predict(self, weather: list[WeatherHour]) -> list[EnergyHour]:
        import numpy as np
        from xgboost import DMatrix

        by_day: dict[date, dict[int, float]] = {}
        for w in weather:
            by_day.setdefault(w.date, {})[w.hour] = w.temperature_c
        trend_max = self.meta["trend_max"]
        feats = {d: day_features(d, temps, trend_max) for d, temps in by_day.items()}
        x = np.array([feats[w.date][w.hour] for w in weather], dtype=float)
        pred = self.booster.predict(DMatrix(x, feature_names=FEATURES))
        if not all(math.isfinite(float(p)) for p in pred):
            raise ValueError("Model returned non-finite predictions")
        return [
            EnergyHour(date=w.date, hour=w.hour, mwh=max(0.0, float(p)))
            for w, p in zip(weather, pred, strict=True)
        ]
