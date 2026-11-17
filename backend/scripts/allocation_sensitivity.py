"""저장된 날짜별 평가 결과(runtime/e2e/days.json)로 배분 용량 기준별 '용량 이내 비율'을 다시 계산한다.

실행(backend/ 에서): python -m scripts.allocation_sensitivity [days.json 경로]
모델을 다시 돌리지 않는다. 날짜별 예측 피크 잉여(peak_surplus_mwh)에 용량 기준만 바꿔 적용한다.
EV 용량은 충전소 파일(runtime/ev_stations.json)과 충전 이력 프로필(runtime/ev_profile.json)이 있으면
그날 피크 시각의 값을 쓰고, 없으면 가정(고정 40 MWh)을 쓴다.
"""

import json
import sys
from datetime import date
from pathlib import Path

from app.core.config import Settings
from app.domain.schemas import Capacities
from app.tools.bundle import ToolBundle


def share_within(flagged: list[dict], capacity) -> tuple[int, float, float]:
    """(용량 이내 일수, 비율, 전체 잉여 대비 흡수 비율)."""
    within = sum(d["peak_surplus_mwh"] <= capacity(d) for d in flagged)
    total = sum(d["peak_surplus_mwh"] for d in flagged)
    absorbed = sum(min(d["peak_surplus_mwh"], capacity(d)) for d in flagged)
    return within, within / len(flagged), absorbed / total if total else 1.0


def main(path: Path) -> None:
    days = json.loads(path.read_text(encoding="utf-8"))
    flagged = [d for d in days if d["risk"] in ("CAUTION", "CRITICAL")]
    caps = Capacities().model_dump()
    fixed = caps["bess"] + caps["vpp"] + caps["p2x"]  # EV를 뺀 합계
    bundle = ToolBundle(Settings())
    ev_by_day = {}
    for d in flagged:
        ev = bundle.ev_allocation_input(d["peak_hour"], date.fromisoformat(d["date"]))
        ev_by_day[d["date"]] = ev["capacity_mwh"] if ev else caps["ev"]
    cases = [
        (f"EV 제외 (BESS+VPP+P2X = {fixed:.1f})", lambda d: fixed),
        (
            f"EV 고정 {caps['ev']:.0f} 포함 (합계 {fixed + caps['ev']:.1f})",
            lambda d: fixed + caps["ev"],
        ),
        ("EV 가정 82.6 포함 (이용률 50%, 출력 7/50 kW)", lambda d: fixed + 82.57),
        ("EV 충전 이력 반영 (시각별)", lambda d: fixed + ev_by_day[d["date"]]),
    ]
    print(
        f"위험 판정일(CAUTION 이상) {len(flagged)}일, 기간 {days[0]['date']} ~ {days[-1]['date']}"
    )
    for name, cap in cases:
        n, frac, absorbed = share_within(flagged, cap)
        print(f"{name}: 용량 이내 {n}/{len(flagged)} = {frac:.1%}, 흡수 비율 {absorbed:.1%}")


if __name__ == "__main__":
    main(
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Settings().ev_profile_path.parent / "e2e/days.json"
    )
