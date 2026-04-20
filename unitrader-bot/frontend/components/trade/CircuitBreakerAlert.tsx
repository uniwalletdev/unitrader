import { useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { authApi } from "@/lib/api";

interface CircuitBreakerAlertProps {
  tradingPaused: boolean;
  dailyLossPct: number;
  maxDailyLossPct: number;
  /** User's personalised bot name */
  botName?: string;
}

/**
 * Stop-sign SVG icon
 */
function StopSignIcon() {
  return (
    <svg
      className="w-6 h-6"
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M2.6 8.4L8.4 2.6C9.2 1.8 10.4 1.8 11.2 2.6L21.4 12.8C22.2 13.6 22.2 14.8 21.4 15.6L15.6 21.4C14.8 22.2 13.6 22.2 12.8 21.4L2.6 11.2C1.8 10.4 1.8 9.2 2.6 8.4Z" />
      <text
        x="12"
        y="15"
        textAnchor="middle"
        fontSize="8"
        fontWeight="bold"
        fill="white"
      >
        STOP
      </text>
    </svg>
  );
}

export default function CircuitBreakerAlert({
  tradingPaused,
  dailyLossPct,
  maxDailyLossPct,
  botName = "Unitrader",
}: CircuitBreakerAlertProps) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!tradingPaused) {
    return null;
  }

  const handleResume = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await authApi.updateSettings({ trading_paused: false });
      // Reload page or invalidate cache
      window.location.reload();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to resume trading");
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed top-0 left-0 right-0 z-50 w-full">
      {/* Red Banner */}
      <div className="w-full px-4 py-4 border-l-4 border-red-500 bg-red-500/10">
        <div className="max-w-6xl mx-auto">
          {/* Header with icon and text */}
          <div className="flex items-start gap-3 mb-3">
            <div className="text-red-500 flex-shrink-0 mt-0.5">
              <StopSignIcon />
            </div>
            <div className="flex-1">
              <p className="text-red-500 font-semibold text-sm sm:text-base">
                {botName} has paused trading — your daily loss limit of{" "}
                <span className="font-bold">{maxDailyLossPct}%</span> was
                reached today (
                <span className="font-bold">{dailyLossPct.toFixed(1)}%</span>
                {" "}loss so far)
              </p>
              {error && (
                <p className="text-red-600 text-xs mt-1">{error}</p>
              )}
            </div>
          </div>

          {/* Buttons */}
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => {
                if (typeof window === "undefined") return;
                window.location.href = "/settings#trading-safety";
              }}
              className="px-4 py-2 bg-red-500 text-white text-sm font-medium rounded-xl hover:bg-red-600 transition-colors"
            >
              Adjust my limit
            </button>
            <button
              onClick={() => setShowConfirm(true)}
              disabled={isLoading}
              className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-xl hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Resuming...
                </>
              ) : (
                "Resume for today"
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Confirmation Dialog */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-[#0d1117] rounded-2xl p-6 max-w-sm mx-4 border border-dark-800">
            <h3 className="text-lg font-semibold text-white mb-2">
              Resume trading?
            </h3>
            <p className="text-dark-400 text-sm mb-4">
              Are you sure? This overrides your safety limit.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                disabled={isLoading}
                className="flex-1 px-4 py-2 bg-dark-800 text-dark-200 text-sm font-medium rounded-xl hover:bg-dark-700 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleResume}
                disabled={isLoading}
                className="flex-1 px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-xl hover:bg-red-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Resuming...
                  </>
                ) : (
                  "Yes, resume"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
