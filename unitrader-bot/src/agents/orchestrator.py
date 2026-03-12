"""
src/agents/orchestrator.py — Master brain of Unitrader's symbiotic agent system.

This orchestrator is the foundation of Unitrader's 28-agent symbiotic system.
Currently wires 3 agents. Future agents plug in by:
1. Adding import to orchestrator.py
2. Adding TaskType enum value
3. Adding workflow method
4. Registering in route() method
The shared_memory layer ensures every new agent immediately benefits
from all historical learnings across all existing agents.

Architecture
------------
The MasterOrchestrator sits between the API layer and individual agents.
It:
  1. Loads shared context (sentiment, avoid patterns) before routing
  2. Routes tasks to the appropriate workflow
  3. Stores every outcome in SharedMemory for cross-agent learning
  4. Logs agent messages to AuditLog for full traceability

Task Types
----------
  TRADE_SIGNAL      → analyse market + execute if signal strong
  USER_QUESTION    → respond to user chat with full context
  CONTENT_CREATE   → generate blog or social content
  MARKET_ALERT     → urgent market condition detected
  PORTFOLIO_REVIEW → summarise user portfolio performance
  DAILY_BRIEFING   → morning summary for user
"""

import logging
import re
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog
from src.agents.core.conversation_agent import ConversationAgent
from src.agents.core.trading_agent import TradingAgent
from src.services.conversation_memory import get_recent_messages_for_claude
from src.integrations.market_data import full_market_analysis
from src.agents.memory.shared_memory import (
    AgentOutcome,
    SharedMemory,
    _is_successful,
)
from src.agents.marketing.content_writer import generate_blog_post
from src.agents.marketing.social_media import generate_social_posts

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Task types
# ─────────────────────────────────────────────

class TaskType(str, Enum):
    TRADE_SIGNAL = "trade_signal"
    USER_QUESTION = "user_question"
    CONTENT_CREATE = "content_create"
    MARKET_ALERT = "market_alert"
    PORTFOLIO_REVIEW = "portfolio_review"
    DAILY_BRIEFING = "daily_briefing"


# ─────────────────────────────────────────────
# Agent message (for audit trail)
# ─────────────────────────────────────────────

class AgentMessage(BaseModel):
    """Message passed between agents for traceability."""

    sender: str
    recipient: str
    message_type: str  # data | signal | outcome | alert
    payload: dict = Field(default_factory=dict)
    confidence: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────
# Orchestrator result
# ─────────────────────────────────────────────

class OrchestratorResult(BaseModel):
    """Result returned from the orchestrator."""

    result: dict
    agents_used: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    execution_time_ms: float = 0.0
    learning_applied: bool = False


# ─────────────────────────────────────────────
# Asset extraction (for shared context)
# ─────────────────────────────────────────────

def _extract_asset_symbols(text: str) -> list[str]:
    """Extract asset symbols from free text for shared context lookups."""
    text_lower = text.lower()
    symbols: set[str] = set()

    crypto_aliases = {
        "btc": "BTCUSDT", "bitcoin": "BTCUSDT",
        "eth": "ETHUSDT", "ethereum": "ETHUSDT",
        "sol": "SOLUSDT", "solana": "SOLUSDT",
        "bnb": "BNBUSDT", "xrp": "XRPUSDT", "doge": "DOGEUSDT",
        "ada": "ADAUSDT", "avax": "AVAXUSDT", "link": "LINKUSDT",
    }
    for alias, sym in crypto_aliases.items():
        if re.search(rf"\b{re.escape(alias)}\b", text_lower):
            symbols.add(sym)

    for ticker in ("aapl", "tsla", "googl", "amzn", "msft", "meta", "nvda", "spy", "qqq"):
        if re.search(rf"\b{re.escape(ticker)}\b", text_lower):
            symbols.add(ticker.upper())

    return list(symbols)[:5]


# ─────────────────────────────────────────────
# MasterOrchestrator
# ─────────────────────────────────────────────

class MasterOrchestrator:
    """Brain of Unitrader's symbiotic agent system.

    Routes tasks to the appropriate workflow, injects shared memory context,
    and stores every outcome for cross-agent learning.
    """

    def __init__(self, db: AsyncSession, user_id: str):
        self._db = db
        self.user_id = user_id
        self._memory = SharedMemory(db)

    def _log_agent_message(self, msg: AgentMessage) -> None:
        """Persist agent message to AuditLog for full traceability."""
        try:
            entry = AuditLog(
                user_id=self.user_id,
                event_type="agent_message",
                event_details={
                    "sender": msg.sender,
                    "recipient": msg.recipient,
                    "message_type": msg.message_type,
                    "payload": msg.payload,
                    "confidence": msg.confidence,
                    "timestamp": msg.timestamp.isoformat(),
                },
            )
            self._db.add(entry)
        except Exception as exc:
            logger.warning("Failed to log agent message: %s", exc)

    async def route(
        self,
        task_type: TaskType,
        payload: dict,
    ) -> OrchestratorResult:
        """Main entry point — route to the correct workflow.

        Before routing: loads shared context for relevant assets.
        After routing: stores outcome in shared_memory.
        """
        start = time.perf_counter()
        agents_used: list[str] = []
        learning_applied = False

        asset = payload.get("symbol") or payload.get("asset")
        if not asset and "message" in payload:
            symbols = _extract_asset_symbols(str(payload["message"]))
            asset = symbols[0] if symbols else None

        shared_ctx: dict[str, Any] = {}
        if asset:
            try:
                shared_ctx = await self._memory.get_all_context_for_asset(asset)
                if shared_ctx:
                    learning_applied = True
            except Exception as exc:
                logger.debug("Shared context fetch failed for %s: %s", asset, exc)

        payload["_shared_context"] = shared_ctx
        payload["_asset"] = asset

        result: dict = {}
        confidence = 0.0

        try:
            if task_type == TaskType.TRADE_SIGNAL:
                result = await self.run_trade_workflow(payload)
                agents_used = ["trading_agent"]
                confidence = result.get("confidence", 0) / 100.0 if isinstance(result.get("confidence"), (int, float)) else 0.0

            elif task_type == TaskType.USER_QUESTION:
                result = await self.run_conversation_workflow(payload)
                agents_used = ["conversation_agent"]
                confidence = 0.8

            elif task_type == TaskType.CONTENT_CREATE:
                result = await self.run_content_workflow(payload)
                agents_used = ["content_writer", "social_media"]
                confidence = 0.7

            elif task_type in (TaskType.MARKET_ALERT, TaskType.PORTFOLIO_REVIEW, TaskType.DAILY_BRIEFING):
                result = await self.run_conversation_workflow(payload)
                agents_used = ["conversation_agent"]
                confidence = 0.75

            else:
                result = {"status": "unsupported", "task_type": task_type.value}
        except Exception as exc:
            logger.error("Orchestrator route failed: %s", exc)
            result = {"status": "error", "reason": str(exc)}

        elapsed_ms = (time.perf_counter() - start) * 1000

        if task_type != TaskType.TRADE_SIGNAL:
            await self.learn_from_outcome(
                workflow=task_type.value,
                action=payload,
                result=result,
                context={"shared_context_keys": list(shared_ctx.keys()) if shared_ctx else []},
                confidence=confidence,
            )

        return OrchestratorResult(
            result=result,
            agents_used=agents_used,
            confidence=confidence,
            execution_time_ms=round(elapsed_ms, 2),
            learning_applied=learning_applied,
        )

    async def run_trade_workflow(self, payload: dict) -> dict:
        """Trade workflow: shared memory → market analysis → decide → execute/skip.

        Supports:
        - Single-asset payload: {"asset": "BTCUSDT", "exchange": "binance"}
        - Batch payload (background loop): {"assets": [...], "exchanges": [...]}
        """
        if isinstance(payload.get("assets"), list):
            allowed_exchanges = set(str(x).lower() for x in (payload.get("exchanges") or []))
            results: list[dict] = []
            for item in payload.get("assets") or []:
                if isinstance(item, dict):
                    sym = (item.get("symbol") or item.get("asset") or "").upper()
                    ex = str(item.get("exchange") or "binance").lower()
                else:
                    sym = str(item).upper()
                    ex = "binance"
                if not sym:
                    continue
                if allowed_exchanges and ex not in allowed_exchanges:
                    results.append({"status": "skipped", "symbol": sym, "reason": f"No keys for {ex}"})
                    continue
                results.append(await self._run_single_trade(sym, ex))
            return {"status": "batch", "count": len(results), "results": results}

        asset = (payload.get("asset") or payload.get("symbol") or "").upper()
        exchange = str(payload.get("exchange") or "alpaca").lower()
        return await self._run_single_trade(asset, exchange)

    async def _run_single_trade(self, asset: str, exchange: str) -> dict:
        """Run the trade workflow for a single asset/exchange pair."""
        if not asset:
            return {"status": "error", "reason": "Missing asset"}
        try:
            shared_ctx = await self._memory.get_all_context_for_asset(asset)
        except Exception:
            shared_ctx = {}

        self._log_agent_message(
            AgentMessage(
                sender="orchestrator",
                recipient="trading_agent",
                message_type="signal",
                payload={"asset": asset, "exchange": exchange},
                confidence=0.85,
            )
        )

        # 1) Market analysis (live)
        try:
            market_data = await full_market_analysis(asset, exchange)
            market_data["exchange"] = exchange
        except ValueError as exc:
            logger.warning("Exchange routing for %s/%s: %s", asset, exchange, exc)
            return {"status": "skipped", "reason": str(exc), "symbol": asset}
        except Exception as exc:
            logger.warning("Market analysis failed for %s/%s: %s", asset, exchange, exc)
            market_data = {"symbol": asset, "exchange": exchange, "price": 0.0, "indicators": {}, "trend": "unknown"}

        # 2) Similar past outcomes based on key features
        indicators = market_data.get("indicators", {}) or {}
        macd = indicators.get("macd", {}) or {}
        query_ctx = {
            "rsi": indicators.get("rsi"),
            "trend": market_data.get("trend"),
            "sentiment_score": shared_ctx.get(f"{asset}_sentiment") or shared_ctx.get(f"{asset}_sentiment_score"),
            "macd_signal": "bullish" if isinstance(macd.get("histogram"), (int, float)) and macd.get("histogram") > 0 else "bearish",
        }
        similar = await self._memory.query_similar_context(
            context=query_ctx,
            action_type="trade",
            asset=asset,
            limit=10,
        )

        # 3) User settings snapshot (best-effort)
        user_settings: dict[str, Any] = {}
        try:
            from models import UserSettings as UserSettingsModel
            result = await self._db.execute(select(UserSettingsModel).where(UserSettingsModel.user_id == self.user_id))
            row = result.scalar_one_or_none()
            if row:
                user_settings = {
                    "max_position_size": row.max_position_size,
                    "max_daily_loss": row.max_daily_loss,
                    "approved_assets": row.approved_assets,
                    "require_confirmation_above": row.require_confirmation_above,
                }
        except Exception:
            pass

        # 4) Decide with shared context
        agent = TradingAgent(self.user_id)
        decision = await agent.decide_with_context(
            user_id=self.user_id,
            asset=asset,
            market_data=market_data,
            shared_context=shared_ctx,
            similar_past_outcomes=similar,
            user_settings=user_settings,
        )

        # 5) Execution policy (confidence thresholds)
        # decision.confidence is 0..1
        if decision.action == "HOLD":
            result = {
                "status": "wait",
                "symbol": asset,
                "decision": "WAIT",
                "confidence": int(decision.confidence * 100),
                "reasoning": decision.reasoning,
                "risk_factors": decision.risk_factors,
            }
        else:
            size_pct = min(float(decision.suggested_size_pct or 0.0), 2.0)
            if decision.confidence < 0.4:
                result = {
                    "status": "wait",
                    "symbol": asset,
                    "decision": "WAIT",
                    "confidence": int(decision.confidence * 100),
                    "reasoning": f"Skipped: low confidence. {decision.reasoning}",
                    "risk_factors": decision.risk_factors,
                }
            else:
                if 0.4 <= decision.confidence <= 0.7:
                    size_pct = round(size_pct * 0.5, 2)

                price = float(market_data.get("price") or 0.0)
                stop_loss = price * (1 - (decision.stop_loss_pct / 100.0)) if decision.action == "BUY" else price * (1 + (decision.stop_loss_pct / 100.0))
                take_profit = price * (1 + (decision.take_profit_pct / 100.0)) if decision.action == "BUY" else price * (1 - (decision.take_profit_pct / 100.0))

                exec_decision = {
                    "decision": decision.action,
                    "confidence": int(decision.confidence * 100),
                    "entry_price": price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "position_size_pct": size_pct,
                    "reasoning": decision.reasoning,
                }
                result = await agent.execute_trade(exec_decision, asset, exchange)

        # 6) Learn from outcome in shared memory (always)
        await self._memory.broadcast_outcome(
            AgentOutcome(
                agent_name="trading_agent",
                action_type="trade",
                user_id=self.user_id,
                context={
                    "asset": asset,
                    "exchange": exchange,
                    "rsi": indicators.get("rsi"),
                    "trend": market_data.get("trend"),
                    "shared_context_keys": list(shared_ctx.keys()),
                },
                action_taken={
                    "action": decision.action,
                    "suggested_size_pct": decision.suggested_size_pct,
                    "risk_factors": decision.risk_factors,
                },
                result={**(result or {}), "success": result.get("status") == "executed"} if isinstance(result, dict) else {"success": False},
                confidence_score=float(decision.confidence),
                asset=asset,
                exchange=exchange,
                tags=["orchestrator_routed"] + (decision.risk_factors[:5] if decision.risk_factors else []),
            )
        )

        return result

    async def run_conversation_workflow(self, payload: dict) -> dict:
        """Conversation workflow: shared memory + market + portfolio → respond."""
        message = payload.get("message", "") or ""
        if not message:
            return {"status": "error", "reason": "Missing message"}

        # Load shared context for all assets mentioned (merge)
        assets = _extract_asset_symbols(message)
        shared: dict[str, Any] = {}
        for sym in assets:
            try:
                shared.update(await self._memory.get_all_context_for_asset(sym))
            except Exception:
                continue

        self._log_agent_message(
            AgentMessage(
                sender="orchestrator",
                recipient="conversation_agent",
                message_type="data",
                payload={"message_preview": message[:120], "assets": assets},
                confidence=0.9,
            )
        )

        # Conversation history (Claude-compatible)
        history = await get_recent_messages_for_claude(self.user_id, limit=10, db=self._db)

        # Market context (best effort for the first asset)
        market_context: dict[str, Any] = {}
        if assets:
            sym = assets[0]
            guess_exchange = "binance" if sym.endswith("USDT") else ("oanda" if "_" in sym else "alpaca")
            try:
                md = await full_market_analysis(sym, guess_exchange)
                market_context = {
                    "symbol": sym,
                    "exchange": guess_exchange,
                    "price": md.get("price"),
                    "trend": md.get("trend"),
                    "rsi": (md.get("indicators") or {}).get("rsi"),
                    "macd": (md.get("indicators") or {}).get("macd"),
                    "change_24h_pct": md.get("price_change_pct"),
                    "timestamp": (md.get("timestamp").isoformat() if getattr(md.get("timestamp"), "isoformat", None) else str(md.get("timestamp"))),
                }
            except Exception as exc:
                logger.debug("Market context fetch failed for chat (%s): %s", sym, exc)

        # Portfolio context from DB (very compact)
        portfolio_context: dict[str, Any] = {}
        try:
            from sqlalchemy import func
            from models import Trade
            open_count_result = await self._db.execute(
                select(func.count()).where(Trade.user_id == self.user_id, Trade.status == "open")
            )
            open_positions = int(open_count_result.scalar() or 0)

            pnl_result = await self._db.execute(
                select(func.coalesce(func.sum(Trade.profit), 0), func.coalesce(func.sum(Trade.loss), 0)).where(
                    Trade.user_id == self.user_id, Trade.status == "closed"
                )
            )
            row = pnl_result.first()
            total_profit = float(row[0] or 0)
            total_loss = float(row[1] or 0)
            portfolio_context = {
                "open_positions": open_positions,
                "net_pnl_usd": round(total_profit - total_loss, 2),
            }
        except Exception:
            portfolio_context = {}

        # Agent insights (shared memory + trading agent performance)
        agent_insights: dict[str, Any] = {}
        if shared:
            agent_insights["shared_context_keys"] = list(shared.keys())[:25]
        try:
            perf = await self._memory.get_agent_performance("trading_agent", timeframe_days=30)
            agent_insights["trading_agent_success_rate_30d"] = perf.success_rate
            agent_insights["trading_agent_avg_confidence_30d"] = perf.avg_confidence
        except Exception:
            pass

        agent = ConversationAgent(self.user_id)
        result = await agent.respond_with_context(
            user_id=self.user_id,
            message=message,
            conversation_history=history,
            market_context=market_context,
            portfolio_context=portfolio_context,
            agent_insights=agent_insights,
        )

        return result

    async def run_content_workflow(self, payload: dict) -> dict:
        """Content workflow: shared memory patterns → market trends → generate."""
        content_type = payload.get("content_type", "blog")  # blog | social
        topic = payload.get("topic", "AI trading strategies")
        platforms = payload.get("platforms")
        use_market_trends = bool(payload.get("use_market_trends"))

        # Optionally enrich topic with current shared market trends.
        if use_market_trends:
            try:
                from sqlalchemy import or_
                from models import SharedContextModel

                now = datetime.now(timezone.utc)
                res = await self._db.execute(
                    select(SharedContextModel).where(
                        or_(SharedContextModel.expires_at.is_(None), SharedContextModel.expires_at > now)
                    )
                )
                rows = res.scalars().all()
                trend_keys = [r for r in rows if str(r.key).lower().endswith("_trend")]
                trends: list[str] = []
                for r in trend_keys[:5]:
                    raw = r.value_data or {}
                    v = raw.get("_v")
                    trends.append(f"{r.key}:{v}")
                if trends:
                    topic = f"{topic} (market trends: {', '.join(trends)})"
            except Exception:
                pass

        self._log_agent_message(AgentMessage(
            sender="orchestrator",
            recipient="content_writer" if content_type == "blog" else "social_media",
            message_type="data",
            payload={"topic": topic, "content_type": content_type},
            confidence=0.7,
        ))

        try:
            from sqlalchemy import select
            from models import AgentOutcomeModel

            result = await self._db.execute(
                select(AgentOutcomeModel)
                .where(AgentOutcomeModel.action_type == "trade")
                .order_by(AgentOutcomeModel.created_at.desc())
                .limit(50)
            )
            rows = result.scalars().all()
            wins = [r for r in rows if _is_successful(r.result_data or {})]
            losses = [r for r in rows if not _is_successful(r.result_data or {})]

            patterns_context = (
                f"Recent platform patterns (anonymised): "
                f"{len(wins)} winning trades, {len(losses)} losing trades. "
                f"Win rate: {len(wins) / len(rows) * 100:.0f}%" if rows else "No data yet."
            )
        except Exception:
            patterns_context = ""

        if content_type == "blog":
            out = await generate_blog_post(
                topic=topic,
                save_to_db=True,
                db=self._db,
            )
        else:
            posts = await generate_social_posts(
                topic=topic,
                count=payload.get("count", 5),
                platforms=platforms,
                save_to_db=True,
            )
            out = {"posts": posts, "count": len(posts)}

        content_result = out or {}
        return content_result

    async def learn_from_outcome(
        self,
        workflow: str,
        action: dict,
        result: dict,
        context: dict,
        confidence: float,
    ) -> None:
        """Store outcome in shared memory and update shared context with learnings."""
        agent_name = "orchestrator"
        if workflow in (TaskType.TRADE_SIGNAL.value, "trade", "trading"):
            agent_name = "trading_agent"
        elif workflow in (TaskType.USER_QUESTION.value, "conversation", "market_alert", "portfolio_review", "daily_briefing"):
            agent_name = "conversation_agent"
        elif workflow in (TaskType.CONTENT_CREATE.value, "content", "content_create"):
            agent_name = "content_writer"

        action_type = "analysis"
        if workflow == TaskType.TRADE_SIGNAL.value:
            action_type = "trade"
        elif workflow == TaskType.USER_QUESTION.value:
            action_type = "conversation"
        elif workflow == TaskType.CONTENT_CREATE.value:
            action_type = "content"

        outcome = AgentOutcome(
            agent_name=agent_name,
            action_type=action_type,
            user_id=self.user_id,
            context=context,
            action_taken=action,
            result=result,
            confidence_score=confidence,
            asset=action.get("asset") or action.get("symbol"),
            tags=["orchestrator_learned"],
        )
        await self._memory.store_outcome(outcome)

        if outcome.asset and not _is_successful(result):
            if "trade" in workflow:
                await self._memory.set_shared_context(
                    key=f"avoid_{outcome.asset}_recent_loss",
                    value=True,
                    set_by="orchestrator",
                    ttl_seconds=3600,
                )

    async def get_system_health(self) -> dict:
        """Return performance metrics for all agents and shared context summary."""
        agents = ["trading_agent", "conversation_agent", "content_writer"]
        perf: dict[str, Any] = {}
        for name in agents:
            try:
                metrics = await self._memory.get_agent_performance(name, timeframe_days=30)
                perf[name] = metrics.model_dump()
            except Exception as exc:
                perf[name] = {"error": str(exc)}

        try:
            from sqlalchemy import or_
            from models import SharedContextModel
            now = datetime.now(timezone.utc)
            result = await self._db.execute(
                select(SharedContextModel).where(
                    or_(
                        SharedContextModel.expires_at.is_(None),
                        SharedContextModel.expires_at > now,
                    )
                ).limit(50)
            )
            rows = result.scalars().all()
            context_summary = {r.key: r.set_by for r in rows[:20]}
        except Exception as exc:
            context_summary = {"error": str(exc)}

        try:
            from models import AgentOutcomeModel
            result = await self._db.execute(
                select(AgentOutcomeModel)
                .order_by(AgentOutcomeModel.created_at.desc())
                .limit(10)
            )
            recent = result.scalars().all()
            recent_outcomes = [
                {
                    "id": r.id,
                    "agent": r.agent_name,
                    "action_type": r.action_type,
                    "asset": r.asset,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in recent
            ]
        except Exception as exc:
            recent_outcomes = [{"error": str(exc)}]

        return {
            "agent_performance": perf,
            "shared_context_summary": context_summary,
            "recent_outcomes": recent_outcomes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
