import { useLivePrice } from "@/hooks/useLivePrice";
import { formatPrice, formatChangePct } from "@/utils/formatPrice";
import { TrendingUp, TrendingDown } from "lucide-react";

interface BrandPickerProps {
  symbol: string;
  exchange: string;
  isSelected?: boolean;
  onClick?: () => void;
}

/**
 * BrandPicker — Card component showing asset with live price
 * 
 * Usage:
 *   <BrandPicker symbol="AAPL" exchange="alpaca" isSelected={selected === "AAPL"} onClick={() => setSelected("AAPL")} />
 */
export default function BrandPicker({
  symbol,
  exchange,
  isSelected = false,
  onClick,
}: BrandPickerProps) {
  const livePrice = useLivePrice(symbol);
  const changePctData = formatChangePct(livePrice.changePct);

  return (
    <button
      onClick={onClick}
      className={`relative rounded-lg border-2 p-4 transition-all duration-200 ${
        isSelected
          ? "border-brand-500 bg-brand-500/10 ring-2 ring-brand-500/30"
          : "border-dark-700 bg-dark-900 hover:border-dark-600"
      }`}
    >
      {/* Header: Symbol and Exchange */}
      <div className="mb-3 flex items-start justify-between">
        <div className="text-left">
          <p className="text-sm font-bold text-white">{symbol.toUpperCase()}</p>
          <p className="text-xs text-dark-400">
            {exchange.charAt(0).toUpperCase() + exchange.slice(1)}
          </p>
        </div>

        {/* Connection status indicator */}
        <div className={`h-2 w-2 rounded-full ${livePrice.isConnected ? "bg-green-500" : "bg-red-500"}`} />
      </div>

      {/* Price display */}
      <div className="mb-3 space-y-1">
        <p className="text-lg font-bold text-white">
          {livePrice.price !== null
            ? formatPrice(livePrice.price, symbol)
            : "—"}
        </p>

        {/* Bid/Ask */}
        {livePrice.bid !== null && livePrice.ask !== null && (
          <p className="text-xs text-dark-400">
            {formatPrice(livePrice.bid, symbol)} / {formatPrice(livePrice.ask, symbol)}
          </p>
        )}
      </div>

      {/* Change percentage with color */}
      {livePrice.changePct !== null && (
        <div className="flex items-center gap-1">
          {livePrice.changePct >= 0 ? (
            <TrendingUp size={14} style={{ color: changePctData.color }} />
          ) : (
            <TrendingDown size={14} style={{ color: changePctData.color }} />
          )}
          <span style={{ color: changePctData.color }} className="text-sm font-semibold">
            {changePctData.text}
          </span>
        </div>
      )}

      {/* Connection status text */}
      {!livePrice.isConnected && (
        <p className="mt-2 text-xs text-red-400">Connecting...</p>
      )}
    </button>
  );
}
