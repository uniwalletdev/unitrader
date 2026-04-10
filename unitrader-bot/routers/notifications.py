"""
routers/notifications.py — Apex notification history and read state APIs.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import ApexNotification, ApexSelectsApprovalToken, User, UserExternalAccount, UserSettings
from routers.auth import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


def _serialize_notification(
    notification: ApexNotification,
    approve_active: bool,
    approve_expires_at: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    can_undo = bool(
        notification.notification_type == "auto_trade_executed"
        and notification.undo_token
        and notification.undo_expires_at
        and notification.undo_expires_at > now
        and not notification.actioned_at
    )
    return {
        "id": notification.id,
        "notification_type": notification.notification_type,
        "title": notification.title,
        "body": notification.body,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "actioned_at": notification.actioned_at.isoformat() if notification.actioned_at else None,
        "action_taken": notification.action_taken,
        "undo_token": notification.undo_token,
        "undo_expires_at": notification.undo_expires_at.isoformat() if notification.undo_expires_at else None,
        "approve_expires_at": approve_expires_at,
        "trade_id": notification.trade_id,
        "data": notification.data or {},
        "can_undo": can_undo,
        "can_approve": bool(
            notification.notification_type == "apex_selects_ready"
            and approve_active
            and not notification.actioned_at
        ),
    }


@router.get("")
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    type: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ApexNotification).where(ApexNotification.user_id == current_user.id)
    if type:
        types = [item.strip() for item in type.split(",") if item.strip()]
        if types:
            stmt = stmt.where(ApexNotification.notification_type.in_(types))
    result = await db.execute(
        stmt.order_by(ApexNotification.created_at.desc()).limit(limit)
    )
    notifications = result.scalars().all()

    unread_result = await db.execute(
        select(func.count(ApexNotification.id)).where(
            ApexNotification.user_id == current_user.id,
            ApexNotification.read_at.is_(None),
        )
    )
    unread_count = int(unread_result.scalar() or 0)

    approve_tokens = {
        token: expires_at.isoformat()
        for token, expires_at in (
            await db.execute(
                select(ApexSelectsApprovalToken.token, ApexSelectsApprovalToken.expires_at).where(
                    ApexSelectsApprovalToken.user_id == current_user.id,
                    ApexSelectsApprovalToken.used_at.is_(None),
                    ApexSelectsApprovalToken.expires_at > datetime.now(timezone.utc),
                )
            )
        ).all()
    }

    items = []
    for notification in notifications:
        approve_token = (notification.data or {}).get("approve_token")
        items.append(
            _serialize_notification(
                notification,
                bool(approve_token and approve_token in approve_tokens),
                approve_tokens.get(approve_token) if approve_token else None,
            )
        )

    return {"status": "success", "data": {"items": items, "unread_count": unread_count}}


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApexNotification).where(
            ApexNotification.id == notification_id,
            ApexNotification.user_id == current_user.id,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        await db.flush()
    return {"status": "success"}


@router.post("/read-all")
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApexNotification).where(
            ApexNotification.user_id == current_user.id,
            ApexNotification.read_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    for notification in result.scalars().all():
        notification.read_at = now
    await db.flush()
    return {"status": "success"}


@router.get("/settings")
async def get_notification_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    min_conf_res = await db.execute(
        select(UserSettings.signal_notify_min_confidence).where(
            UserSettings.user_id == current_user.id
        )
    )
    signal_notify_min_confidence = int(min_conf_res.scalar_one_or_none() or 75)

    external_accounts = (
        await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.user_id == current_user.id,
                UserExternalAccount.is_linked == True,  # noqa: E712
            )
        )
    ).scalars().all()
    telegram = next((acc for acc in external_accounts if acc.platform == "telegram"), None)
    whatsapp = next((acc for acc in external_accounts if acc.platform == "whatsapp"), None)

    # Telegram @handle (optional — many users have no public username)
    telegram_username: str | None = None
    if telegram and telegram.external_username:
        raw = str(telegram.external_username).strip()
        telegram_username = raw[1:] if raw.startswith("@") else raw

    whatsapp_number: str | None = None
    if whatsapp and whatsapp.external_id:
        whatsapp_number = str(whatsapp.external_id).strip()

    return {
        "status": "success",
        "data": {
            "telegram_linked": bool(telegram),
            "telegram_username": telegram_username,
            "telegram_notifications_enabled": bool((telegram.settings or {}).get("notifications", True)) if telegram else False,
            "whatsapp_linked": bool(whatsapp),
            "whatsapp_number": whatsapp_number,
            "whatsapp_notifications_enabled": bool((whatsapp.settings or {}).get("notifications", True)) if whatsapp else False,
            "signal_notify_min_confidence": signal_notify_min_confidence,
        },
    }


@router.patch("/settings")
async def update_notification_settings(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    telegram = (
        await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.user_id == current_user.id,
                UserExternalAccount.platform == "telegram",
                UserExternalAccount.is_linked == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    whatsapp = (
        await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.user_id == current_user.id,
                UserExternalAccount.platform == "whatsapp",
                UserExternalAccount.is_linked == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if "telegram_notifications_enabled" in body and telegram:
        settings = telegram.settings or {}
        settings["notifications"] = bool(body["telegram_notifications_enabled"])
        telegram.settings = settings
    if "whatsapp_notifications_enabled" in body and whatsapp:
        settings = whatsapp.settings or {}
        settings["notifications"] = bool(body["whatsapp_notifications_enabled"])
        whatsapp.settings = settings
    return {"status": "success"}
