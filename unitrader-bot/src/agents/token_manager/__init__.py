"""TokenManagementAgent package.

Central LLM gateway + cost tracker for all Anthropic API calls.
See agent.py for the public API.
"""

from src.agents.token_manager.agent import TokenManagementAgent, get_token_manager
from src.agents.token_manager.pricing import calculate_cost, MODEL_PRICING

__all__ = [
    "TokenManagementAgent",
    "get_token_manager",
    "calculate_cost",
    "MODEL_PRICING",
]
