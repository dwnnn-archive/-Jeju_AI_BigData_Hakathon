import json
import sqlite3
from uuid import uuid4

from filelock import FileLock
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.agents.graph import build_graph
from app.providers.notifications import NotificationSender
from app.repositories.sqlite import Store
from app.tools.bundle import ToolBundle
from app.tools.tool1_kma_weather import parse_request


class ConflictError(Exception):
    pass


class AnalysisUnavailable(Exception):
    def __init__(self, run_id):
        self.run_id = run_id


class AnalysisService:
    def __init__(self, settings):
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(settings.database_path) + ".lock", timeout=120)
        with self.lock:
            self.store = Store(settings.database_path)
            self.connection = sqlite3.connect(
                settings.database_path, check_same_thread=False, timeout=30
            )
            self.saver = SqliteSaver(self.connection)
            self.saver.setup()
            self.graph = build_graph(
                ToolBundle(settings), self.store, self.saver, settings.max_refreshes
            )
        self.sender = NotificationSender(settings, self.store)

    @staticmethod
    def config(run_id):
        return {"configurable": {"thread_id": run_id}, "recursion_limit": 64}

    def create(self, request, run_id=None):
        request = parse_request(request)
        run_id = run_id or str(uuid4())
        with self.lock:
            self.store.create(run_id, request.model_dump(mode="json"))
            try:
                self.graph.invoke(
                    {
                        "id": run_id,
                        "request": request.model_dump(mode="json"),
                        "status": "running",
                        "refresh_count": 0,
                        "sources": {},
                        "trace": ["R1:validated"],
                        "evaluations": [],
                    },
                    self.config(run_id),
                )
            except sqlite3.OperationalError:
                raise
            except Exception as exc:
                self.store.fail(run_id, "analysis_failed")
                raise AnalysisUnavailable(run_id) from exc
            return self._get(run_id)

    def _get(self, run_id):
        record = self.store.run(run_id)
        state = self.graph.get_state(self.config(run_id)).values
        result = {
            key: state.get(key)
            for key in ("result", "allocation", "draft", "decision", "boundary_unresolved")
        }
        result.update(
            {
                "id": run_id,
                "request": json.loads(record["request"]),
                "created_at": record["created_at"],
                "status": "failed" if record["error"] else state.get("status", "running"),
                "error": record["error"],
                "sources": state.get("sources", {}),
                "refresh_count": state.get("refresh_count", 0),
                "trace": state.get("trace", []),
                "evaluations": state.get("evaluations", []),
                "notification": self.store.notification(run_id),
                "decision_intent": self.store.decision_intent(run_id),
            }
        )
        return result

    def get(self, run_id):
        with self.lock:
            return self._get(run_id)

    def list(self, limit=20):
        with self.lock:
            return [self._get(run_id) for run_id in self.store.runs(limit)]

    def decide(self, run_id, decision, actor):
        with self.lock:
            run = self._get(run_id)
            expected = "approved" if decision.action == "approve" else "rejected"
            value = {**decision.model_dump(), "actor": actor}
            if run["status"] == expected:
                if run["decision"] != value:
                    raise ConflictError("The recorded decision differs from this request")
            elif run["status"] == "awaiting_approval":
                # An interrupted approval may have already committed audit/outbox before
                # its graph checkpoint. Replay the same authorized decision only.
                audits = self.store.audit(run_id)
                if audits and audits[0]["decision"] != value:
                    raise ConflictError("A different decision has already been recorded")
                if run["decision_intent"] is not None and run["decision_intent"] != value:
                    raise ConflictError("A different decision is already being processed")
                self.store.reserve_decision(run_id, value)
                self.graph.invoke(Command(resume=value), self.config(run_id))
            else:
                raise ConflictError("Analysis is not awaiting approval")
            if expected == "approved":
                self.sender.dispatch(run_id)
            return self._get(run_id)

    def dispatch(self, run_id):
        with self.lock:
            if self._get(run_id)["status"] != "approved":
                raise ConflictError("Analysis must be approved before dispatch")
            self.sender.dispatch(run_id)
            return self._get(run_id)

    def audit(self, run_id):
        with self.lock:
            return self.store.audit(run_id)

    def chat(self, run_id, message):
        run = self.get(run_id)
        if any(word in message for word in ("승인", "발송", "반려")):
            answer = "상태 변경은 담당자 인증 후 승인 API를 사용하세요."
        elif not run["result"]:
            answer = "완료된 분석 결과가 없습니다."
        elif any(word in message for word in ("수소", "배분", "흡수")) and run["allocation"]:
            a = run["allocation"]
            answer = (
                f"피크 1시간 배분: {a['allocated_mwh']} MWh. "
                f"흡수율 {a['absorption_pct']:.2f}%, 수소 {a['hydrogen_kg']:.2f} kg. "
                "시연 가용량과 수소 환산계수에 따른 권고안입니다."
            )
        else:
            r = run["result"]
            answer = (
                f"{r['date']} {r['peak_hour']:02d}시 KST: {r['risk']}, "
                f"피크 잉여전력 {r['peak_surplus_mwh']:.2f} MWh. "
                f"재조회 {run['refresh_count']}회. 계산 결과에 근거한 제한형 응답입니다."
            )
        return {
            "analysis_id": run_id,
            "answer": answer,
            "status": run["status"],
            "notification": run["notification"],
            "sources": run["sources"],
        }

    def close(self):
        self.store.close()
        self.connection.close()
