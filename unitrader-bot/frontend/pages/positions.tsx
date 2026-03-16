import Head from "next/head";
import { useState, useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/router";
import { ArrowLeft, TrendingUp, TrendingDown, Loader, RefreshCw } from "lucide-react";
import { tradingApi } from "@/lib/api";
import { useLivePrice } from "@/hooks/useLivePrice";
import { formatPrice } from "@/utils/formatPrice";

interface Position {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  current_price?: number;
  stop_loss: number;
  take_profit: number;
  created_at: string;
  unrealised_pnl?: number;
  unrealised_pnl_pct?: number;
}

export default function PositionsPage() {
  const { isSignedIn, isLoaded } = useAuth();
  const router = useRouter();
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load open positions
  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      router.push("/login");
      return;
    }

    const loadPositions = async () => {
      try {
        setLoading(true);
        const response = await tradingApi.openPositions();
        setPositions(response.data.data || []);
      } catch (err: any) {
        setError(err.response?.data?.detail || "Failed to load positions");
      } finally {
        setLoading(false);
      }
    };

    loadPositions();
  }, [isLoaded, isSignedIn, router]);

  if (!isLoaded || loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-dark-950">
        <Loader className="animate-spin text-brand-500" size={32} />
      </div>
    );
  }

  return (
    <>
      <Head>
        <title>Open Positions - Apex Trading</title>
      </Head>

      <div className="min-h-screen bg-dark-950">
        {/* Header */}
        <div className="border-b border-dark-800 bg-dark-900 px-6 py-4">
          <div className="flex items-center gap-4 mb-4">
            <button
              onClick={() => router.push("/app")}
              className="rounded-lg p-2 text-dark-400 hover:bg-dark-800 hover:text-white transition-colors"
            >
              <ArrowLeft size={20} />
            </button>
            <div>
              <h1 className="text-2xl font-bold text-white">Open Positions</h1>
              <p className="text-sm text-dark-400">Monitor your active trades and unrealised P&L</p>
            </div>
          </div>
        </div>

        <div className="max-w-6xl mx-auto px-6 py-8">
          {/* Error message */}
          {error && (
            <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
              {error}
            </div>
          )}

          {/* Empty state */}
          {positions.length === 0 ? (
            <div className="text-center py-12">
              <TrendingUp className="mx-auto mb-4 text-dark-500" size={48} />
              <h3 className="text-lg font-semibold text-white mb-2">No Open Positions</h3>
              <p className="text-sm text-dark-400">You don't have any active trades yet. Start by executing a trade in the Trade tab.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Summary cards */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
                <div className="rounded-lg border border-dark-800 bg-dark-900 p-4">
                  <p className="text-xs text-dark-400 mb-1">Total Positions</p>
                  <p className="text-2xl font-bold text-white">{positions.length}</p>
                </div>
                <div className="rounded-lg border border-dark-800 bg-dark-900 p-4">
                  <p className="text-xs text-dark-400 mb-1">Total Unrealised P&L</p>
                  <p className="text-2xl font-bold text-green-400">
                    £{positions.reduce((sum, p) => sum + (p.unrealised_pnl || 0), 0).toFixed(2)}
                  </p>
                </div>
                <div className="rounded-lg border border-dark-800 bg-dark-900 p-4">
                  <p className="text-xs text-dark-400 mb-1">Winning Trades</p>
                  <p className="text-2xl font-bold text-white">
                    {positions.filter(p => (p.unrealised_pnl || 0) > 0).length}
                  </p>
                </div>
              </div>

              {/* Positions table */}
              <div className="rounded-lg border border-dark-800 overflow-hidden">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-dark-800 bg-dark-900">
                      <th className="px-4 py-3 text-left text-xs font-semibold text-dark-400">Symbol</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-dark-400">Side</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-dark-400">Quantity</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-dark-400">Entry</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-dark-400">Current</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-dark-400">Unrealised P&L</th>
                      <th className="px-4 py-3 text-center text-xs font-semibold text-dark-400">SL / TP</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-dark-800">
                    {positions.map((position) => (
                      <PositionRow key={position.id} position={position} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function PositionRow({ position }: { position: Position }) {
  const livePrice = useLivePrice(position.symbol);
  const currentPrice = livePrice.price || position.current_price || position.entry_price;
  const pnl = (currentPrice - position.entry_price) * position.quantity;
  const pnlPct = ((currentPrice - position.entry_price) / position.entry_price) * 100;
  const isWinning = pnl > 0;

  return (
    <tr className="border-dark-800 hover:bg-dark-900 transition-colors">
      <td className="px-4 py-3">
        <div>
          <p className="text-sm font-bold text-white">{position.symbol}</p>
          <p className="text-xs text-dark-400">{new Date(position.created_at).toLocaleDateString()}</p>
        </div>
      </td>
      <td className="px-4 py-3">
        <div className={`flex items-center gap-1 w-fit rounded px-2 py-1 ${
          position.side === 'BUY'
            ? 'bg-brand-500/10 text-brand-400'
            : 'bg-red-500/10 text-red-400'
        }`}>
          {position.side === 'BUY' ? (
            <TrendingUp size={14} />
          ) : (
            <TrendingDown size={14} />
          )}
          <span className="text-xs font-semibold">{position.side}</span>
        </div>
      </td>
      <td className="px-4 py-3 text-right text-sm text-white">{position.quantity}</td>
      <td className="px-4 py-3 text-right text-sm text-white">{formatPrice(position.entry_price, position.symbol)}</td>
      <td className="px-4 py-3 text-right text-sm font-semibold">
        <span className={livePrice.isConnected ? 'text-white' : 'text-dark-400'}>
          {formatPrice(currentPrice, position.symbol)}
        </span>
        {!livePrice.isConnected && <span className="text-xs text-dark-500"> (delayed)</span>}
      </td>
      <td className={`px-4 py-3 text-right text-sm font-bold ${isWinning ? 'text-green-400' : 'text-red-400'}`}>
        £{pnl.toFixed(2)}
        <span className="text-xs ml-1">({isWinning ? '+' : ''}{pnlPct.toFixed(2)}%)</span>
      </td>
      <td className="px-4 py-3 text-center text-xs">
        <div className="flex items-center justify-center gap-2">
          <span className="text-dark-400">{formatPrice(position.stop_loss, position.symbol)}</span>
          <span className="text-dark-600">/</span>
          <span className="text-dark-400">{formatPrice(position.take_profit, position.symbol)}</span>
        </div>
      </td>
    </tr>
  );
}
