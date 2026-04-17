"""
src/agents/business_ops/ — Business Operations Agent (Phase 12).

Computes MRR, churn, margin, forecasts, and anomaly detection locally.
No business metric ever leaves this database.
"""

from src.agents.business_ops.agent import (
    BusinessOpsAgent,
    get_business_ops_agent,
)

__all__ = ["BusinessOpsAgent", "get_business_ops_agent"]
