# Roadmap

Living document. One-line phase titles, notes underneath. Ordered by commit
arrival, not priority.

## Phase B1 — eToro (in progress)

Scaffolding, Trust Ladder gating, spec-driven wizard, Apex chat offer,
one-time offer card on `/trade`. Status: all commits through Session 2
Commit 5 shipped. Feature flag `FEATURE_ETORO_ENABLED` remains `false` until
Supabase migrations 005 and 006 are applied in prod.

### Turning eToro on in an environment

eToro is hidden from every UI surface (`GET /api/exchanges/list` filters it
out, the Apex onboarding prompt skips the offer block, the `/trade` offer
card returns `{"show": false}`) until the backend flag flips. To enable it
in a given environment:

1. Apply the Supabase migrations in order:
   * `deployment/migrations/005_etoro_support.sql` — adds
     `exchange_api_keys.etoro_environment`.
   * `deployment/migrations/006_etoro_offer_card.sql` — adds
     `user_settings.etoro_offer_dismissed_at`.
2. Set `FEATURE_ETORO_ENABLED=true` in the backend environment (`.env`
   for local dev, or the hosting provider's env config for staging/prod).
3. Restart the backend (the flag is read on startup via
   `config.Settings`).
4. Hard-refresh the frontend so it re-fetches `/api/exchanges/list` and
   `/api/etoro/offer-card` against the now-unfiltered responses.

Migrations MUST land before the flag flips — otherwise connect attempts
fail with a missing-column error at insert time. If you turn the flag
off again, existing eToro keys remain in the DB untouched; they simply
stop being surfaced to users.

## Phase B2 — Revolut X

TBD.

## Phase B1.5 — Registry-drive the remaining UI surfaces

`ExchangeConnections.tsx` was migrated to `GET /api/exchanges/list` in
Commit 6. The following still ship hardcoded exchange lists and should be
migrated next time we touch them:

- `frontend/pages/connect-exchange.tsx` — its own `const EXCHANGES = [...]`
  array. Standalone page still works; the `lib/exchangeApiKeyGuides.ts`
  module stays on disk solely to keep this page compiling.
- `frontend/app/trade/page.tsx` — prose sentence listing
  "Alpaca, Coinbase, Binance, Kraken, and OANDA" in the empty-state card.
  Will fall out of date when new exchanges register.
- `frontend/components/AccountDashboard.tsx` — a `type Exchange` string
  literal union used for display; does not include `etoro`.

None are blocking. Delete `lib/exchangeApiKeyGuides.ts` only after the
first bullet above is fixed.

## Phase B3 — Unify web Apex with Telegram/WhatsApp Apex

Replace `frontend/components/onboarding/ApexOnboardingChat.tsx` (the
quick-reply state machine) with a real `chatApi.sendMessage` integration so
web users get the same conversational Apex that Telegram/WhatsApp users
already have. Today web users see a disguised wizard — not conversational
Apex. Known inconsistency, deferred until after Revolut X.

Scope when unblocked:
- Render Claude replies as bot bubbles; free-text input box.
- Route `action: open_exchange_wizard` from the backend onboarding agent
  directly into `ExchangeConnectWizard` with `presetEnvironment` (the
  backend emission already works; only the web consumer is missing).
- Retire the stage-machine `BotOnboardingChat` component once parity is
  confirmed.
