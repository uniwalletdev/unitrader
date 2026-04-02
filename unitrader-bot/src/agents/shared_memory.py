"""
shared_memory.py — SharedContext and SharedMemory for fast context loading.

Provides a single-call mechanism to load a user's full trading/behavioral context
from the database. Results are cached for 60 seconds per user.

SharedContext is a dataclass containing all user data needed by orchestrator,
trading agent, and conversation agent (user settings, profile, stats, onboarding).

SharedMemory maintains a module-level cache and handles DB queries + cache
expiration logic.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Conversation, Trade, User, UserSettings
from src.market_context import MarketContext, resolve_market_context

logger = logging.getLogger(__name__)

# Module-level cache: user_id -> (SharedContext, loaded_at_timestamp)
_cache: dict[str, tuple["SharedContext", datetime]] = {}


@dataclass
class SharedContext:
    """Complete user context loaded from database in a single call.

    Used by agents to access user settings, trading stats, preferences,
    and recent onboarding messages without multiple DB round-trips.
    """

    user_id: str
    apex_name: str                          # Custom AI trader name
    goal: str                               # e.g. "grow_savings"
    risk_level: str                         # e.g. "balanced"
    max_trade_amount: float                 # USD
    exchange: str                           # e.g. "alpaca"
    explanation_level: str                  # e.g. "simple"
    trade_mode: str                         # e.g. "guided"
    paper_trading_enabled: bool
    trust_ladder_stage: int                 # 1-5, higher = more autonomy
    trading_paused: bool
    subscription_active: bool               # True if pro or trial active
    risk_disclosure_accepted: bool
    max_daily_loss_pct: float              # From UserSettings.max_daily_loss
    onboarding_complete: bool
    trader_class: str = "complete_novice"  # Detected trader profile
    trust_score: int = 100                # 0–100 derived from trade_feedback
    onboarding_profile: dict = field(default_factory=dict)
    favourite_symbols: list[str] = field(default_factory=list)
    total_trades: int = 0
    win_rate: float = 0.0                  # 0–100
    avg_confidence: float = 0.0            # 0–100
    last_signal: Optional[str] = None      # Latest signal from trading agent
    recent_onboarding_messages: list[dict] = field(default_factory=list)
    market_context: Optional[MarketContext] = None

    @classmethod
    def default(cls, user_id: str) -> "SharedContext":
        """Return a safe default SharedContext with minimal values."""
        return cls(
            user_id=user_id,
            apex_name="Claude",
            goal="grow_savings",
            risk_level="balanced",
            max_trade_amount=1000.0,
            exchange="alpaca",
            explanation_level="simple",
            trade_mode="guided",
            paper_trading_enabled=True,
            trust_ladder_stage=1,
            trading_paused=False,
            subscription_active=False,
            risk_disclosure_accepted=False,
            max_daily_loss_pct=5.0,
            onboarding_complete=False,
            trader_class="complete_novice",
            trust_score=100,
            onboarding_profile={},
            favourite_symbols=[],
            total_trades=0,
            win_rate=0.0,
            avg_confidence=0.0,
            last_signal=None,
            recent_onboarding_messages=[],
            market_context=None,
        )

    def is_novice(self) -> bool:
        """Return True if user is a complete novice or curious saver."""
        return self.trader_class in ("complete_novice", "curious_saver")

    def is_intermediate(self) -> bool:
        """Return True if user is self-taught."""
        return self.trader_class == "self_taught"

    def is_pro(self) -> bool:
        """Return True if user is experienced or semi-institutional."""
        return self.trader_class in ("experienced", "semi_institutional")

    def is_crypto_native(self) -> bool:
        """Return True if user is crypto-native trader."""
        return self.trader_class == "crypto_native"

    def preferred_explanation(self) -> str:
        """Return the preferred explanation level based on trader class.
        
        Defaults to user's explanation_level, but falls back to trader class defaults:
        - complete_novice: metaphor (vivid analogies)
        - curious_saver: simple (plain English)
        - self_taught: simple
        - experienced: expert (technical details)
        - semi_institutional: expert
        - crypto_native: expert
        """
        defaults = {
            "complete_novice": "metaphor",
            "curious_saver": "simple",
            "self_taught": "simple",
            "experienced": "expert",
            "semi_institutional": "expert",
            "crypto_native": "expert",
        }
        return self.explanation_level or defaults.get(self.trader_class, "simple")

    def default_trade_mode(self) -> str:
        """Return the default trade mode based on trader experience.
        
        - Novices: "guided" (with confirmations and educational context)
        - Others: "pro" (faster execution, minimal handholding)
        """
        return "guided" if self.is_novice() else "pro"


class SharedMemory:
    """Loads and caches user context with 60-second TTL.

    All methods are safe and never raise exceptions — failures return
    safe defaults.
    """

    CACHE_TTL_SECONDS = 60

    @staticmethod
    async def load(
        user_id: str,
        db: AsyncSession,
        trading_account_id: str | None = None,
    ) -> SharedContext:
        """Load user's full context from database with caching.

        Cache hit: returns cached context if < 60 seconds old
        Cache miss: queries database, caches result, returns context
        DB failure: logs error, returns safe default context

        Args:
            user_id: The user's UUID
            db: SQLAlchemy AsyncSession

        Returns:
            SharedContext: Full user context, either from cache or DB
        """
        try:
            # Check cache
            if user_id in _cache:
                context, loaded_at = _cache[user_id]
                if datetime.now(timezone.utc) - loaded_at < timedelta(
                    seconds=SharedMemory.CACHE_TTL_SECONDS
                ):
                    logger.debug(f"SharedMemory cache hit for user {user_id}")
                    return context

            # Cache miss or expired — load from DB
            logger.debug(f"SharedMemory cache miss for user {user_id}, querying DB")
            context = await SharedMemory._load_from_db(user_id, db, trading_account_id=trading_account_id)

            # Store in cache
            _cache[user_id] = (context, datetime.now(timezone.utc))

            return context

        except Exception as e:
            logger.exception(f"Error loading shared context for user {user_id}: {e}")
            return SharedContext.default(user_id)

    @staticmethod
    def invalidate(user_id: str) -> None:
        """Remove user's context from cache (e.g. after settings change).

        Args:
            user_id: The user's UUID
        """
        if user_id in _cache:
            del _cache[user_id]
            logger.debug(f"SharedMemory cache invalidated for user {user_id}")

    @staticmethod
    async def _load_from_db(
        user_id: str,
        db: AsyncSession,
        trading_account_id: str | None = None,
    ) -> SharedContext:
        """Load full user context from database.

        Queries:
        1. User + UserSettings (one JOIN)
        2. Aggregate trades for win_rate and total_trades
        3. Last 5 onboarding messages from Conversation

        If no UserSettings row exists, creates one with defaults.
        """
        try:
            # Query User and UserSettings (eager load to avoid async lazy-load)
            stmt = (
                select(User)
                .options(selectinload(User.settings))
                .where(User.id == user_id)
            )
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                logger.warning(f"User {user_id} not found in database")
                return SharedContext.default(user_id)

            # Get or create UserSettings
            settings = user.settings
            if not settings:
                logger.info(f"Creating default UserSettings for user {user_id}")
                settings = UserSettings(user_id=user_id)
                db.add(settings)
                await db.commit()

            # Aggregate trade stats
            trade_stats = await SharedMemory._aggregate_trade_stats(user_id, db)

            # Fetch last 5 onboarding messages
            onboarding_messages = await SharedMemory._fetch_onboarding_messages(
                user_id, db
            )

            # Extract favourite symbols from approved_assets
            favourite_symbols = []
            if settings.approved_assets and isinstance(settings.approved_assets, list):
                favourite_symbols = settings.approved_assets

            # Build SharedContext
            context = SharedContext(
                user_id=user_id,
                apex_name=user.ai_name or "Claude",
                goal=getattr(settings, "financial_goal", None) or "grow_savings",
                risk_level=getattr(settings, "risk_level_setting", None) or "balanced",
                max_trade_amount=settings.max_trade_amount or 1000.0,
                exchange="alpaca",  # Default — could query from ExchangeAPIKey
                explanation_level=settings.explanation_level or "simple",
                trade_mode=settings.trade_mode or "guided",
                paper_trading_enabled=True,  # Default — extend with user_settings table if needed
                trust_ladder_stage=1,  # Default — extend with user_settings table if needed
                trading_paused=not user.is_active,
                subscription_active=(
                    user.subscription_tier == "pro"
                    or (
                        user.trial_status == "active"
                        and user.trial_end_date
                        and user.trial_end_date > datetime.now(timezone.utc)
                    )
                ),
                risk_disclosure_accepted=settings.risk_disclosure_accepted or False,
                max_daily_loss_pct=settings.max_daily_loss or 5.0,
                onboarding_complete=getattr(settings, "onboarding_complete", False) or False,
                trader_class=settings.trader_class or "complete_novice",
                trust_score=int(getattr(settings, "trust_score", 100) or 100),
                onboarding_profile={},  # Could store as JSON in user_settings
                favourite_symbols=favourite_symbols,
                total_trades=trade_stats["total_trades"],
                win_rate=trade_stats["win_rate"],
                avg_confidence=trade_stats["avg_confidence"],
                last_signal=None,  # Could query from Conversation.response where context_type="trading"
                recent_onboarding_messages=onboarding_messages,
            )

            if trading_account_id:
                try:
                    context.market_context = await resolve_market_context(
                        db=db, user_id=user_id, trading_account_id=trading_account_id
                    )
                except Exception:
                    context.market_context = None

            return context

        except Exception as e:
            logger.exception(f"Error loading user {user_id} from database: {e}")
            return SharedContext.default(user_id)

    @staticmethod
    async def _aggregate_trade_stats(
        user_id: str, db: AsyncSession
    ) -> dict[str, float]:
        """Calculate total_trades, win_rate (0-100), and avg_confidence (0-100).

        Returns dict with keys: total_trades, win_rate, avg_confidence
        """
        try:
            # Count total closed trades
            stmt = (
                select(func.count(Trade.id))
                .where(and_(Trade.user_id == user_id, Trade.status == "closed"))
            )
            result = await db.execute(stmt)
            total_traded = result.scalar() or 0

            if total_traded == 0:
                return {
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "avg_confidence": 0.0,
                }

            # Count winning trades (profit > 0)
            stmt = (
                select(func.count(Trade.id))
                .where(
                    and_(
                        Trade.user_id == user_id,
                        Trade.status == "closed",
                        Trade.profit.isnot(None),
                        Trade.profit > 0,
                    )
                )
            )
            result = await db.execute(stmt)
            winning_trades = result.scalar() or 0

            # Average confidence score
            stmt = (
                select(func.avg(Trade.claude_confidence))
                .where(
                    and_(
                        Trade.user_id == user_id,
                        Trade.claude_confidence.isnot(None),
                    )
                )
            )
            result = await db.execute(stmt)
            avg_confidence = result.scalar() or 0.0

            win_rate = (winning_trades / total_traded * 100) if total_traded > 0 else 0.0

            return {
                "total_trades": total_traded,
                "win_rate": round(win_rate, 2),
                "avg_confidence": round(float(avg_confidence), 2),
            }

        except Exception as e:
            logger.exception(f"Error aggregating trade stats for user {user_id}: {e}")
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "avg_confidence": 0.0,
            }

    @staticmethod
    async def _fetch_onboarding_messages(
        user_id: str, db: AsyncSession
    ) -> list[dict]:
        """Fetch last 5 onboarding messages from Conversation table.

        Looks for conversations with context_type='onboarding' (or similar marker).
        Returns list of dicts with 'role' and 'content' keys.
        """
        try:
            # Query last 5 onboarding conversations
            stmt = (
                select(Conversation)
                .where(
                    and_(
                        Conversation.user_id == user_id,
                        Conversation.context_type == "onboarding",
                    )
                )
                .order_by(desc(Conversation.created_at))
                .limit(5)
            )
            result = await db.execute(stmt)
            conversations = result.scalars().all()

            # Transform to message-like dicts
            messages = []
            for conv in reversed(conversations):  # Reverse to chronological order
                messages.append(
                    {
                        "role": "user",
                        "content": conv.message,
                    }
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": conv.response,
                    }
                )

            return messages

        except Exception as e:
            logger.exception(
                f"Error fetching onboarding messages for user {user_id}: {e}"
            )
            return []
