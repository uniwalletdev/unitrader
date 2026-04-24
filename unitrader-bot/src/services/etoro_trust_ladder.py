"""
src/services/etoro_trust_ladder.py — safety rules that gate eToro Real-money
access behind Trust Ladder Stage 3 + FEATURE_ETORO_ENABLED.

Two independent safety layers:

    1. ``check_etoro_connect_allowed`` — connect-time block. Called from
       ``routers/trading.py:connect_exchange`` before credentials are
       validated. Prevents a stage<3 user from ever storing Real-money eToro
       keys. Also enforces the ``FEATURE_ETORO_ENABLED`` kill switch.

    2. ``resolve_effective_etoro_environment`` — runtime override. Called
       from ``src/agents/orchestrator.py:execute_trade`` right after the
       execution venue is resolved. If the stored eToro environment is
       ``'real'`` but the user's Trust Ladder stage is below 3, returns
       ``('demo', True)`` and writes an audit event. Defence in depth for
       the unlikely case a user somehow has a Real row despite the connect
       guard (e.g. historical rows, admin backfill, race).

Design rules honoured here:

  * Trust Ladder stages are **monotonic**. A stage<3 user can only be
    downgraded through explicit admin action, which is out of scope here.
  * No key material, signature, or account id is ever put into an
    ``AuditLog.event_details`` payload.
  * All functions are async + pure (apart from the AuditLog write) so they
    can be tested in isolation with an in-memory SQLite session.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings as app_settings
from models import AuditLog

logger = logging.getLogger(__name__)


# Exported to callers and tests for stable assertion values.
EVENT_CONNECT_BLOCKED = "etoro_connect_blocked"
EVENT_TRUST_LADDER_OVERRIDE = "etoro_trust_ladder_override"

REASON_FEATURE_DISABLED = "etoro_feature_disabled"
REASON_REAL_REQUIRES_STAGE_3 = "etoro_real_requires_stage_3"
REASON_TRUST_LADDER_BELOW_3 = "trust_ladder_below_stage_3"

# Trust Ladder stage at which real-money eToro becomes available.
MIN_STAGE_FOR_REAL = 3


EtoroEnv = Literal["demo", "real"]


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — Connect-time guard
# ─────────────────────────────────────────────────────────────────────────────

async def check_etoro_connect_allowed(
    *,
    user_id: str,
    environment: str,
    trust_ladder_stage: int,
    db: AsyncSession,
    feature_enabled: bool | None = None,
) -> None:
    """Raise :class:`HTTPException` when an eToro connect request must be
    blocked. Returns ``None`` on success.

    Args:
        user_id:              The clerk-synced internal user id.
        environment:          ``'demo'`` or ``'real'`` (as sent by the wizard).
        trust_ladder_stage:   Current Trust Ladder stage for this user.
        db:                   Async DB session used to persist the audit row.
        feature_enabled:      Optional override for the feature flag. When
                              ``None`` we read ``settings.feature_etoro_enabled``
                              so callers don't have to import ``config``.

    Writes ``etoro_connect_blocked`` AuditLog on every rejection. Never
    writes an audit row on success — that event is already covered by the
    generic ``api_key_added`` / ``api_key_test`` flows.
    """
    env = (environment or "").lower().strip()
    enabled = (
        feature_enabled
        if feature_enabled is not None
        else bool(getattr(app_settings, "feature_etoro_enabled", False))
    )

    if not enabled:
        await _write_audit(
            db,
            user_id=user_id,
            event_type=EVENT_CONNECT_BLOCKED,
            details={
                "reason": REASON_FEATURE_DISABLED,
                "attempted_environment": env,
                "trust_ladder_stage": int(trust_ladder_stage or 1),
            },
        )
        raise HTTPException(
            status_code=503,
            detail="eToro integration is not available yet. Coming soon.",
        )

    if env == "real" and int(trust_ladder_stage or 1) < MIN_STAGE_FOR_REAL:
        await _write_audit(
            db,
            user_id=user_id,
            event_type=EVENT_CONNECT_BLOCKED,
            details={
                "reason": REASON_REAL_REQUIRES_STAGE_3,
                "attempted_environment": env,
                "trust_ladder_stage": int(trust_ladder_stage or 1),
            },
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": REASON_REAL_REQUIRES_STAGE_3,
                "message": (
                    "Real-money eToro requires completing onboarding. "
                    "Connect to eToro Demo first, or finish your Trust "
                    "Ladder stages to unlock Real."
                ),
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — Runtime override
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_effective_etoro_environment(
    *,
    user_id: str,
    stored_environment: str | None,
    trust_ladder_stage: int,
    db: AsyncSession,
    symbol: str | None = None,
) -> tuple[EtoroEnv, bool]:
    """Return the effective eToro environment a trade should execute in.

    If the stored environment is ``'real'`` but the user's stage is below
    :data:`MIN_STAGE_FOR_REAL`, we force ``'demo'`` and write an
    ``etoro_trust_ladder_override`` audit event so ops can see that the
    defence-in-depth gate fired.

    Args:
        user_id:             Internal user id (for the audit row).
        stored_environment:  Value of ``ExchangeAPIKey.etoro_environment``.
                             ``None`` is treated as ``'demo'`` (safest).
        trust_ladder_stage:  Current Trust Ladder stage.
        db:                  Async DB session.
        symbol:              Optional symbol (recorded in the audit payload
                             only, never the key or account id).

    Returns:
        ``(effective_environment, was_overridden)``. When
        ``was_overridden`` is ``True`` the caller should also force
        ``paper_trading_enabled=True`` on the SharedContext so the
        downstream ``execute_paper`` / ``execute_live`` branch matches.
    """
    stored = (stored_environment or "demo").lower().strip()
    stage = int(trust_ladder_stage or 1)

    # Normalise anything unrecognised to demo so we never accidentally let
    # junk data through.
    if stored not in ("demo", "real"):
        stored = "demo"

    if stored == "real" and stage < MIN_STAGE_FOR_REAL:
        await _write_audit(
            db,
            user_id=user_id,
            event_type=EVENT_TRUST_LADDER_OVERRIDE,
            details={
                "symbol": symbol,
                "stored_environment": "real",
                "effective_environment": "demo",
                "trust_ladder_stage": stage,
                "reason": REASON_TRUST_LADDER_BELOW_3,
            },
        )
        return "demo", True

    return stored, False  # type: ignore[return-value]


# ─────────────────────────────────────────────────────────────────────────────
# Internal
# ─────────────────────────────────────────────────────────────────────────────

async def _write_audit(
    db: AsyncSession,
    *,
    user_id: str,
    event_type: str,
    details: dict,
) -> None:
    """Persist an AuditLog row. Swallows failures so a logging hiccup never
    blocks or corrupts the safety decision — we already made it."""
    try:
        db.add(AuditLog(user_id=user_id, event_type=event_type, event_details=details))
        await db.flush()
    except Exception as exc:  # pragma: no cover — purely defensive
        logger.warning("etoro_trust_ladder audit write failed (%s): %s", event_type, exc)
