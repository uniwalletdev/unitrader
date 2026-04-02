"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Lock, Loader2, TrendingUp, TrendingDown, Minus,
  CheckCircle, BarChart2, Bot, Info,
} from "lucide-react";
import { api, signalApi } from "@/lib/api";
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
  signal_stack_mode?: string;
}

interface FullAutoPanelProps {
  botName: string;
  userSettings: UserSettings;
  trustLadderStage: number;
  onSettingsUpdate: (updates: object) => void;
  exchange?: string;
  tradingAccountId?: string | null;
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
}: FullAutoPanelProps) {
  const [autoEnabled, setAutoEnabled] = useState(userSettings.auto_trade_enabled ?? false);
  const [threshold, setThreshold] = useState(userSettings.auto_trade_threshold ?? 80);
  const [maxPerScan, setMaxPerScan] = useState(userSettings.auto_trade_max_per_scan ?? 2);
  const [watchlist, setWatchlist] = useState<string[]>(userSettings.watchlist ?? []);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [activityLoading, setActivityLoading] = useState(true);
  const [toggling, setToggling] = useState(false);

  const sliderDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // #region agent log
    fetch('http://127.0.0.1:7831/ingest/2858cb77-c539-428f-882e-63cb43d8ab6e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'026d4d'},body:JSON.stringify({sessionId:'026d4d',runId:'initial',hypothesisId:'H2',location:'FullAutoPanel.tsx:91',message:'full-auto input types',data:{watchlistIsArray:Array.isArray(userSettings.watchlist),watchlistType:typeof userSettings.watchlist,watchlistLength:Array.isArray(userSettings.watchlist)?userSettings.watchlist.length:null,autoEnabled:userSettings.auto_trade_enabled ?? false,trustLadderStage},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
  }, [trustLadderStage, userSettings.auto_trade_enabled, userSettings.watchlist]);

  // ── Stats derived from activity ───────────────────────────────────────────
  const tradesToday = activity.filter((a) => a.type === "trade").length;
  const signalsSkipped = activity.filter((a) => a.type === "skipped").length;
  // P&L would require price data — show placeholder until trade history API provides it
  const pnlToday = "—";

  // ── Fetch activity log ────────────────────────────────────────────────────
  const fetchActivity = useCallback(async () => {
    setActivityLoading(true);
    try {
      const res = await api.get("/api/trading/history?hours=24");
      const raw: ActivityEntry[] =
        res.data?.data?.trades ??
        res.data?.trades ??
        (Array.isArray(res.data) ? res.data : []);
      // #region agent log
      fetch('http://127.0.0.1:7831/ingest/2858cb77-c539-428f-882e-63cb43d8ab6e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'026d4d'},body:JSON.stringify({sessionId:'026d4d',runId:'initial',hypothesisId:'H1',location:'FullAutoPanel.tsx:114',message:'history response shape',data:{responseKeys:res?.data&&typeof res.data==='object'?Object.keys(res.data).slice(0,8):[],rawIsArray:Array.isArray(raw),rawType:typeof raw,rawLength:Array.isArray(raw)?raw.length:null,dataHasNestedTrades:Boolean(res?.data?.data?.trades),nestedTradesIsArray:Array.isArray(res?.data?.data?.trades)},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      setActivity(raw);
    } catch {
      setActivity([]);
    } finally {
      setActivityLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchActivity();
  }, [fetchActivity]);

  // ── Toggle auto-trade ──────────────────────────────────────────────────────
  const handleToggle = async () => {
    const next = !autoEnabled;
    setToggling(true);
    setAutoEnabled(next);
    try {
      await signalApi.updateSettings({ signal_stack_mode: userSettings.signal_stack_mode ?? "full_auto" });
      await api.patch("/api/signals/settings", { auto_trade_enabled: next });
      // #region agent log
      fetch('http://127.0.0.1:7831/ingest/2858cb77-c539-428f-882e-63cb43d8ab6e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'026d4d'},body:JSON.stringify({sessionId:'026d4d',runId:'initial',hypothesisId:'H4',location:'FullAutoPanel.tsx:139',message:'auto-toggle persisted',data:{next},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      onSettingsUpdate({ auto_trade_enabled: next });
    } catch (error: any) {
      // #region agent log
      fetch('http://127.0.0.1:7831/ingest/2858cb77-c539-428f-882e-63cb43d8ab6e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'026d4d'},body:JSON.stringify({sessionId:'026d4d',runId:'initial',hypothesisId:'H3',location:'FullAutoPanel.tsx:143',message:'auto-toggle persist failed',data:{status:error?.response?.status ?? null,detail:error?.response?.data?.detail ?? null},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
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
          await api.patch("/api/signals/settings", {
            auto_trade_threshold: t,
            auto_trade_max_per_scan: m,
          });
          onSettingsUpdate({ auto_trade_threshold: t, auto_trade_max_per_scan: m });
        } catch {
          // non-fatal
        }
      }, 500);
    },
    [onSettingsUpdate]
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
          <p className="text-base font-semibold text-white">Full Auto is locked</p>
          <p className="text-sm text-dark-400 mt-1 max-w-xs mx-auto">
            Complete the Trust Ladder first. {botName} needs to prove itself with your money before
            trading solo.
          </p>
        </div>
        <div className="w-full rounded-xl border border-dark-700 bg-dark-800 px-4 py-3 flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-xs">
            <span className="text-dark-400">Progress</span>
            <span className="text-dark-300 font-medium">
              Stage {trustLadderStage} of 4
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
