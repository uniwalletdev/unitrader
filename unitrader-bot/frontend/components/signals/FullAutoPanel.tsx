"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Lock, Loader2, TrendingUp, TrendingDown, Minus,
  CheckCircle, BarChart2, Bot, Info, Undo2,
} from "lucide-react";
import { signalApi, tradingApi } from "@/lib/api";
import BrandPicker from "@/components/trade/BrandPicker";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface UserSettings {
  auto_trade_enabled?: boolean;
  auto_trade_threshold?: number;
  auto_trade_max_per_scan?: number;
  watchlist?: string[];
  trader_class?: string;
  execution_mode?: string;
  autonomous_mode_unlocked?: boolean;
}

interface FullAutoPanelProps {
  botName: string;
  userSettings: UserSettings;
  trustLadderStage: number;
  onSettingsUpdate: (updates: object) => void;
  exchange?: string;
  tradingAccountId?: string | null;
  isPaper?: boolean;
}

interface ActivityEntry {
  id: string;
  type: "trade" | "skipped" | "stop_loss";
  symbol: string;
  side?: string;
  price?: number;
  reason?: string;
  created_at: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function lockProgressText(stage: number): string {
  if (stage <= 1) return "Complete stage 2 to unlock curated selects";
  return "Complete stage 3 to unlock Full Auto";
}

function thresholdNote(botName: string, threshold: number): string {
  if (threshold >= 95) return "Very rare — only the strongest signals";
  if (threshold >= 80) return `${botName} trades roughly 2–3 times per week at this level`;
  if (threshold <= 65) return `More frequent — ${botName} takes more opportunities`;
  return "";
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function ActivityDot({ type }: { type: ActivityEntry["type"] }) {
  if (type === "trade")
    return <span className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0 mt-0.5" />;
  if (type === "stop_loss")
    return <span className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0 mt-0.5" />;
  return <span className="w-2 h-2 rounded-full bg-dark-500 flex-shrink-0 mt-0.5" />;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export default function FullAutoPanel({
  botName,
  userSettings,
  trustLadderStage,
  onSettingsUpdate,
  exchange,
  tradingAccountId,
  isPaper,
}: FullAutoPanelProps) {
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [threshold, setThreshold] = useState(80);
  const [maxPerScan, setMaxPerScan] = useState(2);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [activityLoading, setActivityLoading] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [tradesToday, setTradesToday] = useState(0);
  const [pnlToday, setPnlToday] = useState<string>("—");

  const sliderDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── 60-second undo toast ──────────────────────────────────────────────────
  const [undoTrade, setUndoTrade] = useState<{ id: string; symbol: string; side: string; secondsLeft: number } | null>(null);
  const knownTradeIds = useRef<Set<string>>(new Set());
  const undoCountdown = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearUndo = useCallback(() => {
    if (undoCountdown.current) clearInterval(undoCountdown.current);
    setUndoTrade(null);
  }, []);

  // Load per-account Full Auto settings (NOT user-global)
  useEffect(() => {
    if (!tradingAccountId) return;
    let mounted = true;
    (async () => {
      try {
        const res = await signalApi.accountSettings(tradingAccountId);
        const d = (res.data?.data ?? res.data) as any;
        if (!mounted) return;
        setAutoEnabled(Boolean(d?.auto_trade_enabled ?? false));
        setThreshold(Number(d?.auto_trade_threshold ?? 80));
        setMaxPerScan(Number(d?.auto_trade_max_per_scan ?? 2));
        setWatchlist(Array.isArray(d?.watchlist) ? d.watchlist : []);
      } catch {
        // non-fatal; keep defaults
      }
    })();
    return () => {
      mounted = false;
    };
  }, [tradingAccountId]);

  const signalsSkipped = 0;

  // ── Fetch activity log (last 24h closed trades) ───────────────────────────
  const fetchActivity = useCallback(async () => {
    setActivityLoading(true);
    try {
      const fromIso = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
      const params: Record<string, string | number | boolean> = {
        from_date: fromIso,
        limit: 100,
      };
      if (tradingAccountId) params.trading_account_id = tradingAccountId;
      if (exchange?.trim()) params.exchange = exchange.trim().toLowerCase();
      if (typeof isPaper === "boolean") params.is_paper = isPaper;

      const res = await tradingApi.history(params);
      const h = res.data?.data ?? res.data;
      const tradesRaw = Array.isArray(h?.trades) ? h.trades : [];
      const fromTs = Date.now() - 24 * 60 * 60 * 1000;

      type HistRow = {
        id: string;
        symbol?: string;
        side?: string;
        status?: string;
        exit_price?: number;
        entry_price?: number;
        closed_at?: string | null;
        created_at?: string | null;
        profit?: number | null;
        loss?: number | null;
      };

      const closedRecent = tradesRaw.filter((t: HistRow) => {
        if (t.status && t.status !== "closed") return false;
        const ts = t.closed_at ? new Date(t.closed_at).getTime() : 0;
        return ts >= fromTs;
      });

      const entries: ActivityEntry[] = closedRecent.map((t: HistRow) => ({
        id: String(t.id),
        type: "trade",
        symbol: String(t.symbol ?? "—"),
        side: t.side,
        price: t.exit_price ?? t.entry_price,
        created_at: t.closed_at || t.created_at || new Date().toISOString(),
      }));

      const pnlSum = closedRecent.reduce(
        (s: number, t: HistRow) => s + (Number(t.profit ?? 0) - Number(t.loss ?? 0)),
        0,
      );

      setActivity(entries);
      setTradesToday(closedRecent.length);
      setPnlToday(
        closedRecent.length === 0
          ? "—"
          : `${pnlSum >= 0 ? "+" : "-"}$${Math.abs(pnlSum).toFixed(2)}`,
      );

      // Detect newly-closed trades to surface undo toast
      for (const t of closedRecent as any[]) {
        const sid = String(t.id);
        if (!knownTradeIds.current.has(sid)) {
          knownTradeIds.current.add(sid);
          if (knownTradeIds.current.size > 1) {
            // Seed known IDs silently on first load; only show toast on subsequent
            if (undoCountdown.current) clearInterval(undoCountdown.current);
            setUndoTrade({ id: sid, symbol: String(t.symbol ?? ""), side: String(t.side ?? ""), secondsLeft: 60 });
            undoCountdown.current = setInterval(() => {
              setUndoTrade((prev) => {
                if (!prev) return null;
                if (prev.secondsLeft <= 1) {
                  clearInterval(undoCountdown.current!);
                  return null;
                }
                return { ...prev, secondsLeft: prev.secondsLeft - 1 };
              });
            }, 1000);
          }
        }
      }
    } catch {
      setActivity([]);
      setTradesToday(0);
      setPnlToday("—");
    } finally {
      setActivityLoading(false);
    }
  }, [tradingAccountId, exchange, isPaper]);

  const handleUndo = useCallback(async (tradeId: string) => {
    clearUndo();
    try {
      await tradingApi.closePosition(tradeId);
    } catch {
      // non-fatal — trade may have already settled
    }
    await fetchActivity();
  }, [clearUndo, fetchActivity]);

  useEffect(() => {
    fetchActivity();
  }, [fetchActivity]);

  // ── Toggle auto-trade ──────────────────────────────────────────────────────
  const handleToggle = async () => {
    const next = !autoEnabled;
    setToggling(true);
    setAutoEnabled(next);
    try {
      await signalApi.updateSettings({ execution_mode: userSettings.execution_mode ?? "autonomous" });
      if (tradingAccountId) {
        await signalApi.updateAccountSettings({ trading_account_id: tradingAccountId, auto_trade_enabled: next });
      }
      onSettingsUpdate({ auto_trade_enabled: next });
    } catch {
      setAutoEnabled(!next); // rollback
    } finally {
      setToggling(false);
    }
  };

  // ── Debounced slider persistence ──────────────────────────────────────────
  const persistSliders = useCallback(
    (t: number, m: number) => {
      if (sliderDebounce.current) clearTimeout(sliderDebounce.current);
      sliderDebounce.current = setTimeout(async () => {
        try {
          if (tradingAccountId) {
            await signalApi.updateAccountSettings({
              trading_account_id: tradingAccountId,
              auto_trade_threshold: t,
              auto_trade_max_per_scan: m,
            });
          }
          onSettingsUpdate({ auto_trade_threshold: t, auto_trade_max_per_scan: m });
        } catch {
          // non-fatal
        }
      }, 500);
    },
    [onSettingsUpdate, tradingAccountId]
  );

  const handleThresholdChange = (val: number) => {
    setThreshold(val);
    persistSliders(val, maxPerScan);
  };

  const handleMaxPerScanChange = (val: number) => {
    setMaxPerScan(val);
    persistSliders(threshold, val);
  };

  // ─────────────────────────────────────────────────────────────────────────
  // LOCKED STATE
  // ─────────────────────────────────────────────────────────────────────────

  if (trustLadderStage < 3) {
    return (
      <div className="rounded-2xl border border-dark-700 bg-dark-900 p-6 flex flex-col items-center gap-4 text-center">
        <div className="w-12 h-12 rounded-full bg-dark-800 border border-dark-600 flex items-center justify-center">
          <Lock className="w-5 h-5 text-dark-400" />
        </div>
        <div>
          <p className="text-base font-semibold text-white">Autonomous mode is locked</p>
          <p className="text-sm text-dark-400 mt-1 max-w-xs mx-auto">
            Reach Trust Ladder Stage 3 and opt in from Settings. {botName} needs to prove itself
            before trading solo.
          </p>
        </div>
        <div className="w-full rounded-xl border border-dark-700 bg-dark-800 px-4 py-3 flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-xs">
            <span className="text-dark-400">Progress</span>
            <span className="text-dark-300 font-medium">
              Stage {trustLadderStage} of 3
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-dark-700 overflow-hidden">
            <div
              className="h-full rounded-full bg-brand-500 transition-all duration-500"
              style={{ width: `${(trustLadderStage / 4) * 100}%` }}
            />
          </div>
          <p className="text-[11px] text-dark-500 mt-0.5">{lockProgressText(trustLadderStage)}</p>
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // UNLOCKED STATE
  // ─────────────────────────────────────────────────────────────────────────

  const note = thresholdNote(botName, threshold);

  return (
    <div className="flex flex-col gap-4">

      {/* ── Master toggle card ──────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-dark-700 bg-dark-900 p-5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            className={`w-10 h-10 rounded-xl border flex items-center justify-center transition-all ${
              autoEnabled
                ? "bg-emerald-500/20 border-emerald-500/30"
                : "bg-dark-800 border-dark-600"
            }`}
          >
            <Bot className={`w-5 h-5 ${autoEnabled ? "text-emerald-400" : "text-dark-400"}`} />
          </div>
          <div>
            <p className="text-sm font-semibold text-white">{botName} Autopilot</p>
            <p className="text-xs text-dark-400">{botName} scans every 30 min and trades automatically</p>
          </div>
        </div>

        {/* Toggle */}
        <button
          onClick={handleToggle}
          disabled={toggling}
          className="relative flex-shrink-0"
          aria-label={autoEnabled ? "Disable autopilot" : "Enable autopilot"}
        >
          <div
            className={`w-12 h-6 rounded-full transition-all duration-200 ${
              autoEnabled ? "bg-emerald-500" : "bg-dark-600"
            }`}
          />
          <div
            className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-all duration-200 ${
              autoEnabled ? "left-6" : "left-0.5"
            }`}
          />
          {toggling && (
            <Loader2 className="absolute inset-0 m-auto w-3.5 h-3.5 animate-spin text-dark-400" />
          )}
        </button>
      </div>

      {/* Active/off label */}
      <p className={`text-xs font-medium text-center -mt-2 ${autoEnabled ? "text-emerald-400" : "text-dark-500"}`}>
        {autoEnabled ? "Active" : "Off"}
      </p>

      {/* ── Settings (only when auto is ON) ─────────────────────────────────── */}
      {autoEnabled && (
        <div className="rounded-2xl border border-dark-700 bg-dark-900 p-4 flex flex-col gap-5">

          {/* Confidence threshold */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <label className="text-xs text-dark-300 font-medium">Confidence threshold</label>
              <span className="text-xs font-bold text-white">{threshold}%</span>
            </div>
            <input
              type="range"
              min={65}
              max={95}
              step={5}
              value={threshold}
              onChange={(e) => handleThresholdChange(Number(e.target.value))}
              className="w-full accent-emerald-500"
            />
            {note && (
              <p className="text-[11px] text-dark-400 flex items-start gap-1">
                <Info className="w-3 h-3 mt-0.5 flex-shrink-0" />
                {note}
              </p>
            )}
            <p className="text-[11px] text-dark-500">
              Only trade when {botName} is at least {threshold}% confident
            </p>
          </div>

          {/* Max trades per scan */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <label className="text-xs text-dark-300 font-medium">Max trades per scan</label>
              <span className="text-xs font-bold text-white">{maxPerScan}</span>
            </div>
            <input
              type="range"
              min={1}
              max={3}
              step={1}
              value={maxPerScan}
              onChange={(e) => handleMaxPerScanChange(Number(e.target.value))}
              className="w-full accent-emerald-500"
            />
          </div>

          {/* Watchlist */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-dark-300 font-medium">Watchlist</label>
            <p className="text-[11px] text-dark-500">Symbols {botName} monitors in Full Auto mode</p>
            <BrandPicker
              exchange={exchange || ""}
              tradingAccountId={tradingAccountId}
              traderClass={
                (userSettings.trader_class as
                  | "complete_novice"
                  | "curious_saver"
                  | "self_taught"
                  | "experienced"
                  | "semi_institutional"
                  | "crypto_native") ?? "self_taught"
              }
              selectedSymbols={watchlist}
              onChangeSelectedSymbols={(symbols) => {
                setWatchlist(symbols);
                if (tradingAccountId) {
                  signalApi.updateAccountSettings({ trading_account_id: tradingAccountId, watchlist: symbols }).catch(() => {});
                }
                onSettingsUpdate({ watchlist: symbols });
              }}
            />
          </div>
        </div>
      )}

      {/* ── Activity log ────────────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-dark-700 bg-dark-900 p-4 flex flex-col gap-3">
        <p className="text-sm font-semibold text-white">{botName} activity log</p>
        <p className="text-xs text-dark-500 -mt-1">Today only</p>

        {activityLoading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="w-4 h-4 animate-spin text-dark-400" />
          </div>
        ) : activity.length === 0 ? (
          <div className="rounded-xl border border-dark-700 bg-dark-800 px-4 py-5 text-center">
            <p className="text-sm text-dark-300">{botName} is watching your watchlist.</p>
            <p className="text-xs text-dark-500 mt-1">
              The next scan runs in a few minutes.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {activity.map((entry) => (
              <div key={entry.id} className="flex items-start gap-2.5">
                <ActivityDot type={entry.type} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-dark-200">
                    {entry.type === "trade" && (
                      <>
                        <span className="font-medium">{entry.symbol}</span>{" "}
                        <span className="text-dark-400">{entry.side?.toUpperCase()}</span>
                        {entry.price ? ` @ $${entry.price}` : ""}
                      </>
                    )}
                    {entry.type === "skipped" && (
                      <>
                        Skipped <span className="font-medium">{entry.symbol}</span>
                        {entry.reason ? ` — ${entry.reason}` : ""}
                      </>
                    )}
                    {entry.type === "stop_loss" && (
                      <>
                        Stop-loss / update on{" "}
                        <span className="font-medium">{entry.symbol}</span>
                      </>
                    )}
                  </p>
                </div>
                <span className="flex-shrink-0 text-[10px] text-dark-500">
                  {formatTime(entry.created_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Stats row ───────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Trades today", value: tradesToday },
          { label: "Today's P&L", value: pnlToday },
          { label: "Signals skipped", value: signalsSkipped },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="rounded-xl border border-dark-700 bg-dark-900 p-3 flex flex-col items-center gap-1 text-center"
          >
            <span className="text-lg font-bold text-white">{value}</span>
            <span className="text-[11px] text-dark-400">{label}</span>
          </div>
        ))}
      </div>

      {/* ── 60-second undo toast ────────────────────────────────────────────── */}
      {undoTrade && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
          <div className="flex items-center gap-2 min-w-0">
            <Undo2 className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <p className="text-xs text-amber-200 truncate">
              <span className="font-semibold">{undoTrade.symbol}</span>{" "}
              {undoTrade.side?.toUpperCase()} was just placed
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-xs font-mono text-amber-400 w-6 text-right">{undoTrade.secondsLeft}s</span>
            <button
              onClick={() => handleUndo(undoTrade.id)}
              className="rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-400 transition-colors"
            >
              Undo
            </button>
            <button
              onClick={clearUndo}
              className="rounded-lg border border-dark-600 px-2 py-1.5 text-xs text-dark-400 hover:text-white transition-colors"
            >
              Keep
            </button>
          </div>
        </div>
      )}

      {/* ── Undo note ───────────────────────────────────────────────────────── */}
      <div className="flex items-start gap-2 rounded-xl border border-dark-700 bg-dark-800 px-3 py-2.5">
        <CheckCircle className="w-3.5 h-3.5 text-dark-400 flex-shrink-0 mt-0.5" />
        <p className="text-[11px] text-dark-400 leading-relaxed">
          Every auto trade sends you a notification with a 60-second undo option.{" "}
          <span className="text-dark-300">You are always in control.</span>
        </p>
      </div>
    </div>
  );
}
