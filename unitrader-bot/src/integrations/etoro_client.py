"""
src/integrations/etoro_client.py — eToro public-API adapter (MVP-B).

Subclasses :class:`BaseExchangeClient` so the rest of Unitrader (orchestrator,
routers, trade monitoring, shared memory) can treat eToro identically to
Alpaca / Coinbase / Binance / OANDA / Kraken.

SCOPE: MVP-B is read-only. The following five methods hit real eToro
endpoints verified against the official docs (2026-04-24):

    verify_connection          → GET /watchlists + GET portfolio
    _resolve_instrument_id     → GET /market-data/search (internalSymbolFull, fields)
    get_account_balance        → GET /trading/info/[demo/]portfolio → Credit
    get_current_price          → GET /market-data/instruments/rates
    get_positions              → parsed from portfolio response

The four write-path methods (``place_order``, ``close_position``,
``get_open_orders``, ``get_order_status``) intentionally raise
``NotImplementedError``. Each carries a docstring preserving the verified
endpoint and PascalCase body shape so the follow-up PR doesn't re-research.
Defence in depth: the router at /api/trading/execute and TradingAgent's
run_cycle/close_position paths early-skip when the resolved exchange is
eToro, so users never hit the NotImplementedError in practice.

Credentials:
    • public_api_key (a.k.a. x-api-key)  — app-level, shared across users.
      Pulled from ``settings.etoro_public_api_key`` — NEVER from the DB row.
    • user_key (a.k.a. x-user-key)       — per-user, stored in
      ``exchange_api_keys.encrypted_api_key`` (Fernet).
    • api_key_id                         — per-user, stored in
      ``exchange_api_keys.encrypted_api_secret`` (Fernet, exposed as
      ``api_secret`` in the BaseExchangeClient contract).
    • environment (``demo`` | ``real``)  — stored in
      ``exchange_api_keys.etoro_environment`` and passed in via ``is_paper``
      (``is_paper=True`` ⇔ demo). NOTE: the real environment OMITS the
      env segment from trading paths, unlike demo which includes /demo/.

Every HTTP call passes through the module-level eToro rate limiter with the
correct ``is_write`` flag. Nothing is logged except request-ids and status
codes — never keys, signatures, balances, or order payloads.

Docs:
    https://api-portal.etoro.com/getting-started/authentication
    https://api-portal.etoro.com/guides/market-orders
    https://builders.etoro.com/blog/developers-guide-to-instrument-discovery
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from config import settings
from src.integrations.etoro_rate_limiter import get_etoro_limiter
from src.integrations.exchange_client import BaseExchangeClient

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class EtoroError(Exception):
    """Base class for all eToro errors."""


class EtoroAuthError(EtoroError):
    """401/403 from eToro — user_key rejected or api_key_id mismatch.

    Surface to the UI as 'Key rejected by eToro — please reconnect'.
    """


class EtoroApiError(EtoroError):
    """Non-auth 4xx/5xx error. Body is NOT included in log/str output to
    avoid leaking instrument or balance data."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(f"eToro API error {status_code}: {message}" if message else f"eToro API error {status_code}")


class EtoroConnectionError(EtoroError):
    """Network-level failure reaching eToro (timeouts, DNS, reset)."""


class EtoroRateLimitError(EtoroError):
    """Raised after a second consecutive 429 once the limiter retry is exhausted."""


# ─────────────────────────────────────────────────────────────────────────────
# URLs
# ─────────────────────────────────────────────────────────────────────────────

_BASE_URL = "https://public-api.etoro.com/api/v1"


# ─────────────────────────────────────────────────────────────────────────────
# EtoroClient
# ─────────────────────────────────────────────────────────────────────────────

class EtoroClient(BaseExchangeClient):
    """eToro public-API adapter.

    Subclasses :class:`BaseExchangeClient` so it slots into the unified
    factory, orchestrator, and trade-monitoring paths unchanged.

    Two environments: ``demo`` (paper) and ``real`` (live). Chosen at
    construction time via ``is_paper``. The same eToro User Key works for
    both; only the request path differs (``/trading/demo/...`` vs
    ``/trading/real/...``).
    """

    # Seconds before a single eToro request is abandoned.
    TIMEOUT = 15.0

    def __init__(
        self,
        api_key: str,       # mapped to eToro User Key (x-user-key)
        api_secret: str,    # mapped to eToro API Key ID (informational)
        *,
        is_paper: bool = True,
        public_api_key: str | None = None,
    ):
        super().__init__(api_key, api_secret)
        self._user_key = api_key
        self._api_key_id = api_secret
        self._environment = "demo" if is_paper else "real"
        self._public_api_key = public_api_key or settings.etoro_public_api_key
        if not self._public_api_key:
            logger.warning(
                "EtoroClient constructed without ETORO_PUBLIC_API_KEY — "
                "requests will fail until settings.etoro_public_api_key is set."
            )
        self._http = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=self.TIMEOUT,
        )
        # Tiny in-process cache of symbol → instrumentId so we don't pay a
        # /market-data/search round-trip for every order.
        self._instrument_id_cache: dict[str, int] = {}

    # ── Low-level request helper ────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """Fresh headers per call — x-request-id is regenerated every time."""
        return {
            "x-request-id": str(uuid.uuid4()),
            "x-api-key": self._public_api_key,
            "x-user-key": self._user_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        is_write: bool | None = None,
    ) -> Any:
        """Issue an HTTP call respecting the rate limiter and retrying once
        on a 429. Never logs the request body, response body, keys, or
        signatures — only method, path, status, and request-id.
        """
        # Default write detection: anything non-GET is a write.
        if is_write is None:
            is_write = method.upper() not in {"GET", "HEAD"}

        limiter = get_etoro_limiter()
        headers = self._headers()
        request_id = headers["x-request-id"]

        for attempt in (1, 2):
            await limiter.acquire(is_write=is_write)
            try:
                resp = await self._http.request(
                    method.upper(), path, params=params, json=json, headers=headers,
                )
            except httpx.TimeoutException as exc:
                logger.warning("eToro request timeout path=%s rid=%s: %s", path, request_id, exc)
                raise EtoroConnectionError(f"eToro request timed out for {path}") from exc
            except httpx.NetworkError as exc:
                logger.warning("eToro network error path=%s rid=%s: %s", path, request_id, exc)
                raise EtoroConnectionError(f"eToro network error for {path}") from exc

            status = resp.status_code
            logger.debug("eToro %s %s → %s rid=%s", method.upper(), path, status, request_id)

            if status == 429:
                retry_after = float(resp.headers.get("Retry-After", "1") or 1)
                if attempt == 1:
                    import asyncio as _asyncio
                    await _asyncio.sleep(min(retry_after, 5.0))
                    # Re-generate request id for the retry.
                    headers = self._headers()
                    request_id = headers["x-request-id"]
                    continue
                raise EtoroRateLimitError(f"eToro rate-limited twice on {path}")

            if status in (401, 403):
                raise EtoroAuthError(f"eToro auth error {status} on {path}")

            if status >= 400:
                # Intentionally truncate the body to prevent accidental PII
                # bleed into logs via an upstream logger formatter.
                raise EtoroApiError(status, resp.text[:160])

            if not resp.content:
                return {}
            try:
                return resp.json()
            except ValueError:
                return resp.text

        # Unreachable — the loop either returns or raises.
        raise EtoroApiError(0, "unreachable retry branch")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _info_path(self, suffix: str) -> str:
        """Path for /trading/info/* — demo keeps env in URL, real omits.

        eToro's public API uses asymmetric environment routing:
            demo → /trading/info/demo/portfolio
            real → /trading/info/portfolio   (no env segment)
        Only /pnl has a symmetric /demo/pnl ↔ /real/pnl variant.
        """
        env_segment = "demo/" if self._environment == "demo" else ""
        return f"/trading/info/{env_segment}{suffix.lstrip('/')}"

    async def _portfolio(self) -> dict:
        """Fetch the user's portfolio (Credit, Positions, Orders, PnL, ...).

        Single-trip source of truth — cheaper than three separate calls for
        balance / positions / orders. Response shape is PascalCase per
        eToro's docs, but we fall back to camelCase just in case.
        """
        data = await self._request("GET", self._info_path("portfolio"), is_write=False)
        return data if isinstance(data, dict) else {}

    async def _resolve_instrument_id(self, symbol: str) -> int:
        """Lookup (and cache) eToro's numeric instrumentId for a symbol.

        Uses GET /market-data/search with the server-side exact-match
        filter ``internalSymbolFull``. The ``fields`` query param is
        REQUIRED by eToro; omitting it returns a 400.
        """
        normalised = symbol.upper().strip()
        if normalised in self._instrument_id_cache:
            return self._instrument_id_cache[normalised]
        data = await self._request(
            "GET",
            "/market-data/search",
            params={
                "internalSymbolFull": normalised,
                "fields": "instrumentId,internalSymbolFull,displayname",
                "pageSize": 5,
            },
            is_write=False,
        )
        # Response shape: {"instruments": [...]} or {"items": [...]} or a bare list.
        if isinstance(data, list):
            items: list[dict] = data
        elif isinstance(data, dict):
            items = data.get("instruments") or data.get("items") or []
        else:
            items = []
        for row in items:
            ticker = str(
                row.get("internalSymbolFull")
                or row.get("symbolFull")
                or row.get("symbol")
                or ""
            ).upper()
            if ticker == normalised:
                instrument_id = int(
                    row.get("instrumentId") or row.get("InstrumentID") or row.get("id") or 0
                )
                if instrument_id:
                    self._instrument_id_cache[normalised] = instrument_id
                    return instrument_id
        raise EtoroApiError(404, f"instrument not found: {symbol}")

    # ── BaseExchangeClient interface (READ PATHS — implemented) ────────────

    async def get_account_balance(self) -> float:
        """Return account cash/credit in the account currency.

        Matches the Alpaca/Coinbase semantics used elsewhere in the app.
        Reads ``Credit`` from the portfolio endpoint — the PascalCase field
        per eToro's docs, with camelCase fallback.
        """
        portfolio = await self._portfolio()
        try:
            return float(
                portfolio.get("Credit")
                or portfolio.get("credit")
                or portfolio.get("equity")
                or portfolio.get("totalEquity")
                or 0.0
            )
        except (TypeError, ValueError):
            return 0.0

    async def get_current_price(self, symbol: str) -> float:
        """Return the latest rate for a symbol via the batch rates endpoint.

        Uses ``GET /market-data/instruments/rates?instrumentIds=<id>``
        (single-id batch call) — eToro does not expose a singular
        ``/instruments/{id}/rate`` endpoint.
        """
        instrument_id = await self._resolve_instrument_id(symbol)
        data = await self._request(
            "GET",
            "/market-data/instruments/rates",
            params={"instrumentIds": str(instrument_id)},
            is_write=False,
        )
        rates: list[dict] = []
        if isinstance(data, list):
            rates = data
        elif isinstance(data, dict):
            rates = data.get("rates") or data.get("Rates") or []
        if rates:
            row = rates[0]
            for key in ("last", "ask", "bid", "rate", "price", "Last", "Ask", "Bid"):
                if key in row:
                    try:
                        return float(row[key])
                    except (TypeError, ValueError):
                        pass
        return 0.0

    async def get_positions(self) -> list[dict]:
        """Open positions — parsed from the portfolio response.

        eToro has no dedicated positions endpoint; positions are a field
        within the portfolio response. Returns PascalCase or camelCase
        records depending on what the server sends.
        """
        portfolio = await self._portfolio()
        positions = portfolio.get("Positions") or portfolio.get("positions") or []
        return positions if isinstance(positions, list) else []

    async def verify_connection(self) -> dict:
        """Cheap round-trip used by the connect wizard and `/test-connection`.

        Returns ``{account_id, username, currency, environment,
        available_cash}``. Raises :class:`EtoroAuthError` on 401/403.

        Implementation:
          1. ``GET /watchlists`` — eToro's canonical auth smoke test
             (see https://api-portal.etoro.com/getting-started/authentication).
             This returns 200 iff both x-api-key and x-user-key are valid.
          2. ``GET /trading/info/[demo/]portfolio`` — populates the UI card
             with Credit. ``username`` is not returned by either endpoint
             in this shape; the UI already tolerates an empty string.
        """
        # Step 1: auth smoke test.
        await self._request("GET", "/watchlists", is_write=False)
        # Step 2: portfolio for the wizard's account-info card.
        portfolio = await self._portfolio()
        try:
            available_cash = float(
                portfolio.get("Credit")
                or portfolio.get("credit")
                or portfolio.get("availableCash")
                or portfolio.get("available_cash")
                or 0.0
            )
        except (TypeError, ValueError):
            available_cash = 0.0
        account_id = str(
            portfolio.get("CID")
            or portfolio.get("cid")
            or portfolio.get("accountId")
            or ""
        )
        return {
            "account_id": account_id,
            "username": "",  # Not exposed by the portfolio response.
            "currency": "USD",  # eToro accounts are USD-denominated.
            "environment": self._environment,
            "available_cash": available_cash,
        }

    # ── BaseExchangeClient interface (WRITE PATHS — stubbed for MVP-B) ─────

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
    ) -> str:
        """⚠️  NOT IMPLEMENTED in MVP-B — deferred to follow-up PR.

        When re-enabling, target endpoints (verified against eToro docs
        2026-04-24: https://api-portal.etoro.com/guides/market-orders):

            Market, by-amount (notional USD — matches Unitrader convention):
              Demo: POST /trading/execution/demo/market-open-orders/by-amount
              Real: POST /trading/execution/market-open-orders/by-amount
              Body (PascalCase, all REQUIRED):
                {
                  "InstrumentID": <int>,
                  "IsBuy":        <bool>,      # NOT "direction":"BUY"/"SELL"
                  "Leverage":     1,           # REQUIRED for cash trades
                  "Amount":       <float>,
                }
              Optional body fields: StopLossRate, TakeProfitRate,
                IsTslEnabled, IsNoStopLoss, IsNoTakeProfit
              Response: {"OrderId": <int>, ...}

            Limit:
              Demo: POST /trading/execution/demo/limit-orders
              Real: POST /trading/execution/limit-orders
              Body (PascalCase): same as above + "Rate": <float> (limit price)

            By-units variant (/by-units) exists but is out of MVP scope —
            Unitrader sizes in notional USD everywhere.

        Critical note: eToro SL/TP can ONLY be set at place-order time via
        the StopLossRate/TakeProfitRate body fields above. Post-hoc
        modification is NOT supported by the public API. The follow-up
        PR must expose these as `place_order` kwargs so users don't trade
        without downside protection — shipping without them is a
        user-harm shape.

        Defence in depth preventing this method from ever being called in
        production: routers/trading.py:/execute returns 501 for
        exchange=='etoro', and TradingAgent.run_cycle early-skips
        before reaching the client.
        """
        raise NotImplementedError(
            "eToro order placement not yet implemented — see follow-up issue. "
            "Read-only (verify, balance, positions, price) is live."
        )

    async def close_position(self, symbol: str) -> bool:
        """⚠️  NOT IMPLEMENTED in MVP-B — deferred to follow-up PR.

        When re-enabling, target endpoint (verified 2026-04-24):

            Demo: POST /trading/execution/demo/market-close-orders/positions/{positionId}
            Real: POST /trading/execution/market-close-orders/positions/{positionId}
            Body (JSON):
              {
                "InstrumentId":   <int>,
                "UnitsToDeduct":  null,          # null = full close
                                                 # number = partial
              }

        ⚠️  POST, NOT DELETE. The original Unitrader implementation used
        DELETE which is wrong and is the main reason this is stubbed until
        a careful rewrite — getting close wrong leaves users with positions
        they cannot exit.

        positionId must be resolved first via get_positions() — eToro does
        not accept close-by-symbol.
        """
        raise NotImplementedError(
            "eToro close_position not yet implemented — see follow-up issue."
        )

    async def get_open_orders(self, symbol: str) -> list[dict]:
        """⚠️  NOT IMPLEMENTED in MVP-B — deferred to follow-up PR.

        Source: parse from the portfolio response (eToro has no dedicated
        orders list endpoint):

            GET /trading/info/[demo/]portfolio → response.Orders[]

        CRITICAL design constraint for the follow-up: naive frontend
        polling of this method will burn eToro's per-user rate limit
        since every call re-fetches the whole portfolio. The follow-up
        MUST cache the portfolio response for 30 seconds inside
        EtoroClient and serve both get_open_orders and get_order_status
        from the cache (pattern mirrors the Alpaca historical cache).
        """
        raise NotImplementedError(
            "eToro get_open_orders not yet implemented — see follow-up issue."
        )

    async def get_order_status(self, symbol: str, order_id: str) -> dict:
        """⚠️  NOT IMPLEMENTED in MVP-B — deferred to follow-up PR.

        Source: parse from the portfolio response. No single-order GET
        endpoint exists on eToro's public API — iterate
        response.Orders[] and match by orderId.

        Same 30-second portfolio-cache requirement as get_open_orders.
        """
        raise NotImplementedError(
            "eToro get_order_status not yet implemented — see follow-up issue."
        )

    # ── No-op guards (correct semantics — keep) ────────────────────────────

    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        # eToro attaches SL/TP to the position at place-order time via the
        # StopLossRate body field. Post-hoc modification is NOT supported
        # by the public API. Returning False so callers fall through to
        # their fallback paths is the correct behaviour — do NOT "fix"
        # this to call a separate SL endpoint, because one does not exist.
        logger.info("eToro set_stop_loss is a no-op (not supported on public API)")
        return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        logger.info("eToro set_take_profit is a no-op (not supported on public API)")
        return False

    # ── Housekeeping ──────────────────────────────────────────────────────

    async def aclose(self) -> None:
        await self._http.aclose()
