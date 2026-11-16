"""당일 점검 한 번을 서버에 요청한다. 외부 스케줄러(작업 스케줄러, cron 등)가 호출한다.

사용 (서버가 떠 있어야 한다):
    python -m scripts.run_intraday --slot 0745          # 07:45 점검
    python -m scripts.run_intraday --slot 1045          # 10:45 점검
    python -m scripts.run_intraday --api http://127.0.0.1:8000 --slot 0745 --region jeju

- 같은 날짜·지역·슬롯에는 항상 같은 멱등 키를 보내므로 스케줄러가 두 번 호출해도
  점검이 중복되지 않는다(서버가 기존 접수를 그대로 돌려준다).
- 서버가 규칙을 강제한다: 당일만, 하루 전이 정상으로 끝난 날만, 진행 중인 작업이 없을 때, 최대 2회.
  규칙에 어긋나면 이유를 출력하고 종료 코드 1로 끝난다(알림이 필요한 상황이 아니다).
- 종료 코드: 0 점검 완료(정상), 10 점검 결과가 위험(승인 대기),
  1 요청 실패나 규칙 위반, 2 시간 초과.
- 서버에 API_TOKEN 이 있으면 환경 변수/.env 의 API_TOKEN 을 X-API-Key 로 보낸다.
"""

import argparse
import json
import sys
import time
from datetime import date, datetime
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.core.config import Settings
from app.providers.kma import KST

EXIT_OK, EXIT_FAILED, EXIT_TIMEOUT, EXIT_FLAGGED = 0, 1, 2, 10
DONE = ("completed", "awaiting_approval", "approved", "rejected", "failed", "interrupted")


def idempotency_key(day: date, region: str, mode: str, slot: str) -> str:
    """같은 날짜·지역·모드·슬롯이면 항상 같은 키(UUID)."""
    return str(uuid5(NAMESPACE_URL, f"jeju-curtailment/intraday/{day}/{region}/{mode}/{slot}"))


def run_intraday(
    client: httpx.Client,
    day: date,
    region: str = "jeju",
    mode: str = "live",
    slot: str = "0745",
    scenario: str | None = None,
    api_key: str | None = None,
    timeout: float = 120,
    poll: float = 1.0,
) -> tuple[int, dict]:
    body = {"date": day.isoformat(), "region": region, "mode": mode, "phase": "intraday"}
    if scenario:
        body["scenario"] = scenario
    headers = {"Idempotency-Key": idempotency_key(day, region, mode, slot)}
    if api_key:
        headers["X-API-Key"] = api_key
    response = client.post("/api/v1/analyses", json=body, headers=headers)
    if response.status_code != 202:
        return EXIT_FAILED, {"error": response.status_code, "detail": response.json().get("detail")}
    run_id = response.json()["id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/analyses/{run_id}", headers=headers).json()
        if run["status"] in DONE:
            summary = {
                "id": run_id,
                "status": run["status"],
                "check_no": run.get("check_no"),
                "risk": (run.get("result") or {}).get("risk"),
                "peak_ratio": (run.get("result") or {}).get("peak_ratio"),
                "peak_surplus_mwh": (run.get("result") or {}).get("peak_surplus_mwh"),
            }
            if run["status"] in ("failed", "interrupted"):
                return EXIT_FAILED, summary
            return (EXIT_OK if summary["risk"] == "NORMAL" else EXIT_FLAGGED), summary
        time.sleep(poll)
    return EXIT_TIMEOUT, {"id": run_id, "status": "timeout"}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--slot", required=True, help="점검 시각 슬롯(예: 0745). 멱등 키에 쓴다.")
    p.add_argument("--region", default="jeju")
    p.add_argument("--mode", default="live", choices=["live", "demo"])
    p.add_argument("--scenario", help="demo 모드 시연 시나리오")
    p.add_argument("--timeout", type=float, default=120)
    a = p.parse_args(argv)
    token = Settings().api_token
    with httpx.Client(base_url=a.api, timeout=30) as client:
        code, summary = run_intraday(
            client,
            datetime.now(KST).date(),
            a.region,
            a.mode,
            a.slot,
            a.scenario,
            token.get_secret_value() if token else None,
            a.timeout,
        )
    print(json.dumps(summary, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
