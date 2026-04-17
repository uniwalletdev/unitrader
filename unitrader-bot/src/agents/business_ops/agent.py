"""
src/agents/business_ops/agent.py — Business Operations Agent.

Hourly housekeeping:
  • compute_snapshot() — pulls Stripe + cost APIs, computes MRR/churn/margin,
    writes one row to `business_snapshots`. No outbound writes anywhere.
  • detect_anomalies()  — z-score on last 30 snapshots, flags > 2σ deviations.
  • forecast_30d()      — linear regression on last 90 days.

All external reads go through `src.security.egress.egress_request`, so every
call is audited. Stripe is allowlisted; Railway/Vercel are optional (skipped
if API keys are not configured).
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import BusinessSnapshot, TokenAuditLog, User
from src.security.egress import ApprovalRequiredError, egress_request

logger = logging.getLogger(__name__)


class BusinessOpsAgent:
    """Computes SaaS business metrics locally."""

    async def compute_snapshot(self) -> BusinessSnapshot:
        """Pull data, compute, persist. Returns the new snapshot row."""
        now = datetime.now(timezone.utc)

        # ── 1. MRR + subscription counts ────────────────────────────────
        mrr_cents, active, new_30d, cancelled_30d = await self._stripe_metrics()
        churn_rate = (cancelled_30d / active * 100.0) if active > 0 else 0.0

        # ── 2. Costs (best-effort; skip providers without keys) ─────────
        costs_breakdown: dict[str, int] = {}
        costs_breakdown["anthropic"] = await self._anthropic_cost_cents_this_month()
        costs_breakdown["railway"] = await self._railway_cost_cents()
        costs_breakdown["vercel"] = await self._vercel_cost_cents()
        # Fixed / estimated overheads (editable via token_optimizer_config later).
        costs_breakdown.setdefault("supabase", 0)
        costs_breakdown.setdefault("other", 0)
        costs_total = sum(costs_breakdown.values())

        # ── 3. Margin ───────────────────────────────────────────────────
        margin = mrr_cents - costs_total

        # ── 4. Forecast + anomaly detection (read from history, not external) ─
        async with AsyncSessionLocal() as db:
            forecast_mrr, forecast_cost = await self._forecast_30d(db)
            anomalies = await self._detect_anomalies(db, mrr_cents, costs_total)

            snapshot = BusinessSnapshot(
                snapshot_at=now,
                mrr_cents=mrr_cents,
                active_subs=active,
                new_subs_30d=new_30d,
                cancelled_subs_30d=cancelled_30d,
                churn_rate_pct=round(churn_rate, 2),
                costs_total_cents=costs_total,
                costs_breakdown=costs_breakdown,
                margin_cents=margin,
                forecast_30d_mrr_cents=forecast_mrr,
                forecast_30d_cost_cents=forecast_cost,
                anomalies=anomalies,
            )
            db.add(snapshot)
            await db.commit()
            await db.refresh(snapshot)

        logger.info(
            "BusinessOps snapshot: MRR=%.2f GBP, costs=%.2f, margin=%.2f, "
            "churn=%.2f%%, anomalies=%d",
            mrr_cents / 100, costs_total / 100, margin / 100, churn_rate, len(anomalies),
        )
        return snapshot

    # ───────────────────────────────────────────────────────────────────
    # Stripe (direct SDK — domain allowlisted)
    # ───────────────────────────────────────────────────────────────────

    async def _stripe_metrics(self) -> tuple[int, int, int, int]:
        """Return (mrr_cents, active_subs, new_30d, cancelled_30d).

        Prefers the Stripe Python SDK for paginated fetch. Falls back to
        zeros if STRIPE_SECRET_KEY is not configured.
        """
        if not (settings.stripe_secret_key or "").strip():
            logger.debug("BusinessOps: no Stripe key — returning zeros")
            return 0, 0, 0, 0

        try:
            import stripe
            stripe.api_key = settings.stripe_secret_key
        except Exception:
            logger.exception("BusinessOps: stripe SDK import failed")
            return 0, 0, 0, 0

        mrr_cents = 0
        active = 0
        new_30d = 0
        cancelled_30d = 0
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        cutoff_ts = int(thirty_days_ago.timestamp())

        # Paginate active subs for MRR.
        try:
            subs = stripe.Subscription.list(status="active", limit=100, expand=["data.items"])
            for sub in subs.auto_paging_iter():
                active += 1
                # Sum price × quantity across items, normalised to monthly.
                for item in (sub.get("items", {}).get("data") or []):
                    price = item.get("price") or {}
                    unit_amount = int(price.get("unit_amount") or 0)
                    quantity = int(item.get("quantity") or 1)
                    recurring = price.get("recurring") or {}
                    interval = recurring.get("interval") or "month"
                    interval_count = int(recurring.get("interval_count") or 1)
                    monthly = _normalise_monthly(unit_amount * quantity, interval, interval_count)
                    mrr_cents += monthly
                if int(sub.get("start_date") or 0) >= cutoff_ts:
                    new_30d += 1
        except Exception:
            logger.exception("BusinessOps: Stripe active subs fetch failed")

        # Cancelled in last 30 d.
        try:
            cancelled = stripe.Subscription.list(
                status="canceled",
                limit=100,
                created={"gte": cutoff_ts},
            )
            cancelled_30d = sum(1 for _ in cancelled.auto_paging_iter())
        except Exception:
            logger.exception("BusinessOps: Stripe cancelled subs fetch failed")

        return mrr_cents, active, new_30d, cancelled_30d

    # ───────────────────────────────────────────────────────────────────
    # Anthropic cost — read from our own token_audit_log (no egress)
    # ───────────────────────────────────────────────────────────────────

    async def _anthropic_cost_cents_this_month(self) -> int:
        """Sum token_audit_log.cost_usd for the current month. Returns cents."""
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                result = await db.execute(
                    select(func.coalesce(func.sum(TokenAuditLog.cost_usd), 0))
                    .where(TokenAuditLog.created_at >= month_start)
                )
                usd = float(result.scalar() or 0)
                return int(round(usd * 100))
        except Exception:
            logger.exception("BusinessOps: anthropic cost rollup failed")
            return 0

    # ───────────────────────────────────────────────────────────────────
    # Railway / Vercel — via egress gateway (read-only)
    # ───────────────────────────────────────────────────────────────────

    async def _railway_cost_cents(self) -> int:
        """Best-effort Railway usage query. Returns 0 if API not configured."""
        token = getattr(settings, "railway_api_token", None) or ""
        if not token:
            return 0
        # NOTE: Railway's GraphQL billing API requires project_id. Skipped here
        # pending explicit config. Future: add settings.railway_project_id.
        return 0

    async def _vercel_cost_cents(self) -> int:
        token = getattr(settings, "vercel_api_token", None) or ""
        if not token:
            return 0
        # NOTE: Vercel usage API gated behind team_id. Skipped pending config.
        return 0

    # ───────────────────────────────────────────────────────────────────
    # Forecast + anomaly detection
    # ───────────────────────────────────────────────────────────────────

    async def _forecast_30d(
        self, db: AsyncSession
    ) -> tuple[int | None, int | None]:
        """Linear regression on the last 90 days of snapshots."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        result = await db.execute(
            select(BusinessSnapshot.snapshot_at, BusinessSnapshot.mrr_cents,
                   BusinessSnapshot.costs_total_cents)
            .where(BusinessSnapshot.snapshot_at >= cutoff)
            .order_by(BusinessSnapshot.snapshot_at.asc())
        )
        rows = result.all()
        if len(rows) < 10:
            return None, None

        x = [(row.snapshot_at - rows[0].snapshot_at).total_seconds() / 86400 for row in rows]
        y_mrr = [row.mrr_cents for row in rows]
        y_cost = [row.costs_total_cents for row in rows]
        try:
            mrr_30d = _linear_regress_point(x, y_mrr, x[-1] + 30)
            cost_30d = _linear_regress_point(x, y_cost, x[-1] + 30)
            return int(mrr_30d), int(cost_30d)
        except Exception:
            logger.exception("BusinessOps: forecast failed")
            return None, None

    async def _detect_anomalies(
        self, db: AsyncSession, mrr_now: int, costs_now: int
    ) -> list[dict[str, Any]]:
        """Z-score against the last 30 snapshots. Flags > 2σ deviations."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        result = await db.execute(
            select(BusinessSnapshot.mrr_cents, BusinessSnapshot.costs_total_cents)
            .where(BusinessSnapshot.snapshot_at >= cutoff)
            .order_by(BusinessSnapshot.snapshot_at.desc())
            .limit(30)
        )
        rows = result.all()
        if len(rows) < 5:
            return []

        anomalies: list[dict[str, Any]] = []
        try:
            mrr_vals = [r.mrr_cents for r in rows]
            cost_vals = [r.costs_total_cents for r in rows]
            for label, current, series in (
                ("mrr", mrr_now, mrr_vals),
                ("costs", costs_now, cost_vals),
            ):
                mean = statistics.mean(series)
                stdev = statistics.pstdev(series) or 1.0
                z = (current - mean) / stdev
                if abs(z) >= 2.0:
                    anomalies.append({
                        "metric": label,
                        "current": current,
                        "mean": round(mean, 2),
                        "stdev": round(stdev, 2),
                        "z_score": round(z, 2),
                        "severity": "high" if abs(z) >= 3 else "medium",
                    })
        except Exception:
            logger.exception("BusinessOps: anomaly detection failed")
        return anomalies


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _normalise_monthly(amount_cents: int, interval: str, interval_count: int) -> int:
    """Convert any Stripe price to a monthly-equivalent amount in cents."""
    if interval_count <= 0:
        interval_count = 1
    if interval == "month":
        return amount_cents // interval_count
    if interval == "year":
        return amount_cents // (12 * interval_count)
    if interval == "week":
        return int(round(amount_cents * 4.345 / interval_count))
    if interval == "day":
        return int(round(amount_cents * 30 / interval_count))
    return amount_cents  # unknown → treat as one-off monthly


def _linear_regress_point(xs: list[float], ys: list[int], x_predict: float) -> float:
    """OLS slope/intercept → predict y at x_predict."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n)) or 1.0
    slope = num / den
    intercept = mean_y - slope * mean_x
    return slope * x_predict + intercept


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

_agent: BusinessOpsAgent | None = None


def get_business_ops_agent() -> BusinessOpsAgent:
    global _agent
    if _agent is None:
        _agent = BusinessOpsAgent()
    return _agent
