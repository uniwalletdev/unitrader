# Follow-up: eToro write-path — order placement and position management

> **Status:** Deferred from MVP-B (commit `acd3d04`). Read path is live; write path is stubbed behind `NotImplementedError` + router 501 + orchestrator early-skip guards. This doc is the single source of truth for what the follow-up PR must deliver.

## Gate to unblock

The read path (MVP-B) must have been stable in production for **≥7 days** with:

- Zero new `EtoroApiError(404)` in Sentry
- Zero new `EtoroAuthError` bursts (brief spikes on user key rotation are fine; sustained spikes indicate a regression)
- `/api/trading/execute` 501s for eToro render correctly in the frontend toast (see frontend check in this PR's thread)

## ⚠️ BLOCKER — Two-key architecture question, unanswered

**This must be resolved before any write path ships.**

The Unitrader architecture stores:

- `settings.etoro_public_api_key` — one **app-level** public key on the server, shared across all users.
- `ExchangeAPIKey.encrypted_api_key` — a **per-user** user key, pasted by each user into the wizard.

Every request sends both headers: `x-api-key: <app-key>` + `x-user-key: <per-user-key>`.

**The open question:** does eToro's `x-api-key` authorisation model actually permit *one app key* to authenticate *many unrelated users' user keys*? Or does eToro expect each user-key to be generated under the same account/app that minted the x-api-key (in which case Unitrader needs OAuth, not a shared app key)?

The current `/watchlists` smoke test only proves that **your own** user key works with **your own** app key. It proves nothing about whether a second user's key will authenticate.

### Pre-merge test for the follow-up PR (not this one)

Before shipping any write endpoint, verify with TWO separate eToro test accounts:

```bash
# Test 1: your user key + your server's app key — should 200
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "x-request-id: $(uuidgen)" \
  -H "x-api-key: $ETORO_PUBLIC_API_KEY" \
  -H "x-user-key: $YOUR_USER_KEY" \
  https://public-api.etoro.com/api/v1/watchlists

# Test 2: *different* user's user key + same server's app key — MUST 200
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "x-request-id: $(uuidgen)" \
  -H "x-api-key: $ETORO_PUBLIC_API_KEY" \
  -H "x-user-key: $OTHER_USER_KEY" \
  https://public-api.etoro.com/api/v1/watchlists
```

If Test 2 returns 401/403, Unitrader's current architecture is wrong for eToro. The write-path follow-up becomes an **OAuth migration** issue, not a simple endpoint implementation. That's materially different scope.

**Do not skip this check.** The read path works today because users are probably testing with their own keys in isolation; the polymorphism breaks at the second user.

## Endpoints to implement (verified 2026-04-24)

| Method | Demo path | Real path | Notes |
|---|---|---|---|
| `place_order` market by-amount | `POST /trading/execution/demo/market-open-orders/by-amount` | `POST /trading/execution/market-open-orders/by-amount` | Real omits env segment (asymmetric routing) |
| `place_order` limit | `POST /trading/execution/demo/limit-orders` | `POST /trading/execution/limit-orders` | Same body + `Rate` |
| `close_position` | `POST /trading/execution/demo/market-close-orders/positions/{positionId}` | `POST /trading/execution/market-close-orders/positions/{positionId}` | **POST, not DELETE** (original bug). `positionId` must be resolved first via `get_positions()`. |
| `get_open_orders` / `get_order_status` | N/A (derived) | N/A (derived) | Parse `Orders[]` from `GET /trading/info/[demo/]portfolio` — no dedicated list/single endpoint exists |

## Request body shape — **PascalCase, not camelCase**

Market order (by-amount):

```json
{
  "InstrumentID": 100000,
  "IsBuy":        true,
  "Leverage":     1,
  "Amount":       100.0
}
```

All four fields are **required**. `Leverage: 1` is required even for cash trades. `IsBuy: bool` replaces the old `direction: "BUY"/"SELL"`.

Limit order adds `"Rate": <float>` (limit price).

Close order body:

```json
{
  "InstrumentId":  100000,
  "UnitsToDeduct": null
}
```

`UnitsToDeduct: null` → full close. A number → partial close.

Optional order-body fields the follow-up **must** expose as kwargs:

- `StopLossRate`, `TakeProfitRate` — the *only* way to set SL/TP on eToro. No post-hoc modification endpoint exists.
- `IsTslEnabled` — trailing stop.
- `IsNoStopLoss`, `IsNoTakeProfit` — explicit "no protection" flags (the API may reject orders without SL/TP by default).

## Critical design requirements

### 1. 30-second portfolio cache

`get_open_orders` and `get_order_status` both derive from the same portfolio response. If exposed to the frontend without caching, naive polling will burn eToro's per-user rate limit.

Required pattern inside `EtoroClient` (per-instance, not module-level — positions are user-specific):

```python
self._portfolio_cache: tuple[dict, datetime] | None = None
_PORTFOLIO_CACHE_TTL_SECONDS = 30
```

Both methods read from the cache. Cache invalidation on any write (place/close) so users see their own action reflected immediately even within the TTL.

### 2. SL/TP must be first-class kwargs on `place_order`

```python
async def place_order(
    self,
    symbol: str,
    side: str,
    quantity: float,
    price: float | None = None,
    *,
    stop_loss_rate: float | None = None,
    take_profit_rate: float | None = None,
    trailing_stop: bool = False,
) -> str: ...
```

The existing `set_stop_loss` / `set_take_profit` no-ops stay as-is. They return `False` and the `TradingAgent` already tolerates that. Do NOT "fix" them to call a separate endpoint — one does not exist.

### 3. Remove the MVP-B guards when shipping

- Router 501 in `@c:\Users\Admin\Downloads\unitrader\unitrader-bot\routers\trading.py:1106-1128` (block starts at `# ── eToro write-path gate (MVP-B)`).
- Early-skip guards at `@c:\Users\Admin\Downloads\unitrader\unitrader-bot\src\agents\core\trading_agent.py` line ~1349 and line ~1823.
- `NotImplementedError` raises in `@c:\Users\Admin\Downloads\unitrader\unitrader-bot\src\integrations\etoro_client.py` for `place_order`, `close_position`, `get_open_orders`, `get_order_status`.
- The regression guard `test_write_methods_raise_not_implemented` in `tests/test_etoro_client.py` must be replaced with real behaviour assertions — **do NOT weaken it to a pass-through.**

## Test surface for the follow-up PR

- `test_place_market_order_body_shape` — PascalCase, `IsBuy` as bool, `Leverage: 1`.
- `test_place_market_order_demo_vs_real_path` — path asymmetry.
- `test_place_limit_order_uses_rate` — `Rate` field in body when `price` provided.
- `test_place_order_with_sl_tp_kwargs` — `StopLossRate` / `TakeProfitRate` propagate to body.
- `test_close_position_posts_to_market_close` — POST (not DELETE), correct path, `UnitsToDeduct: null`.
- `test_close_position_resolves_position_id_from_portfolio` — chained portfolio call.
- `test_portfolio_cache_30s_ttl` — two successive `get_open_orders` calls make one HTTP request.
- `test_portfolio_cache_invalidates_on_write` — `place_order` or `close_position` busts the cache.
- `test_get_open_orders_parses_orders_from_portfolio` — response shape.
- `test_get_order_status_matches_by_order_id` — single-order lookup from portfolio list.
- **Two-key architecture integration test** (live, opt-in via env) — `test_second_user_key_authenticates_with_same_app_key`. Skips if the second user key isn't provided. This is the pre-merge gate.

## Out of scope even for the follow-up

- **By-units market orders** (`/market-open-orders/by-units`) — Unitrader sizes in notional USD everywhere; add only if a caller requires it.
- **WebSocket private feed** (`/api-reference/websocket/overview`) — the 30s cache is sufficient until order/position freshness needs to be sub-second. Separate issue.
- **Historical candles** (`/market-data/instruments/{id}/history/candles/...`) — only needed if we ever build eToro-native watchlist scoring (currently `score_universe=None` in the spec).

## Labels

`etoro`, `follow-up`, `blocked-on-mvp-b-bake`, `architecture-decision-required`

## Related

- Parent commit: `acd3d04` — "eToro client: MVP-B — read paths fixed, write paths stubbed"
- Original bug thread: the `/identity` 404 investigation surfaced the endpoint-mismatch root cause.
- Docs:
  - <https://api-portal.etoro.com/getting-started/authentication>
  - <https://api-portal.etoro.com/guides/market-orders>
  - <https://builders.etoro.com/blog/developers-guide-to-instrument-discovery>
