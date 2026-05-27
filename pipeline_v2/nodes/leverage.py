import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

import anthropic
from langsmith import traceable
from langsmith.wrappers import wrap_anthropic

from pipeline_v2.state import AgentState
from pipeline_v2.lib.cost_tracker import compute_cost, add_cost
from pipeline_v2.lib.decision_logger import log_decision
from pipeline_v2.lib.db_persistence import persist_cost_log

logger = logging.getLogger(__name__)

_OPUS_MODEL = "claude-opus-4-6"


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t[t.index("\n") + 1:] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[: t.rfind("```")]
    return t.strip()


_SKILL_MD_PATH = Path(__file__).parent.parent.parent / "skills" / "candidate-leverage" / "SKILL.md"

def _load_candidate_leverage() -> str:
    try:
        text = _SKILL_MD_PATH.read_text()
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return text.strip()
    except OSError:
        raise RuntimeError(
            f"skills/candidate-leverage/SKILL.md not found at {_SKILL_MD_PATH}. "
            "Complete the setup process before running the pipeline: "
            "follow the instructions in CLAUDE.md or paste the setup prompt from README.md into Claude Code."
        )


CANDIDATE_LEVERAGE = _load_candidate_leverage()


def _call_with_retry(fn: Callable, retries: int = 3, delay: float = 5) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1:
                logger.warning(
                    "API call failed (attempt %d/%d): %s. Retrying in %ss…",
                    attempt + 1, retries, exc, delay,
                )
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _is_founder_data_insufficient(state: AgentState) -> bool:
    current_company = state.get("current_company") or {}
    if not current_company.get("founder"):
        return True
    knowledge_state = state.get("knowledge_state") or {}
    founder_background = knowledge_state.get("founder_background") or {}
    if founder_background.get("status") == "unknown":
        return True
    return False


def _opus_leverage_explore(
    client: anthropic.Anthropic,
    company: dict,
    knowledge_state: dict,
    hiring_signals: list,
) -> tuple[list[dict], int, int]:
    """Call 1: explore three distinct leverage angles. Returns (angles, in_tokens, out_tokens)."""
    company_name = company.get("name", "Unknown")
    founder_name = company.get("founder", "Unknown")
    founder_role = company.get("founder_role", "Founder")

    prompt = (
        f"You are a leverage-matching engine for a job-search outreach pipeline.\n\n"
        f"## Candidate Profile\n{CANDIDATE_LEVERAGE}\n\n"
        f"## Company\nName: {company_name}\nFounder: {founder_name} ({founder_role})\n\n"
        f"## Knowledge State\n{json.dumps(knowledge_state, indent=2)}\n\n"
        f"## Hiring Signals\n{json.dumps(hiring_signals, indent=2)}\n\n"
        f"Explore THREE distinct angles for matching the candidate profile to this company.\n"
        f"Each angle must use a different facet of the candidate's experience.\n"
        f"For each angle, explain: what matched, what didn't match, "
        f"what was present in the company, what was present in the candidate.\n\n"
        f"Return ONLY valid JSON:\n"
        f'{{"angles": ['
        f'{{"angle_name": "...", "relevant_experience": "...", "what_matched": "...", '
        f'"what_didnt_match": "...", "what_was_present_in_company": "...", '
        f'"what_was_present_in_candidate": "..."}},'
        f' ... (3 total)'
        f']}}'
    )

    def _call():
        return client.messages.create(
            model=_OPUS_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

    response = _call_with_retry(_call)
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    raw = _strip_fences(response.content[0].text)

    try:
        parsed = json.loads(raw)
        angles = parsed.get("angles", [])
        if not isinstance(angles, list):
            angles = []
    except json.JSONDecodeError:
        logger.warning("Opus leverage explore returned non-JSON: %s", raw[:200])
        angles = []

    return angles, in_tok, out_tok


def _opus_leverage_select(
    client: anthropic.Anthropic,
    company: dict,
    knowledge_state: dict,
    hiring_signals: list,
    angles: list[dict],
) -> tuple[dict, int, int]:
    """Call 2: select the strongest angle. Returns (result_dict, in_tokens, out_tokens).

    result_dict contains LeverageOutput fields + reasoning fields.
    """
    company_name = company.get("name", "Unknown")
    founder_name = company.get("founder", "Unknown")
    founder_role = company.get("founder_role", "Founder")

    prompt = (
        f"You are a leverage-matching engine. Select the strongest angle for outreach.\n\n"
        f"## Candidate Profile\n{CANDIDATE_LEVERAGE}\n\n"
        f"## Company\nName: {company_name}\nFounder: {founder_name} ({founder_role})\n\n"
        f"## Knowledge State\n{json.dumps(knowledge_state, indent=2)}\n\n"
        f"## Hiring Signals\n{json.dumps(hiring_signals, indent=2)}\n\n"
        f"## Angles Explored\n{json.dumps(angles, indent=2)}\n\n"
        f"Select the strongest angle. Explain your reasoning.\n"
        f"Then produce the final outreach leverage output.\n\n"
        f"Return ONLY valid JSON:\n"
        f'{{"selected_angle_index": 0, '
        f'"relevant_experience": "...", "leverage_statement": "...", '
        f'"opening_question": "...", "confidence": "high|medium|low|none", '
        f'"selection_reasoning": "...", "what_matched": "...", "what_didnt_match": "...", '
        f'"what_was_present_in_company": "...", "what_was_present_in_candidate": "...", '
        f'"confidence_reasoning": "..."}}'
    )

    def _call():
        return client.messages.create(
            model=_OPUS_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

    response = _call_with_retry(_call)
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    raw = _strip_fences(response.content[0].text)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Opus leverage select returned non-JSON: %s", raw[:200])
        parsed = {}

    return parsed, in_tok, out_tok


@traceable(name="Leverage Node")
def leverage_node(state: AgentState) -> dict:
    cost_by_stage: dict = dict(state.get("cost_by_stage") or {})
    daily_cost: float = state.get("daily_cost") or 0.0
    current_company = state.get("current_company") or {}
    company_name = current_company.get("name", "Unknown")
    run_id = state.get("run_id") or ""
    company_id = current_company.get("company_id")

    if _is_founder_data_insufficient(state):
        logger.info("Skipping leverage — insufficient founder data for %s", company_name)
        return {
            "last_completed_node": "leverage",
            "skip_reason": "insufficient_founder_data",
            "leverage_output": {
                "relevant_experience": "",
                "leverage_statement": "",
                "opening_question": "",
                "confidence": "none",
            },
            "leverage_confidence": "none",
            "cost_by_stage": cost_by_stage,
            "daily_cost": daily_cost,
        }

    knowledge_state = state.get("knowledge_state") or {}
    hiring_signals = state.get("hiring_signals_found") or []
    client = wrap_anthropic(anthropic.Anthropic())

    # Call 1: explore angles
    angles, in_tok_1, out_tok_1 = _opus_leverage_explore(client, current_company, knowledge_state, hiring_signals)
    cost_1 = compute_cost(_OPUS_MODEL, in_tok_1, out_tok_1)
    persist_cost_log(
        run_id=state.get("run_id", ""),
        stage="leverage",
        company_id=company_id,
        model=_OPUS_MODEL,
        input_tokens=in_tok_1,
        output_tokens=out_tok_1,
        cost_usd=cost_1,
    )
    cost_by_stage = add_cost(cost_by_stage, "leverage", cost_1)
    daily_cost += cost_1

    log_decision(
        run_id=run_id, company_id=company_id, company_name=company_name,
        node="leverage", decision="explore", confidence="medium",
        reasoning=f"explored {len(angles)} leverage angles",
        next_action="select",
        call_type="leverage_explore",
        model_used=_OPUS_MODEL, input_tokens=in_tok_1, output_tokens=out_tok_1,
        node_specific={"angles_count": len(angles), "angles": angles},
    )

    # Call 2: select strongest angle
    select_result, in_tok_2, out_tok_2 = _opus_leverage_select(
        client, current_company, knowledge_state, hiring_signals, angles
    )
    cost_2 = compute_cost(_OPUS_MODEL, in_tok_2, out_tok_2)
    persist_cost_log(
        run_id=state.get("run_id", ""),
        stage="leverage",
        company_id=company_id,
        model=_OPUS_MODEL,
        input_tokens=in_tok_2,
        output_tokens=out_tok_2,
        cost_usd=cost_2,
    )
    cost_by_stage = add_cost(cost_by_stage, "leverage", cost_2)
    daily_cost += cost_2

    # Extract LeverageOutput fields (schema unchanged)
    leverage_output = {
        "relevant_experience": select_result.get("relevant_experience", ""),
        "leverage_statement": select_result.get("leverage_statement", ""),
        "opening_question": select_result.get("opening_question", ""),
        "confidence": select_result.get("confidence", "none"),
    }

    # Reasoning fields go to log_decision node_specific only (not into AgentState)
    reasoning_fields = {
        "angles_explored": angles,
        "selected_angle_index": select_result.get("selected_angle_index"),
        "selection_reasoning": select_result.get("selection_reasoning", ""),
        "what_matched": select_result.get("what_matched", ""),
        "what_didnt_match": select_result.get("what_didnt_match", ""),
        "what_was_present_in_company": select_result.get("what_was_present_in_company", ""),
        "what_was_present_in_candidate": select_result.get("what_was_present_in_candidate", ""),
        "confidence_reasoning": select_result.get("confidence_reasoning", ""),
    }

    log_decision(
        run_id=run_id, company_id=company_id, company_name=company_name,
        node="leverage", decision="select", confidence=leverage_output["confidence"],
        reasoning=select_result.get("selection_reasoning", ""),
        next_action="drafting",
        call_type="leverage_select",
        model_used=_OPUS_MODEL, input_tokens=in_tok_2, output_tokens=out_tok_2,
        node_specific=reasoning_fields,
    )

    return {
        "last_completed_node": "leverage",
        "skip_reason": "",
        "leverage_output": leverage_output,
        "leverage_confidence": leverage_output["confidence"],
        "cost_by_stage": cost_by_stage,
        "daily_cost": daily_cost,
    }
