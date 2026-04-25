/**
 * frontend/lib/exchangeVisuals.ts
 *
 * Small client-side palette that maps an exchange id or asset class to
 * the colours we render in the Settings → Exchange Connections list.
 * Intentionally NOT dependent on any logo asset — just brand-adjacent
 * hex values so the list stops looking like "letter-in-a-grey-circle".
 *
 * Keep this file framework-free (no React imports) so it can be reused
 * by future pages (e.g. the Phase B1.5 /connect-exchange migration)
 * without dragging in JSX.
 */

export interface ExchangeVisual {
  /** Background colour for the brand tile, expressed as a Tailwind-
   *  arbitrary-value string (e.g. "bg-[#fbbf24]/15"). */
  tileBg: string;
  /** Foreground colour for the initial letter inside the tile. */
  tileFg: string;
}

/**
 * Brand-adjacent colours. No logo downloads, no licensing exposure —
 * just the hue each brand is commonly associated with (Alpaca = warm
 * gold, Binance = yellow, Coinbase = Coinbase blue, etc.). The `/15`
 * suffix lands them at ~15% opacity so the tile reads as tinted, not
 * solid.
 */
const EXCHANGE_VISUAL: Record<string, ExchangeVisual> = {
  alpaca:   { tileBg: "bg-[#fbbf24]/15", tileFg: "text-[#fbbf24]" },
  binance:  { tileBg: "bg-[#f0b90b]/15", tileFg: "text-[#f0b90b]" },
  coinbase: { tileBg: "bg-[#0052ff]/20", tileFg: "text-[#60a5fa]" },
  kraken:   { tileBg: "bg-[#5841d8]/20", tileFg: "text-[#a78bfa]" },
  oanda:    { tileBg: "bg-[#e31837]/15", tileFg: "text-[#f87171]" },
  etoro:    { tileBg: "bg-[#13c636]/15", tileFg: "text-[#13c636]" },
  revolutx: { tileBg: "bg-[#7c3aed]/15", tileFg: "text-[#a78bfa]" },
};

export function getExchangeVisual(id: string): ExchangeVisual {
  return (
    EXCHANGE_VISUAL[id.toLowerCase()] ?? {
      tileBg: "bg-dark-800",
      tileFg: "text-dark-400",
    }
  );
}

// ─── Asset-class dots ────────────────────────────────────────────────────────

/**
 * Maps an asset-class string (as returned by the backend registry's
 * `asset_classes` / `primary_asset_class` fields — values like
 * "stocks", "crypto", "forex", "commodities", "etfs") to the colour of
 * the small dot rendered next to the tagline. Keeps the mapping open:
 * unknown classes fall back to a neutral grey dot.
 */
const ASSET_CLASS_COLOR: Record<string, string> = {
  stocks:      "#60a5fa", // blue
  etfs:        "#60a5fa", // share the stocks hue
  crypto:      "#fb923c", // orange
  forex:       "#a78bfa", // purple
  commodities: "#fbbf24", // amber
};

export function assetClassColor(cls: string): string {
  return ASSET_CLASS_COLOR[cls.toLowerCase()] ?? "#64748b";
}

/**
 * Returns a de-duplicated, priority-ordered list of up to `max` colours
 * for the given asset classes. Used to render a tiny stacked dot cluster
 * on rows where an exchange covers multiple asset classes (e.g. eToro).
 */
export function assetClassColors(classes: string[], max = 3): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of classes) {
    const color = assetClassColor(c);
    if (seen.has(color)) continue;
    seen.add(color);
    out.push(color);
    if (out.length >= max) break;
  }
  return out;
}

// ─── Connection-state left bar ───────────────────────────────────────────────

/**
 * Given the mix of connected accounts for an exchange, return the
 * Tailwind class(es) for the 3px coloured bar rendered on the left edge
 * of the card. Empty string when the exchange isn't connected.
 *
 *   disconnected     → ""            (no bar)
 *   paper only       → amber bar
 *   live only        → brand-green bar
 *   mixed paper+live → gradient
 */
export function connectionBarClass(
  connections: Array<{ is_paper: boolean }>,
): string {
  if (connections.length === 0) return "";
  const hasPaper = connections.some((c) => c.is_paper);
  const hasLive  = connections.some((c) => !c.is_paper);
  if (hasPaper && hasLive) {
    return "bg-gradient-to-b from-amber-400 to-brand-400";
  }
  if (hasLive) return "bg-brand-400";
  return "bg-amber-400";
}
