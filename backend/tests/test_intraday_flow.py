"""하루 전 계획 + 당일 점검 이중 설계를 작업 큐·그래프·승인까지 끝까지 확인한다."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.rules import evaluate
from app.domain.schemas import EnergyHour
from app.main import create_app
from app.providers import demo
from app.providers.kma import KST
from app.repositories.forecasts import ForecastArchive
from app.tools.bundle import ToolBundle
from tests.helpers import wait_result

AUTH = {"X-Approver-Token": "test-officer-token"}
TODAY = datetime.now(KST).date()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_path=tmp_path / "state.sqlite",
        approver_token="test-officer-token",
        forecast_archive_enabled=True,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as value:
        # 오늘 날짜의 하루 전 분석은 어제 접수된 것으로 본다(외부 데이터 날짜 범위: 내일~모레).
        value.app.state.service.today = lambda: TODAY - timedelta(days=1)
        yield value


def post(client, body, key=None):
    return client.post(
        "/api/v1/analyses", json=body, headers={"Idempotency-Key": key or str(uuid4())}
    )


def run(client, body, key=None):
    response = post(client, body, key)
    assert response.status_code == 202, response.text
    return wait_result(client, response.json()["id"])


def demo_body(phase="day_ahead", scenario="intraday_escalation", day=None):
    return {
        "date": (day or TODAY).isoformat(),
        "region": "jeju",
        "mode": "demo",
        "scenario": scenario,
        "phase": phase,
    }


def decide(client, run, action="approve"):
    return client.post(
        f"/api/v1/analyses/{run['id']}/decision",
        json={"action": action, "reason": "현장 검토 완료", "result_token": run["result_token"]},
        headers=AUTH,
    )


def test_day_ahead_normal_then_two_intraday_checks_then_approval(client):
    """하루 전 정상 -> 당일 1차 정상 -> 당일 2차 위험 -> 승인 -> 모의 알림."""
    day_ahead = run(client, demo_body())
    assert (day_ahead["status"], day_ahead["result"]["risk"]) == ("completed", "NORMAL")
    assert day_ahead["phase"] == "day_ahead" and day_ahead["allocation"] is None

    first = run(client, demo_body("intraday"))
    assert (first["status"], first["result"]["risk"]) == ("completed", "NORMAL")
    assert first["phase"] == "intraday" and first["check_no"] == 1
    assert "INTRADAY:check1" in first["trace"]

    second = run(client, demo_body("intraday"))
    assert second["check_no"] == 2 and second["result"]["risk"] == "CRITICAL"
    assert second["status"] == "awaiting_approval" and second["can_decide"] is True
    assert second["allocation"]["absorbed_mwh"] == pytest.approx(84.2)  # 하루 전과 같은 배분 규칙
    assert second["sources"]["generation"]["source"] == "demo_scenario"

    approved = decide(client, second)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved" and body["notification"]["status"] == "mock_sent"


def test_intraday_is_only_accepted_when_the_rules_hold(client):
    # 하루 전 분석이 없으면 접수하지 않는다
    assert post(client, demo_body("intraday")).status_code == 409
    # 당일이 아니면 422
    yesterday = demo_body("intraday")
    yesterday["date"] = "2020-01-01"
    assert post(client, yesterday).status_code == 422

    # 하루 전이 위험이면 당일 점검으로 넘어가지 않는다(승인 대기도 밀려나지 않는다)
    critical = run(client, demo_body(scenario="critical"))
    assert critical["status"] == "awaiting_approval"
    refused = post(client, demo_body("intraday", scenario="critical"))
    assert refused.status_code == 409
    assert "NORMAL" in refused.json()["detail"]
    still = client.get(f"/api/v1/analyses/{critical['id']}").json()
    assert still["can_decide"] is True and "superseded" not in still["decision_blocks"]


def test_intraday_limit_is_two_and_same_key_is_idempotent(client):
    run(client, demo_body(scenario="normal"))
    key = str(uuid4())
    first = run(client, demo_body("intraday", "normal"), key)
    again = post(client, demo_body("intraday", "normal"), key)  # 같은 키 재요청
    assert again.status_code == 202 and again.json()["id"] == first["id"]
    second = run(client, demo_body("intraday", "normal"))
    assert (first["check_no"], second["check_no"]) == (1, 2)
    third = post(client, demo_body("intraday", "normal"))
    assert third.status_code == 409 and "limit" in third.json()["detail"]


# ---- 실제(live) 모드: 외부 호출은 가짜로 바꾸고 흐름·저장·차단만 확인한다 ----


def _fake_live(monkeypatch, escalate_on_intraday=True):
    normal = [EnergyHour(date=TODAY, hour=h, mwh=100) for h in range(24)]
    windy = [EnergyHour(date=TODAY, hour=h, mwh=450 if h == 12 else 100) for h in range(24)]
    demand = [EnergyHour(date=TODAY, hour=h, mwh=700) for h in range(24)]
    sources = {"source": "prediction", "simulated": False, "model": "m", "validated": False}
    monkeypatch.setattr(
        ToolBundle,
        "weather",
        lambda self, request, refresh: (
            demo.weather(request.date),
            {"source": "kma", "simulated": False},
        ),
    )
    monkeypatch.setattr(
        ToolBundle, "generation", lambda self, request, weather, refresh: (normal, sources)
    )
    monkeypatch.setattr(
        ToolBundle,
        "demand",
        lambda self, request: (demand, {"source": "demand_model", "simulated": False}),
    )

    def intraday(self, request, now, day_ahead_base=None):
        gen = windy if escalate_on_intraday else normal
        return {
            "result": evaluate(gen, demand, request.date, from_hour=7),
            "inputs": {
                "checked_at": "2026-01-01T07:45:00+09:00",
                "from_hour": 7,
                "day_ahead_base": ["20251231", "2300"],
                "sources": {"7": "nowcast", "8": "ultra", "20": "day_ahead"},
            },
        }

    monkeypatch.setattr(ToolBundle, "intraday_check", intraday)


def live_body(phase="day_ahead"):
    return {"date": TODAY.isoformat(), "region": "jeju", "mode": "live", "phase": phase}


def test_live_flow_flags_escalation_blocks_approval_and_archives_every_evaluation(
    client, settings, monkeypatch
):
    _fake_live(monkeypatch)
    day_ahead = run(client, live_body())
    assert (day_ahead["status"], day_ahead["result"]["risk"]) == ("completed", "NORMAL")

    check = run(client, live_body("intraday"))
    assert check["result"]["risk"] == "CRITICAL" and check["result"]["from_hour"] == 7
    assert check["status"] == "awaiting_approval" and check["check_no"] == 1
    assert check["intraday"]["hour_sources"]["8"] == "ultra"
    assert check["sources"]["weather"]["source"] == "kma_ultra_short"
    # 실제 모드는 검증 전이라 승인·발송이 계속 막힌다
    assert (
        check["can_decide"] is False
        and "operational_validation_missing" in check["decision_blocks"]
    )
    assert decide(client, check).status_code == 409

    logged = ForecastArchive(settings.database_path.parent / "forecasts.sqlite").evaluations()
    assert [(e["phase"], e["check_no"], e["risk"]) for e in logged] == [
        ("day_ahead", 0, "NORMAL"),
        ("intraday", 1, "CRITICAL"),
    ]
    assert '"20251231"' in logged[1]["inputs_json"] and logged[0]["inputs_json"] is None


def test_live_intraday_that_agrees_with_day_ahead_stays_normal_and_counts_as_a_check(
    client, monkeypatch
):
    _fake_live(monkeypatch, escalate_on_intraday=False)
    run(client, live_body())
    first = run(client, live_body("intraday"))
    assert (first["status"], first["result"]["risk"], first["check_no"]) == (
        "completed",
        "NORMAL",
        1,
    )
    second = run(client, live_body("intraday"))
    assert second["check_no"] == 2
    assert post(client, live_body("intraday")).status_code == 409  # 최대 2회


def test_failed_intraday_does_not_block_or_use_up_a_check(client, monkeypatch):
    """기상청 장애로 1차 점검이 실패해도 다음 점검이 가능하고, 실패는 횟수에 들어가지 않는다."""
    _fake_live(monkeypatch, escalate_on_intraday=False)
    run(client, live_body())
    healthy = ToolBundle.intraday_check

    def broken(self, request, now, day_ahead_base=None):
        raise ValueError("kma down")

    monkeypatch.setattr(ToolBundle, "intraday_check", broken)
    failed = run(client, live_body("intraday"))
    assert failed["status"] == "failed"

    monkeypatch.setattr(ToolBundle, "intraday_check", healthy)
    retry = run(client, live_body("intraday"))
    assert (retry["status"], retry["result"]["risk"], retry["check_no"]) == (
        "completed",
        "NORMAL",
        1,
    )
    second = run(client, live_body("intraday"))
    assert second["check_no"] == 2  # 실패한 시도는 세지 않아 정상 점검이 2회까지 가능
    assert post(client, live_body("intraday")).status_code == 409


def test_day_ahead_that_failed_is_not_a_base_for_intraday(client, monkeypatch):
    def broken(self, request, refresh):
        raise ValueError("kma down")

    monkeypatch.setattr(ToolBundle, "weather", broken)
    failed = run(client, live_body())
    assert failed["status"] == "failed"
    refused = post(client, live_body("intraday"))
    assert refused.status_code == 409 and "day-ahead" in refused.json()["detail"]


# ---- 스케줄러가 부르는 명령 ----

from scripts.run_intraday import (  # noqa: E402
    EXIT_FAILED,
    EXIT_FLAGGED,
    EXIT_OK,
    idempotency_key,
    run_intraday,
)


def test_idempotency_key_is_stable_per_slot_and_differs_between_slots():
    a = idempotency_key(TODAY, "jeju", "live", "0745")
    assert a == idempotency_key(TODAY, "jeju", "live", "0745")
    assert (
        len(
            {
                a,
                idempotency_key(TODAY, "jeju", "live", "1045"),
                idempotency_key(TODAY, "jeju", "demo", "0745"),
            }
        )
        == 3
    )
    assert len(a) == 36


def test_scheduler_command_runs_checks_and_reports_exit_codes(client):
    run(client, demo_body())  # 하루 전: 정상
    kwargs = {"mode": "demo", "scenario": "intraday_escalation", "poll": 0.01}
    code1, first = run_intraday(client, TODAY, slot="0745", **kwargs)
    assert code1 == EXIT_OK and first["risk"] == "NORMAL" and first["check_no"] == 1
    # 같은 슬롯을 스케줄러가 한 번 더 불러도 새 점검이 생기지 않는다
    code_again, again = run_intraday(client, TODAY, slot="0745", **kwargs)
    assert again["id"] == first["id"] and code_again == EXIT_OK
    code2, second = run_intraday(client, TODAY, slot="1045", **kwargs)
    assert code2 == EXIT_FLAGGED and second["risk"] == "CRITICAL" and second["check_no"] == 2
    # 이미 위험이 나온 날은 규칙 때문에 더 점검하지 않는다
    code3, third = run_intraday(client, TODAY, slot="1300", **kwargs)
    assert code3 == EXIT_FAILED and "NORMAL" in third["detail"]
