from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.state import AgentState
from app.domain.schemas import AnalysisRequest, EnergyHour, WeatherHour
from app.tools.tool4_risk import evaluate
from app.tools.tool5_allocation import allocate
from app.tools.tool6_notification import draft_notification


def build_graph(bundle, store, saver, max_refreshes):
    def weather(state):
        rows, source = bundle.weather(
            AnalysisRequest.model_validate(state["request"]), state["refresh_count"]
        )
        return {
            "weather": [r.model_dump(mode="json") for r in rows],
            "sources": {**state["sources"], "weather": source},
            "trace": state["trace"] + ["R2:weather"],
        }

    def prediction(state):
        rows, source = bundle.generation(
            AnalysisRequest.model_validate(state["request"]),
            [WeatherHour.model_validate(r) for r in state["weather"]],
            state["refresh_count"],
        )
        return {
            "generation": [r.model_dump(mode="json") for r in rows],
            "sources": {**state["sources"], "generation": source},
            "trace": state["trace"] + ["T2:generation"],
        }

    def demand(state):
        rows, source = bundle.demand(AnalysisRequest.model_validate(state["request"]))
        return {
            "demand": [r.model_dump(mode="json") for r in rows],
            "sources": {**state["sources"], "demand": source},
            "trace": state["trace"] + ["R3:demand"],
        }

    def risk(state):
        result = evaluate(
            [EnergyHour.model_validate(r) for r in state["generation"]],
            [EnergyHour.model_validate(r) for r in state["demand"]],
            AnalysisRequest.model_validate(state["request"]).date,
        )
        boundary = 190 <= result["peak_surplus_mwh"] <= 200
        return {
            "result": result,
            "boundary_unresolved": boundary and state["refresh_count"] >= max_refreshes,
            "evaluations": state["evaluations"]
            + [
                {
                    "refresh_count": state["refresh_count"],
                    "peak_surplus_mwh": result["peak_surplus_mwh"],
                    "risk": result["risk"],
                    "sources": state["sources"],
                }
            ],
            "trace": state["trace"] + ["R5:risk", "R4:boundary_check"],
        }

    def route(state):
        if 190 <= state["result"]["peak_surplus_mwh"] <= 200:
            if state["refresh_count"] < max_refreshes:
                return "refresh"
        return "normal" if state["result"]["risk"] == "NORMAL" else "allocate"

    def refresh(state):
        return {
            "refresh_count": state["refresh_count"] + 1,
            "trace": state["trace"] + ["R4:refresh"],
        }

    def allocation(state):
        return {
            "allocation": allocate(state["result"]["peak_surplus_mwh"]),
            "trace": state["trace"] + ["R6:allocation"],
        }

    def draft(state):
        return {
            "draft": draft_notification(state["result"], state["allocation"]),
            "status": "awaiting_approval",
            "trace": state["trace"] + ["R7:draft"],
        }

    def approval(state):
        decision = interrupt(
            {"type": "human_approval", "analysis_id": state["id"], "draft": state["draft"]}
        )
        store.record_decision(state["id"], decision, state)
        return {
            "decision": decision,
            "status": "approved" if decision["action"] == "approve" else "rejected",
            "trace": state["trace"] + ["R8:" + decision["action"]],
        }

    def normal(state):
        return {"status": "completed", "trace": state["trace"] + ["NORMAL:complete"]}

    graph = StateGraph(AgentState)
    for name, fn in (
        ("weather", weather),
        ("prediction", prediction),
        ("demand", demand),
        ("risk", risk),
        ("refresh", refresh),
        ("allocate", allocation),
        ("draft", draft),
        ("approval", approval),
        ("normal", normal),
    ):
        graph.add_node(name, fn)
    graph.add_edge(START, "weather")
    graph.add_edge("weather", "prediction")
    graph.add_edge("prediction", "demand")
    graph.add_edge("demand", "risk")
    graph.add_conditional_edges("risk", route, {n: n for n in ("refresh", "normal", "allocate")})
    graph.add_edge("refresh", "weather")
    graph.add_edge("allocate", "draft")
    graph.add_edge("draft", "approval")
    graph.add_edge("approval", END)
    graph.add_edge("normal", END)
    return graph.compile(checkpointer=saver)
