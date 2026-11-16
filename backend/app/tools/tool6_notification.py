def draft_notification(result: dict, allocation: dict) -> str:
    return (
        f"[제주 출력제한 대응 권고] {result['date']} {result['peak_hour']:02d}:00 KST\n"
        f"위험등급: {result['risk']}, 발전량/수요 비율 최대 {result['peak_ratio']:.0%}\n"
        f"피크 잉여전력(수요의 {result['thresholds']['warning_ratio']:.0%} 초과분): "
        f"{result['peak_surplus_mwh']:.2f} MWh\n"
        f"BESS/VPP/P2X/EV 배분(MWh): {allocation['allocated_mwh']}\n"
        f"흡수율: {allocation['absorption_pct']:.2f}%, 잔여: {allocation['residual_mwh']:.2f} MWh\n"
        f"수소 환산: {allocation['hydrogen_kg']:.2f} kg (13 kg/MWh 가정)\n"
        "피크 1시간 권고안. 자원 가용량은 시연 추정치이며 현장 검증과 담당자 승인이 필요합니다."
    )
