"""
signal_stack_agent.py — Shared pre-computed signal stack for all users.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import SignalInteraction, SignalScanRun, SignalStack
from src.agents.sentiment_agent import SentimentAgent
from src.agents.shared_memory import SharedContext
from src.integrations.market_data import classify_asset, full_market_analysis

logger = logging.getLogger(__name__)

STOCK_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
    "JPM", "BAC", "GS", "SPY", "QQQ", "NFLX", "AMD", "UBER",
]

CRYPTO_WATCHLIST = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD",
    "ADA/USD", "AVAX/USD", "DOT/USD",
]

FOREX_WATCHLIST = [
    "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD",
]

ASSET_NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "GOOGL": "Google",
    "AMZN": "Amazon",
    "META": "Meta",
    "TSLA": "Tesla",
    "JPM": "JPMorgan",
    "BAC": "Bank of America",
    "GS": "Goldman Sachs",
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq ETF",
    "NFLX": "Netflix",
    "AMD": "AMD",
    "UBER": "Uber",
    "BTC/USD": "Bitcoin",
    "ETH/USD": "Ethereum",
    "SOL/USD": "Solana",
    "BNB/USD": "BNB",
    "XRP/USD": "XRP",
    "ADA/USD": "Cardano",
    "AVAX/USD": "Avalanche",
    "DOT/USD": "Polkadot",
    "EUR_USD": "Euro / Dollar",
    "GBP_USD": "Pound / Dollar",
    "USD_JPY": "Dollar / Yen",
    "AUD_USD": "Aussie / Dollar",
    "USD_CAD": "Dollar / Canadian",
}


class SignalStackAgent:
    """Scan a shared universe and persist ranked opportunities."""

    def __init__(self) -> None:
        self.claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.sentiment_agent = SentimentAgent()

    async def run_scan(self, db: AsyncSession, triggered_by: str = "scheduler") -> dict:
        """
        Main entry point. Scans all assets and writes ranked signals to DB.
        Called every 30 minutes by the scheduler.
        """
        all_symbols = STOCK_WATCHLIST + CRYPTO_WATCHLIST + FOREX_WATCHLIST
        return await self._run_symbols_scan(db, all_symbols, triggered_by=triggered_by)

    async def run_crypto_only_scan(self, db: AsyncSession, triggered_by: str = "scheduler") -> dict:
        """Run the shared scan for crypto assets only."""
        return await self._run_symbols_scan(
            db,
            CRYPTO_WATCHLIST,
            triggered_by=triggered_by,
            delete_expired=False,
        )

    async def record_interaction(
        self,
        signal_id: str,
        user_id: str,
        action: str,
        trade_id: str | None,
        db: AsyncSession,
    ) -> None:
        """Record a user's signal interaction and refresh community counters."""
        signal_uuid = uuid.UUID(signal_id) if isinstance(signal_id, str) else signal_id

        await db.execute(
            pg_insert(SignalInteraction)
            .values(
                user_id=user_id,
                signal_id=signal_uuid,
                action=action,
                trade_id=trade_id,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "signal_id"],
                set_={"action": action, "trade_id": trade_id},
            )
        )

        result = await db.execute(
            select(
                func.count().label("total"),
                func.sum(
                    case((SignalInteraction.action.in_(["accepted", "traded"]), 1), else_=0)
                ).label("accepted"),
            ).where(SignalInteraction.signal_id == signal_uuid)
        )
        row = result.one()
        total = row.total or 0
        accepted = int(row.accepted or 0)

        await db.execute(
            update(SignalStack)
            .where(SignalStack.id == signal_uuid)
            .values(
                community_accepted=accepted,
                community_total=total,
            )
        )
        await db.commit()

    async def _run_symbols_scan(
        self,
        db: AsyncSession,
        symbols: list[str],
        triggered_by: str,
        delete_expired: bool = True,
    ) -> dict:
        """Shared scan runner used by full and crypto-only schedulers."""
        run_id = uuid.uuid4()
        start_time = time.time()
        signals_created = 0
        assets_scanned = 0

        try:
            if delete_expired:
                await db.execute(
                    delete(SignalStack).where(
                        SignalStack.expires_at < datetime.now(timezone.utc)
                    )
                )

            for symbol in symbols:
                try:
                    signal = await self._analyse_symbol(symbol, run_id, db)
                    if signal:
                        db.add(SignalStack(**signal))
                        signals_created += 1
                    assets_scanned += 1
                    await asyncio.sleep(0.3)
                except Exception as exc:
                    logger.error("Signal scan failed for %s: %s", symbol, exc)
                    assets_scanned += 1

            await db.commit()

            db.add(
                SignalScanRun(
                    id=run_id,
                    assets_scanned=assets_scanned,
                    signals_generated=signals_created,
                    duration_ms=int((time.time() - start_time) * 1000),
                    triggered_by=triggered_by,
                )
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "Signal Stack: scanned %s, generated %s signals in %sms",
            assets_scanned,
            signals_created,
            duration_ms,
        )

        return {
            "assets_scanned": assets_scanned,
            "signals_generated": signals_created,
            "run_id": str(run_id),
        }

    async def _analyse_symbol(self, symbol: str, run_id: uuid.UUID, db: AsyncSession) -> dict | None:
        """Analyse one symbol and return a signal dict or None."""
        del db
        try:
            asset_type = classify_asset(symbol)
            if asset_type == "crypto":
                asset_class = "crypto"
                exchange = "coinbase"
            elif asset_type == "forex":
                asset_class = "forex"
                exchange = "oanda"
            else:
                asset_class = "stocks"
                exchange = "alpaca"

            market_data = await full_market_analysis(symbol, exchange)
            indicators = market_data.get("indicators", {}) or {}
            rsi = indicators.get("rsi")
            macd_info = indicators.get("macd", {}) or {}
            macd = self._classify_macd(macd_info)
            current_price = market_data.get("price")
            price_change_24h = market_data.get("price_change_pct")
            volume = market_data.get("volume")
            volume_ratio = self._volume_ratio(volume)

            ctx = SharedContext.default("signal-stack")
            if asset_class == "crypto":
                ctx.trader_class = "crypto_native"
            sentiment = await self.sentiment_agent.get_sentiment(symbol, ctx)
            sentiment_score = sentiment.get("sentiment_score", "neutral")
            fear_greed_index = sentiment.get("fear_greed_index")
            earnings_days = self._earnings_days(sentiment.get("earnings_date"))

            score = self._calculate_score(rsi, macd, volume_ratio, sentiment_score)
            signal_direction = self._determine_signal(rsi, macd, sentiment_score, score)

            if signal_direction == "watch" and score < 50:
                return None
            if signal_direction in ("buy", "sell") and score < 65:
                return None

            reasoning = await self._generate_reasoning(
                symbol=symbol,
                signal=signal_direction,
                confidence=score,
                rsi=rsi,
                macd=macd,
                volume_ratio=volume_ratio,
                sentiment=sentiment_score,
                asset_class=asset_class,
            )

            return {
                "id": uuid.uuid4(),
                "symbol": symbol,
                "asset_name": self._get_asset_name(symbol),
                "asset_class": asset_class,
                "exchange": exchange,
                "signal": signal_direction,
                "confidence": score,
                "reasoning_expert": reasoning["expert"],
                "reasoning_simple": reasoning["simple"],
                "reasoning_metaphor": reasoning["metaphor"],
                "rsi": rsi,
                "macd_signal": macd,
                "volume_ratio": volume_ratio,
                "sentiment_score": sentiment_score,
                "earnings_days": earnings_days,
                "fear_greed_index": fear_greed_index,
                "current_price": current_price,
                "price_change_24h": price_change_24h,
                "scan_run_id": run_id,
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=35),
            }
        except Exception as exc:
            logger.error("Analysis failed for %s: %s", symbol, exc)
            return None

    def _calculate_score(
        self,
        rsi: float | None,
        macd: str,
        volume_ratio: float | None,
        sentiment: str,
    ) -> int:
        """Composite confidence score 0-100 based on signal convergence."""
        score = 50

        if rsi is not None:
            if rsi < 30:
                score += 20
            elif rsi < 40:
                score += 12
            elif rsi < 50:
                score += 5
            elif rsi > 70:
                score -= 15
            elif rsi > 60:
                score -= 5

        if macd == "bullish":
            score += 15
        elif macd == "bearish":
            score -= 15

        if volume_ratio is not None:
            if volume_ratio > 2.0:
                score += 10
            elif volume_ratio > 1.5:
                score += 5

        if sentiment == "very_bullish":
            score += 15
        elif sentiment == "bullish":
            score += 8
        elif sentiment == "very_bearish":
            score -= 15
        elif sentiment == "bearish":
            score -= 8

        return max(0, min(100, int(round(score))))

    def _determine_signal(
        self,
        rsi: float | None,
        macd: str,
        sentiment: str,
        score: int,
    ) -> str:
        del sentiment
        if score < 55:
            return "watch"
        if macd == "bullish" or (rsi is not None and rsi < 45):
            return "buy"
        if macd == "bearish" or (rsi is not None and rsi > 65):
            return "sell"
        return "watch"

    async def _generate_reasoning(
        self,
        symbol: str,
        signal: str,
        confidence: int,
        rsi: float | None,
        macd: str,
        volume_ratio: float | None,
        sentiment: str,
        asset_class: str,
    ) -> dict[str, str]:
        """Generate expert, simple, and metaphor explanations in one Claude call."""
        prompt = f"""You are Unitrader's AI trader. Generate 3 reasoning explanations for this signal.
Be specific. Use the real numbers provided. Never be generic.

Asset: {symbol} ({asset_class})
Signal: {signal.upper()} — {confidence}% confidence
RSI: {rsi} | MACD: {macd} | Volume: {volume_ratio}x avg | Sentiment: {sentiment}

Return JSON only:
{{
  "expert": "2 sentences. Technical language. Include specific indicator values and what they mean.",
  "simple": "2 sentences. No jargon. Explain what Unitrader sees in plain English.",
  "metaphor": "1-2 sentences. Explain with a real-world comparison."
}}"""
        try:
            resp = await self.claude_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if resp.content else "{}"
            return json.loads(text)
        except Exception:
            return {
                "expert": f"{symbol}: {signal.upper()} signal at {confidence}% confidence.",
                "simple": f"Unitrader sees a possible chance to {signal} {symbol}.",
                "metaphor": "Think of it like spotting a road that looks clearer than the rest right now.",
            }

    def _classify_macd(self, macd_info: dict[str, Any]) -> str:
        histogram = float(macd_info.get("histogram", 0.0) or 0.0)
        if histogram > 0.01:
            return "bullish"
        if histogram < -0.01:
            return "bearish"
        return "neutral"

    def _volume_ratio(self, volume: float | None) -> float | None:
        if volume is None:
            return None
        if volume <= 0:
            return 0.0
        return 1.0

    def _get_asset_name(self, symbol: str) -> str:
        return ASSET_NAMES.get(symbol, symbol)

    def _earnings_days(self, earnings_date: str | None) -> int | None:
        if not earnings_date:
            return None
        try:
            earnings_day = datetime.fromisoformat(earnings_date).date()
            return (earnings_day - datetime.now(timezone.utc).date()).days
        except Exception:
            return None


signal_stack_agent = SignalStackAgent()
