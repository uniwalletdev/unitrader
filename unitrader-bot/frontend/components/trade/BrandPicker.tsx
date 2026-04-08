import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLivePrice } from "@/hooks/useLivePrice";
import { authApi, api } from "@/lib/api";
import { fetchSpotPriceViaOhlcv } from "@/lib/fetchSpotPrice";
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
  /** For stock/ETF price prefix on cards (default "$") */
  currencySymbol?: string;
  tradingAccountId?: string | null;
  /** If provided, avoids fetching settings on mount. */
  traderClass?: TraderClass;
  /** If provided, avoids fetching settings on mount. */
  favourites?: string[];
  /** Used for simulator mode max-selection cap. */
  simulatorMode?: boolean;
  /** `single` = one symbol at a time (manual trade). `multi` = watchlist-style (default). */
  selectionMode?: "single" | "multi";
  selectedSymbols?: string[];
  onChangeSelectedSymbols?: (symbols: string[]) => void;
  /** When user enters symbol manually */
  onManualSymbol?: (symbol: string) => void;
  /** Asset-class-first override — locks the category tab to the given asset class. */
  assetClass?: "stocks" | "crypto" | "forex";
}

// Display-name lookup for AI-returned symbols — not a tradeable list
export const BRAND_MAP: Record<string, string> = {
  AAPL: "Apple", MSFT: "Microsoft", NVDA: "NVIDIA", TSLA: "Tesla",
  AMZN: "Amazon", GOOGL: "Alphabet", META: "Meta",
  SPY: "S&P 500 ETF", VOO: "Vanguard S&P 500",
  NFLX: "Netflix", ORCL: "Oracle", AMD: "AMD", INTC: "Intel", CRM: "Salesforce",
  "BTC/USD": "Bitcoin", BTCUSDT: "Bitcoin",
  XBTUSD: "Bitcoin",
  "ETH/USD": "Ethereum", ETHUSDT: "Ethereum",
  ETHUSD: "Ethereum",
  "SOL/USD": "Solana", SOLUSDT: "Solana",
  SOLUSD: "Solana",
  "DOGE/USD": "Dogecoin", DOGEUSDT: "Dogecoin",
  XDGUSD: "Dogecoin",
  "XRP/USD": "XRP", XRPUSDT: "XRP",
  BNBUSDT: "BNB", ADAUSDT: "Cardano", DOTUSDT: "Polkadot",
  EUR_USD: "EUR/USD", GBP_USD: "GBP/USD", USD_JPY: "USD/JPY",
  AUD_USD: "AUD/USD", USD_CAD: "USD/CAD",
};

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/** Human-readable asset line for analysis UI (e.g. NVIDIA — NVDA). */
export function displayBrandLine(symbol: string): { name: string; ticker: string } {
  const ticker = symbol.trim();
  if (!ticker) return { name: "", ticker: "" };
  const upper = ticker.toUpperCase();
  const name = BRAND_MAP[ticker] ?? BRAND_MAP[upper] ?? ticker;
  return { name, ticker };
}

/** Classify API resolved_exchange into picker buckets (stocks vs crypto list). */
function bucketResolvedExchange(resolved: string): "alpaca" | "oanda" | "crypto" {
  const x = resolved.toLowerCase();
  if (x === "alpaca") return "alpaca";
  if (x === "oanda") return "oanda";
  return "crypto";
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
  currencySymbol?: string;
  tradingAccountId?: string | null;
  isSelected: boolean;
  onToggle: () => void;
  onWsRemount?: () => void;
  rsi?: number | null;
  showVolumeChange?: boolean;
  volumeChangePct?: number | null;
}) {
  const live = useLivePrice(props.symbol, { tradingAccountId: props.tradingAccountId });
  const [restPrice, setRestPrice] = useState<number | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [restFetching, setRestFetching] = useState(false);

  const effectivePrice = live.price ?? restPrice;

  useEffect(() => {
    setRestPrice(null);
    setLoadFailed(false);
    setRestFetching(false);
  }, [props.symbol]);

  useEffect(() => {
    if (effectivePrice !== null) {
      setLoadFailed(false);
      return;
    }
    const timer = setTimeout(() => setLoadFailed(true), 8000);
    return () => clearTimeout(timer);
  }, [effectivePrice, props.symbol]);

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
  const cur = props.currencySymbol ?? "$";

  const retryFetch = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setLoadFailed(false);
    setRestPrice(null);
    setRestFetching(true);
    try {
      const p = await fetchSpotPriceViaOhlcv(props.symbol);
      if (p !== null) {
        setRestPrice(p);
      } else {
        props.onWsRemount?.();
      }
    } finally {
      setRestFetching(false);
    }
  };

  const onCardKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      props.onToggle();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={props.onToggle}
      onKeyDown={onCardKeyDown}
      title={props.traderClass === "complete_novice" ? props.symbol.toUpperCase() : undefined}
      className={clsx(
        "group relative cursor-pointer rounded-xl border p-4 text-left transition outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40",
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
          <div className="flex items-center gap-2 text-lg font-bold text-white">
            {effectivePrice !== null ? (
              <span className="tabular-nums">{formatPrice(effectivePrice, props.symbol, cur)}</span>
            ) : loadFailed ? (
              <>
                <span className="tabular-nums text-dark-400">--</span>
                <button
                  type="button"
                  onClick={retryFetch}
                  disabled={restFetching}
                  title="Retry"
                  className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-dark-600 bg-dark-800 text-sm text-dark-300 hover:border-brand-500/40 hover:text-brand-300 disabled:opacity-50"
                >
                  ↻
                </button>
              </>
            ) : (
              <span className="text-sm font-normal text-dark-500">Connecting…</span>
            )}
          </div>
          {(props.traderClass === "experienced" || props.traderClass === "crypto_native") &&
            live.bid !== null &&
            live.ask !== null && (
              <div className="mt-0.5 text-xs text-dark-400">
                {formatPrice(live.bid, props.symbol, cur)} / {formatPrice(live.ask, props.symbol, cur)}
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

    </div>
  );
}

export default function BrandPicker({
  exchange,
  currencySymbol = "$",
  tradingAccountId,
  traderClass: traderClassProp,
  favourites: favouritesProp,
  simulatorMode = false,
  selectionMode = "multi",
  selectedSymbols,
  onChangeSelectedSymbols,
  onManualSymbol,
  assetClass: assetClassProp,
}: BrandPickerProps) {
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [traderClass, setTraderClass] = useState<TraderClass>("complete_novice");
  const [favourites, setFavourites] = useState<string[]>([]);
  /** Bumps React key on BrandCard to re-run useLivePrice (fresh WebSocket) after failed REST fallback. */
  const [wsRemountEpoch, setWsRemountEpoch] = useState<Record<string, number>>({});
  const bumpWsForSymbol = useCallback((sym: string) => {
    setWsRemountEpoch((p) => ({ ...p, [sym]: (p[sym] ?? 0) + 1 }));
  }, []);

  const [category, setCategory] = useState<Category>("stocks");
  const [search, setSearch] = useState("");
  const [showManual, setShowManual] = useState(false);
  const [manualSymbol, setManualSymbol] = useState("");

  const [quickStats, setQuickStats] = useState<QuickStatsMap>({});
  const [fearGreed, setFearGreed] = useState<{ value: number; label: string } | null>(null);
  const [trending, setTrending] = useState<Array<{ symbol: string; brand: string; volume_change_pct?: number | null }>>([]);
  const [aiFeatureItems, setAiFeatureItems] = useState<Array<{ symbol: string; brand: string }> | null>(null);

  // Tier-1: instant symbol list from /exchange-assets (no AI, <100ms)
  const [tier1StockItems, setTier1StockItems] = useState<Array<{ symbol: string; brand: string }> | null>(null);
  const [tier1CryptoItems, setTier1CryptoItems] = useState<Array<{ symbol: string; brand: string }> | null>(null);
  const [tier1Loading, setTier1Loading] = useState(true);

  // Tier-2: AI-ranked picks from /market-top (slow, enhances tier-1 in background)
  const [liveStockItems, setLiveStockItems] = useState<Array<{ symbol: string; brand: string }> | null>(null);
  const [liveCryptoItems, setLiveCryptoItems] = useState<Array<{ symbol: string; brand: string }> | null>(null);
  const [aiEnhanced, setAiEnhanced] = useState(false);
  /** From API (`resolved_exchange`) so tabs/lists match the linked account even if parent `exchange` lags. */
  const [resolvedExchange, setResolvedExchange] = useState<string | null>(null);
  const [remoteSearchItems, setRemoteSearchItems] = useState<Array<{ symbol: string; brand: string }> | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);

  const selections = selectedSymbols ?? [];
  const setSelections = (next: string[]) => {
    onChangeSelectedSymbols?.(next);
  };

  useEffect(() => {
    setResolvedExchange(null);
    setRemoteSearchItems(null);
  }, [exchange, tradingAccountId]);

  const firstTip = useFirstOpenTooltip("unitrader_brandpicker_first_open_v1");
  const didLockCryptoTab = useRef(false);
  const exchangeTrimmed = (exchange || "").trim();
  const effectiveLower = (resolvedExchange ?? exchange ?? "").toLowerCase();
  const coinbaseMode = effectiveLower === "coinbase";
  const binanceMode = effectiveLower === "binance";
  const krakenMode = effectiveLower === "kraken";
  const oandaMode = effectiveLower === "oanda";
  const cryptoOnly = coinbaseMode || binanceMode || krakenMode;
  const forexOnly = oandaMode;
  const stocksOnly = effectiveLower === "alpaca";
  const displayExchange = resolvedExchange ?? exchange;

  // Asset-class prop from parent (multi-exchange architecture)

  const allowedCategories: Category[] = useMemo(() => {
    if (assetClassProp === "crypto") return ["crypto"];
    if (assetClassProp === "forex" || assetClassProp === "stocks") return ["stocks"];
    if (cryptoOnly) return ["crypto"];
    if (forexOnly) return ["stocks"]; // OANDA assets are treated as non-crypto list in this picker
    if (stocksOnly) return ["stocks"];
    return ["stocks", "crypto", "all"];
  }, [assetClassProp, cryptoOnly, forexOnly, stocksOnly]);

  useEffect(() => {
    if (!allowedCategories.includes(category)) {
      setCategory(allowedCategories[0] ?? "stocks");
    }
  }, [allowedCategories, category]);

  useEffect(() => {
    // If parent already provided settings, skip the extra API call.
    if (traderClassProp || favouritesProp) {
      const tc = traderClassProp ?? "complete_novice";
      const fav = favouritesProp ?? [];
      setTraderClass(tc);
      setFavourites(fav);
      if (tc === "self_taught") setCategory("all");
      else if (tc === "crypto_native") setCategory("crypto");
      else setCategory("stocks");
      setLoadingSettings(false);
      return;
    }

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
  }, [traderClassProp, favouritesProp]);

  // crypto_native: lock crypto tab on first load only
  useEffect(() => {
    if (traderClass !== "crypto_native") return;
    if (didLockCryptoTab.current) return;
    setCategory("crypto");
    didLockCryptoTab.current = true;
  }, [traderClass]);

  // Crypto venues: crypto only (stocks require Alpaca connection)
  useEffect(() => {
    if (!cryptoOnly) return;
    if (category === "stocks") setCategory("crypto");
  }, [cryptoOnly, category]);

  // No exchange scope yet — do not leave tier1Loading stuck at initial true (parent still resolving account).
  useEffect(() => {
    if (exchangeTrimmed) return;
    setTier1Loading(false);
    setTier1StockItems(null);
    setTier1CryptoItems(null);
  }, [exchangeTrimmed]);

  // novice / saver: fetch live AI picks to power the featured row
  useEffect(() => {
    if (traderClass !== "complete_novice" && traderClass !== "curious_saver") return;
    // Backend requires trading_account_id; skip until we have it.
    if (!tradingAccountId) return;
    let mounted = true;
    api.get("/api/trading/ai-picks", { params: { limit: 4, trading_account_id: tradingAccountId } })
      .then((res) => {
        const picks = (res.data?.data || []) as Array<{ symbol: string }>;
        const items = picks
          .map((p) => ({ symbol: p.symbol, brand: BRAND_MAP[p.symbol] ?? p.symbol }))
          .filter((x) => x.symbol);
        if (mounted && items.length >= 2) setAiFeatureItems(items);
      })
      .catch(() => {});
    return () => { mounted = false; };
  }, [traderClass, tradingAccountId]);

  // Tier-1: fetch instant symbol list (no AI) — populates grid in <100ms
  useEffect(() => {
    let mounted = true;
    const mapItem = (d: any) => ({
      symbol: d.symbol as string,
      brand: (d.label || BRAND_MAP[d.symbol as string] || d.symbol) as string,
    });
    const ex = (exchange || "").toLowerCase();
    if (!ex) return () => { mounted = false; };
    setTier1Loading(true);
    setTier1StockItems(null);
    setTier1CryptoItems(null);
    const limit =
      ex === "alpaca" ? 9 :
      ex === "oanda" ? 8 :
      12; // crypto exchange (coinbase/binance/kraken) default

    api
      .get("/api/trading/exchange-assets", {
        params: {
          exchange: ex,
          limit,
          ...(tradingAccountId ? { trading_account_id: tradingAccountId } : {}),
        },
      })
      .then((res) => {
        if (!mounted) return;
        const items = (res.data?.data || []).map(mapItem);
        if (ex === "alpaca") {
          setTier1StockItems(items);
          setTier1CryptoItems([]);
        } else if (ex === "oanda") {
          setTier1StockItems(items);
          setTier1CryptoItems([]);
        } else {
          setTier1CryptoItems(items);
          setTier1StockItems([]);
        }
      })
      .catch(() => {
        if (!mounted) return;
        setTier1StockItems([]);
        setTier1CryptoItems([]);
      })
      .finally(() => {
        if (mounted) setTier1Loading(false);
      });
    return () => { mounted = false; };
  }, [exchange, tradingAccountId]);

  // Tier-2: fetch AI-ranked picks in background — silently enhances the grid
  useEffect(() => {
    let mounted = true;
    const mapItem = (d: any) => ({
      symbol: d.symbol as string,
      brand: (d.label || BRAND_MAP[d.symbol as string] || d.symbol) as string,
    });
    const ex = (exchange || "").toLowerCase();
    if (!ex) return () => { mounted = false; };
    const limit =
      ex === "alpaca" ? 9 :
      ex === "oanda" ? 8 :
      12;

    api
      .get("/api/trading/market-top", {
        params: {
          exchange: ex,
          limit,
          ...(tradingAccountId ? { trading_account_id: tradingAccountId } : {}),
        },
      })
      .then((res) => {
        if (!mounted) return;
        const rex = String(res.data?.resolved_exchange ?? ex).toLowerCase();
        setResolvedExchange(rex);
        const items = (res.data?.data || []).map(mapItem);
        const bucket = bucketResolvedExchange(rex);
        if (bucket === "alpaca") {
          setLiveStockItems(items);
          setLiveCryptoItems([]);
        } else if (bucket === "oanda") {
          setLiveStockItems(items);
          setLiveCryptoItems([]);
        } else {
          setLiveCryptoItems(items);
          setLiveStockItems([]);
        }
        setAiEnhanced(true);
      })
      .catch(() => {
        if (!mounted) return;
        // Keep tier-1 items on tier-2 failure — no disruption to user
      })
      .finally(() => {});
    return () => { mounted = false; };
  }, [exchange, tradingAccountId]);

  const aiFeatureItemsForExchange = useMemo(() => {
    if (!aiFeatureItems || aiFeatureItems.length < 2) return null;
    const eff = effectiveLower;
    if (eff === "coinbase" || eff === "binance" || eff === "kraken") {
      const filtered = aiFeatureItems.filter((it) => {
        const s = it.symbol.trim();
        if (s.includes("/")) return true;
        if (/USDT$|BUSD$/i.test(s)) return true;
        return !/^[A-Za-z]{1,5}$/.test(s);
      });
      return filtered.length >= 2 ? filtered : null;
    }
    return aiFeatureItems;
  }, [aiFeatureItems, effectiveLower]);

  const featuredRow = useMemo(() => {
    if (traderClass === "complete_novice") {
      if (aiFeatureItemsForExchange && aiFeatureItemsForExchange.length >= 2) {
        return { title: "AI's picks right now", items: aiFeatureItemsForExchange };
      }
      const picks = favourites.slice(0, 3).map((sym) => ({ symbol: sym, brand: BRAND_MAP[sym] ?? sym }));
      return picks.length ? { title: "Unitrader's picks for you", items: picks } : null;
    }
    if (traderClass === "curious_saver") {
      if (aiFeatureItemsForExchange && aiFeatureItemsForExchange.length >= 2) {
        return { title: "Best opportunities right now", items: aiFeatureItemsForExchange };
      }
      return null;
    }
    if (traderClass === "crypto_native") {
      return trending.length ? { title: "Trending this week", items: trending } : null;
    }
    return null;
  }, [traderClass, favourites, trending, aiFeatureItemsForExchange]);

  const baseList = useMemo(() => {
    const stocks = liveStockItems ?? tier1StockItems ?? [];
    const crypto = liveCryptoItems ?? tier1CryptoItems ?? [];
    if (category === "stocks") return stocks;
    if (category === "crypto") return crypto;
    return [...stocks, ...crypto];
  }, [category, liveStockItems, liveCryptoItems, tier1StockItems, tier1CryptoItems]);

  const localFiltered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return baseList;
    return baseList.filter(
      (x) =>
        x.symbol.toLowerCase().includes(q) || x.brand.toLowerCase().includes(q),
    );
  }, [baseList, search]);

  const runSymbolSearch = useCallback(async () => {
    const q = search.trim();
    if (q.length < 1) {
      setRemoteSearchItems(null);
      return;
    }
    setSearchLoading(true);
    try {
      const exForSearch = (resolvedExchange ?? exchange ?? "alpaca").toLowerCase();
      const res = await api.get("/api/trading/symbol-search", {
        params: {
          q,
          exchange: exForSearch,
          limit: 12,
          ...(tradingAccountId ? { trading_account_id: tradingAccountId } : {}),
        },
      });
      const raw = (res.data?.data ?? []) as Array<{ symbol?: string; label?: string }>;
      const rex = (res.data?.resolved_exchange as string | undefined)?.toLowerCase();
      if (rex) setResolvedExchange(rex);
      setRemoteSearchItems(
        raw
          .map((d) => ({
            symbol: String(d.symbol ?? ""),
            brand: String(d.label ?? d.symbol ?? ""),
          }))
          .filter((x) => x.symbol),
      );
    } catch {
      setRemoteSearchItems([]);
    } finally {
      setSearchLoading(false);
    }
  }, [search, exchange, resolvedExchange, tradingAccountId]);

  useEffect(() => {
    const q = search.trim();
    if (q.length < 1) {
      setRemoteSearchItems(null);
      setSearchLoading(false);
      return;
    }
    const t = window.setTimeout(() => {
      void runSymbolSearch();
    }, 320);
    return () => clearTimeout(t);
  }, [search, runSymbolSearch]);

  const gridDisplayItems = useMemo(() => {
    const q = search.trim();
    if (!q) return baseList;
    if (localFiltered.length > 0) return localFiltered;
    return remoteSearchItems ?? [];
  }, [baseList, search, localFiltered, remoteSearchItems]);

  // self_taught: load RSI quick stats for visible symbols
  useEffect(() => {
    if (traderClass !== "self_taught") return;
    if (!gridDisplayItems.length) return;
    const symbols = gridDisplayItems.slice(0, 20).map((x) => x.symbol).join(",");

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
  }, [traderClass, gridDisplayItems]);

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
    let next: string[];
    if (selectionMode === "single") {
      next = exists ? [] : [symbol];
    } else {
      next = exists ? selections.filter((s) => s !== symbol) : [...selections, symbol];
    }
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
        <p className="text-[11px] leading-relaxed text-dark-500">
          Analyse one symbol at a time: pick a row in the grid below or type a symbol and use Analyse on the manual trade panel.
        </p>
      </div>
    );
  }

  if (traderClass === "experienced" && !allowBrandPickerPrimary) {
    // This branch is intentionally unreachable with current allowBrandPickerPrimary;
    // kept for clarity if you later decide to render this component directly.
  }

  const noOpportunities =
    !!exchangeTrimmed &&
    !loadingSettings &&
    !tier1Loading &&
    baseList.length === 0 &&
    !search.trim();
  const noMatches =
    !loadingSettings &&
    !tier1Loading &&
    search.trim().length > 0 &&
    gridDisplayItems.length === 0;

  const applyManualSymbol = () => {
    if (!manualSymbol.trim()) return;
    onManualSymbol?.(manualSymbol.trim());
  };

  return (
    <div className="space-y-4">
      {loadingSettings || (tier1Loading && !!exchangeTrimmed) ? (
        <div className="space-y-3">
          <div className="text-xs text-dark-400 animate-pulse">Loading tradable assets…</div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        </div>
      ) : !exchangeTrimmed ? (
        <div className="rounded-xl border border-amber-500/25 bg-dark-900 p-4">
          <p className="text-sm font-medium text-white">No broker selected yet</p>
          <p className="mt-1 text-xs text-dark-400">
            Connect a trading account in Settings, or use the account control in the experienced layout, so
            the asset grid matches your exchange.
          </p>
        </div>
      ) : noOpportunities ? (
        <div className="rounded-xl border border-dark-800 bg-dark-900 p-6 text-center">
          <div className="text-sm text-dark-400">No opportunities available right now</div>
          <div className="mt-1 text-xs text-dark-500">
            Markets may be closed, or your account list is still loading. Try again shortly, use Search after
            you open this section, or enter a symbol manually.
          </div>
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
            <div className="relative flex w-full flex-col gap-1 sm:w-auto sm:min-w-[18rem] sm:flex-1 sm:max-w-md">
              <div className="relative w-full">
                <Search size={16} className="absolute left-3 top-3 text-dark-500" />
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search symbols (server + grid)"
                  aria-busy={searchLoading}
                  className="w-full rounded-xl border border-dark-800 bg-dark-900 py-2 pl-10 pr-24 text-sm text-white outline-none placeholder:text-dark-500 focus:border-brand-500/60"
                />
                <button
                  type="button"
                  onClick={() => void runSymbolSearch()}
                  disabled={!search.trim() || searchLoading}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg border border-dark-700 bg-dark-950 px-2.5 py-1 text-[11px] font-semibold text-dark-200 hover:text-white disabled:opacity-40"
                >
                  {searchLoading ? "…" : "Search"}
                </button>
              </div>
              {search.trim() && localFiltered.length === 0 && remoteSearchItems && remoteSearchItems.length > 0 && (
                <div className="text-[11px] text-dark-500">Showing exchange search results for this account.</div>
              )}
            </div>

            <div className="flex items-center gap-2">
              <div className="inline-flex rounded-xl border border-dark-800 bg-dark-900 p-1">
                {allowedCategories.includes("stocks") && (
                  <button
                    type="button"
                    disabled={traderClass === "crypto_native" && !didLockCryptoTab.current}
                    onClick={() => setCategory("stocks")}
                    className={clsx(
                      "rounded-lg px-3 py-1.5 text-xs font-semibold",
                      category === "stocks" ? "bg-dark-800 text-white" : "text-dark-300 hover:text-white",
                    )}
                  >
                    {oandaMode ? "Forex" : "Stocks"}
                  </button>
                )}
                {allowedCategories.includes("crypto") && (
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
                )}
                {allowedCategories.includes("all") && (
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
                )}
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
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return;
                  e.preventDefault();
                  applyManualSymbol();
                }}
                placeholder="e.g. AAPL, BTC/USD, EUR_USD"
                className="w-full flex-1 rounded-xl border border-dark-800 bg-dark-950 px-3 py-2 text-sm text-white outline-none placeholder:text-dark-500 focus:border-brand-500/60"
              />
              <button type="button" onClick={applyManualSymbol} className="btn">
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
                    key={`${featuredRow.title}-${it.symbol}-${wsRemountEpoch[it.symbol] ?? 0}`}
                    traderClass={traderClass}
                    symbol={it.symbol}
                    brand={it.brand}
                    exchange={displayExchange}
                    currencySymbol={currencySymbol}
                    tradingAccountId={tradingAccountId}
                    isSelected={selections.includes(it.symbol)}
                    onToggle={() => handleToggle(it.symbol)}
                    onWsRemount={() => bumpWsForSymbol(it.symbol)}
                    showVolumeChange={traderClass === "crypto_native"}
                    volumeChangePct={(it as any).volume_change_pct ?? null}
                  />
                ))}
              </div>
            </div>
          )}

          {/* AI status badge — shows loading state while tier-2 enhances the list */}
          <div className="flex items-center gap-1.5 text-[11px]">
            {aiEnhanced ? (
              <>
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand-400" />
                <span className="text-brand-400 font-medium">AI-ranked</span>
                <span className="text-dark-500">— sorted by today&apos;s best opportunities</span>
              </>
            ) : (
              <>
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-dark-500 animate-pulse" />
                <span className="text-dark-500">AI analysing market…</span>
              </>
            )}
          </div>

          {noMatches ? (
            <div className="rounded-xl border border-dark-800 bg-dark-900 p-6 text-center">
              <div className="text-sm text-dark-200">
                No matches for &quot;{search.trim()}&quot;
                {searchLoading ? " — searching…" : ""}
              </div>
              <div className="mt-2 text-xs text-dark-500">
                Nothing in the current grid matched. {!searchLoading && "Try another term, tap Search, or enter a symbol manually."}
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {gridDisplayItems.map((it) => (
                <BrandCard
                  key={`${it.symbol}-${wsRemountEpoch[it.symbol] ?? 0}`}
                  traderClass={traderClass}
                  symbol={it.symbol}
                  brand={it.brand}
                  exchange={displayExchange}
                  currencySymbol={currencySymbol}
                  tradingAccountId={tradingAccountId}
                  isSelected={selections.includes(it.symbol)}
                  onToggle={() => handleToggle(it.symbol)}
                  onWsRemount={() => bumpWsForSymbol(it.symbol)}
                  rsi={quickStats?.[it.symbol]?.rsi ?? null}
                  showVolumeChange={traderClass === "crypto_native"}
                />
              ))}
            </div>
          )}

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
