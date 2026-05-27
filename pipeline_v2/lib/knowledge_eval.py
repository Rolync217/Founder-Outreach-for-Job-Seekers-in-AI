from pipeline_v2.lib.scope_loader import get_dimension_priority, get_critical_dimensions


def empty_knowledge_state() -> dict:
    return {
        d: {
            "status": "unknown",
            "summary": "",
            "source": "",
            "source_url": "",
            "gap_reason": "",
            "confidence": "low",
        }
        for d in get_dimension_priority()
    }


def priority_gap(knowledge_state: dict) -> str | None:
    for dim in get_dimension_priority():
        if knowledge_state.get(dim, {}).get("status") != "sufficient":
            return dim
    return None


def all_sufficient(knowledge_state: dict) -> bool:
    return all(
        knowledge_state.get(d, {}).get("status") == "sufficient"
        for d in get_dimension_priority()
    )


def overall_confidence(knowledge_state: dict) -> str:
    critical = get_critical_dimensions()
    all_dims = get_dimension_priority()
    if all(knowledge_state.get(d, {}).get("status") == "sufficient" for d in all_dims):
        return "high"
    if all(knowledge_state.get(d, {}).get("status") == "sufficient" for d in critical):
        return "medium"
    return "low"
