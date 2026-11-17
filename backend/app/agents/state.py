from typing import TypedDict


class AgentState(TypedDict, total=False):
    id: str
    request: dict
    status: str
    refresh_count: int
    weather: list[dict]
    generation: list[dict]
    demand: list[dict]
    sources: dict
    result: dict
    allocation: dict
    draft: str
    decision: dict
    boundary_unresolved: bool
    phase: str
    check_no: int
    intraday: dict
    evaluations: list[dict]
    trace: list[str]
