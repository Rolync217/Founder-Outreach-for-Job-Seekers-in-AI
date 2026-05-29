"""pipeline/nodes/supervisor.py

Supervisor node — hub of the pipeline.

Routing logic is 100% pure Python (no LLM).
Opus is called for:
  1. Per-company quality eval after research completes.
  2. End-of-run summary when the pipeline finishes.
"""

import json
import time
import logging
from typing import Any, Callable

import anthropic
from langsmith import traceable
from langsmith.wrappers import wrap_anthropic

from pipeline_v2.state import AgentState
from pipeline_v2.lib.cost_tracker import compute_cost, is_over_limit, add_cost
from pipeline_v2.lib.scope_loader import get_daily_target
from pipeline_v2.lib.decision_logger import log_decision
from tools.config_loader import cfg

logger = logging.getLogger(__name__)

_SUPERVISOR_MODEL = cfg.models.supervisor


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t[t.index("\n") + 1:] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[: t.rfind("```")]
    return t.strip()


# Fields that are per-company and must be cleared when the supervisor picks a
# new company to research. Spread this into every return dict that sets a new
# current_company so that stale values from the previous company cannot bleed.
_PER_COMPANY_RESET = {
    "knowledge_state": {},
    "knowledge_iterations": 0,
    "knowledge_confidence": "low",
    "hiring_tier": None,
    "hiring_tier_reason": "",
    "hiring_signals_found": [],
    "fetched_sources": [],
    "failed_sources": [],
    "source_attempt_log": [],
    "skip_reason": "",
    "leverage_output": {"relevant_experience": "", "leverage_statement": "", "opening_question": "", "confidence": "none"},
    "leverage_confidence": "none",
    "draft_output": [],
    "draft_iterations": 0,
    "validation_passed": False,
    "validation_feedback": "",
    "research_search_history": [],
    "opus_synthesis": None,
    "research_retry_count": 0,
    "draft_retry_count": 0,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_with_retry(fn: Callable, retries: int = 3, delay: float = 5) -> Any:
    """Call *fn* up to *retries* times with *delay* seconds between attempts.
    On final failure, re-raise the last exception.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1:
                logger.warning(
                    "Opus call failed (attempt %d/%d): %s. Retrying in %ss…",
                    attempt + 1, retries, exc, delay,
                )
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _pop_next_company(candidate_pool: list[dict]) -> tuple[dict, list[dict]]:
    """Pop the first company from the pool, return (company, remaining_pool)."""
    pool = candidate_pool[:]
    company = pool.pop(0)
    return company, pool


# ---------------------------------------------------------------------------
# Opus helpers
# ---------------------------------------------------------------------------

def _opus_quality_eval(
    client: anthropic.Anthropic,
    state: AgentState,
) -> tuple[dict, float, int, int]:
    """Call Opus to validate research quality for the current company.

    Returns:
        (result_dict, cost_usd, input_tokens, output_tokens)
        result_dict keys: quality_ok (bool), quality_notes (str),
            decision_reasoning (str), what_passed (str),
            what_failed (str), what_was_ambiguous (str)
    """
    company_name = (state.get("current_company") or {}).get("name", "Unknown")
    knowledge_state = state.get("knowledge_state", {})
    hiring_tier = state.get("hiring_tier")
    hiring_tier_reason = state.get("hiring_tier_reason", "")
    hiring_signals = state.get("hiring_signals_found", [])

    prompt = (
        f"You are a quality-control evaluator for a job-search research pipeline.\n\n"
        f"Company: {company_name}\n"
        f"Hiring tier: {hiring_tier} — {hiring_tier_reason}\n"
        f"Hiring signals found: {json.dumps(hiring_signals, indent=2)}\n\n"
        f"Knowledge state (5 dimensions):\n"
        f"{json.dumps(knowledge_state, indent=2)}\n\n"
        f"Evaluate whether research quality is sufficient to proceed with outreach drafting.\n"
        f"Consider: are critical dimensions (product_understanding, work_alignment) well-sourced?\n"
        f"Is the tier assignment justified by the signals? Are there gaps that would make "
        f"outreach embarrassing or incorrect?\n\n"
        f"Return ONLY valid JSON:\n"
        f'{{"quality_ok": true, "quality_notes": "...", '
        f'"decision_reasoning": "...", '
        f'"what_passed": "...", '
        f'"what_failed": "...", '
        f'"what_was_ambiguous": "..."}}'
    )

    def _call():
        return client.messages.create(
            model=_SUPERVISOR_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

    response = _call_with_retry(_call)
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    cost = compute_cost(_SUPERVISOR_MODEL, in_tok, out_tok)

    raw_text = _strip_fences(response.content[0].text)
    try:
        result = json.loads(raw_text)
        result.setdefault("decision_reasoning", "")
        result.setdefault("what_passed", "")
        result.setdefault("what_failed", "")
        result.setdefault("what_was_ambiguous", "")
    except json.JSONDecodeError:
        logger.warning(
            "Opus quality eval returned non-JSON — defaulting to fail-safe (quality_ok=False): %s",
            raw_text,
        )
        result = {
            "quality_ok": False,
            "quality_notes": f"parse_error: {raw_text[:200]}",
            "decision_reasoning": "",
            "what_passed": "",
            "what_failed": "",
            "what_was_ambiguous": "",
        }

    return result, cost, in_tok, out_tok


def _opus_end_of_run_summary(
    client: anthropic.Anthropic,
    state: AgentState,
) -> tuple[str, float]:
    """Call Opus once at the end of a run for a plain-text summary.

    Returns:
        (summary_text, cost_usd)
    """
    prompt = (
        f"Summarize this job-search pipeline run.\n\n"
        f"Run ID: {state.get('run_id', 'unknown')}\n"
        f"Run type: {state.get('run_type', 'unknown')}\n"
        f"Companies drafted / ready: {state.get('companies_ready', 0)}\n"
        f"Daily target: {state.get('daily_target', 0)}\n"
        f"Remaining candidate pool size: {len(state.get('candidate_pool', []))}\n"
        f"Cost breakdown: {json.dumps(state.get('cost_by_stage', {}), indent=2)}\n"
        f"Total daily cost: ${state.get('daily_cost', 0.0):.4f}\n\n"
        f"Provide a concise plain-text summary (2–4 sentences)."
    )

    def _call():
        return client.messages.create(
            model=_SUPERVISOR_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

    response = _call_with_retry(_call)
    cost = compute_cost(_SUPERVISOR_MODEL, response.usage.input_tokens, response.usage.output_tokens)
    summary = response.content[0].text.strip()
    return summary, cost


# ---------------------------------------------------------------------------
# Internal routing helpers
# ---------------------------------------------------------------------------

def _pick_next_company_or_source(
    candidate_pool: list[dict],
) -> tuple[str, dict | None, list[dict]]:
    """Decide: go to research (pop company) or go to sourcing (pool empty).

    Returns:
        (decision, company_or_none, updated_pool)
    """
    if candidate_pool:
        company, remaining = _pop_next_company(candidate_pool)
        return "research", company, remaining
    return "sourcing", None, []


def _finalize_run(
    client: anthropic.Anthropic,
    state: AgentState,
    current_cost_by_stage: dict,
    current_daily_cost: float,
) -> dict:
    """Call Opus end-of-run summary and build the terminal state update.

    IMPORTANT: callers MUST pass the current (updated) cost_by_stage and daily_cost,
    not stale values from `state` — costs may have changed since state was last written.
    """
    # Build a temporary state view with the latest cost info for the summary
    state_view = dict(state)
    state_view["cost_by_stage"] = current_cost_by_stage
    state_view["daily_cost"] = current_daily_cost

    summary, summary_cost = _opus_end_of_run_summary(client, state_view)  # type: ignore[arg-type]

    final_cost_by_stage = add_cost(current_cost_by_stage, "supervisor", summary_cost)
    final_daily_cost = current_daily_cost + summary_cost

    logger.info("Pipeline run complete. Summary: %s", summary)

    return {
        "last_completed_node": "done",
        "supervisor_decision": summary,
        "cost_by_stage": final_cost_by_stage,
        "daily_cost": final_daily_cost,
    }


# ---------------------------------------------------------------------------
# Main supervisor node
# ---------------------------------------------------------------------------

@traceable(name="Supervisor Node")
def supervisor_node(state: AgentState) -> dict:
    """Supervisor node — pure Python routing, Opus for quality/summary only.

    Returns a dict of state UPDATES (LangGraph merges these).
    """
    cost_by_stage: dict[str, float] = dict(state.get("cost_by_stage") or {})
    daily_cost: float = state.get("daily_cost") or 0.0
    daily_target: int = get_daily_target(state.get("run_type") or "daily_light")
    companies_ready: int = state.get("companies_ready") or 0
    candidate_pool: list[dict] = list(state.get("candidate_pool") or [])
    last_completed_node: str = state.get("last_completed_node") or ""

    logger.info(
        "Supervisor called. last_completed_node=%s companies_ready=%d pool_size=%d cost=$%.4f",
        last_completed_node, companies_ready, len(candidate_pool), daily_cost,
    )

    # ------------------------------------------------------------------
    # Branch: "" or "init"
    # ------------------------------------------------------------------
    if last_completed_node in ("", "init"):
        if candidate_pool:
            company, remaining = _pop_next_company(candidate_pool)
            return {
                **_PER_COMPANY_RESET,
                "last_completed_node": "supervisor",
                "supervisor_decision": "research",
                "current_company": company,
                "candidate_pool": remaining,
            }
        # No pool — go source companies first
        return {
            "last_completed_node": "supervisor",
            "supervisor_decision": "sourcing",
        }

    # ------------------------------------------------------------------
    # Branch: after sourcing
    # ------------------------------------------------------------------
    if last_completed_node == "sourcing":
        if not candidate_pool:
            client = wrap_anthropic(anthropic.Anthropic())
            done = _finalize_run(client, state, cost_by_stage, daily_cost)
            return done
        company, remaining = _pop_next_company(candidate_pool)
        return {
            **_PER_COMPANY_RESET,
            "last_completed_node": "supervisor",
            "supervisor_decision": "research",
            "current_company": company,
            "candidate_pool": remaining,
        }

    # ------------------------------------------------------------------
    # Graceful fallback: if scoring node was bypassed (re-runs, test scenarios)
    # ------------------------------------------------------------------
    if last_completed_node == "research":
        return {
            "last_completed_node": "supervisor",
            "supervisor_decision": "scoring",
        }

    # ------------------------------------------------------------------
    # Branch: after scoring
    # ------------------------------------------------------------------
    if last_completed_node == "scoring":
        # --- Opus per-company quality eval (always run) ---
        client = wrap_anthropic(anthropic.Anthropic())
        quality_result, quality_cost, q_in_tok, q_out_tok = _opus_quality_eval(client, state)
        cost_by_stage = add_cost(cost_by_stage, "supervisor", quality_cost)
        daily_cost += quality_cost

        hiring_tier: int | None = state.get("hiring_tier")
        current_company_for_log: dict = state.get("current_company") or {}

        log_decision(
            run_id=state.get("run_id") or "",
            company_id=current_company_for_log.get("company_id"),
            company_name=current_company_for_log.get("name", ""),
            node="supervisor",
            decision="quality_eval",
            confidence="high" if quality_result.get("quality_ok") else "low",
            reasoning=quality_result.get("quality_notes", ""),
            next_action="leverage" if quality_result.get("quality_ok") else "skip",
            call_type="supervisor_eval",
            model_used=_SUPERVISOR_MODEL,
            input_tokens=q_in_tok,
            output_tokens=q_out_tok,
            node_specific={
                "decision_reasoning": quality_result.get("decision_reasoning", ""),
                "what_passed": quality_result.get("what_passed", ""),
                "what_failed": quality_result.get("what_failed", ""),
                "what_was_ambiguous": quality_result.get("what_was_ambiguous", ""),
                "hiring_tier": hiring_tier,
            },
        )
        current_company: dict = state.get("current_company") or {}

        # Apply tier downgrade if quality eval says so and tier is 1 or 2
        if not quality_result.get("quality_ok", False) and hiring_tier in (1, 2):
            hiring_tier = hiring_tier + 1  # type: ignore[operator]
            logger.info(
                "Quality eval failed — downgrading tier to %d. Notes: %s",
                hiring_tier, quality_result.get("quality_notes", ""),
            )
            if "tier" in current_company:
                current_company = dict(current_company)
                current_company["tier"] = hiring_tier
        elif not quality_result.get("quality_ok", False) and hiring_tier in (3, 4):
            logger.warning(
                "Quality eval failed for %s but tier %d cannot be downgraded further. Notes: %s",
                current_company.get("name"), hiring_tier, quality_result.get("quality_notes", ""),
            )

        knowledge_confidence: str = state.get("knowledge_confidence") or "low"

        # --- Route ---
        if hiring_tier in (1, 2) and knowledge_confidence in ("high", "medium"):
            return {
                "last_completed_node": "supervisor",
                "supervisor_decision": "leverage",
                "hiring_tier": hiring_tier,
                "current_company": current_company,
                "cost_by_stage": cost_by_stage,
                "daily_cost": daily_cost,
            }

        if hiring_tier == 3:
            # Watchlist — skip leverage+drafting
            logger.info("Tier 3 (watchlist) — skipping leverage+drafting for %s", current_company.get("name"))
        elif hiring_tier == 4:
            # Not active — skip entirely
            logger.info("Tier 4 (not active) — skipping %s", current_company.get("name"))
        else:
            # Tier 1/2 but confidence too low or no founder — treat as skip
            logger.info(
                "Skipping company %s: tier=%s confidence=%s",
                current_company.get("name"), hiring_tier, knowledge_confidence,
            )

        # Check cost cap before picking next
        if is_over_limit(daily_cost):
            done = _finalize_run(client, state, cost_by_stage, daily_cost)
            return done

        # Pick next company or go to sourcing
        decision, company, remaining_pool = _pick_next_company_or_source(candidate_pool)

        if decision == "sourcing":
            done = _finalize_run(client, state, cost_by_stage, daily_cost)
            return done

        base_update = {
            **_PER_COMPANY_RESET,
            "last_completed_node": "supervisor",
            "supervisor_decision": decision,
            # hiring_tier intentionally omitted — _PER_COMPANY_RESET resets it to None
            "cost_by_stage": cost_by_stage,
            "daily_cost": daily_cost,
            "candidate_pool": remaining_pool,
        }
        if company is not None:
            base_update["current_company"] = company
        return base_update

    # ------------------------------------------------------------------
    # Branch: after leverage
    # ------------------------------------------------------------------
    if last_completed_node == "leverage":
        skip_reason: str = state.get("skip_reason") or ""
        if skip_reason == "insufficient_founder_data":
            logger.info("Leverage skipped due to insufficient founder data. Picking next company.")
            decision, company, remaining_pool = _pick_next_company_or_source(candidate_pool)

            base_update = {
                **_PER_COMPANY_RESET,
                "last_completed_node": "supervisor",
                "supervisor_decision": decision,
                "candidate_pool": remaining_pool,
                "cost_by_stage": cost_by_stage,
                "daily_cost": daily_cost,
            }
            if company is not None:
                base_update["current_company"] = company
            return base_update

        # Founder present — proceed to drafting
        return {
            "last_completed_node": "supervisor",
            "supervisor_decision": "drafting",
            "cost_by_stage": cost_by_stage,
            "daily_cost": daily_cost,
        }

    # ------------------------------------------------------------------
    # Branch: after drafting
    # ------------------------------------------------------------------
    if last_completed_node == "drafting":
        companies_ready += 1
        daily_goal_met: bool = companies_ready >= daily_target

        # Check termination conditions
        if daily_goal_met or is_over_limit(daily_cost):
            # Update state before finalizing for accurate summary
            client = wrap_anthropic(anthropic.Anthropic())
            state_copy = dict(state)
            state_copy["companies_ready"] = companies_ready
            state_copy["daily_goal_met"] = daily_goal_met
            done = _finalize_run(client, state_copy, cost_by_stage, daily_cost)
            done["companies_ready"] = companies_ready
            done["daily_goal_met"] = daily_goal_met
            return done

        # Pick next company or go back to sourcing
        decision, company, remaining_pool = _pick_next_company_or_source(candidate_pool)

        base_update = {
            **_PER_COMPANY_RESET,
            "last_completed_node": "supervisor",
            "supervisor_decision": decision,
            "companies_ready": companies_ready,
            "daily_goal_met": daily_goal_met,
            "candidate_pool": remaining_pool,
            "cost_by_stage": cost_by_stage,
            "daily_cost": daily_cost,
        }
        if company is not None:
            base_update["current_company"] = company
        return base_update

    # ------------------------------------------------------------------
    # Unknown last_completed_node — log and route to sourcing as safe default
    # ------------------------------------------------------------------
    logger.warning("Unknown last_completed_node=%r — defaulting to sourcing", last_completed_node)
    return {
        "last_completed_node": "supervisor",
        "supervisor_decision": "sourcing",
        "cost_by_stage": cost_by_stage,
        "daily_cost": daily_cost,
    }
