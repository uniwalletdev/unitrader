"""
shared_memory.py — SharedContext and SharedMemory for fast context loading.

Provides a single-call mechanism to load a user's full trading/behavioral context
from the database. Results are cached for 60 seconds per user.

SharedContext is a dataclass containing all user data needed by orchestrator,
trading agent, and conversation agent (user settings, profile, stats, onboarding).

SharedMemory maintains a module-level cache and handles DB queries + cache
expiration logic.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Conversation, ExchangeAPIKey, Trade, TradingAccount, User, UserSettings
from security import decrypt_api_key
from src.integrations.exchange_client import get_exchange_client
from src.market_context import ExecutionVenue, MarketContext, resolve_market_context

logger = logging.getLogger(__name__)

# Module-level cache: (user_id, trading_account_id or "") -> (SharedContext, loaded_at_timestamp)
# Per-account keys avoid returning a context loaded without market_context when the caller passes trading_account_id.
_cache: dict[tuple[str, str], tuple["SharedContext", datetime]] = {}


@dataclass
class SharedContext:
    """Complete user context loaded from database in a single call.

    Used by agents to access user settings, trading stats, preferences,
    and recent onboarding messages without multiple DB round-trips.
    """

    user_id: str
    apex_name: str                          # Custom AI trader name (legacy alias)
    ai_name: str                            # Personalised companion name (settings-first)
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
    # Conversation / chat: connected brokers and live positions (populated in _load_from_db)
    trading_accounts: list[dict] = field(default_factory=list)
    open_positions: list[dict] = field(default_factory=list)
    user_name: Optional[str] = None
    subscription_tier: str = "free"
    # Closed-trade aggregates (DB truth for P&L / history questions)
    closed_net_pnl_usd: float = 0.0
    best_closed_trade_usd: float = 0.0
    worst_closed_trade_usd: float = 0.0
    recent_closed_trades: list[dict] = field(default_factory=list)
    # Chat-oriented snapshots (last N closed trades; overlaps recent_closed_trades with different shape)
    performance: dict = field(default_factory=dict)
    recent_trades: list[dict] = field(default_factory=list)
    execution_venue: Optional[ExecutionVenue] = None
    account_balance_usd: float = 0.0  # Primary account balance for chat context

    @classmethod
    def default(cls, user_id: str) -> "SharedContext":
        """Return a safe default SharedContext with minimal values."""
        return cls(
            user_id=user_id,
            apex_name="Apex",
            ai_name="Apex",
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
            trading_accounts=[],
            open_positions=[],
            user_name=None,
            subscription_tier="free",
            closed_net_pnl_usd=0.0,
            best_closed_trade_usd=0.0,
            worst_closed_trade_usd=0.0,
            recent_closed_trades=[],
            performance={
                "total_trades": 0,
                "win_rate": 0,
                "total_pnl": 0.0,
                "best_trade": None,
                "worst_trade": None,
            },
            recent_trades=[],
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
            acct = (trading_account_id or "").strip()
            cache_key = (user_id, acct)
            # Check cache
            if cache_key in _cache:
                context, loaded_at = _cache[cache_key]
                if datetime.now(timezone.utc) - loaded_at < timedelta(
                    seconds=SharedMemory.CACHE_TTL_SECONDS
                ):
                    logger.debug(
                        "SharedMemory cache hit for user %s account=%r",
                        user_id,
                        acct or "(none)",
                    )
                    return context

            # Cache miss or expired — load from DB
            logger.debug(
                "SharedMemory cache miss for user %s account=%r, querying DB",
                user_id,
                acct or "(none)",
            )
            context = await SharedMemory._load_from_db(user_id, db, trading_account_id=trading_account_id)

            # Store in cache
            _cache[cache_key] = (context, datetime.now(timezone.utc))

            return context

        except Exception as e:
            logger.exception(f"Error loading shared context for user {user_id}: {e}")
            return SharedContext.default(user_id)

    @staticmethod
    def invalidate(user_id: str) -> None:
        """Remove all cached contexts for this user (all trading_account_id variants).

        Args:
            user_id: The user's UUID
        """
        to_del = [k for k in list(_cache.keys()) if k[0] == user_id]
        for k in to_del:
            del _cache[k]
        if to_del:
            logger.debug(
                "SharedMemory cache invalidated for user %s (%d entries)",
                user_id,
                len(to_del),
            )

    @staticmethod
    async def _fetch_one_account_balance(
        k: ExchangeAPIKey,
        account: TradingAccount | None,
        db: AsyncSession,
        *,
        now: datetime,
    ) -> dict:
        """Single connected exchange row with a live balance fetch (best-effort).

        Persists last-known balances on TradingAccount and falls back to them when
        the live fetch fails.
        """
        entry = {
            "exchange": (k.exchange or "unknown").lower(),
            "is_paper": bool(k.is_paper),
            "balance_usd": 0.0,
            "balance_error": None,
            "balance_note": None,
        }
        try:
            api_key, api_secret = decrypt_api_key(
                k.encrypted_api_key, k.encrypted_api_secret
            )
            client = get_exchange_client(
                k.exchange, api_key, api_secret, is_paper=k.is_paper
            )
            bal = await client.get_account_balance()
            await client.aclose()
            entry["balance_usd"] = round(float(bal), 2)
            entry["balance_note"] = "live"
            if account is not None:
                account.last_known_balance_usd = float(entry["balance_usd"])
                account.last_balance_synced_at = now
                account.last_synced_at = now
        except Exception as exc:
            logger.warning(
                "Balance fetch failed for %s (key %s): %s",
                k.exchange,
                k.id,
                exc,
            )
            entry["balance_error"] = "unavailable"
            if account is not None and account.last_known_balance_usd is not None:
                entry["balance_usd"] = float(account.last_known_balance_usd)
                if account.last_balance_synced_at is not None:
                    age_s = (now - account.last_balance_synced_at).total_seconds()
                    mins = max(int(age_s // 60), 0)
                    entry["balance_note"] = f"cached (last synced {mins}m ago)"
                else:
                    entry["balance_note"] = "cached"
            else:
                entry["balance_note"] = "not synced"
        return entry

    @staticmethod
    async def _fetch_trading_accounts_snapshot(user_id: str, db: AsyncSession) -> list[dict]:
        """Active exchange keys for chat context with live balances (parallel, cached 60s)."""
        try:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(ExchangeAPIKey, TradingAccount)
                .outerjoin(
                    TradingAccount,
                    ExchangeAPIKey.trading_account_id == TradingAccount.id,
                )
                .where(
                    ExchangeAPIKey.user_id == user_id,
                    ExchangeAPIKey.is_active == True,  # noqa: E712
                )
            )
            rows: list[tuple[ExchangeAPIKey, TradingAccount | None]] = list(result.all())
            if not rows:
                return []
            out = list(
                await asyncio.gather(
                    *[
                        SharedMemory._fetch_one_account_balance(k, acct, db, now=now)
                        for (k, acct) in rows
                    ]
                )
            )
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            return out
        except Exception as exc:
            logger.warning("trading_accounts snapshot failed for %s: %s", user_id, exc)
            return []

    @staticmethod
    async def _fetch_open_positions_snapshot(user_id: str, db: AsyncSession) -> list[dict]:
        try:
            result = await db.execute(
                select(Trade)
                .where(
                    Trade.user_id == user_id,
                    Trade.status == "open",
                )
                .order_by(Trade.created_at.desc())
                .limit(50)
            )
            rows = result.scalars().all()
            out: list[dict] = []
            for t in rows:
                entry = float(t.entry_price or 0)
                qty = float(t.quantity or 0)
                out.append(
                    {
                        "symbol": t.symbol,
                        "side": (t.side or "").upper(),
                        "qty": t.quantity,
                        "entry_price": entry,
                        "exchange": (t.exchange or "alpaca").lower(),
                        "notional_entry_usd": round(entry * qty, 2),
                    }
                )
            return out
        except Exception as exc:
            logger.warning("open_positions snapshot failed for %s: %s", user_id, exc)
            return []

    @staticmethod
    def _trade_realized_usd(t: Trade) -> float:
        """Closed-trade P&L from profit/loss columns (no single `pnl` field on Trade)."""
        return float((t.profit or 0) - (t.loss or 0))

    @staticmethod
    async def _fetch_performance_snapshot(user_id: str, db: AsyncSession) -> dict[str, Any]:
        """Lightweight P&L summary for chat context (last 50 closed trades)."""
        empty: dict[str, Any] = {
            "total_trades": 0,
            "win_rate": 0,
            "total_pnl": 0.0,
            "best_trade": None,
            "worst_trade": None,
        }
        try:
            result = await db.execute(
                select(Trade)
                .where(
                    Trade.user_id == user_id,
                    Trade.status == "closed",
                )
                .order_by(desc(Trade.closed_at), desc(Trade.created_at))
                .limit(50)
            )
            trades = list(result.scalars().all())
            if not trades:
                return empty

            pnls = [SharedMemory._trade_realized_usd(t) for t in trades]
            wins = [p for p in pnls if p > 0]
            total_pnl = sum(pnls)
            win_rate = round(len(wins) / len(pnls) * 100) if pnls else 0

            best = max(trades, key=SharedMemory._trade_realized_usd)
            worst = min(trades, key=SharedMemory._trade_realized_usd)
            bp = SharedMemory._trade_realized_usd(best)
            wp = SharedMemory._trade_realized_usd(worst)

            return {
                "total_trades": len(trades),
                "win_rate": win_rate,
                "total_pnl": round(total_pnl, 2),
                "best_trade": (
                    f"{best.symbol} +${bp:.2f}" if bp >= 0 else f"{best.symbol} ${bp:.2f}"
                ),
                "worst_trade": (
                    f"{worst.symbol} -${abs(wp):.2f}" if wp < 0 else f"{worst.symbol} +${wp:.2f}"
                ),
            }
        except Exception as e:
            logger.warning("Performance snapshot failed: %s", e)
            return dict(empty)

    @staticmethod
    async def _fetch_recent_trades_snapshot(user_id: str, db: AsyncSession) -> list[dict]:
        """Last 5 closed trades for chat context."""
        try:
            result = await db.execute(
                select(Trade)
                .where(
                    Trade.user_id == user_id,
                    Trade.status == "closed",
                )
                .order_by(desc(Trade.closed_at), desc(Trade.created_at))
                .limit(5)
            )
            trades = result.scalars().all()
            return [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "pnl": round(SharedMemory._trade_realized_usd(t), 2),
                    "closed_at": t.closed_at.strftime("%d %b") if t.closed_at else "unknown",
                }
                for t in trades
            ]
        except Exception as e:
            logger.warning("Recent trades snapshot failed: %s", e)
            return []

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
        3. Closed-trade insights, performance snapshot (50), recent trades (5)
        4. Last 5 onboarding messages from Conversation

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
            closed_insights = await SharedMemory._fetch_closed_trade_insights(user_id, db)
            performance, recent_trades = await asyncio.gather(
                SharedMemory._fetch_performance_snapshot(user_id, db),
                SharedMemory._fetch_recent_trades_snapshot(user_id, db),
            )

            # Fetch last 5 onboarding messages
            onboarding_messages = await SharedMemory._fetch_onboarding_messages(
                user_id, db
            )

            trading_accounts = await SharedMemory._fetch_trading_accounts_snapshot(
                user_id, db
            )
            open_positions = await SharedMemory._fetch_open_positions_snapshot(user_id, db)

            # Extract favourite symbols from approved_assets
            favourite_symbols = []
            if settings.approved_assets and isinstance(settings.approved_assets, list):
                favourite_symbols = settings.approved_assets

            primary_exchange = (
                trading_accounts[0]["exchange"] if trading_accounts else "alpaca"
            )

            # Surface primary account balance for chat context
            primary_balance = 0.0
            for acct in trading_accounts:
                bal = acct.get("balance_usd", 0.0)
                if bal and bal > 0:
                    primary_balance = bal
                    break

            settings_ai = (getattr(settings, "ai_name", None) or "").strip()
            user_ai = (getattr(user, "ai_name", None) or "").strip()
            resolved_ai = settings_ai or user_ai or "Apex"

            trust_ladder_stage = 1
            if getattr(settings, "risk_disclosure_accepted", False):
                trust_ladder_stage = 2
            if getattr(settings, "onboarding_complete", False):
                trust_ladder_stage = 3

            # Build SharedContext
            context = SharedContext(
                user_id=user_id,
                apex_name=resolved_ai,
                ai_name=resolved_ai,
                goal=getattr(settings, "financial_goal", None) or "grow_savings",
                risk_level=getattr(settings, "risk_level_setting", None) or "balanced",
                max_trade_amount=settings.max_trade_amount or 1000.0,
                exchange=primary_exchange,
                explanation_level=settings.explanation_level or "simple",
                trade_mode=settings.trade_mode or "guided",
                paper_trading_enabled=True,  # Default — extend with user_settings table if needed
                trust_ladder_stage=trust_ladder_stage,
                trading_paused=bool(settings.trading_paused),
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
                trading_accounts=trading_accounts,
                open_positions=open_positions,
                user_name=user.email,
                subscription_tier=(user.subscription_tier or "free").lower(),
                closed_net_pnl_usd=closed_insights["closed_net_pnl_usd"],
                best_closed_trade_usd=closed_insights["best_closed_trade_usd"],
                worst_closed_trade_usd=closed_insights["worst_closed_trade_usd"],
                recent_closed_trades=closed_insights["recent_closed_trades"],
                performance=performance,
                recent_trades=recent_trades,
                account_balance_usd=primary_balance,
            )

            if trading_account_id:
                try:
                    context.market_context = await resolve_market_context(
                        db=db, user_id=user_id, trading_account_id=trading_account_id
                    )
                except Exception as exc:
                    logger.warning(
                        "resolve_market_context failed for user %s trading_account_id=%s: %s",
                        user_id,
                        trading_account_id,
                        exc,
                    )
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
    async def _fetch_closed_trade_insights(
        user_id: str, db: AsyncSession
    ) -> dict[str, Any]:
        """Net / best / worst realized P&L and a short recent-closed list for chat prompts."""
        empty = {
            "closed_net_pnl_usd": 0.0,
            "best_closed_trade_usd": 0.0,
            "worst_closed_trade_usd": 0.0,
            "recent_closed_trades": [],
        }
        try:
            realized = func.coalesce(Trade.profit, 0) - func.coalesce(Trade.loss, 0)
            agg_stmt = (
                select(
                    func.count(Trade.id),
                    func.coalesce(func.sum(realized), 0),
                    func.max(realized),
                    func.min(realized),
                ).where(
                    Trade.user_id == user_id,
                    Trade.status == "closed",
                )
            )
            agg_row = (await db.execute(agg_stmt)).one()
            n_closed = int(agg_row[0] or 0)
            if n_closed == 0:
                return empty

            net = float(agg_row[1] or 0)
            best = float(agg_row[2] or 0)
            worst = float(agg_row[3] or 0)

            recent_stmt = (
                select(Trade)
                .where(
                    Trade.user_id == user_id,
                    Trade.status == "closed",
                )
                .order_by(desc(Trade.closed_at), desc(Trade.created_at))
                .limit(8)
            )
            recent_rows = (await db.execute(recent_stmt)).scalars().all()
            recent_closed_trades: list[dict] = []
            for t in recent_rows:
                pnl = float((t.profit or 0) - (t.loss or 0))
                closed_at = t.closed_at.isoformat() if t.closed_at else None
                recent_closed_trades.append(
                    {
                        "symbol": t.symbol,
                        "side": (t.side or "").upper(),
                        "realized_usd": round(pnl, 2),
                        "closed_at": closed_at,
                    }
                )

            return {
                "closed_net_pnl_usd": round(net, 2),
                "best_closed_trade_usd": round(best, 2),
                "worst_closed_trade_usd": round(worst, 2),
                "recent_closed_trades": recent_closed_trades,
            }
        except Exception as exc:
            logger.warning("closed trade insights failed for %s: %s", user_id, exc)
            return empty

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
