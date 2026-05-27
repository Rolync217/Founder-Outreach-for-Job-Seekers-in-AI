"""
tools/event_logger.py
Structured event logging for the pipeline.

All functions are fire-and-forget — they never raise.
They no-op when run_id is falsy (None / "") so backward-compat
with standalone agent runs is automatic.

Usage:
    from tools.event_logger import (
        log_company_event, log_pipeline_run, log_debug,
        Stage, Decision, Confidence,
    )
"""
import logging
from typing import Optional

import psycopg2.errors
import psycopg2.extras

from tools.config_loader import cfg
from tools.db_conn import get_conn

_log = logging.getLogger("event_logger")

_EVIDENCE_MAX = 500
_DEBUG_MAX    = 2000

# Per-process guard: tracks which observability tables have already emitted
# their one "table unavailable" warning. CPython's GIL makes set.add()
# effectively atomic for simple in-process use, so no explicit lock needed.
_warned_tables: set[str] = set()

# Errors that indicate the observability table is simply not available
# (privilege gap or table not yet created). These degrade quietly after
# the first warning; all other exceptions keep warning unconditionally.
_TABLE_UNAVAILABLE = (
    psycopg2.errors.UndefinedTable,        # relation does not exist  (42P01)
    psycopg2.errors.InsufficientPrivilege, # missing INSERT/SELECT grant (42501)
)


def _warn_once(table: str, exc: Exception) -> None:
    """Emit one warning per table for availability failures; suppress repeats.

    For unexpected errors (not privilege / missing table) the warning always
    fires so genuine defects are not hidden.
    """
    if isinstance(exc, _TABLE_UNAVAILABLE):
        if table not in _warned_tables:
            _warned_tables.add(table)
            _log.warning(
                "[event_logger] %s unavailable (%s: %s). "
                "Structured event logging disabled for this table until process restart. "
                "Subsequent failures suppressed.",
                table, type(exc).__name__, exc,
            )
        # else: silently suppress — table is known-unavailable
    else:
        _log.warning("[event_logger] %s write failed (unexpected): %s", table, exc)


# ---------------------------------------------------------------------------
# Constants — use these everywhere to avoid free-text inconsistency
# ---------------------------------------------------------------------------

class Stage:
    SOURCING  = "sourcing"
    FILTERING = "filtering"
    RESEARCH  = "research"
    DRAFTING  = "drafting"
    RECHECK   = "recheck"


class Decision:
    ADDED    = "added"
    PASSED   = "passed"
    REJECTED = "rejected"
    REQUEUED = "requeued"
    DRAFTED  = "drafted"
    SKIPPED  = "skipped"
    ERROR    = "error"


class Confidence:
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


# ---------------------------------------------------------------------------
# Production logging
# ---------------------------------------------------------------------------

def log_company_event(
    run_id: str,
    company_id: Optional[str],
    company_name: str,
    stage_name: str,
    decision: str,
    *,
    source_name: str = None,
    tool_name: str = None,
    status_before: str = None,
    status_after: str = None,
    reason_code: str = None,
    evidence_summary: str = None,
    confidence: str = None,
    next_action: str = None,
    next_action_code: str = None,
    duration_ms: int = None,
    event_metadata: dict = None,
    error_summary: str = None,
) -> None:
    """Write one company decision event. No-op when run_id is falsy."""
    if not run_id:
        return
    try:
        ev = evidence_summary[:_EVIDENCE_MAX] if evidence_summary else None
        meta = psycopg2.extras.Json(event_metadata) if event_metadata else None
        with get_conn() as conn:
            # decision, source_name, tool_name, next_action, next_action_code kept for caller compat; not in v2 schema
            conn.execute("""
                INSERT INTO company_events_v2
                    (run_id, company_id, stage_name,
                     status_before, status_after, triggered_by, reason_code,
                     evidence_summary, reasoning, confidence,
                     duration_ms, event_metadata, error_summary)
                VALUES
                    (%s, %s::uuid, %s, %s, %s, 'pipeline_run', %s, %s, %s, %s, %s, %s, %s)
            """, (
                run_id, company_id or None, stage_name,
                status_before, status_after, reason_code,
                ev, None, confidence,
                duration_ms, meta, error_summary,
            ))
    except Exception as e:
        _warn_once("company_events_v2", e)


def log_pipeline_run(run_id: str, run_date: str, **kwargs) -> None:
    """Deprecated: pipeline_runs_v2 is now written by db_persistence.persist_pipeline_run."""
    return


# ---------------------------------------------------------------------------
# Debug logging (off by default — controlled by config.yaml debug_mode)
# ---------------------------------------------------------------------------

def log_debug(
    run_id: str,
    stage_name: str,
    log_type: str,
    content: str,
    *,
    company_id: Optional[str] = None,
    company_name: str = None,
) -> None:
    """Write a verbose debug record. No-op unless debug_mode=true in config.yaml.

    debug_mode is read from the in-memory cfg dict at each call, so the check
    is not cached at module level. However, cfg itself is loaded once at process
    startup — changes to config.yaml require a process restart to take effect.
    """
    if not run_id:
        return
    if not cfg.get("pipeline", {}).get("debug_mode", False):
        return
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO debug_logs_v2
                    (run_id, company_id, stage_name, log_type, content)
                VALUES (%s, %s::uuid, %s, %s, %s)
            """, (
                run_id, company_id or None, stage_name, log_type,
                content[:_DEBUG_MAX] if content else None,
            ))
    except Exception as e:
        _warn_once("debug_logs_v2", e)
