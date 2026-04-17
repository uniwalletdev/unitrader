"""
src/security/egress.py — Outbound HTTP choke point (Phase 12).

All outbound HTTP traffic SHOULD route through `egress_request()`.
The gateway:

  1. Extracts the domain from the URL.
  2. Looks it up in `egress_allowlist`.
     - Domain missing OR category='must_approve'  → raises ApprovalRequiredError
       and creates a `business_approvals` row (pending).
     - Domain 'read_only' or 'read_write'         → proceeds.
  3. Executes the request via httpx.
  4. Logs the call to `egress_audit_log` (always, even on error).

Bypassing the gateway is permitted only for legacy clients during the
migration window. A CI test greps for new raw `httpx`/`requests` calls
outside this module.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import BusinessApproval, EgressAllowlist, EgressAuditLog

logger = logging.getLogger(__name__)


class ApprovalRequiredError(Exception):
    """Raised when an egress call targets a non-allowlisted or must-approve domain.

    The approval row is created *before* the exception is raised, so callers
    can inspect `.approval_id` and surface it to the admin UI.
    """

    def __init__(self, approval_id: str, domain: str, message: str | None = None):
        self.approval_id = approval_id
        self.domain = domain
        super().__init__(
            message
            or f"Outbound call to '{domain}' requires admin approval "
               f"(approval_id={approval_id})"
        )


class EgressGateway:
    """Singleton gateway enforcing the egress allowlist.

    Usage:
        from src.security.egress import egress_request
        resp = await egress_request(
            "GET",
            "https://api.stripe.com/v1/subscriptions",
            purpose="business_ops.compute_mrr",
            headers={"Authorization": f"Bearer {key}"},
        )
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        # Small in-process cache for allowlist to avoid hitting DB on every call.
        self._allowlist_cache: dict[str, tuple[str, str]] = {}
        self._cache_loaded_at: float = 0.0

    async def _client_singleton(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _load_allowlist(self, db: AsyncSession, force: bool = False) -> None:
        """Refresh the in-process allowlist cache (TTL 60 s)."""
        now = time.monotonic()
        if not force and (now - self._cache_loaded_at) < 60 and self._allowlist_cache:
            return
        result = await db.execute(select(EgressAllowlist))
        rows = result.scalars().all()
        self._allowlist_cache = {r.domain: (r.category, r.purpose) for r in rows}
        self._cache_loaded_at = now

    async def _lookup(self, db: AsyncSession, domain: str) -> tuple[str, str] | None:
        await self._load_allowlist(db)
        # Exact match first, then parent-domain match (e.g. data.alpaca.markets → alpaca.markets).
        if domain in self._allowlist_cache:
            return self._allowlist_cache[domain]
        parts = domain.split(".")
        for i in range(1, len(parts) - 1):
            parent = ".".join(parts[i:])
            if parent in self._allowlist_cache:
                return self._allowlist_cache[parent]
        return None

    async def _create_approval(
        self,
        db: AsyncSession,
        *,
        domain: str,
        method: str,
        url: str,
        purpose: str | None,
        payload: Any,
        agent: str,
    ) -> str:
        """Insert a pending approval row and return its id."""
        action_category = "hmrc_filing" if "hmrc" in domain else "egress"
        approval = BusinessApproval(
            requested_by_agent=agent,
            action_category=action_category,
            target_domain=domain,
            action_summary=f"{method} {url}",
            request_payload={
                "method": method,
                "url": url,
                "purpose": purpose,
                "payload_preview": _safe_preview(payload),
            },
            status="pending",
            notified_via=[],
            ttl_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db.add(approval)
        await db.commit()
        await db.refresh(approval)

        # Fire-and-forget notification hooks (Telegram, Sentry).
        try:
            from src.services.approval_notifier import notify_new_approval
            import asyncio
            asyncio.create_task(notify_new_approval(approval.id))
        except Exception:
            # Notifier is optional; do not block the egress check.
            logger.debug("approval_notifier unavailable", exc_info=True)

        logger.warning(
            "Egress BLOCKED pending approval: %s %s (domain=%s, approval_id=%s)",
            method, url, domain, approval.id,
        )
        return approval.id

    async def _audit(
        self,
        db: AsyncSession,
        *,
        domain: str,
        method: str,
        url: str,
        status_code: int | None,
        purpose: str | None,
        bytes_out: int,
        bytes_in: int,
        duration_ms: int,
        approval_id: str | None,
        error_message: str | None,
    ) -> None:
        try:
            path = urlparse(url).path or "/"
            row = EgressAuditLog(
                domain=domain,
                method=method,
                path=path[:1024],
                status_code=status_code,
                purpose=purpose,
                bytes_out=bytes_out,
                bytes_in=bytes_in,
                duration_ms=duration_ms,
                approval_id=approval_id,
                error_message=error_message[:2048] if error_message else None,
            )
            db.add(row)
            await db.commit()
        except Exception:
            logger.exception("Failed to write egress_audit_log row")

    async def request(
        self,
        method: str,
        url: str,
        *,
        purpose: str | None = None,
        agent: str = "unknown",
        approval_id: str | None = None,
        **httpx_kwargs: Any,
    ) -> httpx.Response:
        """Execute an outbound HTTP request after the allowlist check.

        Args:
            method: 'GET', 'POST', ...
            url: Full URL.
            purpose: Free-form tag for audit ("business_ops.compute_mrr").
            agent: Name of the calling agent/service for approval attribution.
            approval_id: If supplied, the call is treated as an executed
                approved action (audit row links back to the approval).
            **httpx_kwargs: Forwarded to httpx.AsyncClient.request().

        Returns:
            httpx.Response

        Raises:
            ApprovalRequiredError: Domain is not on the allowlist, or is
                flagged must_approve, and no approval_id was supplied.
        """
        domain = urlparse(url).hostname or ""
        if not domain:
            raise ValueError(f"Cannot extract domain from URL: {url!r}")

        t0 = time.monotonic()
        status_code: int | None = None
        bytes_out = 0
        bytes_in = 0
        err: str | None = None

        # Compute a rough outgoing size.
        if (data := httpx_kwargs.get("json")) is not None:
            import json as _json
            try:
                bytes_out = len(_json.dumps(data))
            except Exception:
                bytes_out = 0
        elif (content := httpx_kwargs.get("content")) is not None:
            bytes_out = len(content) if isinstance(content, (bytes, str)) else 0

        async with AsyncSessionLocal() as db:
            # ── Allowlist check (skipped when executing an approved action) ─
            if approval_id is None:
                entry = await self._lookup(db, domain)
                if entry is None or entry[0] == "must_approve":
                    new_approval_id = await self._create_approval(
                        db,
                        domain=domain,
                        method=method,
                        url=url,
                        purpose=purpose,
                        payload=httpx_kwargs.get("json") or httpx_kwargs.get("content"),
                        agent=agent,
                    )
                    await self._audit(
                        db,
                        domain=domain,
                        method=method,
                        url=url,
                        status_code=None,
                        purpose=purpose,
                        bytes_out=bytes_out,
                        bytes_in=0,
                        duration_ms=int((time.monotonic() - t0) * 1000),
                        approval_id=new_approval_id,
                        error_message="approval_required",
                    )
                    raise ApprovalRequiredError(new_approval_id, domain)

            # ── Execute the request ──────────────────────────────────────────
            try:
                client = await self._client_singleton()
                resp = await client.request(method, url, **httpx_kwargs)
                status_code = resp.status_code
                bytes_in = len(resp.content)
                return resp
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                raise
            finally:
                await self._audit(
                    db,
                    domain=domain,
                    method=method,
                    url=url,
                    status_code=status_code,
                    purpose=purpose,
                    bytes_out=bytes_out,
                    bytes_in=bytes_in,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    approval_id=approval_id,
                    error_message=err,
                )


def _safe_preview(payload: Any, max_chars: int = 512) -> str | None:
    """Redact likely secrets and truncate for display in approval UI."""
    if payload is None:
        return None
    try:
        import json as _json
        if isinstance(payload, (dict, list)):
            s = _json.dumps(payload, default=str)
        else:
            s = str(payload)
    except Exception:
        s = repr(payload)
    # Very conservative redactor: mask anything that looks like an API key.
    import re
    s = re.sub(r"(sk-[A-Za-z0-9_-]{10,})", "sk-***REDACTED***", s)
    s = re.sub(r'("?(api[_-]?key|secret|token|password)"?\s*[:=]\s*")([^"]{4,})(")',
               r'\1***REDACTED***\4', s, flags=re.IGNORECASE)
    return s[:max_chars] + ("…" if len(s) > max_chars else "")


# ─────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────

_gateway: EgressGateway | None = None


def get_egress_gateway() -> EgressGateway:
    global _gateway
    if _gateway is None:
        _gateway = EgressGateway()
    return _gateway


async def egress_request(
    method: str,
    url: str,
    *,
    purpose: str | None = None,
    agent: str = "unknown",
    approval_id: str | None = None,
    **httpx_kwargs: Any,
) -> httpx.Response:
    """Convenience wrapper — see `EgressGateway.request`."""
    return await get_egress_gateway().request(
        method, url,
        purpose=purpose,
        agent=agent,
        approval_id=approval_id,
        **httpx_kwargs,
    )
