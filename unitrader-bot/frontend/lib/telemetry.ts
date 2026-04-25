// Stub telemetry bus. Swap implementation for PostHog/Segment/etc. without touching call sites.
//
// Design rules:
//  * Signature matches PostHog — `trackEvent(name, props)`. Vendor swap is a 3-line
//    change inside this file, zero call-site diffs.
//  * Event names are a typed union so misspellings are compile errors.
//  * Every event is auto-enriched with user_id, trader_class, and timestamp.
//    Call sites only pass event-specific props.
//  * Dev = console.log. Prod = no-op (until a vendor is wired in).
//  * Tolerates missing enrichment context — events still fire with nulls so we
//    don't lose signal while auth is booting.

export type TelemetryEventName =
  | "exchange_wizard_opened"
  | "exchange_wizard_opened_from_apex"
  | "exchange_wizard_step_advanced"
  | "exchange_wizard_env_selected"
  | "exchange_wizard_submit_attempted"
  | "exchange_wizard_revolutx_keypair_generated"
  | "exchange_wizard_revolutx_keypair_failed"
  | "exchange_wizard_connected"
  | "exchange_wizard_failed"
  | "exchange_wizard_abandoned"
  | "etoro_offer_card_shown"
  | "etoro_offer_card_accepted"
  | "etoro_offer_card_dismissed";

interface EnrichmentContext {
  userId?: string | null;
  traderClass?: string | null;
}

let _ctx: EnrichmentContext = {};

/**
 * Set persistent context used to enrich every subsequent event.
 * Call once near the top of the app (e.g. where Clerk's useUser() is in scope)
 * and again when trader_class becomes available from user-settings.
 */
export function configureTelemetry(ctx: EnrichmentContext): void {
  _ctx = { ..._ctx, ...ctx };
}

/**
 * Fire a telemetry event. Safe to call before configureTelemetry — missing
 * enrichment fields resolve to `null` instead of blocking the event.
 */
export function trackEvent(
  name: TelemetryEventName,
  props: Record<string, unknown> = {},
): void {
  const payload = {
    name,
    ...props,
    user_id: _ctx.userId ?? null,
    trader_class: _ctx.traderClass ?? null,
    ts: new Date().toISOString(),
  };

  if (process.env.NODE_ENV !== "production") {
    // eslint-disable-next-line no-console
    console.log("[telemetry]", payload);
    return;
  }

  // TODO: swap for real vendor here — call sites stay unchanged.
  //   e.g. posthog.capture(name, payload); or analytics.track(name, payload);
}
