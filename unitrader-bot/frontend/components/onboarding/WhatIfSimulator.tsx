import { useEffect, useMemo, useRef, useState } from "react";
import { authApi, api } from "@/lib/api";
import { BarChart3, ExternalLink, Loader2, X } from "lucide-react";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

type Mode = "dashboard" | "welcome_modal" | "modal";

type Preset = { id: string; label: string; symbols: string[] };

type SimResponse = {
  gain_gbp?: number;
  return_pct?: number;
  sharpe?: number;
  max_drawdown_pct?: number;
  win_rate_pct?: number;
  series?: Array<{ label: string; value: number }>;
  vs_hold_series?: Array<{ label: string; value: number }>;
  meta?: any;
};

const DISCLAIMER =
  "Past performance does not guarantee future results. This simulation applies\n" +
  "Unitrader's current strategy retroactively to historical market data.";

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function Skeleton() {
  return (
    <div className="space-y-3">
      <div className="h-4 w-48 animate-pulse rounded bg-dark-800" />
      <div className="h-28 w-full animate-pulse rounded bg-dark-900" />
      <div className="h-8 w-full animate-pulse rounded bg-dark-900" />
    </div>
  );
}

function SimpleBars({
  series,
  dottedSeries,
}: {
  series: Array<{ label: string; value: number }>;
  dottedSeries?: Array<{ label: string; value: number }>;
}) {
  const max = Math.max(1, ...series.map((s) => Math.abs(s.value)));
  return (
    <div className="relative rounded-xl border border-dark-800 bg-dark-950 p-4">
      <div className="flex items-end gap-2">
        {series.map((s) => (
          <div key={s.label} className="flex-1">
            <div
              className="w-full rounded-t bg-brand-500/60"
              style={{ height: `${Math.max(8, (Math.abs(s.value) / max) * 96)}px` }}
              title={`${s.label}: ${s.value.toFixed(2)}`}
            />
            <div className="mt-2 truncate text-[10px] text-dark-500">{s.label}</div>
          </div>
        ))}
      </div>
      {dottedSeries && dottedSeries.length === series.length && (
        <div className="pointer-events-none absolute inset-x-4 top-4">
          <div className="relative h-24">
            <div className="absolute inset-0 border-t border-dashed border-dark-600" />
          </div>
        </div>
      )}
    </div>
  );
}

export default function WhatIfSimulator({ mode }: { mode: Mode }) {
  const getWelcomeParam = () => {
    if (typeof window === "undefined") return false;
    return new URLSearchParams(window.location.search).get("welcome") === "true";
  };
  const clearWelcomeParam = () => {
    if (typeof window === "undefined") return;
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete("welcome");
      window.history.replaceState({}, "", url.toString());
    } catch {
      // ignore
    }
  };
  const [traderClass, setTraderClass] = useState<TraderClass | null>(null);
  const [approvedAssets, setApprovedAssets] = useState<string[]>([]);

  const [timeDays, setTimeDays] = useState(30);
  const [amount, setAmount] = useState(100);
  const [presetId, setPresetId] = useState<string>("your_picks");

  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<SimResponse | null>(null);

  const debounceRef = useRef<number | null>(null);

  const [welcomeRequested, setWelcomeRequested] = useState(false);

  useEffect(() => {
    if (mode !== "welcome_modal" && mode !== "modal") {
      setWelcomeRequested(false);
      return;
    }
    setWelcomeRequested(getWelcomeParam());
  }, [mode]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await authApi.getSettings();
        const tc = String(res.data?.trader_class ?? "complete_novice") as TraderClass;
        const assets = Array.isArray(res.data?.approved_assets)
          ? (res.data.approved_assets as string[])
          : [];
        if (!mounted) return;
        setTraderClass(tc);
        setApprovedAssets(assets);

        if (tc === "complete_novice" || tc === "curious_saver") {
          setAmount(100);
          setTimeDays(30);
          setPresetId("your_picks");
        } else if (tc === "self_taught") {
          setAmount(1000);
          setTimeDays(30);
          setPresetId("your_picks");
        } else if (tc === "crypto_native") {
          setAmount(1000);
          setTimeDays(30);
          setPresetId("btc_only");
        } else {
          setAmount(0);
        }
      } catch {
        if (!mounted) return;
        setTraderClass("complete_novice");
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const shouldShowWelcomeModal = useMemo(() => {
    if (!welcomeRequested) return false;
    if (!traderClass) return false;
    if (traderClass === "complete_novice") return true;
    if (traderClass === "curious_saver") return true;
    if (traderClass === "crypto_native") return true;
    if (traderClass === "experienced") return false;
    if (traderClass === "semi_institutional") return false;
    if (traderClass === "self_taught") {
      try {
        if (typeof window === "undefined") return false;
        // Show only if onboarding chat was completed (not skip).
        return window.localStorage.getItem("unitrader_onboarding_chat_completed_v1") === "true";
      } catch {
        return false;
      }
    }
    return false;
  }, [welcomeRequested, traderClass]);

  const presets: Preset[] = useMemo(() => {
    if (!traderClass) return [];

    if (traderClass === "crypto_native") {
      return [
        { id: "btc_only", label: "BTC only", symbols: ["BTC/USD"] },
        { id: "btc_eth", label: "BTC + ETH", symbols: ["BTC/USD", "ETH/USD"] },
        { id: "diversified_crypto", label: "Diversified crypto", symbols: ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"] },
        { id: "high_risk_alts", label: "High-risk alts", symbols: ["SOL/USD", "DOGE/USD", "XRP/USD"] },
      ];
    }

    // complete_novice / curious_saver / self_taught defaults
    const yourPicks = approvedAssets.length ? approvedAssets : ["AAPL", "MSFT", "SPY"];
    return [
      { id: "your_picks", label: "Your picks", symbols: yourPicks.slice(0, 6) },
      { id: "apex_recommends", label: "Unitrader recommends", symbols: ["SPY", "VOO", "AAPL", "MSFT"] },
      { id: "crypto", label: "Crypto", symbols: ["BTC/USD", "ETH/USD"] },
    ];
  }, [traderClass, approvedAssets]);

  const selectedPreset = useMemo(() => {
    return presets.find((p) => p.id === presetId) ?? presets[0] ?? null;
  }, [presets, presetId]);

  const heading = useMemo(() => {
    if (!traderClass) return "";
    if (traderClass === "complete_novice" || traderClass === "curious_saver") {
      return "If Unitrader had traded for you last month";
    }
    if (traderClass === "self_taught") return "How Unitrader's strategy compares to yours";
    if (traderClass === "crypto_native") return "What Unitrader would have done with your crypto";
    return "Backtest";
  }, [traderClass]);

  const isCompactBacktest = traderClass === "experienced" || traderClass === "semi_institutional";

  // Dashboard card is always visible, but content differs.
  const shouldRender = mode === "dashboard" ? true : shouldShowWelcomeModal;

  // Load data — MUST be before any early return to satisfy React's rules of hooks.
  // Guard inside the effect body so data is only fetched when the component is actually visible.
  useEffect(() => {
    if (!shouldRender) return;
    if (!traderClass) return;
    if (isCompactBacktest) {
      // still call simulate-history with nominal params; backend can ignore amount
    }
    if (!selectedPreset) return;

    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    setLoading(true);

    debounceRef.current = window.setTimeout(async () => {
      try {
        const res = await api.get("/api/trading/simulate-history", {
          params: {
            amount: amount,
            days: timeDays,
            symbols: selectedPreset.symbols.join(","),
          },
        });
        const d = (res.data?.data ?? res.data) as SimResponse;
        setData(d);
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    }, 400);

    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shouldRender, amount, timeDays, selectedPreset, traderClass, isCompactBacktest]);

  if (!shouldRender) return null;

  const content = (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <BarChart3 size={16} className="text-brand-400" />
            <h3 className="truncate text-sm font-semibold text-white">{heading}</h3>
          </div>
          {traderClass === "curious_saver" && (
            <div className="mt-1 text-xs text-dark-400">
              Compare the simulation against typical ISA-style returns.
            </div>
          )}
        </div>
      </div>

      {traderClass === "crypto_native" && (
        <div className="inline-flex rounded-xl border border-dark-800 bg-dark-950 p-1">
          {[
            { d: 7, label: "7d" },
            { d: 30, label: "30d" },
            { d: 90, label: "90d" },
          ].map((t) => (
            <button
              key={t.d}
              type="button"
              onClick={() => setTimeDays(t.d)}
              className={clsx(
                "rounded-lg px-3 py-1.5 text-xs font-semibold",
                timeDays === t.d ? "bg-dark-800 text-white" : "text-dark-300 hover:text-white",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      {presets.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {presets.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setPresetId(p.id)}
              className={clsx(
                "rounded-xl border px-3 py-2 text-xs font-semibold",
                presetId === p.id
                  ? "border-brand-500/40 bg-brand-500/10 text-brand-300"
                  : "border-dark-800 bg-dark-950 text-dark-300 hover:text-white",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <Skeleton />
      ) : (
        <>
          {isCompactBacktest ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-3">
                <div className="text-[11px] text-dark-500">Return</div>
                <div className="mt-1 text-sm font-bold text-white tabular-nums">
                  {data?.return_pct !== undefined ? `${data.return_pct.toFixed(2)}%` : "—"}
                </div>
              </div>
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-3">
                <div className="text-[11px] text-dark-500">Sharpe</div>
                <div className="mt-1 text-sm font-bold text-white tabular-nums">
                  {data?.sharpe !== undefined ? data.sharpe.toFixed(2) : "—"}
                </div>
              </div>
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-3">
                <div className="text-[11px] text-dark-500">Max drawdown</div>
                <div className="mt-1 text-sm font-bold text-white tabular-nums">
                  {data?.max_drawdown_pct !== undefined ? `${data.max_drawdown_pct.toFixed(2)}%` : "—"}
                </div>
              </div>
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-3">
                <div className="text-[11px] text-dark-500">Win rate</div>
                <div className="mt-1 text-sm font-bold text-white tabular-nums">
                  {data?.win_rate_pct !== undefined ? `${data.win_rate_pct.toFixed(1)}%` : "—"}
                </div>
              </div>
            </div>
          ) : (
            <>
              <SimpleBars
                series={
                  data?.series?.length
                    ? data.series
                    : [
                        { label: "W1", value: 1.2 },
                        { label: "W2", value: 0.6 },
                        { label: "W3", value: 1.0 },
                        { label: "W4", value: 1.4 },
                      ]
                }
                dottedSeries={
                  traderClass === "self_taught" || traderClass === "crypto_native"
                    ? (data?.vs_hold_series?.length ? data.vs_hold_series : undefined)
                    : undefined
                }
              />

              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="text-xs text-dark-400">Estimated GBP gain</div>
                <div className="mt-1 text-lg font-bold text-white tabular-nums">
                  {data?.gain_gbp !== undefined
                    ? `${data.gain_gbp >= 0 ? "+" : ""}£${data.gain_gbp.toFixed(2)}`
                    : "—"}
                </div>

                {(traderClass === "self_taught" || traderClass === "crypto_native") && (
                  <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
                    <div>
                      <div className="text-[11px] text-dark-500">Win rate</div>
                      <div className="mt-1 text-sm font-semibold text-white tabular-nums">
                        {data?.win_rate_pct !== undefined ? `${data.win_rate_pct.toFixed(1)}%` : "—"}
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] text-dark-500">
                        {traderClass === "crypto_native" ? "vs HODLing" : "vs buy-and-hold"}
                      </div>
                      <div className="mt-1 text-sm font-semibold text-white tabular-nums">
                        {data?.meta?.vs_hold_return_pct !== undefined
                          ? `${Number(data.meta.vs_hold_return_pct).toFixed(2)}%`
                          : "—"}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </>
      )}

      {!isCompactBacktest && (
        <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
          <div className="mb-2 flex items-center justify-between text-xs text-dark-400">
            <span>Amount</span>
            <span className="tabular-nums">£{amount}</span>
          </div>
          <input
            type="range"
            min={traderClass === "self_taught" || traderClass === "crypto_native" ? 100 : 25}
            max={traderClass === "self_taught" || traderClass === "crypto_native" ? 5000 : 500}
            step={traderClass === "self_taught" || traderClass === "crypto_native" ? 100 : 25}
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
            className="w-full"
          />
        </div>
      )}

      {isCompactBacktest && (
        <div className="flex items-center justify-between rounded-xl border border-dark-800 bg-dark-950 p-4">
          <div className="text-xs text-dark-400">Backtest widget (compact)</div>
          <a
            href="#"
            onClick={(e) => e.preventDefault()}
            className="inline-flex items-center gap-1 text-xs font-semibold text-brand-400 hover:underline"
          >
            Run custom backtest <ExternalLink size={14} />
          </a>
        </div>
      )}

      <div className="whitespace-pre-line rounded-xl border border-dark-800 bg-dark-950 p-4 text-xs text-dark-300">
        {DISCLAIMER}
      </div>
    </div>
  );

  if (mode === "dashboard") {
    return (
      <div className="rounded-xl border border-dark-800 bg-dark-950 p-4 md:p-5">
        {content}
      </div>
    );
  }

  // Welcome modal
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-2xl rounded-2xl border border-dark-800 bg-dark-950 p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <div className="text-sm font-semibold text-white">Welcome</div>
          <button
            type="button"
            onClick={() => {
              clearWelcomeParam();
              setWelcomeRequested(false);
            }}
            className="rounded-lg p-2 text-dark-400 hover:bg-dark-900 hover:text-white"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        {content}
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={() => {
              clearWelcomeParam();
              setWelcomeRequested(false);
            }}
            className="btn-primary"
          >
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}

