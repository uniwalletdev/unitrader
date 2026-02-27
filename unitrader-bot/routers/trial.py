"""
routers/trial.py — Trial period management endpoints.

Endpoints:
    GET  /api/trial/status          — Current trial state + AI performance summary
    GET  /api/trial/choice-options  — Upgrade / downgrade / cancel options
    POST /api/trial/make-choice     — Act on the user's choice
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Trade, User
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trial", tags=["Trial"])

TRIAL_DAYS = 14

PRO_BENEFITS = [
    "Unlimited exchange connections",
    "Unlimited AI trades",
    "Priority Claude AI (Opus)",
    "Advanced analytics & reports",
    "Email trade alerts",
    "API access",
    "Premium support",
]

FREE_LIMITS = [
    "1 exchange connection",
    "10 AI trades per month",
    "BTC/USD only",
    "Basic performance dashboard",
    "Community support",
]


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _days_remaining(user: User) -> int:
    if not user.trial_end_date:
        return 0
    now = datetime.now(timezone.utc)
    end = user.trial_end_date
    if end.tzinfo is None:
        from datetime import timezone as _tz
        end = end.replace(tzinfo=_tz.utc)
    delta = (end - now).total_seconds()
    return max(0, int(delta / 86_400))


def _trial_phase(days: int) -> str:
    """Return a label describing urgency based on days remaining."""
    if days >= 8:
        return "early"      # Days 1–6
    if days >= 4:
        return "mid"        # Days 7–10
    if days >= 1:
        return "late"       # Days 11–13
    return "expired"        # Day 14 / past end


# ─────────────────────────────────────────────
# GET /api/trial/status
# ─────────────────────────────────────────────

@router.get("/status")
async def trial_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the user's trial state alongside their AI's performance summary."""
    days = _days_remaining(current_user)
    phase = _trial_phase(days)

    # Auto-expire: if time is up but status hasn't been flipped yet
    if days == 0 and current_user.trial_status == "active":
        current_user.trial_status = "expired"
        await db.commit()

    # ── Aggregate trade stats ─────────────────────────────────────────
    closed_q = select(
        func.count(Trade.id).label("total"),
        func.sum(Trade.profit).label("total_profit"),
        func.sum(Trade.loss).label("total_loss"),
    ).where(
        Trade.user_id == current_user.id,
        Trade.status == "closed",
    )
    row = (await db.execute(closed_q)).one()

    total_trades: int = row.total or 0
    total_profit: float = float(row.total_profit or 0)
    total_loss:   float = float(row.total_loss   or 0)
    net_pnl:      float = total_profit - total_loss

    # Win rate
    wins_q = select(func.count(Trade.id)).where(
        Trade.user_id == current_user.id,
        Trade.status  == "closed",
        Trade.profit  > 0,
    )
    wins: int = (await db.execute(wins_q)).scalar() or 0
    win_rate = round((wins / total_trades * 100) if total_trades else 0, 1)

    # Build a human-readable performance summary
    if total_trades == 0:
        summary = f"{current_user.ai_name} is ready to trade — connect an exchange to start!"
    elif net_pnl >= 0:
        summary = (
            f"{current_user.ai_name} is up ${net_pnl:.2f} "
            f"with a {win_rate}% win rate across {total_trades} trades!"
        )
    else:
        summary = (
            f"{current_user.ai_name} made {total_trades} trades. "
            f"Net P&L: ${net_pnl:.2f}. Learning and improving."
        )

    # Banner message based on urgency
    if phase == "early":
        banner = f"Trial active — {days} days remaining. {current_user.ai_name} is learning your style 🚀"
    elif phase == "mid":
        banner = f"⚡ {days} days left! Your AI has made {total_trades} trades. Don't lose access →"
    elif phase == "late":
        banner = f"⏰ TRIAL EXPIRES IN {days} DAY{'S' if days != 1 else ''}! Make your choice now →"
    else:
        banner = f"Your trial has ended. Choose a plan to keep {current_user.ai_name} trading."

    return {
        "status": current_user.trial_status,
        "phase": phase,
        "days_remaining": days,
        "trial_end_date": current_user.trial_end_date.isoformat() if current_user.trial_end_date else None,
        "trial_started_at": current_user.trial_started_at.isoformat() if current_user.trial_started_at else None,
        "ai_name": current_user.ai_name,
        "subscription_tier": current_user.subscription_tier,
        "banner": banner,
        "show_choice_modal": phase == "expired" or days <= 1,
        "performance": {
            "trades_made": total_trades,
            "wins": wins,
            "win_rate_pct": win_rate,
            "total_profit": round(total_profit, 2),
            "total_loss": round(total_loss, 2),
            "net_pnl": round(net_pnl, 2),
        },
        "performance_summary": summary,
    }


# ─────────────────────────────────────────────
# GET /api/trial/choice-options
# ─────────────────────────────────────────────

@router.get("/choice-options")
async def trial_choice_options(
    current_user: User = Depends(get_current_user),
):
    """Return the three paths available at the end of trial."""
    days = _days_remaining(current_user)

    return {
        "days_remaining": days,
        "ai_name": current_user.ai_name,
        "options": [
            {
                "choice": "pro",
                "label": "Keep Trading — Go Pro",
                "price": "$9.99/month",
                "price_cents": 999,
                "trial_days": 0,
                "highlighted": True,
                "cta": "Upgrade to Pro →",
                "benefits": PRO_BENEFITS,
                "action": "upgrade_to_pro",
                "description": (
                    f"Keep {current_user.ai_name} running 24/7 with "
                    "unlimited trades and all exchanges."
                ),
            },
            {
                "choice": "free",
                "label": "Stay on Free",
                "price": "$0/month",
                "price_cents": 0,
                "highlighted": False,
                "cta": "Continue Free",
                "limits": FREE_LIMITS,
                "action": "downgrade_to_free",
                "description": (
                    "Keep using Unitrader with limited trades and one exchange. "
                    "Upgrade anytime."
                ),
            },
            {
                "choice": "cancel",
                "label": "Cancel Account",
                "price": None,
                "highlighted": False,
                "cta": "Cancel My Account",
                "action": "cancel_account",
                "description": "Permanently delete your account and all data.",
            },
        ],
    }


# ─────────────────────────────────────────────
# POST /api/trial/make-choice
# ─────────────────────────────────────────────

class TrialChoiceRequest(BaseModel):
    choice: str   # pro | free | cancel


@router.post("/make-choice")
async def make_trial_choice(
    body: TrialChoiceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Act on the user's post-trial choice.

    - pro    → redirects client to Stripe checkout (returns checkout_url)
    - free   → downgrades to free tier, trial_status = converted
    - cancel → deactivates account
    """
    if body.choice not in ("pro", "free", "cancel"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="choice must be one of: pro, free, cancel",
        )

    if body.choice == "pro":
        # ── Use the billing service so Stripe customer is created correctly ──
        from config import settings as _settings
        checkout_url: str

        if _settings.stripe_secret_key and _settings.stripe_pro_price_id:
            try:
                from src.services.subscription import start_pro_checkout
                checkout_url = await start_pro_checkout(
                    current_user,
                    _settings.stripe_pro_price_id,
                )
            except Exception as exc:
                logger.error("Stripe checkout failed for user %s: %s", current_user.id, exc)
                checkout_url = "/app?modal=trial"
        else:
            # Stripe not configured in this environment — redirect back with notice
            checkout_url = "/app?modal=trial&stripe=unconfigured"
            logger.warning("Stripe not configured — cannot create checkout for user %s", current_user.id)

        # Mark intent; actual tier upgrade happens via Stripe webhook
        current_user.trial_status = "converted"
        await db.commit()
        return {
            "status": "redirect",
            "choice": "pro",
            "checkout_url": checkout_url,
            "message": "Redirecting to payment...",
        }

    elif body.choice == "free":
        current_user.subscription_tier = "free"
        current_user.trial_status = "downgraded"   # distinct from "converted" (pro)
        await db.commit()
        logger.info("User %s chose free tier after trial", current_user.id)
        return {
            "status": "success",
            "choice": "free",
            "message": (
                f"{current_user.ai_name} will continue on the Free plan. "
                "You can upgrade to Pro anytime."
            ),
            "limits": {
                "max_exchanges": 1,
                "allowed_symbols": ["BTCUSDT", "BTC/USDT", "BTC/USD"],
                "trades_per_month": 10,
            },
        }

    elif body.choice == "cancel":
        current_user.is_active = False
        current_user.trial_status = "converted"
        await db.commit()
        logger.info("User %s cancelled account via trial choice", current_user.id)
        return {
            "status": "success",
            "choice": "cancel",
            "message": "Your account has been deactivated. Sorry to see you go.",
        }
