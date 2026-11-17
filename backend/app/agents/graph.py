from datetime import date

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.state import AgentState
from app.domain.rules import is_boundary
from app.domain.schemas import AnalysisRequest, Capacities, EnergyHour, WeatherHour
from app.providers import demo
from app.tools.tool4_risk import evaluate
from app.tools.tool5_allocation import allocate
from app.tools.tool6_llm import draft_with_llm


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
        bundle.log_evaluation(state["id"], "day_ahead", state["refresh_count"], result)
        boundary = is_boundary(result["peak_ratio"])
        return {
            "result": result,
            "boundary_unresolved": boundary and state["refresh_count"] >= max_refreshes,
            "evaluations": state["evaluations"]
            + [
                {
                    "refresh_count": state["refresh_count"],
                    "peak_surplus_mwh": result["peak_surplus_mwh"],
                    "peak_ratio": result["peak_ratio"],
                    "risk": result["risk"],
                    "sources": state["sources"],
                }
            ],
            "trace": state["trace"] + ["R5:risk", "R4:boundary_check"],
        }

    def route(state):
        if is_boundary(state["result"]["peak_ratio"]):
            if state["refresh_count"] < max_refreshes:
                return "refresh"
        return "normal" if state["result"]["risk"] == "NORMAL" else "allocate"

    def intraday_check(state):
        """하루 전이 정상이던 날의 당일 점검: 초단기실황·초단기예보로 다시 판정한다."""
        request = AnalysisRequest.model_validate(state["request"])
        check_no = max(state.get("check_no", 1), 1)
        inputs = None
        if request.mode == "demo":
            generation = demo.intraday_generation(request.date, request.scenario, check_no)
            result = evaluate(generation, demo.demand(request.date), request.date)
            sources = {
                "weather": {"source": "demo", "simulated": True},
                "generation": {"source": "demo_scenario", "simulated": True, "model": "fixture"},
                "demand": {"source": "demo", "simulated": True},
            }
        else:
            out = bundle.intraday_check(request, bundle.now())
            result, inputs = out["result"], out["inputs"]
            sources = {
                "weather": {
                    "source": "kma_ultra_short",
                    "simulated": False,
                    "irradiance": "estimated",
                    "day_ahead_base": inputs["day_ahead_base"],
                },
                "generation": {
                    "source": "prediction",
                    "simulated": False,
                    "model": "xgboost_jeju_total",
                    "validated": False,
                },
                "demand": {
                    "source": "demand_model",
                    "simulated": False,
                    "model": "xgboost_jeju_demand",
                    "validated": False,
                },
            }
        bundle.log_evaluation(state["id"], "intraday", check_no, result, inputs)
        meta = {"check_no": check_no}
        if inputs:
            meta.update(
                checked_at=inputs["checked_at"],
                from_hour=inputs["from_hour"],
                day_ahead_base=inputs["day_ahead_base"],
                hour_sources=inputs["sources"],
            )
        return {
            "result": result,
            "boundary_unresolved": False,
            "sources": {**state["sources"], **sources},
            "intraday": meta,
            "evaluations": state["evaluations"]
            + [
                {
                    "refresh_count": 0,
                    "peak_surplus_mwh": result["peak_surplus_mwh"],
                    "peak_ratio": result["peak_ratio"],
                    "risk": result["risk"],
                    "sources": sources,
                }
            ],
            "trace": state["trace"] + [f"INTRADAY:check{check_no}"],
        }

    def entry(state):
        return "intraday_check" if state["request"].get("phase") == "intraday" else "weather"

    def route_intraday(state):
        return "normal" if state["result"]["risk"] == "NORMAL" else "allocate"

    def refresh(state):
        return {
            "refresh_count": state["refresh_count"] + 1,
            "trace": state["trace"] + ["R4:refresh"],
        }

    def allocation(state):
        result = state["result"]
        ev = bundle.ev_allocation_input(result["peak_hour"], date.fromisoformat(result["date"]))
        plan = allocate(
            result["peak_surplus_mwh"], Capacities(ev=ev["capacity_mwh"]) if ev else None
        )
        if ev:
            # EV 용량만 허브 데이터 기반이다. 나머지 자원은 여전히 가정이다.
            plan["availability_source"] = (
                "jejudatahub_ev_stations+history"
                if ev["basis"] == "history_profile"
                else "jejudatahub_ev_stations+assumptions"
            )
            plan["ev_basis"] = ev
        return {"allocation": plan, "trace": state["trace"] + ["R6:allocation"]}

    def draft(state):
        cfg = bundle.settings
        key = cfg.anthropic_api_key.get_secret_value() if cfg.anthropic_api_key else None
        text, source = draft_with_llm(
            state["result"],
            state["allocation"],
            api_key=key,
            model=cfg.llm_model,
            timeout=cfg.llm_timeout,
        )
        return {
            "draft": text,
            "status": "awaiting_approval",
            "trace": state["trace"] + [f"R7:draft:{source}"],
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
        ("intraday_check", intraday_check),
        ("allocate", allocation),
        ("draft", draft),
        ("approval", approval),
        ("normal", normal),
    ):
        graph.add_node(name, fn)
    graph.add_conditional_edges(
        START, entry, {"weather": "weather", "intraday_check": "intraday_check"}
    )
    graph.add_edge("weather", "prediction")
    graph.add_edge("prediction", "demand")
    graph.add_edge("demand", "risk")
    graph.add_conditional_edges("risk", route, {n: n for n in ("refresh", "normal", "allocate")})
    graph.add_edge("refresh", "weather")
    graph.add_conditional_edges(
        "intraday_check", route_intraday, {"normal": "normal", "allocate": "allocate"}
    )
    graph.add_edge("allocate", "draft")
    graph.add_edge("draft", "approval")
    graph.add_edge("approval", END)
    graph.add_edge("normal", END)
    return graph.compile(checkpointer=saver)
