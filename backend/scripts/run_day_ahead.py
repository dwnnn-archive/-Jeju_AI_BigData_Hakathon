"""하루 전 계획(내일 대상)을 서버 없이 한 번 돌려 판정 기록(evaluations)을 쌓는다. 작업 스케줄러가 매일 호출한다.

사용 (backend/ 에서, backend/.env 에 KMA_API_KEY 등 필요):
    python -m scripts.run_day_ahead                 # 매일 17:30 작업 스케줄러가 호출
    python -m scripts.run_day_ahead --mode demo     # 키 없이 흐름만 확인(기록은 실제 DB에 남는다)

- 앱을 프로세스 안에서 띄워 분석 1건을 돌리고 끝난다. 서버를 따로 켜 둘 필요가 없다.
- 대상은 실행 시점의 **내일**이다. 하루 전 판정은 오늘 날짜로는 돌릴 수 없다(지난 시간대 예보가 없다).
- **17:15~23:50 사이에만** 돈다. 그 밖이면 건너뛴다. PC가 꺼졌다 늦게 켜져 따라잡기로 실행되면
  "내일"이 엉뚱한 날이 되기 때문이다. 건너뛴 날의 판정 기록은 복구되지 않는다.
- 같은 날짜·지역·모드는 같은 멱등 키를 쓴다. 두 번 호출해도 기록은 한 건이다.
  (앞선 시도가 실패로 끝났으면 키를 바꿔 한 번 다시 시도한다.)
- 종료 코드: 0 완료(위험이면 승인 대기로 남는다), 1 실패, 2 시간 초과, 3 시간 창 밖이라 건너뜀.
- live 모드에서 위험이면 승인 대기 건이 남는다. 승인과 발송은 live 에서 항상 막혀 있고 이 스크립트는 승인하지 않는다.
- 통보문 초안을 위해 ANTHROPIC_API_KEY 가 있으면 판정 결과가 LLM 으로 전송된다.
"""

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.providers.kma import KST

EXIT_OK, EXIT_FAILED, EXIT_TIMEOUT, EXIT_SKIPPED = 0, 1, 2, 3
DONE = ("completed", "awaiting_approval", "approved", "rejected", "failed", "interrupted")
WINDOW = (dtime(17, 15), dtime(23, 50))


def target_for(now: datetime) -> date | None:
    """실행 시각이 시간 창 안이면 내일, 밖이면 None."""
    local = now.astimezone(KST)
    if WINDOW[0] <= local.time() <= WINDOW[1]:
        return local.date() + timedelta(days=1)
    return None


def idempotency_key(target: date, region: str, mode: str, attempt: int = 0) -> str:
    suffix = f"/retry{attempt}" if attempt else ""
    return str(uuid5(NAMESPACE_URL, f"jeju-curtailment/day_ahead/{target}/{region}/{mode}{suffix}"))


def run_day_ahead(
    client,
    target: date,
    region: str = "jeju",
    mode: str = "live",
    api_key: str | None = None,
    timeout: float = 180,
    poll: float = 1.0,
) -> tuple[int, dict]:
    headers = {"X-API-Key": api_key} if api_key else {}
    summary: dict = {}
    for attempt in (0, 1):
        body = {"date": target.isoformat(), "region": region, "mode": mode, "phase": "day_ahead"}
        response = client.post(
            "/api/v1/analyses",
            json=body,
            headers={**headers, "Idempotency-Key": idempotency_key(target, region, mode, attempt)},
        )
        if response.status_code != 202:
            return EXIT_FAILED, {
                "error": response.status_code,
                "detail": response.json().get("detail"),
            }
        run_id = response.json()["id"]
        deadline = time.monotonic() + timeout
        run = None
        while time.monotonic() < deadline:
            run = client.get(f"/api/v1/analyses/{run_id}", headers=headers).json()
            if run["status"] in DONE:
                break
            time.sleep(poll)
        else:
            return EXIT_TIMEOUT, {"id": run_id, "status": "timeout", "target": target.isoformat()}
        result = run.get("result") or {}
        summary = {
            "id": run_id,
            "target": target.isoformat(),
            "attempt": attempt,
            "status": run["status"],
            "risk": result.get("risk"),
            "peak_ratio": result.get("peak_ratio"),
            "peak_hour": result.get("peak_hour"),
            "peak_surplus_mwh": result.get("peak_surplus_mwh"),
        }
        if run["status"] not in ("failed", "interrupted"):
            return EXIT_OK, summary
    return EXIT_FAILED, summary


def settings_with_default_models() -> Settings:
    """모델 경로가 설정에 없으면 runtime/models 아래 기본 위치를 쓴다(있을 때만)."""
    s = Settings()
    updates = {}
    for field, default in (
        ("jeju_model_dir", Path("runtime/models/jeju")),
        ("jeju_demand_model_dir", Path("runtime/models/demand")),
    ):
        if getattr(s, field) is None and default.is_dir():
            updates[field] = default
    return s.model_copy(update=updates) if updates else s


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--region", default="jeju")
    p.add_argument("--mode", default="live", choices=["live", "demo"])
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument(
        "--ignore-window", action="store_true", help="시간 창 밖에서도 내일로 실행(시험용)"
    )
    a = p.parse_args(argv)
    now = datetime.now(KST)
    target = target_for(now) or (now.date() + timedelta(days=1) if a.ignore_window else None)
    if target is None:
        print(
            json.dumps(
                {"status": "skipped", "reason": "outside 17:15-23:50 KST", "now": now.isoformat()}
            )
        )
        return EXIT_SKIPPED
    settings = settings_with_default_models()
    token = settings.api_token
    with TestClient(create_app(settings)) as client:
        code, summary = run_day_ahead(
            client, target, a.region, a.mode, token.get_secret_value() if token else None, a.timeout
        )
    print(json.dumps(summary, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
