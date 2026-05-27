"""
pipeline/lib/db_persistence.py

Persist LangGraph pipeline outputs to Postgres tables used by the dashboard.
All functions are fire-and-forget (failure must not crash the pipeline).
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


_CONFIDENCE_MAP = {"high": 90, "medium": 60, "low": 30}


def persist_company(state: dict) -> Optional[str]:
    """Upsert current company into companies_v2. Returns company_id (UUID) or None on error."""
    from tools.db_conn import get_conn
    company = state.get("current_company") or {}
    name = company.get("name", "").strip()
    if not name:
        return None
    website      = (company.get("website") or company.get("url", "")).strip() or None
    batch        = company.get("batch") or None
    founded_year = str(company.get("founded_year")).strip() if company.get("founded_year") else None
    sector       = company.get("sector") or None
    stage        = company.get("stage") or None
    team_size    = int(company["team_size"]) if company.get("team_size") else None
    location     = company.get("location") or None
    sourcing_confidence = _CONFIDENCE_MAP.get(company.get("fit_confidence", ""), None)

    try:
        with get_conn() as conn:
            existing_id = None
            if website:
                row = conn.execute(
                    "SELECT id FROM companies_v2 WHERE company_website = %s", (website,)
                ).fetchone()
                if row:
                    existing_id = str(row["id"])
            if not existing_id:
                row = conn.execute(
                    "SELECT id FROM companies_v2 WHERE LOWER(name) = LOWER(%s)", (name,)
                ).fetchone()
                if row:
                    existing_id = str(row["id"])

            if existing_id:
                conn.execute("""
                    UPDATE companies_v2
                    SET status              = 'researched',
                        company_website     = COALESCE(%s, company_website),
                        batch               = COALESCE(%s, batch),
                        founded_year        = COALESCE(%s, founded_year),
                        sector              = COALESCE(%s, sector),
                        stage               = COALESCE(%s, stage),
                        team_size           = COALESCE(%s, team_size),
                        location            = COALESCE(%s, location),
                        sourcing_confidence = COALESCE(%s, sourcing_confidence),
                        last_processed_at   = now(),
                        updated_at          = now()
                    WHERE id = %s
                """, (website, batch, founded_year, sector, stage, team_size, location,
                      sourcing_confidence, existing_id))
                return existing_id
            else:
                row = conn.execute("""
                    INSERT INTO companies_v2
                        (name, company_website, source, description, status,
                         batch, founded_year, sector, stage, team_size, location,
                         sourcing_confidence, last_processed_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'researched',
                            %s, %s, %s, %s, %s, %s, %s, now(), now())
                    RETURNING id
                """, (
                    name, website,
                    company.get("source_name") or company.get("pool_origin", "pipeline"),
                    company.get("description", ""),
                    batch, founded_year, sector, stage, team_size, location,
                    sourcing_confidence,
                )).fetchone()
                return str(row["id"])
    except Exception as e:
        logger.warning("Failed to persist company '%s': %s", name, e)
        return None


def _build_citations_from_knowledge_state(knowledge_state: dict) -> list:
    """Extract source URLs from knowledge dimensions as citations."""
    citations = []
    dim_labels = {
        "product_understanding": "product",
        "work_alignment": "alignment",
        "founder_background": "founder",
        "hiring_signal": "hiring",
        "company_stage_and_size": "stage",
    }
    for dim, label in dim_labels.items():
        d = knowledge_state.get(dim, {})
        url = d.get("source_url", "")
        summary = d.get("summary", "")
        if url:
            citations.append({
                "claim": summary[:200] if summary else label,
                "source_url": url,
                "source_type": "company_website",
                "quote": None,
                "confidence": d.get("confidence", "medium"),
            })
    return citations


def _generate_company_report(state: dict) -> str:
    """Generate a markdown company report from available research data."""
    company = state.get("current_company") or {}
    opus = state.get("opus_synthesis") or {}
    sc = state.get("structured_company") or {}
    ks = state.get("knowledge_state") or {}
    sf = state.get("structured_founders") or []

    product_dim = ks.get("product_understanding", {})
    align_dim = ks.get("work_alignment", {})
    hiring_dim = ks.get("hiring_signal", {})

    lines = [
        f"# {company.get('name', 'Unknown Company')}",
        "",
        f"**Product:** {product_dim.get('summary', 'Unknown')}",
        f"**Alignment:** {align_dim.get('summary', 'Unknown')}",
        f"**Hiring Signal:** {hiring_dim.get('summary', 'None')}",
        "",
    ]
    if sc.get("traction"):
        lines += [f"**Traction:** {sc['traction']}", ""]
    if sc.get("funding_round"):
        amount = sc.get("funding_amount", "undisclosed")
        lines += [f"**Funding:** {sc['funding_round'].title()} — {amount}", ""]
    if sf:
        lines += ["## Founders"]
        for f in sf:
            lines.append(f"- **{f.get('name', '?')}** ({f.get('role', '?')}): {f.get('bio', '')}")
        lines.append("")
    if opus.get("outreach_angle"):
        lines += [f"**Outreach Angle:** {opus['outreach_angle']}", ""]
    return "\n".join(lines)


def persist_research(company_id: str, state: dict) -> Optional[str]:
    """Insert or update research_v2 row. Returns research_id (UUID) or None."""
    from tools.db_conn import get_conn
    try:
        knowledge_state = state.get("knowledge_state") or {}
        hiring_signals  = state.get("hiring_signals_found") or []
        opus            = state.get("opus_synthesis") or {}
        sc              = state.get("structured_company") or {}

        product_dim    = knowledge_state.get("product_understanding") or {}
        work_align_dim = knowledge_state.get("work_alignment") or {}
        founder_bg_dim = knowledge_state.get("founder_background") or {}

        alignment_notes        = opus.get("work_alignment") or work_align_dim.get("summary") or ""
        outreach_angle         = opus.get("outreach_angle") or ""
        company_founding_story = opus.get("why_founders_narrative") or founder_bg_dim.get("summary") or ""
        raw_research_json      = json.dumps(opus) if opus else None

        problem_statement = product_dim.get("problem", "") or product_dim.get("summary", "")
        solution_summary  = product_dim.get("solution", "") or product_dim.get("summary", "")

        has_live_product   = sc.get("has_live_product")
        has_paid_customers = sc.get("has_paid_customers")
        is_agentic_ai      = sc.get("is_agentic_ai")
        tech_stack         = sc.get("tech_stack") or None
        product_type       = sc.get("product_type") or None
        traction           = sc.get("traction") or None
        funding_round      = sc.get("funding_round") or None
        funding_amount     = sc.get("funding_amount") or None
        funding_investors  = sc.get("funding_investors") or None
        funding_date       = sc.get("funding_date") or None

        citations = _build_citations_from_knowledge_state(knowledge_state)
        citations_json = json.dumps(citations) if citations else None

        company_report = _generate_company_report(state)

        with get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM research_v2 WHERE company_id = %s", (company_id,)
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE research_v2
                    SET knowledge_state        = %s,
                        hiring_signals_json    = %s,
                        alignment_notes        = COALESCE(%s, alignment_notes),
                        outreach_angle         = COALESCE(%s, outreach_angle),
                        company_founding_story = COALESCE(%s, company_founding_story),
                        raw_research_json      = COALESCE(%s::jsonb, raw_research_json),
                        has_live_product       = COALESCE(%s, has_live_product),
                        has_paid_customers     = COALESCE(%s, has_paid_customers),
                        is_agentic_ai          = COALESCE(%s, is_agentic_ai),
                        tech_stack             = COALESCE(%s, tech_stack),
                        product_type           = COALESCE(%s, product_type),
                        traction               = COALESCE(%s, traction),
                        funding_round          = COALESCE(%s, funding_round),
                        funding_amount         = COALESCE(%s, funding_amount),
                        funding_investors      = COALESCE(%s, funding_investors),
                        funding_date           = COALESCE(%s, funding_date),
                        citations_json         = COALESCE(%s::jsonb, citations_json),
                        company_report         = COALESCE(%s, company_report),
                        updated_at             = now()
                    WHERE id = %s
                """, (
                    json.dumps(knowledge_state), json.dumps(hiring_signals),
                    alignment_notes or None, outreach_angle or None,
                    company_founding_story or None, raw_research_json,
                    has_live_product, has_paid_customers, is_agentic_ai,
                    tech_stack, product_type, traction,
                    funding_round, funding_amount, funding_investors, funding_date,
                    citations_json, company_report or None,
                    str(existing["id"]),
                ))
                return str(existing["id"])
            else:
                row = conn.execute("""
                    INSERT INTO research_v2
                        (company_id, problem_statement, solution_summary,
                         knowledge_state, hiring_signals_json,
                         alignment_notes, outreach_angle, company_founding_story,
                         raw_research_json, has_live_product, has_paid_customers,
                         is_agentic_ai, tech_stack, product_type, traction,
                         funding_round, funding_amount, funding_investors, funding_date,
                         citations_json, company_report)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    RETURNING id
                """, (
                    company_id, problem_statement, solution_summary,
                    json.dumps(knowledge_state), json.dumps(hiring_signals),
                    alignment_notes or None, outreach_angle or None,
                    company_founding_story or None, raw_research_json,
                    has_live_product, has_paid_customers, is_agentic_ai,
                    tech_stack, product_type, traction,
                    funding_round, funding_amount, funding_investors, funding_date,
                    citations_json, company_report or None,
                )).fetchone()
                return str(row["id"])
    except Exception as e:
        logger.warning("Failed to persist research for company_id=%s: %s", company_id, e)
        return None


def _upsert_founder(conn, company_id: str, founder: dict) -> Optional[str]:
    """Upsert into founders_v2 from a FounderInfo dict. Returns founder_id (UUID) or None."""
    name = (founder.get("name") or "").strip()
    if not name:
        return None
    linkedin_url = founder.get("linkedin_url") or None
    role         = founder.get("role") or None
    bio          = founder.get("bio") or None
    motivation   = founder.get("personal_motivation") or None
    prior_cos    = json.dumps(founder["prior_companies"]) if founder.get("prior_companies") else None
    id_conf      = founder.get("identification_confidence") or "medium"
    out_conf     = "high" if (role or "").upper() in ("CEO", "CTO", "FOUNDER", "CO-FOUNDER") else "medium"

    try:
        if linkedin_url:
            row = conn.execute("""
                INSERT INTO founders_v2
                    (company_id, name, founder_role_type, linkedin_url, bio,
                     personal_motivation, prior_companies,
                     identification_confidence, outreach_confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (company_id, linkedin_url) DO UPDATE
                    SET name                    = EXCLUDED.name,
                        founder_role_type       = COALESCE(EXCLUDED.founder_role_type, founders_v2.founder_role_type),
                        bio                     = COALESCE(EXCLUDED.bio, founders_v2.bio),
                        personal_motivation     = COALESCE(EXCLUDED.personal_motivation, founders_v2.personal_motivation),
                        prior_companies         = COALESCE(EXCLUDED.prior_companies, founders_v2.prior_companies),
                        identification_confidence = COALESCE(EXCLUDED.identification_confidence, founders_v2.identification_confidence),
                        outreach_confidence     = COALESCE(EXCLUDED.outreach_confidence, founders_v2.outreach_confidence)
                RETURNING id
            """, (company_id, name, role, linkedin_url, bio, motivation,
                  prior_cos, id_conf, out_conf)).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM founders_v2 WHERE company_id = %s AND LOWER(name) = LOWER(%s)",
                (company_id, name),
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE founders_v2
                    SET bio                     = COALESCE(%s, bio),
                        personal_motivation     = COALESCE(%s, personal_motivation),
                        prior_companies         = COALESCE(%s::jsonb, prior_companies),
                        identification_confidence = COALESCE(%s, identification_confidence),
                        outreach_confidence     = COALESCE(%s, outreach_confidence)
                    WHERE id = %s
                """, (bio, motivation, prior_cos, id_conf, out_conf, str(existing["id"])))
                return str(existing["id"])
            row = conn.execute("""
                INSERT INTO founders_v2
                    (company_id, name, founder_role_type, bio, personal_motivation,
                     prior_companies, identification_confidence, outreach_confidence)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                RETURNING id
            """, (company_id, name, role, bio, motivation,
                  prior_cos, id_conf, out_conf)).fetchone()
        return str(row["id"]) if row else None
    except Exception as e:
        logger.warning("Failed to upsert founder '%s' for company_id=%s: %s", name, company_id, e)
        return None


def persist_drafts(company_id: str, state: dict) -> list[str]:
    """Insert outreach_v2 rows for each draft. Returns list of outreach UUIDs."""
    from tools.db_conn import get_conn
    draft_output = state.get("draft_output") or []
    if not draft_output:
        return []

    leverage         = state.get("leverage_output") or {}
    hiring_signals   = state.get("hiring_signals_found") or []
    top_signal       = json.dumps(hiring_signals[0]) if hiring_signals else None
    structured_founders = state.get("structured_founders") or []

    founder_lookup: dict[str, dict] = {}
    for f in structured_founders:
        key = (f.get("name") or "").strip().lower()
        if key:
            founder_lookup[key] = f

    outreach_ids: list[str] = []

    try:
        with get_conn() as conn:
            for draft in draft_output:
                founder_name = (draft.get("founder_name") or "").strip()
                message_mode = draft.get("message_mode", "")

                founder_info = founder_lookup.get(founder_name.lower()) or {
                    "name": founder_name,
                    "role": draft.get("founder_role", ""),
                }

                founder_id = _upsert_founder(conn, company_id, founder_info)
                if not founder_id:
                    logger.warning(
                        "Skipping draft for company_id=%s mode=%s — no founder name",
                        company_id, message_mode,
                    )
                    continue

                char_count = draft.get("char_count") if message_mode == "linkedin_invite" else None

                try:
                    row = conn.execute("""
                        INSERT INTO outreach_v2
                            (company_id, founder_id, channel, message_mode,
                             message_draft, status,
                             relevant_experience, leverage_statement, opening,
                             leverage_confidence, validation_status,
                             linkedin_invite_char_count, hiring_signal_used)
                        VALUES (%s, %s, 'linkedin', %s, %s, 'drafted', %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (company_id, founder_id, channel, message_mode)
                            WHERE founder_id IS NOT NULL
                        DO UPDATE SET
                            message_draft              = EXCLUDED.message_draft,
                            leverage_confidence        = EXCLUDED.leverage_confidence,
                            validation_status          = EXCLUDED.validation_status,
                            linkedin_invite_char_count = EXCLUDED.linkedin_invite_char_count,
                            hiring_signal_used         = COALESCE(EXCLUDED.hiring_signal_used, outreach_v2.hiring_signal_used)
                        RETURNING id
                    """, (
                        company_id, founder_id, message_mode,
                        draft.get("message_text", ""),
                        leverage.get("relevant_experience", ""),
                        leverage.get("leverage_statement", ""),
                        leverage.get("opening_question", ""),
                        draft.get("leverage_confidence", ""),
                        draft.get("validation_status", ""),
                        char_count, top_signal,
                    )).fetchone()
                    if row:
                        outreach_ids.append(str(row["id"]))
                except Exception as e:
                    logger.warning(
                        "Failed to persist draft for company_id=%s mode=%s: %s",
                        company_id, message_mode, e,
                    )
    except Exception as e:
        logger.warning("Failed to persist drafts for company_id=%s: %s", company_id, e)

    return outreach_ids


def persist_pipeline_run(state: dict) -> None:
    """Insert a pipeline_runs_v2 row at the start of a run."""
    from tools.db_conn import get_conn
    run_id   = state.get("run_id")
    run_type = state.get("run_type") or "unknown"
    if not run_id:
        return
    triggered_by = "manual" if state.get("candidate_pool") else "automatic"
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO pipeline_runs_v2 (id, run_type, scope, triggered_by, status, started_at)
                VALUES (%s, %s, 'all_companies', %s, 'running', now())
                ON CONFLICT (id) DO NOTHING
            """, (run_id, run_type, triggered_by))
    except Exception as e:
        logger.warning("Failed to create pipeline_runs_v2 row run_id=%s: %s", run_id, e)


def complete_pipeline_run(run_id: str, final_state: dict) -> None:
    """Update pipeline_runs_v2 with final counters and status after the graph finishes."""
    from tools.db_conn import get_conn
    if not run_id:
        return
    draft_output = final_state.get("draft_output") or []
    try:
        with get_conn() as conn:
            conn.execute("""
                UPDATE pipeline_runs_v2
                SET status            = 'completed',
                    ended_at          = now(),
                    total_sourced     = %s,
                    total_researched  = %s,
                    total_drafted     = %s,
                    total_cost_usd    = %s
                WHERE id = %s
            """, (
                len(final_state.get("candidate_pool") or []),
                final_state.get("companies_ready", 0),
                len(draft_output),
                final_state.get("daily_cost", 0.0),
                run_id,
            ))
    except Exception as e:
        logger.warning("Failed to complete pipeline_runs_v2 run_id=%s: %s", run_id, e)


def persist_scoring(company_id: str, state: dict) -> None:
    """Upsert full scoring rubric into scoring_v2."""
    from tools.db_conn import get_conn
    run_id      = state.get("run_id")
    tier        = state.get("hiring_tier")
    tier_reason = state.get("hiring_tier_reason") or ""
    if not run_id or tier is None:
        return
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO scoring_v2
                    (company_id, run_id, tier, tier_reason,
                     score_hiring, score_founder, score_product,
                     score_traction, score_recency, score_alignment,
                     total_score,
                     reasoning_hiring, reasoning_founder, reasoning_product,
                     reasoning_traction, reasoning_recency, reasoning_alignment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s)
                ON CONFLICT (company_id, run_id) DO UPDATE
                    SET tier              = EXCLUDED.tier,
                        tier_reason       = EXCLUDED.tier_reason,
                        score_hiring      = COALESCE(EXCLUDED.score_hiring, scoring_v2.score_hiring),
                        score_founder     = COALESCE(EXCLUDED.score_founder, scoring_v2.score_founder),
                        score_product     = COALESCE(EXCLUDED.score_product, scoring_v2.score_product),
                        score_traction    = COALESCE(EXCLUDED.score_traction, scoring_v2.score_traction),
                        score_recency     = COALESCE(EXCLUDED.score_recency, scoring_v2.score_recency),
                        score_alignment   = COALESCE(EXCLUDED.score_alignment, scoring_v2.score_alignment),
                        total_score       = COALESCE(EXCLUDED.total_score, scoring_v2.total_score),
                        reasoning_hiring  = COALESCE(EXCLUDED.reasoning_hiring, scoring_v2.reasoning_hiring),
                        reasoning_founder = COALESCE(EXCLUDED.reasoning_founder, scoring_v2.reasoning_founder),
                        reasoning_product = COALESCE(EXCLUDED.reasoning_product, scoring_v2.reasoning_product),
                        reasoning_traction= COALESCE(EXCLUDED.reasoning_traction, scoring_v2.reasoning_traction),
                        reasoning_recency = COALESCE(EXCLUDED.reasoning_recency, scoring_v2.reasoning_recency),
                        reasoning_alignment=COALESCE(EXCLUDED.reasoning_alignment, scoring_v2.reasoning_alignment)
            """, (
                company_id, run_id, tier, tier_reason,
                state.get("score_hiring"), state.get("score_founder"),
                state.get("score_product"), state.get("score_traction"),
                state.get("score_recency"), state.get("score_alignment"),
                state.get("total_score"),
                state.get("reasoning_hiring"), state.get("reasoning_founder"),
                state.get("reasoning_product"), state.get("reasoning_traction"),
                state.get("reasoning_recency"), state.get("reasoning_alignment"),
            ))
    except Exception as e:
        logger.warning("Failed to persist scoring for company_id=%s: %s", company_id, e)


def persist_cost_log(
    run_id: str,
    stage: str,
    company_id: Optional[str],
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    """Write one row to cost_log_v2. Fire-and-forget."""
    from tools.db_conn import get_conn
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO cost_log_v2
                    (run_id, company_id, stage, model, input_tokens, output_tokens, cost_usd)
                VALUES (%s, %s::uuid, %s, %s, %s, %s, %s)
            """, (run_id, company_id or None, stage, model, input_tokens, output_tokens, cost_usd))
    except Exception as e:
        logger.warning("Failed to write cost_log_v2 run_id=%s: %s", run_id, e)


def persist_pipeline_stage(
    run_id: str,
    stage_name: str,
    status: str,
    companies_total: int = 0,
    companies_done: int = 0,
    error_summary: Optional[str] = None,
    started_at=None,
) -> None:
    """Upsert a row in pipeline_run_stages_v2. Fire-and-forget."""
    from tools.db_conn import get_conn
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO pipeline_run_stages_v2
                    (run_id, stage_name, status, companies_total, companies_done,
                     error_summary, started_at, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s,
                        COALESCE(%s, now()),
                        CASE WHEN %s IN ('completed','failed') THEN now() ELSE NULL END)
                ON CONFLICT (run_id, stage_name) DO UPDATE
                    SET status          = EXCLUDED.status,
                        companies_total = EXCLUDED.companies_total,
                        companies_done  = EXCLUDED.companies_done,
                        error_summary   = COALESCE(EXCLUDED.error_summary, pipeline_run_stages_v2.error_summary),
                        completed_at    = CASE WHEN EXCLUDED.status IN ('completed','failed') THEN now()
                                               ELSE pipeline_run_stages_v2.completed_at END
            """, (run_id, stage_name, status, companies_total, companies_done,
                  error_summary, started_at, status))
    except Exception as e:
        logger.warning("Failed to write pipeline_run_stages_v2 run_id=%s stage=%s: %s", run_id, stage_name, e)


def persist_source(
    company_id: str,
    source_name: str,
    source_url: Optional[str],
    scrape_strategy: Optional[str],
    recon_result: Optional[dict] = None,
    raw_markdown: Optional[str] = None,
    citations: Optional[list] = None,
    tool_log: Optional[list] = None,
) -> None:
    """Write one sources_v2 row. Marks previous row for same source as not-latest. Fire-and-forget."""
    from tools.db_conn import get_conn
    try:
        with get_conn() as conn:
            conn.execute("""
                UPDATE sources_v2 SET is_latest = FALSE
                WHERE company_id = %s AND source_name = %s AND is_latest = TRUE
            """, (company_id, source_name))
            conn.execute("""
                INSERT INTO sources_v2
                    (company_id, source_name, source_url, scrape_strategy,
                     is_latest, recon_result, raw_markdown, citations_json, tool_log_json)
                VALUES (%s, %s, %s, %s, TRUE, %s::jsonb, %s, %s::jsonb, %s::jsonb)
            """, (
                company_id, source_name, source_url, scrape_strategy,
                json.dumps(recon_result) if recon_result else None,
                raw_markdown,
                json.dumps(citations) if citations else None,
                json.dumps(tool_log) if tool_log else None,
            ))
    except Exception as e:
        logger.warning("Failed to persist source company_id=%s source=%s: %s", company_id, source_name, e)
