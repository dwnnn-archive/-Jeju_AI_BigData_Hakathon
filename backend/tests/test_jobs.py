import sqlite3
import time
from threading import Event, Thread
from uuid import uuid4

import pytest
from filelock import Timeout

from app.core.config import Settings
from app.domain.schemas import AnalysisRequest
from app.services.analysis import ConflictError
from app.services.jobs import JobService
from app.services.worker import start_worker


@pytest.fixture
def service(tmp_path):
    value = JobService(Settings(database_path=tmp_path / "jobs.sqlite", worker_enabled=False))
    yield value
    value.close()


def submit(service, **kwargs):
    return service.submit(AnalysisRequest(date="2026-11-15", **kwargs), str(uuid4()))


def test_receipt_does_not_claim_analysis_started(service):
    run = submit(service)
    assert run["status"] == "queued"
    assert run["started_at"] is None
    assert run["result"] is None
    assert not run["can_decide"]


def test_idempotency_reconciles_lost_receipt_without_new_job(service):
    key = str(uuid4())
    request = AnalysisRequest(date="2026-11-15")
    first = service.submit(request, key)
    second = service.submit(request, key)
    assert first["id"] == second["id"] == key
    assert len(service.list()) == 1
    with pytest.raises(ConflictError):
        service.submit(AnalysisRequest(date="2026-11-16"), key)


def test_started_only_after_worker_executes_and_reads_do_not_wait(service, monkeypatch):
    entered, release = Event(), Event()
    original = service.engine.create

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(service.engine, "create", slow)
    run = submit(service)
    thread = Thread(target=service.run_once)
    thread.start()
    try:
        assert entered.wait(2)
        started = time.monotonic()
        view = service.get(run["id"])
        assert time.monotonic() - started < 0.5
        assert view["status"] == "running"
        assert view["started_at"] is not None
    finally:
        release.set()
        thread.join(5)
    assert service.get(run["id"])["status"] == "awaiting_approval"


def test_expired_heartbeat_is_unknown_not_running(service):
    run = submit(service)
    service.jobs.start(run["id"])
    with service.jobs.connection() as conn:
        conn.execute("UPDATE jobs SET heartbeat_at='2000-01-01T00:00:00+00:00'")
    assert service.get(run["id"])["status"] == "status_unknown"
    assert not service.get(run["id"])["can_decide"]


def test_result_token_and_newer_analysis_gate_decisions(service):
    first = submit(service)
    service.run_once()
    result = service.get(first["id"])
    assert result["can_decide"]
    with pytest.raises(ConflictError):
        service.decide(first["id"], "approve", "검토", "wrong-token", "officer")
    submit(service)
    assert not service.get(first["id"])["can_decide"]
    with pytest.raises(ConflictError):
        service.decide(first["id"], "approve", "검토", result["result_token"], "officer")


def test_live_missing_data_fails_without_demo_result(service):
    run = submit(service, mode="live")
    service.run_once()
    result = service.get(run["id"])
    assert result["status"] == "failed"
    assert result["result"] is None
    assert not result["can_decide"]


def test_result_expiry_and_unresolved_boundary_prevent_approval(service):
    run = submit(service, scenario="boundary_stable")
    service.run_once()
    result = service.get(run["id"])
    assert "boundary_unresolved" in result["decision_blocks"]
    assert not result["can_decide"]
    other = submit(service)
    service.run_once()
    with service.jobs.connection() as conn:
        conn.execute(
            "UPDATE jobs SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (other["id"],)
        )
    assert "result_expired" in service.get(other["id"])["decision_blocks"]
    with pytest.raises(ConflictError):
        service.decide(
            other["id"], "approve", "검토", service.get(other["id"])["result_token"], "officer"
        )


def test_approved_state_keeps_notification_semantics(service):
    run = submit(service)
    service.run_once()
    result = service.get(run["id"])
    approved = service.decide(run["id"], "approve", "시연 검토", result["result_token"], "officer")
    assert approved["status"] == "approved"
    assert approved["notification"]["status"] == "mock_sent"
    assert approved["operationally_validated"] is False


def test_restart_marks_unfinished_running_as_interrupted(tmp_path):
    settings = Settings(database_path=tmp_path / "state.sqlite", worker_enabled=False)
    service = JobService(settings)
    run = submit(service)
    service.jobs.start(run["id"])
    service.close()
    restarted = JobService(settings)
    try:
        restarted.recover()
        assert restarted.get(run["id"])["status"] == "interrupted"
        assert not restarted.get(run["id"])["can_decide"]
    finally:
        restarted.close()


def test_worker_recovers_after_temporary_database_failure(service, monkeypatch):
    run = submit(service)
    original = service.jobs.next_queued
    failed = Event()

    def temporarily_locked():
        if not failed.is_set():
            failed.set()
            raise sqlite3.OperationalError("database is locked")
        return original()

    monkeypatch.setattr(service.jobs, "next_queued", temporarily_locked)
    start_worker(service)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if service.get(run["id"])["status"] == "awaiting_approval":
            break
        time.sleep(0.02)
    assert failed.is_set()
    assert service.runner.is_alive()
    assert service.worker_error is None
    assert service.get(run["id"])["status"] == "awaiting_approval"


def test_busy_graph_rejects_decision_promptly_without_blocking_receipts(service):
    run = submit(service)
    service.run_once()
    result = service.get(run["id"])
    entered, release = Event(), Event()

    def occupy_graph():
        with service.engine.lock:
            entered.set()
            release.wait(5)

    thread = Thread(target=occupy_graph)
    thread.start()
    try:
        assert entered.wait(2)
        started = time.monotonic()
        with pytest.raises(Timeout):
            service.decide(run["id"], "approve", "시연", result["result_token"], "officer")
        assert time.monotonic() - started < 0.5
        assert submit(service)["status"] == "queued"
        assert not service.audit(run["id"])
    finally:
        release.set()
        thread.join(5)


@pytest.mark.parametrize("after_commit", [False, True])
def test_hard_crash_during_decision_never_reopens_review(tmp_path, monkeypatch, after_commit):
    settings = Settings(database_path=tmp_path / "crash.sqlite", worker_enabled=False)
    service = JobService(settings)
    run = submit(service)
    service.run_once()
    original = service.engine.decide

    def crash(*args):
        if after_commit:
            original(*args)
        raise SystemExit("simulated process death: skips Exception recovery")

    monkeypatch.setattr(service.engine, "decide", crash)
    result = service.get(run["id"])
    with pytest.raises(SystemExit):
        service.decide(run["id"], "approve", "시연", result["result_token"], "officer")
    assert service.get(run["id"])["status"] == "decision_pending"
    assert not service.get(run["id"])["can_decide"]
    service.close()
    restarted = JobService(settings)
    try:
        restarted.recover()
        restored = restarted.get(run["id"])
        assert restored["status"] == ("approved" if after_commit else "decision_pending")
        assert not restored["can_decide"]
        replay = restarted.decide(run["id"], "approve", "시연", result["result_token"], "officer")
        assert replay["status"] == "approved"
        assert len(restarted.audit(run["id"])) == 1
    finally:
        restarted.close()


def test_expiry_is_checked_inside_decision_transaction(service):
    run = submit(service)
    service.run_once()
    view = service.get(run["id"])
    with service.jobs.connection() as conn:
        conn.execute("UPDATE jobs SET expires_at='2000-01-01T00:00:00+00:00'")
    with pytest.raises(ValueError, match="expired"):
        service.jobs.reserve_decision(
            run["id"], {"action": "approve", "reason": "시연", "actor": "officer"}
        )
    assert not service.audit(run["id"])
    assert service.get(run["id"])["status"] == "awaiting_approval"
    assert view["result_token"] == service.get(run["id"])["result_token"]


def test_snapshot_write_failure_recovers_completed_graph(service, monkeypatch):
    run = submit(service)
    original = service.jobs.finish
    failed = False

    def transient(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise sqlite3.OperationalError("database is locked")
        return original(*args, **kwargs)

    monkeypatch.setattr(service.jobs, "finish", transient)
    with pytest.raises(sqlite3.OperationalError):
        service.run_once()
    assert service.engine.get(run["id"])["status"] == "awaiting_approval"
    assert service.get(run["id"])["status"] != "failed"
    service.recover()
    assert service.get(run["id"])["status"] == "awaiting_approval"
