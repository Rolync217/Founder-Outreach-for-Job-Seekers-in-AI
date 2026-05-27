-- migrations/001_v2_schema.sql
-- Creates all v2 tables, indexes, constraints, triggers, and FKs.
-- Run once against a fresh database:
--   psql $DATABASE_URL -f migrations/001_v2_schema.sql
-- Or via the helper:
--   python tools/migrate.py

-- ─── Helper function ─────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─── Tables ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.pipeline_runs_v2 (
    id                  text        NOT NULL,
    run_type            text        NOT NULL,
    scope               text        NOT NULL DEFAULT 'all_companies',
    company_ids         jsonb,
    triggered_by        text        NOT NULL DEFAULT 'automatic',
    prompt              text,
    status              text        NOT NULL DEFAULT 'running',
    total_sourced       integer     NOT NULL DEFAULT 0,
    total_researched    integer     NOT NULL DEFAULT 0,
    total_scored        integer     NOT NULL DEFAULT 0,
    total_drafted       integer     NOT NULL DEFAULT 0,
    total_sent          integer     NOT NULL DEFAULT 0,
    total_rejected      integer     NOT NULL DEFAULT 0,
    total_cost_usd      numeric     NOT NULL DEFAULT 0,
    error_summary       text,
    started_at          timestamptz,
    ended_at            timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.companies_v2 (
    id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
    name                text        NOT NULL,
    company_website     text,
    description         text,
    source              text,
    batch               text,
    founded_year        text,
    sector              text,
    stage               text,
    team_size           integer,
    location            text,
    status              text        NOT NULL DEFAULT 'unclassified',
    status_reason       text,
    sourcing_confidence integer,
    run_number          integer,
    last_processed_at   timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.sources_v2 (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    company_id      uuid        NOT NULL,
    source_name     text        NOT NULL,
    source_url      text,
    scrape_strategy text,
    is_latest       boolean     NOT NULL DEFAULT false,
    recon_result    jsonb,
    raw_markdown    text,
    citations_json  jsonb,
    tool_log_json   jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT latest_source_must_have_url CHECK ((is_latest = false) OR (source_url IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS public.research_v2 (
    id                      uuid        NOT NULL DEFAULT gen_random_uuid(),
    company_id              uuid        NOT NULL,
    problem_statement       text,
    solution_summary        text,
    company_founding_story  text,
    traction                text,
    product_type            text,
    has_live_product        boolean,
    has_paid_customers      boolean,
    is_agentic_ai           boolean,
    tech_stack              text,
    alignment_notes         text,
    outreach_angle          text,
    funding_round           text,
    funding_amount          text,
    funding_investors       text,
    funding_date            text,
    hiring_signals_json     jsonb       NOT NULL DEFAULT '[]',
    knowledge_state         jsonb       NOT NULL DEFAULT '{}',
    company_report          text,
    raw_research_json       jsonb,
    citations_json          jsonb,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.founders_v2 (
    id                          uuid        NOT NULL DEFAULT gen_random_uuid(),
    company_id                  uuid        NOT NULL,
    name                        text        NOT NULL,
    founder_role_type           text,
    bio                         text,
    personal_motivation         text,
    prior_companies             jsonb,
    identification_confidence   text,
    outreach_confidence         text,
    linkedin_url                text,
    email                       text,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.contacts_v2 (
    id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
    company_id          uuid        NOT NULL,
    name                text        NOT NULL,
    role                text,
    bio                 text,
    outreach_confidence text,
    linkedin_url        text,
    email               text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.scoring_v2 (
    id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
    company_id          uuid        NOT NULL,
    run_id              text        NOT NULL,
    score_hiring        text,
    score_founder       text,
    score_product       text,
    score_traction      text,
    score_recency       text,
    score_alignment     text,
    reasoning_hiring    text,
    reasoning_founder   text,
    reasoning_product   text,
    reasoning_traction  text,
    reasoning_recency   text,
    reasoning_alignment text,
    total_score         text,
    tier                integer,
    tier_reason         text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.outreach_v2 (
    id                      uuid        NOT NULL DEFAULT gen_random_uuid(),
    company_id              uuid        NOT NULL,
    founder_id              uuid,
    contact_id              uuid,
    channel                 text        NOT NULL DEFAULT 'linkedin',
    message_draft           text,
    message_final           text,
    hiring_signal_used      jsonb,
    message_citations_json  jsonb,
    status                  text        NOT NULL DEFAULT 'drafted',
    sent_at                 timestamptz,
    reply_received          boolean     NOT NULL DEFAULT false,
    reply_received_at       timestamptz,
    reply_text              text,
    relevant_experience     text,
    leverage_statement      text,
    opening                 text,
    leverage_confidence     text,
    validation_status       text,
    snooze_until            timestamptz,
    is_deleted              boolean     NOT NULL DEFAULT false,
    deleted_at              timestamptz,
    skipped_at              timestamptz,
    message_mode            text,
    linkedin_invite_char_count integer,
    created_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.follow_ups_v2 (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    outreach_id     uuid        NOT NULL,
    message_draft   text,
    message_final   text,
    scheduled_date  timestamptz,
    status          text        NOT NULL DEFAULT 'pending',
    sent_at         timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.pipeline_run_stages_v2 (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    run_id          text        NOT NULL,
    stage_name      text        NOT NULL,
    status          text        NOT NULL DEFAULT 'pending',
    companies_total integer     NOT NULL DEFAULT 0,
    companies_done  integer     NOT NULL DEFAULT 0,
    error_summary   text,
    started_at      timestamptz,
    completed_at    timestamptz,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.agent_decisions_v2 (
    id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
    run_id              text,
    company_id          uuid,
    node                text,
    decision            text,
    confidence          text,
    reasoning           text,
    next_action         text,
    evidence            jsonb,
    negative_evidence   jsonb,
    ambiguities         jsonb,
    node_specific       jsonb,
    iteration_number    integer,
    was_redirected      boolean,
    redirect_reason     text,
    model_used          text,
    input_tokens        integer,
    output_tokens       integer,
    cost_usd            numeric,
    call_type           text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.cost_log_v2 (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    run_id          text,
    company_id      uuid,
    stage           text,
    model           text,
    input_tokens    integer,
    output_tokens   integer,
    cost_usd        numeric,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.company_events_v2 (
    id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
    run_id              text,
    company_id          uuid        NOT NULL,
    stage_name          text,
    status_before       text,
    status_after        text,
    triggered_by        text,
    reason_code         text,
    evidence_summary    text,
    reasoning           text,
    confidence          text,
    duration_ms         integer,
    event_metadata      jsonb,
    error_summary       text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.regen_events_v2 (
    id                          uuid        NOT NULL DEFAULT gen_random_uuid(),
    outreach_id                 uuid        NOT NULL,
    company_id                  uuid,
    message_mode                text,
    user_prompt                 text,
    user_prompt_normalized      text,
    original_message            text,
    regenerated_message         text,
    status_before               text,
    status_after                text,
    char_count_before           integer,
    char_count_after            integer,
    model_used                  text,
    cost_usd                    numeric,
    attempt_no                  integer,
    failure_reason              text,
    latency_ms                  integer,
    prompt_template_version     text,
    outcome                     text,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.debug_logs_v2 (
    id          uuid        NOT NULL DEFAULT gen_random_uuid(),
    run_id      text,
    company_id  uuid,
    stage_name  text,
    log_type    text,
    content     text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

-- ─── Unique constraints ───────────────────────────────────────────────────────
-- Wrapped in DO blocks so the migration is idempotent on Postgres < 17,
-- which does not support ADD CONSTRAINT IF NOT EXISTS.

DO $$ BEGIN
    ALTER TABLE public.research_v2
        ADD CONSTRAINT research_v2_company_id_key UNIQUE (company_id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.founders_v2
        ADD CONSTRAINT founders_v2_company_id_linkedin_url_key UNIQUE (company_id, linkedin_url);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.contacts_v2
        ADD CONSTRAINT contacts_v2_company_id_linkedin_url_key UNIQUE (company_id, linkedin_url);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.scoring_v2
        ADD CONSTRAINT scoring_v2_company_id_run_id_key UNIQUE (company_id, run_id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.pipeline_run_stages_v2
        ADD CONSTRAINT pipeline_run_stages_v2_run_id_stage_name_key UNIQUE (run_id, stage_name);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.follow_ups_v2
        ADD CONSTRAINT unique_followup_per_date UNIQUE (outreach_id, scheduled_date);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.regen_events_v2
        ADD CONSTRAINT unique_regen_attempt UNIQUE (outreach_id, attempt_no);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

-- ─── Indexes ──────────────────────────────────────────────────────────────────

-- companies_v2
CREATE UNIQUE INDEX IF NOT EXISTS companies_v2_website_unique
    ON public.companies_v2 (company_website) WHERE (company_website IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_companies_v2_status  ON public.companies_v2 (status);
CREATE INDEX IF NOT EXISTS idx_companies_v2_source  ON public.companies_v2 (source);
CREATE INDEX IF NOT EXISTS idx_companies_v2_run     ON public.companies_v2 (run_number);
CREATE INDEX IF NOT EXISTS idx_companies_v2_website ON public.companies_v2 (company_website);

-- sources_v2
CREATE INDEX IF NOT EXISTS idx_sources_v2_company ON public.sources_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_sources_v2_latest  ON public.sources_v2 (company_id, is_latest);
CREATE INDEX IF NOT EXISTS idx_sources_v2_source  ON public.sources_v2 (source_name);
CREATE UNIQUE INDEX IF NOT EXISTS unique_latest_source
    ON public.sources_v2 (company_id, source_name) WHERE (is_latest = true);

-- research_v2
CREATE INDEX IF NOT EXISTS idx_research_v2_company     ON public.research_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_research_v2_agentic     ON public.research_v2 (is_agentic_ai);
CREATE INDEX IF NOT EXISTS idx_research_v2_live_product ON public.research_v2 (has_live_product);
CREATE INDEX IF NOT EXISTS idx_research_v2_hiring      ON public.research_v2 USING gin (hiring_signals_json);

-- founders_v2 / contacts_v2
CREATE INDEX IF NOT EXISTS idx_founders_v2_company  ON public.founders_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_founders_v2_linkedin ON public.founders_v2 (linkedin_url);
CREATE INDEX IF NOT EXISTS idx_contacts_v2_company  ON public.contacts_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_v2_linkedin ON public.contacts_v2 (linkedin_url);

-- scoring_v2
CREATE INDEX IF NOT EXISTS idx_scoring_v2_company ON public.scoring_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_scoring_v2_run     ON public.scoring_v2 (run_id);
CREATE INDEX IF NOT EXISTS idx_scoring_v2_tier    ON public.scoring_v2 (tier);
CREATE INDEX IF NOT EXISTS idx_scoring_v2_total   ON public.scoring_v2 (total_score);

-- outreach_v2
CREATE INDEX IF NOT EXISTS idx_outreach_v2_company ON public.outreach_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_outreach_v2_founder ON public.outreach_v2 (founder_id);
CREATE INDEX IF NOT EXISTS idx_outreach_v2_contact ON public.outreach_v2 (contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_v2_status  ON public.outreach_v2 (status);
CREATE INDEX IF NOT EXISTS idx_outreach_v2_sent    ON public.outreach_v2 (sent_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS unique_outreach_founder
    ON public.outreach_v2 (company_id, founder_id, channel, message_mode)
    WHERE (founder_id IS NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS unique_outreach_contact
    ON public.outreach_v2 (company_id, contact_id, channel, message_mode)
    WHERE (contact_id IS NOT NULL);

-- follow_ups_v2
CREATE INDEX IF NOT EXISTS idx_follow_ups_v2_outreach  ON public.follow_ups_v2 (outreach_id);
CREATE INDEX IF NOT EXISTS idx_follow_ups_v2_status    ON public.follow_ups_v2 (status);
CREATE INDEX IF NOT EXISTS idx_follow_ups_v2_scheduled ON public.follow_ups_v2 (scheduled_date);

-- pipeline_runs_v2 / pipeline_run_stages_v2
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_v2_status   ON public.pipeline_runs_v2 (status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_v2_run_type ON public.pipeline_runs_v2 (run_type);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_v2_created  ON public.pipeline_runs_v2 (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_stages_v2_run         ON public.pipeline_run_stages_v2 (run_id);
CREATE INDEX IF NOT EXISTS idx_run_stages_v2_status      ON public.pipeline_run_stages_v2 (status);

-- agent_decisions_v2
CREATE INDEX IF NOT EXISTS idx_agent_decisions_v2_company ON public.agent_decisions_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_v2_run     ON public.agent_decisions_v2 (run_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_v2_node    ON public.agent_decisions_v2 (node);

-- cost_log_v2
CREATE INDEX IF NOT EXISTS idx_cost_log_v2_company  ON public.cost_log_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_cost_log_v2_run      ON public.cost_log_v2 (run_id);
CREATE INDEX IF NOT EXISTS idx_cost_log_v2_stage    ON public.cost_log_v2 (stage);
CREATE INDEX IF NOT EXISTS idx_cost_log_v2_created  ON public.cost_log_v2 (created_at DESC);

-- company_events_v2
CREATE INDEX IF NOT EXISTS idx_company_events_v2_company ON public.company_events_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_company_events_v2_run     ON public.company_events_v2 (run_id);
CREATE INDEX IF NOT EXISTS idx_company_events_v2_status  ON public.company_events_v2 (status_after);
CREATE INDEX IF NOT EXISTS idx_company_events_v2_created ON public.company_events_v2 (created_at DESC);

-- regen_events_v2
CREATE INDEX IF NOT EXISTS idx_regen_events_v2_outreach ON public.regen_events_v2 (outreach_id);
CREATE INDEX IF NOT EXISTS idx_regen_events_v2_company  ON public.regen_events_v2 (company_id);

-- debug_logs_v2
CREATE INDEX IF NOT EXISTS idx_debug_logs_v2_company ON public.debug_logs_v2 (company_id);
CREATE INDEX IF NOT EXISTS idx_debug_logs_v2_run     ON public.debug_logs_v2 (run_id);

-- ─── Foreign keys ─────────────────────────────────────────────────────────────

DO $$ BEGIN
    ALTER TABLE public.sources_v2
        ADD CONSTRAINT sources_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.research_v2
        ADD CONSTRAINT research_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.founders_v2
        ADD CONSTRAINT founders_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.contacts_v2
        ADD CONSTRAINT contacts_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.scoring_v2
        ADD CONSTRAINT scoring_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.scoring_v2
        ADD CONSTRAINT scoring_v2_run_id_fkey
        FOREIGN KEY (run_id) REFERENCES public.pipeline_runs_v2(id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.outreach_v2
        ADD CONSTRAINT outreach_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.outreach_v2
        ADD CONSTRAINT outreach_v2_founder_id_fkey
        FOREIGN KEY (founder_id) REFERENCES public.founders_v2(id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.outreach_v2
        ADD CONSTRAINT outreach_v2_contact_id_fkey
        FOREIGN KEY (contact_id) REFERENCES public.contacts_v2(id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.follow_ups_v2
        ADD CONSTRAINT follow_ups_v2_outreach_id_fkey
        FOREIGN KEY (outreach_id) REFERENCES public.outreach_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.pipeline_run_stages_v2
        ADD CONSTRAINT pipeline_run_stages_v2_run_id_fkey
        FOREIGN KEY (run_id) REFERENCES public.pipeline_runs_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.agent_decisions_v2
        ADD CONSTRAINT agent_decisions_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.agent_decisions_v2
        ADD CONSTRAINT agent_decisions_v2_run_id_fkey
        FOREIGN KEY (run_id) REFERENCES public.pipeline_runs_v2(id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.cost_log_v2
        ADD CONSTRAINT cost_log_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.cost_log_v2
        ADD CONSTRAINT cost_log_v2_run_id_fkey
        FOREIGN KEY (run_id) REFERENCES public.pipeline_runs_v2(id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.company_events_v2
        ADD CONSTRAINT company_events_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.company_events_v2
        ADD CONSTRAINT company_events_v2_run_id_fkey
        FOREIGN KEY (run_id) REFERENCES public.pipeline_runs_v2(id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.regen_events_v2
        ADD CONSTRAINT regen_events_v2_outreach_id_fkey
        FOREIGN KEY (outreach_id) REFERENCES public.outreach_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.regen_events_v2
        ADD CONSTRAINT regen_events_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.debug_logs_v2
        ADD CONSTRAINT debug_logs_v2_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies_v2(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.debug_logs_v2
        ADD CONSTRAINT debug_logs_v2_run_id_fkey
        FOREIGN KEY (run_id) REFERENCES public.pipeline_runs_v2(id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

-- ─── Triggers ─────────────────────────────────────────────────────────────────

DROP TRIGGER IF EXISTS trg_companies_v2_updated_at ON public.companies_v2;
CREATE TRIGGER trg_companies_v2_updated_at
    BEFORE UPDATE ON public.companies_v2
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_research_v2_updated_at ON public.research_v2;
CREATE TRIGGER trg_research_v2_updated_at
    BEFORE UPDATE ON public.research_v2
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
