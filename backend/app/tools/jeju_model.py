"""제주 전체 단위 발전량 모델 (풍력 모델 + 태양광 모델).

정답은 KPX가 공개한 제주 전체 시간별 거래 발전량이다. 설비별 계산이 아니다.
특징 생성 함수를 학습(scripts/train_jeju_model.py)과 추론이 함께 쓰므로 두 입력이 어긋나지 않는다.
- 풍력: 시각, 월, 풍속, 기온.
- 태양광: 시각, 연중 일, 하늘상태(SKY 1/3/4), 기온, 연도 추세.
  학습에는 ASOS 전운량을 하늘상태와 같은 3단계로 바꿔 쓴다(실측 일사량은 추론 시 없음).
KPX 값은 시장 참여 발전기 기준이고 ESS가 섞여 있어 "시장 거래된 발전량"이다.
"""

import json
import math
from datetime import date
from pathlib import Path

from app.domain.schemas import EnergyHour, WeatherHour

REFERENCE_DATE = date(2013, 1, 1)
WIND_FEATURES = ["hour", "month", "wind_ms", "temperature_c"]
SOLAR_FEATURES = ["hour", "day_of_year", "sky", "temperature_c", "trend_years"]
# 기상청 단기예보 격자: 고산(한경면). 풍속 상관이 가장 높은 지점(ASOS 고산 185)에 대응한다.
GOSAN_GRID = (46, 35)


def sky_from_cloud_tenths(tenths: float) -> int:
    """ASOS 전운량(0~10) → 예보 하늘상태 코드: 맑음 1(0~5), 구름많음 3(6~8), 흐림 4(9~10)."""
    if not 0 <= tenths <= 10:
        raise ValueError("Cloud cover must be within 0..10")
    return 1 if tenths <= 5 else 3 if tenths <= 8 else 4


def wind_features(d: date, hour: int, wind_ms: float, temperature_c: float) -> list[float]:
    return [hour, d.month, wind_ms, temperature_c]


def trend_years(d: date, trend_max: float | None = None) -> float:
    value = (d - REFERENCE_DATE).days / 365.25
    return value if trend_max is None else min(value, trend_max)


def solar_features(
    d: date, hour: int, sky: int, temperature_c: float, trend_max: float | None = None
) -> list[float]:
    return [hour, d.timetuple().tm_yday, sky, temperature_c, trend_years(d, trend_max)]


class JejuModel:
    """<dir>/wind.json, solar.json, meta.json 을 읽어 제주 전체 시간별 발전량을 예측한다."""

    def __init__(self, directory: Path):
        from xgboost import Booster

        self.meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        self.wind, self.solar = Booster(), Booster()
        self.wind.load_model(directory / "wind.json")
        self.solar.load_model(directory / "solar.json")

    def components(self, weather: list[WeatherHour]) -> tuple[list[float], list[float]]:
        import numpy as np
        from xgboost import DMatrix

        trend_max = self.meta["solar_trend_max"]
        wind_x = np.array(
            [wind_features(w.date, w.hour, w.wind_ms, w.temperature_c) for w in weather],
            dtype=float,
        )
        solar_x = np.array(
            [solar_features(w.date, w.hour, w.sky, w.temperature_c, trend_max) for w in weather],
            dtype=float,
        )
        wind = self.wind.predict(DMatrix(wind_x, feature_names=WIND_FEATURES))
        solar = self.solar.predict(DMatrix(solar_x, feature_names=SOLAR_FEATURES))
        if not all(math.isfinite(float(v)) for v in (*wind, *solar)):
            raise ValueError("Model returned non-finite predictions")
        return [max(0.0, float(v)) for v in wind], [max(0.0, float(v)) for v in solar]

    def predict(self, weather: list[WeatherHour]) -> list[EnergyHour]:
        wind, solar = self.components(weather)
        return [
            EnergyHour(date=w.date, hour=w.hour, mwh=a + b)
            for w, a, b in zip(weather, wind, solar, strict=True)
        ]
