"""TokenManagementAgent — central LLM gateway and cost tracker.

Every Anthropic API call in the codebase should route through this agent via
`complete()`. It handles:

  • Model routing (Haiku vs Sonnet) via `complexity`
  • Pre-call budget check + per-agent rate limiting
  • Post-call usage logging to `token_audit_log`
  • Monthly budget accounting in `token_budget`
  • Alert firing at 70/85/95% consumption thresholds
  • Circuit-breaker style fallback to cheaper model when budget is tight

Agents that have not yet been migrated can still emit telemetry by calling
`log_call()` directly after their existing `messages.create(...)` call.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import anthropic
import sentry_sdk
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import AgentRateLimit, TokenAuditLog, TokenBudget
from src.agents.token_manager.pricing import calculate_cost
from src.agents.token_manager.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

# Complexity → model mapping. Fast/simple models come from settings so the
# retired-model swap is a one-line env change; complex remains pinned.
_MODEL_SIMPLE = settings.anthropic_model_fast
_MODEL_COMPLEX = "claude-sonnet-4-20250514"
_MODEL_FALLBACK = settings.anthropic_model_fast

# Priority classification for agents (kept in sync with SQL seed).
_P0_AGENTS = frozenset({"trading", "token_manager"})
_P2_AGENTS = frozenset({"content_writer", "social_media", "learning_hub"})

# Budget thresholds (fraction).
_THRESHOLD_FALLBACK = 0.85    # Switch non-P0 agents to fallback model at 85%
_THRESHOLD_PAUSE_P2 = 0.85    # Pause P2 agents at 85%
_THRESHOLD_HARD_CAP = 0.98    # Hard cap for non-P0 agents
_THRESHOLD_ALERT_70 = 0.70
_THRESHOLD_ALERT_85 = 0.85
_THRESHOLD_ALERT_95 = 0.95


@dataclass
class LLMResponse:
    """Normalized response from the gateway."""
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    cached_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    fallback_used: bool = False
    raw: Any = field(default=None, repr=False)


class BudgetExceededError(Exception):
    """Raised when a non-P0 agent hits a hard budget cap."""


class TokenManagementAgent:
    """Singleton gateway for all LLM calls."""

    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None
        self._rate_limiter = get_rate_limiter()

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                base_url=settings.anthropic_base_url,
            )
        return self._client

    # ──────────────────────────────────────────────────────────────────────
    # Model routing
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _priority_for(agent_name: str) -> str:
        if agent_name in _P0_AGENTS:
            return "p0"
        if agent_name in _P2_AGENTS:
            return "p2"
        return "p1"

    def _select_model(
        self,
        complexity: Literal["simple", "complex"],
        agent_name: str,
        budget_pct: float,
        override_model: str | None,
    ) -> tuple[str, bool]:
        """Return (model, fallback_used)."""
        if override_model:
            return override_model, False

        baseline = _MODEL_COMPLEX if complexity == "complex" else _MODEL_SIMPLE
        priority = self._priority_for(agent_name)

        # Non-P0 agents downgrade to fallback model when budget is tight.
        if priority != "p0" and budget_pct >= _THRESHOLD_FALLBACK:
            if baseline != _MODEL_FALLBACK:
                return _MODEL_FALLBACK, True

        return baseline, False

    # ──────────────────────────────────────────────────────────────────────
    # Budget check (called before routing non-P0 agents)
    # ──────────────────────────────────────────────────────────────────────

    async def check_budget(
        self,
        agent_name: str,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Return budget status + allowance for `agent_name`.

        Returns:
            {
              "allowed": bool,
              "pct_used": float (0-1),
              "reason": str,
              "fallback_model": str | None,
              "budget_total": int,
              "budget_used": int,
            }
        """
        priority = self._priority_for(agent_name)

        async def _inner(sess: AsyncSession) -> dict[str, Any]:
            budget = await self._current_budget(sess)
            if budget is None:
                # No budget row — allow but warn.
                return {
                    "allowed": True,
                    "pct_used": 0.0,
                    "reason": "no_budget_row",
                    "fallback_model": None,
                    "budget_total": 0,
                    "budget_used": 0,
                }
            pct = (budget.budget_used / budget.budget_total) if budget.budget_total else 0.0

            # P0 always allowed.
            if priority == "p0":
                return {
                    "allowed": True,
                    "pct_used": pct,
                    "reason": "p0_never_throttled",
                    "fallback_model": None,
                    "budget_total": budget.budget_total,
                    "budget_used": budget.budget_used,
                }

            # P2 pauses above threshold.
            if priority == "p2" and pct >= _THRESHOLD_PAUSE_P2:
                return {
                    "allowed": False,
                    "pct_used": pct,
                    "reason": f"p2_paused: budget {pct:.1%} > {_THRESHOLD_PAUSE_P2:.0%}",
                    "fallback_model": _MODEL_FALLBACK,
                    "budget_total": budget.budget_total,
                    "budget_used": budget.budget_used,
                }

            # P1 hard-caps near 100%.
            if priority == "p1" and pct >= _THRESHOLD_HARD_CAP:
                return {
                    "allowed": False,
                    "pct_used": pct,
                    "reason": f"p1_hard_cap: budget {pct:.1%} > {_THRESHOLD_HARD_CAP:.0%}",
                    "fallback_model": _MODEL_FALLBACK,
                    "budget_total": budget.budget_total,
                    "budget_used": budget.budget_used,
                }

            # P1 downgrades at 85% (allowed but with cheaper model).
            if priority == "p1" and pct >= _THRESHOLD_FALLBACK:
                return {
                    "allowed": True,
                    "pct_used": pct,
                    "reason": f"p1_fallback: budget {pct:.1%} ≥ 85%",
                    "fallback_model": _MODEL_FALLBACK,
                    "budget_total": budget.budget_total,
                    "budget_used": budget.budget_used,
                }

            return {
                "allowed": True,
                "pct_used": pct,
                "reason": "ok",
                "fallback_model": None,
                "budget_total": budget.budget_total,
                "budget_used": budget.budget_used,
            }

        if db is not None:
            return await _inner(db)
        async with AsyncSessionLocal() as sess:
            return await _inner(sess)

    # ──────────────────────────────────────────────────────────────────────
    # Gateway: complete() — the single entrypoint
    # ──────────────────────────────────────────────────────────────────────

    async def complete(
        self,
        *,
        agent_name: str,
        task_type: str,
        system: str,
        messages: list[dict[str, Any]],
        complexity: Literal["simple", "complex"] = "simple",
        max_tokens: int = 512,
        user_id: str | None = None,
        trade_id: str | None = None,
        override_model: str | None = None,
        cacheable: bool = False,
    ) -> LLMResponse:
        """Single entrypoint for any Anthropic chat completion in the app."""
        # 1. Budget check
        status = await self.check_budget(agent_name)
        if not status["allowed"]:
            raise BudgetExceededError(status["reason"])

        # 2. Model routing
        model, fallback_used = self._select_model(
            complexity, agent_name, status["pct_used"], override_model
        )

        # 3. Rate-limit reservation (estimate = max_tokens as upper bound)
        async with AsyncSessionLocal() as db:
            allowed, reason = await self._rate_limiter.acquire(
                db, agent_name, max_tokens
            )
        if not allowed:
            raise BudgetExceededError(reason)

        # 4. Call Anthropic
        start = time.monotonic()
        error_msg: str | None = None
        raw_response: Any = None
        tokens_in = 0
        tokens_out = 0
        cached = 0
        text = ""

        create_kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        if cacheable:
            # Anthropic prompt caching: system prompt as a cache block
            create_kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        try:
            raw_response = await self.client.messages.create(**create_kwargs)
            text = (raw_response.content[0].text or "").strip() if raw_response.content else ""
            usage = getattr(raw_response, "usage", None)
            if usage is not None:
                tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
                tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
                cached = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        except Exception as exc:
            error_msg = str(exc)
            logger.error(
                "TokenManager.complete(agent=%s) call failed: %s", agent_name, exc
            )
            # Log failure and re-raise
            latency_ms = int((time.monotonic() - start) * 1000)
            asyncio.create_task(
                self.log_call(
                    agent_name=agent_name,
                    task_type=task_type,
                    model=model,
                    tokens_in=0,
                    tokens_out=0,
                    cached_tokens=0,
                    latency_ms=latency_ms,
                    user_id=user_id,
                    trade_id=trade_id,
                    status="error",
                    error_message=error_msg,
                )
            )
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        cost = calculate_cost(tokens_in, tokens_out, model, cached_tokens=cached)

        # 5. Fire-and-forget log
        asyncio.create_task(
            self.log_call(
                agent_name=agent_name,
                task_type=task_type,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cached_tokens=cached,
                latency_ms=latency_ms,
                user_id=user_id,
                trade_id=trade_id,
                status="success",
            )
        )

        return LLMResponse(
            text=text,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached,
            cost_usd=cost,
            latency_ms=latency_ms,
            fallback_used=fallback_used,
            raw=raw_response,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Post-call logging (usable standalone by non-migrated agents)
    # ──────────────────────────────────────────────────────────────────────

    async def log_call(
        self,
        *,
        agent_name: str,
        task_type: str | None,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cached_tokens: int = 0,
        latency_ms: int | None = None,
        user_id: str | None = None,
        trade_id: str | None = None,
        status: str = "success",
        error_message: str | None = None,
        context_hash: str | None = None,
    ) -> None:
        """Persist one LLM call to token_audit_log and update monthly budget."""
        cost = calculate_cost(tokens_in, tokens_out, model, cached_tokens=cached_tokens)

        try:
            async with AsyncSessionLocal() as db:
                entry = TokenAuditLog(
                    agent_name=agent_name,
                    task_type=task_type,
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cached_tokens=cached_tokens,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    user_id=user_id,
                    trade_id=trade_id,
                    status=status,
                    error_message=error_message,
                    context_hash=context_hash,
                )
                db.add(entry)
                # Update monthly budget
                budget = await self._current_budget(db, create_if_missing=True)
                if budget is not None and status == "success":
                    total_tokens = tokens_in + tokens_out
                    await db.execute(
                        update(TokenBudget)
                        .where(TokenBudget.id == budget.id)
                        .values(
                            budget_used=TokenBudget.budget_used + total_tokens,
                            cost_total_usd=TokenBudget.cost_total_usd + cost,
                        )
                    )
                await db.commit()
        except Exception as exc:
            logger.error("TokenManager.log_call failed: %s", exc, exc_info=True)
            sentry_sdk.capture_exception(exc)

    # ──────────────────────────────────────────────────────────────────────
    # Budget helpers
    # ──────────────────────────────────────────────────────────────────────

    async def _current_budget(
        self,
        db: AsyncSession,
        create_if_missing: bool = False,
    ) -> TokenBudget | None:
        """Return the active budget row for the current month."""
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        result = await db.execute(
            select(TokenBudget).where(TokenBudget.month_start == month_start)
        )
        budget = result.scalar_one_or_none()

        if budget is None and create_if_missing:
            # Seed a new month's budget row on the fly.
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)
            month_end = next_month.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            budget = TokenBudget(
                month_start=month_start,
                month_end=month_end,
                budget_total=10_000_000,
                status="active",
            )
            db.add(budget)
            await db.flush()

        return budget

    # ──────────────────────────────────────────────────────────────────────
    # Alerts (called by scheduler)
    # ──────────────────────────────────────────────────────────────────────

    async def check_and_fire_alerts(self) -> None:
        """Fire Sentry alerts at 70/85/95% monthly consumption."""
        try:
            async with AsyncSessionLocal() as db:
                budget = await self._current_budget(db)
                if budget is None or budget.budget_total == 0:
                    return

                pct = budget.budget_used / budget.budget_total
                fired = False

                if pct >= _THRESHOLD_ALERT_95 and not budget.alert_95_sent:
                    _fire_alert(
                        "critical",
                        f"Token budget 95% consumed ({budget.budget_used:,}/"
                        f"{budget.budget_total:,}). "
                        f"Cost=${float(budget.cost_total_usd):.2f}.",
                    )
                    budget.alert_95_sent = True
                    fired = True
                if pct >= _THRESHOLD_ALERT_85 and not budget.alert_85_sent:
                    _fire_alert(
                        "warning",
                        f"Token budget 85% consumed — non-P0 agents falling back "
                        f"to {_MODEL_FALLBACK}.",
                    )
                    budget.alert_85_sent = True
                    fired = True
                if pct >= _THRESHOLD_ALERT_70 and not budget.alert_70_sent:
                    _fire_alert(
                        "info",
                        f"Token budget 70% consumed ({budget.budget_used:,}/"
                        f"{budget.budget_total:,}).",
                    )
                    budget.alert_70_sent = True
                    fired = True

                if fired:
                    await db.commit()
        except Exception as exc:
            logger.error("check_and_fire_alerts failed: %s", exc, exc_info=True)

    # ──────────────────────────────────────────────────────────────────────
    # Dashboard helpers
    # ──────────────────────────────────────────────────────────────────────

    async def get_current_budget(self) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            budget = await self._current_budget(db, create_if_missing=True)
            if budget is None:
                return {"status": "no_budget"}
            pct = (budget.budget_used / budget.budget_total) if budget.budget_total else 0.0
            return {
                "month_start": budget.month_start.isoformat(),
                "month_end": budget.month_end.isoformat(),
                "budget_total": budget.budget_total,
                "budget_used": budget.budget_used,
                "pct_used": round(pct, 4),
                "cost_total_usd": float(budget.cost_total_usd or 0),
                "status": budget.status,
                "alerts": {
                    "70": budget.alert_70_sent,
                    "85": budget.alert_85_sent,
                    "95": budget.alert_95_sent,
                },
            }


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _fire_alert(level: str, message: str) -> None:
    """Push an alert to Sentry (and whichever handler is wired up)."""
    logger.warning("TokenBudget alert [%s]: %s", level.upper(), message)
    try:
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("component", "token_manager")
            scope.set_tag("alert_level", level)
            sentry_sdk.capture_message(message, level=level)
    except Exception:
        pass


def context_hash(system: str, messages: list[dict]) -> str:
    """Deterministic hash for cache lookups and dedup."""
    m = hashlib.sha256()
    m.update(system.encode("utf-8", errors="ignore"))
    for msg in messages:
        m.update(str(msg.get("role", "")).encode())
        content = msg.get("content", "")
        if isinstance(content, str):
            m.update(content.encode("utf-8", errors="ignore"))
        else:
            m.update(str(content).encode("utf-8", errors="ignore"))
    return m.hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# Singleton accessor
# ──────────────────────────────────────────────────────────────────────────

_token_manager: TokenManagementAgent | None = None


def get_token_manager() -> TokenManagementAgent:
    """Return the process-wide TokenManagementAgent singleton."""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManagementAgent()
    return _token_manager
