import logging

from pipeline_v2.lib.scope_loader import get_cost_cap

_MODEL_RATES = {
    "claude-opus-4-7":           {"input": 15.0 / 1e6, "output": 75.0 / 1e6},
    "claude-opus-4-6":           {"input": 15.0 / 1e6, "output": 75.0 / 1e6},
    "claude-sonnet-4-6":         {"input": 3.0 / 1e6,  "output": 15.0 / 1e6},
    "claude-haiku-4-5-20251001": {"input": 0.8 / 1e6,  "output": 4.0 / 1e6},
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _MODEL_RATES.get(model)
    if rates is None:
        logging.getLogger(__name__).warning(
            "Unknown model '%s' — falling back to Sonnet rates, cost tracking may be wrong", model
        )
        rates = _MODEL_RATES["claude-sonnet-4-6"]
    return input_tokens * rates["input"] + output_tokens * rates["output"]


def is_over_limit(daily_cost: float) -> bool:
    return daily_cost >= get_cost_cap()


def add_cost(cost_by_stage: dict, stage: str, amount: float) -> dict:
    updated = dict(cost_by_stage)
    updated[stage] = updated.get(stage, 0.0) + amount
    return updated
