"""
src/agents/core/trading_agent.py — Core AI trading agent for Unitrader.

The TradingAgent ties together:
  - Market analysis (price, indicators, trend)
  - Claude LLM decision-making
  - Personalisation from trade history
  - Hard safety guardrails
  - Exchange execution
  - Database logging
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import ExchangeAPIKey, Trade, User, UserSettings
from security import decrypt_api_key
from src.integrations.exchange_client import get_exchange_client
from src.integrations.market_data import full_market_analysis
from src.services.trade_execution import build_trade_parameters
from src.utils.json_parser import parse_claude_json
from src.services.learning_hub import (
    get_trading_insights,
    get_active_instructions,
    record_agent_output,
)

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-3-haiku-20240307"

_SYSTEM_PROMPT = """\
You are a professional quantitative trading AI assistant named {ai_name}.
Your job is to analyse market data and make precise trading decisions.

RULES YOU MUST FOLLOW:
1. Risk at most 2% of account balance per trade.
2. Every trade MUST have a stop-loss. Never trade without one.
3. Only trade when confidence is 50 or above.
4. Prefer a risk-to-reward ratio of at least 2:1.
5. When in doubt, output WAIT — preserving capital is always valid.
6. Be concise and logical. No speculation — only data-driven decisions.
{learning_context}
RESPONSE FORMAT (strict JSON, no markdown, no extra text):
{{
  "decision": "BUY" | "SELL" | "WAIT",
  "confidence": <integer 0-100>,
  "entry_price": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "position_size_pct": <float, max 2.0>,
  "reasoning": "<1-2 sentences explaining the decision>"
}}
"""

_USER_PROMPT_TEMPLATE = """\
CURRENT MARKET DATA FOR {symbol} on {exchange}:

Price:          ${price:,.4f}
24h High:       ${high_24h:,.4f}
24h Low:        ${low_24h:,.4f}
24h Volume:     ${volume:,.0f}
24h Change:     {price_change_pct:+.2f}%
Trend:          {trend}

TECHNICAL INDICATORS:
  RSI (14):     {rsi:.1f}
  MACD Line:    {macd_line:.6f}
  MACD Signal:  {macd_signal:.6f}
  MACD Hist:    {macd_hist:.6f}
  MA(20):       ${ma20:,.4f}
  MA(50):       ${ma50:,.4f}
  MA(200):      ${ma200:,.4f}

SUPPORT / RESISTANCE:
  Support:      ${support:,.4f}
  Pivot:        ${pivot:,.4f}
  Resistance:   ${resistance:,.4f}

ACCOUNT:
  Balance:      ${account_balance:,.2f} USD
  Open Trades:  {open_trades_count}

USER HISTORY (last 50 similar trades):
  Win Rate:     {win_rate:.1f}%
  Avg Profit:   {avg_profit:.2f}%
  Avg Loss:     {avg_loss:.2f}%

Provide your trading decision in the required JSON format.
"""


class TradingAgent:
    """AI-driven trading agent scoped to a single user.

    Lifecycle per cycle:
        1. analyze_market()      — gather data
        2. get_claude_decision() — ask Claude
        3. personalize_decision() — adjust sizing from history
        4. _safety_checks()      — hard guardrails
        5. execute_trade()       — place orders + persist
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # ─────────────────────────────────────────────
    # Market Analysis
    # ─────────────────────────────────────────────

    async def analyze_market(self, symbol: str, exchange: str) -> dict:
        """Fetch live data and compute technical indicators.

        Returns the full market snapshot dict used to build the Claude prompt.
        """
        try:
            data = await full_market_analysis(symbol, exchange)
            logger.info("Market analysis complete: %s @ %.4f", symbol, data.get("price", 0))
            return data
        except Exception as exc:
            logger.error("analyze_market failed for %s/%s: %s", symbol, exchange, exc)
            raise

    # ─────────────────────────────────────────────
    # User History Context
    # ─────────────────────────────────────────────

    async def _get_user_history(
        self, db: AsyncSession, symbol: str
    ) -> dict:
        """Return win-rate and avg P&L for the user's last 50 closed trades on this symbol."""
        result = await db.execute(
            select(Trade)
            .where(
                Trade.user_id == self.user_id,
                Trade.symbol == symbol,
                Trade.status == "closed",
            )
            .order_by(Trade.closed_at.desc())
            .limit(50)
        )
        trades = result.scalars().all()

        if not trades:
            return {"win_rate": 50.0, "avg_profit": 0.0, "avg_loss": 0.0, "count": 0}

        wins = [t for t in trades if (t.profit or 0) > 0]
        losses = [t for t in trades if (t.loss or 0) > 0]

        win_rate = len(wins) / len(trades) * 100 if trades else 50.0
        avg_profit = (sum(t.profit_percent or 0 for t in wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(t.profit_percent or 0 for t in losses) / len(losses)) if losses else 0.0

        return {
            "win_rate": round(win_rate, 1),
            "avg_profit": round(avg_profit, 2),
            "avg_loss": round(avg_loss, 2),
            "count": len(trades),
        }

    async def _get_open_trade_count(self, db: AsyncSession) -> int:
        result = await db.execute(
            select(func.count()).where(
                Trade.user_id == self.user_id,
                Trade.status == "open",
            )
        )
        return result.scalar() or 0

    # ─────────────────────────────────────────────
    # Claude Decision
    # ─────────────────────────────────────────────

    async def get_claude_decision(
        self,
        market_data: dict,
        user_history: dict,
        account_balance: float,
        open_trades_count: int,
        ai_name: str = "Claude",
        learning_context: str = "",
    ) -> dict:
        """Send market data to Claude and parse the trading decision.

        Returns:
            {
                "decision": "BUY",
                "confidence": 78,
                "entry_price": 45000.0,
                "stop_loss": 44100.0,
                "take_profit": 46800.0,
                "position_size_pct": 1.5,
                "reasoning": "...",
            }
        """
        if not settings.anthropic_api_key:
            logger.warning("Anthropic API key not set — returning WAIT decision")
            return self._wait_decision("Anthropic API key not configured")

        indicators = market_data.get("indicators", {})
        macd = indicators.get("macd", {})
        sr = market_data.get("support_resistance", {})

        prompt = _USER_PROMPT_TEMPLATE.format(
            symbol=market_data.get("symbol", "UNKNOWN"),
            exchange=market_data.get("exchange", "unknown"),
            price=market_data.get("price", 0),
            high_24h=market_data.get("high_24h", 0),
            low_24h=market_data.get("low_24h", 0),
            volume=market_data.get("volume", 0),
            price_change_pct=market_data.get("price_change_pct", 0),
            trend=market_data.get("trend", "unknown"),
            rsi=indicators.get("rsi", 50),
            macd_line=macd.get("line", 0),
            macd_signal=macd.get("signal", 0),
            macd_hist=macd.get("histogram", 0),
            ma20=indicators.get("ma20", 0),
            ma50=indicators.get("ma50", 0),
            ma200=indicators.get("ma200", 0),
            support=sr.get("support", 0),
            pivot=sr.get("pivot", 0),
            resistance=sr.get("resistance", 0),
            account_balance=account_balance,
            open_trades_count=open_trades_count,
            win_rate=user_history.get("win_rate", 50),
            avg_profit=user_history.get("avg_profit", 0),
            avg_loss=user_history.get("avg_loss", 0),
        )

        try:
            response = await self._claude.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=512,
                system=_SYSTEM_PROMPT.format(
                    ai_name=ai_name,
                    learning_context=learning_context,
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            decision = parse_claude_json(raw, context="trade decision")
            logger.info(
                "Claude decision: %s (confidence=%s) for %s",
                decision.get("decision"),
                decision.get("confidence"),
                market_data.get("symbol"),
            )
            return decision
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON trade decision: %s", raw[:200])
            return self._wait_decision("Claude response parse error")
        except Exception as exc:
            logger.error("Claude API call failed: %s", exc)
            return self._wait_decision(str(exc))

    @staticmethod
    def _wait_decision(reason: str) -> dict:
        return {
            "decision": "WAIT",
            "confidence": 0,
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "position_size_pct": 0.0,
            "reasoning": reason,
        }

    # ─────────────────────────────────────────────
    # Personalisation
    # ─────────────────────────────────────────────

    async def personalize_decision(
        self,
        decision: dict,
        user_history: dict,
        insights: dict | None = None,
    ) -> dict:
        """Adjust position size from user history + learning hub insights.

        User history rules:
          - Win rate > 65 % → +10 % size (capped at 2 %)
          - Win rate < 40 % → -25 % size

        Learning hub rules (applied after user history):
          - focus_condition matches current trend  → apply position_size_modifier
          - avoid_condition matches current trend  → WAIT (skip trade)
        """
        if decision.get("decision") == "WAIT":
            return decision

        win_rate = user_history.get("win_rate", 50)
        size = decision.get("position_size_pct", 1.0)

        # ── User history personalisation ──────────────────────────────────
        if win_rate > 65 and user_history.get("count", 0) >= 10:
            size = min(size * 1.10, 2.0)
            logger.debug("Personalisation: +10%% size (win_rate=%.1f%%)", win_rate)
        elif win_rate < 40 and user_history.get("count", 0) >= 10:
            size = size * 0.75
            logger.debug("Personalisation: -25%% size (win_rate=%.1f%%)", win_rate)

        # ── Learning hub insights ─────────────────────────────────────────
        if insights and insights.get("has_insights"):
            trend = decision.get("market_trend", "")
            avoid = insights.get("avoid_condition")
            focus = insights.get("focus_condition")
            modifier = insights.get("position_size_modifier", 1.0)

            if avoid and trend and avoid.lower() in trend.lower():
                logger.info(
                    "LearningHub: skipping trade — avoid_condition '%s' matches trend '%s'",
                    avoid, trend,
                )
                decision["decision"] = "WAIT"
                decision["reasoning"] = (
                    f"Learning hub: skipping {trend} market — "
                    f"historical data shows low win rate."
                )
                return decision

            if focus and trend and focus.lower() in trend.lower():
                size = min(size * modifier, 2.0)
                logger.info(
                    "LearningHub: boosting size ×%.2f for focus condition '%s'",
                    modifier, focus,
                )
            elif insights.get("avoid_setups"):
                # General caution if avoid setups exist but no direct match
                size = min(size, 1.5)

        decision["position_size_pct"] = round(size, 2)
        return decision

    # ─────────────────────────────────────────────
    # Safety Guardrails
    # ─────────────────────────────────────────────

    async def _safety_checks(
        self,
        decision: dict,
        account_balance: float,
        user_settings: UserSettings,
        db: AsyncSession,
    ) -> dict:
        """Enforce hard risk limits before any order is placed.

        Returns:
            {"allowed": True} or {"allowed": False, "reason": "..."}
        """
        if decision.get("decision") == "WAIT":
            return {"allowed": False, "reason": "Decision is WAIT"}

        # 1. Position size ≤ 2 %
        if decision.get("position_size_pct", 0) > 2.0:
            decision["position_size_pct"] = 2.0

        # 2. Stop loss mandatory
        if not decision.get("stop_loss") or decision["stop_loss"] <= 0:
            return {"allowed": False, "reason": "No stop-loss provided by Claude"}

        # 3. Confidence threshold
        if decision.get("confidence", 0) < 50:
            return {"allowed": False, "reason": f"Confidence {decision['confidence']} < 50"}

        # 4. Sufficient balance
        position_usd = account_balance * (decision["position_size_pct"] / 100)
        if position_usd < 1.0:
            return {"allowed": False, "reason": "Insufficient balance for minimum trade size"}

        # 5. Max daily loss check
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await db.execute(
            select(func.sum(Trade.loss)).where(
                Trade.user_id == self.user_id,
                Trade.closed_at >= today_start,
                Trade.status == "closed",
            )
        )
        daily_loss = abs(result.scalar() or 0)
        max_daily_loss_usd = account_balance * ((user_settings.max_daily_loss or 5.0) / 100)

        if daily_loss >= max_daily_loss_usd:
            return {
                "allowed": False,
                "reason": f"Daily loss limit reached (${daily_loss:.2f} / ${max_daily_loss_usd:.2f})",
            }

        # 6. Max position size from user settings
        max_pos_pct = user_settings.max_position_size or 2.0
        if decision["position_size_pct"] > max_pos_pct:
            decision["position_size_pct"] = max_pos_pct

        return {"allowed": True}

    # ─────────────────────────────────────────────
    # Execute Trade
    # ─────────────────────────────────────────────

    async def execute_trade(
        self,
        decision: dict,
        symbol: str,
        exchange_name: str,
        ai_name: str = "Claude",
    ) -> dict:
        """Orchestrate the full trade lifecycle: safety → order → DB → notify.

        Returns:
            {"status": "executed", "trade_id": "..."} or
            {"status": "rejected", "reason": "..."}
        """
        async with AsyncSessionLocal() as db:
            # Load user + settings
            user_result = await db.execute(select(User).where(User.id == self.user_id))
            user = user_result.scalar_one_or_none()
            if not user or not user.is_active:
                return {"status": "rejected", "reason": "User not found or inactive"}

            settings_result = await db.execute(
                select(UserSettings).where(UserSettings.user_id == self.user_id)
            )
            user_settings = settings_result.scalar_one_or_none()
            if not user_settings:
                user_settings = UserSettings(user_id=self.user_id)

            # Load decrypted API key
            key_result = await db.execute(
                select(ExchangeAPIKey).where(
                    ExchangeAPIKey.user_id == self.user_id,
                    ExchangeAPIKey.exchange == exchange_name,
                    ExchangeAPIKey.is_active == True,  # noqa: E712
                )
            )
            api_key_row = key_result.scalar_one_or_none()
            if not api_key_row:
                return {"status": "rejected", "reason": f"No active API key for {exchange_name}"}

            try:
                raw_key, raw_secret = decrypt_api_key(
                    api_key_row.encrypted_api_key,
                    api_key_row.encrypted_api_secret,
                )
            except Exception as exc:
                logger.error("Failed to decrypt API key: %s", exc)
                return {"status": "rejected", "reason": "Could not decrypt exchange API key"}

            # Get exchange client + balance
            client = get_exchange_client(exchange_name, raw_key, raw_secret)
            try:
                account_balance = await client.get_account_balance()
            except Exception as exc:
                return {"status": "rejected", "reason": f"Exchange balance fetch failed: {exc}"}

            # Safety checks
            guard = await self._safety_checks(decision, account_balance, user_settings, db)
            if not guard["allowed"]:
                logger.info(
                    "Trade rejected for user %s: %s", self.user_id, guard["reason"]
                )
                return {"status": "rejected", "reason": guard["reason"]}

            # Build precise parameters
            params = build_trade_parameters(
                confidence=decision["confidence"],
                entry_price=decision["entry_price"],
                side=decision["decision"],
                account_balance=account_balance,
            )
            if not params.get("tradeable"):
                return {"status": "rejected", "reason": params.get("reason", "Not tradeable")}

            # Place the order
            start_time = datetime.now(timezone.utc)
            try:
                order_id = await client.place_order(
                    symbol=symbol,
                    side=decision["decision"],
                    quantity=params["quantity"],
                    price=decision["entry_price"],
                )
            except Exception as exc:
                logger.error("Order placement failed: %s", exc)
                return {"status": "rejected", "reason": f"Order placement failed: {exc}"}

            execution_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            # Place stop-loss
            await client.set_stop_loss(symbol, order_id, decision["stop_loss"])

            # Place take-profit
            await client.set_take_profit(symbol, order_id, decision["take_profit"])

            # Persist to database
            trade = Trade(
                user_id=self.user_id,
                symbol=symbol,
                side=decision["decision"],
                quantity=params["quantity"],
                entry_price=decision["entry_price"],
                stop_loss=decision["stop_loss"],
                take_profit=decision["take_profit"],
                status="open",
                claude_confidence=float(decision["confidence"]),
                market_condition=decision.get("market_condition", "unknown"),
                execution_time=round(execution_ms, 2),
            )
            db.add(trade)
            await db.flush()
            trade_id = trade.id

            await db.commit()
            await client.aclose()

        logger.info(
            "%s executed %s %s @ %.4f (trade_id=%s)",
            ai_name, decision["decision"], symbol, decision["entry_price"], trade_id,
        )

        return {
            "status": "executed",
            "trade_id": trade_id,
            "symbol": symbol,
            "side": decision["decision"],
            "entry_price": decision["entry_price"],
            "stop_loss": decision["stop_loss"],
            "take_profit": decision["take_profit"],
            "quantity": params["quantity"],
            "position_size_usd": params["size_amount"],
            "confidence": decision["confidence"],
            "reasoning": decision.get("reasoning", ""),
            "message": (
                f"{ai_name} executed {decision['decision']} on {symbol} "
                f"@ ${decision['entry_price']:,.4f} "
                f"(confidence {decision['confidence']}%)"
            ),
        }

    # ─────────────────────────────────────────────
    # Full Cycle (analyze → decide → execute)
    # ─────────────────────────────────────────────

    async def run_cycle(self, symbol: str, exchange_name: str) -> dict:
        """Run a complete analysis → decision → execution cycle.

        Enhanced with Learning Hub insights:
          1. Fetch active hub insights + instructions before analysis
          2. Inject learning context into Claude's system prompt
          3. Apply hub-guided position sizing / condition filters
          4. Log the outcome back to hub via record_agent_output()
        """
        # ── Step 0: Fetch learning hub insights (non-blocking fallback) ───
        try:
            insights = await get_trading_insights()
            instructions = await get_active_instructions("trading")
        except Exception as exc:
            logger.warning("LearningHub insights unavailable: %s", exc)
            insights = {"has_insights": False}
            instructions = []

        # Build learning context string to inject into system prompt
        learning_context = ""
        if insights.get("has_insights"):
            parts: list[str] = []
            if insights.get("high_confidence_setups"):
                parts.append(
                    "HIGH WIN-RATE SETUPS (prioritise these):\n"
                    + "\n".join(f"  - {s}" for s in insights["high_confidence_setups"])
                )
            if insights.get("avoid_setups"):
                parts.append(
                    "SETUPS TO AVOID (lower win-rate historically):\n"
                    + "\n".join(f"  - {s}" for s in insights["avoid_setups"])
                )
            if instructions:
                parts.append(
                    "LEARNING HUB DIRECTIVE:\n"
                    + "\n".join(f"  [{i['priority']}] {i['instruction']}" for i in instructions)
                )
            if parts:
                learning_context = (
                    "\nLEARNING INSIGHTS FROM PATTERN ANALYSIS:\n"
                    + "\n".join(parts)
                    + "\n"
                )

        # ── Step 1: Load user + exchange ──────────────────────────────────
        async with AsyncSessionLocal() as db:
            user_result = await db.execute(select(User).where(User.id == self.user_id))
            user = user_result.scalar_one_or_none()
            ai_name = user.ai_name if user else "Claude"

            user_history = await self._get_user_history(db, symbol)
            open_count   = await self._get_open_trade_count(db)

            try:
                balance_key = await db.execute(
                    select(ExchangeAPIKey).where(
                        ExchangeAPIKey.user_id == self.user_id,
                        ExchangeAPIKey.exchange == exchange_name,
                        ExchangeAPIKey.is_active == True,  # noqa: E712
                    )
                )
                key_row = balance_key.scalar_one_or_none()
                if not key_row:
                    return {"status": "skipped", "reason": "No API key configured"}
                raw_key, raw_secret = decrypt_api_key(
                    key_row.encrypted_api_key, key_row.encrypted_api_secret
                )
                client = get_exchange_client(exchange_name, raw_key, raw_secret)
                account_balance = await client.get_account_balance()
                await client.aclose()
            except Exception as exc:
                return {"status": "error", "reason": str(exc)}

        # ── Step 2: Market analysis ───────────────────────────────────────
        market_data = await self.analyze_market(symbol, exchange_name)
        market_data["exchange"] = exchange_name

        # ── Step 3: Claude decision (with learning context injected) ──────
        decision = await self.get_claude_decision(
            market_data, user_history, account_balance, open_count,
            ai_name, learning_context=learning_context,
        )

        # Pass market trend into decision dict for personalize_decision to read
        decision["market_trend"] = market_data.get("trend", "")

        # ── Step 4: Personalise + apply learning hub condition filters ────
        decision = await self.personalize_decision(decision, user_history, insights)

        if decision["decision"] == "WAIT":
            await record_agent_output(
                agent_name="trading",
                output_type="trade",
                content={"symbol": symbol, "decision": "WAIT", "reasoning": decision.get("reasoning", "")},
                outcome="skipped",
                metrics={"confidence": decision.get("confidence", 0)},
            )
            return {
                "status": "wait",
                "symbol": symbol,
                "reasoning": decision.get("reasoning", ""),
            }

        # ── Step 5: Execute ───────────────────────────────────────────────
        result = await self.execute_trade(decision, symbol, exchange_name, ai_name)

        # ── Step 6: Log outcome to learning hub ──────────────────────────
        outcome = "success" if result.get("status") == "executed" else "failure"
        instr_id = instructions[0]["id"] if instructions else None
        await record_agent_output(
            agent_name="trading",
            output_type="trade",
            content={
                "symbol": symbol,
                "decision": decision.get("decision"),
                "confidence": decision.get("confidence"),
                "trend": market_data.get("trend"),
                "learning_applied": insights.get("has_insights", False),
            },
            outcome=outcome,
            metrics={
                "confidence": decision.get("confidence", 0),
                "position_size_pct": decision.get("position_size_pct", 0),
            },
            source_instruction_id=instr_id,
        )

        return result

    # ─────────────────────────────────────────────
    # Close Position
    # ─────────────────────────────────────────────

    async def close_position(self, trade_id: str) -> dict:
        """Manually close an open position and record the result.

        Returns the final trade result with profit/loss figures.
        """
        async with AsyncSessionLocal() as db:
            trade_result = await db.execute(
                select(Trade).where(
                    Trade.id == trade_id,
                    Trade.user_id == self.user_id,
                    Trade.status == "open",
                )
            )
            trade = trade_result.scalar_one_or_none()
            if not trade:
                return {"status": "error", "reason": "Trade not found or already closed"}

            key_result = await db.execute(
                select(ExchangeAPIKey).where(
                    ExchangeAPIKey.user_id == self.user_id,
                    ExchangeAPIKey.exchange.in_(["binance", "alpaca", "oanda"]),
                    ExchangeAPIKey.is_active == True,  # noqa: E712
                )
            )
            key_row = key_result.scalars().first()
            if not key_row:
                return {"status": "error", "reason": "No active exchange API key"}

            raw_key, raw_secret = decrypt_api_key(
                key_row.encrypted_api_key, key_row.encrypted_api_secret
            )
            client = get_exchange_client(key_row.exchange, raw_key, raw_secret)

            try:
                current_price = await client.get_current_price(trade.symbol)
                await client.close_position(trade.symbol)
            except Exception as exc:
                await client.aclose()
                return {"status": "error", "reason": str(exc)}
            finally:
                await client.aclose()

            # Calculate P&L
            if trade.side == "BUY":
                pnl = (current_price - trade.entry_price) * trade.quantity
            else:
                pnl = (trade.entry_price - current_price) * trade.quantity

            pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
            if trade.side == "SELL":
                pnl_pct = -pnl_pct

            trade.exit_price = current_price
            trade.status = "closed"
            trade.closed_at = datetime.now(timezone.utc)
            if pnl >= 0:
                trade.profit = round(pnl, 2)
                trade.profit_percent = round(pnl_pct, 4)
            else:
                trade.loss = round(abs(pnl), 2)
                trade.profit_percent = round(pnl_pct, 4)

            await db.commit()

        result = {
            "status": "closed",
            "trade_id": trade_id,
            "symbol": trade.symbol,
            "exit_price": current_price,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
        }
        logger.info("Position closed: %s P&L=%.2f", trade_id, pnl)
        return result
