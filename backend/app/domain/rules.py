import math
from datetime import date

from app.domain.schemas import Capacities, EnergyHour, validate_day

# 위험 규칙: 예측 발전량 / 수요 비율.
# 제주 출력제한 이력(2021-01 ~ 2024-05)으로 보정했다. 근거와 검증은 docs/guides/demand-options.md.
# - 이전 규칙(잉여 = 발전량 - 수요, 150/200 MWh)은 실제 수요에서 출력제한 1,592시간 중 단 한 시간도
#   잡지 못했다. 제주는 재생에너지가 수요의 절반에 못 미쳐도 출력제한이 걸린다.
# - 비율 0.40 이상이면 출력제한일의 83~89%를 잡고(위험일의 73~78%가 실제 제한일),
#   0.45 이상이면 66~77%를 잡는다(위험일의 83~88%가 실제 제한일). 수요 출처(KPX 예측, 자체 모델)와
#   무관하게 비슷한 값이라 같은 기준을 쓴다.
WARNING_RATIO = 0.40  # 이 비율부터 CAUTION. 초과분(잉여) 계산의 기준선이기도 하다.
CRITICAL_RATIO = 0.45  # 이 비율부터 CRITICAL
BOUNDARY_RATIO = 0.43  # CRITICAL 직전 구간(0.43 ~ 0.45): 경계값 재검증 대상


def risk_level(ratio: float) -> str:
    return (
        "CRITICAL" if ratio >= CRITICAL_RATIO else "CAUTION" if ratio >= WARNING_RATIO else "NORMAL"
    )


def surplus_mwh(generation: float, demand: float) -> float:
    """경계선(수요 x WARNING_RATIO)을 넘는 발전량. 배분(흡수) 대상 물량이다."""
    return max(0.0, generation - WARNING_RATIO * demand)


def is_boundary(peak_ratio: float) -> bool:
    return BOUNDARY_RATIO <= peak_ratio <= CRITICAL_RATIO


def evaluate(
    generation: list[EnergyHour],
    demand: list[EnergyHour],
    target: date,
    from_hour: int = 0,
) -> dict:
    """from_hour 이후(포함) 시간으로만 피크와 등급을 정한다(당일 점검에서 지난 시간 제외)."""
    if not 0 <= from_hour <= 23:
        raise ValueError("from_hour must be within 0..23")
    generation, demand = validate_day(generation, target), validate_day(demand, target)
    hourly = []
    for g, d in zip(generation, demand, strict=True):
        if d.mwh <= 0:
            raise ValueError("Demand must be positive")
        ratio = g.mwh / d.mwh
        hourly.append(
            {
                "hour": g.hour,
                "generation_mwh": g.mwh,
                "demand_mwh": d.mwh,
                "ratio": ratio,
                "surplus_mwh": surplus_mwh(g.mwh, d.mwh),
                "risk": risk_level(ratio),
            }
        )
    window = [row for row in hourly if row["hour"] >= from_hour]
    peak = max(window, key=lambda row: (row["surplus_mwh"], row["ratio"]))
    peak_ratio = max(row["ratio"] for row in window)
    return {
        "hourly": hourly,
        "peak_hour": peak["hour"],
        "peak_surplus_mwh": peak["surplus_mwh"],
        "peak_ratio": peak_ratio,
        "risk": risk_level(peak_ratio),
        "from_hour": from_hour,
        "thresholds": {
            "warning_ratio": WARNING_RATIO,
            "critical_ratio": CRITICAL_RATIO,
            "surplus_basis": "generation - warning_ratio * demand",
        },
        "date": target.isoformat(),
        "timezone": "Asia/Seoul",
        "interval_hours": 1,
        "energy_unit": "MWh",
    }


def allocate(peak: float, capacities: Capacities | None = None) -> dict:
    if not math.isfinite(peak) or peak < 0:
        raise ValueError("Surplus must be finite and nonnegative")
    caps = (capacities or Capacities()).model_dump()
    remaining, assigned = peak, {}
    for resource, capacity in caps.items():
        assigned[resource] = min(remaining, capacity)
        remaining -= assigned[resource]
    absorbed = peak - remaining
    return {
        "allocated_mwh": assigned,
        "capacities_mwh": caps,
        "absorbed_mwh": absorbed,
        "residual_mwh": remaining,
        "absorption_pct": absorbed / peak * 100 if peak else 0,
        "hydrogen_kg": assigned["p2x"] * 13,
        "scope": "peak_hour_only",
        "availability_source": "estimated_demo",
        "availability_verified": False,
    }
