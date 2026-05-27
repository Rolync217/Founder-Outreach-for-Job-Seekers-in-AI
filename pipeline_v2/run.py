"""Pipeline entrypoint — call run_pipeline(run_type) to execute one full run."""
import uuid
import logging
from datetime import datetime, timezone

from langsmith import traceable

from pipeline_v2.graph import build_graph
from pipeline_v2.state import AgentState

logger = logging.getLogger(__name__)


@traceable(name="JobSearchAuto Pipeline")
def run_pipeline(
    run_type: str = "daily_light",
    candidate_pool: list[dict] | None = None,
) -> dict:
    """Run the full pipeline. Returns the final state dict.

    Args:
        run_type: "daily_light" or "deep_run"
        candidate_pool: optional pre-seeded pool (skips sourcing if provided)
    """
    from pipeline_v2.lib.db_persistence import persist_pipeline_run, complete_pipeline_run, persist_pipeline_stage

    graph = build_graph()

    initial_state: AgentState = {
        "run_id": str(uuid.uuid4()),
        "run_type": run_type,
        "run_date": datetime.now(timezone.utc).date().isoformat(),
        "last_completed_node": "init",
        "daily_target": 0,
        "companies_ready": 0,
        "daily_goal_met": False,
        "candidate_pool": candidate_pool or [],
        "sourcing_iterations": 0,
        "entities_rejected_as_invalid": [],
        "current_company": {},
        "knowledge_state": {},
        "knowledge_iterations": 0,
        "knowledge_confidence": "low",
        "research_retry_count": 0,
        "fetched_sources": [],
        "failed_sources": [],
        "source_attempt_log": [],
        "sourcing_source_attempt_log": [],
        "hiring_tier": None,
        "hiring_tier_reason": "",
        "hiring_signals_found": [],
        "promotion_reason": "",
        "work_alignment": {},
        "leverage_output": {"relevant_experience": "", "leverage_statement": "", "opening_question": "", "confidence": "none"},
        "leverage_confidence": "none",
        "draft_output": [],
        "draft_iterations": 0,
        "draft_retry_count": 0,
        "validation_passed": False,
        "validation_feedback": "",
        "research_search_history": [],
        "opus_synthesis": None,
        "structured_company": {},
        "structured_founders": [],
        "supervisor_decision": "",
        "skip_reason": "",
        "decision_log": [],
        "daily_cost": 0.0,
        "cost_by_stage": {},
    }

    logger.info("Starting pipeline run_id=%s run_type=%s", initial_state["run_id"], run_type)

    persist_pipeline_run(initial_state)

    final_state = graph.invoke(initial_state)

    run_id = initial_state["run_id"]
    pool_size = len(final_state.get("candidate_pool") or [])
    persist_pipeline_stage(run_id, "sourcing", "completed",
        companies_total=pool_size,
        companies_done=pool_size)
    persist_pipeline_stage(run_id, "research", "completed",
        companies_total=pool_size,
        companies_done=final_state.get("companies_ready", 0))
    persist_pipeline_stage(run_id, "scoring", "completed",
        companies_total=pool_size,
        companies_done=final_state.get("companies_ready", 0))
    persist_pipeline_stage(run_id, "drafting", "completed",
        companies_total=pool_size,
        companies_done=len(final_state.get("draft_output") or []))

    complete_pipeline_run(initial_state["run_id"], final_state)

    logger.info(
        "Pipeline complete. companies_ready=%d daily_cost=$%.4f",
        final_state.get("companies_ready", 0),
        final_state.get("daily_cost", 0.0),
    )

    return final_state
