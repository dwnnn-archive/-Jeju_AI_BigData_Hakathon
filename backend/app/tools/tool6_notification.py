def _station_line(allocation: dict) -> str:
    """허브 충전소 데이터가 있으면 여력이 큰 충전소 상위 3곳을 알림에 적는다."""
    top = (allocation.get("ev_basis") or {}).get("top_stations") or []
    if not top:
        return ""
    names = ", ".join(s["name"] for s in top[:3])
    return f"EV 충전 여력이 큰 충전소(설치 규모 기준): {names}\n"


def _mwh(value: float) -> str:
    """소수 첫째 자리까지. 정수면 소수점 없이(30.0 -> 30, 108.994 -> 109)."""
    return str(int(round(value))) if abs(value - round(value)) < 0.05 else f"{value:.1f}"


def _allocated_line(allocated: dict) -> str:
    """배분량을 'BESS 37.7 / VPP 30 / P2X 3.3 / EV 109' 모양으로 쓴다(긴 소수점 없이)."""
    return " / ".join(f"{name.upper()} {_mwh(float(value))}" for name, value in allocated.items())


def footer_lines(allocation: dict) -> str:
    """초안 끝의 충전소 안내와 한계 문구. LLM 초안에도 같은 문구를 코드가 붙인다."""
    return (
        _station_line(allocation)
        + "피크 1시간 대응 후보 제안(참고). "
        + (
            "EV 용량은 제주데이터허브 충전소 정보 기반, BESS는 ESS 계량 실적, P2X는 보도 수치이며 "
            "VPP는 흡수 가능량 자료가 없는 가정값입니다. "
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
        f"EV/BESS/VPP/P2X 배분(MWh): {_allocated_line(allocation['allocated_mwh'])}\n"
        f"흡수율: {allocation['absorption_pct']:.2f}%, 잔여: {allocation['residual_mwh']:.2f} MWh\n"
        f"수소 환산: {allocation['hydrogen_kg']:.2f} kg (13 kg/MWh 가정)\n"
        + footer_lines(allocation)
    )
