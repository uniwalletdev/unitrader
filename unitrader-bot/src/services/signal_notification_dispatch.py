"""
src/services/signal_notification_dispatch.py — High-confidence signal alerts.

Broadcasts a single market signal to all active users who have Telegram and/or
WhatsApp linked and notifications enabled, subject to each user's minimum
confidence threshold.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog, User, UserExternalAccount, UserSettings
from src.services.unitrader_notifications import get_unitrader_notification_engine

logger = logging.getLogger(__name__)


def _build_telegram_message(signal: dict) -> str:
    symbol = str(signal.get("symbol", "")).strip()
    direction = str(signal.get("direction", "")).strip().upper()
    confidence = int(signal.get("confidence", 0) or 0)
    exchange = str(signal.get("exchange", "")).strip().upper()
    price = float(signal.get("price", 0) or 0)
    reasoning = str(signal.get("reasoning", "") or "").strip()

    return (
        f"🔔 *Signal Alert – {symbol}*\n"
        f"Direction: *{direction}*\n"
        f"Confidence: *{confidence}%*\n"
        f"Exchange: {exchange}\n"
        f"Price: ${price:.2f}\n\n"
        f"_{reasoning}_\n\n"
        "[Open Apex →](https://unitraderai.vercel.app/dashboard)"
    )


def _build_whatsapp_message(signal: dict) -> str:
    symbol = str(signal.get("symbol", "")).strip()
    direction = str(signal.get("direction", "")).strip().upper()
    confidence = int(signal.get("confidence", 0) or 0)
    exchange = str(signal.get("exchange", "")).strip().upper()
    price = float(signal.get("price", 0) or 0)
    reasoning = str(signal.get("reasoning", "") or "").strip()

    return (
        f"🔔 Signal Alert – {symbol}\n"
        f"Direction: {direction}\n"
        f"Confidence: {confidence}%\n"
        f"Exchange: {exchange}\n"
        f"Price: ${price:.2f}\n\n"
        f"{reasoning}\n\n"
        "Open Apex: https://unitraderai.vercel.app/dashboard"
    )


async def dispatch_signal_notification(signal: dict, db: AsyncSession) -> dict:
    """Broadcast a high-confidence signal to all eligible users.

    Returns:
        {"sent_telegram": int, "sent_whatsapp": int, "errors": list[dict]}
    """
    confidence = int(signal.get("confidence", 0) or 0)

    # Dedupe window: avoid broadcasting the same signal repeatedly when multiple
    # Full Auto accounts independently discover it in close succession.
    # This is implemented using the audit log (no new tables needed).
    symbol = str(signal.get("symbol", "")).strip().upper()
    direction = str(signal.get("direction", "")).strip().upper()
    exchange = str(signal.get("exchange", "")).strip().lower()
    bucket = int(confidence // 5) * 5  # bucket to reduce near-identical spam
    dedupe_key = f"{exchange}:{symbol}:{direction}:{bucket}"
    dedupe_window_seconds = 5 * 60
    try:
        recent = (
            await db.execute(
                select(AuditLog.id)
                .where(
                    AuditLog.event_type == "signal_notification_dispatched",
                    AuditLog.timestamp
                    >= datetime.now(timezone.utc) - timedelta(seconds=dedupe_window_seconds),
                )
                .order_by(AuditLog.timestamp.desc())
                .limit(30)
            )
        ).all()
        if recent:
            # Pull recent rows' keys via a second select that includes event_details;
            # keep the first query cheap for the common no-recent-events case.
            rows_recent = (
                await db.execute(
                    select(AuditLog.event_details)
                    .where(AuditLog.id.in_([rid for (rid,) in recent]))
                )
            ).all()
            for (details,) in rows_recent:
                if isinstance(details, dict) and details.get("dedupe_key") == dedupe_key:
                    return {
                        "sent_telegram": 0,
                        "sent_whatsapp": 0,
                        "errors": [],
                        "deduped": True,
                        "dedupe_key": dedupe_key,
                    }
    except Exception as exc:
        logger.debug("Signal notification dedupe check failed (non-fatal): %s", exc)

    # Pull all linked Telegram/WhatsApp accounts for active users (filter in Python
    # for JSON settings, which are stored in UserExternalAccount.settings).
    rows = (
        await db.execute(
            select(
                User.id,
                UserSettings.signal_notify_min_confidence,
                UserExternalAccount.platform,
                UserExternalAccount.external_id,
                UserExternalAccount.settings,
            )
            .join(UserSettings, UserSettings.user_id == User.id)
            .join(UserExternalAccount, UserExternalAccount.user_id == User.id)
            .where(
                User.is_active == True,  # noqa: E712
                UserExternalAccount.is_linked == True,  # noqa: E712
                UserExternalAccount.platform.in_(["telegram", "whatsapp"]),
            )
        )
    ).all()

    recipients: dict[str, dict] = {}
    for user_id, min_conf, platform, external_id, settings in rows:
        # Per-user confidence threshold (default handled by DB/model).
        if int(min_conf or 75) > confidence:
            continue
        per_platform_enabled = bool((settings or {}).get("notifications", True))
        if not per_platform_enabled:
            continue
        r = recipients.setdefault(str(user_id), {"telegram": None, "whatsapp": None})
        if platform == "telegram":
            r["telegram"] = str(external_id)
        elif platform == "whatsapp":
            r["whatsapp"] = str(external_id)

    telegram_targets = [v["telegram"] for v in recipients.values() if v.get("telegram")]
    whatsapp_targets = [v["whatsapp"] for v in recipients.values() if v.get("whatsapp")]

    # Audit BEFORE dispatch (single row).
    try:
        db.add(
            AuditLog(
                user_id="system",
                event_type="signal_notification_dispatched",
                event_details={
                    "signal": signal,
                    "dedupe_key": dedupe_key,
                    "recipient_count": len(recipients),
                    "channels": [
                        *([] if not telegram_targets else ["telegram"]),
                        *([] if not whatsapp_targets else ["whatsapp"]),
                    ],
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
        await db.flush()
    except Exception as exc:
        # Non-fatal: do not block sends if audit logging fails.
        logger.warning("Signal notification audit log write failed: %s", exc)

    engine = get_unitrader_notification_engine()
    telegram_bot = getattr(engine, "telegram_bot", None) if engine else None
    whatsapp_bot = getattr(engine, "whatsapp_bot", None) if engine else None

    telegram_msg = _build_telegram_message(signal)
    whatsapp_msg = _build_whatsapp_message(signal)

    errors: list[dict] = []

    async def _send_telegram(chat_id: str) -> bool:
        try:
            if not telegram_bot or not getattr(telegram_bot, "app", None):
                return False
            await telegram_bot.app.bot.send_message(
                chat_id=chat_id,
                text=telegram_msg,
                parse_mode="Markdown",
            )
            return True
        except Exception as exc:
            errors.append({"channel": "telegram", "target": chat_id, "error": str(exc)})
            return False

    async def _send_whatsapp(number: str) -> bool:
        try:
            if not whatsapp_bot:
                return False
            await whatsapp_bot.send_message(number, whatsapp_msg)
            return True
        except Exception as exc:
            errors.append({"channel": "whatsapp", "target": number, "error": str(exc)})
            return False

    telegram_tasks = [_send_telegram(cid) for cid in telegram_targets]
    whatsapp_tasks = [_send_whatsapp(num) for num in whatsapp_targets]
    results = await asyncio.gather(*telegram_tasks, *whatsapp_tasks, return_exceptions=False)

    sent_telegram = sum(1 for ok in results[: len(telegram_tasks)] if ok is True)
    sent_whatsapp = sum(1 for ok in results[len(telegram_tasks) :] if ok is True)

    return {"sent_telegram": sent_telegram, "sent_whatsapp": sent_whatsapp, "errors": errors}

