"""
routers/trading.py — Trading API endpoints for Unitrader.

Endpoints:
    POST /api/trading/execute             — Run analysis + execute trade
    GET  /api/trading/open-positions      — All open positions
    GET  /api/trading/history             — Closed trade history
    GET  /api/trading/performance         — Aggregated statistics
    POST /api/trading/close-position      — Manual close at market
    GET  /api/trading/risk-analysis       — Daily loss, remaining budget
    GET  /api/trading/simulate-history   — Historical portfolio simulation
    POST /api/trading/exchange-keys       — Save encrypted exchange API keys
    GET  /api/trading/exchange-keys       — List connected exchanges
    DELETE /api/trading/exchange-keys/{exchange} — Remove exchange keys
    GET  /api/trading/exchange-assets     — Instant tier-1 symbol list for connected exchange (no AI)
    GET  /api/trading/market-top          — Dynamic AI-ranked top picks (hourly cache)
    GET  /api/trading/symbol-search       — Fuzzy symbol + company name search
    GET  /api/trading/ai-picks            — AI analysis of dynamic symbol candidates
"""

import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import get_db
from typing import Literal

from models import (
    AuditLog,
    ApexNotification,
    ExchangeAPIKey,
    TradingAccount,
    Trade,
    TradeFeedback,
    TradeUndoToken,
    User,
    UserSettings,
)
from routers.auth import get_current_user
from schemas import SuccessResponse, TradeResponse
from security import encrypt_api_key, hash_api_key, decrypt_api_key
from src.agents.goal_tracking_agent import GoalTrackingAgent
from src.agents.shared_memory import SharedMemory
from src.integrations.alpaca_rate_limiter import alpaca_limiter
from src.integrations.market_data import classify_asset
from src.agents.orchestrator import get_orchestrator
from src.integrations.exchange_client import (
    get_exchange_client,
    validate_alpaca_keys,
    validate_binance_keys,
    validate_coinbase_keys,
    validate_kraken_keys,
    validate_oanda_keys,
)
from src.services.trade_monitoring import enforce_loss_limits
from src.services.subscription import check_trade_limit
from src.services.unitrader_notifications import get_unitrader_notification_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trading", tags=["Trading"])
performance_router = APIRouter(prefix="/api/performance", tags=["Performance"])
trades_router = APIRouter(prefix="/api/trades", tags=["Trades"])


def _human_account_type(trader_class: str) -> str:
    m = {
        "complete_novice": "Beginner investor",
        "curious_saver": "Passive saver",
        "self_taught": "Self-taught trader",
        "experienced": "Experienced trader",
        "semi_institutional": "Institutional trader",
        "crypto_native": "Crypto trader",
    }
    return m.get(trader_class, "Trader")


# ─────────────────────────────────────────────
# Request / Response Bodies
# ─────────────────────────────────────────────

class ExecuteTradeRequest(BaseModel):
    symbol: str
    exchange: str  # binance | alpaca | oanda | coinbase
    trading_account_id: str | None = None
    is_paper: bool | None = None


class AnalyzeTradeRequest(BaseModel):
    symbol: str
    exchange: str  # binance | alpaca | oanda | coinbase
    trader_class: str | None = None
    trading_account_id: str
    is_paper: bool | None = None


class TradeFeedbackRequest(BaseModel):
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=2000)
    is_paper: bool


class ClosePositionRequest(BaseModel):
    trade_id: str


class ConnectExchangeRequest(BaseModel):
    exchange: str = Field(..., pattern="^(alpaca|binance|oanda|coinbase|kraken)$")
    api_key: str = Field(..., min_length=1)
    api_secret: str = Field(..., min_length=1)
    is_paper: bool = Field(True, description="Whether these are paper/sandbox keys")


VALID_EXCHANGES = {"alpaca", "binance", "oanda", "coinbase", "kraken"}


def _account_label(exchange: str, is_paper: bool) -> str:
    suffix = "Paper" if is_paper else "Live"
    return f"{exchange.title()} {suffix}"


async def _ensure_trading_account(
    db: AsyncSession,
    *,
    user_id: str,
    exchange: str,
    is_paper: bool,
    external_account_id: str | None = None,
) -> TradingAccount:
    result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.user_id == user_id,
            TradingAccount.exchange == exchange,
            TradingAccount.is_paper == is_paper,
            TradingAccount.is_active == True,  # noqa: E712
        )
    )
    account = result.scalar_one_or_none()
    if account:
        if external_account_id and not account.external_account_id:
            account.external_account_id = external_account_id
        account.account_label = _account_label(exchange, is_paper)
        return account

    account = TradingAccount(
        user_id=user_id,
        exchange=exchange,
        is_paper=is_paper,
        account_label=_account_label(exchange, is_paper),
        external_account_id=external_account_id,
        is_active=True,
    )
    db.add(account)
    await db.flush()
    return account


async def _resolve_trading_account_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    exchange: str,
    trading_account_id: str | None = None,
    is_paper: bool | None = None,
    allow_fallback_preferred: bool = True,
) -> TradingAccount | None:
    if trading_account_id:
        result = await db.execute(
            select(TradingAccount).where(
                TradingAccount.id == trading_account_id,
                TradingAccount.user_id == user_id,
                TradingAccount.exchange == exchange,
                TradingAccount.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    filters = [
        TradingAccount.user_id == user_id,
        TradingAccount.exchange == exchange,
        TradingAccount.is_active == True,  # noqa: E712
    ]
    if is_paper is not None:
        filters.append(TradingAccount.is_paper == is_paper)
    result = await db.execute(
        select(TradingAccount)
        .where(and_(*filters))
        .order_by(TradingAccount.is_paper.desc(), TradingAccount.created_at.desc())
    )
    accounts = result.scalars().all()
    if not accounts:
        return None
    if len(accounts) == 1:
        return accounts[0]

    if allow_fallback_preferred:
        settings_result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        user_settings = settings_result.scalar_one_or_none()
        preferred_id = getattr(user_settings, "preferred_trading_account_id", None)
        if preferred_id:
            for account in accounts:
                if account.id == preferred_id:
                    return account

    paper_accounts = [account for account in accounts if account.is_paper]
    if len(paper_accounts) == 1:
        return paper_accounts[0]
    return None


async def _sync_preferred_trading_account_if_stale(
    db: AsyncSession,
    *,
    user_id: str,
    connected_account_id: str,
) -> None:
    """Set preferred_trading_account_id when missing or pointing at inactive/missing account."""
    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = settings_result.scalar_one_or_none()
    if not user_settings:
        user_settings = UserSettings(user_id=user_id)
        db.add(user_settings)
        await db.flush()
    preferred_id = getattr(user_settings, "preferred_trading_account_id", None)
    preferred_ok = False
    if preferred_id:
        ta_row = await db.execute(
            select(TradingAccount).where(
                TradingAccount.id == preferred_id,
                TradingAccount.user_id == user_id,
                TradingAccount.is_active == True,  # noqa: E712
            )
        )
        preferred_ok = ta_row.scalar_one_or_none() is not None
    if not preferred_ok:
        user_settings.preferred_trading_account_id = connected_account_id
        await db.commit()


# ─────────────────────────────────────────────
# Validation dispatcher
# ─────────────────────────────────────────────

async def _validate_exchange_keys(exchange: str, api_key: str, api_secret: str, is_paper: bool) -> float:
    """Validate keys against the exchange and return the account balance.

    Raises HTTPException(400) on failure.
    """
    if exchange not in settings.enabled_exchange_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{exchange.capitalize()} is not currently available. Coming soon.",
        )
    try:
        if exchange == "alpaca":
            valid = await validate_alpaca_keys(api_key, api_secret, paper=is_paper)
            if not valid:
                raise ValueError("Alpaca rejected the credentials")
        elif exchange == "binance":
            valid = await validate_binance_keys(api_key, api_secret)
            if not valid:
                raise ValueError("Binance rejected the credentials")
        elif exchange == "oanda":
            valid = await validate_oanda_keys(api_key, api_secret)
            if not valid:
                raise ValueError("OANDA rejected the credentials")
        elif exchange == "kraken":
            valid = await validate_kraken_keys(api_key, api_secret)
            if not valid:
                raise ValueError("Kraken rejected the credentials")
        elif exchange == "coinbase":
            import httpx as _httpx
            try:
                await validate_coinbase_keys(api_key, api_secret)
            except _httpx.HTTPStatusError as cb_exc:
                is_pem = api_secret.strip().startswith("-----BEGIN") and "PRIVATE KEY" in api_secret
                status_code = cb_exc.response.status_code if cb_exc.response is not None else 0
                if status_code in (401, 403):
                    if is_pem:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=(
                                "Coinbase rejected the CDP key (401). "
                                "Make sure the API Key Name exactly matches the private key, "
                                "trade permissions are enabled, and no IP allowlist blocks our server. "
                                "Re-copy the full JSON from portal.cdp.coinbase.com and paste it again."
                            ),
                        )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Coinbase rejected these credentials. "
                            "Legacy keys are not supported for Advanced Trade. "
                            "Create a new CDP key at portal.cdp.coinbase.com, "
                            "copy the JSON and paste it in the connection box."
                        ),
                    )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Coinbase returned HTTP {status_code}. Please try again or contact support.",
                )
            except Exception as cb_exc:
                logger.warning("Coinbase key validation failed: %s", cb_exc)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Coinbase connection failed. Check your API key and secret.",
                )

        client = get_exchange_client(exchange, api_key, api_secret, is_paper=is_paper)
        balance = await client.get_account_balance()
        await client.aclose()
        return balance
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Exchange balance check failed (%s): %s", exchange, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not connect to {exchange}. Verify your API credentials.",
        )


# ─────────────────────────────────────────────
# POST /api/trading/exchange-keys — Connect exchange
# ─────────────────────────────────────────────

@router.post("/exchange-keys")
async def connect_exchange(
    body: ConnectExchangeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save (or update) encrypted exchange API keys for the current user.

    Validates the keys against the exchange before storing them.
    Keys are encrypted with Fernet and never returned after saving.
    """
    exchange = body.exchange.lower()
    is_paper = body.is_paper
    # Coinbase has no paper/sandbox trading; force live to prevent bad labels & mode splits.
    if exchange == "coinbase":
        is_paper = False

    balance = await _validate_exchange_keys(exchange, body.api_key, body.api_secret, is_paper)

    try:
        enc_key, enc_secret = encrypt_api_key(body.api_key, body.api_secret)
        key_hash_val = hash_api_key(body.api_key)

        account = await _ensure_trading_account(
            db,
            user_id=current_user.id,
            exchange=exchange,
            is_paper=is_paper,
        )

        existing = await db.execute(
            select(ExchangeAPIKey).where(
                ExchangeAPIKey.user_id == current_user.id,
                ExchangeAPIKey.exchange == exchange,
                ExchangeAPIKey.is_paper == is_paper,
                ExchangeAPIKey.is_active == True,  # noqa: E712
            )
        )
        old_key = existing.scalar_one_or_none()
        if old_key:
            old_key.is_active = False
            old_key.rotated_at = datetime.now(timezone.utc)

        now = datetime.now(timezone.utc)
        new_key = ExchangeAPIKey(
            user_id=current_user.id,
            trading_account_id=account.id,
            exchange=exchange,
            encrypted_api_key=enc_key,
            encrypted_api_secret=enc_secret,
            key_hash=key_hash_val,
            is_active=True,
            is_paper=is_paper,
        )
        db.add(new_key)
        await db.commit()
        await db.refresh(new_key)

        await _sync_preferred_trading_account_if_stale(
            db,
            user_id=current_user.id,
            connected_account_id=account.id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to save exchange keys for user %s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save exchange keys. Please try again.",
        )

    return {
        "status": "success",
        "data": {
            "exchange": exchange,
            "trading_account_id": account.id,
            "account_label": account.account_label,
            "connected_at": new_key.created_at.isoformat() if new_key.created_at else now.isoformat(),
            "is_paper": is_paper,
            "balance_usd": round(balance, 2),
            "message": f"{exchange.title()} connected successfully",
        },
    }


# ─────────────────────────────────────────────
# GET /api/trading/exchange-keys — List connected exchanges
# ─────────────────────────────────────────────

@router.get("/exchange-keys")
async def list_exchange_keys(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all connected exchanges for the current user (no secrets exposed)."""
    result = await db.execute(
        select(ExchangeAPIKey)
        .options(selectinload(ExchangeAPIKey.trading_account))
        .where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.is_active == True,  # noqa: E712
        )
    )
    keys = result.scalars().all()
    return {
        "status": "success",
        "data": [
            {
                "trading_account_id": k.trading_account_id,
                "exchange": k.exchange,
                "account_label": k.trading_account.account_label if k.trading_account else _account_label(k.exchange, k.is_paper),
                "connected_at": k.created_at.isoformat() if k.created_at else None,
                "is_paper": k.is_paper,
                "last_used": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ],
    }


# ─────────────────────────────────────────────
# DELETE /api/trading/exchange-keys/{exchange} — Disconnect
# ─────────────────────────────────────────────

@router.delete("/exchange-keys/{exchange}")
async def disconnect_exchange(
    exchange: str = Path(..., pattern="^(alpaca|binance|oanda|coinbase|kraken)$"),
    trading_account_id: str | None = Query(None),
    is_paper: bool | None = Query(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate exchange keys (soft-delete)."""
    result = await db.execute(
        select(ExchangeAPIKey)
        .options(selectinload(ExchangeAPIKey.trading_account))
        .where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.exchange == exchange.lower(),
            *((
                (ExchangeAPIKey.trading_account_id == trading_account_id,)
                if trading_account_id
                else ()
            )),
            *((
                (ExchangeAPIKey.is_paper == is_paper,)
                if is_paper is not None
                else ()
            )),
            ExchangeAPIKey.is_active == True,  # noqa: E712
        )
    )
    key_rows = result.scalars().all()
    if not key_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active {exchange} connection found",
        )
    if len(key_rows) > 1 and not trading_account_id and is_paper is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="multiple_accounts_found",
        )

    try:
        for key_row in key_rows:
            key_row.is_active = False
            key_row.rotated_at = datetime.now(timezone.utc)
            if key_row.trading_account:
                key_row.trading_account.is_active = False
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to disconnect %s for user %s: %s", exchange, current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect exchange. Please try again.",
        )

    return {"status": "success", "data": {"exchange": exchange, "message": f"{exchange.title()} disconnected"}}


# ─────────────────────────────────────────────
# GET /api/trading/account-balances — Live balance per connected exchange
# ─────────────────────────────────────────────

@router.get("/account-balances")
async def get_account_balances(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch live balance for every active exchange key the user has.

    Returns per-key data:  exchange, is_paper, balance, currency.
    Errors on individual exchanges are returned as balance=None.
    """
    # IMPORTANT: avoid async lazy-loading relationships inside this endpoint.
    # MissingGreenlet happens when any code path triggers a relationship load.
    result = await db.execute(
        select(ExchangeAPIKey, TradingAccount)
        .outerjoin(TradingAccount, ExchangeAPIKey.trading_account_id == TradingAccount.id)
        .where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.is_active == True,  # noqa: E712
        )
    )
    key_rows: list[tuple[ExchangeAPIKey, TradingAccount | None]] = list(result.all())
    now = datetime.now(timezone.utc)

    async def _fetch_one(k: ExchangeAPIKey, acct: TradingAccount | None) -> dict:
        entry = {
            "trading_account_id": k.trading_account_id,
            "exchange": k.exchange,
            "account_label": (
                (acct.account_label if acct else None) or _account_label(k.exchange, k.is_paper)
            ),
            "is_paper": k.is_paper,
            "connected_at": k.created_at.isoformat() if k.created_at else None,
            "last_used": k.last_used_at.isoformat() if k.last_used_at else None,
            "balance": None,
            "currency": "USD",
            "balance_note": None,
            "error": None,
        }
        try:
            api_key, api_secret = decrypt_api_key(
                k.encrypted_api_key, k.encrypted_api_secret
            )
            client = get_exchange_client(
                k.exchange, api_key, api_secret, is_paper=k.is_paper
            )
            balance = await client.get_account_balance()
            await client.aclose()
            entry["balance"] = round(balance, 2)
            entry["balance_note"] = "live"
            if acct is not None:
                acct.last_known_balance_usd = float(entry["balance"])
                acct.last_balance_synced_at = now
                acct.last_synced_at = now
            # Standardize display currency to USD across the product.
            # (Exchange integrations may have native base currencies, but UI displays USD.)
            entry["currency"] = "USD"
        except Exception as exc:
            logger.warning(
                "Failed to fetch balance for %s (user %s): %s",
                k.exchange, current_user.id, exc,
            )
            entry["error"] = str(exc)
            if acct is not None and acct.last_known_balance_usd is not None:
                entry["balance"] = float(acct.last_known_balance_usd)
                if acct.last_balance_synced_at is not None:
                    age_s = (now - acct.last_balance_synced_at).total_seconds()
                    mins = max(int(age_s // 60), 0)
                    entry["balance_note"] = f"cached (last synced {mins}m ago)"
                else:
                    entry["balance_note"] = "cached"
        return entry

    items = await asyncio.gather(*[_fetch_one(k, acct) for (k, acct) in key_rows])
    try:
        await db.commit()
    except Exception:
        await db.rollback()

    return {"status": "success", "data": list(items)}


# ─────────────────────────────────────────────
# GET /api/trading/market-top — Dynamic AI-ranked top picks (hourly cache)
# ─────────────────────────────────────────────

# Server-side cache: {exchange: {"data": [...], "at": datetime}}
_market_top_cache: dict[str, dict] = {}
_MARKET_TOP_TTL_MINUTES = 60


@router.get("/market-top")
async def get_market_top(
    exchange: str = Query(default="alpaca", pattern="^(alpaca|binance|oanda|coinbase|kraken)$"),
    trading_account_id: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=10),
    refresh: bool = Query(default=False),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the day's top AI-ranked opportunities from a large symbol universe.

    Unlike /ai-picks which analyses a fixed list, this endpoint:
    1. Scans the exchange universe using fast momentum pre-scoring
    2. Selects the top 5 candidates by price change % and volume
    3. Runs full Claude AI analysis on those candidates only
    4. Returns the top `limit` symbols by AI confidence

    Results are cached for 60 minutes. Pass ?refresh=true to force update.
    """
    from datetime import datetime, timezone
    from src.agents.core.trading_agent import TradingAgent
    from src.agents.shared_memory import SharedContext, SharedMemory
    from src.watchlists import score_universe, SYMBOL_LABELS
    from src.market_context import Exchange, MarketContext, resolve_market_context

    ex = exchange.lower()
    req_market_context: MarketContext | None = None
    if trading_account_id:
        req_market_context = await resolve_market_context(
            db=db, user_id=current_user.id, trading_account_id=trading_account_id
        )
        ex = req_market_context.exchange.value
    if ex not in {"alpaca", "binance", "oanda", "coinbase", "kraken"}:
        raise HTTPException(status_code=400, detail="unsupported_exchange")

    # Return cached result if still fresh
    cached = _market_top_cache.get(ex)
    if not refresh and cached:
        age_minutes = (datetime.now(timezone.utc) - cached["at"]).total_seconds() / 60
        if age_minutes < _MARKET_TOP_TTL_MINUTES:
            return {
                "status": "success",
                "resolved_exchange": ex,
                "data": cached["data"][:limit],
                "cached": True,
                "age_minutes": round(age_minutes),
            }

    try:
        # Step 1: fast momentum pre-filter — no Claude, just market data
        if req_market_context is None:
            # Browsing mode (no connected account): use the requested exchange for universe selection.
            try:
                req_market_context = MarketContext(
                    exchange=Exchange(ex),
                    is_paper=True,
                    trading_account_id="legacy_unscoped",
                    user_id=current_user.id,
                )
            except Exception:
                req_market_context = None

        candidates = (await score_universe(market_context=req_market_context))[:5]

        # Step 2: AI analysis of candidates only
        ctx = await SharedMemory.load(current_user.id, db, trading_account_id=trading_account_id)
        if ctx is None:
            ctx = SharedContext.default(current_user.id)
        ctx.exchange = ex

        agent = TradingAgent(user_id=current_user.id)
        semaphore = asyncio.Semaphore(3)

        async def _analyse_one(sym: str) -> dict | None:
            async with semaphore:
                try:
                    result = await agent.analyze(symbol=sym, exchange=ex, context=ctx)
                    if result is None:
                        return None
                    entry = result.market_data.get("price", 0) if result.market_data else 0
                    price_change = result.market_data.get("price_change_pct", 0) if result.market_data else 0
                    sl_pct = result.suggested_stop_loss_pct or 2.0
                    tp_pct = result.suggested_take_profit_pct or 4.0
                    return {
                        "symbol": sym,
                        "label": SYMBOL_LABELS.get(sym, sym),
                        "decision": result.signal.upper() if result.signal else "WAIT",
                        "confidence": result.confidence,
                        "reasoning": result.explanation_expert or "",
                        "entry_price": round(entry, 4) if entry else None,
                        "price_change_pct": round(float(price_change), 2) if price_change else 0,
                        "stop_loss": round(entry * (1 - sl_pct / 100), 4) if entry else None,
                        "take_profit": round(entry * (1 + tp_pct / 100), 4) if entry else None,
                        "market_condition": (result.market_data or {}).get("trend", ""),
                        "key_factors": result.key_factors or [],
                    }
                except Exception as exc:
                    logger.debug("market-top: analysis failed for %s: %s", sym, exc)
                    return None

        raw = await asyncio.gather(*[_analyse_one(s) for s in candidates])
        results = [r for r in raw if r is not None]

        # Sort: actionable signals first, then by confidence
        buys_sells = sorted([r for r in results if r["decision"] != "WAIT"], key=lambda r: r["confidence"], reverse=True)
        waits = sorted([r for r in results if r["decision"] == "WAIT"], key=lambda r: r["confidence"], reverse=True)
        ordered = (buys_sells + waits)[:10]

        # Cache full result
        _market_top_cache[ex] = {"data": ordered, "at": datetime.now(timezone.utc)}

        return {
            "status": "success",
            "resolved_exchange": ex,
            "data": ordered[:limit],
            "cached": False,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("market-top error for user %s", current_user.id)
        raise HTTPException(
            status_code=500,
            detail="market_top_unavailable",
        )


# ─────────────────────────────────────────────
# GET /api/trading/exchange-assets — Instant tier-1 symbol list (no AI)
# ─────────────────────────────────────────────

@router.get("/exchange-assets")
async def get_exchange_assets(
    exchange: str = Query(default="alpaca", pattern="^(alpaca|binance|oanda|coinbase|kraken)$"),
    trading_account_id: str | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=20),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the top N most liquid symbols for a connected exchange — no AI analysis.

    This is the instant tier-1 response (<50ms) that populates the dashboard
    immediately while AI analysis loads in the background via /market-top.

    Symbols are ordered by approximate liquidity / market importance. The
    frontend renders tiles immediately using WebSocket live prices; AI decisions
    are added when /market-top completes (tier-2 enhancement).
    """
    from src.watchlists import SYMBOL_UNIVERSE, SYMBOL_LABELS
    from src.market_context import resolve_market_context

    ex = exchange.lower()
    if trading_account_id:
        ctx = await resolve_market_context(
            db=db, user_id=current_user.id, trading_account_id=trading_account_id
        )
        ex = ctx.exchange.value
    universe_full = SYMBOL_UNIVERSE.get(ex)
    if not universe_full:
        raise HTTPException(status_code=400, detail="unsupported_exchange")
    universe = universe_full[:limit]
    data = [
        {"symbol": sym, "label": SYMBOL_LABELS.get(sym, sym)}
        for sym in universe
    ]
    return {"status": "success", "resolved_exchange": ex, "data": data}


# ─────────────────────────────────────────────
# GET /api/trading/symbol-search — Fuzzy ticker + company name search
# ─────────────────────────────────────────────

@router.get("/symbol-search")
async def search_symbols(
    q: str = Query(min_length=1, max_length=50),
    exchange: str = Query(default="alpaca", pattern="^(alpaca|binance|oanda|coinbase|kraken)$"),
    trading_account_id: str | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=20),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search symbols by ticker or company name.

    Supports partial matches on both ticker (AAPL) and company name (Apple).
    Returns results from the AI scanning universe for the given exchange.

    When ``trading_account_id`` is provided, the exchange is taken from that
    account (same as /exchange-assets) so search matches the active broker.

    Examples:
        ?q=apple&exchange=alpaca  → [{symbol: AAPL, label: Apple Inc, ...}]
        ?q=bitcoin&exchange=binance → [{symbol: BTCUSDT, label: Bitcoin, ...}]
        ?q=euro&exchange=oanda   → [{symbol: EUR_USD, label: Euro / US Dollar, ...}]
    """
    from src.market_context import resolve_market_context
    from src.watchlists import symbol_search

    ex = exchange.lower()
    if trading_account_id:
        ctx = await resolve_market_context(
            db=db, user_id=current_user.id, trading_account_id=trading_account_id
        )
        ex = ctx.exchange.value
    results = symbol_search(q, exchange=ex, limit=limit)
    return {"status": "success", "resolved_exchange": ex, "data": results}


# ─────────────────────────────────────────────
# GET /api/trading/ai-picks — AI analysis of top dynamic candidates
# ─────────────────────────────────────────────

@router.get("/ai-picks")
async def get_ai_picks(
    exchange: str = Query(default="alpaca", pattern="^(alpaca|binance|oanda|coinbase|kraken)$"),
    trading_account_id: str = Query(...),
    limit: int = Query(default=3, ge=1, le=10),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analyse dynamic top candidates and return picks without executing.

    Uses score_universe() to pre-filter the scanning universe down to 5
    candidates, then runs full AI analysis and returns the highest-confidence
    results sorted by confidence descending.
    """
    from src.agents.core.trading_agent import TradingAgent
    from src.agents.shared_memory import SharedContext, SharedMemory
    from src.market_context import resolve_market_context
    from src.watchlists import score_universe, SYMBOL_LABELS

    try:
        market_ctx = await resolve_market_context(
            db=db, user_id=current_user.id, trading_account_id=trading_account_id
        )

        ctx = await SharedMemory.load(
            current_user.id, db, trading_account_id=trading_account_id
        )
        if ctx is None:
            ctx = SharedContext.default(current_user.id)
        ctx.exchange = market_ctx.exchange.value

        # Dynamic candidates instead of fixed watchlist
        symbols = (await score_universe(market_context=market_ctx))[:5]

        agent = TradingAgent(user_id=current_user.id)
        semaphore = asyncio.Semaphore(3)

        async def _analyse_one(sym: str) -> dict | None:
            async with semaphore:
                try:
                    result = await agent.analyze(symbol=sym, exchange=market_ctx.exchange.value, context=ctx)
                    if result is None:
                        return None
                    entry = result.market_data.get("price", 0) if result.market_data else 0
                    sl_pct = result.suggested_stop_loss_pct or 2.0
                    tp_pct = result.suggested_take_profit_pct or 4.0
                    return {
                        "symbol": sym,
                        "label": SYMBOL_LABELS.get(sym, sym),
                        "decision": result.signal.upper() if result.signal else "WAIT",
                        "confidence": result.confidence,
                        "reasoning": result.explanation_expert or "",
                        "entry_price": round(entry, 4) if entry else None,
                        "stop_loss": round(entry * (1 - sl_pct / 100), 4) if entry else None,
                        "take_profit": round(entry * (1 + tp_pct / 100), 4) if entry else None,
                        "market_condition": (result.market_data or {}).get("trend", ""),
                        "key_factors": result.key_factors or [],
                    }
                except Exception as exc:
                    logger.debug("ai-picks: analysis failed for %s: %s", sym, exc)
                    return None

        raw = await asyncio.gather(*[_analyse_one(s) for s in symbols])
        picks = [p for p in raw if p and p["decision"] != "WAIT"]
        picks.sort(key=lambda p: p["confidence"], reverse=True)
        if len(picks) < limit:
            waits = [p for p in raw if p and p["decision"] == "WAIT"]
            waits.sort(key=lambda p: p["confidence"], reverse=True)
            picks += waits[: limit - len(picks)]

        return {"status": "success", "data": picks[:limit]}

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ai-picks error for user %s", current_user.id)
        raise HTTPException(
            status_code=500,
            detail="ai_picks_unavailable",
        )


# ─────────────────────────────────────────────
# POST /api/trading/execute — Full cycle: analyse → decide → place order
# ─────────────────────────────────────────────

@router.post("/execute")
async def execute_trade(
    body: ExecuteTradeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run a complete trade cycle for the given symbol and exchange.

    Calls TradingAgent.run_cycle() which:
      1. Fetches live market data
      2. Runs Claude AI analysis and decision
      3. Places a real (or paper) order on the exchange if signal is BUY/SELL
      4. Persists the trade to the database
      5. Returns the outcome

    After a successful execution the symbol is also saved to
    UserSettings.approved_assets so the 5-minute background loop continues
    trading it automatically without further user action.

    Use POST /analyze for analysis-only (no order placed).
    """
    from src.agents.core.trading_agent import TradingAgent

    try:
        # ── Onboarding gate ────────────────────────────────────────────────────
        settings_result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        _user_settings = settings_result.scalar_one_or_none()
        if _user_settings and not getattr(_user_settings, "onboarding_complete", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="onboarding_required",
            )

        # ── Trade limit (free tier: 10/month) ─────────────────────────────────
        trade_check = await check_trade_limit(current_user, db)
        if not trade_check["allowed"]:
            reason = trade_check.get("reason", "unknown")
            detail = reason if reason in {"trial_limit_reached", "subscription_required"} else "subscription_required"
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

        # ── Full cycle: analyse + execute ──────────────────────────────────────
        agent = TradingAgent(user_id=current_user.id)
        result = await agent.run_cycle(
            symbol=body.symbol.upper(),
            exchange_name=body.exchange.lower(),
            trading_account_id=body.trading_account_id,
            is_paper=body.is_paper,
        )

        if result is None:
            logger.error("run_cycle returned None for user %s symbol %s", current_user.id, body.symbol)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="agent_unavailable")

        if isinstance(result, dict) and result.get("status") == "error":
            reason = result.get("reason", "market_data_unavailable")
            logger.error("run_cycle error user=%s symbol=%s: %s", current_user.id, body.symbol, reason)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=reason)

        # ── Persist symbol so the background loop picks it up automatically ───
        if isinstance(result, dict) and result.get("status") == "executed":
            try:
                if not _user_settings:
                    r2 = await db.execute(select(UserSettings).where(UserSettings.user_id == current_user.id))
                    _user_settings = r2.scalar_one_or_none()
                if _user_settings:
                    sym_upper = body.symbol.upper()
                    current_assets: list = list(_user_settings.approved_assets or [])
                    if sym_upper not in current_assets:
                        current_assets.insert(0, sym_upper)
                        _user_settings.approved_assets = current_assets
                        await db.commit()
            except Exception as _exc:
                logger.warning("Could not persist approved_assets for user %s: %s", current_user.id, _exc)

        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Trade execute failed for user %s", current_user.id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="trade_execution_failed")


# ─────────────────────────────────────────────
# POST /api/trading/analyze
# ─────────────────────────────────────────────

@router.post("/analyze")
async def analyze_trade(
    body: AnalyzeTradeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run analysis only (no execution)."""
    try:
        from src.market_context import resolve_market_context

        _ = await resolve_market_context(
            db=db, user_id=current_user.id, trading_account_id=body.trading_account_id
        )
        orchestrator = get_orchestrator()
        result = await orchestrator.route(
            user_id=current_user.id,
            action="trade_analyze",
            payload={
                "symbol": body.symbol.upper(),
                "exchange": body.exchange.lower(),
                "trader_class": body.trader_class,
                "trading_account_id": body.trading_account_id,
                "is_paper": body.is_paper,
            },
            db=db,
        )
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Trade analyze failed for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=500, detail="trade_analyze_failed")


# ─────────────────────────────────────────────
# GET /api/trading/open-positions
# ─────────────────────────────────────────────

@router.get("/open-positions")
async def get_open_positions(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    trading_account_id: str | None = Query(None),
    exchange: str | None = Query(None),
    is_paper: bool | None = Query(None),
):
    """Return all currently open positions for the authenticated user."""
    filters = [Trade.user_id == current_user.id, Trade.status == "open"]
    if trading_account_id:
        filters.append(Trade.trading_account_id == trading_account_id)
    if exchange:
        filters.append(Trade.exchange == exchange.lower())
    if is_paper is not None:
        filters.append(Trade.is_paper == is_paper)
    result = await db.execute(
        select(Trade)
        .where(and_(*filters))
        .order_by(Trade.created_at.desc())
    )
    trades = result.scalars().all()
    return {
        "status": "success",
        "data": {
            "count": len(trades),
            "positions": [_trade_to_dict(t) for t in trades],
        },
    }


# ─────────────────────────────────────────────
# GET /api/trading/history
# ─────────────────────────────────────────────

@router.get("/history")
async def get_trade_history(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    symbol: str | None = Query(None, description="Filter by symbol, e.g. BTCUSDT"),
    from_date: datetime | None = Query(None, description="Start date (ISO 8601)"),
    to_date: datetime | None = Query(None, description="End date (ISO 8601)"),
    outcome: str | None = Query(None, description="profit | loss"),
    trading_account_id: str | None = Query(None),
    exchange: str | None = Query(None),
    is_paper: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return closed trade history with optional filters."""
    filters = [Trade.user_id == current_user.id, Trade.status == "closed"]

    if symbol:
        filters.append(Trade.symbol == symbol.upper())
    if from_date:
        filters.append(Trade.closed_at >= from_date)
    if to_date:
        filters.append(Trade.closed_at <= to_date)
    if outcome == "profit":
        filters.append(Trade.profit.isnot(None))
    elif outcome == "loss":
        filters.append(Trade.loss.isnot(None))
    if trading_account_id:
        filters.append(Trade.trading_account_id == trading_account_id)
    if exchange:
        filters.append(Trade.exchange == exchange.lower())
    if is_paper is not None:
        filters.append(Trade.is_paper == is_paper)

    result = await db.execute(
        select(Trade)
        .where(and_(*filters))
        .order_by(Trade.closed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    trades = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).where(and_(*filters))
    )
    total = count_result.scalar() or 0

    return {
        "status": "success",
        "data": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "trades": [_trade_to_dict(t) for t in trades],
        },
    }


# ─────────────────────────────────────────────
# GET /api/trading/performance
# ─────────────────────────────────────────────

@router.get("/performance")
async def get_performance(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    symbol: str | None = Query(None),
    market_condition: str | None = Query(None),
    trading_account_id: str | None = Query(None),
    exchange: str | None = Query(None),
    is_paper: bool | None = Query(None),
):
    """Return aggregated performance statistics.

    Optional filters: symbol, market_condition (uptrend / downtrend / consolidating).
    """
    base_filter = [
        Trade.user_id == current_user.id,
        Trade.status == "closed",
    ]
    if symbol:
        base_filter.append(Trade.symbol == symbol.upper())
    if market_condition:
        base_filter.append(Trade.market_condition == market_condition)
    if trading_account_id:
        base_filter.append(Trade.trading_account_id == trading_account_id)
    if exchange:
        base_filter.append(Trade.exchange == exchange.lower())
    if is_paper is not None:
        base_filter.append(Trade.is_paper == is_paper)

    result = await db.execute(select(Trade).where(and_(*base_filter)))
    trades = result.scalars().all()

    if not trades:
        return {"status": "success", "data": {"message": "No closed trades yet"}}

    wins = [t for t in trades if (t.profit or 0) > 0]
    losses = [t for t in trades if (t.loss or 0) > 0]

    total_profit = sum(t.profit or 0 for t in wins)
    total_loss = sum(t.loss or 0 for t in losses)
    net_pnl = total_profit - total_loss
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    avg_profit_pct = (
        sum(t.profit_percent or 0 for t in wins) / len(wins) if wins else 0
    )
    avg_loss_pct = (
        sum(t.profit_percent or 0 for t in losses) / len(losses) if losses else 0
    )

    # Best and worst trades
    best = max(trades, key=lambda t: t.profit or 0)
    worst = min(trades, key=lambda t: -(t.loss or 0))

    return {
        "status": "success",
        "data": {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 1),
            "total_profit_usd": round(total_profit, 2),
            "total_loss_usd": round(total_loss, 2),
            "net_pnl_usd": round(net_pnl, 2),
            "avg_profit_pct": round(avg_profit_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "best_trade": _trade_to_dict(best),
            "worst_trade": _trade_to_dict(worst),
        },
    }


# ─────────────────────────────────────────────
# POST /api/trading/close-position
# ─────────────────────────────────────────────

@router.post("/close-position")
async def close_position(
    body: ClosePositionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually close an open position at current market price.

    Fetches the live price, cancels pending stop/target orders, records P&L.
    """
    # Verify trade belongs to this user
    result = await db.execute(
        select(Trade).where(
            Trade.id == body.trade_id,
            Trade.user_id == current_user.id,
            Trade.status == "open",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Open trade not found",
        )

    agent = TradingAgent(current_user.id)
    result = await agent.close_position(body.trade_id)
    return {"status": "success", "data": result}


@router.post("/undo/{token}")
async def undo_trade(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Undo a recently executed trade using a short-lived token."""
    token_result = await db.execute(
        select(TradeUndoToken).where(TradeUndoToken.token == token)
    )
    undo_token = token_result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if not undo_token or undo_token.used_at is not None or undo_token.expires_at <= now:
        raise HTTPException(status_code=410, detail="Undo window has expired")
    undo_token.attempts_count = int(undo_token.attempts_count or 0) + 1
    if undo_token.attempts_count > 3:
        raise HTTPException(status_code=429, detail="Too many undo attempts for this trade")

    trade_result = await db.execute(
        select(Trade).where(
            Trade.id == undo_token.trade_id,
            Trade.user_id == undo_token.user_id,
        )
    )
    trade = trade_result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.status != "open":
        return {"success": False, "message": "Position already closed — cannot undo"}

    agent = TradingAgent(undo_token.user_id)
    result = await agent.close_position(undo_token.trade_id)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("reason", "Undo failed"))

    undo_token.used_at = now
    trade.status = "cancelled_by_user"
    linked_notifications = await db.execute(
        select(ApexNotification).where(
            ApexNotification.user_id == undo_token.user_id,
            ApexNotification.undo_token == token,
        )
    )
    for notification in linked_notifications.scalars().all():
        notification.actioned_at = now
        notification.action_taken = "undone"
    db.add(
        AuditLog(
            user_id=undo_token.user_id,
            event_type="trade_undone_via_notification",
            event_details={"trade_id": undo_token.trade_id, "token": token},
        )
    )
    notification_engine = get_unitrader_notification_engine()
    if notification_engine:
        from src.services.user_ai_name import get_user_ai_name

        _ai = await get_user_ai_name(undo_token.user_id, db)
        await notification_engine._dispatch(  # type: ignore[attr-defined]
            user_id=undo_token.user_id,
            notification_type="trade_undo_confirmed",
            title=f"Done — {_ai} reversed {trade.symbol}",
            body=(
                f"Done — {_ai}'s trade on {trade.symbol} has been reversed. "
                "No further action needed."
            ),
            channel_message=(
                f"Done — {_ai}'s trade on {trade.symbol} has been reversed.\n"
                "No further action needed.\n\n"
                "⚠️ Not financial advice. Capital at risk."
            ),
            data={"trade_id": undo_token.trade_id, "symbol": trade.symbol},
            trade_id=undo_token.trade_id,
            db=db,
        )
    await db.flush()
    return {"success": True, "message": "Trade reversed successfully"}


# ─────────────────────────────────────────────
# GET /api/trading/risk-analysis
# ─────────────────────────────────────────────

@router.get("/risk-analysis")
async def get_risk_analysis(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current daily loss, remaining budget, and loss limit status.

    Useful for the frontend dashboard to show risk indicators in real-time.
    """
    loss_status = await enforce_loss_limits(current_user.id)

    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    user_settings = settings_result.scalar_one_or_none()
    max_daily_pct = user_settings.max_daily_loss if user_settings else 5.0

    balance = loss_status["balance"]
    daily_loss = loss_status["daily_loss_usd"]
    max_daily_usd = balance * (max_daily_pct / 100)
    remaining = max(max_daily_usd - daily_loss, 0)
    used_pct = (daily_loss / max_daily_usd * 100) if max_daily_usd > 0 else 0

    alert = used_pct >= 80

    return {
        "status": "success",
        "data": {
            "balance_usd": round(balance, 2),
            "daily_loss_usd": round(daily_loss, 2),
            "daily_loss_pct": round(used_pct, 1),
            "max_daily_loss_usd": round(max_daily_usd, 2),
            "remaining_budget_usd": round(remaining, 2),
            "weekly_loss_usd": round(loss_status["weekly_loss_usd"], 2),
            "monthly_loss_usd": round(loss_status["monthly_loss_usd"], 2),
            "limit_action": loss_status["action"],
            "alert": alert,
            "alert_message": "Approaching daily loss limit!" if alert else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


# ─────────────────────────────────────────────
# GET /api/trading/ohlcv
# ─────────────────────────────────────────────

@router.get("/ohlcv")
async def get_ohlcv(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    symbol: str = Query(..., description="Symbol, e.g. AAPL"),
    days: int = Query(30, ge=1, le=365),
    interval: str = Query("1day", description="Only '1day' supported"),
):
    """Fetch daily OHLCV bars for charts.

    Calls Alpaca:
      GET /v2/stocks/{symbol}/bars?timeframe=1Day&limit={days}
    """
    if interval.lower() != "1day":
        raise HTTPException(status_code=400, detail="Only interval=1day supported")

    sym = symbol.strip().upper()
    if "/" in sym or "_" in sym:
        raise HTTPException(status_code=400, detail="Only stock symbols supported for ohlcv")

    key_res = await db.execute(
        select(ExchangeAPIKey).where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.exchange == "alpaca",
            ExchangeAPIKey.is_active == True,  # noqa: E712
        )
    )
    key_row = key_res.scalars().first()
    if not key_row:
        raise HTTPException(status_code=404, detail="No active alpaca connection found")

    try:
        raw_key, raw_secret = decrypt_api_key(
            key_row.encrypted_api_key, key_row.encrypted_api_secret
        )
        headers = {
            "APCA-API-KEY-ID": raw_key,
            "APCA-API-SECRET-KEY": raw_secret,
        }
        base = (settings.alpaca_data_url or "https://data.alpaca.markets").rstrip("/")
        url = f"{base}/v2/stocks/{sym}/bars"
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            await alpaca_limiter.acquire()
            resp = await client.get(url, params={"timeframe": "1Day", "limit": days})
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        status_code = getattr(exc.response, "status_code", 500)
        logger.error("OHLCV fetch failed for %s: %s", sym, exc)
        raise HTTPException(status_code=status_code, detail="ohlcv_fetch_failed")
    except Exception as exc:
        logger.error("OHLCV fetch failed for %s: %s", sym, exc)
        raise HTTPException(status_code=500, detail="ohlcv_fetch_failed")

    bars = (payload.get("bars") or []) if isinstance(payload, dict) else []
    out = []
    for b in bars:
        t = b.get("t")
        day = t[:10] if isinstance(t, str) and len(t) >= 10 else ""
        out.append(
            {
                "time": day,
                "open": float(b.get("o", 0) or 0),
                "high": float(b.get("h", 0) or 0),
                "low": float(b.get("l", 0) or 0),
                "close": float(b.get("c", 0) or 0),
                "volume": float(b.get("v", 0) or 0),
            }
        )

    return {"status": "success", "data": out}


# ─────────────────────────────────────────────
# GET /api/trading/simulate-history
# ─────────────────────────────────────────────

@router.get("/simulate-history")
async def simulate_history(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    amount: float = Query(1000.0, gt=0, description="Total USD to simulate investing"),
    days: int = Query(30, ge=1, le=365, description="Number of calendar days of history"),
    symbols: str = Query(..., description="Comma-separated symbols e.g. AAPL,MSFT,SPY"),
):
    """Simulate historical portfolio performance for a set of symbols.

    Distributes ``amount`` equally across ``symbols`` and calculates
    what the portfolio value would have been over the past ``days`` days,
    using daily closing prices from Alpaca.

    Prefers the user's stored Alpaca keys; falls back to server-level keys.
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="At least one symbol required")
    if len(symbol_list) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 symbols per request")

    # Resolve Alpaca credentials: user keys > system keys
    api_key: str | None = None
    api_secret: str | None = None

    key_res = await db.execute(
        select(ExchangeAPIKey).where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.exchange == "alpaca",
            ExchangeAPIKey.is_active == True,  # noqa: E712
        )
    )
    key_row = key_res.scalars().first()
    if key_row:
        api_key, api_secret = decrypt_api_key(
            key_row.encrypted_api_key, key_row.encrypted_api_secret
        )
    elif settings.alpaca_api_key and settings.alpaca_api_secret:
        api_key, api_secret = settings.alpaca_api_key, settings.alpaca_api_secret

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Alpaca connection found. Connect your Alpaca account first.",
        )

    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    base = (settings.alpaca_data_url or "https://data.alpaca.markets").rstrip("/")
    allocation_per_symbol = amount / len(symbol_list)
    # Fetch one extra bar as the "purchase day" baseline
    limit = days + 1

    per_symbol: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        for sym in symbol_list:
            try:
                await alpaca_limiter.acquire()
                resp = await client.get(
                    f"{base}/v2/stocks/{sym}/bars",
                    params={"timeframe": "1Day", "limit": limit},
                )
                resp.raise_for_status()
                bars: list[dict] = resp.json().get("bars") or []
            except Exception as exc:
                logger.warning("simulate-history: skipping %s — %s", sym, exc)
                continue

            if len(bars) < 2:
                logger.warning("simulate-history: not enough bars for %s", sym)
                continue

            bars.sort(key=lambda b: b.get("t", ""))
            buy_price = float(bars[0].get("c") or 0)
            if buy_price <= 0:
                continue

            dates = [b["t"][:10] for b in bars[1:]]
            values = [
                round(allocation_per_symbol / buy_price * float(b.get("c") or 0), 2)
                for b in bars[1:]
            ]
            per_symbol[sym] = {
                "dates": dates,
                "values": values,
                "buy_price": buy_price,
            }

    if not per_symbol:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="market_data_unavailable",
        )

    # Merge all dates from all symbols and sort
    all_dates: list[str] = sorted(
        {d for data in per_symbol.values() for d in data["dates"]}
    )

    # For each date, sum values across symbols (carry last known value for gaps)
    last_known: dict[str, float] = {sym: allocation_per_symbol for sym in per_symbol}
    portfolio_values: list[float] = []
    for date in all_dates:
        day_total = 0.0
        for sym, data in per_symbol.items():
            if date in data["dates"]:
                idx = data["dates"].index(date)
                last_known[sym] = data["values"][idx]
            day_total += last_known[sym]
        portfolio_values.append(round(day_total, 2))

    initial_value = round(amount, 2)
    final_value = portfolio_values[-1] if portfolio_values else initial_value
    total_return_pct = (
        round((final_value - initial_value) / initial_value * 100, 2)
        if initial_value > 0
        else 0.0
    )

    per_symbol_summary = {
        sym: {
            "initial_allocation": round(allocation_per_symbol, 2),
            "final_value": data["values"][-1] if data["values"] else round(allocation_per_symbol, 2),
            "return_pct": round(
                (data["values"][-1] - allocation_per_symbol) / allocation_per_symbol * 100, 2
            ) if data["values"] and allocation_per_symbol > 0 else 0.0,
        }
        for sym, data in per_symbol.items()
    }

    return {
        "status": "success",
        "data": {
            "dates": all_dates,
            "portfolio_values": portfolio_values,
            "per_symbol": per_symbol_summary,
            "initial_value": initial_value,
            "final_value": final_value,
            "total_return_pct": total_return_pct,
        },
    }


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def _trade_to_dict(trade: Trade) -> dict:
    trading_account = getattr(trade, "trading_account", None)
    raw_reason = (getattr(trade, "reasoning", None) or "").strip()
    reasoning_snippet: str | None
    if not raw_reason:
        reasoning_snippet = None
    elif len(raw_reason) <= 200:
        reasoning_snippet = raw_reason
    else:
        reasoning_snippet = raw_reason[:200] + "…"
    return {
        "id": trade.id,
        "trading_account_id": trade.trading_account_id,
        "exchange": trade.exchange,
        "is_paper": trade.is_paper,
        "account_scope": trade.account_scope,
        "account_label": trading_account.account_label if trading_account else None,
        "symbol": trade.symbol,
        "side": trade.side,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "profit": trade.profit,
        "loss": trade.loss,
        "profit_percent": trade.profit_percent,
        "status": trade.status,
        "claude_confidence": trade.claude_confidence,
        "market_condition": trade.market_condition,
        "execution_time_ms": trade.execution_time,
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
        "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
        "reasoning": reasoning_snippet,
    }


# ─────────────────────────────────────────────
# GET /api/performance/summary
# ─────────────────────────────────────────────

@performance_router.get("/summary")
async def performance_summary(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    trading_account_id: str | None = Query(None),
    exchange: str | None = Query(None),
    is_paper: bool | None = Query(None),
):
    """Trader-class-aware performance summary.

    Always includes:
      total_return_gbp, total_return_pct, win_rate, total_trades, paper_trades,
      best_trade, worst_trade, monthly_summary
    Additional fields are gated by trader_class.
    """
    ctx = await SharedMemory.load(current_user.id, db)
    trader_class = getattr(ctx, "trader_class", "complete_novice") or "complete_novice"

    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Trade).where(
            Trade.user_id == current_user.id,
            Trade.status == "closed",
            Trade.closed_at.isnot(None),
            Trade.closed_at >= since,
            *((
                (Trade.trading_account_id == trading_account_id,)
                if trading_account_id
                else ()
            )),
            *((
                (Trade.exchange == exchange.lower(),)
                if exchange
                else ()
            )),
            *((
                (Trade.is_paper == is_paper,)
                if is_paper is not None
                else ()
            )),
        )
    )
    trades = result.scalars().all()

    def trade_pnl(t: Trade) -> float:
        return float((t.profit or 0) - (t.loss or 0))

    total_return_gbp = sum(trade_pnl(t) for t in trades)
    total_trades = len(trades)
    wins = [t for t in trades if trade_pnl(t) > 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0

    # Use average entry value as a rough capital base proxy for return %
    base_cap = 0.0
    if trades:
        base_cap = sum(float(t.entry_price or 0) * float(t.quantity or 0) for t in trades) / max(
            1, len(trades)
        )
    total_return_pct = (total_return_gbp / base_cap * 100) if base_cap > 0 else 0.0

    best_trade = _trade_to_dict(max(trades, key=trade_pnl)) if trades else None
    worst_trade = _trade_to_dict(min(trades, key=trade_pnl)) if trades else None

    # Monthly summary: YYYY-MM -> pnl
    monthly_summary: dict[str, float] = {}
    for t in trades:
        if not t.closed_at:
            continue
        k = t.closed_at.strftime("%Y-%m")
        monthly_summary[k] = monthly_summary.get(k, 0.0) + trade_pnl(t)

    # Paper trades not currently recorded per trade in DB schema.
    paper_trades = 0

    payload: dict = {
        # NOTE: Trades are tracked in USD; keep legacy *_gbp fields for backward compatibility.
        "total_return_usd": round(total_return_gbp, 2),
        "total_return_gbp": round(total_return_gbp, 2),
        "total_return_pct": round(total_return_pct, 2),
        "win_rate": round(win_rate, 1),
        "total_trades": total_trades,
        "paper_trades": paper_trades,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "monthly_summary": monthly_summary,
    }

    # ── complete_novice / curious_saver ────────────────────────────────────
    if trader_class in {"complete_novice", "curious_saver"}:
        try:
            goal_agent = GoalTrackingAgent()
            report = await goal_agent.generate_progress_report(current_user.id, db)
            goal_progress_message = report.get("message")
        except Exception:
            goal_progress_message = None

        # Trust ladder summary derived from SharedContext; paper_trades_count unavailable in DB.
        stage = int(getattr(ctx, "trust_ladder_stage", 1) or 1)
        payload["goal_progress_message"] = goal_progress_message or "Keep going — Unitrader is tracking your progress."
        payload["trust_ladder_summary"] = {
            "stage": stage,
            "days_until_advance": 0,
            "paper_trades_count": 0,
        }

        # One warm sentence from Claude API (best-effort, falls back if not configured)
        encouragement = None
        try:
            if settings.anthropic_api_key:
                from anthropic import Anthropic
                import asyncio as _asyncio

                client = Anthropic()
                prompt = (
                    "Write exactly one warm, encouraging sentence for a beginner investor. "
                    "No numbers, no jargon."
                )
                resp = await _asyncio.to_thread(
                    lambda: client.messages.create(
                        model=settings.anthropic_model,
                        max_tokens=60,
                        messages=[{"role": "user", "content": prompt}],
                    )
                )
                encouragement = resp.content[0].text.strip()
        except Exception:
            encouragement = None
        payload["encouragement"] = encouragement or "You’re doing the right thing by learning step by step."

        # Omit technical metrics implicitly by not adding them.

    # ── self_taught ─────────────────────────────────────────────────────────
    if trader_class == "self_taught":
        # Benchmarks not available from DB-only data; return best-effort placeholders.
        avg_hold_time_days = None
        if trades:
            holds = []
            for t in trades:
                if t.created_at and t.closed_at:
                    holds.append((t.closed_at - t.created_at).total_seconds() / 86400)
            avg_hold_time_days = sum(holds) / len(holds) if holds else None
        payload.update(
            {
                "vs_buy_hold": 0.0,
                "vs_spy": 0.0,
                "avg_hold_time_days": round(avg_hold_time_days, 2) if avg_hold_time_days is not None else 0.0,
            }
        )

    # ── experienced / semi_institutional ────────────────────────────────────
    if trader_class in {"experienced", "semi_institutional"}:
        pnls = [trade_pnl(t) for t in trades]
        mean = (sum(pnls) / len(pnls)) if pnls else 0.0
        var = (sum((x - mean) ** 2 for x in pnls) / len(pnls)) if pnls else 0.0
        stddev = var ** 0.5
        sharpe = (mean / stddev * (252 ** 0.5)) if stddev > 0 else 0.0

        # Max drawdown from cumulative pnl
        peak = 0.0
        dd = 0.0
        cum = 0.0
        for x in pnls:
            cum += x
            peak = max(peak, cum)
            dd = min(dd, cum - peak)
        max_drawdown = (dd / peak * 100) if peak > 0 else float(dd)

        calmar = (total_return_pct / abs(max_drawdown)) if max_drawdown else 0.0

        # Avg hold time (days)
        holds = []
        for t in trades:
            if t.created_at and t.closed_at:
                holds.append((t.closed_at - t.created_at).total_seconds() / 86400)
        avg_hold_time_days = sum(holds) / len(holds) if holds else 0.0

        # Sector PnL not available (sector not stored on Trade). Return empty dict.
        sector_pnl: dict[str, float] = {}

        # Win rate by asset class (symbol classification)
        by_class: dict[str, list[Trade]] = {"stocks": [], "crypto": [], "forex": []}
        for t in trades:
            try:
                ac = classify_asset(t.symbol)
            except Exception:
                ac = "stock"
            key = "stocks" if ac == "stock" else ac
            if key in by_class:
                by_class[key].append(t)
        win_rate_by_asset_class: dict[str, float] = {}
        for k, ts in by_class.items():
            if not ts:
                win_rate_by_asset_class[k] = 0.0
            else:
                w = len([t for t in ts if trade_pnl(t) > 0])
                win_rate_by_asset_class[k] = round(w / len(ts) * 100, 1)

        payload.update(
            {
                "sharpe_ratio": round(sharpe, 3),
                "max_drawdown": round(float(max_drawdown), 3),
                "calmar_ratio": round(float(calmar), 3),
                "beta": 0.0,
                "alpha": 0.0,
                "avg_hold_time_days": round(float(avg_hold_time_days), 2),
                "sector_pnl": sector_pnl,
                "win_rate_by_asset_class": win_rate_by_asset_class,
            }
        )

    # ── crypto_native ───────────────────────────────────────────────────────
    if trader_class == "crypto_native":
        crypto_trades = [t for t in trades if classify_asset(t.symbol) == "crypto"] if trades else []
        best = None
        worst = None
        if crypto_trades:
            best_t = max(crypto_trades, key=lambda t: float(t.profit_percent or -1e9))
            worst_t = min(crypto_trades, key=lambda t: float(t.profit_percent or 1e9))
            best = {
                "symbol": best_t.symbol,
                "pct_gain": float(best_t.profit_percent or 0),
                "pnl_usd": round(trade_pnl(best_t), 2),
                "pnl_gbp": round(trade_pnl(best_t), 2),  # legacy alias
            }
            worst = {
                "symbol": worst_t.symbol,
                "pct_loss": float(worst_t.profit_percent or 0),
                "pnl_usd": round(trade_pnl(worst_t), 2),
                "pnl_gbp": round(trade_pnl(worst_t), 2),  # legacy alias
            }
        payload.update(
            {
                "vs_bitcoin_hold": 0.0,
                "best_crypto": best,
                "worst_crypto": worst,
                "total_fees_paid": 0.0,
            }
        )

    return {"status": "success", "data": payload}


@performance_router.get("/feedback-stats")
async def feedback_stats(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    counts = await db.execute(
        select(
            func.count(TradeFeedback.id),
            func.sum(case((TradeFeedback.rating == 1, 1), else_=0)),
        ).where(TradeFeedback.user_id == current_user.id)
    )
    total_count, positive_count = counts.one()
    total = int(total_count or 0)
    positive = int(positive_count or 0)
    positive_pct = float(round((positive / total) * 100, 1)) if total > 0 else 0.0

    comments_res = await db.execute(
        select(TradeFeedback.comment)
        .where(
            TradeFeedback.user_id == current_user.id,
            TradeFeedback.comment.isnot(None),
            TradeFeedback.comment != "",
        )
        .order_by(TradeFeedback.created_at.desc())
        .limit(3)
    )
    recent_comments = [r[0] for r in comments_res.all() if r[0]]

    settings_row = await db.execute(
        select(UserSettings.trust_score).where(UserSettings.user_id == current_user.id)
    )
    trust = settings_row.scalar_one_or_none()
    trust_score = int(trust) if trust is not None else (100 if total == 0 else int(round((positive / total) * 100)))

    return {
        "positive_pct": positive_pct,
        "total_rated": total,
        "trust_score": trust_score,
        "recent_comments": recent_comments,
    }


@performance_router.get("/share-card")
async def share_card(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=7, le=365),
):
    """Phase 30: data for shareable performance card."""
    ctx = await SharedMemory.load(current_user.id, db)
    trader_class = getattr(ctx, "trader_class", "complete_novice") or "complete_novice"

    # Reuse performance summary logic by querying the same closed-trades window.
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Trade).where(
            Trade.user_id == current_user.id,
            Trade.status == "closed",
            Trade.closed_at.isnot(None),
            Trade.closed_at >= since,
        )
    )
    trades = result.scalars().all()

    def trade_pnl(t: Trade) -> float:
        return float((t.profit or 0) - (t.loss or 0))

    total_return_gbp = sum(trade_pnl(t) for t in trades)
    total_trades = len(trades)
    wins = len([t for t in trades if trade_pnl(t) > 0])
    win_rate = (wins / total_trades * 100) if total_trades else 0.0

    base_cap = 0.0
    if trades:
        base_cap = sum(float(t.entry_price or 0) * float(t.quantity or 0) for t in trades) / max(
            1, len(trades)
        )
    total_return_pct = (total_return_gbp / base_cap * 100) if base_cap > 0 else 0.0

    # Optional pro metrics (best-effort, consistent with /summary placeholders)
    sharpe = 0.0
    max_drawdown = 0.0
    if trades:
        # crude daily returns proxy: per-trade % spread over holding time
        rets = []
        for t in trades:
            if t.profit_percent is None:
                continue
            rets.append(float(t.profit_percent) / 100.0)
        if len(rets) >= 2:
            import statistics

            mu = statistics.mean(rets)
            sd = statistics.pstdev(rets) or 1e-9
            sharpe = (mu / sd) * (252 ** 0.5)
        # drawdown is already computed in /summary for pro; keep placeholder here
        max_drawdown = 0.0

    # Benchmarks (placeholders unless already available)
    vs_index = 0.0
    vs_hold = 0.0
    if trader_class == "self_taught":
        # Match /summary placeholders
        vs_hold = 0.0
    if trader_class == "curious_saver":
        vs_index = 0.0

    # Days since started (use user.created_at)
    days_since_started = 0
    ures = await db.execute(select(User.created_at).where(User.id == current_user.id))
    created_at = ures.scalar_one_or_none()
    if created_at:
        try:
            days_since_started = max(0, int((datetime.now(timezone.utc) - created_at).total_seconds() // 86400))
        except Exception:
            days_since_started = 0

    CLASS_SHARE_TEXT = {
        "complete_novice": "Unitrader grew my savings by {pct}% last month - and I only started {days} days ago!",
        "curious_saver": "My AI trader just outperformed my index fund by {vs_index}% last month",
        "self_taught": "Unitrader's AI strategy beat buy-and-hold by {vs_hold}% - worth trying",
        "experienced": "Unitrader hit {win_rate}% win rate with {sharpe:.1f} Sharpe last month",
        "semi_institutional": "Unitrader: {win_rate}% win rate, {sharpe:.1f} Sharpe, {drawdown}% max drawdown",
        "crypto_native": "Unitrader turned my crypto portfolio +{pct}% last month. AI trading works.",
    }
    tmpl = CLASS_SHARE_TEXT.get(trader_class, CLASS_SHARE_TEXT["complete_novice"])

    share_text = tmpl.format(
        pct=round(float(total_return_pct), 1),
        days=days_since_started,
        vs_index=round(float(vs_index), 1),
        vs_hold=round(float(vs_hold), 1),
        win_rate=round(float(win_rate), 1),
        sharpe=float(sharpe),
        drawdown=round(float(max_drawdown), 1),
    )

    referral_url = f"{(settings.frontend_url or 'http://localhost:3000').rstrip('/')}/register?ref={current_user.id}"
    disclaimer = (
        "Past performance does not guarantee future results. "
        "Returns shown are based on historical trades and may not reflect fees, slippage, or future conditions."
    )

    return {
        "status": "success",
        "data": {
            "share_text": share_text,
            "referral_url": referral_url,
            "disclaimer": disclaimer,
        },
    }


# ─────────────────────────────────────────────
# GET /api/trades/export  (Phase 27 - tax export)
# ─────────────────────────────────────────────

@trades_router.get("/export")
async def export_trades_csv(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    days: int = Query(365, ge=1, le=3650),
):
    """Export closed trades as a CSV for tax/accounting.

    Adds column: Account Type (human readable trader_class) after existing columns.
    """
    ctx = await SharedMemory.load(current_user.id, db)
    trader_class = getattr(ctx, "trader_class", "complete_novice") or "complete_novice"
    account_type = _human_account_type(trader_class)

    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Trade).where(
            Trade.user_id == current_user.id,
            Trade.status == "closed",
            Trade.closed_at.isnot(None),
            Trade.closed_at >= since,
        ).order_by(Trade.closed_at.asc())
    )
    trades = result.scalars().all()

    # Existing columns (stable): Date, Symbol, Side, Qty, Entry, Exit, PnL_USD, PnL_Pct
    headers = [
        "Date",
        "Symbol",
        "Side",
        "Quantity",
        "Entry Price",
        "Exit Price",
        "PnL (USD)",
        "PnL (%)",
        "Account Type",
    ]

    def _iter_rows():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(headers)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for t in trades:
            pnl = float((t.profit or 0) - (t.loss or 0))
            w.writerow(
                [
                    t.closed_at.date().isoformat() if t.closed_at else "",
                    t.symbol,
                    t.side,
                    t.quantity,
                    t.entry_price,
                    t.exit_price or "",
                    round(pnl, 2),
                    round(float(t.profit_percent or 0), 4) if t.profit_percent is not None else "",
                    account_type,
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = f"unitrader-trades-{current_user.id}-{datetime.now(timezone.utc).date().isoformat()}.csv"
    return StreamingResponse(
        _iter_rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@trades_router.post("/{trade_id}/feedback")
async def submit_trade_feedback(
    trade_id: str = Path(...),
    body: TradeFeedbackRequest = ...,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate live trade ownership if needed
    live_trade_id: str | None = None
    paper_trade_id: str | None = None

    if body.is_paper:
        paper_trade_id = str(trade_id)
    else:
        live_trade_id = str(trade_id)
        res = await db.execute(
            select(Trade).where(Trade.id == live_trade_id, Trade.user_id == current_user.id)
        )
        t = res.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="trade_not_found")

    fb = TradeFeedback(
        user_id=current_user.id,
        trade_id=live_trade_id,
        paper_trade_id=paper_trade_id,
        rating=int(body.rating),
        comment=(body.comment or None),
    )
    db.add(fb)

    # Recalculate trust_score = round(positive/total*100)
    counts = await db.execute(
        select(
            func.count(TradeFeedback.id),
            func.sum(case((TradeFeedback.rating == 1, 1), else_=0)),
        ).where(TradeFeedback.user_id == current_user.id)
    )
    total_count, positive_count = counts.one()
    total = int(total_count or 0)
    positive = int(positive_count or 0)
    trust_score = int(round((positive / total) * 100)) if total > 0 else 100

    settings_row = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    settings = settings_row.scalar_one_or_none()
    if not settings:
        settings = UserSettings(user_id=current_user.id)
        db.add(settings)

    settings.trust_score = trust_score

    audit_log = AuditLog(
        user_id=current_user.id,
        event_type="trade_feedback",
        event_details={
            "rating": int(body.rating),
            "comment_length": len(body.comment or ""),
            "trade_id": str(trade_id),
        },
    )
    db.add(audit_log)

    await db.commit()

    # Ensure agents see updated trust_score quickly
    SharedMemory.invalidate(current_user.id)

    return {"success": True, "new_trust_score": trust_score}
