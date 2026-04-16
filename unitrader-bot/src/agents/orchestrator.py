"""
orchestrator.py — Master router for agent workflows using SharedContext.

Routes API requests to the correct agent based on action type.
Loads SharedContext once per request, passes to agents, writes audit trails.

Actions:
  "trade_analyze"     → TradingAgent.analyze (expert + simple + metaphor explanations)
  "trade_execute"     → Risk + Portfolio checks, then execute (paper/live)
  "chat"              → ConversationAgent.respond (post-onboarding trading chat)
  "onboarding_chat"   → ConversationAgent.chat in onboarding mode
  "backtest"          → TradingAgent.backtest for strategy validation
"""

import logging
from datetime import datetime

import sentry_sdk
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog
from src.agents.shared_memory import SharedContext, SharedMemory
from src.market_context import MarketContext, resolve_execution_venue
from src.agents.core.trading_agent import TradingAgent, validate_trade_amount
from src.agents.core.conversation_agent import ConversationAgent
from src.agents.sentiment_agent import SentimentAgent
from src.agents.portfolio_agent import PortfolioAgent
from src.agents.token_manager import get_token_manager

logger = logging.getLogger(__name__)


# Map orchestrator actions → agent priority class (for TokenManagementAgent).
# Trading is p0 (real money — never throttled). Everything else is p1.
_ACTION_TO_AGENT: dict[str, str] = {
    "trade_analyze":    "trading",
    "trade_execute":    "trading",
    "chat":             "conversation",
    "onboarding_chat":  "conversation",
    "backtest":         "trading",
}


class MasterOrchestrator:
    """Routes requests to agents with shared context injection."""

    def __init__(self):
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # AUDIT LOGGING HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    async def log_trade_decision(
        self,
        user_id: str,
        payload: dict,
        ctx: SharedContext,
        risk_result: tuple,  # (allowed: bool, reason: str)
        portfolio_result: dict,
        agent_response: dict,
        db: AsyncSession,
    ) -> None:
        """
        Log a trade decision to audit_log with full context.

        CRITICAL: Wraps in try/except with Sentry integration.
        If audit write fails, raises HTTPException 500 and does NOT execute trade.

        Args:
            user_id: User ID
            payload: Request payload (symbol, side, amount, etc.)
            ctx: SharedContext snapshot
            risk_result: Tuple of (allowed: bool, reason: str)
            portfolio_result: Dict with "approved" and "reason"
            agent_response: Response from trading agent
            db: AsyncSession for database access

        Raises:
            HTTPException: 500 if audit logging fails
        """
        try:
            market_context: MarketContext | None = getattr(ctx, "market_context", None)
            existing_market_snapshot = agent_response.get("market_data", {}) or {}
            audit_log = AuditLog(
                user_id=user_id,
                event_type="trade_decision",
                event_details={
                    "symbol": payload.get("symbol"),
                    "side": agent_response.get("signal"),
                    "amount": payload.get("amount"),
                    "paper_mode": ctx.paper_trading_enabled,
                    "trust_ladder_stage": ctx.trust_ladder_stage,
                    "ai_reasoning": agent_response.get("explanation_expert"),
                    "ai_confidence": agent_response.get("confidence"),
                    "market_data_snapshot": {
                        **existing_market_snapshot,
                        **(market_context.to_snapshot() if market_context else {}),
                    },
                    "risk_check_result": {
                        "allowed": risk_result[0],
                        "reason": risk_result[1],
                    },
                    "portfolio_check_result": {
                        "approved": portfolio_result.get("approved"),
                        "reason": portfolio_result.get("reason"),
                    },
                },
            )
            db.add(audit_log)
            await db.commit()

            logger.info(
                f"Trade decision logged for user {user_id}: "
                f"{payload.get('symbol')} {agent_response.get('signal')} "
                f"(risk={risk_result[0]}, portfolio={portfolio_result.get('approved')})"
            )

        except Exception as e:
            logger.error(f"Failed to write trade decision audit log: {e}")
            sentry_sdk.capture_exception(e)
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Audit logging failed — trade not executed for safety",
            )

    async def log_trust_ladder_advance(
        self,
        user_id: str,
        old_stage: int,
        new_stage: int,
        db: AsyncSession,
    ) -> None:
        """Log when user's trust ladder stage advances."""
        try:
            audit_log = AuditLog(
                user_id=user_id,
                event_type="trust_ladder_advance",
                event_details={
                    "old_stage": old_stage,
                    "new_stage": new_stage,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            db.add(audit_log)
            await db.commit()
            logger.info(f"User {user_id} trust ladder advanced: {old_stage} → {new_stage}")
        except Exception as e:
            logger.warning(f"Failed to log trust ladder advance: {e}")
            sentry_sdk.capture_exception(e)
            await db.rollback()

    async def log_circuit_breaker_activation(
        self,
        user_id: str,
        current_loss_pct: float,
        max_daily_loss_pct: float,
        db: AsyncSession,
    ) -> None:
        """Log when circuit breaker triggers (daily loss limit reached)."""
        try:
            audit_log = AuditLog(
                user_id=user_id,
                event_type="circuit_breaker",
                event_details={
                    "current_loss_pct": current_loss_pct,
                    "max_daily_loss_pct": max_daily_loss_pct,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            db.add(audit_log)
            await db.commit()
            logger.warning(
                f"Circuit breaker activated for user {user_id}: "
                f"{current_loss_pct}% loss >= {max_daily_loss_pct}% limit"
            )
        except Exception as e:
            logger.warning(f"Failed to log circuit breaker activation: {e}")
            sentry_sdk.capture_exception(e)
            await db.rollback()

    async def log_onboarding_complete(
        self,
        user_id: str,
        db: AsyncSession,
    ) -> None:
        """Log when user completes onboarding."""
        try:
            audit_log = AuditLog(
                user_id=user_id,
                event_type="onboarding_complete",
                event_details={
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            db.add(audit_log)
            await db.commit()
            logger.info(f"Onboarding completed for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to log onboarding complete: {e}")
            sentry_sdk.capture_exception(e)
            await db.rollback()

    # ─────────────────────────────────────────────────────────────────────────
    # ROUTE
    # ─────────────────────────────────────────────────────────────────────────

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
        # Load shared context once for all agents.
        # If trading_account_id is provided, SharedMemory will populate ctx.market_context.
        trading_account_id = payload.get("trading_account_id") if isinstance(payload, dict) else None
        ctx: SharedContext = await SharedMemory.load(
            user_id, db, trading_account_id=str(trading_account_id) if trading_account_id else None
        )
        logger.info(f"Orchestrator route for user {user_id}, action={action}")

        # ── Token budget pre-check (non-P0 actions only) ─────────────────
        agent_name = _ACTION_TO_AGENT.get(action, "conversation")
        try:
            tm = get_token_manager()
            budget_status = await tm.check_budget(agent_name, db)
            if not budget_status.get("allowed", True):
                logger.warning(
                    "Orchestrator: blocking action=%s agent=%s — %s",
                    action, agent_name, budget_status.get("reason"),
                )
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "token_budget_exceeded",
                        "reason": budget_status.get("reason"),
                        "pct_used": budget_status.get("pct_used"),
                        "fallback_model": budget_status.get("fallback_model"),
                    },
                )
        except HTTPException:
            raise
        except Exception as exc:
            # Never fail-close on token-manager errors — log and continue.
            logger.error("TokenManager.check_budget failed (continuing): %s", exc)

        try:
            if action == "trade_analyze":
                return await self._trade_analyze(user_id, ctx, payload, db)

            elif action == "trade_execute":
                return await self._trade_execute(user_id, ctx, payload, db)

            elif action == "chat":
                return await self._chat(user_id, ctx, payload, db)

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
        """Analyze a trading opportunity with market sentiment and personalized explanations.

        Steps:
        1. Check subscription
        2. Check trading_paused
        3. Fetch market sentiment based on trader_class
        4. Call trading_agent.analyze(symbol) with sentiment context
        5. Get expert explanation
        6. Translate to simple explanation
        7. Translate to metaphor explanation
        8. Return merged response with sentiment context
        """
        symbol = payload.get("symbol")
        if not symbol:
            raise ValueError("Missing symbol in payload")

        # When scoped to a trading account, broker comes from DB (market_context), not the UI payload.
        exchange = payload.get("exchange")
        if ctx.market_context is not None:
            ctx.exchange = ctx.market_context.exchange.value
        elif exchange:
            ctx.exchange = exchange.lower()

        # Resolve execution venue for multi-exchange routing
        try:
            venue = await resolve_execution_venue(
                user_id=user_id,
                asset_class=payload.get("asset_class"),
                db=db,
                trust_ladder_stage=ctx.trust_ladder_stage,
            )
            ctx.execution_venue = venue
            ctx.exchange = venue.exchange
        except Exception as exc:
            logger.warning("resolve_execution_venue failed for user %s: %s", user_id, exc)

        # Check subscription
        if not ctx.subscription_active:
            raise HTTPException(status_code=402, detail="Subscription required to analyze trades")

        # Check trading paused
        if ctx.trading_paused:
            raise HTTPException(
                status_code=429,
                detail="Trading paused — daily loss limit reached",
            )

        # Fetch market sentiment (cached 30 minutes per symbol)
        sentiment_agent = SentimentAgent()
        sentiment = await sentiment_agent.get_sentiment(symbol, ctx)

        # Build sentiment context based on trader class
        sentiment_context = self._build_sentiment_context(sentiment, ctx)

        # Call trading agent to analyze
        trading_agent = TradingAgent(user_id=user_id)
        analysis_result = await trading_agent.analyze(symbol=symbol, exchange=ctx.exchange, context=ctx)

        # Extract expert explanation
        expert_explanation = analysis_result.explanation_expert

        # Translate to simple explanation
        simple_explanation = await trading_agent.translate_explanation(
            expert_text=expert_explanation,
            target="simple",
            context=ctx,
        )

        # Translate to metaphor explanation
        metaphor_explanation = await trading_agent.translate_explanation(
            expert_text=expert_explanation,
            target="metaphor",
            context=ctx,
        )

        # Compute absolute price levels from percentages
        entry_price = analysis_result.market_data.get("price", 0) if analysis_result.market_data else 0
        sl_pct = analysis_result.suggested_stop_loss_pct
        tp_pct = analysis_result.suggested_take_profit_pct
        stop_loss = round(entry_price * (1 - sl_pct / 100), 4) if entry_price and sl_pct else None
        take_profit = round(entry_price * (1 + tp_pct / 100), 4) if entry_price and tp_pct else None

        # Extract technical indicators for experienced-user display
        indicators = analysis_result.market_data.get("indicators", {}) if analysis_result.market_data else {}

        signal = analysis_result.signal  # "buy" | "sell" | "wait"

        return {
            **analysis_result.model_dump(),
            # ── Frontend-expected field names ────────────────────────────────────
            "status": "wait" if signal == "wait" else "executed",
            "decision": signal.upper(),          # "BUY" | "SELL" | "WAIT"
            # Top-level explanations (frontend reads these directly)
            "expert": expert_explanation,
            "simple": simple_explanation,
            "metaphor": metaphor_explanation,
            # Absolute price levels
            "entry_price": entry_price if entry_price else None,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            # Technical indicators for experienced traders
            "rsi": indicators.get("rsi"),
            "macd": indicators.get("macd", {}).get("histogram") if indicators.get("macd") else None,
            "volume_ratio": indicators.get("volume_ratio"),
            "market_trend": analysis_result.market_data.get("trend") if analysis_result.market_data else None,
            # ── Nested versions preserved ────────────────────────────────────────
            "explanations": {
                "expert": expert_explanation,
                "simple": simple_explanation,
                "metaphor": metaphor_explanation,
            },
            "sentiment": sentiment,
            "sentiment_context": sentiment_context,
        }

    def _build_sentiment_context(self, sentiment: dict, ctx: SharedContext) -> str:
        """Build sentiment context injection based on trader class.

        Args:
            sentiment: Dict from SentimentAgent.get_sentiment() with sentiment data
            ctx: SharedContext with trader_class and user settings

        Returns:
            String to inject into trading agent context
        """
        context_parts = []

        # Check for earnings alert - applies to ALL trader classes
        if sentiment.get("earnings_alert"):
            earnings_date = sentiment.get("earnings_date", "unknown")
            context_parts.append(
                f"⚠️ EARNINGS ALERT: Earnings announced for {earnings_date}. "
                f"Reduce signal confidence by 50% due to pre-earnings volatility."
            )

        # Check for extreme crypto fear (Fear & Greed < 20) - crypto_native only
        if (
            ctx.is_crypto_native()
            and sentiment.get("fear_greed_index") is not None
            and sentiment["fear_greed_index"] < 20
        ):
            context_parts.append(
                f"🔴 CRYPTO FEAR: Fear & Greed Index is {sentiment['fear_greed_index']} (extreme fear). "
                f"Market is in panic mode. Apply extra caution."
            )

        # Inject sentiment summary based on trader class
        if ctx.is_pro() or ctx.is_intermediate():
            # Full sentiment + headlines for experienced traders
            if sentiment.get("sentiment_summary"):
                context_parts.append(f"Market Sentiment: {sentiment['sentiment_summary']}")
            if sentiment.get("headlines"):
                headlines_text = " | ".join(sentiment["headlines"])
                context_parts.append(f"Latest Headlines: {headlines_text}")
        else:
            # Simple sentiment for novices and crypto natives
            if sentiment.get("sentiment_summary_simple"):
                context_parts.append(f"Market Sentiment: {sentiment['sentiment_summary_simple']}")

        return "\n".join(context_parts) if context_parts else ""

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
        """Execute a trade with full risk and portfolio checks + comprehensive audit logging.

        Steps:
        1. Load context + all prerequisite checks
        2. Call trading_agent.analyze() for signal + reasoning + market data
        3. Risk agent check: can_open_position(symbol, amount)
        4. Portfolio agent check: evaluate_new_trade(symbol, side, amount)
        5. Write comprehensive AuditLog via log_trade_decision BEFORE execution
        6. Execute: paper_trading_enabled → execute_paper, else execute_live
        7. Invalidate shared_memory cache
        8. Return trade result

        CRITICAL: If audit logging fails, raises HTTPException 500 and does NOT execute trade.
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

        # Risk disclosure check for real money trading (trust_ladder_stage >= 2)
        if ctx.trust_ladder_stage >= 2 and not ctx.risk_disclosure_accepted:
            raise HTTPException(
                status_code=403,
                detail="Risk disclosure not accepted — real money trading requires risk acknowledgement",
            )

        # Trade amount validation against trader-class limits + Trust Ladder stage
        amount_check = validate_trade_amount(float(amount), ctx)
        if not amount_check["valid"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": amount_check["reason"],
                    "min_trade_amount": amount_check["min"],
                    "max_trade_amount": amount_check["max"],
                },
            )

        # Resolve execution venue so agents use the correct exchange
        try:
            venue = await resolve_execution_venue(
                user_id=user_id,
                asset_class=payload.get("asset_class"),
                db=db,
                trust_ladder_stage=ctx.trust_ladder_stage,
            )
            ctx.execution_venue = venue
            ctx.exchange = venue.exchange
        except Exception as exc:
            logger.warning("resolve_execution_venue failed for user %s: %s", user_id, exc)

        # Step 2: Get AI analysis with signal, explanation, confidence, market data
        trading_agent = TradingAgent(user_id=user_id)
        agent_analysis = await trading_agent.analyze(symbol=symbol, exchange=ctx.exchange, context=ctx)

        # Import risk and portfolio agents
        from src.agents.core.risk_agent import RiskAgent
        from src.agents.core.portfolio_agent import PortfolioAgent

        # Step 3: Risk agent validation
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

        # Step 4: Portfolio agent validation
        portfolio_agent = PortfolioAgent()
        portfolio_check = await portfolio_agent.evaluate_new_trade(
            user_id=user_id,
            symbol=symbol,
            side=side,
            amount=amount,
            ctx=ctx,
            db=db,
        )

        if not portfolio_check.get("approved"):
            return {
                "success": False,
                "reason": portfolio_check.get("reason"),
            }

        # Step 5: Write comprehensive audit log BEFORE execution
        # CRITICAL: If this fails, raises HTTPException 500 and trade is NOT executed
        risk_result = (risk_check.get("allowed"), risk_check.get("reason", ""))
        await self.log_trade_decision(
            user_id=user_id,
            payload=payload,
            ctx=ctx,
            risk_result=risk_result,
            portfolio_result=portfolio_check,
            agent_response=agent_analysis.model_dump(),
            db=db,
        )

        # Step 6: Execute trade
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

        # Step 7: Invalidate cache
        SharedMemory.invalidate(user_id)

        # Step 8: Return result
        return trade_result

    # ─────────────────────────────────────────────────────────────────────────
    # CHAT (post-onboarding trading chat)
    # ─────────────────────────────────────────────────────────────────────────

    async def _chat(
        self,
        user_id: str,
        ctx: SharedContext,
        payload: dict,
        db: AsyncSession,
    ) -> dict:
        """Route to ConversationAgent.handle_message() with the route() SharedContext.

        Returns a normalised dict with keys the frontend expects:
          response, context_label, message (alias), completed=False
        """
        message = payload.get("message")
        if not message:
            raise ValueError("Missing message in payload")

        conv_agent = ConversationAgent(user_id=user_id)
        channel = str(payload.get("channel") or "web_app")
        # Pass db=None so respond() manages its own sessions — avoids failures
        # if the request-scoped session is in an aborted PG transaction state.
        # Pass ctx from route() so we do not reload SharedMemory and lose market_context.
        result = await conv_agent.handle_message(
            message=message, context=ctx, db=None, channel=channel
        )

        # Normalise: expose both 'response' and 'message' so either frontend
        # field read pattern works
        result.setdefault("message", result.get("response", ""))
        result.setdefault("completed", False)
        return result

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

        conv_agent = ConversationAgent(user_id=user_id)
        response = await conv_agent.chat(
            user_message=message,
            mode="onboarding",
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

        trading_agent = TradingAgent(user_id=user_id)
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
