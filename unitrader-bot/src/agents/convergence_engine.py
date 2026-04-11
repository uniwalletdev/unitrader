"""
convergence_engine.py — Weighted multi-source signal voting for Apex.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from src.agents.sentiment_agent import SentimentAgent

logger = logging.getLogger(__name__)

WEIGHTS = {
    "technical": 0.25,
    "sentiment": 0.20,
    "fear_greed": 0.15,
    "earnings": -0.15,
    "insider": 0.12,
}

_STOCK_FEAR_GREED_CACHE: dict[str, Any] = {
    "value": 50,
    "label": "Neutral",
    "cached_at": None,
}
_STOCK_FEAR_GREED_TTL = timedelta(days=7)


class ConvergenceEngine:
    """Seven-source design trimmed to the current v1 production votes."""

    def __init__(self, claude_client) -> None:
        self.claude_client = claude_client
        self.sentiment_agent = SentimentAgent()

    async def score_symbol(
        self,
        symbol: str,
        asset_class: str,
        existing_market_data: dict,
        existing_sentiment: dict,
        db: AsyncSession,
        companion_name: str = "Apex",
    ) -> dict:
        """Run the v1 vote collectors and return a normalized convergence result.
        
        Args:
            companion_name: User's custom AI name (defaults to 'Apex' for background jobs).
        """
        results = await self._gather_votes(
            symbol=symbol,
            asset_class=asset_class,
            existing_market_data=existing_market_data,
            existing_sentiment=existing_sentiment,
            db=db,
        )

        votes = {
            "technical": results[0] if not isinstance(results[0], Exception) else self._neutral_vote(),
            "sentiment": results[1] if not isinstance(results[1], Exception) else self._neutral_vote(),
            "fear_greed": results[2] if not isinstance(results[2], Exception) else self._neutral_vote(),
            "earnings": (
                results[3]
                if not isinstance(results[3], Exception)
                else {"penalty": 0, "days_until": None, "evidence": "unavailable"}
            ),
            "insider": results[4] if not isinstance(results[4], Exception) else self._neutral_vote(),
        }

        raw_score = (
            votes["technical"]["score"] * WEIGHTS["technical"]
            + votes["sentiment"]["score"] * WEIGHTS["sentiment"]
            + votes["fear_greed"]["score"] * WEIGHTS["fear_greed"]
            + votes["insider"]["score"] * WEIGHTS["insider"]
        )
        earnings_penalty = votes["earnings"]["penalty"] * WEIGHTS["earnings"]
        final_score = max(0, min(100, int(round(raw_score + earnings_penalty))))

        signal = self._determine_direction(votes, final_score)
        votes_for = self._count_agreeing_votes(votes, signal)
        reasoning = await self._generate_convergence_reasoning(
            symbol=symbol,
            asset_class=asset_class,
            signal=signal,
            confidence=final_score,
            votes=votes,
            votes_for=votes_for,
            companion_name=companion_name,
        )

        return {
            "signal": signal,
            "confidence": final_score,
            "votes_for": votes_for,
            "total_votes": 5,
            "vote_breakdown": votes,
            "reasoning_expert": reasoning["expert"],
            "reasoning_simple": reasoning["simple"],
            "reasoning_metaphor": reasoning["metaphor"],
            "convergence_summary": reasoning["one_line"],
        }

    async def _gather_votes(
        self,
        symbol: str,
        asset_class: str,
        existing_market_data: dict,
        existing_sentiment: dict,
        db: AsyncSession,
    ):
        del db
        return await __import__("asyncio").gather(
            self._vote_technical(existing_market_data),
            self._vote_sentiment(existing_sentiment),
            self._vote_fear_greed(symbol, asset_class),
            self._vote_earnings(symbol, asset_class, existing_sentiment),
            self._vote_insider(symbol, asset_class),
            return_exceptions=True,
        )

    async def _vote_technical(self, market_data: dict) -> dict:
        indicators = market_data.get("indicators", {}) or {}
        rsi = float(indicators.get("rsi", 50) or 50)
        macd_info = indicators.get("macd", {}) or {}
        macd_signal = self._classify_macd(macd_info)
        volume = market_data.get("volume")
        avg_volume = market_data.get("avg_volume")
        volume_ratio = self._volume_ratio(volume, avg_volume)
        score = 50

        if rsi < 30:
            score += 30
        elif rsi < 40:
            score += 18
        elif rsi < 50:
            score += 5
        elif rsi > 70:
            score -= 20
        elif rsi > 60:
            score -= 8

        if macd_signal == "bullish":
            score += 15
        elif macd_signal == "bearish":
            score -= 15

        if volume_ratio > 2.5:
            score += 10
        elif volume_ratio > 1.5:
            score += 5
        elif 0 < volume_ratio < 0.5:
            score -= 5

        direction = "bullish" if score > 55 else "bearish" if score < 45 else "neutral"
        evidence = f"RSI {rsi:.0f}, MACD {macd_signal}, volume {volume_ratio:.1f}x average"
        return {"score": max(0, min(100, score)), "direction": direction, "evidence": evidence}

    async def _vote_sentiment(self, sentiment_data: dict) -> dict:
        raw = sentiment_data.get("sentiment_score", "neutral")
        score_map = {
            "very_bullish": 90,
            "bullish": 70,
            "neutral": 50,
            "bearish": 30,
            "very_bearish": 10,
        }
        direction_map = {
            "very_bullish": "bullish",
            "bullish": "bullish",
            "neutral": "neutral",
            "bearish": "bearish",
            "very_bearish": "bearish",
        }
        score = score_map.get(raw, 50)
        evidence = sentiment_data.get("sentiment_summary_simple", "Apex reviewed recent headlines")
        return {"score": score, "direction": direction_map.get(raw, "neutral"), "evidence": evidence}

    async def _vote_fear_greed(self, symbol: str, asset_class: str) -> dict:
        try:
            if asset_class == "crypto":
                value = await self.sentiment_agent._fetch_fear_greed()
                label = self._classify_fear_greed(value or 50)
            elif asset_class == "stocks":
                value = self._get_cached_stock_fear_greed()
                label = self._classify_fear_greed(value)
            else:
                value = 50
                label = "Neutral"

            if value <= 25:
                score = 85
                direction = "bullish"
            elif value <= 45:
                score = 65
                direction = "bullish"
            elif value <= 55:
                score = 50
                direction = "neutral"
            elif value <= 75:
                score = 35
                direction = "bearish"
            else:
                score = 15
                direction = "bearish"

            if asset_class == "forex":
                score = 50
                direction = "neutral"
                label = "Neutral"
                value = 50

            evidence = f"Market mood: {label} ({value}/100)"
            return {
                "score": score,
                "direction": direction,
                "evidence": evidence,
                "raw_value": value,
                "label": label,
            }
        except Exception as exc:
            logger.warning("Fear & Greed vote failed for %s: %s", symbol, exc)
            return self._neutral_vote("Fear & Greed unavailable")

    async def _vote_earnings(self, symbol: str, asset_class: str, sentiment_data: dict) -> dict:
        if asset_class != "stocks":
            return {"penalty": 0, "days_until": None, "evidence": "N/A (not a stock)"}

        try:
            days = self._days_until_earnings(sentiment_data.get("earnings_date"))
            if days is None:
                fetched = await self.sentiment_agent._fetch_earnings(symbol)
                if fetched:
                    days = (fetched["date"] - datetime.now(timezone.utc).date()).days

            if days is None:
                return {"penalty": 0, "days_until": None, "evidence": "Earnings date unknown"}
            if days <= 3:
                return {"penalty": 80, "days_until": days, "evidence": f"DANGER: Earnings in {days} days — Apex will not trade"}
            if days <= 7:
                return {"penalty": 50, "days_until": days, "evidence": f"WARNING: Earnings in {days} days — high uncertainty"}
            if days <= 14:
                return {"penalty": 20, "days_until": days, "evidence": f"Caution: Earnings in {days} days"}
            return {"penalty": 0, "days_until": days, "evidence": f"Earnings in {days} days — safe trading window"}
        except Exception as exc:
            logger.warning("Earnings vote failed for %s: %s", symbol, exc)
            return {"penalty": 0, "days_until": None, "evidence": "Earnings data unavailable"}

    async def _vote_insider(self, symbol: str, asset_class: str) -> dict:
        if asset_class != "stocks":
            return self._neutral_vote("N/A (not a stock)")

        try:
            activity = await self.sentiment_agent._fetch_insider_activity(symbol)
            recent_buys = int(activity.get("recent_insider_buy_count") or 0)
            buy_value = activity.get("recent_insider_buy_value_usd") or 0
            insider_signal = activity.get("insider_signal", "neutral")
            summary = activity.get("insider_summary", "No recent insider activity")

            if insider_signal == "bullish" and recent_buys >= 2:
                score = 80
                direction = "bullish"
            elif insider_signal == "bullish" and recent_buys >= 1:
                score = 65
                direction = "bullish"
            elif insider_signal == "bearish":
                score = 35
                direction = "bearish"
            else:
                score = 50
                direction = "neutral"

            value_suffix = f" (£{buy_value:,.0f})" if buy_value else ""
            evidence = f"{summary}{value_suffix}"
            return {"score": score, "direction": direction, "evidence": evidence}
        except Exception as exc:
            logger.warning("Insider vote failed for %s: %s", symbol, exc)
            return self._neutral_vote("SEC data unavailable")

    async def _generate_convergence_reasoning(
        self,
        symbol: str,
        asset_class: str,
        signal: str,
        confidence: int,
        votes: dict,
        votes_for: int,
        companion_name: str = "Apex",
    ) -> dict:
        vote_lines = []
        for source, data in votes.items():
            if source == "earnings":
                vote_lines.append(f"  {source}: {data.get('evidence', 'N/A')}")
                continue
            direction = data.get("direction", "neutral")
            evidence = data.get("evidence", "N/A")
            mark = "+" if direction == "bullish" else "-" if direction == "bearish" else "~"
            vote_lines.append(f"  [{mark}] {source}: {evidence}")

        votes_text = "\n".join(vote_lines)
        prompt = f"""You are {companion_name}, Unitrader's AI trader. A convergence analysis just completed.
Generate 4 versions of reasoning for this result. Be specific. Reference actual evidence.
Never say "AI analysis" — say "{companion_name}" or "I". Never use generic language.

Symbol: {symbol} ({asset_class})
Signal: {signal.upper()} — {confidence}% confidence
Votes agreeing: {votes_for} of 5 sources

Evidence from each source:
{votes_text}

Return JSON only:
{{
  "expert": "2-3 sentences. Technical language. Reference specific evidence. Mention how many sources agree.",
  "simple": "2 sentences. No jargon. Plain English. What does this mean for the user's money?",
  "metaphor": "1-2 sentences. Real-world comparison a beginner would understand immediately.",
  "one_line": "Max 12 words. A sharp verdict."
}}"""

        try:
            resp = await self.claude_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if resp.content else "{}"
            return json.loads(text)
        except Exception:
            action_word = "buy" if signal == "buy" else "sell" if signal == "sell" else "wait"
            return {
                "expert": f"{symbol}: {signal.upper()} at {confidence}% confidence. {votes_for}/5 sources agree with Apex's direction.",
                "simple": f"Apex sees a possible {action_word} setup in {symbol}, but only where the evidence lines up.",
                "metaphor": f"Think of it like {votes_for} specialists nodding in the same direction before Apex acts.",
                "one_line": f"{votes_for} of 5 signals agree — Apex says {signal.upper()}.",
            }

    def _determine_direction(self, votes: dict, final_score: int) -> str:
        if final_score < 45:
            return "sell"
        if final_score > 60:
            return "buy"
        return "watch"

    def _count_agreeing_votes(self, votes: dict, signal: str) -> int:
        target = "bullish" if signal == "buy" else "bearish" if signal == "sell" else "neutral"
        count = 0
        for source, vote in votes.items():
            if source == "earnings":
                continue
            direction = vote.get("direction", "neutral")
            if target == "bullish" and direction == "bullish":
                count += 1
            elif target == "bearish" and direction == "bearish":
                count += 1
            elif target == "neutral" and direction == "neutral":
                count += 1
        return count

    def _neutral_vote(self, evidence: str = "unavailable") -> dict:
        return {"score": 50, "direction": "neutral", "evidence": evidence}

    def _classify_macd(self, macd_info: dict[str, Any]) -> str:
        histogram = float(macd_info.get("histogram", 0.0) or 0.0)
        if histogram > 0.01:
            return "bullish"
        if histogram < -0.01:
            return "bearish"
        return "neutral"

    def _volume_ratio(self, volume: float | None, avg_volume: float | None = None) -> float:
        """Compute current volume relative to average.

        If avg_volume is provided, returns volume / avg_volume.
        Otherwise falls back to 1.0 (neutral).
        """
        if volume is None or volume <= 0:
            return 0.0 if volume is not None and volume <= 0 else 1.0
        if avg_volume and avg_volume > 0:
            return round(volume / avg_volume, 2)
        return 1.0

    def _days_until_earnings(self, earnings_date: str | None) -> int | None:
        if not earnings_date:
            return None
        try:
            earnings_day = datetime.fromisoformat(earnings_date).date()
            return (earnings_day - datetime.now(timezone.utc).date()).days
        except Exception:
            return None

    def _classify_fear_greed(self, value: int) -> str:
        if value <= 25:
            return "Extreme Fear"
        if value <= 45:
            return "Fear"
        if value <= 55:
            return "Neutral"
        if value <= 75:
            return "Greed"
        return "Extreme Greed"

    def _get_cached_stock_fear_greed(self) -> int:
        cached_at = _STOCK_FEAR_GREED_CACHE.get("cached_at")
        if cached_at and datetime.now(timezone.utc) - cached_at < _STOCK_FEAR_GREED_TTL:
            return int(_STOCK_FEAR_GREED_CACHE["value"])

        # Try live CNN Fear & Greed Index — fire-and-forget with fallback
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            future = loop.create_task(self._fetch_stock_fear_greed())
            # Don't await here — update cache async; return cached/fallback now
        except Exception:
            pass

        # Return last cached value or neutral fallback
        return int(_STOCK_FEAR_GREED_CACHE.get("value", 50))

    async def _fetch_stock_fear_greed(self) -> int:
        """Fetch CNN Fear & Greed Index for stocks and update the module cache."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
                resp.raise_for_status()
                data = resp.json()
                score = data.get("fear_and_greed", {}).get("score")
                if score is not None:
                    value = int(round(float(score)))
                    _STOCK_FEAR_GREED_CACHE["value"] = value
                    _STOCK_FEAR_GREED_CACHE["label"] = self._classify_fear_greed(value)
                    _STOCK_FEAR_GREED_CACHE["cached_at"] = datetime.now(timezone.utc)
                    logger.info("Stock Fear & Greed updated: %s (%s)", value, _STOCK_FEAR_GREED_CACHE["label"])
                    return value
        except Exception as exc:
            logger.warning("CNN Fear & Greed fetch failed: %s", exc)
        # Fallback: keep existing cached value
        return int(_STOCK_FEAR_GREED_CACHE.get("value", 50))
