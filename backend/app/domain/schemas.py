from datetime import date as Date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Region = Literal["jeju", "hallim", "jocheon", "haengwon"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AnalysisRequest(StrictModel):
    date: Date | None = None
    region: Region | None = None
    query: str | None = Field(default=None, max_length=1000)
    mode: Literal["demo", "live"] = "demo"
    scenario: Literal[
        "normal", "critical", "boundary", "boundary_stable", "intraday_escalation"
    ] = "critical"
    # day_ahead: 하루 전 계획(단기예보). intraday: 하루 전이 정상이던 날의 당일 점검(초단기예보).
    phase: Literal["day_ahead", "intraday"] = "day_ahead"


class EnergyHour(StrictModel):
    date: Date
    hour: int = Field(ge=0, le=23)
    mwh: NonNegative


class WeatherHour(StrictModel):
    date: Date
    hour: int = Field(ge=0, le=23)
    wind_ms: float = Field(ge=0, le=100)
    temperature_c: float = Field(ge=-70, le=70)
    sky: int = Field(ge=1, le=4)
    irradiance_wm2: float = Field(ge=0, le=1500)


class Capacities(StrictModel):
    # 배분은 이 필드 순서대로 앞 자원부터 채운다. 제주데이터허브 충전소·이력으로 용량을 계산하는
    # EV가 1순위이고, 나머지 세 자원은 EV로 다 담지 못할 때 보태는 확장 후보다.
    ev: NonNegative = 40
    bess: NonNegative = 37.7  # 제주 ESS 계량 실적의 시간당 최대 충전량(2024-01~2025-12)
    # 제주 플러스DR 실적(KPX 수요자원거래시장 보고서): 실시간 시장 월별 시간당 평균 증대량의 최댓값(2023-04, 73.7 MWh/23시간)
    vpp: NonNegative = 3.2
    p2x: NonNegative = 3.3  # 행원 그린수소 실증단지 수전해 3.3 MW(2026-09 보도), 1시간 상한


class Plant(StrictModel):
    id: str = Field(min_length=1)
    kind: Literal["wind", "solar"]
    capacity_mw: NonNegative
    source: str = Field(min_length=1)


class Decision(StrictModel):
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=1000)


class ConfirmRequest(StrictModel):
    result_token: str = Field(min_length=64, max_length=64)


class DraftRequest(StrictModel):
    previous: str | None = Field(default=None, max_length=3000)


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=1000)


class ReviewDecision(Decision):
    result_token: str = Field(min_length=64, max_length=64)


class LoginCheck(StrictModel):
    approver_id: str = Field(min_length=1, max_length=100)


class DispatchRequest(StrictModel):
    result_token: str = Field(min_length=64, max_length=64)


def validate_day(rows, target: Date):
    if len(rows) != 24 or {r.hour for r in rows} != set(range(24)):
        raise ValueError("Exactly 24 unique hours (0..23) are required")
    if any(r.date != target for r in rows):
        raise ValueError("All rows must match the requested KST date")
    return sorted(rows, key=lambda r: r.hour)
