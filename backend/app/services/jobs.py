"""Public application service: durable receipt, truthful status and result-bound decisions."""

import hashlib
import json
import sqlite3
import threading
from datetime import datetime
from uuid import UUID

from filelock import FileLock

from app.domain.schemas import AnalysisRequest, Decision
from app.providers.kma import KST
from app.repositories.jobs import JobRepository, iso_now, utcnow
from app.services.analysis import AnalysisService, ConflictError
from app.tools.tool1_kma_weather import parse_request


def result_token(snapshot):
    fields = ("id", "request", "result", "allocation", "sources", "draft")
    content = json.dumps(
        {key: snapshot.get(key) for key in fields},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(content.encode()).hexdigest()


class JobService:
    def __init__(self, settings):
        self.settings = settings
        self.engine = AnalysisService(settings)
        self.jobs = JobRepository(settings.database_path)
        self.review_lock = FileLock(str(settings.database_path) + ".review.lock", timeout=10)
        self.execution_lock = FileLock(str(settings.database_path) + ".worker.lock", timeout=0)
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.runner = None
        self.worker_error = None

    def submit(self, request, key):
        key = str(UUID(key))
        request = parse_request(request)
        with self.review_lock:
            if request.phase == "intraday":
                self._require_intraday_allowed(request, key)
            try:
                row = self.jobs.insert(key, request.model_dump(mode="json"))
            except ValueError as exc:
                raise ConflictError(str(exc)) from exc
        self.wake.set()
        return self._view(row)

    def _require_intraday_allowed(self, request, key):
        """당일 점검은 당일에, 하루 전이 정상으로 끝난 날에만, 최대 횟수 안에서 접수한다."""
        try:
            self.jobs.get(key)
            return  # 같은 키의 재요청은 기존 접수를 돌려주므로 규칙을 다시 따지지 않는다
        except KeyError:
            pass
        if request.date != datetime.now(KST).date():
            raise ValueError("Intraday checks are only available for today (KST)")
        rows = self.jobs.scope_rows(self.jobs.scope_of(request.model_dump(mode="json")))
        if not rows:
            raise ConflictError("A day-ahead analysis for this date is required first")
        if any(r["status"] in ("queued", "running") for r in rows):
            raise ConflictError("An analysis for this date is still in progress")
        # 실패·중단된 시도는 건너뛴다. 기상청 장애로 한 번 실패해도
        # 다음 점검으로 만회할 수 있어야 한다.
        rows = [r for r in rows if r["status"] not in ("failed", "interrupted")]
        if not rows:
            raise ConflictError("A day-ahead analysis for this date is required first")
        latest = rows[-1]
        risk = (
            (json.loads(latest["snapshot_json"]) if latest["snapshot_json"] else {}).get("result")
            or {}
        ).get("risk")
        if latest["status"] != "completed" or risk != "NORMAL":
            raise ConflictError("Intraday checks only follow a day that was judged NORMAL")
        done = [
            r
            for r in rows
            if self.jobs.is_intraday(r) and r["status"] not in ("failed", "interrupted")
        ]
        if len(done) >= self.settings.max_intraday_checks:
            raise ConflictError("The intraday check limit for this date has been reached")

    def _view(self, row, summary=False):
        snapshot = json.loads(row["snapshot_json"]) if row["snapshot_json"] else {}
        status = row["status"]
        fresh_until = None
        if status == "running":
            heartbeat = datetime.fromisoformat(row["heartbeat_at"])
            age = (utcnow() - heartbeat).total_seconds()
            if age > self.settings.worker_stale_seconds:
                status = "status_unknown"
            fresh_until = heartbeat.timestamp() + self.settings.worker_stale_seconds
        request = json.loads(row["request_json"])
        blocks = []
        if status != "awaiting_approval":
            blocks.append("not_awaiting_approval")
        if row["legacy"]:
            blocks.append("legacy_result")
        if not self.jobs.latest(row):
            blocks.append("superseded")
        if row["expires_at"] and utcnow() >= datetime.fromisoformat(row["expires_at"]):
            blocks.append("result_expired")
        if snapshot.get("boundary_unresolved"):
            blocks.append("boundary_unresolved")
        # No field or API key can promote the current unvalidated model/SOC to operational use.
        if request["mode"] != "demo":
            blocks.append("operational_validation_missing")
        if not row["result_token"]:
            blocks.append("result_unavailable")
        view = {
            **snapshot,
            "id": row["id"],
            "request": request,
            "status": status,
            "version": row["version"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "heartbeat_at": row["heartbeat_at"],
            "finished_at": row["finished_at"],
            "expires_at": row["expires_at"],
            "server_checked_at": iso_now(),
            "fresh_until_epoch": fresh_until,
            "result_token": row["result_token"],
            "error": row["error"],
            "can_decide": not blocks,
            "decision_blocks": blocks,
            "operationally_validated": False,
            "phase": request.get("phase", "day_ahead"),
            "simulation": request["mode"] == "demo",
            "result": snapshot.get("result"),
            "allocation": snapshot.get("allocation"),
            "draft": snapshot.get("draft"),
            "decision": snapshot.get("decision"),
            "decision_intent": snapshot.get("decision_intent"),
            "notification": snapshot.get("notification"),
            "sources": snapshot.get("sources", {}),
        }
        if summary:
            for field in ("draft", "allocation", "notification", "evaluations", "trace"):
                view.pop(field, None)
            if view["result"]:
                view["result"] = {k: v for k, v in view["result"].items() if k != "hourly"}
        return view

    def get(self, run_id):
        return self._view(self.jobs.get(run_id))

    def list(self, limit=20):
        return [self._view(r, summary=True) for r in self.jobs.list(limit)]

    def _save(self, run_id, snapshot):
        self.jobs.finish(
            run_id,
            snapshot["status"],
            snapshot,
            result_token(snapshot),
            self.settings.result_ttl_seconds,
            snapshot.get("error"),
        )

    def run_once(self):
        # All processes share this execution lock; reads never take it.
        with self.engine.lock:
            run_id = self.jobs.next_queued()
            if run_id is None or not self.jobs.start(run_id):
                return False
            stopped = threading.Event()

            def beat():
                while not stopped.wait(self.settings.heartbeat_seconds):
                    self.jobs.heartbeat(run_id)

            heartbeat = threading.Thread(target=beat, daemon=True)
            heartbeat.start()
            try:
                row = self.jobs.get(run_id)
                request = AnalysisRequest.model_validate_json(row["request_json"])
                check_no = self.jobs.intraday_rank(row) if request.phase == "intraday" else 0
                snapshot = self.engine.create(request, run_id=run_id, check_no=check_no)
            except sqlite3.OperationalError:
                raise
            except Exception:
                self.jobs.finish(run_id, "failed", error="analysis_failed")
            else:
                # A storage failure is not a calculation failure; recover from the checkpoint.
                self._save(run_id, snapshot)
            finally:
                stopped.set()
                heartbeat.join()
            return True

    def recover(self):
        with self.engine.lock:
            for row in self.jobs.unfinished():
                try:
                    snapshot = self.engine.get(row["id"])
                    if snapshot["status"] in (
                        "completed",
                        "awaiting_approval",
                        "approved",
                        "rejected",
                    ):
                        if snapshot.get("decision_intent"):
                            if snapshot["status"] == "awaiting_approval":
                                self.jobs.finish(row["id"], "decision_pending", snapshot)
                                continue
                        self._save(row["id"], snapshot)
                        continue
                except KeyError:
                    pass
                self.jobs.finish(row["id"], "interrupted", error="worker_interrupted")
            # Preserve pre-migration history as read-only snapshots.
            for (run_id,) in self.engine.store.conn.execute(
                "SELECT id FROM runs WHERE id NOT IN (SELECT id FROM jobs)"
            ).fetchall():
                snapshot = self.engine.get(run_id)
                self.jobs.insert(run_id, snapshot["request"], legacy=True)
                status = snapshot["status"]
                if status == "running":
                    snapshot["status"] = "interrupted"
                self._save(run_id, snapshot)

    def decide(self, run_id, action, reason, token, actor):
        # Never wait behind a long analysis or hold the receipt lock while waiting.
        # Validate expiry/latest result only after obtaining exclusive execution access.
        with self.engine.lock.acquire(timeout=0.25), self.review_lock:
            view = self.get(run_id)
            if not token or token != view["result_token"]:
                raise ConflictError("The reviewed result does not match the current result")
            value = {"action": action, "reason": reason, "actor": actor}
            repeated = view["status"] in ("approved", "rejected", "decision_pending")
            if repeated:
                recorded = view.get("decision") or view.get("decision_intent")
                if recorded != value:
                    raise ConflictError("The recorded decision differs from this request")
            elif not view["can_decide"]:
                raise ConflictError("Decision blocked: " + ", ".join(view["decision_blocks"]))
            if not repeated:
                try:
                    self.jobs.reserve_decision(run_id, value)
                except ValueError as exc:
                    raise ConflictError(str(exc)) from exc
            try:
                snapshot = self.engine.decide(run_id, Decision(action=action, reason=reason), actor)
            except Exception:
                snapshot = self.engine.get(run_id)
                if snapshot.get("decision_intent"):
                    self.jobs.finish(run_id, "decision_pending", snapshot)
                raise
            self._save(run_id, snapshot)
            return self.get(run_id)

    def dispatch(self, run_id, token):
        with self.engine.lock.acquire(timeout=0.25), self.review_lock:
            view = self.get(run_id)
            if not token or token != view["result_token"] or view["status"] != "approved":
                raise ConflictError("Dispatch requires the approved result token")
            if view["request"]["mode"] != "demo":
                raise ConflictError("Operational dispatch is unavailable")
            self._save(run_id, self.engine.dispatch(run_id))
            return self.get(run_id)

    def audit(self, run_id):
        self.jobs.get(run_id)
        # Separate connection avoids the execution lock even while another job runs.
        with self.jobs.connection() as conn:
            return [
                {"decision": json.loads(row["decision"]), "created_at": row["created_at"]}
                for row in conn.execute("SELECT * FROM audit WHERE analysis_id=?", (run_id,))
            ]

    def chat(self, run_id, message):
        run = self.get(run_id)
        if any(word in message for word in ("승인", "발송", "반려")):
            answer = "상태 변경은 담당자 인증 후 승인 API를 사용하세요."
        elif not run["result"]:
            answer = "아직 확인된 계산 결과가 없습니다."
        elif any(word in message for word in ("수소", "배분", "흡수")) and run["allocation"]:
            answer = (
                f"피크 1시간 수소 환산 {run['allocation']['hydrogen_kg']:.2f} kg. "
                "시연 추정치입니다."
            )
        else:
            answer = (
                f"{run['result']['date']} 피크 잉여전력 "
                f"{run['result']['peak_surplus_mwh']:.2f} MWh."
            )
        return {
            "analysis_id": run_id,
            "answer": answer,
            "status": run["status"],
            "sources": run["sources"],
            "notification": run["notification"],
        }

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.runner:
            self.runner.join()
        self.engine.close()
