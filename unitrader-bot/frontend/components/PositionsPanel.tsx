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
        <Loader2 size={16} className="mr-2 animate-spin" /> Loading positions...
      </div>
    );
  }

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 md:gap-4">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="md:size-[18px] text-brand-400" />
          <h1 className="text-base md:text-xl font-bold text-white">Open Positions</h1>
          <span className="rounded-full bg-dark-800 px-2 md:px-2.5 py-0.5 text-xs font-medium text-dark-300">
            {positions.length}
          </span>
        </div>
        <button onClick={load} className="btn-outline gap-2 py-2 text-xs touch-target w-full md:w-auto">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {message && (
        <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${
          message.type === "success" ? "bg-brand-500/10 text-brand-400" : "bg-red-500/10 text-red-400"
        }`}>
          {message.type === "success" ? <TrendingUp size={13} /> : <AlertTriangle size={13} />}
          {message.text}
        </div>
      )}

      {positions.length === 0 ? (
        <div className="mx-auto max-w-md space-y-4 py-16 text-center">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-dark-900">
            <Crosshair size={28} className="text-dark-500" />
          </div>
          <h2 className="text-base md:text-lg font-semibold text-white">No Open Positions</h2>
          <p className="text-xs md:text-sm text-dark-400">
            Your AI hasn't opened any trades yet. Go to the Trade tab to analyze a market and execute.
          </p>
          <button onClick={() => onNavigate?.("trade")} className="btn-primary text-xs md:text-sm py-2 md:py-3 w-full md:w-auto">
            <Crosshair size={14} /> Start Trading
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 -mx-3 md:mx-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-dark-800 text-left text-dark-500">
                {["Symbol", "Side", "Qty", "Entry", "Stop Loss", "Take Profit", "Conf.", "Opened", ""].map((h) => (
                  <th key={h} className="px-2 md:px-4 py-2 md:py-3 font-medium text-xs md:text-sm">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((t) => (
                <tr key={t.id} className="border-b border-dark-900 hover:bg-dark-900/50">
                  <td className="px-2 md:px-4 py-2 md:py-3 font-mono font-medium text-white text-xs md:text-sm">{t.symbol}</td>
                  <td className={`px-2 md:px-4 py-2 md:py-3 font-semibold text-xs md:text-sm ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>
                    {t.side}
                  </td>
                  <td className="px-2 md:px-4 py-2 md:py-3 font-mono text-dark-300 text-xs md:text-sm">{t.quantity}</td>
                  <td className="px-2 md:px-4 py-2 md:py-3 font-mono text-white text-xs md:text-sm">${t.entry_price?.toFixed(2)}</td>
                  <td className="px-2 md:px-4 py-2 md:py-3 font-mono text-red-400 text-xs md:text-sm">${t.stop_loss?.toFixed(2)}</td>
                  <td className="px-2 md:px-4 py-2 md:py-3 font-mono text-brand-400 text-xs md:text-sm">${t.take_profit?.toFixed(2)}</td>
                  <td className="px-2 md:px-4 py-2 md:py-3 text-dark-400 text-xs md:text-sm">{t.claude_confidence?.toFixed(0)}%</td>
                  <td className="px-2 md:px-4 py-2 md:py-3 text-dark-500 text-xs md:text-sm">
                    {new Date(t.created_at).toLocaleDateString([], { month: "short", day: "numeric" })}{" "}
                    {new Date(t.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className="px-2 md:px-4 py-2 md:py-3">
                    <button
                      onClick={() => handleClose(t)}
                      disabled={closing === t.id}
                      className="flex items-center gap-1 rounded-md border border-red-500/30 px-2 md:px-2.5 py-1 md:py-1.5 text-xs text-red-400 transition hover:bg-red-500/10 disabled:opacity-50 touch-target"
                    >
                      {closing === t.id ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <XCircle size={11} />
                      )}
                      <span className="hidden md:inline">Close</span>
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
