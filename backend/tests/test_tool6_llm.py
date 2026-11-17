from types import SimpleNamespace

from app.tools.tool6_llm import build_facts, draft_with_llm, is_faithful

RESULT = {
    "date": "2026-11-18", "peak_hour": 12, "risk": "CRITICAL", "peak_ratio": 0.73,
    "peak_surplus_mwh": 230.0, "thresholds": {"warning_ratio": 0.40},
}
PLAN = {
    "allocated_mwh": {"bess": 70.0, "vpp": 30.0, "p2x": 30.0, "ev": 40.0},
    "absorption_pct": 73.913, "residual_mwh": 60.0, "hydrogen_kg": 390.0,
}
GOOD = (
    "2026-11-18 12:00 KST에 CRITICAL 위험이 예상됩니다. 피크 잉여전력은 230.00 MWh이며 "
    "흡수율 73.91%를 목표로 BESS 70.00, VPP 30.00, P2X 30.00, EV 40.00 MWh 배분을 권고합니다. "
    "잔여는 60.00 MWh입니다."
)


class FakeClient:
    def __init__(self, text=GOOD, stop="end_turn", error=None):
        self.calls = 0
        self.messages = self
        self._text, self._stop, self._error = text, stop, error

    def create(self, **kwargs):
        self.calls += 1
        assert "api_key" not in kwargs and kwargs["model"] == "m"
        if self._error:
            raise self._error
        return SimpleNamespace(
            stop_reason=self._stop, content=[SimpleNamespace(type="text", text=self._text)]
        )


def run(client=None, key="k"):
    return draft_with_llm(RESULT, PLAN, api_key=key, model="m", client=client)


def test_uses_llm_body_and_code_footer():
    text, source = run(FakeClient())
    assert source == "llm" and GOOD in text
    assert text.startswith("[제주 출력제한 대응 권고]") and "담당자 승인이 필요합니다" in text


def test_no_key_falls_back_to_template_without_call():
    text, source = run(client=None, key=None)
    assert source == "template:no_key" and "위험등급: CRITICAL" in text


def test_invented_number_is_rejected():
    client = FakeClient(GOOD.replace("230.00", "250.00"))
    text, source = run(client)
    assert source == "template:unfaithful" and "230.00 MWh" in text
    assert client.calls == 2  # 한 번 다시 시도한 뒤 대체


def test_missing_key_value_is_rejected():
    assert not is_faithful("CRITICAL 위험입니다. 잉여 230.00 MWh.", build_facts(RESULT, PLAN))


def test_api_error_and_refusal_fall_back():
    assert run(FakeClient(error=RuntimeError("down")))[1] == "template:error:RuntimeError"
    assert run(FakeClient(stop="refusal"))[1] == "template:no_text"
    assert run(FakeClient(text=""))[1] == "template:no_text"


def test_facts_exclude_station_names():
    plan = {**PLAN, "ev_basis": {"top_stations": [{"name": "비밀충전소"}]}}
    assert "비밀충전소" not in str(build_facts(RESULT, plan))


def test_hydrogen_assumption_is_added_by_code():
    body = GOOD + " 수소 생산량은 390.00 kg입니다."
    text, source = run(FakeClient(body))
    assert source == "llm" and "13 kg/MWh 가정값입니다" in text
    again, _ = run(FakeClient(GOOD + " 수소 390.00 kg은 가정입니다."))
    assert again.count("13 kg/MWh") == 0


def test_too_long_body_is_rejected():
    assert run(FakeClient(GOOD + " 추가 설명." * 80))[1] == "template:unfaithful"


def test_retry_recovers_when_second_answer_is_faithful():
    class Flaky(FakeClient):
        def create(self, **kw):
            self._text = GOOD if self.calls else GOOD.replace("230.00", "999.00")
            return super().create(**kw)

    client = Flaky()
    assert run(client)[1] == "llm" and client.calls == 2


def test_units_attached_to_numbers_are_accepted():
    body = GOOD.replace("230.00 MWh", "230.00MWh").replace("60.00 MWh", "60.00MWh")
    assert is_faithful(body, build_facts(RESULT, PLAN))
    assert not is_faithful(body.replace("230.00MWh", "231.00MWh"), build_facts(RESULT, PLAN))
