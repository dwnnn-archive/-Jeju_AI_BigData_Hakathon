def _station_line(allocation: dict) -> str:
    """허브 충전소 데이터가 있으면 여력이 큰 충전소 상위 3곳을 알림에 적는다."""
    top = (allocation.get("ev_basis") or {}).get("top_stations") or []
    if not top:
        return ""
    names = ", ".join(s["name"] for s in top[:3])
    return f"EV 충전 여력이 큰 충전소(설치 규모 기준): {names}\n"


def footer_lines(allocation: dict) -> str:
    """초안 끝의 충전소 안내와 한계 문구. LLM 초안에도 같은 문구를 코드가 붙인다."""
    return (
        _station_line(allocation)
        + "피크 1시간 권고안. "
        + (
            "EV 용량만 제주데이터허브 충전소 정보 기반이며 나머지 자원 가용량은 시연 추정치입니다. "
            if allocation.get("ev_basis")
            else "자원 가용량은 시연 추정치이며 "
        )
        + "현장 검증과 담당자 승인이 필요합니다."
    )


def draft_notification(result: dict, allocation: dict) -> str:
    return (
        f"[제주 출력제한 대응 권고] {result['date']} {result['peak_hour']:02d}:00 KST\n"
        f"위험등급: {result['risk']}, 발전량/수요 비율 최대 {result['peak_ratio']:.0%}\n"
        f"피크 잉여전력(수요의 {result['thresholds']['warning_ratio']:.0%} 초과분): "
        f"{result['peak_surplus_mwh']:.2f} MWh\n"
        f"BESS/VPP/P2X/EV 배분(MWh): {allocation['allocated_mwh']}\n"
        f"흡수율: {allocation['absorption_pct']:.2f}%, 잔여: {allocation['residual_mwh']:.2f} MWh\n"
        f"수소 환산: {allocation['hydrogen_kg']:.2f} kg (13 kg/MWh 가정)\n"
        + footer_lines(allocation)
    )
