"""
src/services/approval_notifier.py — Dispatches approval-needed alerts.

Called fire-and-forget from `src/security/egress.py` when a new
`business_approvals` row is created. Sends to:

  • Telegram admin chat (if TELEGRAM_ADMIN_CHAT_ID is set) — inline
    Approve / Deny buttons.
  • Sentry breadcrumb (always, for visibility).

Failures are swallowed; the primary egress block must not depend on
notification delivery.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import BusinessApproval

logger = logging.getLogger(__name__)


async def notify_new_approval(approval_id: str) -> None:
    """Send notifications for a newly-created pending approval.

    Updates `business_approvals.notified_via` with the successful channels.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BusinessApproval).where(BusinessApproval.id == approval_id)
        )
        approval = result.scalar_one_or_none()
        if approval is None or approval.status != "pending":
            return

        channels: list[str] = []

        # ── Telegram inline-button prompt ──────────────────────────────
        try:
            if await _send_telegram_approval(approval):
                channels.append("telegram")
        except Exception:
            logger.exception("approval_notifier: telegram send failed")

        # ── Sentry breadcrumb (best-effort) ────────────────────────────
        try:
            import sentry_sdk
            sentry_sdk.add_breadcrumb(
                category="governance",
                level="warning",
                message=f"Approval requested: {approval.action_summary}",
                data={
                    "approval_id": approval.id,
                    "domain": approval.target_domain,
                    "agent": approval.requested_by_agent,
                },
            )
        except Exception:
            pass

        if channels:
            approval.notified_via = channels
            await db.commit()


async def _send_telegram_approval(approval: BusinessApproval) -> bool:
    """POST to Telegram Bot API with inline Approve / Deny buttons."""
    admin_chat_id = getattr(settings, "telegram_admin_chat_id", None) or ""
    token = (settings.telegram_bot_token or "").strip()
    if not admin_chat_id or not token:
        return False

    text = (
        f"🛡️ *Governance approval required*\n\n"
        f"*Agent:* `{approval.requested_by_agent}`\n"
        f"*Domain:* `{approval.target_domain or '—'}`\n"
        f"*Action:* {_escape_md(approval.action_summary)}\n"
        f"*Category:* `{approval.action_category}`\n"
        f"*TTL:* 24 h\n\n"
        f"_ID:_ `{approval.id}`"
    )

    payload = {
        "chat_id": str(admin_chat_id),
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"gov_approve:{approval.id}"},
                {"text": "❌ Deny",    "callback_data": f"gov_deny:{approval.id}"},
            ], [
                {"text": "🔍 Details", "callback_data": f"gov_detail:{approval.id}"},
            ]],
        },
    }

    # Use the egress gateway so the notification itself is audited.
    from src.security.egress import egress_request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = await egress_request(
            "POST", url,
            purpose="governance.approval_notify",
            agent="approval_notifier",
            json=payload,
        )
        if resp.status_code == 200:
            return True
        logger.warning("Telegram approval notify returned %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception:
        logger.exception("Telegram approval notify failed")
        return False


def _escape_md(text: str) -> str:
    """Minimal Markdown escape (Telegram legacy mode)."""
    return (
        text.replace("_", r"\_")
            .replace("*", r"\*")
            .replace("[", r"\[")
            .replace("`", r"\`")
    )
