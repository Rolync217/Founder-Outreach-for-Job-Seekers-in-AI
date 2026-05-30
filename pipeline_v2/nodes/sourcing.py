"""pipeline/nodes/sourcing.py

Sourcing node — discovers companies using Firecrawl search and Playwright (YC only).
Uses Haiku for entity extraction from raw search results.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from langsmith import traceable
from pipeline_v2.lib.llm_client import call_llm

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore[assignment]

from pipeline_v2.state import AgentState
from pipeline_v2.lib.cost_tracker import compute_cost, add_cost, is_over_limit
from pipeline_v2.lib.entity_validator import validate_entity
from pipeline_v2.lib.source_loader import load_sources, get_work_alignment_criteria
from pipeline_v2.lib.scope_loader import get_light_source_categories, get_cost_cap, get_pool_sufficient_threshold
from pipeline_v2.lib.decision_logger import log_decision
from pipeline_v2.lib.db_persistence import persist_cost_log
from tools.config_loader import cfg

logger = logging.getLogger(__name__)

_USER_NAME = cfg.get("user_profile", {}).get("name", "the candidate")
_USER_BACKGROUND = cfg.get("user_profile", {}).get("background", "a software engineer")

_FILTER_MODEL = cfg.models.filter
_SOURCING_MODEL = cfg.models.sourcing


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t[t.index("\n") + 1:] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[: t.rfind("```")]
    return t.strip()


_STOP_CONDITIONS = {
    "target_pool_size": {"daily_light": 30, "deep_run": 50},
    "max_sourcing_iterations": 15,
    "consecutive_low_quality_limit": 5,
    "minimum_dimension_coverage": {
        "required_before_stop": ["hiring_signal", "product_understanding"],
        "minimum_companies_per_dimension": 5,
    },
}

_SOURCING_PURPOSES = {
    "discover_new_startups",
    "detect_direct_hiring_from_founder",
    "detect_early_hiring_signals",
    "discover_startups_hiring",
}


def _is_sourcing_eligible(src: dict, run_type: str, light_categories: list[str]) -> bool:
    purposes = set(src.get("purpose") or [])
    if not purposes.intersection(_SOURCING_PURPOSES):
        return False
    if run_type == "daily_light" and src.get("source_category") not in light_categories:
        return False
    return True


def _call_with_retry(fn: Callable, retries: int = 3, delay: float = 5) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                logger.warning(
                    "API call failed (attempt %d/%d): %s. Retrying in %ss…",
                    attempt + 1, retries, exc, delay,
                )
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


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


def _load_work_type_preferences() -> str:
    """Extract the work_type_preferences section from candidate-leverage SKILL.md."""
    skill_path = (
        Path(__file__).parent.parent.parent / "skills" / "candidate-leverage" / "SKILL.md"
    )
    try:
        content = skill_path.read_text()
        marker = "### work_type_preferences"
        idx = content.find(marker)
        if idx == -1:
            return ""
        return content[idx:].strip()
    except Exception:
        return ""


def _build_sourcing_sources_detail(
    all_sources: list[dict],
    attempted: set[str],
    run_type: str,
    light_categories: list[str],
) -> str:
    """Build a rich per-source description for the Sonnet prompt.

    Shows ALL sources (eligible and ineligible) with run_type_eligible markers so Sonnet
    can reason about the full landscape. Ineligible sources are clearly marked.
    """
    lines: list[str] = ["## SOURCING SOURCES\n"]
    for src in all_sources:
        name = src["source_name"]
        cost = src.get("cost_tier", "unknown")
        conf = src.get("confidence_weight", "unknown")
        dims = ", ".join(src.get("signal_types_supported") or [])
        is_attempted = name in attempted
        is_eligible = _is_sourcing_eligible(src, run_type, light_categories)

        when_to_use = _first_n_sentences(src.get("when_to_use", ""), 2)
        when_not = _first_n_sentences(src.get("when_not_to_use", ""), 1)
        failures_raw = src.get("common_failure_modes") or []
        failures = ", ".join(str(f).split("#")[0].strip() for f in failures_raw)

        attempted_label = "YES — already attempted this run" if is_attempted else "no"
        eligible_label = "YES" if is_eligible else f"no  ← not available in {run_type}"

        lines.append(f"[{name}]")
        lines.append(f"  cost={cost} | confidence_weight={conf} | signal_types={dims}")
        lines.append(f"  already_attempted: {attempted_label}")
        lines.append(f"  run_type_eligible: {eligible_label}")
        if when_to_use:
            lines.append(f"  when_to_use: {when_to_use}")
        if when_not:
            lines.append(f"  when_not_to_use: {when_not}")
        if failures:
            lines.append(f"  common_failure_modes: {failures}")
        lines.append("")

    eligible_names = {
        s["source_name"] for s in all_sources
        if _is_sourcing_eligible(s, run_type, light_categories)
    }
    all_exhausted = all(n in attempted for n in eligible_names)
    if all_exhausted:
        lines.append(
            "NOTE: All curated sources have been attempted. You may choose 'outside_curated' "
            "to generate a free-form web search targeted at the specific company types you still need."
        )
    return "\n".join(lines)


def _sonnet_sourcing_decision(
    pool: list[dict],
    pool_target: int,
    under_covered_dims: list[str],
    all_sources: list[dict],
    light_categories: list[str],
    attempted_source_names: set[str],
    run_type: str,
    work_alignment_criteria: dict,
    work_type_preferences: str,
    sourcing_cost: float = 0.0,
    daily_cost_total: float = 0.0,
    cost_cap: float = 0.0,
    low_quality_streak: int = 0,
    sourcing_iterations: int = 0,
) -> tuple[dict, int, int]:
    pool_size = len(pool)
    sources_detail = _build_sourcing_sources_detail(all_sources, attempted_source_names, run_type, light_categories)

    # Pool quality summary — name + truncated description per company
    pool_lines = []
    for c in pool:
        name = c.get("name", "")
        desc = c.get("description", "")
        pool_lines.append(f"  - {name}: {desc[:80]}" if desc else f"  - {name}")
    pool_summary = (
        "\n".join(pool_lines) if pool_lines else "  (pool is empty — nothing found yet)"
    )

    # Format work_alignment_criteria sections
    wac_lines: list[str] = []
    for category in ("strongly_preferred", "preferred", "acceptable", "excluded"):
        section = work_alignment_criteria.get(category)
        if section is None:
            continue
        if isinstance(section, dict):
            desc = " ".join((section.get("description") or "").split())
            signals = section.get("signals") or []
            wac_lines.append(f"  {category.upper()}:")
            if desc:
                wac_lines.append(f"    {desc}")
            for sig in signals:
                wac_lines.append(f"    - {sig}")
        elif isinstance(section, list):
            wac_lines.append(f"  {category.upper()}: {', '.join(str(x) for x in section)}")
    wac_text = "\n".join(wac_lines)

    under_covered_str = (
        ", ".join(under_covered_dims) if under_covered_dims
        else "none — all dimensions have coverage"
    )

    prompt = (
        "You are a sourcing agent finding early-stage AI startups for a specific candidate.\n\n"
        "## SOURCING GOAL\n\n"
        f"Find early-stage AI startups where {_USER_NAME} could write a cold message a founder\n"
        f"would actually reply to. {_USER_NAME} is {_USER_BACKGROUND}. They are looking for\n"
        "companies where agents ARE the product or where existing workflows are being made\n"
        "agentic. Every company you find should be worth researching in depth.\n\n"
        "## CANDIDATE WORK TYPE PREFERENCES\n\n"
        f"{work_type_preferences}\n\n"
        "## TARGET COMPANY PROFILE\n\n"
        "  Stage: pre-seed, seed, or Series A maximum\n"
        "  Team size: under 50 employees\n"
        "  Domain: AI agent products, agentic workflow automation\n"
        "  Hard excludes: crypto, blockchain, web3, GPU optimization, model training\n"
        "    infrastructure, inference optimization, vector databases as core product,\n"
        "    MLOps, LLM evaluation frameworks as product, developer-only APIs,\n"
        "    AI safety research, foundation models\n\n"
        "## WORK ALIGNMENT CRITERIA\n\n"
        f"{wac_text}\n\n"
        "## CURRENT POOL STATE\n\n"
        f"Pool size: {pool_size} / {pool_target} (target)\n"
        f"Under-covered dimensions: {under_covered_str}\n\n"
        "Companies found so far:\n"
        f"{pool_summary}\n\n"
        "## EXECUTION TOOLS AVAILABLE\n\n"
        "web_search (Firecrawl):\n"
        "  Used for ALL sources except yc_directory.\n"
        "  How it works: searches the public web using your query string. Returns top 10\n"
        "  results as title, description snippet, and URL. Quality depends entirely on how\n"
        "  specific and targeted your query is. The source name does NOT change what\n"
        "  Firecrawl searches — your query does.\n"
        "  To surface platform-specific content, include the platform in your query:\n"
        "    - founder_posts: include 'linkedin.com' or 'twitter.com' and 'founder' or\n"
        "      'CEO' or 'CTO' and 'hiring'\n"
        "    - community_hiring_platforms: include 'Hacker News hiring' or\n"
        "      'YC Work at a Startup' or specific Slack/Discord community names\n"
        "    - vc_portfolio_pages: include the VC firm name and 'portfolio' —\n"
        "      e.g. 'a16z portfolio AI agent startup 2025'\n"
        "    - funding_news: include 'raised' or 'seed round' or 'Series A' with\n"
        "      domain keywords\n"
        "    - ats_boards: NEVER use site: alone — always pair the ATS domain with\n"
        "      job-type keywords, e.g. 'AI agent startup engineer greenhouse.io jobs'\n"
        "      or 'agentic workflow software engineer lever.co'. A bare site: query\n"
        "      will be rejected by the search engine.\n\n"
        "yc_directory_scraper:\n"
        "  Used ONLY for yc_directory.\n"
        "  How it works: scrapes YC company directory with Hiring filter applied. Returns\n"
        "  structured company cards. No query string needed — Python handles navigation.\n"
        "  Use when: pool needs YC-backed company coverage and yc_directory has not been\n"
        "  attempted yet.\n\n"
        "When you choose a source, you are choosing a query strategy, not a different data\n"
        "pipeline. Write your query as if you are a skilled researcher who knows exactly what\n"
        "search terms will surface the companies you are looking for on the open web.\n\n"
        f"{sources_detail}\n\n"
        "## BUDGET STATUS\n\n"
        f"Cost used this run (sourcing): ${sourcing_cost:.4f}\n"
        f"Remaining before run cap: ${max(0.0, cost_cap - daily_cost_total):.4f}\n"
        f"Iterations completed: {sourcing_iterations}\n"
        f"Consecutive weak results: {low_quality_streak}\n\n"
        "If consecutive weak results >= 3, consider whether a fundamentally different search\n"
        "angle would help, or whether you have genuinely exhausted the available signal for this run.\n\n"
        "If remaining budget < $0.10, prioritize stopping unless you have a specific\n"
        "high-value search you haven't tried.\n\n"
        "## YOUR TASK\n\n"
        f"Run type: {run_type}\n\n"
        "Reason through:\n"
        "1. What types of companies are already in the pool? What categories are missing?\n"
        "2. What dimensions are under-covered and which sources best address them?\n"
        "3. Which source should you use next and why? Consider attempted sources and their\n"
        "   failure modes.\n"
        "4. Write a specific, targeted query that will actually surface AI agent startups\n"
        "   fitting the target profile.\n"
        "5. Should you stop? Only signal should_stop=true if the pool is genuinely good enough.\n\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "thinking": {\n'
        '    "what_i_know_about_pool_so_far": "types of companies found, coverage gaps, quality",\n'
        '    "what_i_still_need": "what kinds of companies or signals are still missing",\n'
        '    "sources_i_considered": [\n'
        '      {"source_name": "...", "why_considered": "...", "why_rejected_or_chosen": "..."}\n'
        '    ],\n'
        '    "why_this_source_now": "full reasoning for chosen source given pool state",\n'
        '    "what_i_expect_this_query_to_surface": "specific kinds of companies this finds",\n'
        '    "what_would_make_me_stop_after_this": "what pool needs to look like to call goal met"\n'
        '  },\n'
        '  "decision": {\n'
        '    "source_name": "...",\n'
        '    "search_query": "...",\n'
        '    "query_reasoning": "one-line summary",\n'
        '    "should_stop": false,\n'
        '    "stop_reasoning": ""\n'
        "  }\n"
        "}"
    )

    def _call():
        return call_llm(
            model=_SOURCING_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
        )

    content, in_tok, out_tok = _call_with_retry(_call)
    raw = _strip_fences(content)

    try:
        parsed = json.loads(raw)
        decision = parsed.get("decision") or {}
        thinking = parsed.get("thinking") or {}
        decision["_thinking"] = thinking
    except json.JSONDecodeError:
        logger.warning("Sonnet sourcing decision parse error — using fallback: %s", raw[:200])
        available = [
            s for s in all_sources
            if _is_sourcing_eligible(s, run_type, light_categories)
            and s["source_name"] not in attempted_source_names
        ]
        fallback_source = available[0]["source_name"] if available else "outside_curated"
        decision = {
            "source_name": fallback_source,
            "search_query": "AI agent startup hiring engineer 2026",
            "query_reasoning": "parse error fallback",
            "should_stop": False,
            "stop_reasoning": "",
            "_thinking": {},
        }

    return decision, in_tok, out_tok


@traceable(run_type="tool", name="Firecrawl Sourcing Search")
def _fetch_via_firecrawl(query: str) -> dict:
    """Fetch via Firecrawl search using model-generated query.

    Returns: {success: bool, results: list[{title, content, url}], error: str}
    """
    try:
        from pipeline_v2.lib.tool_router import search_web

        def _search():
            return search_web(query, limit=10)

        raw = _call_with_retry(_search)
        results = [
            {"title": r.get("title", ""), "content": r.get("description", ""), "url": r.get("url", "")}
            for r in raw
        ]
        return {"success": True, "results": results, "error": ""}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "results": [], "error": str(exc)}


@traceable(run_type="tool", name="YC Directory Fetch")
def _fetch_yc_directory(run_type: str) -> dict:
    """Fetch YC companies via Playwright. Returns {success, results: list[{title, content, url}], error}"""
    if sync_playwright is None:
        return {"success": False, "results": [], "error": "playwright not installed"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page()
            try:
                page.goto("https://www.ycombinator.com/companies", timeout=60000)

                hiring_btn = page.query_selector("button[data-value='Hiring']")
                if hiring_btn:
                    hiring_btn.click()
                    page.wait_for_timeout(1000)
                else:
                    page.wait_for_timeout(3000)

                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 1000)")
                    page.wait_for_timeout(500)

                results = []
                cards = page.query_selector_all(".company-card")
                if not cards:
                    cards = page.query_selector_all(".companies-list li")

                if cards:
                    for card in cards[:50]:
                        text = card.inner_text()
                        link = card.query_selector("a")
                        url = ""
                        if link:
                            href = link.get_attribute("href") or ""
                            if href.startswith("/"):
                                url = f"https://www.ycombinator.com{href}"
                            else:
                                url = href
                        lines = [line.strip() for line in text.split("\n") if line.strip()]
                        name = lines[0] if lines else ""
                        description = lines[1] if len(lines) > 1 else ""
                        if name:
                            results.append({"title": name, "content": description, "url": url})
                else:
                    content = page.content()
                    urls = re.findall(r'href="(/companies/[^"]+)"', content)
                    seen = set()
                    for u in urls[:50]:
                        full_url = f"https://www.ycombinator.com{u}"
                        if full_url not in seen:
                            seen.add(full_url)
                            slug = u.split("/")[-1].replace("-", " ").title()
                            results.append({"title": slug, "content": "", "url": full_url})
            finally:
                browser.close()

        return {"success": True, "results": results, "error": ""}
    except Exception as exc:
        return {"success": False, "results": [], "error": str(exc)}


def _haiku_extract_entities(
    source: dict,
    results: list[dict],
) -> tuple[list[dict], float, int, int]:
    """Use Haiku to extract company entities from raw Tavily results with confidence scoring.

    Returns (entities, cost_usd, input_tokens, output_tokens).
    Each entity: {name, url, description, source_name, pool_origin,
                  fit_confidence, fit_reasoning, fit_flags}
    """
    results_text = ""
    for r in results:
        chunk = (
            f"Title: {r.get('title', '')}\n"
            f"URL: {r.get('url', '')}\n"
            f"Content: {r.get('content', '')}\n\n"
        )
        if len(results_text) + len(chunk) > 3000:
            results_text += chunk[: max(0, 3000 - len(results_text))]
            break
        results_text += chunk

    source_name = source.get("source_name", "unknown")
    prompt = (
        f"You are extracting company entities from search results for a job-search pipeline.\n"
        f"Source: {source_name}\n"
        f"Target profile: early-stage AI agent startups (pre-seed to Series A, under 50 employees).\n"
        f"The candidate is {_USER_NAME}. {_USER_BACKGROUND}. They are looking for companies\n"
        f"where agents ARE the product or where existing workflows are being made agentic.\n\n"
        f"Search results:\n{results_text}\n\n"
        f"EXTRACTION RULES:\n"
        f"Include a company if it could plausibly be an early-stage AI startup.\n"
        f"When in doubt — include with fit_confidence: low rather than exclude.\n\n"
        f"Hard-exclude ONLY these (never include regardless):\n"
        f"- VC firms, investors, funds\n"
        f"- Article titles or blog post titles (not actual companies)\n"
        f"- Generic category/list pages\n"
        f"- Accelerators themselves (include their portfolio companies, not the accelerator)\n"
        f"- Large, publicly traded, or well-known companies with >500 employees\n"
        f"  (e.g. Airbnb, DoorDash, Stripe, OpenAI, Google, Microsoft)\n"
        f"- Duplicate companies already mentioned earlier in the same results\n\n"
        f"For every company you include, assess fit against the target profile:\n\n"
        f"  fit_confidence: high\n"
        f"    Clearly an AI agent product or agentic workflow automation company,\n"
        f"    early stage (pre-seed/seed/Series A), under ~50 employees, no red flags.\n\n"
        f"  fit_confidence: medium\n"
        f"    Possibly fits but something is uncertain — stage unclear, team size unknown,\n"
        f"    domain description is ambiguous, or could be wrapper vs. real agent work.\n\n"
        f"  fit_confidence: low\n"
        f"    Weakly fits or has a specific red flag worth flagging, but not definitively\n"
        f"    excluded. Use this for companies in: crypto/blockchain/web3, GPU/model training\n"
        f"    infrastructure, inference optimization, vector databases as core product,\n"
        f"    MLOps, LLM evaluation frameworks as product, developer-only APIs,\n"
        f"    AI safety research, foundation model companies. Include them with a flag\n"
        f"    so the research node can verify.\n\n"
        f"Return ONLY valid JSON — a list of objects:\n"
        f"[\n"
        f"  {{\n"
        f'    "name": "Company Name",\n'
        f'    "url": "https://...",\n'
        f'    "description": "one-line description or empty string",\n'
        f'    "fit_confidence": "high",\n'
        f'    "fit_reasoning": "one sentence explaining this confidence level",\n'
        f'    "fit_flags": [],\n'
        f'    "batch": "W25 or S24 etc. — ONLY if this is a YC company and the batch is visible. null otherwise.",\n'
        f'    "founded_year": "4-digit year as string, e.g. \\"2023\\" — null if not visible.",\n'
        f'    "team_size": null\n'
        f"  }},\n"
        f"  ...\n"
        f"]\n\n"
        f"fit_flags must be an empty list [] for high confidence.\n"
        f"For medium/low, list specific concerns, e.g.:\n"
        f'  "may be post-Series A", "unclear if agent or wrapper",\n'
        f'  "description suggests infra focus", "team size unknown",\n'
        f'  "could be developer API not end-user product",\n'
        f'  "domain: crypto/blockchain", "domain: GPU/model training infra"\n\n'
        f"If no valid companies found, return []."
    )

    def _call():
        return call_llm(
            model=_FILTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
        )

    raw_content, haiku_in_tok, haiku_out_tok = _call_with_retry(_call)
    cost = compute_cost(_FILTER_MODEL, haiku_in_tok, haiku_out_tok)

    raw_text = raw_content.strip()
    try:
        entities = json.loads(_strip_fences(raw_text))
        if not isinstance(entities, list):
            entities = []
    except json.JSONDecodeError:
        logger.warning("Haiku returned non-JSON for source %s: %s", source_name, raw_text[:200])
        return [], cost, haiku_in_tok, haiku_out_tok

    for entity in entities:
        entity["source_name"] = source_name
        entity["pool_origin"] = source.get("source_category", "unknown")
        entity.setdefault("fit_confidence", "medium")
        entity.setdefault("fit_reasoning", "")
        entity.setdefault("fit_flags", [])
        entity.setdefault("batch", None)
        entity.setdefault("founded_year", None)
        entity.setdefault("team_size", None)

    return entities, cost, haiku_in_tok, haiku_out_tok


def _check_dimension_coverage(pool: list[dict], sources: list[dict]) -> list[str]:
    """Check which required dimensions have < 5 companies covered.
    Returns list of dimension names that are still under-covered.
    """
    required = _STOP_CONDITIONS["minimum_dimension_coverage"]["required_before_stop"]
    minimum = _STOP_CONDITIONS["minimum_dimension_coverage"]["minimum_companies_per_dimension"]

    sources_by_dimension: dict[str, set[str]] = {}
    for src in sources:
        for dim in src.get("signal_types_supported", []):
            sources_by_dimension.setdefault(dim, set()).add(src["source_name"])

    under_covered = []
    for dim in required:
        supporting_sources = sources_by_dimension.get(dim, set())
        count = sum(1 for c in pool if c.get("source_name") in supporting_sources)
        if count < minimum:
            under_covered.append(dim)

    return under_covered


@traceable(name="Sourcing Node")
def sourcing_node(state: AgentState) -> dict:
    run_type: str = state.get("run_type") or "daily_light"
    run_id: str = state.get("run_id") or ""
    candidate_pool: list[dict] = list(state.get("candidate_pool") or [])
    sourcing_iterations: int = state.get("sourcing_iterations") or 0
    entities_rejected_as_invalid: list[dict] = list(state.get("entities_rejected_as_invalid") or [])
    sourcing_attempt_log: list = list(state.get("sourcing_source_attempt_log") or [])
    cost_by_stage: dict[str, float] = dict(state.get("cost_by_stage") or {})
    daily_cost: float = state.get("daily_cost") or 0.0

    all_sources = load_sources()
    light_categories = get_light_source_categories()

    eligible_sources = [s for s in all_sources if _is_sourcing_eligible(s, run_type, light_categories)]

    pool = list(candidate_pool)
    pool_names: set[str] = {c["name"].lower() for c in pool}
    rejected = list(entities_rejected_as_invalid)
    attempt_log = list(sourcing_attempt_log)
    low_quality_streak = 0
    outside_curated_count = 0

    target = get_pool_sufficient_threshold()
    attempted_source_names: set[str] = {a["source_name"] for a in attempt_log}

    work_alignment_criteria = get_work_alignment_criteria()
    work_type_preferences = _load_work_type_preferences()

    logger.info(
        "Sourcing node started. run_type=%s pool_size=%d target=%d eligible_sources=%d",
        run_type, len(pool), target, len(eligible_sources),
    )

    while True:
        # Hard stop: daily cost cap — only legitimate Python exit besides pool-target check
        if is_over_limit(daily_cost):
            log_decision(
                run_id=run_id, company_id=None, company_name="sourcing_run",
                node="sourcing", decision="stop", confidence="high",
                reasoning="daily cost cap reached",
                next_action="supervisor", call_type="sourcing_stop",
                node_specific={"reason": "daily cost cap reached", "pool_size": len(pool)},
            )
            logger.warning("Daily cost cap reached — stopping sourcing.")
            break

        # Always compute coverage so Sonnet gets accurate data regardless of pool size
        under_covered = _check_dimension_coverage(pool, all_sources)

        # Python hard limit: pool full + dimension coverage satisfied
        if len(pool) >= target and not under_covered:
            log_decision(
                run_id=run_id, company_id=None, company_name="sourcing_run",
                node="sourcing", decision="stop", confidence="high",
                reasoning="pool target reached and dimension coverage satisfied",
                next_action="supervisor", call_type="sourcing_stop",
                node_specific={"pool_size": len(pool), "iterations": sourcing_iterations},
            )
            logger.info("Pool target reached and coverage satisfied — stopping.")
            break

        # Sonnet decides which source to use and generates the search query
        decision, in_tok, out_tok = _sonnet_sourcing_decision(
            pool, target, under_covered,
            all_sources, light_categories, attempted_source_names, run_type,
            work_alignment_criteria, work_type_preferences,
            sourcing_cost=cost_by_stage.get("sourcing", 0.0),
            daily_cost_total=daily_cost,
            cost_cap=get_cost_cap(),
            low_quality_streak=low_quality_streak,
            sourcing_iterations=sourcing_iterations,
        )
        sonnet_cost = compute_cost(_SOURCING_MODEL, in_tok, out_tok)
        cost_by_stage = add_cost(cost_by_stage, "sourcing", sonnet_cost)
        daily_cost += sonnet_cost
        persist_cost_log(
            run_id=run_id,
            stage="sourcing",
            company_id=None,
            model=_SOURCING_MODEL,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=sonnet_cost,
        )

        source_name = decision.get("source_name", "")
        search_query = decision.get("search_query", "")
        is_outside_curated = source_name == "outside_curated"

        # Hard limit: outside_curated can run at most 3 times per sourcing run
        if is_outside_curated:
            outside_curated_count += 1
            if outside_curated_count > 3:
                logger.warning("outside_curated limit reached (3) — stopping sourcing loop")
                log_decision(
                    run_id=run_id, company_id=None, company_name="sourcing_run",
                    node="sourcing", decision="stop", confidence="high",
                    reasoning="outside_curated hard limit (3) reached",
                    next_action="supervisor", call_type="sourcing_stop",
                    node_specific={"pool_size": len(pool), "outside_curated_count": outside_curated_count},
                )
                break

        # Safety net: if Sonnet chose an ineligible source, swap to an eligible fallback
        if not is_outside_curated and source_name:
            _chosen = next((s for s in all_sources if s["source_name"] == source_name), None)
            if _chosen and not _is_sourcing_eligible(_chosen, run_type, light_categories):
                _fallback = next(
                    (s for s in all_sources
                     if _is_sourcing_eligible(s, run_type, light_categories)
                     and s["source_name"] not in attempted_source_names),
                    None,
                )
                if _fallback:
                    _old_name = source_name
                    source_name = _fallback["source_name"]
                    logger.warning(
                        "Safety net fired: swapped ineligible source %s → %s (run_type=%s)",
                        _old_name, source_name, run_type,
                    )
                    log_decision(
                        run_id=run_id, company_id=None, company_name="sourcing_run",
                        node="sourcing", decision="ineligible_source_swap", confidence="high",
                        reasoning=f"Sonnet chose {_old_name} which is ineligible for {run_type}",
                        next_action="fetch", call_type="sourcing_ineligible_source_swap",
                        node_specific={
                            "old_source_name": _old_name,
                            "new_source_name": source_name,
                            "run_type": run_type,
                        },
                    )

        call_type = "sourcing_outside_curated" if is_outside_curated else "sourcing_query"
        thinking = decision.pop("_thinking", {})

        log_decision(
            run_id=run_id, company_id=None, company_name="sourcing_run",
            node="sourcing", decision=source_name, confidence="medium",
            reasoning=decision.get("query_reasoning", ""),
            next_action="fetch", call_type=call_type,
            model_used=_SOURCING_MODEL, input_tokens=in_tok, output_tokens=out_tok,
            node_specific={"search_query": search_query, "pool_size": len(pool), "thinking": thinking},
        )

        if decision.get("should_stop", False):
            if len(pool) < 10:
                log_decision(
                    run_id=run_id, company_id=None, company_name="sourcing_run",
                    node="sourcing", decision="stop_override", confidence="high",
                    reasoning="Python overriding Sonnet stop — pool below minimum floor",
                    next_action="fetch", call_type="sourcing_stop_override",
                    node_specific={"reason": "pool below minimum floor", "pool_size": len(pool)},
                )
                logger.info(
                    "Python overriding Sonnet stop — pool below minimum floor (%d < 10)", len(pool)
                )
            else:
                log_decision(
                    run_id=run_id, company_id=None, company_name="sourcing_run",
                    node="sourcing", decision="stop", confidence="high",
                    reasoning=decision.get("stop_reasoning", "agent decided to stop"),
                    next_action="supervisor", call_type="sourcing_stop",
                    node_specific={
                        "stop_reasoning": decision.get("stop_reasoning", ""),
                        "pool_size": len(pool),
                    },
                )
                logger.info("Sonnet stop honored: %s", decision.get("stop_reasoning"))
                break

        # Track attempted source names (outside_curated not tracked by name)
        if not is_outside_curated and source_name:
            attempted_source_names.add(source_name)

        logger.info("Sourcing iteration %d — source: %s", sourcing_iterations, source_name)

        # Dispatch fetch
        if source_name == "yc_directory":
            # Try the direct Algolia index first (richer data, no Playwright dep).
            # Falls back to the Playwright scraper if credentials are unavailable.
            try:
                from pipeline_v2.lib.tool_router import find_yc_companies
                algolia_companies = find_yc_companies()
                if algolia_companies:
                    fetch_result = {
                        "success": True,
                        "results": [
                            {
                                "title":   c.get("name", ""),
                                "content": c.get("description", ""),
                                "url":     c.get("website", ""),
                            }
                            for c in algolia_companies
                        ],
                        "error": "",
                    }
                else:
                    fetch_result = _fetch_yc_directory(run_type)
            except Exception as _algolia_exc:
                logger.warning("YC Algolia scraper failed (%s), falling back to Playwright", _algolia_exc)
                fetch_result = _fetch_yc_directory(run_type)
        elif not search_query.strip():
            logger.warning("Empty search_query for source %s — skipping", source_name)
            fetch_result = {"success": False, "results": [], "error": "empty search query"}
        else:
            fetch_result = _fetch_via_firecrawl(search_query)

        # Find the source dict for Haiku context; use minimal dict for outside_curated
        source_dict = next((s for s in all_sources if s["source_name"] == source_name), None)
        if source_dict is None:
            source_dict = {"source_name": source_name, "source_category": "outside_curated"}

        attempt = {
            "source_name": source_name,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "success": fetch_result["success"],
            "failure_reason": fetch_result.get("error", "") if not fetch_result["success"] else "",
            "entities_found": 0,
        }

        if not fetch_result["success"]:
            logger.warning("Fetch failed for source %s: %s", source_name, fetch_result.get("error"))
            low_quality_streak += 1
            attempt_log.append(attempt)
            sourcing_iterations += 1
            continue

        entities, haiku_cost, haiku_in_tok, haiku_out_tok = _haiku_extract_entities(source_dict, fetch_result["results"])
        persist_cost_log(
            run_id=run_id,
            stage="sourcing",
            company_id=None,
            model=_FILTER_MODEL,
            input_tokens=haiku_in_tok,
            output_tokens=haiku_out_tok,
            cost_usd=haiku_cost,
        )
        cost_by_stage = add_cost(cost_by_stage, "sourcing", haiku_cost)
        daily_cost += haiku_cost

        entities_added = 0
        for entity in entities:
            valid, reason = validate_entity(entity)
            if not valid:
                entity["rejection_reason"] = reason
                rejected.append(entity)
                continue
            name_lower = entity["name"].lower()
            if name_lower not in pool_names:
                if entity.get("fit_confidence") == "low":
                    entity["needs_prefilter_review"] = True
                pool.append(entity)
                pool_names.add(name_lower)
                entities_added += 1

        attempt["entities_found"] = entities_added
        attempt_log.append(attempt)
        logger.info("Source %s added %d entities. Pool size: %d", source_name, entities_added, len(pool))

        if entities_added == 0:
            low_quality_streak += 1
        else:
            low_quality_streak = 0

        sourcing_iterations += 1

    log_decision(
        run_id=run_id, company_id=None, company_name="sourcing_run",
        node="sourcing", decision="complete", confidence="medium",
        reasoning=f"Found {len(pool)} companies in {sourcing_iterations} iterations",
        next_action="supervisor", call_type="sourcing_stop",
        node_specific={"pool_size": len(pool), "iterations": sourcing_iterations, "rejected": len(rejected)},
    )

    return {
        "last_completed_node": "sourcing",
        "candidate_pool": pool,
        "sourcing_iterations": sourcing_iterations,
        "entities_rejected_as_invalid": rejected,
        "sourcing_source_attempt_log": attempt_log,
        "daily_cost": daily_cost,
        "cost_by_stage": cost_by_stage,
    }
