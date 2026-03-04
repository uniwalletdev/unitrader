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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp size={18} className="text-brand-400" />
          <h1 className="text-xl font-bold text-white">Open Positions</h1>
          <span className="rounded-full bg-dark-800 px-2.5 py-0.5 text-xs font-medium text-dark-300">
            {positions.length}
          </span>
        </div>
        <button onClick={load} className="btn-outline gap-2 py-2 text-xs">
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
          <h2 className="text-lg font-semibold text-white">No Open Positions</h2>
          <p className="text-sm text-dark-400">
            Your AI hasn't opened any trades yet. Go to the Trade tab to analyze a market and execute.
          </p>
          <button onClick={() => onNavigate?.("trade")} className="btn-primary">
            <Crosshair size={14} /> Start Trading
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-dark-800 bg-dark-950">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-dark-800 text-left text-dark-500">
                {["Symbol", "Side", "Qty", "Entry", "Stop Loss", "Take Profit", "Confidence", "Opened", ""].map((h) => (
                  <th key={h} className="px-4 py-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((t) => (
                <tr key={t.id} className="border-b border-dark-900 hover:bg-dark-900/50">
                  <td className="px-4 py-3 font-mono font-medium text-white">{t.symbol}</td>
                  <td className={`px-4 py-3 font-semibold ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>
                    {t.side}
                  </td>
                  <td className="px-4 py-3 font-mono text-dark-300">{t.quantity}</td>
                  <td className="px-4 py-3 font-mono text-white">${t.entry_price?.toLocaleString()}</td>
                  <td className="px-4 py-3 font-mono text-red-400">${t.stop_loss?.toLocaleString()}</td>
                  <td className="px-4 py-3 font-mono text-brand-400">${t.take_profit?.toLocaleString()}</td>
                  <td className="px-4 py-3 text-dark-400">{t.claude_confidence?.toFixed(0)}%</td>
                  <td className="px-4 py-3 text-dark-500">
                    {new Date(t.created_at).toLocaleDateString()}{" "}
                    {new Date(t.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleClose(t)}
                      disabled={closing === t.id}
                      className="flex items-center gap-1 rounded-md border border-red-500/30 px-2.5 py-1.5 text-xs text-red-400 transition hover:bg-red-500/10 disabled:opacity-50"
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
