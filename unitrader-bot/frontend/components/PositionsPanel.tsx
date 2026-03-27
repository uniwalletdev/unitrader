import { useState, useEffect, useCallback } from "react";
import {
  TrendingUp, RefreshCw, Loader2, XCircle, AlertTriangle, Crosshair,
} from "lucide-react";
import { tradingApi } from "@/lib/api";

interface Trade {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  claude_confidence?: number;
  created_at: string;
  market_condition?: string;
}

export default function PositionsPanel({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const [positions, setPositions] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [closing, setClosing] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await tradingApi.openPositions();
      setPositions(res.data.data?.positions || []);
    } catch {
      setPositions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 30s
  useEffect(() => {
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const handleClose = async (trade: Trade) => {
    if (!confirm(`Close ${trade.symbol} ${trade.side} position at market price?`)) return;
    setClosing(trade.id);
    setMessage(null);
    try {
      await tradingApi.closePosition(trade.id);
      setMessage({ type: "success", text: `${trade.symbol} position closed.` });
      await load();
    } catch (err: any) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Failed to close position." });
    } finally {
      setClosing(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-dark-500">
        <Loader2 size={15} className="mr-2 animate-spin text-brand-400" /> Loading positions...
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title">Open Positions</h1>
          <p className="page-subtitle">{positions.length} active trade{positions.length !== 1 ? 's' : ''}</p>
        </div>
        <button onClick={load} className="btn-ghost gap-2">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {message && (
        <div className={`flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs ${
          message.type === "success" ? "bg-brand-500/[0.06] border border-brand-500/15 text-brand-400" : "bg-red-500/[0.04] border border-red-500/15 text-red-400"
        }`}>
          {message.type === "success" ? <TrendingUp size={13} /> : <AlertTriangle size={13} />}
          {message.text}
        </div>
      )}

      {positions.length === 0 ? (
        <div className="mx-auto max-w-md space-y-5 py-16 text-center">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-dark-800 bg-[#0d1117]">
            <Crosshair size={28} className="text-dark-500" />
          </div>
          <h2 className="text-lg font-semibold text-white tracking-tight">No Open Positions</h2>
          <p className="text-sm text-dark-400 leading-relaxed">
            Your AI hasn't opened any trades yet. Go to the Trade tab to analyze a market and execute.
          </p>
          <button onClick={() => onNavigate?.("trade")} className="btn-primary w-full">
            <Crosshair size={14} /> Start Trading
          </button>
        </div>
      ) : isMobile ? (
        <div className="space-y-2.5">
          {positions.map((t) => (
            <div key={t.id} className="rounded-xl border border-dark-800 bg-[#0d1117] p-3">
              <div className="mb-2 flex items-start justify-between gap-2">
                <div>
                  <p className="font-mono text-sm font-semibold text-white">{t.symbol}</p>
                  <p className={`text-xs font-semibold ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>
                    {t.side}
                  </p>
                </div>
                <button
                  onClick={() => handleClose(t)}
                  disabled={closing === t.id}
                  className="flex items-center gap-1.5 rounded-lg border border-red-500/20 px-2 py-1.5 text-[11px] text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-50"
                >
                  {closing === t.id ? <Loader2 size={11} className="animate-spin" /> : <XCircle size={11} />}
                  Close
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div className="rounded-lg border border-dark-800 bg-dark-900/40 p-2">
                  <p className="text-dark-500">Qty</p>
                  <p className="font-mono text-dark-200">{t.quantity}</p>
                </div>
                <div className="rounded-lg border border-dark-800 bg-dark-900/40 p-2">
                  <p className="text-dark-500">Confidence</p>
                  <p className="text-dark-200">{t.claude_confidence?.toFixed(0) ?? "—"}%</p>
                </div>
                <div className="rounded-lg border border-dark-800 bg-dark-900/40 p-2">
                  <p className="text-dark-500">Entry</p>
                  <p className="font-mono text-white">${t.entry_price?.toFixed(2)}</p>
                </div>
                <div className="rounded-lg border border-dark-800 bg-dark-900/40 p-2">
                  <p className="text-dark-500">Opened</p>
                  <p className="text-dark-300">
                    {new Date(t.created_at).toLocaleDateString([], { month: "short", day: "numeric" })}
                  </p>
                </div>
                <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-2">
                  <p className="text-dark-500">Stop Loss</p>
                  <p className="font-mono text-red-400">${t.stop_loss?.toFixed(2)}</p>
                </div>
                <div className="rounded-lg border border-brand-500/20 bg-brand-500/5 p-2">
                  <p className="text-dark-500">Take Profit</p>
                  <p className="font-mono text-brand-400">${t.take_profit?.toFixed(2)}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="table-container overflow-x-auto rounded-2xl border border-dark-800 bg-[#0d1117]">
          <table className="min-w-[860px] w-full text-xs md:min-w-full">
            <thead>
              <tr className="border-b border-dark-800 text-left">
                {["Symbol", "Side", "Qty", "Entry", "Stop Loss", "Take Profit", "Conf.", "Opened", ""].map((h) => (
                  <th key={h} className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-dark-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((t) => (
                <tr key={t.id} className="border-b border-dark-800/50 hover:bg-white/[0.02] transition-colors">
                  <td className="px-4 py-3 font-mono font-semibold text-white">{t.symbol}</td>
                  <td className={`px-4 py-3 font-semibold ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>
                    {t.side}
                  </td>
                  <td className="px-4 py-3 font-mono text-dark-300 tabular-nums">{t.quantity}</td>
                  <td className="px-4 py-3 font-mono text-white tabular-nums">${t.entry_price?.toFixed(2)}</td>
                  <td className="px-4 py-3 font-mono text-red-400 tabular-nums">${t.stop_loss?.toFixed(2)}</td>
                  <td className="px-4 py-3 font-mono text-brand-400 tabular-nums">${t.take_profit?.toFixed(2)}</td>
                  <td className="px-4 py-3 text-dark-400 tabular-nums">{t.claude_confidence?.toFixed(0)}%</td>
                  <td className="px-4 py-3 text-dark-500">
                    {new Date(t.created_at).toLocaleDateString([], { month: "short", day: "numeric" })}{" "}
                    {new Date(t.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleClose(t)}
                      disabled={closing === t.id}
                      className="flex items-center gap-1.5 rounded-lg border border-red-500/20 px-2.5 py-1.5 text-xs text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-50"
                    >
                      {closing === t.id ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <XCircle size={11} />
                      )}
                      Close
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
