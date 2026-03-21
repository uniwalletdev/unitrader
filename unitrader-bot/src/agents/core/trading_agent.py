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
import httpx
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import AuditLog, ExchangeAPIKey, Trade, User, UserSettings
from security import decrypt_api_key
from src.agents.shared_memory import SharedContext
from src.integrations.exchange_client import get_exchange_client
from src.integrations.market_data import full_market_analysis, normalise_symbol
from src.services.trade_execution import build_trade_parameters
from src.utils.json_parser import parse_claude_json
from src.services.learning_hub import (
    get_trading_insights,
    get_active_instructions,
    record_agent_output,
)

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-3-haiku-20240307"

# ─────────────────────────────────────────────
# Trader-class trade-size limits (in GBP/USD)
# ─────────────────────────────────────────────

CLASS_TRADE_LIMITS: dict[str, dict[str, float]] = {
    "complete_novice":    {"min": 25,  "max": 25},
    "curious_saver":      {"min": 10,  "max": 500},
    "self_taught":        {"min": 5,   "max": 5000},
    "experienced":        {"min": 1,   "max": 10000},
    "semi_institutional": {"min": 1,   "max": 50000},
    "crypto_native":      {"min": 5,   "max": 5000},
}


def validate_trade_amount(amount: float, ctx: SharedContext) -> dict:
    """Validate trade amount against trader-class limits and Trust Ladder stage.

    Trust Ladder overrides:
      Stage 1 (Micro Mode) — always caps at 25, regardless of class.
      Stage >= 2 (Standard) — non-novice classes use their full class max.

    Returns:
        {"valid": True, "min": n, "max": n}
        or {"valid": False, "reason": str, "min": n, "max": n}
    """
    limits = dict(CLASS_TRADE_LIMITS.get(ctx.trader_class, CLASS_TRADE_LIMITS["complete_novice"]))

    # Trust Ladder Stage 1 — micro mode, hard cap at 25
    if ctx.trust_ladder_stage == 1:
        limits = {"min": 25, "max": 25}
    elif ctx.trust_ladder_stage >= 2 and not ctx.is_novice():
        # Non-novice traders at Stage 2+ keep their full class max
        limits["max"] = CLASS_TRADE_LIMITS.get(ctx.trader_class, {}).get("max", 5000)

    if amount < limits["min"]:
        return {
            "valid": False,
            "reason": f"Minimum trade amount is £{limits['min']} for your account level.",
            "min": limits["min"],
            "max": limits["max"],
        }

    if amount > limits["max"]:
        return {
            "valid": False,
            "reason": f"Maximum trade amount is £{limits['max']} for your account level.",
            "min": limits["min"],
            "max": limits["max"],
        }

    return {"valid": True, "min": limits["min"], "max": limits["max"]}


class TradingDecision(BaseModel):
    """Normalized trade decision returned to the orchestrator.

    This is the *decision* stage only — execution is handled separately by the
    orchestrator + existing TradingAgent execution logic.
    """

    action: str = Field(..., pattern="^(BUY|SELL|HOLD)$")
    asset: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    suggested_size_pct: float = Field(..., ge=0.0)
    stop_loss_pct: float = Field(..., ge=0.0)
    take_profit_pct: float = Field(..., ge=0.0)
    risk_factors: list[str] = Field(default_factory=list)


class TradeAnalysis(BaseModel):
    """Detailed AI trade analysis with expert explanation and market context.
    
    Returned by analyze() method when analyzing with SharedContext.
    """

    signal: str = Field(..., pattern="^(buy|sell|wait)$")
    confidence: int = Field(..., ge=0, le=100)
    explanation_expert: str
    key_factors: list[dict]
    suggested_stop_loss_pct: float = Field(..., ge=0.0)
    suggested_take_profit_pct: float = Field(..., ge=0.0)
    market_data: dict


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

_ANALYZE_SYSTEM_PROMPT = """\
You are {ai_name}, a professional AI trading analyst.

USER PROFILE:
- Goal: {goal}
- Risk Tolerance: {risk_level}
- Account Stage: {trust_ladder_stage}/5 (1=paper/learning, 5=full autonomy)
- Max Position Size: {max_position_pct}% of account per trade
- Mode: {trade_mode}

ANALYSIS RULES:
1. Every trade MUST have a stop-loss. Never trade without one.
2. Only signal BUY/SELL when confidence ≥ 50.
3. For {risk_level} traders: {risk_guidance}
4. For trust level {trust_ladder_stage}: {trust_guidance}
5. Return ONLY the specified JSON format. No markdown, no extra text.

RESPONSE FORMAT (strict JSON, no markdown):
{{
  "signal": "buy" | "sell" | "wait",
  "confidence": <integer 0-100>,
  "explanation_expert": "<technical analysis with RSI, MACD, MA, volume levels>",
  "key_factors": [
    {{"label": "<factor name>", "sentiment": "positive|negative|neutral", "detail": "<brief explanation>"}}
  ],
  "suggested_stop_loss_pct": <float>,
  "suggested_take_profit_pct": <float>,
  "market_data": {{
    "price": <current price>,
    "rsi": <RSI value 0-100>,
    "macd": <MACD histogram value>,
    "above_20ma": <boolean>,
    "volume_ratio": <24h volume / avg volume>
  }}
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

    async def analyze_market(self, symbol: str, exchange: str) -> dict | None:
        """Fetch live data and compute technical indicators.

        Returns the full market snapshot dict, or None if market data
        is unavailable or routing/exchange errors occur. Never raises.
        """
        try:
            clean_symbol = symbol
            if "/" in symbol:
                parts = symbol.split("/")
                if len(parts) == 3:
                    clean_symbol = f"{parts[0]}/{parts[1]}"
            
            # Log the request details for debugging
            logger.debug("Market analysis request: symbol=%s, exchange=%s, cleaned=%s", 
                        symbol, exchange, clean_symbol)
            
            data = await full_market_analysis(clean_symbol, exchange)
            logger.info("Market analysis complete: %s/%s @ %.4f", clean_symbol, exchange, data.get("price", 0))
            return data
        except httpx.HTTPStatusError as exc:
            status_code = getattr(exc.response, "status_code", None)
            url = getattr(exc.response, "url", "unknown")
            
            # Provide specific guidance for common errors
            error_detail = ""
            if status_code == 401:
                error_detail = " — Check Alpaca API credentials (APCA-API-KEY-ID/APCA-API-SECRET-KEY)"
            elif status_code == 404:
                # Common case: crypto symbol routed to stock endpoint
                if symbol and ("/" in symbol or symbol.upper() in ["BTC", "ETH", "SOL"]):
                    error_detail = f" — Symbol {symbol} appears to be crypto but routed to stock endpoint. Ensure routing is correct."
                else:
                    error_detail = f" — Symbol '{symbol}' not found on {exchange}"
            
            logger.error(
                "analyze_market HTTP error for %s/%s (status=%s): %s%s",
                symbol,
                exchange,
                status_code,
                exc,
                error_detail,
            )
            return None
        except ValueError as exc:
            logger.error("analyze_market routing error for %s/%s: %s", symbol, exchange, exc)
            return None
        except Exception as exc:
            logger.error("analyze_market failed for %s/%s: %s", symbol, exchange, exc, exc_info=True)
            return None

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

    async def decide_with_context(
        self,
        user_id: str,
        asset: str,
        market_data: dict,
        shared_context: dict,
        similar_past_outcomes: list,
        user_settings: dict,
    ) -> TradingDecision:
        """Return a normalized trading decision using orchestrator-provided context.

        This method is additive: it reuses the existing Claude-decision pipeline
        but injects shared-memory context and a summary of similar past outcomes
        into the system prompt via the existing ``learning_context`` slot.

        The orchestrator uses the returned decision to decide whether to execute,
        scale down size, or skip the trade.
        """
        # Prefer orchestrator-provided user_id, but keep backwards compat.
        self.user_id = user_id or self.user_id

        # Basic risk factor identification (lightweight + deterministic).
        risk_factors: list[str] = []
        try:
            indicators = (market_data or {}).get("indicators", {}) or {}
            rsi = indicators.get("rsi")
            trend = (market_data or {}).get("trend")
            macd = indicators.get("macd", {}) or {}
            if isinstance(rsi, (int, float)):
                if rsi >= 70:
                    risk_factors.append("overbought_RSI")
                elif rsi <= 30:
                    risk_factors.append("oversold_RSI")
            if trend in ("downtrend", "consolidating"):
                risk_factors.append(f"trend_{trend}")
            if isinstance(macd.get("histogram"), (int, float)) and macd.get("histogram") < 0:
                risk_factors.append("bearish_MACD")
        except Exception:
            pass

        # Shared context heuristics (avoid patterns + sentiment).
        try:
            for k, v in (shared_context or {}).items():
                if k.startswith("avoid_") and v:
                    risk_factors.append(k)
            # Common sentiment key conventions: "<ASSET>_sentiment" or "<ASSET>_sentiment_score"
            s_key = f"{asset.upper()}_sentiment"
            s_val = shared_context.get(s_key)
            if isinstance(s_val, (int, float)) and s_val < -0.1:
                risk_factors.append("negative_sentiment")
        except Exception:
            pass

        # Similar outcomes summary (compact, model-friendly).
        def _outcome_success(o: Any) -> bool:
            try:
                r = getattr(o, "result", None) or getattr(o, "result_data", None) or o.get("result") or o.get("result_data")  # type: ignore[attr-defined]
            except Exception:
                r = None
            r = r or {}
            if r.get("success") is True:
                return True
            profit = r.get("profit_pct") or r.get("profit") or 0
            try:
                return float(profit) > 0
            except Exception:
                return False

        sim_total = len(similar_past_outcomes or [])
        sim_wins = sum(1 for o in (similar_past_outcomes or []) if _outcome_success(o))
        sim_losses = sim_total - sim_wins
        sim_summary = (
            f"{sim_total} similar outcomes; {sim_wins} wins / {sim_losses} losses"
            if sim_total
            else "no similar outcomes found"
        )

        # Build the new required context injection block.
        learning_context = (
            "\nORCHESTRATOR CONTEXT (apply these learnings):\n"
            f"Past similar situations: {sim_summary}\n"
            f"Current shared intelligence: {shared_context}\n"
            f"Risk factors identified: {risk_factors}\n"
            "Adjust your decision confidence accordingly.\n"
        )

        # Load user + exchange keys to compute account_balance (keeps existing logic).
        exchange_name = (market_data or {}).get("exchange") or (market_data or {}).get("exchange_name") or ""
        exchange_name = str(exchange_name).lower().strip() or "alpaca"

        raw_key = raw_secret = None
        account_balance = 0.0
        open_count = 0
        user_history: dict = {"win_rate": 50.0, "avg_profit": 0.0, "avg_loss": 0.0, "count": 0}
        ai_name = "Claude"

        try:
            async with AsyncSessionLocal() as db:
                user_result = await db.execute(select(User).where(User.id == self.user_id))
                user = user_result.scalar_one_or_none()
                ai_name = user.ai_name if user and user.ai_name else "Claude"

                user_history = await self._get_user_history(db, asset)
                open_count = await self._get_open_trade_count(db)

                key_result = await db.execute(
                    select(ExchangeAPIKey).where(
                        ExchangeAPIKey.user_id == self.user_id,
                        ExchangeAPIKey.exchange == exchange_name,
                        ExchangeAPIKey.is_active == True,  # noqa: E712
                    )
                )
                key_row = key_result.scalar_one_or_none()
                if key_row:
                    is_paper = getattr(key_row, "is_paper", True)
                    raw_key, raw_secret = decrypt_api_key(
                        key_row.encrypted_api_key, key_row.encrypted_api_secret
                    )
                    client = get_exchange_client(exchange_name, raw_key, raw_secret, is_paper=is_paper)
                    raw_key = raw_secret = None
                    try:
                        account_balance = await client.get_account_balance()
                    finally:
                        await client.aclose()
        except Exception as exc:
            raw_key = raw_secret = None
            logger.warning("decide_with_context: balance/history load failed: %s", exc)

        # Ensure the market_data carries exchange for prompt formatting.
        market_data = dict(market_data or {})
        market_data["exchange"] = exchange_name

        decision = await self.get_claude_decision(
            market_data=market_data,
            user_history=user_history,
            account_balance=account_balance,
            open_trades_count=open_count,
            ai_name=ai_name,
            learning_context=learning_context,
        )

        action = decision.get("decision", "WAIT")
        normalized_action = "HOLD" if action == "WAIT" else str(action).upper()
        conf = float(decision.get("confidence", 0)) / 100.0
        entry = float(decision.get("entry_price") or market_data.get("price") or 0.0)
        stop = float(decision.get("stop_loss") or 0.0)
        take = float(decision.get("take_profit") or 0.0)

        stop_loss_pct = round(abs(entry - stop) / entry * 100, 4) if entry and stop else 0.0
        take_profit_pct = round(abs(take - entry) / entry * 100, 4) if entry and take else 0.0

        return TradingDecision(
            action=normalized_action if normalized_action in ("BUY", "SELL", "HOLD") else "HOLD",
            asset=asset,
            confidence=max(0.0, min(conf, 1.0)),
            reasoning=str(decision.get("reasoning") or ""),
            suggested_size_pct=float(decision.get("position_size_pct") or 0.0),
            stop_loss_pct=float(stop_loss_pct),
            take_profit_pct=float(take_profit_pct),
            risk_factors=list(dict.fromkeys(risk_factors)),  # stable de-dupe
        )

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
    # Personalized Analysis (Context-Aware)
    # ─────────────────────────────────────────────

    async def analyze(
        self,
        symbol: str,
        exchange: str,
        context: SharedContext,
        market_data: dict | None = None,
        historical_price: float | None = None,
    ) -> TradeAnalysis:
        """Perform context-aware trade analysis with personalized sizing and explanations.

        This method uses a user's SharedContext (goal, risk level, trust stage) to
        provide tailored trading guidance. Returns detailed technical analysis with
        market context.

        Args:
            symbol: Trading pair (e.g., "BTC/USD", "AAPL")
            exchange: Exchange name (e.g., "alpaca", "coinbase")
            context: SharedContext with user settings, goal, risk level
            market_data: Optional pre-fetched market analysis dict. If None, fetches live data.
            historical_price: Optional historical price for backtesting. If provided, uses this
                             instead of fetching live market data.

        Returns:
            TradeAnalysis with detailed signal, confidence, factors, and SL/TP levels.
        """
        # Fetch market data if not provided
        if market_data is None:
            if historical_price is not None:
                # Backtest mode: use provided price instead of live data
                market_data = await self._create_backtest_market_data(
                    symbol, exchange, historical_price
                )
            else:
                # Live mode: fetch full market analysis
                market_data = await self.analyze_market(symbol, exchange)
                if market_data is None:
                    # Fallback on data failure
                    return TradeAnalysis(
                        signal="wait",
                        confidence=0,
                        explanation_expert="Market data unavailable.",
                        key_factors=[],
                        suggested_stop_loss_pct=0.0,
                        suggested_take_profit_pct=0.0,
                        market_data={},
                    )

        # Build risk-aware guidance based on risk level
        risk_guidance = self._get_risk_guidance(context.risk_level)
        trust_guidance = self._get_trust_guidance(context.trust_ladder_stage)

        # Calculate max position size based on risk level
        max_position_pct = self._calculate_max_position_pct(
            context.risk_level, context.trust_ladder_stage
        )

        # Build personalized system prompt
        system_prompt = _ANALYZE_SYSTEM_PROMPT.format(
            ai_name=context.apex_name,
            goal=context.goal,
            risk_level=context.risk_level,
            trust_ladder_stage=context.trust_ladder_stage,
            max_position_pct=max_position_pct,
            trade_mode=context.trade_mode,
            risk_guidance=risk_guidance,
            trust_guidance=trust_guidance,
        )
        if getattr(context, "trust_score", 100) < 50:
            system_prompt += (
                "\n\n"
                "This user has rated less than half of your decisions positively.\n"
                "Be more conservative, explain every decision more carefully,\n"
                "and prioritise capital preservation over returns.\n"
            )

        # Build user prompt with current market data
        user_prompt = self._build_analysis_user_prompt(symbol, market_data)

        try:
            # Call Claude with new prompt structure
            response = await self._claude.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            raw = response.content[0].text.strip()
            analysis_dict = parse_claude_json(raw, context="trade analysis")

            # Validate and construct TradeAnalysis response
            analysis = TradeAnalysis(
                signal=analysis_dict.get("signal", "wait").lower(),
                confidence=int(analysis_dict.get("confidence", 0)),
                explanation_expert=analysis_dict.get("explanation_expert", ""),
                key_factors=analysis_dict.get("key_factors", []),
                suggested_stop_loss_pct=float(analysis_dict.get("suggested_stop_loss_pct", 0.0)),
                suggested_take_profit_pct=float(analysis_dict.get("suggested_take_profit_pct", 0.0)),
                market_data=analysis_dict.get("market_data", {}),
            )

            logger.info(
                "Trade analysis: %s/%s signal=%s confidence=%d",
                symbol,
                exchange,
                analysis.signal,
                analysis.confidence,
            )
            return analysis

        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON trade analysis: %s", raw[:200])
            return TradeAnalysis(
                signal="wait",
                confidence=0,
                explanation_expert="Analysis parse error. Retrying.",
                key_factors=[],
                suggested_stop_loss_pct=0.0,
                suggested_take_profit_pct=0.0,
                market_data=market_data or {},
            )
        except Exception as exc:
            logger.error("Trade analysis failed for %s/%s: %s", symbol, exchange, exc)
            return TradeAnalysis(
                signal="wait",
                confidence=0,
                explanation_expert=f"Analysis error: {str(exc)}",
                key_factors=[],
                suggested_stop_loss_pct=0.0,
                suggested_take_profit_pct=0.0,
                market_data=market_data or {},
            )

    async def translate_explanation(
        self,
        expert_text: str,
        target: str,
        context: SharedContext,
    ) -> str:
        """Translate expert technical explanation to simple or metaphor form.

        Args:
            expert_text: Full technical analysis with RSI, MACD, MA, volume details
            target: "simple" for plain English, "metaphor" for vivid analogy
            context: SharedContext with user explanation_level preference

        Returns:
            Translated explanation string (2-3 sentences)
        """
        if target == "simple":
            return await self._translate_to_simple(expert_text, context)
        elif target == "metaphor":
            return await self._translate_to_metaphor(expert_text, context)
        else:
            logger.warning("Unknown translation target: %s, returning original", target)
            return expert_text

    async def _translate_to_simple(self, expert_text: str, context: SharedContext) -> str:
        """Convert technical explanation to 2-3 plain English sentences."""
        if not settings.anthropic_api_key:
            return expert_text

        translation_prompt = f"""\
Simplify this trading analysis for a beginner investor. Use no jargon (no RSI, MACD, MA, etc).
Use plain English in 2-3 sentences. Be encouraging but honest.

Expert analysis:
{expert_text}

Simple explanation:"""

        try:
            response = await self._claude.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=256,
                system="You are a friendly financial advisor explaining trading concepts to beginners.",
                messages=[{"role": "user", "content": translation_prompt}],
            )
            return response.content[0].text.strip()
        except Exception as exc:
            logger.warning("Failed to translate to simple: %s", exc)
            return expert_text

    async def _translate_to_metaphor(self, expert_text: str, context: SharedContext) -> str:
        """Convert technical explanation to a vivid real-world analogy (2-3 sentences)."""
        if not settings.anthropic_api_key:
            return expert_text

        translation_prompt = f"""\
Create a vivid real-world analogy for this trading signal. Use 2-3 sentences.
Make it relatable and memorable for someone learning to trade.

Expert analysis:
{expert_text}

Real-world analogy:"""

        try:
            response = await self._claude.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=256,
                system="You are a creative educator using analogies to explain trading concepts.",
                messages=[{"role": "user", "content": translation_prompt}],
            )
            return response.content[0].text.strip()
        except Exception as exc:
            logger.warning("Failed to translate to metaphor: %s", exc)
            return expert_text

    def _get_risk_guidance(self, risk_level: str) -> str:
        """Return guidance string for the user's risk tolerance level."""
        guidance_map = {
            "conservative": "Take smaller positions (0.5-1%). Tighter stop-loss (0.5-1%). Wait for high-confidence setups (70+).",
            "balanced": "Standard positions (1-1.5%). Moderate stop-loss (1-2%). Trade on confidence 50+.",
            "aggressive": "Larger positions (1.5-2%). Wider stop-loss (2-3%). Higher risk-reward targets (1:3 or better).",
        }
        return guidance_map.get(risk_level, guidance_map["balanced"])

    def _get_trust_guidance(self, trust_stage: int) -> str:
        """Return guidance based on user's trust ladder stage."""
        guidance_map = {
            1: "This is paper (simulated) trading. Focus on learning, not profits. Be experimental.",
            2: "You have proven consistency. Start with very small real trades (0.25% position size).",
            3: "Standard position sizing applies. You've shown good risk management.",
            4: "You have demonstrated skill. Can use full position sizing (up to 2%).",
            5: "Autonomous trading enabled. You can scale up as capital allows.",
        }
        return guidance_map.get(trust_stage, guidance_map[1])

    def _calculate_max_position_pct(self, risk_level: str, trust_stage: int) -> float:
        """Calculate max position size % based on risk level and trust stage."""
        # Base sizing by risk level
        base_sizes = {
            "conservative": 0.75,
            "balanced": 1.5,
            "aggressive": 2.0,
        }
        base = base_sizes.get(risk_level, 1.5)

        # Scale down by trust stage (1-5)
        # Stage 1-2: reduced sizing for learning/early real trades
        # Stage 3+: full sizing
        if trust_stage <= 2:
            return min(base * 0.5, 0.5)  # Cap at 0.5% for paper/early
        elif trust_stage == 3:
            return min(base * 0.75, 1.0)
        else:
            return base

    def _build_analysis_user_prompt(self, symbol: str, market_data: dict) -> str:
        """Build the user prompt for trade analysis with market data."""
        indicators = market_data.get("indicators", {})
        macd = indicators.get("macd", {})
        sr = market_data.get("support_resistance", {})

        prompt = f"""\
ANALYZE THIS TRADE OPPORTUNITY:

Symbol:         {symbol}
Price:          ${market_data.get("price", 0):,.4f}
24h High/Low:   ${market_data.get("high_24h", 0):,.4f} / ${market_data.get("low_24h", 0):,.4f}
24h Volume:     {market_data.get("volume", 0):,.0f}
Trend:          {market_data.get("trend", "unknown")}

TECHNICAL INDICATORS:
RSI (14):       {indicators.get("rsi", 50):.1f}
MACD:           Line={macd.get("line", 0):.4f}, Signal={macd.get("signal", 0):.4f}, Hist={macd.get("histogram", 0):.6f}
MA20/50/200:    ${indicators.get("ma20", 0):,.4f} / ${indicators.get("ma50", 0):,.4f} / ${indicators.get("ma200", 0):,.4f}

SUPPORT/RESISTANCE:
Support:        ${sr.get("support", 0):,.4f}
Pivot:          ${sr.get("pivot", 0):,.4f}
Resistance:     ${sr.get("resistance", 0):,.4f}

Provide your detailed technical analysis with the specified JSON format."""

        return prompt

    async def _create_backtest_market_data(
        self, symbol: str, exchange: str, historical_price: float
    ) -> dict:
        """Create a market data dict for backtesting with a historical price."""
        # For backtest mode, we use the provided historical_price and create synthetic indicators
        # In real backtest scenarios, you'd have full OHLCV data to compute real indicators
        return {
            "symbol": symbol,
            "exchange": exchange,
            "price": historical_price,
            "high_24h": historical_price * 1.02,
            "low_24h": historical_price * 0.98,
            "volume": 0,  # Backtest volume unknown
            "trend": "unknown",  # Would need historical data to determine
            "indicators": {
                "rsi": 50,  # Neutral RSI for backtest
                "ma20": historical_price,
                "ma50": historical_price,
                "ma200": historical_price,
                "macd": {"line": 0, "signal": 0, "histogram": 0},
            },
            "support_resistance": {
                "support": historical_price * 0.98,
                "pivot": historical_price,
                "resistance": historical_price * 1.02,
            },
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
        """Orchestrate the full trade lifecycle: safety -> order -> DB -> notify.

        Per-user exchange keys are fetched, decrypted, used once, then wiped.

        Returns:
            {"status": "executed", "trade_id": "..."} or
            {"status": "rejected", "reason": "..."}
        """
        try:
            symbol = normalise_symbol(symbol, exchange_name)
        except ValueError as exc:
            return {"status": "rejected", "reason": str(exc)}

        raw_key = raw_secret = None
        client = None
        try:
            async with AsyncSessionLocal() as db:
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

                key_result = await db.execute(
                    select(ExchangeAPIKey).where(
                        ExchangeAPIKey.user_id == self.user_id,
                        ExchangeAPIKey.exchange == exchange_name,
                        ExchangeAPIKey.is_active == True,  # noqa: E712
                    )
                )
                api_key_row = key_result.scalar_one_or_none()
                if not api_key_row:
                    logger.warning(
                        "No active %s API key for user %s — cannot execute trade",
                        exchange_name, self.user_id,
                    )
                    return {"status": "rejected", "reason": f"No active API key for {exchange_name}"}

                is_paper = getattr(api_key_row, "is_paper", True)
                try:
                    raw_key, raw_secret = decrypt_api_key(
                        api_key_row.encrypted_api_key,
                        api_key_row.encrypted_api_secret,
                    )
                except Exception as exc:
                    logger.error("Failed to decrypt API key for user %s: %s", self.user_id, exc)
                    return {"status": "rejected", "reason": "Could not decrypt exchange API key"}

                client = get_exchange_client(exchange_name, raw_key, raw_secret, is_paper=is_paper)
                raw_key = raw_secret = None  # wipe decrypted keys immediately

                try:
                    account_balance = await client.get_account_balance()
                except Exception as exc:
                    return {"status": "rejected", "reason": f"Exchange balance fetch failed: {exc}"}

                guard = await self._safety_checks(decision, account_balance, user_settings, db)
                if not guard["allowed"]:
                    logger.info("Trade rejected for user %s: %s", self.user_id, guard["reason"])
                    return {"status": "rejected", "reason": guard["reason"]}

                params = build_trade_parameters(
                    confidence=decision["confidence"],
                    entry_price=decision["entry_price"],
                    side=decision["decision"],
                    account_balance=account_balance,
                )
                if not params.get("tradeable"):
                    return {"status": "rejected", "reason": params.get("reason", "Not tradeable")}

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

                await client.set_stop_loss(symbol, order_id, decision["stop_loss"])
                await client.set_take_profit(symbol, order_id, decision["take_profit"])

                trade = Trade(
                    user_id=self.user_id,
                    exchange=exchange_name,
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

        finally:
            raw_key = raw_secret = None
            if client:
                await client.aclose()

        logger.info(
            "%s executed %s %s @ %.4f (trade_id=%s)",
            ai_name, decision["decision"], symbol, decision["entry_price"], trade_id,
        )

        return {
            "status": "executed",
            "trade_id": trade_id,
            "symbol": symbol,
            "decision": decision["decision"],
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

    async def run_cycle(
        self,
        symbol: str,
        exchange_name: str,
        orchestrator_context: str = "",
    ) -> dict:
        """Run a complete analysis → decision → execution cycle.

        Enhanced with Learning Hub insights:
          1. Fetch active hub insights + instructions before analysis
          2. Inject learning context into Claude's system prompt
          3. Apply hub-guided position sizing / condition filters
          4. Log the outcome back to hub via record_agent_output()

        Args:
            symbol: Ticker symbol (e.g. BTCUSDT, AAPL).
            exchange_name: Exchange name (binance, alpaca, oanda).
            orchestrator_context: Optional extra context from MasterOrchestrator
                (shared memory learnings, similar past outcomes). Appended to
                learning_context when provided.
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

        if orchestrator_context:
            learning_context += "\n" + orchestrator_context

        # ── Step 1: Load user + exchange keys ─────────────────────────────
        raw_key = raw_secret = None
        try:
            async with AsyncSessionLocal() as db:
                user_result = await db.execute(select(User).where(User.id == self.user_id))
                user = user_result.scalar_one_or_none()
                ai_name = user.ai_name if user else "Claude"

                user_history = await self._get_user_history(db, symbol)
                open_count   = await self._get_open_trade_count(db)

                key_result = await db.execute(
                    select(ExchangeAPIKey).where(
                        ExchangeAPIKey.user_id == self.user_id,
                        ExchangeAPIKey.exchange == exchange_name,
                        ExchangeAPIKey.is_active == True,  # noqa: E712
                    )
                )
                key_row = key_result.scalar_one_or_none()
                if not key_row:
                    logger.warning(
                        "No %s API key for user %s — skipping trading cycle",
                        exchange_name, self.user_id,
                    )
                    return {"status": "skipped", "reason": "No API key configured"}

                is_paper = getattr(key_row, "is_paper", True)
                raw_key, raw_secret = decrypt_api_key(
                    key_row.encrypted_api_key, key_row.encrypted_api_secret
                )

            client = get_exchange_client(exchange_name, raw_key, raw_secret, is_paper=is_paper)
            raw_key = raw_secret = None  # wipe from memory immediately

            try:
                account_balance = await client.get_account_balance()
            finally:
                await client.aclose()

        except Exception as exc:
            raw_key = raw_secret = None
            logger.error("run_cycle key/balance phase failed for user %s: %s", self.user_id, exc)
            return {"status": "error", "reason": str(exc)}

        # ── Step 2: Market analysis ───────────────────────────────────────
        market_data = await self.analyze_market(symbol, exchange_name)
        if market_data is None:
            logger.warning(f"run_cycle aborting — no market data for {symbol}")
            return {
                "status": "error",
                "reason": "market_data_unavailable",
                "symbol": symbol,
                "exchange": exchange_name
            }
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
                "decision": "WAIT",
                "confidence": decision.get("confidence", 0),
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

        Per-user keys are decrypted, used, then wiped from memory.
        """
        raw_key = raw_secret = None
        client = None
        try:
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
                        ExchangeAPIKey.exchange == trade.exchange,
                        ExchangeAPIKey.is_active == True,  # noqa: E712
                    )
                )
                key_row = key_result.scalars().first()
                if not key_row:
                    logger.warning(
                        "No active %s API key for user %s — cannot close position %s",
                        trade.exchange, self.user_id, trade_id,
                    )
                    return {"status": "error", "reason": f"No active API key for {trade.exchange}"}

                is_paper = getattr(key_row, "is_paper", True)
                raw_key, raw_secret = decrypt_api_key(
                    key_row.encrypted_api_key, key_row.encrypted_api_secret
                )
                client = get_exchange_client(key_row.exchange, raw_key, raw_secret, is_paper=is_paper)
                raw_key = raw_secret = None  # wipe immediately

                try:
                    current_price = await client.get_current_price(trade.symbol)
                    await client.close_position(trade.symbol)
                except Exception as exc:
                    return {"status": "error", "reason": str(exc)}

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

        finally:
            raw_key = raw_secret = None
            if client:
                await client.aclose()

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

    # ─────────────────────────────────────────────
    # Monitor & Auto-Close Positions
    # ─────────────────────────────────────────────

    async def monitor_open_positions(self, user_id: str, db: AsyncSession) -> list[dict]:
        """Monitor all open positions and auto-close those hitting stop-loss or take-profit.

        Called every 5 minutes by Position Monitor Agent and once before every new analysis.

        Returns:
            List of closed positions with reasons and P&L details.
        """
        closed = []

        # 1. Fetch all open trades for this user
        open_trades_result = await db.execute(
            select(Trade).where(Trade.user_id == user_id, Trade.status == "open")
        )
        trades = open_trades_result.scalars().all()

        for trade in trades:
            # 2. Get current price
            try:
                current_price = await self.get_current_price(trade.symbol)
            except Exception as exc:
                logger.debug(f"Could not fetch price for {trade.symbol}: {exc}")
                continue  # Skip if price unavailable — never crash

            # 3. Calculate unrealised P&L %
            entry = float(trade.entry_price)
            if entry == 0:
                continue
            pnl_pct = ((current_price - entry) / entry) * 100
            if trade.side == "SELL":
                pnl_pct = -pnl_pct

            # 4. Check stop-loss and take-profit
            stop_loss_pct = float(getattr(trade, "stop_loss_pct", None) or 2.0)
            take_profit_pct = float(getattr(trade, "take_profit_pct", None) or 5.0)
            reason = None

            if pnl_pct <= -stop_loss_pct:
                reason = "stop_loss_triggered"
            elif pnl_pct >= take_profit_pct:
                reason = "take_profit_triggered"

            if reason:
                # 5. Execute close order
                close_side = "SELL" if trade.side == "BUY" else "BUY"
                await self.execute_close(trade, current_price, close_side, db)

                # 6. Write to AuditLog BEFORE closing
                await self._write_audit_log(
                    db,
                    user_id,
                    reason,
                    trade.symbol,
                    {
                        "entry_price": entry,
                        "exit_price": current_price,
                        "pnl_pct": round(pnl_pct, 2),
                    },
                )

                # 7. Send Telegram alert
                emoji = "🛑" if reason == "stop_loss_triggered" else "✅"
                msg = (
                    f"{emoji} {reason.replace('_', ' ').title()}: {trade.symbol}\n"
                    f"Entry: £{entry:.2f} → Exit: £{current_price:.2f}\n"
                    f"P&L: {pnl_pct:+.1f}%"
                )
                await self._send_telegram_alert(user_id, msg, db)

                closed.append(
                    {
                        "trade_id": str(trade.id),
                        "symbol": trade.symbol,
                        "reason": reason,
                        "pnl_pct": round(pnl_pct, 2),
                    }
                )

        return closed

    async def execute_close(
        self, trade: Trade, exit_price: float, side: str, db: AsyncSession
    ) -> None:
        """Close a trade at the specified exit price.

        Handles both paper and live trades. Updates the trades table with:
        - exit_price
        - pnl / pnl_percent
        - status = "closed"
        - closed_at = now()

        Also marks user_settings.first_trade_done = True after first close.
        """
        pnl = 0.0
        pnl_pct = 0.0

        if trade.side == "BUY":
            pnl = (exit_price - trade.entry_price) * trade.quantity
        else:  # SELL
            pnl = (trade.entry_price - exit_price) * trade.quantity

        pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
        if trade.side == "SELL":
            pnl_pct = -pnl_pct

        # Update trade
        trade.exit_price = exit_price
        trade.status = "closed"
        trade.closed_at = datetime.now(timezone.utc)

        if pnl >= 0:
            trade.profit = round(pnl, 2)
            trade.profit_percent = round(pnl_pct, 4)
        else:
            trade.loss = round(abs(pnl), 2)
            trade.profit_percent = round(pnl_pct, 4)

        await db.flush()

        # Mark first trade closed
        settings_result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == trade.user_id)
        )
        user_settings = settings_result.scalar_one_or_none()
        if user_settings:
            # first_trade_done may not exist on all UserSettings, add if needed
            if hasattr(user_settings, "first_trade_done"):
                user_settings.first_trade_done = True
            await db.flush()

        await db.commit()

        logger.info(
            f"Trade {trade.id} closed: {trade.symbol} P&L={pnl:.2f} ({pnl_pct:.2f}%)"
        )

    async def get_current_price(self, symbol: str) -> float:
        """Fetch current price from Alpaca API.

        Handles both stocks (GET /v2/stocks/{symbol}/quotes/latest) and
        crypto (GET /v1beta3/crypto/us/latest/quotes).

        Args:
            symbol: Ticker symbol (e.g. BTCUSDT, AAPL)

        Returns:
            Current price as float

        Raises:
            Exception on API failure
        """
        base_url = "https://api.polygon.io"
        api_key = settings.POLYGON_API_KEY if hasattr(settings, "POLYGON_API_KEY") else None

        # Try Alpaca API first
        alpaca_url = "https://data.alpaca.markets"
        headers = {"APCA-API-KEY-ID": settings.ALPACA_KEY} if hasattr(settings, "ALPACA_KEY") else {}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Try stocks endpoint
                if not symbol.endswith("USDT"):
                    url = f"{alpaca_url}/v2/stocks/{symbol.upper()}/quotes/latest"
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        if "quote" in data:
                            return float(data["quote"].get("ap", data["quote"].get("bp", 0)))

                # Try crypto endpoint
                if "USDT" in symbol or "USD" in symbol:
                    crypto_symbol = symbol.replace("USDT", "").replace("USD", "").upper()
                    url = f"{alpaca_url}/v1beta3/crypto/us/latest/quotes"
                    params = {"symbols": crypto_symbol}
                    response = await client.get(url, headers=headers, params=params)
                    if response.status_code == 200:
                        data = response.json()
                        if "quotes" in data and crypto_symbol in data["quotes"]:
                            return float(data["quotes"][crypto_symbol].get("ap", data["quotes"][crypto_symbol].get("bp", 0)))

                # Fallback to Polygon API
                if api_key:
                    url = f"{base_url}/v3/quotes/latest"
                    params = {"ticker": symbol.upper(), "apikey": api_key}
                    response = await client.get(url, params=params)
                    if response.status_code == 200:
                        data = response.json()
                        if "results" in data and len(data["results"]) > 0:
                            return float(data["results"][0].get("last_quote", {}).get("ask", 0))

        except Exception as exc:
            logger.error(f"Error fetching price for {symbol}: {exc}")
            raise

        raise ValueError(f"Could not fetch price for {symbol}")

    async def _write_audit_log(
        self,
        db: AsyncSession,
        user_id: str,
        reason: str,
        symbol: str,
        details: dict,
    ) -> None:
        """Write trade event to AuditLog for compliance and debugging."""
        try:
            entry = AuditLog(
                user_id=user_id,
                event_type="position_closed",
                event_details={
                    "symbol": symbol,
                    "reason": reason,
                    **details,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            db.add(entry)
            await db.flush()
        except Exception as exc:
            logger.error(f"Failed to write audit log: {exc}")

    async def _send_telegram_alert(
        self, user_id: str, message: str, db: AsyncSession
    ) -> None:
        """Send Telegram alert to user about position close."""
        try:
            from src.integrations.telegram_bot import send_user_message

            await send_user_message(user_id, message, db)
        except Exception as exc:
            logger.debug(f"Failed to send Telegram alert: {exc}")

