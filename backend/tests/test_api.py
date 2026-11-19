from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.helpers import submit

AUTH = {"X-Approver-Token": "test-officer-token"}
REQUEST = {"date": "2026-11-14", "region": "jeju"}


def in_days(n):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    return (datetime.now(ZoneInfo("Asia/Seoul")).date() + timedelta(days=n)).isoformat()


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=tmp_path / "state.sqlite", approver_token="test-officer-token")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as value:
        yield value


def create(client, scenario="critical"):
    return submit(client, {**REQUEST, "scenario": scenario})


def decide(client, run_id, action="approve", headers=None, result_token=None):
    return client.post(
        f"/api/v1/analyses/{run_id}/decision",
        json={
            "action": action,
            "reason": "현장 검토 완료",
            "result_token": result_token
            or client.get(f"/api/v1/analyses/{run_id}").json()["result_token"],
        },
        headers=AUTH if headers is None else headers,
    )


def test_critical_waits_for_approval_and_sends_only_after_authenticated_decision(client):
    run = create(client)
    assert run["status"] == "awaiting_approval"
    assert run["result"]["peak_surplus_mwh"] == 230
    assert run["allocation"]["hydrogen_kg"] == pytest.approx(42.9)  # P2X 3.3 MWh x 13 kg/MWh
    assert run["notification"] is None
    assert decide(client, run["id"], headers={}).status_code == 401
    assert (
        client.post(
            f"/api/v1/analyses/{run['id']}/dispatch",
            headers=AUTH,
            json={"result_token": run["result_token"]},
        ).status_code
        == 409
    )
    result = decide(client, run["id"]).json()
    assert result["status"] == "approved"
    assert result["decision"]["actor"] == "local-officer"
    assert result["notification"]["status"] == "mock_sent"


def test_normal_day_finishes_without_approval_or_outbox(client):
    run = create(client, "normal")
    assert run["status"] == "completed"
    assert run["result"]["risk"] == "NORMAL"
    assert run["allocation"] is None
    assert decide(client, run["id"]).status_code == 409


def test_boundary_refetch_changes_prediction_and_retains_history(client):
    run = create(client, "boundary")
    assert run["refresh_count"] == 1
    assert run["result"]["risk"] == "CRITICAL"
    assert run["evaluations"][0]["peak_surplus_mwh"] == pytest.approx(
        28
    )  # 비율 0.44, CRITICAL 직전
    assert run["evaluations"][0]["risk"] == "CAUTION"
    assert run["evaluations"][1]["peak_surplus_mwh"] == pytest.approx(230)


def test_persistent_boundary_does_not_loop_forever(client):
    run = create(client, "boundary_stable")
    assert run["refresh_count"] == 1
    assert run["boundary_unresolved"] is True
    assert run["result"]["risk"] == "CAUTION"


def test_reject_is_terminal_and_has_no_notification(client):
    run = create(client)
    response = decide(client, run["id"], "reject")
    assert response.json()["status"] == "rejected"
    assert response.json()["notification"] is None
    assert decide(client, run["id"]).status_code == 409


def test_repeated_approval_and_dispatch_do_not_duplicate_side_effects(client):
    run = create(client)
    first = decide(client, run["id"]).json()["notification"]
    second = decide(client, run["id"]).json()["notification"]
    third = client.post(
        f"/api/v1/analyses/{run['id']}/dispatch",
        headers=AUTH,
        json={"result_token": run["result_token"]},
    ).json()["notification"]
    assert first["id"] == second["id"] == third["id"]
    assert third["attempts"] == 1
    assert len(client.get(f"/api/v1/analyses/{run['id']}/audit").json()) == 1


def test_restart_preserves_interrupt_and_allows_approval(settings):
    with TestClient(create_app(settings)) as first:
        run = create(first)
    with TestClient(create_app(settings)) as second:
        loaded = second.get(f"/api/v1/analyses/{run['id']}").json()
        assert loaded["status"] == "awaiting_approval"
        assert decide(second, run["id"]).json()["status"] == "approved"


def test_concurrent_approvals_are_serialized(client):
    run = create(client)
    token = run["result_token"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: decide(client, run["id"], result_token=token), range(2))
        )
    assert any(response.status_code == 200 for response in responses)
    for response in responses:
        # Slow CI may exceed the bounded lock wait. Reconcile with the same request.
        if response.status_code == 503:
            response = decide(client, run["id"], result_token=token)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "approved"
        assert result["result_token"] == token
        assert result["notification"]["id"] == run["id"]
        assert result["notification"]["status"] == "mock_sent"
        assert result["notification"]["attempts"] == 1
    assert len(client.get(f"/api/v1/analyses/{run['id']}/audit").json()) == 1


def test_busy_concurrent_approval_retry_preserves_one_decision(client, monkeypatch):
    run = create(client)
    token = run["result_token"]
    entered, release = Event(), Event()
    original = client.app.state.service.engine.decide

    def hold_first_decision(*args, **kwargs):
        entered.set()
        assert release.wait(10), "Test did not release the approval"
        return original(*args, **kwargs)

    monkeypatch.setattr(client.app.state.service.engine, "decide", hold_first_decision)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(decide, client, run["id"], result_token=token)
        try:
            assert entered.wait(5), "First approval did not start"
            second = decide(client, run["id"], result_token=token)
            assert second.status_code == 503
            pending = client.get(f"/api/v1/analyses/{run['id']}").json()
            assert pending["status"] == "decision_pending"
            assert not pending["can_decide"]
            assert pending["notification"] is None
            assert client.get(f"/api/v1/analyses/{run['id']}/audit").json() == []
        finally:
            release.set()
        completed = first.result(timeout=5)
    assert completed.status_code == 200, completed.text
    replay = decide(client, run["id"], result_token=token)
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "approved"
    assert replay.json()["result_token"] == token
    assert replay.json()["decision"] == completed.json()["decision"]
    assert replay.json()["notification"]["id"] == completed.json()["notification"]["id"]
    assert replay.json()["notification"]["status"] == "mock_sent"
    assert replay.json()["notification"]["attempts"] == 1
    assert len(client.get(f"/api/v1/analyses/{run['id']}/audit").json()) == 1


def test_explicit_live_fallback_is_visible_but_cannot_be_approved(settings):
    settings.allow_mock_fallback = True
    settings.notification_mode = "webhook"
    with TestClient(create_app(settings)) as client:
        response = submit(client, {**REQUEST, "date": in_days(1), "mode": "live"})
        assert response["sources"]["weather"]["simulated"] is True
        assert not response["can_decide"]
        run = create(client)
        result = decide(client, run["id"]).json()
        assert result["notification"]["status"] == "blocked"
        assert result["notification"]["attempts"] == 0


def test_strict_live_failure_is_recorded_without_leaking_upstream_secrets(settings):
    settings.allow_mock_fallback = False
    with TestClient(create_app(settings)) as client:
        response = submit(client, {**REQUEST, "date": in_days(1), "mode": "live"})
        assert response["status"] == "failed"
        runs = client.get("/api/v1/analyses").json()
        assert runs[0]["status"] == "failed"


def test_api_key_protects_reads_and_writes_when_configured(settings):
    settings.api_token = "reader-key"
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/analyses").status_code == 401
        assert (
            client.get("/api/v1/analyses", headers={"X-API-Key": "reader-key"}).status_code == 200
        )


def test_approval_is_disabled_without_configured_token(settings):
    settings.approver_token = None
    with TestClient(create_app(settings)) as client:
        run = create(client)
        assert decide(client, run["id"]).status_code == 503


def test_query_and_grounded_chat_cannot_approve(client):
    run = submit(client, {"query": "2026-11-14 한림 위험 분석"})
    reply = client.post(
        f"/api/v1/analyses/{run['id']}/chat", json={"message": "승인하고 발송해"}
    ).json()
    assert reply["status"] == "awaiting_approval"
    assert reply["notification"] is None
    assert "승인 API" in reply["answer"]
    answer = client.post(
        f"/api/v1/analyses/{run['id']}/chat", json={"message": "수소 생산량?"}
    ).json()
    assert "42.90" in answer["answer"]


def test_invalid_and_unknown_requests_have_defined_errors(client):
    assert client.post("/api/v1/analyses", json={}).status_code == 422
    assert client.post("/api/v1/analyses", json={**REQUEST, "mode": "typo"}).status_code == 422
    assert client.get("/api/v1/analyses/not-found").status_code == 404


def test_non_ascii_auth_headers_are_unauthorized_not_server_errors(settings):
    settings.api_token = "reader-key"
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        assert client.get("/api/v1/analyses", headers={b"X-API-Key": b"\xff"}).status_code == 401
    settings.api_token = None
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        run = create(client)
        response = decide(client, run["id"], headers={b"X-Approver-Token": b"\xff"})
        assert response.status_code == 401


def test_login_check_verifies_officer_id_and_token(client):
    ok = client.post("/api/v1/auth/check", json={"approver_id": "local-officer"}, headers=AUTH)
    assert ok.status_code == 200
    assert ok.json() == {"approver_id": "local-officer"}
    wrong_token = client.post(
        "/api/v1/auth/check",
        json={"approver_id": "local-officer"},
        headers={"X-Approver-Token": "nope"},
    )
    assert wrong_token.status_code == 401
    wrong_id = client.post("/api/v1/auth/check", json={"approver_id": "someone"}, headers=AUTH)
    assert wrong_id.status_code == 401
    missing = client.post("/api/v1/auth/check", json={"approver_id": "local-officer"})
    assert missing.status_code == 401


def test_login_check_is_disabled_without_configured_token(settings):
    settings.approver_token = None
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/auth/check", json={"approver_id": "local-officer"}, headers=AUTH
        )
        assert response.status_code == 503


def test_live_day_ahead_accepts_only_tomorrow_and_the_day_after(settings):
    settings.allow_mock_fallback = True
    with TestClient(create_app(settings)) as client:
        for n in (1, 2):
            body = {**REQUEST, "date": in_days(n), "mode": "live"}
            assert client.post(
                "/api/v1/analyses", json=body, headers={"Idempotency-Key": str(uuid4())}
            ).status_code == 202
        for n in (-1, 0, 3):
            body = {**REQUEST, "date": in_days(n), "mode": "live"}
            out = client.post(
                "/api/v1/analyses", json=body, headers={"Idempotency-Key": str(uuid4())}
            )
            assert out.status_code == 422 and out.json()["detail"] == "date_out_of_range"


def test_demo_mode_has_no_date_limit(settings):
    with TestClient(create_app(settings)) as client:
        for n in (-30, 0, 10):
            body = {**REQUEST, "date": in_days(n), "mode": "demo", "scenario": "critical"}
            assert client.post(
                "/api/v1/analyses", json=body, headers={"Idempotency-Key": str(uuid4())}
            ).status_code == 202
