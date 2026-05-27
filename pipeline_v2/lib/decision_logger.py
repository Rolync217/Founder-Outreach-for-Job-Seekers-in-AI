import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from tools.db_conn import get_conn

_PENDING_LOG = Path(__file__).parent.parent.parent / ".tmp" / "pending_decisions.jsonl"

_log = logging.getLogger("decision_logger")
_DEV_LOG_DIR = Path(__file__).parent.parent.parent / ".tmp"


def _make_evidence_item(
    evidence_text: str,
    source_name: str = "",
    source_url: str = "",
    signal_type: str = "",
) -> dict:
    return {
        "evidence_text": evidence_text,
        "source_name": source_name,
        "source_url": source_url,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "signal_type": signal_type,
    }


def _write_dev_log(
    run_id: str,
    company_name: str,
    node: str,
    call_type: str | None,
    model_used: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    decision: str,
    reasoning: str,
    node_specific: dict | None,
) -> None:
    """Append one row to .tmp/dev_log_<run_id>.md for local visibility."""
    try:
        _DEV_LOG_DIR.mkdir(exist_ok=True)
        path = _DEV_LOG_DIR / f"dev_log_{run_id[:8]}.md"
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

        # Write header on first call
        if not path.exists():
            path.write_text(
                f"# Dev Log — run {run_id}\n\n"
                f"| time | company | node | call_type | model | in_tok | out_tok |"
                f" decision | reasoning | node_specific |\n"
                f"|------|---------|------|-----------|-------|--------|---------|"
                f"----------|-----------|---------------|\n"
            )

        # Truncate long fields so the table stays readable
        def _trunc(s: str, n: int = 120) -> str:
            s = str(s).replace("|", "\\|").replace("\n", " ")
            return s[:n] + "…" if len(s) > n else s

        ns_str = _trunc(json.dumps(node_specific or {}), 200)
        path.open("a").write(
            f"| {ts} | {company_name} | {node} | {call_type or ''} |"
            f" {model_used or ''} | {input_tokens or ''} | {output_tokens or ''} |"
            f" {_trunc(decision)} | {_trunc(reasoning)} | {ns_str} |\n"
        )
    except Exception as e:
        _log.warning("Failed to write dev log: %s", e)


def _write_pending(
    run_id, company_id, company_name, node, decision,
    confidence, reasoning, next_action,
    evidence, negative_evidence, ambiguities, node_specific,
    iteration_number, was_redirected, redirect_reason,
    model_used, input_tokens, output_tokens, call_type,
) -> None:
    """Append full decision record to .tmp/pending_decisions.jsonl for later flush."""
    try:
        _PENDING_LOG.parent.mkdir(exist_ok=True)
        record = {
            "run_id": run_id, "company_id": company_id, "company_name": company_name,
            "node": node, "decision": decision, "confidence": confidence,
            "reasoning": reasoning, "next_action": next_action,
            "evidence": evidence or [], "negative_evidence": negative_evidence or [],
            "ambiguities": ambiguities or [], "node_specific": node_specific or {},
            "iteration_number": iteration_number, "was_redirected": was_redirected,
            "redirect_reason": redirect_reason, "model_used": model_used,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "call_type": call_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with _PENDING_LOG.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        _log.warning("Failed to write pending decision: %s", e)


def log_decision(
    run_id: str,
    company_id: str | None,
    company_name: str,
    node: str,
    decision: str,
    confidence: str,
    reasoning: str,
    next_action: str,
    evidence: list[dict] | None = None,
    negative_evidence: list[dict] | None = None,
    ambiguities: list[str] | None = None,
    node_specific: dict | None = None,
    iteration_number: int | None = None,
    was_redirected: bool | None = None,
    redirect_reason: str | None = None,
    model_used: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    call_type: str | None = None,
) -> str | None:
    """
    evidence and negative_evidence are lists of EvidenceItem dicts (from _make_evidence_item).
    For backward compatibility, plain strings are also accepted and auto-wrapped.
    Always writes to .tmp/dev_log_<run_id>.md for local visibility.
    """
    def _normalize(items):
        if not items:
            return []
        result = []
        for item in items:
            if isinstance(item, str):
                result.append(_make_evidence_item(item))
            else:
                result.append(item)
        return result

    # Always write local dev log regardless of DB status
    _write_dev_log(run_id, company_name, node, call_type, model_used,
                   input_tokens, output_tokens, decision, reasoning, node_specific)

    try:
        with get_conn() as conn:
            row = conn.execute("""
                INSERT INTO agent_decisions_v2
                    (run_id, company_id, node, decision,
                     confidence, reasoning, next_action,
                     evidence, negative_evidence, ambiguities, node_specific,
                     iteration_number, was_redirected, redirect_reason,
                     model_used, input_tokens, output_tokens, call_type)
                VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                run_id, company_id, node, decision,
                confidence, reasoning, next_action,
                json.dumps(_normalize(evidence)),
                json.dumps(_normalize(negative_evidence)),
                json.dumps(ambiguities or []),
                json.dumps(node_specific or {}),
                iteration_number, was_redirected, redirect_reason,
                model_used, input_tokens, output_tokens, call_type,
            )).fetchone()
            return row["id"]
    except Exception as e:
        _log.error(
            "Failed to log decision to DB — saved to pending_decisions.jsonl",
            extra={
                "run_id": run_id, "company_name": company_name,
                "node": node, "decision": decision, "error": str(e)
            },
            exc_info=True,
        )
        _write_pending(
            run_id, company_id, company_name, node, decision,
            confidence, reasoning, next_action,
            evidence, negative_evidence, ambiguities, node_specific,
            iteration_number, was_redirected, redirect_reason,
            model_used, input_tokens, output_tokens, call_type,
        )
        return None


def get_decisions_for_company_id(company_id: str) -> list[dict]:
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM agent_decisions_v2
            WHERE company_id = %s::uuid
            ORDER BY created_at DESC
        """, (company_id,)).fetchall()


def get_decisions_for_run(run_id: str) -> list[dict]:
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM agent_decisions_v2
            WHERE run_id = %s
            ORDER BY created_at ASC
        """, (run_id,)).fetchall()
