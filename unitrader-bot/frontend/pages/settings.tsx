import Head from "next/head";
import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/router";
import { ArrowLeft, AlertCircle, Loader, Check } from "lucide-react";
import { authApi } from "@/lib/api";
import CircuitBreakerAlert from "@/components/trade/CircuitBreakerAlert";

interface UserSettings {
  explanation_level?: string;
  trade_mode?: string;
  max_trade_amount?: number;
  max_daily_loss?: number;
  trading_paused?: boolean;
  leaderboard_opt_out?: boolean;
  approved_assets?: string[];
  first_trade_done?: boolean;
  push_token?: string;
}

export default function SettingsPage() {
  const { isSignedIn, isLoaded } = useAuth();
  const router = useRouter();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [dailyLossPct, setDailyLossPct] = useState(10);
  const [portfolioValue, setPortfolioValue] = useState(10000); // Default estimate
  const [isSaving, setIsSaving] = useState(false);

  // Load settings
  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      router.push("/login");
      return;
    }

    const loadSettings = async () => {
      try {
        setLoading(true);
        const response = await authApi.getSettings();
        const data = response.data;
        setSettings(data);
        setDailyLossPct(data.max_daily_loss || 10);
      } catch (err: any) {
        if (err.code === "ECONNABORTED" || err.message?.includes("timeout")) {
          setError("Settings took too long to load. Please refresh the page.");
        } else {
          setError(err.response?.data?.detail || "Failed to load settings");
        }
      } finally {
        setLoading(false);
      }
    };

    loadSettings();
  }, [isLoaded, isSignedIn, router]);

  // Debounced save handler
  const handleDailyLossChange = useCallback(
    (newValue: number) => {
      setDailyLossPct(newValue);
    },
    []
  );

  // Save daily loss setting with debounce
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (dailyLossPct !== (settings?.max_daily_loss || 10)) {
        try {
          setIsSaving(true);
          setError(null);
          await authApi.updateSettings({ max_daily_loss: dailyLossPct });
          setSettings(prev => prev ? { ...prev, max_daily_loss: dailyLossPct } : null);
          setSuccess("Daily loss limit updated");
          setTimeout(() => setSuccess(null), 3000);
        } catch (err: any) {
          setError(err.response?.data?.detail || "Failed to save settings");
        } finally {
          setIsSaving(false);
        }
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [dailyLossPct, settings?.max_daily_loss]);

  if (!isLoaded || loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-dark-950">
        <Loader className="animate-spin text-brand-500" size={32} />
      </div>
    );
  }

  if (error && !settings) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-dark-950 gap-4">
        <AlertCircle className="text-red-400" size={36} />
        <p className="text-white font-semibold">{error}</p>
        <button
          onClick={() => { setError(null); setLoading(true); authApi.getSettings().then(r => { setSettings(r.data); setDailyLossPct(r.data.max_daily_loss || 10); }).catch(e => setError(e.response?.data?.detail || "Failed to load settings")).finally(() => setLoading(false)); }}
          className="btn-primary px-6 py-2"
        >
          Try Again
        </button>
      </div>
    );
  }

  const calculatedLossAmount = (portfolioValue * dailyLossPct) / 100;
  const isTradingPaused = settings?.trading_paused || false;

  return (
    <>
      <Head>
        <title>Settings - Apex Trading</title>
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
              <h1 className="text-2xl font-bold text-white">Settings</h1>
              <p className="text-sm text-dark-400">Manage your trading preferences and safety controls</p>
            </div>
          </div>
        </div>

        <div className="max-w-4xl mx-auto px-6 py-8">
          {/* Global Error */}
          {error && (
            <div className="mb-6 flex items-start gap-3 rounded-lg bg-red-500/10 border border-red-500/30 p-4">
              <AlertCircle className="shrink-0 text-red-500 mt-0.5" size={18} />
              <div>
                <p className="text-sm font-medium text-red-500">{error}</p>
              </div>
            </div>
          )}

          {/* Global Success */}
          {success && (
            <div className="mb-6 flex items-start gap-3 rounded-lg bg-green-500/10 border border-green-500/30 p-4">
              <Check className="shrink-0 text-green-500 mt-0.5" size={18} />
              <div>
                <p className="text-sm font-medium text-green-500">{success}</p>
              </div>
            </div>
          )}

          {/* Circuit Breaker Alert */}
          {isTradingPaused && (
            <div className="mb-8">
              <CircuitBreakerAlert
                tradingPaused={true}
                dailyLossPct={0} // Will show actual trading paused message
                maxDailyLossPct={dailyLossPct}
              />
            </div>
          )}

          {/* Trading Safety Section */}
          <div className="rounded-lg border border-dark-800 bg-dark-900 p-6 mb-8">
            <div className="mb-6">
              <h2 className="text-xl font-bold text-white mb-2">Daily Loss Limit</h2>
              <p className="text-sm text-dark-400">
                Apex will automatically pause trading if your daily loss exceeds this limit. You can resume trading manually from this page.
              </p>
            </div>

            <div className="space-y-6">
              {/* Slider */}
              <div>
                <label className="block text-sm font-medium text-white mb-3">
                  Stop trading if I lose
                  <span className="ml-2 font-bold text-brand-500">{dailyLossPct}%</span>
                </label>

                <input
                  type="range"
                  min="1"
                  max="25"
                  step="1"
                  value={dailyLossPct}
                  onChange={(e) => handleDailyLossChange(parseInt(e.target.value))}
                  disabled={isSaving}
                  className="w-full h-2 bg-dark-800 rounded-lg appearance-none cursor-pointer slider accent-brand-500"
                />

                <div className="mt-3 p-3 rounded-lg bg-dark-800/50 border border-dark-700">
                  <p className="text-sm text-dark-300">
                    This equals <span className="font-bold text-brand-500">approximately £{calculatedLossAmount.toFixed(2)}</span> loss
                    <span className="text-dark-400"> (based on £{portfolioValue.toLocaleString()} portfolio)</span>
                  </p>
                </div>
              </div>

              {/* Quick presets */}
              <div>
                <label className="block text-sm font-medium text-white mb-2">Quick presets</label>
                <div className="flex flex-wrap gap-2">
                  {[5, 10, 15, 20].map((value) => (
                    <button
                      key={value}
                      onClick={() => handleDailyLossChange(value)}
                      disabled={isSaving}
                      className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
                        dailyLossPct === value
                          ? "bg-brand-500 text-white"
                          : "bg-dark-800 text-dark-300 hover:bg-dark-700 hover:text-white"
                      } disabled:opacity-50 disabled:cursor-not-allowed`}
                    >
                      {value}%
                    </button>
                  ))}
                </div>
              </div>

              {/* Status indicator */}
              {isTradingPaused && (
                <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 flex items-start gap-3">
                  <AlertCircle className="shrink-0 text-red-500 mt-0.5" size={16} />
                  <div>
                    <p className="text-sm font-medium text-red-400">Trading is currently paused</p>
                    <p className="text-xs text-red-400/70 mt-1">You've reached your daily loss limit. You can adjust your limit above or resume trading.</p>
                  </div>
                </div>
              )}

              {/* Saving indicator */}
              {isSaving && (
                <div className="flex items-center gap-2 text-sm text-dark-400">
                  <Loader className="animate-spin" size={16} />
                  Saving...
                </div>
              )}
            </div>
          </div>

          {/* Other Settings Sections (placeholder) */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Explanation Level */}
            <div className="rounded-lg border border-dark-800 bg-dark-900 p-6">
              <h3 className="text-lg font-semibold text-white mb-3">Trading Explanations</h3>
              <p className="text-sm text-dark-400 mb-4">How detailed should trade explanations be?</p>
              <select
                value={settings?.explanation_level || "detailed"}
                onChange={(e) => {
                  const newLevel = e.target.value;
                  authApi.updateSettings({ explanation_level: newLevel });
                  setSettings(prev => prev ? { ...prev, explanation_level: newLevel } : null);
                }}
                className="w-full px-3 py-2 rounded-lg bg-dark-800 border border-dark-700 text-white focus:outline-none focus:border-brand-500"
              >
                <option value="simple">Simple - Just the essentials</option>
                <option value="detailed">Detailed - Full analysis</option>
                <option value="metaphor">Metaphor - Easy to understand analogies</option>
              </select>
            </div>

            {/* Trade Mode */}
            <div className="rounded-lg border border-dark-800 bg-dark-900 p-6">
              <h3 className="text-lg font-semibold text-white mb-3">Trading Mode</h3>
              <p className="text-sm text-dark-400 mb-4">How should Apex execute trades?</p>
              <select
                value={settings?.trade_mode || "paper"}
                onChange={(e) => {
                  const newMode = e.target.value;
                  authApi.updateSettings({ trade_mode: newMode });
                  setSettings(prev => prev ? { ...prev, trade_mode: newMode } : null);
                }}
                className="w-full px-3 py-2 rounded-lg bg-dark-800 border border-dark-700 text-white focus:outline-none focus:border-brand-500"
              >
                <option value="paper">Paper Trading - Simulated</option>
                <option value="live">Live Trading - Real money</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        .slider::-webkit-slider-thumb {
          appearance: none;
          width: 20px;
          height: 20px;
          border-radius: 50%;
          background: #22c55e;
          cursor: pointer;
          box-shadow: 0 0 8px rgba(34, 197, 94, 0.3);
        }

        .slider::-moz-range-thumb {
          width: 20px;
          height: 20px;
          border-radius: 50%;
          background: #22c55e;
          cursor: pointer;
          border: none;
          box-shadow: 0 0 8px rgba(34, 197, 94, 0.3);
        }

        .slider:disabled::-webkit-slider-thumb {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .slider:disabled::-moz-range-thumb {
          opacity: 0.5;
          cursor: not-allowed;
        }
      `}</style>
    </>
  );
}
