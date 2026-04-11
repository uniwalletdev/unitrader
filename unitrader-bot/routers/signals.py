"""
routers/signals.py — Signal Stack API and Apex Selects approval handlers.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import (
    ApexNotification,
    ApexSelectsApprovalToken,
    SignalScanRun,
    SignalStack,
    TradingAccount,
    User,
    UserSettings,
)
from routers.auth import get_current_user
from schemas import UserSettingsResponse
from src.agents.orchestrator import get_orchestrator
from src.agents.shared_memory import SharedMemory
from src.agents.signal_stack_agent import signal_stack_agent
from src.integrations.market_data import classify_asset
from src.market_context import resolve_market_context
from src.services.unitrader_notifications import get_unitrader_notification_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signals", tags=["Signals"])


class SignalInteractionRequest(BaseModel):
    action: str
    trade_id: str | None = None


class UpdateSignalSettingsRequest(BaseModel):
    signal_stack_mode: str | None = None
    # NOTE: Full Auto settings are per trading_account_id (see /account-settings).
    apex_selects_threshold: int | None = None
    apex_selects_max_trades: int | None = None
    apex_selects_asset_classes: list[str] | None = None
    morning_briefing_enabled: bool | None = None
    morning_briefing_time: str | None = None


class TradingAccountSettingsResponse(BaseModel):
    trading_account_id: str
    exchange: str
    is_paper: bool
    account_label: str
    watchlist: list[str] = []
    auto_trade_enabled: bool = False
    auto_trade_threshold: int = 80
    auto_trade_max_per_scan: int = 1


class UpdateTradingAccountSettingsRequest(BaseModel):
    trading_account_id: str
    watchlist: list[str] | None = None
    auto_trade_enabled: bool | None = None
    auto_trade_threshold: int | None = None
    auto_trade_max_per_scan: int | None = None


def _to_float(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _serialize_signal(signal: SignalStack) -> dict:
    return {
        "id": str(signal.id),
        "symbol": signal.symbol,
        "asset_name": signal.asset_name,
        "asset_class": signal.asset_class,
        "exchange": signal.exchange,
        "signal": signal.signal,
        "confidence": signal.confidence,
        "reasoning": signal.reasoning_simple or signal.reasoning_expert or "",
        "reasoning_expert": signal.reasoning_expert or "",
        "reasoning_simple": signal.reasoning_simple or "",
        "reasoning_metaphor": signal.reasoning_metaphor or "",
        "rsi": _to_float(signal.rsi),
        "macd_signal": signal.macd_signal,
        "volume_ratio": _to_float(signal.volume_ratio),
        "sentiment_score": signal.sentiment_score,
        "current_price": _to_float(signal.current_price) or 0,
        "price_change_24h": _to_float(signal.price_change_24h) or 0,
        "community_pct": (
            round((signal.community_accepted / signal.community_total) * 100, 1)
            if signal.community_total and signal.community_total >= 10
            else None
        ),
        "community_total": signal.community_total or 0,
        "expires_at": signal.expires_at.isoformat() if signal.expires_at else None,
    }


def _personalize_signal_with_ai_name(serialized: dict, ai_name: str) -> dict:
    """Replace 'Apex' placeholder with user's custom AI name in signal reasoning."""
    if ai_name and ai_name.lower() != "apex":
        # Replace Apex in all reasoning fields
        for field in ["reasoning_simple", "reasoning_expert", "reasoning_metaphor", "reasoning"]:
            if serialized.get(field):
                # Replace "Apex" with AI name (case-sensitive for proper nouns)
                serialized[field] = serialized[field].replace("Apex", ai_name)
                # Also handle variations like "Apex will", "Apex's"
                serialized[field] = serialized[field].replace(f"{ai_name} will", f"{ai_name} will")
    return serialized


def _exchange_for_signal(symbol: str, asset_class: str) -> str:
    if asset_class == "crypto":
        return "coinbase"
    if asset_class == "forex":
        return "oanda"
    return "alpaca"


@router.get("/stack")
async def get_signal_stack(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    trading_account_id: str | None = Query(default=None),
):
    if trading_account_id is None:
        settings_result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        settings = settings_result.scalar_one_or_none()
        trading_account_id = getattr(settings, "preferred_trading_account_id", None) if settings else None
    if trading_account_id is None:
        return {
            "status": "success",
            "data": {
                "signals": [],
                "reason": "no_account",
                "last_scan_at": None,
                "next_scan_in_minutes": 30,
                "assets_scanned": 0,
            },
        }

    market_ctx = await resolve_market_context(
        db=db, user_id=current_user.id, trading_account_id=trading_account_id
    )
    now = datetime.now(timezone.utc)
    signals_result = await db.execute(
        select(SignalStack)
        .where(SignalStack.expires_at > now)
        .where(SignalStack.exchange == market_ctx.exchange.value)
        .order_by(SignalStack.confidence.desc(), SignalStack.created_at.desc())
    )
    signals = signals_result.scalars().all()

    run_result = await db.execute(
        select(SignalScanRun).order_by(SignalScanRun.created_at.desc()).limit(1)
    )
    last_run = run_result.scalar_one_or_none()

    # Get user's AI name for personalization
    user_result = await db.execute(
        select(User).where(User.id == current_user.id)
    )
    user = user_result.scalar_one()
    ai_name = user.ai_name or "Apex"

    return {
        "status": "success",
        "data": {
            "signals": [
                _personalize_signal_with_ai_name(_serialize_signal(signal), ai_name)
                for signal in signals
            ],
            "last_scan_at": last_run.created_at.isoformat() if last_run else None,
            "next_scan_in_minutes": 30,
            "assets_scanned": last_run.assets_scanned if last_run else 0,
        },
    }


@router.post("/{signal_id}/interact")
async def interact_with_signal(
    body: SignalInteractionRequest,
    signal_id: str = Path(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.action not in {"accepted", "skipped", "traded"}:
        raise HTTPException(status_code=400, detail="Invalid signal action")

    await signal_stack_agent.record_interaction(
        signal_id=signal_id,
        user_id=current_user.id,
        action=body.action,
        trade_id=body.trade_id,
        db=db,
    )
    return {"status": "success"}


@router.patch("/settings", response_model=UserSettingsResponse)
async def update_signal_settings(
    body: UpdateSignalSettingsRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        settings = UserSettings(user_id=current_user.id)
        db.add(settings)

    for field, value in body.model_dump(exclude_unset=True).items():
        if hasattr(settings, field):
            setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)
    SharedMemory.invalidate(current_user.id)
    return UserSettingsResponse.model_validate(settings)


@router.get("/account-settings", response_model=TradingAccountSettingsResponse)
async def get_trading_account_settings(
    trading_account_id: str = Query(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account_result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.id == trading_account_id,
            TradingAccount.user_id == current_user.id,
        )
    )
    account = account_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="trading_account_not_found")

    return TradingAccountSettingsResponse(
        trading_account_id=account.id,
        exchange=account.exchange,
        is_paper=account.is_paper,
        account_label=account.account_label,
        watchlist=list(account.watchlist or []),
        auto_trade_enabled=bool(getattr(account, "auto_trade_enabled", False)),
        auto_trade_threshold=int(getattr(account, "auto_trade_threshold", 80) or 80),
        auto_trade_max_per_scan=int(getattr(account, "auto_trade_max_per_scan", 1) or 1),
    )


@router.patch("/account-settings", response_model=TradingAccountSettingsResponse)
async def update_trading_account_settings(
    body: UpdateTradingAccountSettingsRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account_result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.id == body.trading_account_id,
            TradingAccount.user_id == current_user.id,
        )
    )
    account = account_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="trading_account_not_found")

    # Full Auto is Elite-only: reject auto_trade_enabled=True for non-Elite users
    if body.auto_trade_enabled is True:
        user_result = await db.execute(
            select(User).where(User.id == current_user.id)
        )
        user = user_result.scalar_one_or_none()
        is_trial_active = (
            user
            and user.trial_status == "active"
            and user.trial_end_date
            and user.trial_end_date > datetime.now(timezone.utc)
        )
        if not user or (user.subscription_tier != "elite" and not is_trial_active):
            raise HTTPException(
                status_code=403,
                detail="full_auto_elite_only",
            )

    payload = body.model_dump(exclude_unset=True)
    payload.pop("trading_account_id", None)
    for field, value in payload.items():
        if hasattr(account, field):
            setattr(account, field, value)

    await db.commit()
    await db.refresh(account)
    SharedMemory.invalidate(current_user.id)

    return TradingAccountSettingsResponse(
        trading_account_id=account.id,
        exchange=account.exchange,
        is_paper=account.is_paper,
        account_label=account.account_label,
        watchlist=list(account.watchlist or []),
        auto_trade_enabled=bool(getattr(account, "auto_trade_enabled", False)),
        auto_trade_threshold=int(getattr(account, "auto_trade_threshold", 80) or 80),
        auto_trade_max_per_scan=int(getattr(account, "auto_trade_max_per_scan", 1) or 1),
    )


@router.get("/apex-selects")
async def get_apex_selects_shortlist(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    trading_account_id: str | None = Query(default=None),
):
    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    settings = settings_result.scalar_one_or_none() or UserSettings(user_id=current_user.id)

    if trading_account_id is None:
        trading_account_id = getattr(settings, "preferred_trading_account_id", None)
    if trading_account_id is None:
        return {"status": "success", "data": {"signals": []}}

    try:
        market_ctx = await resolve_market_context(
            db=db, user_id=current_user.id, trading_account_id=trading_account_id
        )
    except HTTPException as exc:
        # Treat missing/invalid account selection as an empty state (not an error)
        if exc.status_code in (400, 404):
            return {"status": "success", "data": {"signals": []}}
        raise

    threshold = settings.apex_selects_threshold or 75
    max_trades = settings.apex_selects_max_trades or 2
    allowed = settings.apex_selects_asset_classes or ["stocks", "crypto"]
    watchlist = set(settings.watchlist or [])

    signals_result = await db.execute(
        select(SignalStack)
        .where(
            SignalStack.expires_at > datetime.now(timezone.utc),
            SignalStack.signal.in_(["buy", "sell"]),
            SignalStack.confidence >= threshold,
            SignalStack.exchange == market_ctx.exchange.value,
        )
        .order_by(SignalStack.confidence.desc(), SignalStack.created_at.desc())
    )
    # Get user's AI name for personalization
    user_result = await db.execute(
        select(User).where(User.id == current_user.id)
    )
    user = user_result.scalar_one()
    ai_name = user.ai_name or "Apex"

    signals = []
    for signal in signals_result.scalars().all():
        if signal.asset_class not in allowed:
            continue
        if watchlist and signal.symbol not in watchlist:
            continue
        payload = _personalize_signal_with_ai_name(_serialize_signal(signal), ai_name)
        payload["threshold_used"] = threshold
        signals.append(payload)
        if len(signals) >= max_trades:
            break

    return {"status": "success", "data": {"signals": signals}}


async def _execute_apex_selects_token(
    token: str,
    db: AsyncSession,
) -> dict:
    token_result = await db.execute(
        select(ApexSelectsApprovalToken).where(ApexSelectsApprovalToken.token == token)
    )
    approval = token_result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if not approval or approval.used_at is not None or approval.expires_at <= now:
        raise HTTPException(status_code=410, detail="This approval link has expired. Open Unitrader to see current signals.")

    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == approval.user_id)
    )
    user_settings = settings_result.scalar_one_or_none() or UserSettings(user_id=approval.user_id)
    ctx = await SharedMemory.load(approval.user_id, db)
    orchestrator = get_orchestrator()
    executed_trades: list[dict] = []

    for signal in approval.signals_payload.get("signals", []):
        symbol = signal.get("symbol")
        asset_class = signal.get("asset_class") or classify_asset(symbol or "")
        ctx.exchange = signal.get("exchange") or _exchange_for_signal(symbol or "", asset_class)
        amount = float(user_settings.max_trade_amount or 100)
        result = await orchestrator.route(
            approval.user_id,
            "trade_execute",
            {
                "symbol": symbol,
                "side": str(signal.get("signal", "buy")).upper(),
                "amount": amount,
                "signal_context": signal,
                "source": "apex_selects_approval",
            },
            db,
        )
        if result.get("status") == "executed":
            executed_trades.append(
                {
                    "id": result.get("trade_id"),
                    "symbol": symbol,
                    "asset_name": signal.get("asset_name", symbol),
                    "side": signal.get("signal", "buy"),
                    "amount": amount,
                }
            )

    approval.used_at = now
    notification_result = await db.execute(
        select(ApexNotification).where(
            ApexNotification.user_id == approval.user_id,
            ApexNotification.notification_type == "apex_selects_ready",
            ApexNotification.actioned_at.is_(None),
        ).order_by(ApexNotification.created_at.desc())
    )
    for notification in notification_result.scalars().all():
        if (notification.data or {}).get("approve_token") == token:
            notification.actioned_at = now
            notification.action_taken = "approved"
            break

    if executed_trades:
        notification_engine = get_unitrader_notification_engine()
        if notification_engine:
            await notification_engine.send_apex_selects_executed(
                user_id=approval.user_id,
                executed_trades=executed_trades,
                db=db,
            )

    return {
        "status": "success",
        "data": {
            "executed_count": len(executed_trades),
            "trades": executed_trades,
        },
    }


@router.get("/apex-selects/approve/{token}", response_class=HTMLResponse)
async def approve_apex_selects_browser(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await _execute_apex_selects_token(token, db)
        executed_count = result["data"]["executed_count"]
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return result
        return HTMLResponse(
            content=(
                "<html><body style=\"font-family:Arial,sans-serif;background:#0a0d14;color:#fff;"
                "display:flex;align-items:center;justify-content:center;min-height:100vh;\">"
                "<div style=\"max-width:520px;padding:24px;border:1px solid #1f2937;border-radius:16px;background:#0d1117;\">"
                f"<h1 style=\"font-size:24px;margin-bottom:12px;\">Done — Apex has placed {executed_count} trades.</h1>"
                "<p style=\"color:#9ca3af;line-height:1.5;\">Check your Unitrader app for the latest positions and activity.</p>"
                "</div></body></html>"
            )
        )
    except HTTPException as exc:
        return HTMLResponse(
            status_code=exc.status_code,
            content=(
                "<html><body style=\"font-family:Arial,sans-serif;background:#0a0d14;color:#fff;"
                "display:flex;align-items:center;justify-content:center;min-height:100vh;\">"
                "<div style=\"max-width:520px;padding:24px;border:1px solid #1f2937;border-radius:16px;background:#0d1117;\">"
                f"<h1 style=\"font-size:24px;margin-bottom:12px;\">{exc.detail}</h1>"
                "<p style=\"color:#9ca3af;line-height:1.5;\">Open Unitrader to see current signals.</p>"
                "</div></body></html>"
            )
        )


@router.post("/apex-selects/approve/{token}")
async def approve_apex_selects(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    return await _execute_apex_selects_token(token, db)
