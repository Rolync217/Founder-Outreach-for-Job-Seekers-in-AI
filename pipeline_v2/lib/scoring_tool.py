"""
Pure-Python scoring math. This module is registered as a Claude tool so the LLM
assigns qualitative labels (strong/good/weak/missing) and this code does the math.
No LLM calls here — only deterministic computation.

Weights and tier thresholds are loaded from skills/search_scope.yaml at runtime
via scope_loader. Edit the yaml to change scoring behavior — no code changes needed.
"""

from pipeline_v2.lib.scope_loader import get_scoring_weights, get_tier_thresholds

_LABEL_POINTS: dict[str, int] = {"strong": 3, "good": 2, "weak": 1, "missing": 0}


def compute_score(
    score_hiring: str,
    score_founder: str,
    score_product: str,
    score_traction: str,
    score_recency: str,
    score_alignment: str,
) -> dict:
    """
    Compute total_score label and tier from per-dimension labels.

    Args: each score is one of: "strong" | "good" | "weak" | "missing"
    Returns: {"total_score": str, "tier": int, "raw_score": int, "max_score": int}
    """
    weights = get_scoring_weights()
    thresholds = get_tier_thresholds()

    scores = {
        "hiring":    score_hiring,
        "traction":  score_traction,
        "founder":   score_founder,
        "product":   score_product,
        "alignment": score_alignment,
        "recency":   score_recency,
    }
    raw = sum(
        _LABEL_POINTS.get(scores.get(dim, "missing"), 0) * weight
        for dim, weight in weights.items()
    )
    max_score = sum(3 * w for w in weights.values())
    fraction = raw / max_score if max_score else 0.0

    for threshold, tier, label in thresholds:
        if fraction >= threshold:
            return {"total_score": label, "tier": tier, "raw_score": raw, "max_score": max_score}
    return {"total_score": "weak", "tier": 4, "raw_score": raw, "max_score": max_score}


SCORING_TOOL_DEFINITION: dict = {
    "name": "compute_score",
    "description": (
        "Compute the numerical total_score and tier from your per-dimension quality labels. "
        "Call this ONCE after you have assessed all six dimensions. "
        "You assign the labels — this tool does the math."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "score_hiring":    {"type": "string", "enum": ["strong", "good", "weak", "missing"], "description": "How strong is the hiring signal for a relevant role?"},
            "score_founder":   {"type": "string", "enum": ["strong", "good", "weak", "missing"], "description": "How strong is the founder background and credibility?"},
            "score_product":   {"type": "string", "enum": ["strong", "good", "weak", "missing"], "description": "How strong is the product — live, paying customers, clear value?"},
            "score_traction":  {"type": "string", "enum": ["strong", "good", "weak", "missing"], "description": "How strong is the traction evidence — users, revenue, growth?"},
            "score_recency":   {"type": "string", "enum": ["strong", "good", "weak", "missing"], "description": "How recent is the company activity — funding, hiring, news?"},
            "score_alignment": {"type": "string", "enum": ["strong", "good", "weak", "missing"], "description": "How well does this opportunity align with the candidate's background?"},
        },
        "required": ["score_hiring", "score_founder", "score_product", "score_traction", "score_recency", "score_alignment"],
    },
}
