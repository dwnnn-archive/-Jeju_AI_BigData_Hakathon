import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.tools import chat_agent
from tests.helpers import submit

REQUEST = {"date": "2026-11-14", "region": "jeju", "scenario": "critical"}


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(name, args=None, id="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=args or {}, id=id)


def reply(*blocks, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


class FakeClient:
    """미리 정한 응답을 차례로 돌려주고, 받은 요청을 기록한다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy({k: v for k, v in kwargs.items() if k != "messages"}))
        self.calls[-1]["n_messages"] = len(kwargs["messages"])
        step = self.responses.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def app_client(tmp_path):
    settings = Settings(database_path=tmp_path / "state.sqlite", approver_token="t" * 12)
    with TestClient(create_app(settings)) as client:
        yield client


def run_critical(client):
    return submit(client, REQUEST)


def chat(client, run_id, message="오늘 위험한가요?", fake=None):
    client.app.state.service.chat_client = fake
    response = client.post(f"/api/v1/analyses/{run_id}/chat", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


GOOD = "위험 등급은 CRITICAL이고 피크 잉여전력은 230.0 MWh입니다. 시연 데이터 기준입니다."


def test_llm_picks_tool_and_answer_uses_only_tool_numbers(app_client):
    run = run_critical(app_client)
    fake = FakeClient(reply(tool_use("get_risk_summary"), stop="tool_use"), reply(text(GOOD)))
    out = chat(app_client, run["id"], fake=fake)
    assert out["mode"] == "llm" and out["answer"] == GOOD
    assert out["tools_used"] == [{"name": "get_risk_summary", "input": {}}]
    # 두 번째 요청에는 도구 결과가 실려 갔다
    assert fake.calls[1]["n_messages"] == 3
    assert fake.calls[0]["tool_choice"] == {"type": "auto"}


def test_unfaithful_number_is_retried_once_then_accepted(app_client):
    run = run_critical(app_client)
    bad = "피크 잉여전력은 999.0 MWh입니다."
    fake = FakeClient(
        reply(tool_use("get_risk_summary"), stop="tool_use"), reply(text(bad)), reply(text(GOOD))
    )
    out = chat(app_client, run["id"], fake=fake)
    assert out["mode"] == "llm" and out["answer"] == GOOD
    assert len(fake.calls) == 3


def test_repeated_unfaithful_numbers_fall_back_to_rules(app_client):
    run = run_critical(app_client)
    bad = "피크 잉여전력은 999.0 MWh입니다."
    fake = FakeClient(
        reply(tool_use("get_risk_summary"), stop="tool_use"), reply(text(bad)), reply(text(bad))
    )
    out = chat(app_client, run["id"], message="잉여전력은?", fake=fake)
    assert out["mode"] == "rules" and out["mode_reason"] == "unfaithful"
    assert "999" not in out["answer"] and out["tools_used"] == []


def test_answer_without_any_tool_is_not_used(app_client):
    run = run_critical(app_client)
    out = chat(app_client, run["id"], fake=FakeClient(reply(text(GOOD))))
    assert out["mode"] == "rules" and out["mode_reason"] == "no_tool_used"
    assert "질문에 답할 수 있습니다" in out["answer"] and "MWh" not in out["answer"]


def test_api_error_and_refusal_fall_back_without_failing_the_request(app_client):
    run = run_critical(app_client)
    out = chat(app_client, run["id"], fake=FakeClient(RuntimeError("boom")))
    assert out["mode"] == "rules" and out["mode_reason"] == "error:RuntimeError"
    out = chat(app_client, run["id"], fake=FakeClient(reply(text("거절"), stop="refusal")))
    assert out["mode"] == "rules" and out["mode_reason"] == "stop:refusal"


def test_without_key_uses_keyword_answer(app_client):
    run = run_critical(app_client)
    out = chat(app_client, run["id"], message="수소는 얼마나 만들 수 있어?", fake=None)
    assert out["mode"] == "rules" and out["mode_reason"] == "no_key"
    assert "수소 환산" in out["answer"]


def test_keyword_guard_still_blocks_state_change_requests_without_llm(app_client):
    run = run_critical(app_client)
    out = chat(app_client, run["id"], message="이거 승인해 줘", fake=None)
    assert out["mode"] == "rules" and "승인 API" in out["answer"]


def test_chat_never_changes_state(app_client):
    run = run_critical(app_client)
    fake = FakeClient(
        reply(tool_use("get_review_status"), stop="tool_use"),
        reply(text("발송 확정은 아직 기록되지 않았습니다.")),
    )
    chat(app_client, run["id"], message="승인해 줘", fake=fake)
    after = app_client.get(f"/api/v1/analyses/{run['id']}").json()
    assert after["status"] == "awaiting_approval" and after["decision"] is None
    assert after["notification"] is None


def test_unknown_tool_is_reported_as_error_not_executed(app_client):
    run = run_critical(app_client)
    fake = FakeClient(
        reply(tool_use("approve_and_send", {"x": 1}), stop="tool_use"),
        reply(tool_use("get_risk_summary", id="tu_2"), stop="tool_use"),
        reply(text(GOOD)),
    )
    out = chat(app_client, run["id"], fake=fake)
    assert out["mode"] == "llm"
    assert [t["name"] for t in out["tools_used"]] == [
        "get_risk_summary"
    ]  # 모르는 도구는 기록하지 않는다


def test_tool_set_is_read_only_and_strict():
    names = list(chat_agent.TOOLS)
    assert not any(
        w in n for n in names for w in ("approve", "dispatch", "send", "decide", "reject")
    )
    assert all(
        d["strict"] and d["input_schema"]["additionalProperties"] is False
        for d in chat_agent.tool_definitions()
    )


def test_strict_schemas_use_no_unsupported_keywords():
    # strict 스키마가 minimum/maximum 등을 받지 않아 API가 400을 냈다(실제 호출).
    banned = {"minimum", "maximum", "minLength", "maxLength", "pattern", "format"}
    for d in chat_agent.tool_definitions():
        for prop in d["input_schema"]["properties"].values():
            assert not banned & set(prop), (d["name"], prop)


def test_tools_do_not_mutate_the_run_and_format_numbers_as_strings(app_client):
    run = run_critical(app_client)
    before = copy.deepcopy(run)
    outputs = [spec["fn"](run, {}) for spec in chat_agent.TOOLS.values()]
    assert run == before
    risk = chat_agent.tool_risk_summary(run, {})
    assert risk["risk"] == "CRITICAL" and risk["peak_surplus_mwh"] == "230.0"
    assert risk["peak_window"] == "12:00–13:00" and isinstance(risk["peak_hour"], int)
    assert all(isinstance(o, dict) for o in outputs)
    one = chat_agent.tool_hourly_forecast(run, {"hour": 12})["hours"]
    assert len(one) == 1 and one[0]["hour"] == 12
    assert chat_agent.tool_hourly_forecast(run, {"hour": 99}) == {
        "available": False,
        "reason": "0~23 사이의 시각만 조회할 수 있습니다.",
    }


def test_tools_say_so_when_there_is_no_result_or_no_ev_file():
    empty = {"result": None, "allocation": None, "sources": {}, "simulation": True}
    assert chat_agent.tool_risk_summary(empty, {})["available"] is False
    assert chat_agent.tool_allocation(empty, {})["available"] is False
    assert chat_agent.tool_ev_stations(empty, {})["available"] is False


def test_ev_tool_lists_top_stations_and_keeps_the_ranking_caveat():
    run = {
        "allocation": {
            "ev_basis": {
                "stations_total": 3180,
                "stations_open": 2969,
                "capacity_mwh": 109.0,
                "basis": "history_profile",
                "history_months": ["202104", "202204"],
                "top_stations": [
                    {
                        "name": "가 충전소",
                        "slow_chargers": 10,
                        "fast_chargers": 2,
                        "capacity_mwh": 0.25,
                    }
                ],
            }
        }
    }
    out = chat_agent.tool_ev_stations(run, {})
    assert (
        out["top_stations"][0]["name"] == "가 충전소"
        and out["top_stations"][0]["capacity_kwh"] == "250"
    )
    assert out["top_count"] == 1 and "혼잡도" in out["ranking_note"]


def test_unsupported_numbers_allows_equal_values_and_question_numbers():
    ev = ['{"peak": "230.0", "hour": 12}']
    assert chat_agent.unsupported_numbers("230 MWh, 12시", ev, "") == []
    assert chat_agent.unsupported_numbers("12시에 231 MWh", ev, "") == ["231"]
    assert (
        chat_agent.unsupported_numbers("15시는 어떤가요? 15시 값은 모릅니다", ev, "15시는?") == []
    )


def test_regenerate_draft_returns_new_text_without_changing_the_run(app_client):
    run = run_critical(app_client)
    absorption = f"{run['allocation']['absorption_pct']:.2f}"
    body = f"CRITICAL 위험이 예상됩니다. 피크 잉여전력은 230.00 MWh이며 흡수율 {absorption}%를 목표로 제안합니다."
    app_client.app.state.service.chat_client = FakeClient(reply(text(body)))
    before = app_client.get(f"/api/v1/analyses/{run['id']}").json()
    response = app_client.post(f"/api/v1/analyses/{run['id']}/draft", json={})
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "llm" and "230.00" in out["draft"]
    after = app_client.get(f"/api/v1/analyses/{run['id']}").json()
    assert after["draft"] == before["draft"] and after["status"] == before["status"]


def test_regenerate_draft_without_key_falls_back_to_template(app_client):
    run = run_critical(app_client)
    app_client.app.state.service.chat_client = None
    out = app_client.post(f"/api/v1/analyses/{run['id']}/draft", json={}).json()
    assert out["mode"] == "template" and out["mode_reason"] == "no_key"
    assert out["draft"].startswith("[제주 출력제한 대응 권고]")


def test_data_sources_separates_past_backtest_from_missing_operational_validation():
    live = {
        "simulation": False,
        "sources": {"generation": {"source": "prediction", "model": "xgboost", "simulated": False}},
    }
    out = chat_agent.tool_data_sources(live, {})
    assert "offline_backtest" in out and "80.8%" in out["offline_backtest"]
    assert "아직 하지 않음" in out["operational_validation"]
    assert all("validated" not in s for s in out["sources"])
    demo = {"simulation": True, "sources": {"generation": {"source": "demo_scenario", "simulated": True}}}
    assert "offline_backtest" not in chat_agent.tool_data_sources(demo, {})


def test_confirmation_is_recorded_once_without_login_and_changes_nothing_else(app_client):
    run = run_critical(app_client)
    assert run["confirmation"] is None
    url = f"/api/v1/analyses/{run['id']}/confirm"
    first = app_client.post(url, json={"result_token": run["result_token"]})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["confirmation"]["confirmed_at"] and body["version"] == run["version"] + 1
    # 같은 확인을 다시 눌러도 처음 기록이 그대로이고 버전도 늘지 않는다
    again = app_client.post(url, json={"result_token": run["result_token"]}).json()
    assert again["confirmation"] == body["confirmation"] and again["version"] == body["version"]
    # 발송·결정 상태는 건드리지 않는다
    assert body["status"] == run["status"] == "awaiting_approval"
    assert body["decision"] is None and body["notification"] is None
    listed = app_client.get("/api/v1/analyses").json()
    assert next(r for r in listed if r["id"] == run["id"])["confirmation"] == body["confirmation"]


def test_confirmation_needs_the_current_result_token(app_client):
    run = run_critical(app_client)
    out = app_client.post(
        f"/api/v1/analyses/{run['id']}/confirm", json={"result_token": "0" * 64}
    )
    assert out.status_code == 422 and out.json()["detail"] == "result_token_mismatch"
    assert app_client.get(f"/api/v1/analyses/{run['id']}").json()["confirmation"] is None
    missing = app_client.post(
        "/api/v1/analyses/00000000-0000-0000-0000-000000000000/confirm",
        json={"result_token": "0" * 64},
    )
    assert missing.status_code == 404
