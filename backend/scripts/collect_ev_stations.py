"""제주데이터허브 전기자동차 충전소 목록을 받아 로컬에 저장한다.

실행: python -m scripts.collect_ev_stations
필요: backend/.env 의 JEJUHUB_PROJECT_KEY. 저장 위치는 EV_SNAPSHOT_PATH(기본 runtime/ev_stations.json).
저장 파일은 runtime/ 아래라 Git에 올라가지 않는다(허브 데이터 외부 배포 금지).
"""

import sys

import httpx

from app.core.config import Settings
from app.providers.jejuhub_ev import (
    call_count,
    enable_call_log,
    ev_capacity,
    fetch_stations,
    save_snapshot,
)


def main() -> int:
    settings = Settings()
    if settings.jejuhub_project_key is None:
        print("JEJUHUB_PROJECT_KEY가 설정되어 있지 않습니다(backend/.env).", file=sys.stderr)
        return 2
    enable_call_log(settings.ev_snapshot_path.parent / "hub_calls.log")
    try:
        with httpx.Client(timeout=settings.http_timeout) as client:
            stations = fetch_stations(
                settings.jejuhub_project_key.get_secret_value(), client=client
            )
    except RuntimeError as exc:
        print(f"수집 실패: {exc} (이번 실행 허브 호출 {call_count()}회)", file=sys.stderr)
        return 1
    save_snapshot(stations, settings.ev_snapshot_path)
    print(f"이번 실행 허브 호출 {call_count()}회 (내역: runtime/hub_calls.log)")
    noon = ev_capacity(stations, 12)
    print(
        f"충전소 {len(stations)}곳 저장 → {settings.ev_snapshot_path}\n"
        f"12시 운영 {noon['stations_open']}곳, 완속 {noon['slow_chargers']}기, 급속 {noon['fast_chargers']}기\n"
        f"제외: 운영 시간 불명 {noon['stations_hours_unknown']}곳, 전용·제한 {noon['stations_restricted']}곳"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
