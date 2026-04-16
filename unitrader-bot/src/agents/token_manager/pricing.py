"""Anthropic pricing table + cost calculator.

Prices are USD per 1M tokens, as published by Anthropic (2025).
Update this table when pricing changes.

Reference: https://www.anthropic.com/pricing
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────
# Pricing per 1,000,000 tokens (USD)
# Keys must match the `model` field used in `messages.create(model=...)`.
# ──────────────────────────────────────────────────────────────────────────

MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude Sonnet 4 (flagship, used for trading/chat/content)
    "claude-sonnet-4-20250514": {
        "input": 3.00,
        "output": 15.00,
        "cached_input": 0.30,   # 90% discount on cache reads
    },
    # Claude 3.5 Sonnet (older)
    "claude-3-5-sonnet-20241022": {
        "input": 3.00,
        "output": 15.00,
        "cached_input": 0.30,
    },
    "claude-3-5-sonnet-20240620": {
        "input": 3.00,
        "output": 15.00,
        "cached_input": 0.30,
    },
    # Claude Opus
    "claude-3-opus-20240229": {
        "input": 15.00,
        "output": 75.00,
        "cached_input": 1.50,
    },
    # Claude Haiku (fallback / fast)
    "claude-3-haiku-20240307": {
        "input": 0.25,
        "output": 1.25,
        "cached_input": 0.03,
    },
    "claude-3-5-haiku-20241022": {
        "input": 0.80,
        "output": 4.00,
        "cached_input": 0.08,
    },
}

# Fallback pricing when model is unknown (conservative — Sonnet-level).
_UNKNOWN_MODEL_PRICING = {"input": 3.00, "output": 15.00, "cached_input": 0.30}


def calculate_cost(
    tokens_in: int,
    tokens_out: int,
    model: str,
    cached_tokens: int = 0,
) -> float:
    """Return total cost in USD for a single Anthropic call.

    Args:
        tokens_in: Total input tokens (including cached).
        tokens_out: Output tokens.
        model: Exact model string used in the API call.
        cached_tokens: Subset of tokens_in served from prompt cache.

    Returns:
        Total cost in USD (float, high precision).
    """
    pricing = MODEL_PRICING.get(model, _UNKNOWN_MODEL_PRICING)

    uncached_in = max(0, tokens_in - cached_tokens)

    cost = (
        (uncached_in / 1_000_000) * pricing["input"]
        + (cached_tokens / 1_000_000) * pricing.get("cached_input", pricing["input"])
        + (tokens_out / 1_000_000) * pricing["output"]
    )
    return round(cost, 8)
