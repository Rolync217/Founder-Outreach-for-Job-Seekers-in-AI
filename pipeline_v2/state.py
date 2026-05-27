from typing import TypedDict, Optional


class KnowledgeDimension(TypedDict):
    status: str          # "unknown" | "partial" | "sufficient"
    summary: str
    source: str
    source_url: str      # URL where this data came from
    gap_reason: str
    confidence: str      # "high" | "medium" | "low"


class KnowledgeState(TypedDict):
    product_understanding: KnowledgeDimension
    founder_background: KnowledgeDimension
    work_alignment: KnowledgeDimension
    hiring_signal: KnowledgeDimension
    company_stage_and_size: KnowledgeDimension


class WorkAlignment(TypedDict):
    status: str
    is_user_facing_product: bool
    work_type: str
    would_user_touch: str
    alignment_confidence: str
    alignment_reason: str


class LeverageOutput(TypedDict):
    relevant_experience: str
    leverage_statement: str
    opening_question: str
    confidence: str


class DraftRecord(TypedDict):
    founder_name: str
    founder_role: str
    message_mode: str
    message_text: str
    char_count: int
    word_count: int
    leverage_confidence: str
    validation_status: str
    validation_failures: list[str]
    rewrite_iteration: int
    founder_critique: str  # founder-perspective critique; empty string if critique skipped


class HiringSignal(TypedDict, total=False):
    # Core fields — always present
    signal_text: str
    signal_type: str
    source: str
    source_url: str
    signal_recency_days: int
    url: str
    confirmed_from_url: str   # explicit page URL where signal was read (may equal source_url)
    # Social post provenance — present only for founder_posts / community_hiring_platforms
    poster_name: str | None
    poster_role: str | None
    post_platform: str | None   # linkedin | twitter | other
    post_date_raw: str | None


class EvidenceItem(TypedDict):
    evidence_text: str
    source_name: str
    source_url: str
    captured_at: str     # ISO timestamp
    signal_type: str     # optional, empty string if not applicable


class SourceAttempt(TypedDict):
    source_name: str
    attempted_at: str
    success: bool
    failure_reason: str  # empty if success
    entities_found: int  # for sourcing; dimensions updated for research


class DecisionLog(TypedDict):
    node: str
    decision: str
    confidence: str
    reasoning: str
    key_evidence: list[str]
    negative_evidence: list[str]
    ambiguities: list[str]
    next_action: str
    timestamp: str


class FounderInfo(TypedDict, total=False):
    name: str
    role: str               # CEO / CTO / co-founder / etc.
    linkedin_url: str
    bio: str                # career background
    personal_motivation: str
    prior_companies: list[dict]  # [{"company": "Google", "role": "SWE", "years": "2020-2022"}]
    identification_confidence: str  # high / medium / low


class StructuredCompany(TypedDict, total=False):
    has_live_product: bool
    has_paid_customers: bool
    is_agentic_ai: bool
    tech_stack: str
    product_type: str       # API / SaaS / platform / CLI / other
    traction: str
    funding_round: str      # seed / series_a / series_b / unknown
    funding_amount: str     # "$10M" or "undisclosed" or null
    funding_investors: str
    funding_date: str


class AgentState(TypedDict):
    # Pipeline level
    run_id: str                          # UUID for this pipeline run
    daily_target: int
    companies_ready: int
    daily_goal_met: bool
    run_date: str
    run_type: str                        # "daily_light" | "deep_run"
    last_completed_node: str             # explicit — never inferred

    # Sourcing
    candidate_pool: list[dict]           # each entry carries pool_origin, source_url
    sourcing_iterations: int
    entities_rejected_as_invalid: list[dict]

    # Per company (current)
    current_company: dict

    # Knowledge state
    knowledge_state: KnowledgeState
    knowledge_iterations: int
    knowledge_confidence: str            # "high" | "medium" | "low"
    research_retry_count: int
    research_search_history: list[dict]
    opus_synthesis: dict | None

    # Structured extractions from research (populated by opus synthesis)
    structured_company: StructuredCompany
    structured_founders: list  # list[FounderInfo]

    # Source tracking — explicit in state, not implicit
    fetched_sources: list[str]           # source names successfully fetched
    failed_sources: list[str]            # source names that failed
    source_attempt_log: list[SourceAttempt]          # research-stage attempt log
    sourcing_source_attempt_log: list[SourceAttempt]  # sourcing stage only

    # Hiring signal
    hiring_tier: Optional[int]           # 1-4
    hiring_tier_reason: str
    hiring_signals_found: list[HiringSignal]

    # Leverage
    leverage_output: LeverageOutput
    leverage_confidence: str

    # Drafting
    draft_output: list[DraftRecord]
    draft_iterations: int
    draft_retry_count: int
    validation_passed: bool
    validation_feedback: str

    # Supervisor
    supervisor_decision: str
    skip_reason: str

    # Evidence trail
    decision_log: list[DecisionLog]

    # Cost
    daily_cost: float
    cost_by_stage: dict[str, float]
