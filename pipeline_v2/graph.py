from langgraph.graph import StateGraph, END

from pipeline_v2.state import AgentState
from pipeline_v2.nodes.supervisor import supervisor_node
from pipeline_v2.nodes.sourcing import sourcing_node
from pipeline_v2.nodes.research import research_node
from pipeline_v2.nodes.scoring import scoring_node
from pipeline_v2.nodes.leverage import leverage_node
from pipeline_v2.nodes.drafting import drafting_node


def _route_supervisor(state: AgentState) -> str:
    if state.get("last_completed_node") == "done":
        return END
    decision = state.get("supervisor_decision", "")
    routes = {
        "sourcing":  "sourcing",
        "research":  "research",
        "scoring":   "scoring",
        "leverage":  "leverage",
        "drafting":  "drafting",
    }
    return routes.get(decision, END)


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("sourcing",   sourcing_node)
    builder.add_node("research",   research_node)
    builder.add_node("scoring",    scoring_node)
    builder.add_node("leverage",   leverage_node)
    builder.add_node("drafting",   drafting_node)

    builder.set_entry_point("supervisor")
    builder.add_conditional_edges("supervisor", _route_supervisor)
    builder.add_edge("sourcing",  "supervisor")
    builder.add_edge("research",  "scoring")   # research always goes to scoring
    builder.add_edge("scoring",   "supervisor")
    builder.add_edge("leverage",  "supervisor")
    builder.add_edge("drafting",  "supervisor")
    return builder.compile()
