"""
src/services/email_sequences.py — Trial email drip sequence via Resend.

Emails sent:
    Day 7  — "Your AI made $X! Keep the momentum →"
    Day 11 — "Last 3 days! Choose your path"
    Day 13 — "TOMORROW: Your trial ends"
    Day 0  — Trial expired, force choice

Called daily by the background scheduler in main.py.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import Trade, User

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Email sending (Resend)
# ─────────────────────────────────────────────

async def _send(to: str, subject: str, html: str) -> bool:
    """Send one email via Resend. Returns True on success."""
    from config import settings
    if not settings.resend_api_key:
        logger.warning("Resend not configured — skipping email to %s: %s", to, subject)
        return False
    try:
        import resend
        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": getattr(settings, "email_from", "noreply@unitrader.app"),
            "to": to,
            "subject": subject,
            "html": html,
        })
        logger.info("Email sent → %s | %s", to, subject)
        return True
    except Exception as exc:
        logger.error("Resend failed for %s: %s", to, exc)
        return False


# ─────────────────────────────────────────────
# HTML email templates
# ─────────────────────────────────────────────

def _html_base(content: str) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto;background:#0d1117;
                color:#e6edf3;padding:32px;border-radius:12px;">
      <div style="margin-bottom:24px;">
        <span style="font-weight:700;font-size:20px;color:#7c3aed;">Unitrader</span>
      </div>
      {content}
      <hr style="border:none;border-top:1px solid #21262d;margin:32px 0;">
      <p style="font-size:12px;color:#8b949e;">
        You're receiving this because you signed up for a Unitrader trial.
        <a href="https://unitrader.app/app" style="color:#7c3aed;">Manage your account</a>
      </p>
    </div>
    """


def _day7_html(ai_name: str, net_pnl: float, win_rate: float, trades: int) -> str:
    pnl_str = f"+${net_pnl:.2f}" if net_pnl >= 0 else f"-${abs(net_pnl):.2f}"
    return _html_base(f"""
      <h2 style="color:#fff;margin-bottom:8px;">
        🚀 {ai_name} is halfway through your trial!
      </h2>
      <p style="color:#8b949e;margin-bottom:24px;">
        Here's what your AI has achieved in the first 7 days:
      </p>
      <div style="background:#161b22;border-radius:8px;padding:20px;margin-bottom:24px;">
        <div style="display:flex;gap:24px;flex-wrap:wrap;">
          <div>
            <p style="color:#8b949e;font-size:12px;margin:0;">Net P&amp;L</p>
            <p style="font-size:24px;font-weight:700;color:{'#7c3aed' if net_pnl >= 0 else '#f85149'};margin:4px 0;">
              {pnl_str}
            </p>
          </div>
          <div>
            <p style="color:#8b949e;font-size:12px;margin:0;">Win Rate</p>
            <p style="font-size:24px;font-weight:700;color:#7c3aed;margin:4px 0;">{win_rate}%</p>
          </div>
          <div>
            <p style="color:#8b949e;font-size:12px;margin:0;">Trades</p>
            <p style="font-size:24px;font-weight:700;color:#fff;margin:4px 0;">{trades}</p>
          </div>
        </div>
      </div>
      <p style="color:#8b949e;margin-bottom:24px;">
        {ai_name} has 7 days left to trade for you. After that, choose Pro ($9.99/mo)
        to keep going — or stay on the free plan with limited trades.
      </p>
      <a href="https://unitrader.app/app"
         style="display:inline-block;background:#7c3aed;color:#fff;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:600;">
        View {ai_name}'s Dashboard →
      </a>
    """)


def _day11_html(ai_name: str, net_pnl: float, days_left: int) -> str:
    pnl_str = f"+${net_pnl:.2f}" if net_pnl >= 0 else f"-${abs(net_pnl):.2f}"
    return _html_base(f"""
      <h2 style="color:#fff;margin-bottom:8px;">
        ⏰ {days_left} days left with {ai_name}
      </h2>
      <p style="color:#8b949e;margin-bottom:24px;">
        Your trial ends in {days_left} days. {ai_name} has achieved {pnl_str} for you.
        Time to choose your path.
      </p>
      <div style="background:#161b22;border-radius:8px;padding:20px;margin-bottom:24px;">
        <p style="color:#fff;font-weight:600;margin:0 0 16px;">Your options after trial:</p>
        <div style="margin-bottom:12px;">
          <span style="color:#7c3aed;font-weight:600;">Pro — $9.99/mo</span>
          <span style="color:#8b949e;font-size:14px;"> · Unlimited trades, all exchanges, priority AI</span>
        </div>
        <div>
          <span style="color:#fff;font-weight:600;">Free — $0/mo</span>
          <span style="color:#8b949e;font-size:14px;"> · 10 trades/month, 1 exchange, BTC only</span>
        </div>
      </div>
      <a href="https://unitrader.app/app?modal=trial"
         style="display:inline-block;background:#7c3aed;color:#fff;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:600;">
        Choose My Plan →
      </a>
    """)


def _day13_html(ai_name: str) -> str:
    return _html_base(f"""
      <h2 style="color:#f85149;margin-bottom:8px;">
        🔴 TOMORROW: {ai_name}'s trial expires
      </h2>
      <p style="color:#8b949e;margin-bottom:24px;">
        This is your last reminder. After tomorrow, {ai_name} will stop trading
        unless you choose a plan.
      </p>
      <a href="https://unitrader.app/app?modal=trial"
         style="display:inline-block;background:#7c3aed;color:#fff;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:600;">
        Make My Choice Now →
      </a>
      <p style="color:#8b949e;margin-top:24px;font-size:14px;">
        Pro is only $9.99/month. That's 33 cents a day for a 24/7 AI trader.
      </p>
    """)


def _expired_html(ai_name: str) -> str:
    return _html_base(f"""
      <h2 style="color:#fff;margin-bottom:8px;">
        Your trial has ended
      </h2>
      <p style="color:#8b949e;margin-bottom:24px;">
        {ai_name} has stopped trading. Choose a plan to reactivate your AI or
        continue on the free tier with limited access.
      </p>
      <a href="https://unitrader.app/app?modal=trial"
         style="display:inline-block;background:#7c3aed;color:#fff;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:600;">
        Choose Your Plan →
      </a>
    """)


# ─────────────────────────────────────────────
# Per-user email logic
# ─────────────────────────────────────────────

async def _get_user_stats(db: AsyncSession, user_id: str) -> dict:
    """Fetch aggregate trade stats for a user."""
    from sqlalchemy import func
    row = (await db.execute(
        select(
            func.count(Trade.id).label("total"),
            func.sum(Trade.profit).label("profit"),
            func.sum(Trade.loss).label("loss"),
        ).where(Trade.user_id == user_id, Trade.status == "closed")
    )).one()

    total   = row.total or 0
    profit  = float(row.profit or 0)
    loss    = float(row.loss    or 0)
    net_pnl = profit - loss
    wins    = (await db.execute(
        select(func.count(Trade.id)).where(
            Trade.user_id == user_id,
            Trade.status  == "closed",
            Trade.profit  > 0,
        )
    )).scalar() or 0
    win_rate = round((wins / total * 100) if total else 0, 1)

    return {"total": total, "net_pnl": net_pnl, "win_rate": win_rate}


async def process_trial_email_for_user(user: User, db: AsyncSession) -> None:
    """Send the correct trial email for a single user based on their days remaining."""
    if not user.trial_end_date or user.trial_status != "active":
        return

    now = datetime.now(timezone.utc)
    end = user.trial_end_date
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    days_left = max(0, int((end - now).total_seconds() / 86_400))
    stats = await _get_user_stats(db, user.id)

    if days_left == 7:
        await _send(
            to=user.email,
            subject=f"🚀 {user.ai_name} is halfway through your trial!",
            html=_day7_html(user.ai_name, stats["net_pnl"], stats["win_rate"], stats["total"]),
        )
    elif days_left == 3:
        await _send(
            to=user.email,
            subject=f"⏰ {days_left} days left with {user.ai_name}!",
            html=_day11_html(user.ai_name, stats["net_pnl"], days_left),
        )
    elif days_left == 1:
        await _send(
            to=user.email,
            subject=f"🔴 Tomorrow: {user.ai_name}'s trial expires!",
            html=_day13_html(user.ai_name),
        )
    elif days_left == 0:
        # Mark as expired
        user.trial_status = "expired"
        await db.commit()
        await _send(
            to=user.email,
            subject=f"Your Unitrader trial has ended",
            html=_expired_html(user.ai_name),
        )


# ─────────────────────────────────────────────
# Main scheduler entry point
# ─────────────────────────────────────────────

async def send_trial_emails_for_all_users() -> None:
    """Process trial emails for every active trial user.

    Called daily at 9am UTC by the background scheduler in main.py.
    """
    logger.info("Trial email scheduler: running daily check...")
    processed = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.trial_status == "active",
                User.is_active == True,   # noqa: E712
            )
        )
        users = result.scalars().all()

    for user in users:
        try:
            async with AsyncSessionLocal() as db:
                # Re-fetch user in a fresh session for each email
                result = await db.execute(select(User).where(User.id == user.id))
                fresh_user = result.scalar_one_or_none()
                if fresh_user:
                    await process_trial_email_for_user(fresh_user, db)
                    processed += 1
        except Exception as exc:
            logger.error("Trial email error for user %s: %s", user.id, exc)

    logger.info("Trial email scheduler: processed %d users", processed)
