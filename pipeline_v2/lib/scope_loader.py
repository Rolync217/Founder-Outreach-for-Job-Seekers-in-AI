import os
import yaml
from pathlib import Path
from functools import lru_cache

_SMOKE_TEST_COST_CAP = 2.0
_SMOKE_TEST_POOL_SIZE = 5


def _is_smoke_test() -> bool:
    return os.environ.get("SMOKE_TEST", "") == "1"

_SKILLS = Path(__file__).parent.parent.parent / "skills"


@lru_cache(maxsize=1)
def _load() -> dict:
    path = _SKILLS / "search_scope.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data or "research" not in data or "cost_hard_cap_usd" not in data:
        raise ValueError(
            f"search_scope.yaml at {path} is missing required keys. "
            "Expected: research, cost_hard_cap_usd, daily_target, sourcing."
        )
    return data


def get_max_iterations(run_type: str) -> int:
    iterations = _load()["research"]["max_iterations"]
    if run_type not in iterations:
        raise ValueError(f"Unknown run_type '{run_type}'. Expected: {list(iterations.keys())}")
    return iterations[run_type]


def get_no_progress_threshold(run_type: str) -> int:
    thresholds = _load()["research"]["consecutive_no_progress_threshold"]
    if run_type not in thresholds:
        raise ValueError(f"Unknown run_type '{run_type}'. Expected: {list(thresholds.keys())}")
    return thresholds[run_type]


def get_dimension_priority() -> list[str]:
    return _load()["research"]["dimension_priority"]


def get_critical_dimensions() -> list[str]:
    return _load()["research"]["critical_dimensions"]


def get_daily_target(run_type: str) -> int:
    return _load()["daily_target"][run_type]


def get_cost_cap() -> float:
    if _is_smoke_test():
        return _SMOKE_TEST_COST_CAP
    return float(_load()["cost_hard_cap_usd"])


def get_light_source_categories() -> list[str]:
    return _load()["sourcing"]["light_run_source_categories"]


def get_pool_sufficient_threshold() -> int:
    if _is_smoke_test():
        return _SMOKE_TEST_POOL_SIZE
    return _load()["sourcing"]["pool_sufficient_threshold"]


def get_tier_signals() -> dict:
    return _load()["hiring_tiers"]


def get_opus_checkpoint_interval(run_type: str) -> int:
    intervals = _load()["research"]["opus_checkpoint_interval"]
    if run_type not in intervals:
        raise ValueError(f"Unknown run_type '{run_type}'. Expected: {list(intervals.keys())}")
    return intervals[run_type]


def get_scoring_config() -> dict:
    """Return the scoring section from search_scope.yaml, or {} if missing."""
    return _load().get("scoring", {})


_DEFAULT_WEIGHTS: dict[str, int] = {
    "hiring": 4, "traction": 2, "founder": 2,
    "product": 2, "alignment": 2, "recency": 1,
}


def get_scoring_weights() -> dict[str, int]:
    """Return dimension weights from yaml, falling back to defaults."""
    return get_scoring_config().get("weights", _DEFAULT_WEIGHTS)


def get_tier_thresholds() -> list[tuple[float, int, str]]:
    """Return tier thresholds as (min_fraction, tier, label) tuples."""
    t = get_scoring_config().get("tier_thresholds", {})
    return [
        (t.get("tier_1_pct", 0.72), 1, "strong"),
        (t.get("tier_2_pct", 0.48), 2, "good"),
        (t.get("tier_3_pct", 0.28), 3, "weak"),
        (0.00, 4, "weak"),
    ]
