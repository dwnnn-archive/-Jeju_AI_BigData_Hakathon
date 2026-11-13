import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app


def test_decision_replay_recovers_commit_before_checkpoint(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / "state.sqlite", approver_token="officer")
    headers = {"X-Approver-Token": "officer"}
    decision = {"action": "approve", "reason": "reviewed"}
    with TestClient(create_app(settings)) as client:
        run = client.post("/api/v1/analyses", json={"date": "2026-11-14"}).json()
        store = client.app.state.service.store
        original = store.record_decision

        def crash_after_commit(*args):
            original(*args)
            raise RuntimeError("simulated process failure after outbox commit")

        monkeypatch.setattr(store, "record_decision", crash_after_commit)
        with pytest.raises(RuntimeError):
            client.post(f"/api/v1/analyses/{run['id']}/decision", json=decision, headers=headers)
    with TestClient(create_app(settings)) as restarted:
        response = restarted.post(
            f"/api/v1/analyses/{run['id']}/decision", json=decision, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["notification"]["attempts"] == 1
        assert response.json()["status"] == "approved"
        assert len(restarted.get(f"/api/v1/analyses/{run['id']}/audit").json()) == 1


def test_interrupted_dispatch_is_never_automatically_retried(tmp_path):
    settings = Settings(database_path=tmp_path / "state.sqlite", approver_token="officer")
    with TestClient(create_app(settings)) as client:
        run = client.post("/api/v1/analyses", json={"date": "2026-11-14"}).json()
        path = f"/api/v1/analyses/{run['id']}"
        client.post(
            path + "/decision",
            json={"action": "approve", "reason": "reviewed"},
            headers={"X-Approver-Token": "officer"},
        )
        # Simulate persisted delivery state at the instant a process was terminated.
        client.app.state.service.store.update_notification(run["id"], "sending")
    with TestClient(create_app(settings)) as restarted:
        response = restarted.post(path + "/dispatch", headers={"X-Approver-Token": "officer"})
        assert response.json()["notification"]["status"] == "delivery_unknown"
        assert response.json()["notification"]["attempts"] == 1


def test_retry_cannot_replace_persisted_resume_before_audit_commit(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / "state.sqlite", approver_token="officer")
    headers = {"X-Approver-Token": "officer"}
    first_decision = {"action": "approve", "reason": "first decision"}
    with TestClient(create_app(settings)) as client:
        run = client.post("/api/v1/analyses", json={"date": "2026-11-14"}).json()
        path = f"/api/v1/analyses/{run['id']}/decision"

        def crash_before_audit(*args):
            raise RuntimeError("interrupted before audit commit")

        monkeypatch.setattr(client.app.state.service.store, "record_decision", crash_before_audit)
        with pytest.raises(RuntimeError):
            client.post(path, json=first_decision, headers=headers)
    with TestClient(create_app(settings)) as restarted:
        conflict = restarted.post(
            path, json={"action": "reject", "reason": "changed"}, headers=headers
        )
        assert conflict.status_code == 409
        response = restarted.post(path, json=first_decision, headers=headers)
        assert response.status_code == 200
        assert response.json()["decision"]["action"] == "approve"
        assert response.json()["notification"]["attempts"] == 1
