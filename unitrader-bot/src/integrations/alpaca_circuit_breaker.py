"""
Alpaca Circuit Breaker — prevents cascading failures when credentials are
invalid or the Alpaca API is down.

When Alpaca returns consecutive 401 Unauthorized responses, the circuit
breaker trips OPEN and short-circuits all subsequent requests for a cooldown
period.  This avoids:
  • Hundreds of wasted 401 requests per minute
  • Log spam from every symbol failing individually
  • Downstream crashes (empty volumes → max() crash, 500s on endpoints)

States:
  CLOSED    → normal operation, all requests go through
  OPEN      → all requests immediately raise AlpacaUnavailableError
  HALF_OPEN → one probe request allowed; success → CLOSED, failure → OPEN
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class AlpacaUnavailableError(Exception):
    """Raised when the Alpaca circuit breaker is OPEN."""
    pass


class AlpacaCircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 300.0,
    ):
        self._failure_count = 0
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state = "CLOSED"
        self._opened_at: float = 0.0
        self._last_error: str = ""

    # ── read state ──────────────────────────────

    @property
    def state(self) -> str:
        if self._state == "OPEN":
            if time.monotonic() - self._opened_at >= self._recovery_timeout:
                self._state = "HALF_OPEN"
                logger.info("Alpaca circuit breaker → HALF_OPEN (will probe on next request)")
        return self._state

    @property
    def remaining_cooldown(self) -> float:
        if self._state != "OPEN":
            return 0.0
        return max(0.0, self._recovery_timeout - (time.monotonic() - self._opened_at))

    # ── record outcomes ─────────────────────────

    def record_success(self) -> None:
        if self._state != "CLOSED":
            logger.info("Alpaca circuit breaker → CLOSED (recovered)")
        self._failure_count = 0
        self._state = "CLOSED"
        self._last_error = ""

    def record_auth_failure(self, error: str = "") -> None:
        self._failure_count += 1
        self._last_error = error
        if self._failure_count >= self._failure_threshold:
            self._state = "OPEN"
            self._opened_at = time.monotonic()
            logger.error(
                "Alpaca circuit breaker → OPEN after %d consecutive auth failures. "
                "All Alpaca requests will be skipped for %.0fs. Last error: %s",
                self._failure_count,
                self._recovery_timeout,
                error,
            )

    # ── guard ───────────────────────────────────

    def check(self) -> None:
        """Call before every Alpaca request.  Raises if circuit is OPEN."""
        s = self.state  # may transition OPEN → HALF_OPEN
        if s == "OPEN":
            raise AlpacaUnavailableError(
                f"Alpaca circuit breaker OPEN — skipping request. "
                f"Retry in {self.remaining_cooldown:.0f}s. Last: {self._last_error}"
            )
        # HALF_OPEN → allow one probe request
        # CLOSED → allow all

    def status_dict(self) -> dict:
        """Expose state for the /health endpoint."""
        return {
            "state": self.state,
            "failure_count": self._failure_count,
            "remaining_cooldown_s": round(self.remaining_cooldown),
            "last_error": self._last_error,
        }


# ── module-level singleton ──────────────────────

alpaca_breaker = AlpacaCircuitBreaker(failure_threshold=3, recovery_timeout=300.0)
