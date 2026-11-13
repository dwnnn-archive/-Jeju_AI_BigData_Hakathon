import math
from datetime import date

from app.domain.schemas import Capacities, EnergyHour, validate_day


def risk_level(surplus: float) -> str:
    return "CRITICAL" if surplus >= 200 else "CAUTION" if surplus >= 150 else "NORMAL"


def evaluate(generation: list[EnergyHour], demand: list[EnergyHour], target: date) -> dict:
    generation, demand = validate_day(generation, target), validate_day(demand, target)
    hourly = [
        {
            "hour": g.hour,
            "generation_mwh": g.mwh,
            "demand_mwh": d.mwh,
            "surplus_mwh": max(0.0, g.mwh - d.mwh),
            "risk": risk_level(max(0.0, g.mwh - d.mwh)),
        }
        for g, d in zip(generation, demand, strict=True)
    ]
    peak = max(hourly, key=lambda row: row["surplus_mwh"])
    return {
        "hourly": hourly,
        "peak_hour": peak["hour"],
        "peak_surplus_mwh": peak["surplus_mwh"],
        "risk": peak["risk"],
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
