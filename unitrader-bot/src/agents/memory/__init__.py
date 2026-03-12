"""
src/agents/memory — Symbiotic learning memory layer.

Every agent in Unitrader reads from and writes to a shared brain so they
collectively improve over time without requiring explicit coordination.

Architecture
------------
The memory layer follows the **Blackboard** architectural pattern:

    ┌─────────────────────────────────────────────────────────────┐
    │                        BLACKBOARD                           │
    │   SharedMemory (shared_memory.py)                           │
    │                                                             │
    │  ┌──────────────────┐   ┌──────────────────────────────┐    │
    │  │  AgentOutcomes   │   │      SharedContext           │    │
    │  │  (DB table)      │   │      (DB table)              │    │
    │  │                  │   │                              │    │
    │  │  Every decision  │   │  Live key/value store        │    │
    │  │  + its outcome   │   │  with optional TTL expiry    │    │
    │  └──────────────────┘   └──────────────────────────────┘    │
    └─────────────────────────────────────────────────────────────┘
              ▲  write                          ▲  write
              │                                 │
    ┌─────────┴────┐   ┌────────────┐   ┌──────┴────────┐
    │ TradingAgent │   │ ChatAgent  │   │ ContentAgent  │
    └──────────────┘   └────────────┘   └───────────────┘
              │  read                           │  read
              ▼                                 ▼
     "What worked last time BTC RSI > 70?"
     "What is BTC_sentiment right now?"
     "Has this conversation pattern been positive?"

Public API
----------
    from src.agents.memory import SharedMemory, AgentOutcome, SharedContext

    async with AsyncSessionLocal() as db:
        mem = SharedMemory(db)
        await mem.store_outcome(outcome)
        similar = await mem.query_similar_context(ctx, "trade", "BTCUSDT")
        perf = await mem.get_agent_performance("trading_agent")
"""

from src.agents.memory.shared_memory import (
    AgentOutcome,
    PerformanceMetrics,
    SharedContext,
    SharedMemory,
)

__all__ = [
    "SharedMemory",
    "AgentOutcome",
    "PerformanceMetrics",
    "SharedContext",
]
