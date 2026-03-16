import { useEffect, useMemo, useRef, useState } from "react";
import { useLivePrice } from "@/hooks/useLivePrice";
import { authApi, api } from "@/lib/api";
import { formatChangePct, formatPrice } from "@/utils/formatPrice";
import {
  ChevronDown,
  Info,
  Search,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

type Category = "stocks" | "crypto" | "all";

type QuickStatsMap = Record<string, { rsi?: number | null }>;

interface BrandPickerProps {
  exchange: string;
  /** Used for simulator mode max-selection cap. */
  simulatorMode?: boolean;
  selectedSymbols?: string[];
  onChangeSelectedSymbols?: (symbols: string[]) => void;
  /** When user enters symbol manually */
  onManualSymbol?: (symbol: string) => void;
}

const STOCK_BRANDS: Array<{ symbol: string; brand: string }> = [
  { symbol: "AAPL", brand: "Apple" },
  { symbol: "MSFT", brand: "Microsoft" },
  { symbol: "NVDA", brand: "NVIDIA" },
  { symbol: "TSLA", brand: "Tesla" },
  { symbol: "AMZN", brand: "Amazon" },
  { symbol: "GOOGL", brand: "Alphabet" },
  { symbol: "META", brand: "Meta" },
  { symbol: "SPY", brand: "S&P 500 (SPY)" },
  { symbol: "VOO", brand: "Vanguard S&P 500 (VOO)" },
];

const CRYPTO_BRANDS: Array<{ symbol: string; brand: string }> = [
  { symbol: "BTC/USD", brand: "Bitcoin" },
  { symbol: "ETH/USD", brand: "Ethereum" },
  { symbol: "SOL/USD", brand: "Solana" },
  { symbol: "DOGE/USD", brand: "Dogecoin" },
  { symbol: "XRP/USD", brand: "XRP" },
];

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function useFirstOpenTooltip(key: string) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const v = window.localStorage.getItem(key);
    if (!v) {
      setShow(true);
      window.localStorage.setItem(key, "1");
    }
  }, [key]);
  return { show, dismiss: () => setShow(false) };
}

function RSIBadge({ rsi }: { rsi: number | null | undefined }) {
  if (rsi === null || rsi === undefined || Number.isNaN(rsi)) {
    return (
      <span className="rounded-md border border-dark-700 bg-dark-900 px-2 py-0.5 text-[11px] text-dark-300">
        RSI —
      </span>
    );
  }
  const color =
    rsi < 40 ? "border-green-500/30 bg-green-500/10 text-green-300" :
    rsi > 70 ? "border-red-500/30 bg-red-500/10 text-red-300" :
    "border-dark-700 bg-dark-900 text-dark-300";
  return (
    <span className={clsx("rounded-md border px-2 py-0.5 text-[11px]", color)}>
      RSI {Math.round(rsi)}
    </span>
  );
}

function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-xl border border-dark-800 bg-dark-900 p-4">
      <div className="h-4 w-28 rounded bg-dark-800" />
      <div className="mt-3 h-7 w-24 rounded bg-dark-800" />
      <div className="mt-2 h-3 w-20 rounded bg-dark-800" />
      <div className="mt-3 h-4 w-16 rounded bg-dark-800" />
    </div>
  );
}

function BrandCard(props: {
  traderClass: TraderClass;
  symbol: string;
  brand: string;
  exchange: string;
  isSelected: boolean;
  onToggle: () => void;
  rsi?: number | null;
  showVolumeChange?: boolean;
  volumeChangePct?: number | null;
}) {
  const live = useLivePrice(props.symbol);
  const change = formatChangePct(live.changePct);

  const showTicker =
    props.traderClass === "curious_saver" ||
    props.traderClass === "self_taught" ||
    props.traderClass === "experienced" ||
    props.traderClass === "crypto_native";

  const showChangeNumber =
    props.traderClass === "curious_saver" ||
    props.traderClass === "self_taught" ||
    props.traderClass === "experienced" ||
    props.traderClass === "crypto_native";

  const pctText = useMemo(() => {
    if (live.changePct === null) return null;
    if (props.traderClass === "curious_saver") return `${live.changePct.toFixed(1)}%`;
    if (props.traderClass === "self_taught") return `${live.changePct.toFixed(2)}%`;
    if (props.traderClass === "experienced") return `${live.changePct.toFixed(2)}%`;
    if (props.traderClass === "crypto_native") return `${live.changePct.toFixed(2)}%`;
    return null;
  }, [live.changePct, props.traderClass]);

  const arrowOnly = props.traderClass === "complete_novice";

  return (
    <button
      type="button"
      onClick={props.onToggle}
      title={props.traderClass === "complete_novice" ? props.symbol.toUpperCase() : undefined}
      className={clsx(
        "group relative rounded-xl border p-4 text-left transition",
        props.isSelected
          ? "border-brand-500 bg-brand-500/10 ring-2 ring-brand-500/20"
          : "border-dark-800 bg-dark-900 hover:border-dark-700",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-base font-semibold text-white">
            {props.brand}
          </div>
          {showTicker ? (
            <div className="mt-0.5 truncate text-xs text-dark-400">
              {props.symbol.toUpperCase()}
            </div>
          ) : (
            <div className="mt-0.5 text-xs text-dark-400 opacity-0 transition group-hover:opacity-100">
              {props.symbol.toUpperCase()}
            </div>
          )}
        </div>

        {props.traderClass === "self_taught" && <RSIBadge rsi={props.rsi} />}
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-lg font-bold text-white">
            {live.price !== null ? formatPrice(live.price, props.symbol) : "—"}
          </div>
          {(props.traderClass === "experienced" || props.traderClass === "crypto_native") &&
            live.bid !== null &&
            live.ask !== null && (
              <div className="mt-0.5 text-xs text-dark-400">
                {formatPrice(live.bid, props.symbol)} / {formatPrice(live.ask, props.symbol)}
              </div>
            )}
        </div>

        {live.changePct !== null && (
          <div className="flex items-center gap-1">
            {live.changePct >= 0 ? (
              <TrendingUp size={14} style={{ color: change.color }} />
            ) : (
              <TrendingDown size={14} style={{ color: change.color }} />
            )}
            {arrowOnly ? null : (
              <span
                style={{ color: change.color }}
                className="text-sm font-semibold tabular-nums"
              >
                {showChangeNumber ? (pctText ?? change.text) : ""}
              </span>
            )}
          </div>
        )}
      </div>

      {props.traderClass === "crypto_native" && props.showVolumeChange && (
        <div className="mt-2 text-xs text-dark-400">
          Vol 24h:{" "}
          <span className="tabular-nums text-dark-200">
            {props.volumeChangePct === null || props.volumeChangePct === undefined
              ? "—"
              : `${props.volumeChangePct.toFixed(1)}%`}
          </span>
        </div>
      )}

      {!live.isConnected && (
        <div className="mt-2 text-xs text-red-400">Connecting…</div>
      )}
    </button>
  );
}

export default function BrandPicker({
  exchange,
  simulatorMode = false,
  selectedSymbols,
  onChangeSelectedSymbols,
  onManualSymbol,
}: BrandPickerProps) {
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [traderClass, setTraderClass] = useState<TraderClass>("complete_novice");
  const [favourites, setFavourites] = useState<string[]>([]);

  const [category, setCategory] = useState<Category>("stocks");
  const [search, setSearch] = useState("");
  const [showManual, setShowManual] = useState(false);
  const [manualSymbol, setManualSymbol] = useState("");

  const [quickStats, setQuickStats] = useState<QuickStatsMap>({});
  const [fearGreed, setFearGreed] = useState<{ value: number; label: string } | null>(null);
  const [trending, setTrending] = useState<Array<{ symbol: string; brand: string; volume_change_pct?: number | null }>>([]);

  const selections = selectedSymbols ?? [];
  const setSelections = (next: string[]) => {
    onChangeSelectedSymbols?.(next);
  };

  const firstTip = useFirstOpenTooltip("unitrader_brandpicker_first_open_v1");
  const didLockCryptoTab = useRef(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoadingSettings(true);
      try {
        const res = await authApi.getSettings();
        const s = res.data;
        const tc = (s?.trader_class as TraderClass | undefined) ?? "complete_novice";
        const fav = Array.isArray(s?.approved_assets) ? (s.approved_assets as string[]) : [];

        if (!mounted) return;
        setTraderClass(tc);
        setFavourites(fav);

        // Default category by trader class
        if (tc === "self_taught") setCategory("all");
        else if (tc === "crypto_native") setCategory("crypto");
        else setCategory("stocks");
      } catch {
        if (!mounted) return;
        setTraderClass("complete_novice");
      } finally {
        if (mounted) setLoadingSettings(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  // crypto_native: lock crypto tab on first load only
  useEffect(() => {
    if (traderClass !== "crypto_native") return;
    if (didLockCryptoTab.current) return;
    setCategory("crypto");
    didLockCryptoTab.current = true;
  }, [traderClass]);

  const featuredRow = useMemo(() => {
    if (traderClass === "complete_novice") {
      const picks = favourites.slice(0, 3).map((sym) => ({ symbol: sym, brand: sym }));
      return picks.length
        ? { title: "Apex's picks for you", items: picks }
        : null;
    }
    if (traderClass === "curious_saver") {
      return {
        title: "Popular with UK investors",
        items: [
          { symbol: "SPY", brand: "S&P 500 (SPY)" },
          { symbol: "VOO", brand: "Vanguard S&P 500 (VOO)" },
          { symbol: "AAPL", brand: "Apple" },
          { symbol: "MSFT", brand: "Microsoft" },
        ],
      };
    }
    if (traderClass === "crypto_native") {
      return trending.length
        ? { title: "Trending this week", items: trending }
        : { title: "Trending this week", items: CRYPTO_BRANDS.slice(0, 4) };
    }
    return null;
  }, [traderClass, favourites, trending]);

  const gridItems = useMemo(() => {
    const base =
      category === "stocks"
        ? STOCK_BRANDS
        : category === "crypto"
          ? CRYPTO_BRANDS
          : [...STOCK_BRANDS, ...CRYPTO_BRANDS];

    const q = search.trim().toLowerCase();
    if (!q) return base;
    return base.filter(
      (x) =>
        x.symbol.toLowerCase().includes(q) || x.brand.toLowerCase().includes(q),
    );
  }, [category, search]);

  // self_taught: load RSI quick stats for visible symbols
  useEffect(() => {
    if (traderClass !== "self_taught") return;
    if (!gridItems.length) return;
    const symbols = gridItems.slice(0, 20).map((x) => x.symbol).join(",");

    let mounted = true;
    (async () => {
      try {
        const res = await api.get("/api/trading/quick-stats", { params: { symbols } });
        const data = res.data?.data ?? res.data;
        if (!mounted) return;
        setQuickStats((data ?? {}) as QuickStatsMap);
      } catch {
        if (!mounted) return;
        setQuickStats({});
      }
    })();
    return () => {
      mounted = false;
    };
  }, [traderClass, gridItems]);

  // crypto_native: fear & greed widget
  useEffect(() => {
    if (traderClass !== "crypto_native") return;
    let mounted = true;
    (async () => {
      try {
        const res = await api.get("/api/trading/fear-greed");
        const d = res.data?.data ?? res.data;
        const value = Number(d?.value ?? d?.score ?? d?.fear_greed ?? NaN);
        const label = String(d?.label ?? (value < 50 ? "Fear" : "Greed"));
        if (!mounted) return;
        if (!Number.isFinite(value)) return;
        setFearGreed({ value, label });
      } catch {
        if (!mounted) return;
        setFearGreed(null);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [traderClass]);

  // crypto_native: trending movers (best-effort; endpoint may not exist yet)
  useEffect(() => {
    if (traderClass !== "crypto_native") return;
    let mounted = true;
    (async () => {
      try {
        const res = await api.get("/api/trading/trending-week");
        const d = res.data?.data ?? res.data;
        const items = Array.isArray(d) ? d : Array.isArray(d?.items) ? d.items : [];
        const top = items
          .slice(0, 4)
          .map((x: any) => ({
            symbol: String(x.symbol ?? ""),
            brand: String(x.brand ?? x.symbol ?? ""),
            volume_change_pct:
              x.volume_change_pct === null || x.volume_change_pct === undefined
                ? null
                : Number(x.volume_change_pct),
          }))
          .filter((x: any) => x.symbol);
        if (!mounted) return;
        setTrending(top);
      } catch {
        if (!mounted) return;
        setTrending([]);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [traderClass]);

  const allowBrandPickerPrimary =
    traderClass !== "semi_institutional" && traderClass !== "experienced";

  const handleToggle = (symbol: string) => {
    if (!onChangeSelectedSymbols) {
      onManualSymbol?.(symbol);
      return;
    }
    const exists = selections.includes(symbol);
    const next = exists ? selections.filter((s) => s !== symbol) : [...selections, symbol];
    if (simulatorMode && next.length > 3) return;
    setSelections(next);
  };

  if (traderClass === "semi_institutional") {
    return (
      <div className="space-y-3">
        <div className="text-sm font-semibold text-white">Analyse multiple symbols</div>
        <textarea
          value={manualSymbol}
          onChange={(e) => setManualSymbol(e.target.value)}
          placeholder="AAPL, MSFT, NVDA, BTC/USD (comma-separated)"
          className="min-h-[96px] w-full rounded-xl border border-dark-800 bg-dark-900 px-4 py-3 text-sm text-white outline-none placeholder:text-dark-500 focus:border-brand-500/60"
        />
        <button
          type="button"
          onClick={async () => {
            const symbols = manualSymbol
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean);
            if (!symbols.length) return;
            try {
              await api.get("/api/trading/bulk-analyze", { params: { symbols: symbols.join(",") } });
            } catch {
              // endpoint may not exist yet; no-op
            }
          }}
          className="btn w-full"
        >
          Analyse all
        </button>
      </div>
    );
  }

  if (traderClass === "experienced" && !allowBrandPickerPrimary) {
    // This branch is intentionally unreachable with current allowBrandPickerPrimary;
    // kept for clarity if you later decide to render this component directly.
  }

  return (
    <div className="space-y-4">
      {loadingSettings ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : (
        <>
          {traderClass === "crypto_native" && fearGreed && (
            <div
              className={clsx(
                "rounded-xl border bg-dark-900 p-4",
                fearGreed.value < 50
                  ? "border-red-500/20"
                  : "border-green-500/20",
              )}
            >
              <div className="text-xs text-dark-400">Market</div>
              <div
                className={clsx(
                  "mt-1 text-sm font-semibold",
                  fearGreed.value < 50 ? "text-red-300" : "text-green-300",
                )}
              >
                {fearGreed.label} ({fearGreed.value})
              </div>
            </div>
          )}

          {traderClass === "complete_novice" && firstTip.show && (
            <div className="flex items-start gap-2 rounded-xl border border-dark-800 bg-dark-900 p-4">
              <Info size={16} className="mt-0.5 text-brand-300" />
              <div className="flex-1 text-sm text-dark-200">
                Tap a company you believe in to get started
              </div>
              <button
                type="button"
                onClick={firstTip.dismiss}
                className="text-xs text-dark-400 hover:text-white"
              >
                Got it
              </button>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="relative w-full sm:w-72">
              <Search size={16} className="absolute left-3 top-3 text-dark-500" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search brands or symbols"
                className="w-full rounded-xl border border-dark-800 bg-dark-900 py-2 pl-10 pr-3 text-sm text-white outline-none placeholder:text-dark-500 focus:border-brand-500/60"
              />
            </div>

            <div className="flex items-center gap-2">
              <div className="inline-flex rounded-xl border border-dark-800 bg-dark-900 p-1">
                <button
                  type="button"
                  disabled={traderClass === "crypto_native" && !didLockCryptoTab.current}
                  onClick={() => setCategory("stocks")}
                  className={clsx(
                    "rounded-lg px-3 py-1.5 text-xs font-semibold",
                    category === "stocks" ? "bg-dark-800 text-white" : "text-dark-300 hover:text-white",
                  )}
                >
                  Stocks
                </button>
                <button
                  type="button"
                  onClick={() => setCategory("crypto")}
                  className={clsx(
                    "rounded-lg px-3 py-1.5 text-xs font-semibold",
                    category === "crypto" ? "bg-dark-800 text-white" : "text-dark-300 hover:text-white",
                  )}
                >
                  Crypto
                </button>
                <button
                  type="button"
                  onClick={() => setCategory("all")}
                  className={clsx(
                    "rounded-lg px-3 py-1.5 text-xs font-semibold",
                    category === "all" ? "bg-dark-800 text-white" : "text-dark-300 hover:text-white",
                  )}
                >
                  All
                </button>
              </div>

              <button
                type="button"
                onClick={() => setShowManual((v) => !v)}
                className="inline-flex items-center gap-1 rounded-xl border border-dark-800 bg-dark-900 px-3 py-2 text-xs font-semibold text-dark-200 hover:text-white"
              >
                Enter symbol manually <ChevronDown size={14} className={showManual ? "rotate-180" : ""} />
              </button>
            </div>
          </div>

          {showManual && (
            <div className="flex flex-col gap-2 rounded-xl border border-dark-800 bg-dark-900 p-4 sm:flex-row sm:items-center">
              <input
                value={manualSymbol}
                onChange={(e) => setManualSymbol(e.target.value)}
                placeholder="e.g. AAPL, BTC/USD, EUR_USD"
                className="w-full flex-1 rounded-xl border border-dark-800 bg-dark-950 px-3 py-2 text-sm text-white outline-none placeholder:text-dark-500 focus:border-brand-500/60"
              />
              <button
                type="button"
                onClick={() => {
                  if (!manualSymbol.trim()) return;
                  onManualSymbol?.(manualSymbol.trim());
                }}
                className="btn"
              >
                Use symbol
              </button>
            </div>
          )}

          {featuredRow && traderClass !== "self_taught" && traderClass !== "experienced" && (
            <div className="space-y-3">
              <div className="text-sm font-semibold text-white">{featuredRow.title}</div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {featuredRow.items.map((it) => (
                  <BrandCard
                    key={`${featuredRow.title}-${it.symbol}`}
                    traderClass={traderClass}
                    symbol={it.symbol}
                    brand={it.brand}
                    exchange={exchange}
                    isSelected={selections.includes(it.symbol)}
                    onToggle={() => handleToggle(it.symbol)}
                    showVolumeChange={traderClass === "crypto_native"}
                    volumeChangePct={(it as any).volume_change_pct ?? null}
                  />
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {gridItems.map((it) => (
              <BrandCard
                key={it.symbol}
                traderClass={traderClass}
                symbol={it.symbol}
                brand={it.brand}
                exchange={exchange}
                isSelected={selections.includes(it.symbol)}
                onToggle={() => handleToggle(it.symbol)}
                rsi={quickStats?.[it.symbol]?.rsi ?? null}
                showVolumeChange={traderClass === "crypto_native"}
              />
            ))}
          </div>

          {simulatorMode && (
            <div className="text-xs text-dark-400">
              Simulator mode: select up to 3 symbols.
            </div>
          )}
        </>
      )}
    </div>
  );
}
