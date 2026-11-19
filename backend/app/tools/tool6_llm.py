"""R7 통보문 초안을 LLM(Claude)이 문장으로 풀어 쓰게 한다.

역할 분담
- 위험등급·잉여전력·배분량 같은 **수치는 앞 단계가 계산한 값**이다. LLM은 그 값을 문장으로 옮기기만 한다.
- LLM 본문의 숫자는 입력으로 준 숫자와 대조한다. 입력에 없는 숫자가 있거나 핵심 값이 빠지면 LLM 본문을 버린다.
- 키가 없거나, 호출이 실패하거나, 검증에 실패하면 기존 템플릿 초안(draft_notification)을 그대로 쓴다.
- 충전소 이름 같은 허브 원본 정보는 LLM에 보내지 않는다. 초안 끝의 충전소·한계 문구는 코드가 붙인다.
"""

import re

from app.tools.tool6_notification import draft_notification, footer_lines

SYSTEM_PROMPT = (
    "당신은 제주도청 에너지 담당 부서 행정담당자를 돕는 보조자다. 아래 JSON 사실만 근거로, 출력제한 대응 권고 "
    "통보문 본문을 한국어로 2~3문장, 문자 알림에 맞게 짧고 간결한 평서체로 쓴다.\n"
    "규칙: (1) JSON에 없는 숫자나 사실을 만들지 않는다. (2) 숫자는 JSON의 문자열을 그대로 옮긴다. "
    "(3) 위험등급은 JSON의 영문 값을 그대로 쓴다. (4) 설비 제어 명령이나 확정 표현을 쓰지 않고 "
    "제안 형태로 쓴다. (5) 제목·목록·머리말 없이 본문 문장만 쓴다. (6) 수소 환산량은 가정값이므로 언급할 때 hydrogen_assumption을 함께 쓴다. "
    "(7) 수신 대상은 문자 발송에 동의한 시민과 관내 충전소 등 운영자·재생에너지 사업자이므로, 전문 용어를 줄이고 "
    "두 대상 모두 이해할 수 있게 쓴다. (8) 입력에 previous_body가 있으면 그 문안과 다른 표현·문장 구성으로 새로 쓰되 사실은 같게 한다."
)

MAX_ATTEMPTS = 2
MAX_BODY_CHARS = 400  # 문자 알림용. 길면 템플릿으로 대체한다.
HYDROGEN_NOTE = "수소 환산은 13 kg/MWh 가정값입니다."
_NUMBER = re.compile(
    r"(?<![A-Za-z\d.])\d+(?:\.\d+)?"
)  # P2X 속 숫자 제외. 230.00MWh처럼 단위가 붙어도 통째로 잡는다


def build_facts(result: dict, allocation: dict) -> dict:
    """LLM에 줄 사실. 숫자는 최종 문장에 쓸 모양의 문자열로 미리 만들어 둔다."""
    return {
        "date": str(result["date"]),
        "peak_hour_kst": f"{result['peak_hour']:02d}:00",
        "risk": str(result["risk"]),
        "peak_ratio": f"{result['peak_ratio']:.0%}",
        "warning_ratio": f"{result['thresholds']['warning_ratio']:.0%}",
        "peak_surplus_mwh": f"{result['peak_surplus_mwh']:.2f}",
        "allocated_mwh": {k: f"{v:.2f}" for k, v in allocation["allocated_mwh"].items()},
        "absorption_pct": f"{allocation['absorption_pct']:.2f}",
        "residual_mwh": f"{allocation['residual_mwh']:.2f}",
        "hydrogen_kg": f"{allocation['hydrogen_kg']:.2f}",
        "hydrogen_assumption": "13 kg/MWh 가정",
    }


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def _flatten(value) -> list[str]:
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten(v)]
    return [str(value)]


def is_faithful(body: str, facts: dict) -> bool:
    """본문의 숫자가 모두 사실에 있고, 핵심 값(등급·잉여·흡수율)이 들어 있는지."""
    if len(body) > MAX_BODY_CHARS:
        return False
    allowed = _numbers(" ".join(_flatten(facts)))
    if not _numbers(body) <= allowed:
        return False
    required = (facts["risk"], facts["peak_surplus_mwh"], facts["absorption_pct"])
    return all(item in body for item in required)


def _call_claude(
    client, model: str, facts: dict, timeout: float, previous: str | None = None
) -> str | None:
    import json

    payload = {**facts, "previous_body": previous} if previous else facts
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        timeout=timeout,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    if response.stop_reason != "end_turn":  # refusal, max_tokens 등은 쓰지 않는다
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


def _previous_body(draft: str | None) -> str | None:
    """이전 초안에서 머리줄과 꼬리 문구를 뺀 본문(새 문안을 다르게 쓰게 하는 용도)."""
    if not draft:
        return None
    lines = draft.split(chr(10))
    return " ".join(lines[1:-1] if len(lines) > 2 else lines).strip()[:600] or None


def make_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key, max_retries=1)


def draft_with_llm(
    result: dict,
    allocation: dict,
    *,
    api_key: str | None,
    model: str,
    timeout: float = 30.0,
    client=None,
    previous: str | None = None,
) -> tuple[str, str]:
    """(초안, 출처). 출처는 'llm' 또는 'template'(+이유). previous가 있으면 그와 다른 문안을 요청한다."""
    template = draft_notification(result, allocation)
    if client is None:
        if not api_key:
            return template, "template:no_key"
        try:
            client = make_client(api_key)
        except ImportError:
            return template, "template:sdk_missing"
    facts = build_facts(result, allocation)
    body = None
    # 모델 출력은 호출마다 달라 검증에서 떨어지면 한 번 더 받는다.
    for _ in range(MAX_ATTEMPTS):
        try:
            body = _call_claude(client, model, facts, timeout, _previous_body(previous))
        except (
            Exception
        ) as exc:  # 네트워크·인증·한도 오류. 초안 작성 실패가 분석을 멈추게 하지 않는다.
            return template, f"template:error:{type(exc).__name__}"
        if body is None:
            return template, "template:no_text"
        if is_faithful(body, facts):
            break
        body = None
    if body is None:
        return template, "template:unfaithful"
    head = f"[제주 출력제한 대응 권고] {result['date']} {result['peak_hour']:02d}:00 KST\n"
    if "수소" in body and "가정" not in body:  # 환산이 가정임을 코드가 보장한다
        body += " " + HYDROGEN_NOTE
    return head + body + "\n" + footer_lines(allocation), "llm"
