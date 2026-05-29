"""
pipeline/nodes/scoring.py

Agentic scoring node. LLM assigns qualitative labels (strong/good/weak/missing)
per dimension; scoring_tool.py computes the math (tier, total_score).
Workflow criteria loaded from skills/search_scope.yaml when available.
"""
import json
import logging

import anthropic
from langsmith import traceable
from langsmith.wrappers import wrap_anthropic

from pipeline_v2.state import AgentState
from pipeline_v2.lib.scoring_tool import compute_score, SCORING_TOOL_DEFINITION
from pipeline_v2.lib.scope_loader import get_scoring_config
from pipeline_v2.lib.cost_tracker import compute_cost, add_cost
from pipeline_v2.lib.db_persistence import persist_scoring, persist_cost_log
from pipeline_v2.lib.decision_logger import log_decision
from tools.config_loader import cfg

logger = logging.getLogger(__name__)

_SONNET_MODEL = cfg.models.scoring


def _build_scoring_prompt(state: dict, scoring_cfg: dict) -> str:
    company = state.get("current_company") or {}
    ks = state.get("knowledge_state") or {}
    signals = state.get("hiring_signals_found") or []
    opus = state.get("opus_synthesis") or {}
    sc = state.get("structured_company") or {}

    guidance = scoring_cfg.get("dimension_guidance", {})

    prompt_parts = [
        "You are scoring a company for job search outreach priority.\n\n",
        f"Company: {company.get('name', 'Unknown')}\n\n",
        "## Research Summary\n",
        f"Product: {ks.get('product_understanding', {}).get('summary', 'unknown')}\n",
        f"Work alignment: {ks.get('work_alignment', {}).get('summary', 'unknown')}\n",
        f"Founder background: {ks.get('founder_background', {}).get('summary', 'unknown')}\n",
        f"Company stage: {ks.get('company_stage_and_size', {}).get('summary', 'unknown')}\n",
        f"Has live product: {sc.get('has_live_product')}, Paying customers: {sc.get('has_paid_customers')}\n",
        f"Is agentic AI: {sc.get('is_agentic_ai')}\n",
        f"Traction: {sc.get('traction', 'unknown')}\n",
        f"Funding: {sc.get('funding_round')} {sc.get('funding_amount', '')}\n\n",
        "## Hiring Signals\n",
    ]
    if signals:
        for s in signals:
            prompt_parts.append(f"- {s.get('signal_type')}: {s.get('signal_text', '')[:200]}\n")
    else:
        prompt_parts.append("- None found\n")

    prompt_parts.append("\n## Outreach Angle\n")
    prompt_parts.append(f"{opus.get('outreach_angle', 'None identified')}\n\n")

    if guidance:
        prompt_parts.append("## Scoring Guidance\n")
        for dim, text in guidance.items():
            prompt_parts.append(f"**{dim}:** {text}\n")
        prompt_parts.append("\n")

    prompt_parts.append(
        "Assess each scoring dimension. Then call compute_score with your six labels.\n"
        "After the tool returns, provide one-sentence reasoning for each dimension.\n"
        "Your reasoning MUST reference specific evidence from the research above."
    )
    return "".join(prompt_parts)


@traceable(name="Scoring Node")
def _call_scoring_agent(state: dict) -> dict:
    """
    Run the scoring LLM with tool use. Returns a dict with all 6 dimension scores,
    6 reasoning strings, total_score, and tier.
    """
    scoring_cfg = get_scoring_config()
    client = wrap_anthropic(anthropic.Anthropic())
    prompt = _build_scoring_prompt(state, scoring_cfg)

    messages = [{"role": "user", "content": prompt}]
    scores: dict = {}
    tool_result: dict = {}
    reasoning: dict = {}
    total_in_tok: int = 0
    total_out_tok: int = 0

    for _ in range(3):
        resp = client.messages.create(
            model=_SONNET_MODEL,
            max_tokens=1024,
            tools=[SCORING_TOOL_DEFINITION],
            messages=messages,
        )
        total_in_tok += resp.usage.input_tokens
        total_out_tok += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})

        tool_use_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "tool_use"),
            None,
        )

        if tool_use_block:
            tool_input = tool_use_block.input
            tool_result = compute_score(**tool_input)
            scores = {**tool_input, **tool_result}

            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_block.id,
                    "content": json.dumps(tool_result),
                }],
            })
            continue

        if resp.content:
            text = getattr(resp.content[0], "text", "")
            for dim in ("hiring", "founder", "product", "traction", "recency", "alignment"):
                for line in text.split("\n"):
                    line_lower = line.lower()
                    if dim in line_lower and (":" in line_lower or "-" in line_lower):
                        reasoning[f"reasoning_{dim}"] = line.strip().split(":", 1)[-1].strip()[:500]
                        break
                if f"reasoning_{dim}" not in reasoning:
                    reasoning[f"reasoning_{dim}"] = ""
        break

    if not scores:
        scores = {
            "score_hiring": "missing", "score_founder": "missing",
            "score_product": "missing", "score_traction": "missing",
            "score_recency": "missing", "score_alignment": "missing",
            **compute_score("missing", "missing", "missing", "missing", "missing", "missing"),
        }

    return {**scores, **reasoning, "_in_tok": total_in_tok, "_out_tok": total_out_tok}


def scoring_node(state: AgentState) -> dict:
    """LangGraph node — scores the current company and persists to scoring_v2."""
    company = state.get("current_company") or {}
    company_id = company.get("company_id")
    company_name = company.get("name", "unknown")

    if not company_id:
        logger.warning("scoring_node: no company_id in current_company — skipping")
        return {"last_completed_node": "scoring"}

    try:
        result = _call_scoring_agent(state)
    except Exception as e:
        logger.warning("scoring_node failed for %s: %s", company_name, e)
        return {
            "last_completed_node": "scoring",
            "hiring_tier": state.get("hiring_tier"),
            "hiring_tier_reason": state.get("hiring_tier_reason", ""),
        }

    tier        = result.get("tier") or state.get("hiring_tier")
    tier_reason = result.get("reasoning_hiring", "")

    in_tok  = result.pop("_in_tok", 1200)
    out_tok = result.pop("_out_tok", 400)
    cost = compute_cost(_SONNET_MODEL, in_tok, out_tok)
    persist_cost_log(
        run_id=state.get("run_id", ""),
        stage="scoring",
        company_id=company_id,
        model=_SONNET_MODEL,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
    )
    cost_by_stage = add_cost(dict(state.get("cost_by_stage") or {}), "scoring", cost)

    persist_scoring(company_id, {
        **dict(state),
        "hiring_tier": tier,
        "hiring_tier_reason": tier_reason,
        "score_hiring":    result.get("score_hiring", "missing"),
        "score_founder":   result.get("score_founder", "missing"),
        "score_product":   result.get("score_product", "missing"),
        "score_traction":  result.get("score_traction", "missing"),
        "score_recency":   result.get("score_recency", "missing"),
        "score_alignment": result.get("score_alignment", "missing"),
        "total_score":     result.get("total_score", "weak"),
        "reasoning_hiring":    result.get("reasoning_hiring", ""),
        "reasoning_founder":   result.get("reasoning_founder", ""),
        "reasoning_product":   result.get("reasoning_product", ""),
        "reasoning_traction":  result.get("reasoning_traction", ""),
        "reasoning_recency":   result.get("reasoning_recency", ""),
        "reasoning_alignment": result.get("reasoning_alignment", ""),
    })

    log_decision(
        run_id=state.get("run_id", ""),
        company_id=company_id,
        company_name=company_name,
        node="scoring",
        decision=f"tier_{tier}",
        confidence="high" if result.get("score_hiring") in ("strong", "good") else "medium",
        reasoning=tier_reason,
        next_action="leverage" if tier in (1, 2) else "skip",
        call_type="scoring",
        model_used=_SONNET_MODEL,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )

    return {
        "last_completed_node": "scoring",
        "hiring_tier": tier,
        "hiring_tier_reason": tier_reason,
        "daily_cost": state.get("daily_cost", 0.0) + cost,
        "cost_by_stage": cost_by_stage,
    }
