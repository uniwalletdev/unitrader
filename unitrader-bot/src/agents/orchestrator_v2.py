"""
orchestrator.py — Master router for agent workflows using SharedContext.

Routes API requests to the correct agent based on action type.
Loads SharedContext once per request, passes to agents, writes audit trails.

Actions:
  "trade_analyze"     → TradingAgent.analyze (expert + simple + metaphor explanations)
  "trade_execute"     → Risk + Portfolio checks, then execute (paper/live)
  "onboarding_chat"   → ConversationAgent.chat in onboarding mode
  "backtest"          → TradingAgent.backtest for strategy validation
"""

import logging
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog
from src.agents.shared_memory import SharedContext, SharedMemory
from src.agents.core.trading_agent import TradingAgent
from src.agents.core.conversation_agent import ConversationAgent

logger = logging.getLogger(__name__)


class MasterOrchestrator:
    """Routes requests to agents with shared context injection."""

    def __init__(self):
        pass

    async def route(
        self,
        user_id: str,
        action: str,
        payload: dict,
        db: AsyncSession,
    ) -> dict:
        """Route request to the appropriate agent workflow.

        Args:
            user_id: Unitrader user UUID
            action: One of "trade_analyze", "trade_execute", "onboarding_chat", "backtest"
            payload: Action-specific parameters (e.g. {"symbol": "NVDA"})
            db: AsyncSession for database access

        Returns:
            dict with action result
        """
        # Load shared context once for all agents
        ctx: SharedContext = await SharedMemory.load(user_id, db)
        logger.info(f"Orchestrator route for user {user_id}, action={action}")

        try:
            if action == "trade_analyze":
                return await self._trade_analyze(user_id, ctx, payload, db)

            elif action == "trade_execute":
                return await self._trade_execute(user_id, ctx, payload, db)

            elif action == "onboarding_chat":
                return await self._onboarding_chat(user_id, ctx, payload, db)

            elif action == "backtest":
                return await self._backtest(user_id, ctx, payload, db)

            else:
                raise ValueError(f"Unknown action: {action}")

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Orchestrator error for user {user_id}, action {action}: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # TRADE ANALYZE
    # ─────────────────────────────────────────────────────────────────────────

    async def _trade_analyze(
        self,
        user_id: str,
        ctx: SharedContext,
        payload: dict,
        db: AsyncSession,
    ) -> dict:
        """Analyze a trading opportunity with expert + simple + metaphor explanations.

        Steps:
        1. Check subscription
        2. Check trading_paused
        3. Call trading_agent.analyze(symbol)
        4. Get expert explanation
        5. Translate to simple explanation
        6. Translate to metaphor explanation
        7. Return merged response
        """
        symbol = payload.get("symbol")
        if not symbol:
            raise ValueError("Missing symbol in payload")

        # Check subscription
        if not ctx.subscription_active:
            raise HTTPException(status_code=402, detail="Subscription required to analyze trades")

        # Check trading paused
        if ctx.trading_paused:
            raise HTTPException(
                status_code=429,
                detail="Trading paused — daily loss limit reached",
            )

        # Call trading agent to analyze
        trading_agent = TradingAgent()
        analysis_result = await trading_agent.analyze(symbol=symbol, context=ctx)

        # Extract expert explanation
        expert_explanation = analysis_result.get("explanation", "")

        # Get conversation agent for translations
        conv_agent = ConversationAgent()

        # Translate to simple explanation
        simple_result = await conv_agent.translate(
            expert_text=expert_explanation,
            target="simple",
            context=ctx,
        )
        simple_explanation = simple_result.get("translated_text", "")

        # Translate to metaphor explanation
        metaphor_result = await conv_agent.translate(
            expert_text=expert_explanation,
            target="metaphor",
            context=ctx,
        )
        metaphor_explanation = metaphor_result.get("translated_text", "")

        # Merge all explanations into result
        return {
            **analysis_result,
            "explanations": {
                "expert": expert_explanation,
                "simple": simple_explanation,
                "metaphor": metaphor_explanation,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # TRADE EXECUTE
    # ─────────────────────────────────────────────────────────────────────────

    async def _trade_execute(
        self,
        user_id: str,
        ctx: SharedContext,
        payload: dict,
        db: AsyncSession,
    ) -> dict:
        """Execute a trade with full risk and portfolio checks.

        Steps:
        1. Load context + all analyze checks
        2. Risk agent check: can_open_position(symbol, amount)
        3. Portfolio agent check: evaluate_new_trade(symbol, side, amount)
        4. Write to AuditLog BEFORE execution
        5. Execute: paper_trading_enabled → execute_paper, else execute_live
        6. Invalidate shared_memory cache
        7. Return trade result
        """
        symbol = payload.get("symbol")
        side = payload.get("side")  # BUY or SELL
        amount = payload.get("amount")

        if not all([symbol, side, amount]):
            raise ValueError("Missing symbol, side, or amount in payload")

        # Re-use analyze checks
        if not ctx.subscription_active:
            raise HTTPException(status_code=402, detail="Subscription required to execute trades")

        if ctx.trading_paused:
            raise HTTPException(
                status_code=429,
                detail="Trading paused — daily loss limit reached",
            )

        # Import risk and portfolio agents
        from src.agents.core.risk_agent import RiskAgent
        from src.agents.core.portfolio_agent import PortfolioAgent

        # Step 2: Risk agent validation
        risk_agent = RiskAgent()
        risk_check = await risk_agent.can_open_position(
            user_id=user_id,
            symbol=symbol,
            amount=amount,
            db=db,
        )

        if not risk_check.get("allowed"):
            return {
                "success": False,
                "reason": risk_check.get("reason"),
                "suggestion": risk_check.get("suggestion"),
            }

        # Step 3: Portfolio agent validation
        portfolio_agent = PortfolioAgent()
        portfolio_check = await portfolio_agent.evaluate_new_trade(
            user_id=user_id,
            symbol=symbol,
            side=side,
            amount=amount,
            db=db,
        )

        if not portfolio_check.get("approved"):
            return {
                "success": False,
                "reason": portfolio_check.get("reason"),
            }

        # Step 4: Write audit log BEFORE execution
        audit_entry = AuditLog(
            user_id=user_id,
            event_type="trade_decision",
            event_details={
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "context_snapshot": {
                    "subscription_active": ctx.subscription_active,
                    "risk_level": ctx.risk_level,
                    "max_daily_loss_pct": ctx.max_daily_loss_pct,
                    "paper_trading_enabled": ctx.paper_trading_enabled,
                    "win_rate": ctx.win_rate,
                },
                "risk_approved": True,
                "portfolio_approved": True,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
        db.add(audit_entry)
        await db.commit()

        # Step 5: Execute trade
        trading_agent = TradingAgent()

        if ctx.paper_trading_enabled:
            trade_result = await trading_agent.execute_paper(
                payload=payload,
                context=ctx,
                db=db,
            )
        else:
            trade_result = await trading_agent.execute_live(
                payload=payload,
                context=ctx,
                db=db,
            )

        # Step 6: Invalidate cache
        SharedMemory.invalidate(user_id)

        # Step 7: Return result
        return trade_result

    # ─────────────────────────────────────────────────────────────────────────
    # ONBOARDING CHAT
    # ─────────────────────────────────────────────────────────────────────────

    async def _onboarding_chat(
        self,
        user_id: str,
        ctx: SharedContext,
        payload: dict,
        db: AsyncSession,
    ) -> dict:
        """Route to conversation agent in onboarding mode.

        Steps:
        1. Extract message from payload
        2. Call conversation_agent.chat(mode="onboarding", context=ctx)
        3. Return response
        """
        message = payload.get("message")
        if not message:
            raise ValueError("Missing message in payload")

        conv_agent = ConversationAgent()
        response = await conv_agent.chat(
            message=message,
            mode="onboarding",
            context=ctx,
            db=db,
        )

        return response

    # ─────────────────────────────────────────────────────────────────────────
    # BACKTEST
    # ─────────────────────────────────────────────────────────────────────────

    async def _backtest(
        self,
        user_id: str,
        ctx: SharedContext,
        payload: dict,
        db: AsyncSession,
    ) -> dict:
        """Run backtest on a trading strategy.

        Steps:
        1. Extract symbols, amount, days from payload
        2. Call trading_agent.backtest(symbols, amount, days, context=ctx)
        3. Return backtest results
        """
        symbols = payload.get("symbols")
        amount = payload.get("amount")
        days = payload.get("days")

        if not all([symbols, amount, days]):
            raise ValueError("Missing symbols, amount, or days in payload")

        trading_agent = TradingAgent()
        backtest_result = await trading_agent.backtest(
            symbols=symbols,
            amount=amount,
            days=days,
            context=ctx,
        )

        return backtest_result


# Module-level singleton orchestrator
_orchestrator: MasterOrchestrator | None = None


def get_orchestrator() -> MasterOrchestrator:
    """Get or create singleton orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MasterOrchestrator()
    return _orchestrator
