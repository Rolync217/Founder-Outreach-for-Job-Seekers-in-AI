import yaml
from functools import lru_cache
from pathlib import Path
from pipeline_v2.lib.scope_loader import get_dimension_priority

_SKILLS = Path(__file__).parent.parent.parent / "skills"

_COST_TIER_RANK = {"low": 0, "medium": 1, "high": 2}
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _validate_sources(sources: list[dict]) -> None:
    valid_dimensions = set(get_dimension_priority())
    for s in sources:
        name = s.get("source_name", "<unnamed>")
        for dim in s.get("signal_types_supported", []):
            if dim not in valid_dimensions:
                raise ValueError(
                    f"Source '{name}' has invalid signal_types_supported value '{dim}'. "
                    f"Valid dimensions: {sorted(valid_dimensions)}"
                )


def load_sources(require_enabled: bool = True) -> list[dict]:
    path = _SKILLS / "sources.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    all_sources = data.get("sources") or []
    enabled = [s for s in all_sources if s.get("enabled", True)]
    _validate_sources(enabled)
    if require_enabled and not enabled:
        raise ValueError(
            "sources.yaml has no enabled sources. "
            "The pipeline cannot run without at least one enabled source. "
            "Add sources to skills/sources.yaml before running."
        )
    return enabled


@lru_cache(maxsize=1)
def _load_priority_data() -> tuple[dict[str, int], dict[str, list[str]]]:
    """Load global source_priority_ranking and dimension_priority_overrides from sources.yaml.
    Returns (global_priority_rank, dimension_overrides).
    global_priority_rank: {source_name: int} lower = higher priority
    dimension_overrides: {dimension: [source_name, ...]} ordered highest to lowest priority
    """
    path = _SKILLS / "sources.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    global_block = (data or {}).get("global") or {}
    global_priority: dict[str, int] = global_block.get("source_priority_ranking") or {}
    dim_overrides: dict[str, list[str]] = global_block.get("dimension_priority_overrides") or {}
    return global_priority, dim_overrides


def sources_for_dimension(sources: list[dict], dimension: str) -> list[dict]:
    return [s for s in sources if dimension in s.get("signal_types_supported", [])]


def cheapest_for_dimension(
    sources: list[dict],
    dimension: str,
    fetched: set[str],
    run_type: str,
    light_categories: list[str],
) -> dict | None:
    available = [
        s for s in sources
        if dimension in s.get("signal_types_supported", [])
        and s["source_name"] not in fetched
        and (run_type == "deep_run" or s.get("source_category") in light_categories)
    ]
    if not available:
        return None

    global_priority, dim_overrides = _load_priority_data()
    override_order = dim_overrides.get(dimension, [])
    override_pos = {name: i for i, name in enumerate(override_order)}
    fallback_base = len(override_order)

    def _sort_key(s: dict) -> tuple:
        name = s["source_name"]
        cost = _COST_TIER_RANK.get(s.get("cost_tier", "medium"), 1)
        dim_pos = override_pos.get(name, fallback_base + global_priority.get(name, 999))
        conf = -_CONFIDENCE_RANK.get(s.get("confidence_weight", "low"), 0)  # negate: higher conf wins
        return (cost, dim_pos, conf)

    return min(available, key=_sort_key)


def _first_sentence(text: str) -> str:
    """Return the first sentence of a (possibly multi-line) string."""
    if not text:
        return ""
    flat = " ".join(text.split())
    end = flat.find(". ")
    return flat[: end + 1].strip() if end != -1 else flat.strip()


def _build_sources_compact_summary_inner() -> str:
    path = _SKILLS / "sources.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)

    sources = [s for s in (data.get("sources") or []) if s.get("enabled", True)]
    global_block = (data or {}).get("global") or {}

    lines: list[str] = ["## Available Sources\n"]
    for s in sources:
        name = s.get("source_name", "")
        dims = ", ".join(s.get("signal_types_supported") or [])
        cost = s.get("cost_tier", "medium")
        use = _first_sentence(s.get("when_to_use", ""))
        failures_raw = s.get("common_failure_modes") or []
        failure_names = [str(f).split("#")[0].strip() for f in failures_raw]
        failures = ", ".join(failure_names)
        lines.append(f"[{name}] dims={dims} cost={cost}")
        if use:
            lines.append(f"  use: {use}")
        if failures:
            lines.append(f"  failures: {failures}")
        lines.append("")

    # Dimension completion criteria (full)
    dcc = global_block.get("dimension_completion_criteria")
    if dcc:
        lines.append("## dimension_completion_criteria\n")
        lines.append(yaml.dump(dcc, default_flow_style=False))

    # Early exit rules (full)
    eer = global_block.get("early_exit_rules")
    if eer:
        lines.append("## early_exit_rules\n")
        lines.append(yaml.dump(eer, default_flow_style=False))

    # Work alignment criteria (full)
    wac = global_block.get("work_alignment_criteria")
    if wac:
        lines.append("## work_alignment_criteria\n")
        lines.append(yaml.dump(wac, default_flow_style=False))

    # Contradiction resolution — first sentence of description per rule only
    cr = global_block.get("contradiction_resolution")
    if cr:
        lines.append("## contradiction_resolution (summary)\n")
        for rule in (cr.get("rules") or []):
            rule_name = rule.get("rule", "")
            desc = _first_sentence(rule.get("description", ""))
            lines.append(f"- {rule_name}: {desc}")
        lines.append("")

    return "\n".join(lines)


@lru_cache(maxsize=1)
def _cached_sources_compact_summary() -> str:
    return _build_sources_compact_summary_inner()


def get_sources_compact_summary() -> str:
    return _cached_sources_compact_summary()


def get_work_alignment_criteria() -> dict:
    """Return the work_alignment_criteria dict from the global block in sources.yaml."""
    path = _SKILLS / "sources.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    return ((data or {}).get("global") or {}).get("work_alignment_criteria") or {}
