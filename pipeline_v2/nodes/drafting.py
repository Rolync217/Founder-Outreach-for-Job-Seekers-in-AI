import json
import logging
import re
import time
from pathlib import Path as _Path
from typing import Any, Callable

from langsmith import traceable
from pipeline_v2.lib.llm_client import call_llm

from pipeline_v2.state import AgentState, DraftRecord
from pipeline_v2.lib.cost_tracker import compute_cost, add_cost
from pipeline_v2.lib.decision_logger import log_decision
from pipeline_v2.lib.db_persistence import persist_cost_log
from tools.config_loader import cfg

logger = logging.getLogger(__name__)

_DRAFTING_MODEL = cfg.models.drafting
_USER_FIRST_NAME = cfg.get("user_profile", {}).get("name", "").split()[0].lower()


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t[t.index("\n") + 1:] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[: t.rfind("```")]
    return t.strip()


def _load_outreach_rules() -> str:
    base = _Path(__file__).parent.parent.parent / "skills" / "outreach-rules"
    parts = []
    for fname in ["references/rules.md", "references/tone-templates.md", "references/examples.md"]:
        fpath = base / fname
        try:
            parts.append(fpath.read_text())
        except OSError:
            logger.warning("Could not load outreach rule file: %s", fpath)
    style_path = _Path(__file__).parent.parent.parent / "skills" / "outreach_style.md"
    try:
        parts.append(style_path.read_text())
    except OSError:
        pass  # optional — not required
    return "\n\n---\n\n".join(parts) if parts else ""


OUTREACH_RULES = _load_outreach_rules()

_MESSAGE_MODES = ["linkedin_invite", "linkedin_dm", "long_reference"]

_LIMITS = {
    "linkedin_invite": {"chars": (290, 300)},
    "linkedin_dm": {"words": (0, 150)},
    "long_reference": {"words": (0, 170)},
}


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


def _count_words(text: str) -> int:
    return len(text.split())


def _count_chars(text: str) -> int:
    return len(text)


def _validate_draft(mode: str, text: str) -> list[str]:
    failures = []

    # 1. format_limits
    if mode == "linkedin_invite":
        char_count = _count_chars(text)
        min_chars, max_chars = _LIMITS["linkedin_invite"]["chars"]
        if not (min_chars <= char_count <= max_chars):
            failures.append("format_limits")
    elif mode == "linkedin_dm":
        word_count = _count_words(text)
        if word_count >= _LIMITS["linkedin_dm"]["words"][1]:
            failures.append("format_limits")
    elif mode == "long_reference":
        word_count = _count_words(text)
        if word_count >= _LIMITS["long_reference"]["words"][1]:
            failures.append("format_limits")

    # 2. soft_entry (linkedin_invite only)
    if mode == "linkedin_invite":
        text_lower = text.lower()
        soft_entry_phrases = [
            "had a quick thought",
            "was looking into",
            "one thing i was thinking",
        ]
        if not any(phrase in text_lower for phrase in soft_entry_phrases):
            failures.append("soft_entry")

    # 3. opening_not_generic
    generic_openings = [
        "I came across",
        "I noticed you",
        "I saw that you",
        "impressive",
        "interesting",
    ]
    for phrase in generic_openings:
        if text.lower().startswith(phrase.lower()):
            failures.append("opening_not_generic")
            break

    # 4. has_credibility
    text_lower = text.lower()
    if "i've seen" not in text_lower and "in my workflow" not in text_lower:
        failures.append("has_credibility")

    # 5. has_soft_ask — question must appear before the sign-off name
    stripped = text.strip()
    if stripped.rstrip(".,;:!").lower().endswith(_USER_FIRST_NAME):
        stripped_no_punct = stripped.rstrip(".,;:!")
        pre_signoff = stripped_no_punct[: -len(_USER_FIRST_NAME)].rstrip()
        soft_ask_ok = pre_signoff.endswith("?")
    else:
        soft_ask_ok = stripped.endswith("?")
    if not soft_ask_ok:
        failures.append("has_soft_ask")

    # 6. no_em_dashes
    if "—" in text:
        failures.append("no_em_dashes")

    # 7. no_banned_phrases
    banned_phrases = [
        "looking for a job",
        "seeking",
        "would love to connect",
        "i came across",
        "salary",
        "compensation",
        "equity",
        "referral",
    ]
    text_lower = text.lower()
    for phrase in banned_phrases:
        if phrase in text_lower:
            failures.append("no_banned_phrases")
            break

    # 8. no_job_framing
    if re.search(r'\b(job|role|opportunity)\b', text_lower):
        failures.append("no_job_framing")

    # 9. no_links
    link_patterns = ["http://", "https://", "linkedin.com"]
    for pattern in link_patterns:
        if pattern in text_lower:
            failures.append("no_links")
            break

    # 10. ends_with_name
    if not text.strip().rstrip(".,;:!").lower().endswith(_USER_FIRST_NAME):
        failures.append("ends_with_name")

    return failures


def _sonnet_draft(
    mode: str,
    company: dict,
    knowledge_state: dict,
    leverage_output: dict,
    hiring_signals: list,
    previous_failures: list[str],
    iteration: int,
) -> tuple[str, float, int, int]:
    limits = _LIMITS[mode]
    if "chars" in limits:
        limit_description = f"{limits['chars'][0]}–{limits['chars'][1]} characters"
    else:
        limit_description = f"under {limits['words'][1]} words"

    company_name = company.get("name", "Unknown")
    founder_name = company.get("founder", "Unknown")
    founder_role = company.get("founder_role", "Founder")

    product_understanding = (knowledge_state.get("product_understanding") or {}).get("summary", "")
    work_alignment = (knowledge_state.get("work_alignment") or {}).get("summary", "")
    relevant_experience = leverage_output.get("relevant_experience", "")
    leverage_statement = leverage_output.get("leverage_statement", "")

    signals_slice = hiring_signals[:3]

    prompt_parts = [
        "You are a cold outreach drafting engine. Draft a personalized cold outreach message.\n\n",
        f"## Outreach Rules\n{OUTREACH_RULES}\n\n",
        f"## Message Mode\n{mode}\n\n",
        f"## Limit\n{limit_description}\n\n",
        f"## Company\nName: {company_name}\nFounder: {founder_name} ({founder_role})\n\n",
        f"## Product Understanding\n{product_understanding}\n\n",
        f"## Work Alignment\n{work_alignment}\n\n",
        f"## Relevant Experience\n{relevant_experience}\n\n",
        f"## Leverage Statement\n{leverage_statement}\n\n",
        f"## Hiring Signals\n{json.dumps(signals_slice, indent=2)}\n\n",
    ]

    if iteration > 0 and previous_failures:
        prompt_parts.append(
            f"## Previous Validation Failures\n"
            f"The previous draft failed these checks: {previous_failures}\n"
            f"Fix all of them in this rewrite.\n\n"
        )

    prompt_parts.append(
        "Return ONLY the message text — no JSON, no preamble, no explanation."
    )

    prompt = "".join(prompt_parts)

    def _call():
        return call_llm(
            model=_DRAFTING_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )

    content, in_tok, out_tok = _call_with_retry(_call)
    cost = compute_cost(_DRAFTING_MODEL, in_tok, out_tok)
    text = content.strip()
    return text, cost, in_tok, out_tok


def _sonnet_founder_critique(
    mode: str,
    text: str,
    company_name: str,
    founder_name: str,
    founder_role: str,
) -> tuple[dict, float, int, int]:
    prompt = (
        f"You are {founder_name}, {founder_role} at {company_name}.\n"
        f"You just received this cold message:\n\n"
        f"---\n{text}\n---\n\n"
        f"Context on what founders like you typically respond to:\n"
        f"{OUTREACH_RULES}\n\n"
        f"React as you naturally would. Answer:\n"
        f"1. Does this feel authentic and specific to your company, or like a template?\n"
        f"2. Is the observation real and grounded, or generic and vague?\n"
        f"3. What is your main concern about this message, if any?\n\n"
        f"Return ONLY valid JSON:\n"
        f'{{"seems_authentic": true, "main_concern": "...", "critique": "..."}}'
    )

    def _call():
        return call_llm(
            model=_DRAFTING_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
        )

    content, in_tok, out_tok = _call_with_retry(_call)
    cost = compute_cost(_DRAFTING_MODEL, in_tok, out_tok)
    raw = _strip_fences(content)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Founder critique returned non-JSON for mode %s: %s", mode, raw[:100])
        result = {}
    return result, cost, in_tok, out_tok


@traceable(name="Drafting Node")
def drafting_node(state: AgentState) -> dict:
    current_company = state.get("current_company") or {}
    knowledge_state = state.get("knowledge_state") or {}
    leverage_output = state.get("leverage_output") or {}
    hiring_signals_found = state.get("hiring_signals_found") or []
    cost_by_stage = dict(state.get("cost_by_stage") or {})
    daily_cost = state.get("daily_cost") or 0.0

    records: list[DraftRecord] = []

    for mode in _MESSAGE_MODES:
        iteration = 0
        failures: list[str] = []
        text = ""

        while iteration < 3:
            text, cost, in_tok, out_tok = _sonnet_draft(
                mode,
                current_company,
                knowledge_state,
                leverage_output,
                hiring_signals_found,
                failures,
                iteration,
            )
            persist_cost_log(
                run_id=state.get("run_id", ""),
                stage="drafting",
                company_id=(state.get("current_company") or {}).get("company_id"),
                model=_DRAFTING_MODEL,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost,
            )
            cost_by_stage = add_cost(cost_by_stage, "drafting", cost)
            daily_cost += cost

            log_decision(
                run_id=(state.get("run_id") or ""),
                company_id=(state.get("current_company") or {}).get("company_id"),
                company_name=current_company.get("name", ""),
                node="drafting", decision="generate", confidence="medium",
                reasoning=f"mode={mode} iteration={iteration}",
                next_action="validate",
                call_type="draft_generate",
                model_used=_DRAFTING_MODEL,
                input_tokens=in_tok, output_tokens=out_tok,
                node_specific={"mode": mode, "iteration": iteration},
            )

            new_failures = _validate_draft(mode, text)

            if not new_failures:
                failures = []
                break

            if iteration == 2:
                failures = new_failures
                break

            failures = new_failures
            iteration += 1

        # Founder critique — only if Python validation passed
        founder_critique = ""
        if not failures:
            try:
                critique_result, critique_cost, crit_in_tok, crit_out_tok = _sonnet_founder_critique(
                    mode, text,
                    current_company.get("name", ""),
                    current_company.get("founder", ""),
                    current_company.get("founder_role", "Founder"),
                )
                cost_by_stage = add_cost(cost_by_stage, "drafting", critique_cost)
                daily_cost += critique_cost
                founder_critique = critique_result.get("critique", "")
                log_decision(
                    run_id=(state.get("run_id") or ""),
                    company_id=(state.get("current_company") or {}).get("company_id"),
                    company_name=current_company.get("name", ""),
                    node="drafting", decision="critique", confidence="medium",
                    reasoning=critique_result.get("main_concern", ""),
                    next_action="done",
                    call_type="draft_critique",
                    model_used=_DRAFTING_MODEL,
                    input_tokens=crit_in_tok, output_tokens=crit_out_tok,
                    node_specific={
                        "mode": mode, "seems_authentic": critique_result.get("seems_authentic"),
                        "main_concern": critique_result.get("main_concern", ""),
                    },
                )
            except Exception as e:
                logger.warning("Founder critique failed for mode %s: %s", mode, e)

        record: DraftRecord = {
            "founder_name": current_company.get("founder", ""),
            "founder_role": current_company.get("founder_role", ""),
            "message_mode": mode,
            "message_text": text,
            "char_count": _count_chars(text),
            "word_count": _count_words(text),
            "leverage_confidence": state.get("leverage_confidence") or "none",
            "validation_status": "passed" if not failures else "needs_fix",
            "validation_failures": failures,
            "rewrite_iteration": iteration,
            "founder_critique": founder_critique,
        }
        records.append(record)

    all_failures = []
    for r in records:
        all_failures.extend(r["validation_failures"])

    # Persist drafts to DB (best-effort)
    try:
        from pipeline_v2.lib.db_persistence import persist_drafts
        company_id = (state.get("current_company") or {}).get("company_id")
        if company_id:
            persist_drafts(company_id, {**dict(state), "draft_output": records})
    except Exception as e:
        logger.warning("Failed to persist drafts: %s", e)

    return {
        "last_completed_node": "drafting",
        "draft_output": records,
        "draft_iterations": sum(r["rewrite_iteration"] + 1 for r in records),
        "validation_passed": all(r["validation_status"] == "passed" for r in records),
        "validation_feedback": "; ".join(all_failures),
        "cost_by_stage": cost_by_stage,
        "daily_cost": daily_cost,
    }
