"""pipeline/nodes/research.py

Research node — goal-oriented Sonnet agent with Opus advisor checkpoints.

Sonnet makes per-iteration source selection, query generation, and knowledge
evaluation decisions. Opus fires every N iterations (or on stuck signal) as
an advisor — redirecting (Option A) or synthesizing (Option B). Python
enforces only hard limits: cost cap, max iterations, consecutive fetch
failure threshold.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

import anthropic
from langsmith import traceable
from langsmith.wrappers import wrap_anthropic

from pipeline_v2.state import AgentState
from pipeline_v2.lib.cost_tracker import compute_cost, add_cost, is_over_limit
from pipeline_v2.lib.knowledge_eval import empty_knowledge_state, overall_confidence
from pipeline_v2.lib.scope_loader import (
    get_max_iterations,
    get_no_progress_threshold,
    get_opus_checkpoint_interval,
    get_light_source_categories,
    get_tier_signals,
    get_cost_cap,
)
from pipeline_v2.lib.source_loader import load_sources
from pipeline_v2.lib.decision_logger import log_decision
from tools.config_loader import cfg

_USER_NAME = cfg.get("user_profile", {}).get("name", "the candidate")
_USER_BACKGROUND = cfg.get("user_profile", {}).get("background", "a software engineer")
from pipeline_v2.lib.db_persistence import persist_company, persist_research, persist_cost_log, persist_source

logger = logging.getLogger(__name__)

_SONNET_MODEL = cfg.models.research
_OPUS_MODEL = cfg.models.research_synthesis


def _strip_fences(text: str) -> str:
    """Strip markdown code fences (```json ... ``` or ``` ... ```) from model output."""
    t = text.strip()
    if t.startswith("```"):
        t = t[t.index("\n") + 1:] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[: t.rfind("```")]
    return t.strip()


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _first_n_sentences(text: str, n: int) -> str:
    if not text:
        return ""
    flat = " ".join(text.split())
    parts: list[str] = []
    rest = flat
    for _ in range(n):
        end = rest.find(". ")
        if end == -1:
            parts.append(rest.strip())
            break
        parts.append(rest[: end + 1].strip())
        rest = rest[end + 2:]
    return " ".join(parts)


_EXECUTION_TOOLS_SECTION = (
    "EXECUTION TOOLS\n\n"
    "web_search (Tavily):\n"
    "  Used for ALL sources except yc_directory.\n"
    "  Searches the public web using your query string. Returns top 10 results.\n"
    "  The source name does NOT change what gets searched — your query determines\n"
    "  everything.\n"
    "  Query tips per source:\n"
    '    founder_posts: include "linkedin.com" or "twitter.com" and\n'
    '      "founder" or "CEO" or "CTO" and "hiring"\n'
    '    community_hiring_platforms: include "Hacker News hiring" or\n'
    '      "YC Work at a Startup" or specific community names\n'
    '    vc_portfolio_pages: include the VC firm name and "portfolio"\n'
    '      e.g. "a16z portfolio AI agent startup 2025"\n'
    '    funding_news: include "raised" or "seed round" or "Series A"\n'
    "      with relevant domain keywords\n"
    "    All others: be as specific as possible — generic queries return noise\n\n"
    "yc_directory_scraper:\n"
    "  Used ONLY for yc_directory.\n"
    "  Scrapes YC company directory with Hiring filter. Returns structured\n"
    "  company cards. No query string needed — Python handles navigation.\n\n"
    "When you choose a source you are choosing a query strategy, not a different\n"
    "data pipeline. Write your query as if you are a skilled researcher who knows\n"
    "exactly what search terms will surface the right content on the open web.\n"
)


def _call_with_retry(fn: Callable, retries: int = 3, delay: float = 5) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1:
                logger.warning(
                    "API call failed (attempt %d/%d): %s. Retrying in %ss...",
                    attempt + 1, retries, exc, delay,
                )
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Eligibility and source lookup
# ---------------------------------------------------------------------------

def _is_eligible_for_run_type(source: dict, run_type: str, light_categories: list[str]) -> bool:
    """Return True if this source may be used in the given run_type.

    outside_curated stubs are always eligible — they represent agent-chosen
    sources outside the curated list and are already committed to.
    """
    if source.get("source_category") == "outside_curated":
        return True
    if run_type == "deep_run":
        return True
    return source.get("source_category") in light_categories


def _find_source_by_name(sources: list[dict], name: str) -> dict:
    """Return the source dict matching name, or a minimal outside_curated stub."""
    for s in sources:
        if s.get("source_name") == name:
            return s
    return {"source_name": name, "source_category": "outside_curated", "cost_tier": "medium"}


def _build_research_sources_detail(
    all_sources: list[dict],
    fetched_sources_set: set[str],
    run_type: str,
    light_categories: list[str],
) -> str:
    """Build a per-request source detail block showing all sources with fetched/eligible markers."""
    lines: list[str] = []
    for s in all_sources:
        name = s.get("source_name", "")
        cost = s.get("cost_tier", "medium")
        cw = s.get("confidence_weight", "low")
        dims = ", ".join(s.get("signal_types_supported") or [])
        fetched = "YES" if name in fetched_sources_set else "no"
        eligible = _is_eligible_for_run_type(s, run_type, light_categories)
        eligible_str = "YES" if eligible else f"no  \u2190 not available in {run_type}; only used in deep_run"
        when_to_use = _first_n_sentences(s.get("when_to_use", ""), 2)
        when_not_to_use = _first_n_sentences(s.get("when_not_to_use", ""), 1)
        failures_raw = s.get("common_failure_modes") or []
        failure_names = ", ".join(str(f).split("#")[0].strip() for f in failures_raw)
        lines.append(f"[{name}]")
        lines.append(f"  cost={cost} | confidence_weight={cw}")
        lines.append(f"  dims={dims}")
        lines.append(f"  already_fetched: {fetched}")
        lines.append(f"  run_type_eligible: {eligible_str}")
        if when_to_use:
            lines.append(f"  when_to_use: {when_to_use}")
        if when_not_to_use:
            lines.append(f"  when_not_to_use: {when_not_to_use}")
        if failure_names:
            lines.append(f"  failure_modes: {failure_names}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tier assignment and early exit
# ---------------------------------------------------------------------------

def _assign_hiring_tier(knowledge_state: dict, hiring_signals: list[dict]) -> tuple[int, str]:
    tier_signals = get_tier_signals()
    tier1_signals = set(tier_signals["tier1"]["signals"])
    tier2_signals = set(tier_signals["tier2"]["signals"])

    for signal in hiring_signals:
        if signal.get("signal_type") in tier1_signals:
            return 1, signal.get("signal_text", "Tier 1 signal found")

    for signal in hiring_signals:
        if signal.get("signal_type") in tier2_signals:
            return 2, signal.get("signal_text", "Tier 2 signal found")

    if knowledge_state.get("hiring_signal", {}).get("status") == "partial":
        return 3, "No active signal, monitoring"

    return 4, "No signals found"


def _should_early_exit(knowledge_state: dict, hiring_signals: list[dict]) -> bool:
    tier1_signal_types = {
        "founder_personal_hiring_post",
        "job_posted_relevant_role_30d",
        "direct_hiring_confirmation",
    }
    has_tier1 = any(s.get("signal_type") in tier1_signal_types for s in hiring_signals)
    critical_ok = all(
        knowledge_state.get(d, {}).get("status") == "sufficient"
        for d in ["product_understanding", "work_alignment"]
    )
    return has_tier1 and critical_ok


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

@traceable(run_type="tool", name="Tavily Research Search")
def _fetch_source_with_query(source: dict, company: dict, search_query: str) -> dict:
    """Fetch via Tavily using model-generated query.

    Returns: {success: bool, content: str, url: str, error: str}
    """
    try:
        from pipeline_v2.lib.tool_router import search_web

        def _search():
            return search_web(search_query, limit=5)

        results = _call_with_retry(_search)
        combined_text = " ".join(r.get("description", r.get("content", "")) for r in results)
        first_url = results[0].get("url", "") if results else ""
        result_urls = [r.get("url", "") for r in results if r.get("url")]
        return {"success": True, "content": combined_text, "url": first_url, "result_urls": result_urls, "error": ""}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "content": "", "url": "", "result_urls": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Sonnet kickoff
# ---------------------------------------------------------------------------

_KICKOFF_FALLBACK = {
    "source_name": "company_website",
    "search_query": "",
    "query_reasoning": "default fallback — parse error on kickoff",
    "what_i_expect": "basic product and company information",
    "pool_gap_addressed": "product_understanding",
    "stuck_signal": False,
}


def _sonnet_kickoff(
    client: anthropic.Anthropic,
    company: dict,
    sources_detail: str,
    iterations: int = 0,
    max_iter: int = 0,
    consecutive_fetch_failures: int = 0,
    no_progress_thresh: int = 0,
    research_cost: float = 0.0,
    remaining: float = 0.0,
) -> tuple[dict, int, int]:
    """Kickoff planning call. Returns (plan_dict, input_tokens, output_tokens).

    plan_dict keys: source_name, search_query, query_reasoning,
                    what_i_expect, pool_gap_addressed, stuck_signal
    """
    company_name = company.get("name", "Unknown")
    founder = company.get("founder", "")
    description = company.get("description", "")
    fit_flags: list[str] = company.get("fit_flags") or []
    fit_confidence: str = company.get("fit_confidence", "")

    fit_context = ""
    if fit_flags:
        flags_str = "; ".join(fit_flags)
        fit_context = (
            f"\nSourcing confidence for this company: {fit_confidence}.\n"
            f"The sourcing agent flagged these specific uncertainties that need verification:\n"
            f"  {flags_str}\n"
            f"Prioritize resolving these flags in your first research fetches.\n"
        )

    flag_instruction = (
        "- If fit_flags are present above, your first fetch should target resolving the most\n"
        "  critical flag. Examples: if 'unclear if agent or wrapper' — fetch company_website\n"
        "  to assess product type first. If 'may be post-Series A' — fetch crunchbase_via_tavily.\n"
        "  If 'domain: crypto/blockchain' — fetch company_website to confirm or rule out.\n"
    ) if fit_flags else ""

    prompt = (
        f"You are a research agent preparing to investigate a company for cold outreach.\n\n"
        f"Company: {company_name}\n"
        + (f"Founder: {founder}\n" if founder else "")
        + (f"Description: {description}\n" if description else "")
        + fit_context
        + f"\nYour goal: understand this company well enough that {_USER_NAME} could write a message "
        f"the founder would actually reply to. {_USER_NAME} is {_USER_BACKGROUND}. "
        f"They are looking for companies building AI agent products.\n\n"
        f"{_EXECUTION_TOOLS_SECTION}\n"
        f"## RESEARCH STATUS\n\n"
        f"Iterations completed: {iterations}\n"
        f"Max iterations: {max_iter}\n"
        f"Consecutive fetch failures: {consecutive_fetch_failures}\n"
        f"No-progress threshold: {no_progress_thresh}\n"
        f"Cost used (research stage): ${research_cost:.4f}\n"
        f"Remaining before run cap: ${remaining:.4f}\n\n"
        f"If consecutive fetch failures >= {max(0, no_progress_thresh - 1)}, consider changing "
        f"strategy — try a fundamentally different source or query angle rather than repeating "
        f"similar searches.\n\n"
        f"If remaining budget < $0.05, prioritize the single most important remaining gap over "
        f"breadth.\n\n"
        f"Available sources:\n{sources_detail}\n\n"
        f"This is your kickoff planning step. No content has been fetched yet.\n\n"
        f"Plan your first research fetch:\n"
        f"- Which source gives the most useful starting point for this company?\n"
        f"- What specific search query will you use?\n"
        + flag_instruction
        + "- What do you expect to learn from it?\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "source_name": "...",\n'
        '  "search_query": "...",\n'
        '  "query_reasoning": "...",\n'
        '  "what_i_expect": "...",\n'
        '  "pool_gap_addressed": "...",\n'
        '  "stuck_signal": false\n'
        "}"
    )

    def _call():
        return client.messages.create(
            model=_SONNET_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

    response = _call_with_retry(_call)
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    raw = _strip_fences(response.content[0].text)

    try:
        result = json.loads(raw)
        if not isinstance(result.get("source_name"), str):
            raise ValueError("missing source_name")
        return result, in_tok, out_tok
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Kickoff parse error: %s. Raw: %s", exc, raw[:200])
        fallback = dict(_KICKOFF_FALLBACK)
        fallback["search_query"] = f"{company_name} product overview"
        return fallback, in_tok, out_tok


# ---------------------------------------------------------------------------
# Sonnet iteration
# ---------------------------------------------------------------------------

def _sonnet_iteration(
    client: anthropic.Anthropic,
    company: dict,
    knowledge_state: dict,
    source_name: str,
    search_query_used: str,
    content: str,
    search_history: list[dict],
    sources_detail: str,
    opus_redirect: dict | None = None,
    iterations: int = 0,
    max_iter: int = 0,
    consecutive_fetch_failures: int = 0,
    no_progress_thresh: int = 0,
    research_cost: float = 0.0,
    remaining: float = 0.0,
) -> tuple[dict, int, int]:
    """Per-iteration knowledge evaluation and next-source planning.

    Returns (iter_result_dict, input_tokens, output_tokens).
    """
    company_name = company.get("name", "Unknown")
    founder = company.get("founder", "")

    redirect_block = ""
    if opus_redirect is not None:
        redirect_instr = opus_redirect.get("redirect_instruction") or {}
        redirect_block = (
            "\n\n[OPUS REDIRECT]\n"
            f"The Opus advisor reviewed your research and issued a redirect.\n"
            f"What was missed: {opus_redirect.get('what_was_missed', '')}\n"
            f"Why it was missed: {opus_redirect.get('why_it_was_missed', '')}\n"
            f"Redirect instruction: {json.dumps(redirect_instr)}\n"
            f"Expected from redirect: {opus_redirect.get('expected_from_redirect', '')}\n"
            f"Evaluate this fetch with the redirect context in mind.\n"
        )

    history_str = json.dumps(search_history[-5:], indent=2) if search_history else "[]"
    content_truncated = content[:4000] if len(content) > 4000 else content

    prompt = (
        f"You are a research agent investigating {company_name} for cold outreach.\n\n"
        f"Company: {company_name}\n"
        + (f"Founder: {founder}\n" if founder else "")
        + f"\nYour goal: understand this company well enough that {_USER_NAME} could write a message "
        f"the founder would actually reply to.\n\n"
        f"{_EXECUTION_TOOLS_SECTION}\n"
        f"## RESEARCH STATUS\n\n"
        f"Iterations completed: {iterations}\n"
        f"Max iterations: {max_iter}\n"
        f"Consecutive fetch failures: {consecutive_fetch_failures}\n"
        f"No-progress threshold: {no_progress_thresh}\n"
        f"Cost used (research stage): ${research_cost:.4f}\n"
        f"Remaining before run cap: ${remaining:.4f}\n\n"
        f"If consecutive fetch failures >= {max(0, no_progress_thresh - 1)}, consider changing "
        f"strategy — try a fundamentally different source or query angle rather than repeating "
        f"similar searches.\n\n"
        f"If remaining budget < $0.05, prioritize the single most important remaining gap over "
        f"breadth.\n\n"
        f"Available sources:\n{sources_detail}\n\n"
        f"Current knowledge state:\n{json.dumps(knowledge_state, indent=2)}\n\n"
        f"Recent search history (last 5):\n{history_str}\n\n"
        f"---\n"
        f"Latest fetch:\n"
        f"Source: {source_name}\n"
        f"Query used: {search_query_used}\n"
        f"Content:\n{content_truncated}\n"
        + redirect_block
        + "\n---\n\n"
        f"Evaluate what you learned from this fetch.\n"
        f"Update the knowledge state for dimensions this content is relevant to.\n"
        f"Then plan your next fetch.\n\n"
        f"Signal types (use exact strings):\n"
        f"Tier 1: founder_personal_hiring_post, job_posted_relevant_role_30d, direct_hiring_confirmation\n"
        f"Tier 2: funding_raised_90d, headcount_growing, job_posted_not_exact_match, yc_batch_recent\n\n"
        f"Provenance rules for hiring_signals:\n"
        f"- confirmed_from_url: always include — the specific page URL where this signal was found.\n"
        f"- poster_name, poster_role, post_platform, post_date_raw: only include for signals with\n"
        f"  source 'founder_posts' or 'community_hiring_platforms', and only if the content actually\n"
        f"  contains that information. Set to null otherwise. Do not infer or hallucinate these fields.\n"
        f"- post_platform values: linkedin | twitter | other\n\n"
        f"Return ONLY valid JSON:\n"
        f"{{\n"
        f'  "knowledge_state": {{ /* full updated 5-dim dict — preserve unchanged dims exactly */ }},\n'
        f'  "hiring_signals": [\n'
        f'    {{\n'
        f'      "signal_text": "...", "signal_type": "...", "source": "{source_name}",\n'
        f'      "source_url": "...", "signal_recency_days": 0, "url": "...",\n'
        f'      "confirmed_from_url": "...",\n'
        f'      "poster_name": null, "poster_role": null, "post_platform": null, "post_date_raw": null\n'
        f'    }}\n'
        f'  ],\n'
        f'  "dims_updated": ["dim1"],\n'
        f'  "source_chosen_reasoning": "...",\n'
        f'  "what_i_expected_to_find": "...",\n'
        f'  "what_i_actually_found": "...",\n'
        f'  "dimension_assessment_reasoning": "...",\n'
        f'  "early_exit_reasoning": null,\n'
        f'  "stuck_signal": false,\n'
        f'  "sources_considered": [\n'
        f'    {{\n'
        f'      "source_name": "...",\n'
        f'      "why_considered": "...",\n'
        f'      "why_rejected_or_chosen": "..."\n'
        f'    }}\n'
        f'  ],\n'
        f'  "next_source": {{\n'
        f'    "source_name": "...",\n'
        f'    "search_query": "...",\n'
        f'    "query_reasoning": "...",\n'
        f'    "what_i_expect": "...",\n'
        f'    "pool_gap_addressed": "..."\n'
        f'  }}\n'
        f"}}"
    )

    def _call():
        return client.messages.create(
            model=_SONNET_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

    response = _call_with_retry(_call)
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    raw = _strip_fences(response.content[0].text)

    try:
        result = json.loads(raw)
        result.setdefault("knowledge_state", knowledge_state)
        result.setdefault("hiring_signals", [])
        result.setdefault("dims_updated", [])
        result.setdefault("stuck_signal", False)
        result.setdefault("sources_considered", [])
        result.setdefault("next_source", {
            "source_name": "web_search_general",
            "search_query": f"{company_name} AI agent",
            "query_reasoning": "fallback",
            "what_i_expect": "general info",
            "pool_gap_addressed": "product_understanding",
        })
        return result, in_tok, out_tok
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Iteration parse error: %s. Raw: %s", exc, raw[:200])
        return {
            "knowledge_state": knowledge_state,
            "hiring_signals": [],
            "dims_updated": [],
            "source_chosen_reasoning": "parse error",
            "what_i_expected_to_find": "",
            "what_i_actually_found": "parse error on model response",
            "dimension_assessment_reasoning": "",
            "early_exit_reasoning": None,
            "stuck_signal": True,
            "next_source": {
                "source_name": "web_search_general",
                "search_query": f"{company_name} AI agent",
                "query_reasoning": "fallback after parse error",
                "what_i_expect": "general info",
                "pool_gap_addressed": "product_understanding",
            },
        }, in_tok, out_tok


# ---------------------------------------------------------------------------
# Opus checkpoint
# ---------------------------------------------------------------------------

def _opus_checkpoint(
    client: anthropic.Anthropic,
    company: dict,
    search_history: list[dict],
    knowledge_state: dict,
    n_iterations: int,
    stuck_reason: str,
) -> tuple[dict, int, int]:
    """Opus advisor checkpoint. Returns (checkpoint_dict, input_tokens, output_tokens).

    checkpoint_dict contains option="A" (redirect) or option="B" (synthesis).
    Falls back to option="B" synthesis on parse error to avoid infinite loops.
    """
    company_name = company.get("name", "Unknown")
    founder = company.get("founder", "")

    prompt = (
        f"You are a senior research advisor reviewing research progress for a cold outreach pipeline.\n\n"
        f"Company: {company_name}\n"
        + (f"Founder: {founder}\n" if founder else "")
        + f"Iterations completed: {n_iterations}\n"
        + (f"Reason for checkpoint: {stuck_reason}\n" if stuck_reason else "")
        + f"\nYour goal: determine whether {_USER_NAME} has enough to write a message the founder would "
        f"actually reply to. {_USER_NAME} is {_USER_BACKGROUND}.\n\n"
        f"Current knowledge state:\n{json.dumps(knowledge_state, indent=2)}\n\n"
        f"Full search history:\n{json.dumps(search_history, indent=2)}\n\n"
        f"Assess the research. Choose ONE of:\n\n"
        f"Option A — Redirect: Research has missed something important. Tell the agent what to look for.\n"
        f"Option B — Synthesize: Research is sufficient. Produce outreach context.\n\n"
        f"Return ONLY valid JSON in exactly one of these shapes:\n\n"
        f"Option A:\n"
        f"{{\n"
        f'  "option": "A",\n'
        f'  "sufficiency_judgment": "insufficient",\n'
        f'  "what_was_done_well": "...",\n'
        f'  "what_was_missed": "...",\n'
        f'  "why_it_was_missed": "...",\n'
        f'  "redirect_instruction": {{\n'
        f'    "source_name": "...",\n'
        f'    "search_query": "...",\n'
        f'    "query_reasoning": "...",\n'
        f'    "what_i_expect": "...",\n'
        f'    "pool_gap_addressed": "..."\n'
        f'  }},\n'
        f'  "expected_from_redirect": "..."\n'
        f"}}\n\n"
        f"Option B:\n"
        f"{{\n"
        f'  "option": "B",\n'
        f'  "sufficiency_judgment": "sufficient",\n'
        f'  "what_was_done_well": "...",\n'
        f'  "what_was_missed": "...",\n'
        f'  "gaps_accepted": "...",\n'
        f'  "work_alignment": "...",\n'
        f'  "why_founders_narrative": "...",\n'
        f'  "product_gaps": "...",\n'
        f'  "outreach_angle": "...",\n'
        f'  "jd_actual_work": null,\n'
        f'  "jd_pain_signals": null,\n'
        f'  "jd_language": null,\n'
        f'  "work_alignment_reasoning": "...",\n'
        f'  "why_founders_evidence": "...",\n'
        f'  "structured_company": {{\n'
        f'    "has_live_product": true or false,\n'
        f'    "has_paid_customers": true or false,\n'
        f'    "is_agentic_ai": true or false,\n'
        f'    "tech_stack": "Python, FastAPI, LangGraph (or null if unknown)",\n'
        f'    "product_type": "API or SaaS or platform or CLI or other (or null)",\n'
        f'    "traction": "free text — users, revenue, growth evidence (or null)",\n'
        f'    "funding_round": "seed or series_a or series_b or unknown",\n'
        f'    "funding_amount": "$2M or undisclosed or null",\n'
        f'    "funding_investors": "YC, a16z (or null)",\n'
        f'    "funding_date": "2024-01 or null"\n'
        f'  }},\n'
        f'  "structured_founders": [\n'
        f'    {{\n'
        f'      "name": "Full Name",\n'
        f'      "role": "CEO or CTO or co-founder",\n'
        f'      "linkedin_url": "https://linkedin.com/in/... or null",\n'
        f'      "bio": "Career background in one sentence",\n'
        f'      "personal_motivation": "Why this person is working on this problem",\n'
        f'      "prior_companies": [{{"company": "Google", "role": "SWE", "years": "2020-2022"}}],\n'
        f'      "identification_confidence": "high or medium or low"\n'
        f'    }}\n'
        f'  ]\n'
        f"}}\n\n"
        f"jd_actual_work: what the engineering role actually involves day-to-day, extracted from a "
        f"job description if one was found. Set to null if no JD was found.\n"
        f"jd_pain_signals: problems the JD reveals the company is currently facing, inferred from "
        f"role requirements. Set to null if no JD was found.\n"
        f"jd_language: exact phrases the company uses to describe their work, preserved verbatim "
        f"for use in drafting. Set to null if no JD was found."
        f"\nstructured_company: Extract all fields you can confirm. Use null for anything unknown — do NOT guess.\n"
        f"structured_founders: List ALL confirmed founders (1–3). If you cannot confirm a founder, omit them. "
        f"Set identification_confidence based on: high = confirmed on LinkedIn or company website, "
        f"medium = mentioned in article, low = inferred only."
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
        result = json.loads(raw)
        if result.get("option") not in ("A", "B"):
            raise ValueError(f"unexpected option: {result.get('option')}")
        return result, in_tok, out_tok
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Opus checkpoint parse error: %s. Raw: %s", exc, raw[:200])
        return {
            "option": "B",
            "sufficiency_judgment": "sufficient",
            "what_was_done_well": "parse error fallback",
            "what_was_missed": "",
            "gaps_accepted": "parse error — proceeding with available data",
            "work_alignment": knowledge_state.get("work_alignment", {}).get("summary", ""),
            "why_founders_narrative": "",
            "product_gaps": "",
            "outreach_angle": "",
            "jd_actual_work": None,
            "jd_pain_signals": None,
            "jd_language": None,
            "work_alignment_reasoning": "fallback from parse error",
            "why_founders_evidence": "",
            "structured_company": {},
            "structured_founders": [],
        }, in_tok, out_tok


# ---------------------------------------------------------------------------
# Main research node
# ---------------------------------------------------------------------------

@traceable(name="Research Node")
def research_node(state: AgentState) -> dict:
    """Goal-oriented research node — Sonnet agent with Opus advisor checkpoints."""
    current_company: dict = state.get("current_company") or {}
    run_type: str = state.get("run_type") or "daily_light"
    run_id: str = state.get("run_id") or ""

    if not current_company:
        logger.warning("research_node called with no current_company — returning early with tier 4")
        return {
            "last_completed_node": "research",
            "knowledge_state": empty_knowledge_state(),
            "knowledge_iterations": 0,
            "knowledge_confidence": "low",
            "hiring_tier": 4,
            "hiring_tier_reason": "No company to research",
            "hiring_signals_found": [],
            "fetched_sources": [],
            "failed_sources": [],
            "source_attempt_log": [],
            "research_search_history": [],
            "opus_synthesis": None,
            "daily_cost": state.get("daily_cost") or 0.0,
            "cost_by_stage": dict(state.get("cost_by_stage") or {}),
        }

    knowledge_state: dict = dict(state.get("knowledge_state") or empty_knowledge_state())
    hiring_signals: list[dict] = list(state.get("hiring_signals_found") or [])
    cost_by_stage: dict[str, float] = dict(state.get("cost_by_stage") or {})
    daily_cost: float = state.get("daily_cost") or 0.0
    search_history: list[dict] = list(state.get("research_search_history") or [])
    fetched_sources_set: set[str] = set(state.get("fetched_sources") or [])
    failed_sources: list[str] = list(state.get("failed_sources") or [])
    source_attempt_log: list[dict] = list(state.get("source_attempt_log") or [])

    all_sources = load_sources()
    light_categories = get_light_source_categories()
    max_iter = get_max_iterations(run_type)
    no_progress_thresh = get_no_progress_threshold(run_type)
    checkpoint_interval = get_opus_checkpoint_interval(run_type)

    sonnet_client = wrap_anthropic(anthropic.Anthropic())
    opus_client = wrap_anthropic(anthropic.Anthropic())

    # ── Phase 0: Kickoff ──────────────────────────────────────────────────
    if is_over_limit(daily_cost):
        logger.warning("Daily cost cap reached before research kickoff ($%.4f) — skipping %s",
                       daily_cost, current_company.get("name"))
        return {
            "last_completed_node": "research",
            "skip_reason": "cost_cap_before_kickoff",
            "knowledge_state": knowledge_state,
            "hiring_tier": None,
            "hiring_tier_reason": "skipped: cost cap",
            "hiring_signals_found": hiring_signals,
            "cost_by_stage": cost_by_stage,
            "daily_cost": daily_cost,
        }

    sources_detail = _build_research_sources_detail(all_sources, fetched_sources_set, run_type, light_categories)
    kickoff_result, in_tok, out_tok = _sonnet_kickoff(
        sonnet_client, current_company, sources_detail,
        iterations=0,
        max_iter=max_iter,
        consecutive_fetch_failures=0,
        no_progress_thresh=no_progress_thresh,
        research_cost=cost_by_stage.get("research", 0.0),
        remaining=max(0.0, get_cost_cap() - daily_cost),
    )
    cost = compute_cost(_SONNET_MODEL, in_tok, out_tok)
    persist_cost_log(
        run_id=run_id,
        stage="research",
        company_id=(state.get("current_company") or {}).get("company_id"),
        model=_SONNET_MODEL,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
    )
    cost_by_stage = add_cost(cost_by_stage, "research", cost)
    daily_cost += cost

    log_decision(
        run_id=run_id, company_id=None, company_name=current_company.get("name", ""),
        node="research", decision="kickoff_plan",
        confidence="low", reasoning=kickoff_result.get("query_reasoning", ""),
        next_action="research_iteration",
        node_specific={
            "source_name": kickoff_result.get("source_name"),
            "search_query": kickoff_result.get("search_query"),
            "what_i_expect": kickoff_result.get("what_i_expect"),
            "pool_gap_addressed": kickoff_result.get("pool_gap_addressed"),
        },
        model_used=_SONNET_MODEL, input_tokens=in_tok, output_tokens=out_tok,
        call_type="research_kickoff", iteration_number=0,
    )

    next_source_plan: dict = kickoff_result
    sonnet_iters_since_checkpoint: int = 0
    in_redirect_mode: bool = False
    current_redirect: dict | None = None
    redirect_just_completed: bool = False
    redirect_source_name: str | None = None
    consecutive_fetch_failures: int = 0
    opus_synthesis: dict | None = None
    structured_company: dict = {}
    structured_founders: list = []
    iterations: int = 0

    # ── Main loop ─────────────────────────────────────────────────────────
    while iterations < max_iter:
        # Determine source + query for this iteration
        if in_redirect_mode and current_redirect:
            redirect_instr = current_redirect.get("redirect_instruction") or {}
            source_name = redirect_instr.get("source_name", "web_search_general")
            search_query = redirect_instr.get("search_query",
                                             f"{current_company.get('name', '')} AI agent")
            in_redirect_mode = False
            redirect_just_completed = True
            redirect_source_name = source_name
        else:
            source_name = next_source_plan.get("source_name", "web_search_general")
            search_query = next_source_plan.get("search_query",
                                                f"{current_company.get('name', '')} AI agent")

        source_obj = _find_source_by_name(all_sources, source_name)
        is_outside_curated = source_obj.get("source_category") == "outside_curated"

        # Fall back to an eligible curated source if chosen one is ineligible
        if not _is_eligible_for_run_type(source_obj, run_type, light_categories):
            fallback = next(
                (s for s in all_sources
                 if _is_eligible_for_run_type(s, run_type, light_categories)
                 and s["source_name"] not in fetched_sources_set),
                None,
            )
            if fallback is None:
                logger.info("No eligible sources remain — exiting loop")
                break
            source_obj = fallback
            source_name = fallback["source_name"]
            search_query = f"{current_company.get('name', '')} {source_name}"
            is_outside_curated = False

        # Hard limit: cost cap
        if is_over_limit(daily_cost):
            logger.warning("Daily cost cap reached ($%.4f) — exiting for %s",
                           daily_cost, current_company.get("name"))
            break

        # yc_directory has no per-company scraper in research — fall back to a
        # targeted Tavily lookup so the LLM gets real data instead of an empty query error.
        if source_name == "yc_directory":
            company_name = current_company.get("name", "")
            search_query = f'"{company_name}" site:ycombinator.com'

        # Fetch
        fetch_result = _fetch_source_with_query(source_obj, current_company, search_query)

        attempt: dict = {
            "source_name": source_name,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "success": fetch_result["success"],
            "failure_reason": fetch_result["error"] if not fetch_result["success"] else "",
            "entities_found": 0,
        }

        if not fetch_result["success"]:
            failed_sources.append(source_name)
            fetched_sources_set.add(source_name)
            consecutive_fetch_failures += 1
            source_attempt_log.append(attempt)
            logger.warning("Fetch failed: %s — %s (consecutive=%d)",
                           source_name, fetch_result["error"], consecutive_fetch_failures)
            if consecutive_fetch_failures >= no_progress_thresh:
                logger.info("Consecutive fetch failure threshold — exiting loop")
                break
            iterations += 1
            continue

        consecutive_fetch_failures = 0
        fetched_sources_set.add(source_name)
        sources_detail = _build_research_sources_detail(all_sources, fetched_sources_set, run_type, light_categories)

        # Log outside_curated immediately after successful fetch
        if is_outside_curated:
            log_decision(
                run_id=run_id, company_id=None, company_name=current_company.get("name", ""),
                node="research", decision="outside_curated_fetch",
                confidence="low", reasoning=next_source_plan.get("query_reasoning", ""),
                next_action="research_iteration",
                node_specific={
                    "why_curated_insufficient": next_source_plan.get("stuck_signal_reason", ""),
                    "outside_source_chosen": source_name,
                    "reasoning": next_source_plan.get("source_chosen_reasoning", ""),
                },
                model_used=None, input_tokens=None, output_tokens=None,
                call_type="research_outside_curated", iteration_number=iterations + 1,
            )

        # Guard: don't fire Sonnet if cap already blown by a prior call this iteration
        if is_over_limit(daily_cost):
            logger.warning("Daily cost cap reached before Sonnet iteration ($%.4f) — exiting for %s",
                           daily_cost, current_company.get("name"))
            break

        # Sonnet iteration evaluation
        opus_redirect_for_prompt = current_redirect if redirect_just_completed else None
        iter_result, in_tok, out_tok = _sonnet_iteration(
            sonnet_client, current_company, knowledge_state,
            source_name, search_query, fetch_result["content"],
            search_history, sources_detail, opus_redirect=opus_redirect_for_prompt,
            iterations=iterations,
            max_iter=max_iter,
            consecutive_fetch_failures=consecutive_fetch_failures,
            no_progress_thresh=no_progress_thresh,
            research_cost=cost_by_stage.get("research", 0.0),
            remaining=max(0.0, get_cost_cap() - daily_cost),
        )
        cost = compute_cost(_SONNET_MODEL, in_tok, out_tok)
        persist_cost_log(
            run_id=run_id,
            stage="research",
            company_id=(state.get("current_company") or {}).get("company_id"),
            model=_SONNET_MODEL,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
        )
        cost_by_stage = add_cost(cost_by_stage, "research", cost)
        daily_cost += cost
        sonnet_iters_since_checkpoint += 1

        # Update state
        knowledge_state = iter_result.get("knowledge_state", knowledge_state)
        hiring_signals.extend(iter_result.get("hiring_signals", []))
        next_source_plan = iter_result.get("next_source", next_source_plan)
        stuck_signal: bool = bool(iter_result.get("stuck_signal", False))

        history_entry = {
            "iteration": iterations + 1,
            "source_name": source_name,
            "search_query": search_query,
            "success": True,
            "result_urls": fetch_result.get("result_urls", []),
            "dims_updated": iter_result.get("dims_updated", []),
            "what_i_expected_to_find": iter_result.get("what_i_expected_to_find", ""),
            "what_i_actually_found": iter_result.get("what_i_actually_found", ""),
            "source_chosen_reasoning": iter_result.get("source_chosen_reasoning", ""),
        }
        search_history.append(history_entry)

        attempt["entities_found"] = len(iter_result.get("dims_updated", []))
        source_attempt_log.append(attempt)

        log_decision(
            run_id=run_id, company_id=None, company_name=current_company.get("name", ""),
            node="research", decision=f"iteration_{iterations + 1}",
            confidence="medium",
            reasoning=iter_result.get("dimension_assessment_reasoning", ""),
            next_action="research_iteration",
            node_specific={
                "source_chosen_reasoning": iter_result.get("source_chosen_reasoning"),
                "sources_considered": iter_result.get("sources_considered", []),
                "what_i_expected_to_find": iter_result.get("what_i_expected_to_find"),
                "what_i_actually_found": iter_result.get("what_i_actually_found"),
                "dimension_assessment_reasoning": iter_result.get("dimension_assessment_reasoning"),
                "early_exit_reasoning": iter_result.get("early_exit_reasoning"),
                "dims_updated": iter_result.get("dims_updated", []),
                "stuck_signal": stuck_signal,
            },
            model_used=_SONNET_MODEL, input_tokens=in_tok, output_tokens=out_tok,
            call_type="research_iteration", iteration_number=iterations + 1,
        )

        # Log redirect outcome — Python only, no model call
        if redirect_just_completed:
            log_decision(
                run_id=run_id, company_id=None, company_name=current_company.get("name", ""),
                node="research", decision=f"redirect_outcome_{iterations + 1}",
                confidence="medium", reasoning="",
                next_action="research_iteration",
                node_specific={
                    "redirect_found_expected": bool(iter_result.get("dims_updated")),
                    "what_was_actually_found": iter_result.get("what_i_actually_found"),
                    "revised_sufficiency_judgment": (
                        "partial" if iter_result.get("dims_updated") else "still_insufficient"
                    ),
                    "redirect_source": redirect_source_name,
                },
                model_used=None, input_tokens=None, output_tokens=None,
                call_type="opus_checkpoint_redirect_outcome", iteration_number=iterations + 1,
                was_redirected=True,
                redirect_reason=(current_redirect.get("what_was_missed", "")
                                 if current_redirect else ""),
            )
            redirect_just_completed = False
            current_redirect = None
            redirect_source_name = None

        # Check early exit
        if _should_early_exit(knowledge_state, hiring_signals):
            logger.info("Early exit: Tier 1 signal + critical dims sufficient")
            iterations += 1
            break

        # Check Opus checkpoint
        if is_over_limit(daily_cost):
            logger.warning("Daily cost cap reached before Opus checkpoint ($%.4f) — exiting for %s",
                           daily_cost, current_company.get("name"))
            break
        trigger_checkpoint = (sonnet_iters_since_checkpoint >= checkpoint_interval) or stuck_signal
        if trigger_checkpoint:
            checkpoint_result, in_tok, out_tok = _opus_checkpoint(
                opus_client, current_company, search_history, knowledge_state,
                iterations + 1, "stuck" if stuck_signal else "interval",
            )
            cost = compute_cost(_OPUS_MODEL, in_tok, out_tok)
            persist_cost_log(
                run_id=run_id,
                stage="research",
                company_id=(state.get("current_company") or {}).get("company_id"),
                model=_OPUS_MODEL,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost,
            )
            cost_by_stage = add_cost(cost_by_stage, "research", cost)
            daily_cost += cost
            sonnet_iters_since_checkpoint = 0

            option = checkpoint_result.get("option", "B")

            if option == "A":
                in_redirect_mode = True
                current_redirect = checkpoint_result
                log_decision(
                    run_id=run_id, company_id=None, company_name=current_company.get("name", ""),
                    node="research", decision="opus_checkpoint_redirect",
                    confidence="high",
                    reasoning=checkpoint_result.get("sufficiency_judgment", ""),
                    next_action="research_iteration",
                    node_specific={
                        "sufficiency_judgment": checkpoint_result.get("sufficiency_judgment"),
                        "what_was_done_well": checkpoint_result.get("what_was_done_well"),
                        "what_was_missed": checkpoint_result.get("what_was_missed"),
                        "why_it_was_missed": checkpoint_result.get("why_it_was_missed"),
                        "redirect_instruction": checkpoint_result.get("redirect_instruction"),
                        "expected_from_redirect": checkpoint_result.get("expected_from_redirect"),
                    },
                    model_used=_OPUS_MODEL, input_tokens=in_tok, output_tokens=out_tok,
                    call_type="opus_checkpoint", iteration_number=iterations + 1,
                    was_redirected=True,
                    redirect_reason=checkpoint_result.get("what_was_missed", ""),
                )
            else:
                opus_synthesis = checkpoint_result
                structured_company = (opus_synthesis or {}).get("structured_company") or {}
                structured_founders = (opus_synthesis or {}).get("structured_founders") or []
                log_decision(
                    run_id=run_id, company_id=None, company_name=current_company.get("name", ""),
                    node="research", decision="opus_synthesis",
                    confidence="high",
                    reasoning=checkpoint_result.get("sufficiency_judgment", ""),
                    next_action="leverage",
                    node_specific={
                        "sufficiency_judgment": checkpoint_result.get("sufficiency_judgment"),
                        "what_was_done_well": checkpoint_result.get("what_was_done_well"),
                        "what_was_missed": checkpoint_result.get("what_was_missed"),
                        "gaps_accepted": checkpoint_result.get("gaps_accepted"),
                        "work_alignment": checkpoint_result.get("work_alignment"),
                        "why_founders_narrative": checkpoint_result.get("why_founders_narrative"),
                        "product_gaps": checkpoint_result.get("product_gaps"),
                        "outreach_angle": checkpoint_result.get("outreach_angle"),
                        "jd_actual_work": checkpoint_result.get("jd_actual_work"),
                        "jd_pain_signals": checkpoint_result.get("jd_pain_signals"),
                        "jd_language": checkpoint_result.get("jd_language"),
                        "work_alignment_reasoning": checkpoint_result.get("work_alignment_reasoning"),
                        "why_founders_evidence": checkpoint_result.get("why_founders_evidence"),
                    },
                    model_used=_OPUS_MODEL, input_tokens=in_tok, output_tokens=out_tok,
                    call_type="opus_synthesis", iteration_number=iterations + 1,
                )
                iterations += 1
                break

        iterations += 1

    # ── Post-loop ─────────────────────────────────────────────────────────
    hiring_tier, hiring_tier_reason = _assign_hiring_tier(knowledge_state, hiring_signals)
    knowledge_confidence = overall_confidence(knowledge_state)

    _persist_state = {
        **dict(state),
        "current_company": current_company,
        "hiring_tier": hiring_tier,
        "hiring_tier_reason": hiring_tier_reason,
        "knowledge_confidence": knowledge_confidence,
        "knowledge_state": knowledge_state,
        "hiring_signals_found": hiring_signals,
    }
    company_id = persist_company(_persist_state)
    if company_id:
        persist_research(company_id, _persist_state)
        for attempt in source_attempt_log:
            if attempt.get("success"):
                persist_source(
                    company_id=company_id,
                    source_name=attempt.get("source_name", "unknown"),
                    source_url=attempt.get("source_url"),
                    scrape_strategy=attempt.get("strategy"),
                )
        current_company = dict(current_company)
        current_company["company_id"] = company_id
        if structured_founders:
            primary = structured_founders[0]
            current_company["founder"] = primary.get("name", "")
            current_company["founder_role"] = primary.get("role", "")
            current_company["founder_linkedin"] = primary.get("linkedin_url", "")
            current_company["founders"] = structured_founders

    return {
        "last_completed_node": "research",
        "current_company": current_company,
        "knowledge_state": knowledge_state,
        "knowledge_iterations": iterations,
        "knowledge_confidence": knowledge_confidence,
        "hiring_tier": hiring_tier,
        "hiring_tier_reason": hiring_tier_reason,
        "hiring_signals_found": hiring_signals,
        "fetched_sources": list(fetched_sources_set),
        "failed_sources": failed_sources,
        "source_attempt_log": source_attempt_log,
        "daily_cost": daily_cost,
        "cost_by_stage": cost_by_stage,
        "opus_synthesis": opus_synthesis,
        "structured_company": structured_company,
        "structured_founders": structured_founders,
        "research_search_history": search_history,
    }
