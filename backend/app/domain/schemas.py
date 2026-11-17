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
    bess: NonNegative = 37.7  # 제주 ESS 계량 실적의 시간당 최대 충전량(2024-01~2025-12)
    vpp: NonNegative = 30
    p2x: NonNegative = 3.3  # 행원 그린수소 실증단지 수전해 3.3 MW(2026-09 보도), 1시간 상한
    ev: NonNegative = 40


class Plant(StrictModel):
    id: str = Field(min_length=1)
    kind: Literal["wind", "solar"]
    capacity_mw: NonNegative
    source: str = Field(min_length=1)


class Decision(StrictModel):
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=1000)


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
