"""
src/agents/memory/shared_memory.py — Symbiotic learning shared brain.

Every agent in Unitrader reads from and writes to this module so that
decisions made by one agent automatically inform all others.

Symbiotic Learning Concept
--------------------------
Traditional AI systems treat each decision in isolation.  Unitrader's agents
operate symbiotically: every action taken and its measured outcome is stored
in a shared memory, so patterns discovered by the trading agent are visible to
the conversation agent, patterns in user engagement are visible to the content
agent, and so on.

The two layers of shared memory are:

1. **AgentOutcome store** — an append-only history of every agent decision and
   its result.  Used for similarity search: "What happened the last 10 times
   BTC RSI was above 70 and sentiment was negative?"

2. **SharedContext blackboard** — a live key/value store with optional TTL.
   One agent publishes a value (e.g. "BTC_sentiment" = -0.7) and any other
   agent reads it before its next decision.  Expired entries are ignored.

Data Flow
---------
    TradingAgent decides to BUY BTCUSDT
        → stores AgentOutcome(action="buy", context={rsi:72, trend:"up"})
        → calls broadcast_outcome() which sets:
              shared_ctx["BTCUSDT_last_trade"] = {"direction":"buy", ...}
              shared_ctx["avoid_BTCUSDT_overbought"] = True   (if loss)

    ConversationAgent receives "should I buy BTC?"
        → calls get_all_context_for_asset("BTCUSDT")
        → gets {"BTCUSDT_sentiment": -0.7, "BTCUSDT_last_trade": {...}}
        → injects this into Claude system prompt for a grounded answer

    SentimentAgent finishes analysis
        → sets shared_ctx["BTCUSDT_sentiment"] = -0.7  (TTL=1h)
        → TradingAgent reads this before next cycle
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AgentOutcomeModel, SharedContextModel

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Pydantic data models
# ─────────────────────────────────────────────

class AgentOutcome(BaseModel):
    """A single recorded action + outcome from any agent.

    Attributes
    ----------
    id              : UUID string generated on creation.
    agent_name      : Logical name of the agent (e.g. "trading_agent").
    action_type     : Broad category — one of: "trade", "analysis",
                      "conversation", "content".
    user_id         : ID of the user whose session triggered this action.
                      May be None for scheduled/background actions.
    context         : Snapshot of conditions at decision time.
                      For trading: {rsi, macd_histogram, trend, sentiment,
                      fear_greed, price, volume_change}.
                      For conversation: {detected_context, sentiment_score}.
    action_taken    : What the agent decided.
                      For trading: {symbol, direction, size, entry_price,
                      stop_loss, take_profit}.
                      For conversation: {response_length, tone, context_used}.
    result          : Measured outcome after the fact.
                      For trading: {profit_pct, holding_period_h, exit_reason}.
                      For conversation: {user_rated_helpful, follow_up_count}.
    confidence_score: Agent's self-reported confidence (0.0 = no idea,
                      1.0 = highly certain).
    asset           : Ticker involved, if any (e.g. "BTCUSDT", "AAPL").
    exchange        : Exchange name if relevant ("binance", "alpaca", "oanda").
    timestamp       : UTC datetime of the action.
    tags            : Free-form labels for grouping (e.g. ["overbought",
                      "negative_sentiment", "high_volume"]).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str
    action_type: str  # trade | analysis | conversation | content
    user_id: str | None = None
    context: dict = Field(default_factory=dict)
    action_taken: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    asset: str | None = None
    exchange: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = Field(default_factory=list)


class PerformanceMetrics(BaseModel):
    """Aggregated performance statistics for one agent over a time window.

    Attributes
    ----------
    agent_name      : Name of the agent being measured.
    total_actions   : Total decisions recorded in the timeframe.
    success_rate    : Fraction of actions with a positive result (0.0–1.0).
    avg_confidence  : Mean confidence score across all actions.
    best_conditions : Context snapshot from the highest-performing cluster
                      (most common context dict among successful actions).
    worst_conditions: Context snapshot from the lowest-performing cluster.
    timeframe       : Human-readable description of the window (e.g. "30d").
    """

    agent_name: str
    total_actions: int
    success_rate: float
    avg_confidence: float
    best_conditions: dict
    worst_conditions: dict
    timeframe: str


class SharedContext(BaseModel):
    """A single key/value entry on the inter-agent blackboard.

    Attributes
    ----------
    key        : Unique identifier, typically "<ASSET>_<metric>" or a global
                 key like "market_fear_greed".
    value      : Any JSON-serialisable Python value.
    set_by     : Name of the agent that last wrote this entry.
    expires_at : UTC expiry time; None means permanent until overwritten.
    timestamp  : When this entry was last written.
    """

    key: str
    value: Any
    set_by: str
    expires_at: datetime | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────
# Similarity helpers  (pure functions, no I/O)
# ─────────────────────────────────────────────

def _rsi_band(rsi: float | None) -> str:
    """Bucket RSI into named bands for approximate similarity matching."""
    if rsi is None:
        return "unknown"
    if rsi < 30:
        return "oversold"
    if rsi < 45:
        return "low"
    if rsi < 55:
        return "neutral"
    if rsi < 70:
        return "high"
    return "overbought"


def _sentiment_band(score: float | None) -> str:
    """Bucket sentiment score (−1 to +1) into named bands."""
    if score is None:
        return "unknown"
    if score < -0.5:
        return "very_negative"
    if score < -0.1:
        return "negative"
    if score < 0.1:
        return "neutral"
    if score < 0.5:
        return "positive"
    return "very_positive"


def _context_score(stored: dict, query: dict, asset: str | None) -> int:
    """Score how similar two context dicts are.

    Returns an integer similarity score (higher = more similar).
    Checks: same RSI band, same sentiment band, same trend direction,
    same asset.  Each matching dimension contributes points.
    """
    score = 0

    if asset and stored.get("asset") == asset:
        score += 3

    stored_rsi = _rsi_band(stored.get("rsi"))
    query_rsi = _rsi_band(query.get("rsi"))
    if stored_rsi == query_rsi and stored_rsi != "unknown":
        score += 2

    stored_sent = _sentiment_band(stored.get("sentiment_score"))
    query_sent = _sentiment_band(query.get("sentiment_score"))
    if stored_sent == query_sent and stored_sent != "unknown":
        score += 2

    if (
        stored.get("trend")
        and query.get("trend")
        and stored["trend"] == query["trend"]
    ):
        score += 2

    if (
        stored.get("macd_signal")
        and query.get("macd_signal")
        and stored["macd_signal"] == query["macd_signal"]
    ):
        score += 1

    return score


def _is_successful(result: dict) -> bool:
    """Determine whether an outcome result dict represents a success.

    Checks common result shapes used by different agents:
    - trade: profit_pct > 0
    - conversation: user_rated_helpful == True
    - content: engagement == "high"
    - analysis: is_correct == True
    - generic: success == True
    """
    if result.get("success") is True:
        return True
    if result.get("is_correct") is True:
        return True
    if result.get("user_rated_helpful") is True:
        return True
    if result.get("engagement") == "high":
        return True
    profit = result.get("profit_pct") or result.get("profit") or 0
    try:
        return float(profit) > 0
    except (TypeError, ValueError):
        return False


# ─────────────────────────────────────────────
# SharedMemory
# ─────────────────────────────────────────────

class SharedMemory:
    """Shared brain for all Unitrader agents.

    Provides two complementary memory systems:

    1. **Outcome store** — persist + query historical agent decisions and
       their measured results.  Enables "learning from the past" by finding
       outcomes in similar market/sentiment conditions.

    2. **Context blackboard** — a live key/value store (with optional TTL)
       that any agent can read and write.  Enables real-time coordination
       without tight coupling between agents.

    All methods are async and use the injected ``AsyncSession``.

    Usage
    -----
        async with AsyncSessionLocal() as db:
            mem = SharedMemory(db)

            # record a trading decision and its outcome
            outcome = AgentOutcome(
                agent_name="trading_agent",
                action_type="trade",
                user_id=user_id,
                context={"rsi": 72, "trend": "uptrend", "sentiment_score": 0.3},
                action_taken={"symbol": "BTCUSDT", "direction": "buy", "size": 0.1},
                result={"profit_pct": 2.4, "exit_reason": "take_profit"},
                confidence_score=0.78,
                asset="BTCUSDT",
                exchange="binance",
                tags=["overbought", "bullish_macd"],
            )
            outcome_id = await mem.store_outcome(outcome)

            # find similar past decisions to inform the next one
            similar = await mem.query_similar_context(
                context={"rsi": 69, "trend": "uptrend"},
                action_type="trade",
                asset="BTCUSDT",
            )

            # read what the sentiment agent published
            ctx = await mem.get_shared_context("BTCUSDT_sentiment")
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ─────────────────────────────────────────
    # Outcome store
    # ─────────────────────────────────────────

    async def store_outcome(self, outcome: AgentOutcome) -> str:
        """Persist an agent outcome to the database.

        Args:
            outcome: Fully populated ``AgentOutcome`` instance.

        Returns:
            The outcome's UUID string.
        """
        # Guard against FK violation: if user_id doesn't exist in users
        # table (e.g. 'system' row missing), set to None so the INSERT
        # succeeds — the outcome data is more important than the FK link.
        uid = outcome.user_id
        if uid:
            from sqlalchemy import select, text
            try:
                chk = await self._db.execute(
                    select(text("1")).select_from(text("users")).where(text("id = :uid")),
                    {"uid": uid},
                )
                if chk.scalar_one_or_none() is None:
                    logger.warning(
                        "store_outcome: user_id=%s not found in users table — setting to NULL", uid
                    )
                    uid = None
            except Exception:
                uid = None  # safe fallback

        row = AgentOutcomeModel(
            id=outcome.id,
            agent_name=outcome.agent_name,
            action_type=outcome.action_type,
            user_id=uid,
            context_data=outcome.context,
            action_data=outcome.action_taken,
            result_data=outcome.result,
            confidence=outcome.confidence_score,
            asset=outcome.asset,
            exchange=outcome.exchange,
            tags=outcome.tags,
            created_at=outcome.timestamp,
        )
        self._db.add(row)
        try:
            await self._db.flush()
        except Exception as exc:
            logger.error("SharedMemory.store_outcome failed: %s", exc)
            await self._db.rollback()
            raise
        logger.debug(
            "Stored outcome %s for agent=%s action=%s asset=%s",
            outcome.id, outcome.agent_name, outcome.action_type, outcome.asset,
        )
        return outcome.id

    async def query_similar_context(
        self,
        context: dict,
        action_type: str,
        asset: str | None = None,
        limit: int = 10,
    ) -> list[AgentOutcome]:
        """Find past outcomes whose context most closely matches the current one.

        Similarity is evaluated across four dimensions:
        - **Asset match** — same symbol carries the most weight.
        - **RSI band** — "overbought" / "oversold" / etc.
        - **Sentiment band** — bucketed from the raw −1 to +1 score.
        - **Trend direction** — "uptrend" / "downtrend" / "consolidating".
        - **MACD signal** — "bullish" / "bearish".

        Candidates are pre-filtered by ``action_type`` (and optionally
        ``asset``) to keep the in-Python scoring manageable.  A larger pool
        of the most recent 500 matching rows is fetched from the DB then
        re-ranked by similarity score before returning the top ``limit``.

        Args:
            context    : Current context dict (same shape as ``AgentOutcome.context``).
            action_type: Filter to outcomes of the same category.
            asset      : Optional — if provided, same-asset records score higher.
            limit      : Maximum number of results to return.

        Returns:
            List of ``AgentOutcome`` objects, most relevant first.
        """
        # Pull a recent pool for in-Python scoring; 500 keeps memory bounded.
        _POOL = 500

        stmt = (
            select(AgentOutcomeModel)
            .where(AgentOutcomeModel.action_type == action_type)
            .order_by(AgentOutcomeModel.created_at.desc())
            .limit(_POOL)
        )
        if asset:
            # Weight the fetch towards same-asset rows but also include
            # same action_type rows with no asset for general patterns.
            stmt = (
                select(AgentOutcomeModel)
                .where(
                    and_(
                        AgentOutcomeModel.action_type == action_type,
                        or_(
                            AgentOutcomeModel.asset == asset,
                            AgentOutcomeModel.asset.is_(None),
                        ),
                    )
                )
                .order_by(AgentOutcomeModel.created_at.desc())
                .limit(_POOL)
            )

        result = await self._db.execute(stmt)
        rows = result.scalars().all()

        # Score in Python and sort descending
        scored: list[tuple[int, AgentOutcomeModel]] = []
        for row in rows:
            stored_ctx = row.context_data or {}
            sim = _context_score(stored_ctx, context, asset)
            scored.append((sim, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        return [_row_to_outcome(row) for _, row in top]

    # ─────────────────────────────────────────
    # Performance metrics
    # ─────────────────────────────────────────

    async def get_agent_performance(
        self,
        agent_name: str,
        timeframe_days: int = 30,
    ) -> PerformanceMetrics:
        """Compute aggregated performance metrics for one agent.

        Calculates success rate, average confidence, and the most common
        context snapshot among successful vs unsuccessful actions.

        Args:
            agent_name     : Name of the agent to analyse.
            timeframe_days : Look-back window in days (default 30).

        Returns:
            ``PerformanceMetrics`` populated from the DB.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=timeframe_days)

        stmt = (
            select(AgentOutcomeModel)
            .where(
                and_(
                    AgentOutcomeModel.agent_name == agent_name,
                    AgentOutcomeModel.created_at >= cutoff,
                )
            )
            .order_by(AgentOutcomeModel.created_at.desc())
        )
        result = await self._db.execute(stmt)
        rows = result.scalars().all()

        total = len(rows)
        if total == 0:
            return PerformanceMetrics(
                agent_name=agent_name,
                total_actions=0,
                success_rate=0.0,
                avg_confidence=0.0,
                best_conditions={},
                worst_conditions={},
                timeframe=f"{timeframe_days}d",
            )

        successes = [r for r in rows if _is_successful(r.result_data or {})]
        failures = [r for r in rows if not _is_successful(r.result_data or {})]

        success_rate = len(successes) / total
        avg_conf = sum(r.confidence for r in rows) / total

        best_conditions = _most_common_context(successes)
        worst_conditions = _most_common_context(failures)

        return PerformanceMetrics(
            agent_name=agent_name,
            total_actions=total,
            success_rate=round(success_rate, 4),
            avg_confidence=round(avg_conf, 4),
            best_conditions=best_conditions,
            worst_conditions=worst_conditions,
            timeframe=f"{timeframe_days}d",
        )

    # ─────────────────────────────────────────
    # Context blackboard — write
    # ─────────────────────────────────────────

    async def set_shared_context(
        self,
        key: str,
        value: Any,
        set_by: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """Write a key/value pair to the shared context blackboard.

        If the key already exists it is overwritten (upsert semantics).

        Args:
            key         : Unique string key (e.g. "BTCUSDT_sentiment").
            value       : Any JSON-serialisable Python value.
            set_by      : Name of the writing agent.
            ttl_seconds : If set, the entry expires this many seconds from now.
                          Pass None for a persistent entry.

        Examples
        --------
            # Sentiment agent publishes BTC fear score (1-hour TTL)
            await mem.set_shared_context("BTCUSDT_sentiment", -0.7, "sentiment_agent", ttl_seconds=3600)

            # Trading agent marks a pattern to avoid (no expiry)
            await mem.set_shared_context("avoid_BTCUSDT_overbought", True, "trading_agent")
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None

        # Try update first
        stmt = select(SharedContextModel).where(SharedContextModel.key == key)
        result = await self._db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.value_data = {"_v": value}
            existing.set_by = set_by
            existing.expires_at = expires_at
            existing.updated_at = now
        else:
            row = SharedContextModel(
                key=key,
                value_data={"_v": value},
                set_by=set_by,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            self._db.add(row)

        try:
            await self._db.flush()
        except Exception as exc:
            logger.error("SharedMemory.set_shared_context failed key=%s: %s", key, exc)
            await self._db.rollback()
            raise

        logger.debug("SharedContext set key=%s by=%s ttl=%s", key, set_by, ttl_seconds)

    # ─────────────────────────────────────────
    # Context blackboard — read
    # ─────────────────────────────────────────

    async def get_shared_context(self, key: str) -> SharedContext | None:
        """Retrieve a shared context value by key.

        Returns ``None`` if the key does not exist or has expired.

        Args:
            key: The context key to look up.

        Returns:
            A ``SharedContext`` instance, or ``None``.
        """
        stmt = select(SharedContextModel).where(SharedContextModel.key == key)
        result = await self._db.execute(stmt)
        row = result.scalar_one_or_none()

        if not row:
            return None

        now = datetime.now(timezone.utc)
        if row.expires_at and row.expires_at.replace(tzinfo=timezone.utc) < now:
            logger.debug("SharedContext key=%s has expired", key)
            return None

        raw = row.value_data or {}
        value = raw.get("_v")
        exp = row.expires_at
        if exp and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

        return SharedContext(
            key=row.key,
            value=value,
            set_by=row.set_by,
            expires_at=exp,
            timestamp=row.updated_at.replace(tzinfo=timezone.utc)
            if row.updated_at.tzinfo is None
            else row.updated_at,
        )

    async def get_all_context_for_asset(self, asset: str) -> dict[str, Any]:
        """Return all non-expired shared context entries for a given asset.

        Matches any key that starts with ``<asset>_`` (case-insensitive).

        Args:
            asset: The ticker symbol, e.g. "BTCUSDT" or "AAPL".

        Returns:
            Dict mapping the full key to its current value.
            E.g. {"BTCUSDT_sentiment": -0.7, "BTCUSDT_trend": "bearish"}

        Example
        -------
            ctx = await mem.get_all_context_for_asset("BTCUSDT")
            # {"BTCUSDT_sentiment": -0.7, "BTCUSDT_fear_greed": 23, ...}
        """
        prefix = asset.upper() + "_"
        now = datetime.now(timezone.utc)

        stmt = select(SharedContextModel).where(
            SharedContextModel.key.like(f"{prefix}%")
        )
        result = await self._db.execute(stmt)
        rows = result.scalars().all()

        out: dict[str, Any] = {}
        for row in rows:
            exp = row.expires_at
            if exp:
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < now:
                    continue
            raw = row.value_data or {}
            out[row.key] = raw.get("_v")

        return out

    # ─────────────────────────────────────────
    # Broadcast
    # ─────────────────────────────────────────

    async def broadcast_outcome(self, outcome: AgentOutcome) -> None:
        """Store an outcome and propagate key learnings to the blackboard.

        After storing the outcome, derives actionable context entries that
        other agents can consume before their next decision.  This is the
        core mechanism for cross-agent learning.

        Patterns written to the blackboard:
        - ``{ASSET}_last_{ACTION_TYPE}`` — summary of the most recent action.
        - ``{ASSET}_recent_success`` — True/False if result was positive.
        - ``avoid_{ASSET}_{TAG}`` — True when a tagged condition led to a loss.
          Consuming agents should treat these as caution signals.

        Args:
            outcome: The completed ``AgentOutcome`` to store and broadcast.
        """
        await self.store_outcome(outcome)

        if not outcome.asset:
            return

        success = _is_successful(outcome.result)
        asset_upper = outcome.asset.upper()
        agent = outcome.agent_name

        # Publish the last action summary for this asset
        await self.set_shared_context(
            key=f"{asset_upper}_last_{outcome.action_type}",
            value={
                "agent": agent,
                "action": outcome.action_taken,
                "success": success,
                "confidence": outcome.confidence_score,
                "timestamp": outcome.timestamp.isoformat(),
            },
            set_by=agent,
            ttl_seconds=86_400,  # 24 hours
        )

        # Publish whether the most recent result for this asset was good
        await self.set_shared_context(
            key=f"{asset_upper}_recent_success",
            value=success,
            set_by=agent,
            ttl_seconds=3_600,  # 1 hour — short-lived signal
        )

        # On failure: tag each context label as a caution pattern
        if not success and outcome.tags:
            for tag in outcome.tags:
                safe_tag = tag.replace(" ", "_").lower()
                await self.set_shared_context(
                    key=f"avoid_{asset_upper}_{safe_tag}",
                    value=True,
                    set_by=agent,
                    ttl_seconds=43_200,  # 12 hours
                )
                logger.info(
                    "SharedMemory: caution pattern set — avoid_%s_%s (agent=%s)",
                    asset_upper, safe_tag, agent,
                )

    # ─────────────────────────────────────────
    # Housekeeping
    # ─────────────────────────────────────────

    async def purge_expired_context(self) -> int:
        """Delete SharedContext rows whose expiry has passed.

        Intended to be called periodically (e.g. every hour) from a
        background task to keep the table tidy.

        Returns:
            Number of rows deleted.
        """
        now = datetime.now(timezone.utc)
        stmt = delete(SharedContextModel).where(
            and_(
                SharedContextModel.expires_at.is_not(None),
                SharedContextModel.expires_at < now,
            )
        )
        result = await self._db.execute(stmt)
        count = result.rowcount
        if count:
            logger.info("SharedMemory: purged %d expired context entries", count)
        return count


# ─────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────

def _row_to_outcome(row: AgentOutcomeModel) -> AgentOutcome:
    """Convert an ORM row to an ``AgentOutcome`` Pydantic model."""
    ts = row.created_at
    if ts and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return AgentOutcome(
        id=row.id,
        agent_name=row.agent_name,
        action_type=row.action_type,
        user_id=row.user_id,
        context=row.context_data or {},
        action_taken=row.action_data or {},
        result=row.result_data or {},
        confidence_score=row.confidence,
        asset=row.asset,
        exchange=row.exchange,
        timestamp=ts or datetime.now(timezone.utc),
        tags=row.tags or [],
    )


def _most_common_context(rows: list[AgentOutcomeModel]) -> dict:
    """Return a representative context dict from a list of outcome rows.

    Uses a simple majority-vote approach: for each context key, picks the
    most frequently occurring value across all rows.

    Returns an empty dict if ``rows`` is empty.
    """
    if not rows:
        return {}

    key_value_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        ctx = row.context_data or {}
        for k, v in ctx.items():
            if k not in key_value_counts:
                key_value_counts[k] = {}
            str_v = str(v)
            key_value_counts[k][str_v] = key_value_counts[k].get(str_v, 0) + 1

    representative: dict = {}
    for k, counts in key_value_counts.items():
        most_common_str = max(counts, key=counts.__getitem__)
        # Try to restore original type by looking it up in any row
        for row in rows:
            ctx = row.context_data or {}
            if k in ctx and str(ctx[k]) == most_common_str:
                representative[k] = ctx[k]
                break
        else:
            representative[k] = most_common_str

    return representative
