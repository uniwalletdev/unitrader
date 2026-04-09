import Head from "next/head";
import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/router";
import { ArrowLeft, AlertCircle, Loader, Check, Bell, Send } from "lucide-react";
import { authApi, notificationApi } from "@/lib/api";
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
  signal_stack_mode?: string;
  morning_briefing_enabled?: boolean;
  morning_briefing_time?: string;
  daily_digest_enabled?: boolean;
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
  const [telegramLinked, setTelegramLinked] = useState(false);
  const [telegramNotificationsEnabled, setTelegramNotificationsEnabled] = useState(false);
  const [whatsappLinked, setWhatsappLinked] = useState(false);
  const [whatsappNotificationsEnabled, setWhatsappNotificationsEnabled] = useState(false);
  const [linkingInProgress, setLinkingInProgress] = useState(false);

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
        const notifRes = await notificationApi.settings();
        setTelegramLinked(!!notifRes.data?.data?.telegram_linked);
        setTelegramNotificationsEnabled(!!notifRes.data?.data?.telegram_notifications_enabled);
        setWhatsappLinked(!!notifRes.data?.data?.whatsapp_linked);
        setWhatsappNotificationsEnabled(!!notifRes.data?.data?.whatsapp_notifications_enabled);
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
        <Loader className="animate-spin text-brand-400" size={20} />
      </div>
    );
  }

  if (error && !settings) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-dark-950 gap-5 px-6">
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-8 text-center max-w-sm">
          <AlertCircle className="text-red-400 mx-auto mb-4" size={28} />
          <p className="text-sm text-dark-300 mb-5">{error}</p>
          <button
            onClick={() => { setError(null); setLoading(true); authApi.getSettings().then(r => { setSettings(r.data); setDailyLossPct(r.data.max_daily_loss || 10); }).catch(e => setError(e.response?.data?.detail || "Failed to load settings")).finally(() => setLoading(false)); }}
            className="btn-primary w-full"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  const calculatedLossAmount = (portfolioValue * dailyLossPct) / 100;
  const isTradingPaused = settings?.trading_paused || false;
  const signalMode = settings?.signal_stack_mode || "browse";

  return (
    <>
      <Head>
        <title>Settings - Unitrader Trading</title>
      </Head>

      <div className="min-h-screen bg-dark-950">
        <div className="border-b border-dark-800/60 px-6 py-4">
          <div className="flex items-center gap-4 max-w-4xl mx-auto">
            <button
              onClick={() => router.push("/app")}
              className="rounded-xl p-2 text-dark-400 hover:bg-dark-800/50 hover:text-white transition-colors"
            >
              <ArrowLeft size={18} />
            </button>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white">Settings</h1>
              <p className="text-sm text-dark-400">Manage your trading preferences and safety controls</p>
            </div>
          </div>
        </div>

        <div className="max-w-4xl mx-auto px-6 py-8 space-y-6 animate-fade-in">
          {error && (
            <div className="flex items-start gap-3 rounded-2xl bg-red-500/[0.04] border border-red-500/15 p-4">
              <AlertCircle className="shrink-0 text-red-400 mt-0.5" size={16} />
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          {success && (
            <div className="flex items-start gap-3 rounded-2xl bg-brand-500/[0.06] border border-brand-500/15 p-4">
              <Check className="shrink-0 text-brand-400 mt-0.5" size={16} />
              <p className="text-sm text-brand-400">{success}</p>
            </div>
          )}

          {isTradingPaused && (
            <CircuitBreakerAlert
              tradingPaused={true}
              dailyLossPct={0}
              maxDailyLossPct={dailyLossPct}
            />
          )}

          <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-6">
            <div className="mb-6">
              <h2 className="text-lg font-bold tracking-tight text-white mb-1.5">Daily Loss Limit</h2>
              <p className="text-sm text-dark-400 leading-relaxed">
                Unitrader will automatically pause trading if your daily loss exceeds this limit. You can resume trading manually from this page.
              </p>
            </div>

            <div className="space-y-6">
              {/* Slider */}
              <div>
                <label className="block text-sm font-medium text-white mb-3">
                  Stop trading if I lose
                  <span className="ml-2 font-bold text-brand-400">{dailyLossPct}%</span>
                </label>

                <input
                  type="range"
                  min="1"
                  max="25"
                  step="1"
                  value={dailyLossPct}
                  onChange={(e) => handleDailyLossChange(parseInt(e.target.value))}
                  disabled={isSaving}
                  className="w-full h-1.5 bg-dark-800 rounded-lg appearance-none cursor-pointer slider"
                />

                <div className="mt-3 p-3 rounded-xl bg-dark-900/50 border border-dark-800/50">
                  <p className="text-sm text-dark-300">
                    This equals <span className="font-bold text-brand-400 tabular-nums">${calculatedLossAmount.toFixed(2)}</span> loss
                    <span className="text-dark-500"> (based on ${portfolioValue.toLocaleString()} portfolio)</span>
                  </p>
                </div>
              </div>

              <div>
                <p className="text-[11px] font-medium uppercase tracking-wider text-dark-500 mb-2">Quick presets</p>
                <div className="flex flex-wrap gap-2">
                  {[5, 10, 15, 20].map((value) => (
                    <button
                      key={value}
                      onClick={() => handleDailyLossChange(value)}
                      disabled={isSaving}
                      className={`px-3.5 py-1.5 rounded-xl text-xs font-medium transition-all ${
                        dailyLossPct === value
                          ? "bg-brand-500 text-black shadow-glow-sm"
                          : "bg-dark-800 text-dark-300 hover:bg-dark-700 hover:text-white border border-dark-700"
                      } disabled:opacity-50 disabled:cursor-not-allowed`}
                    >
                      {value}%
                    </button>
                  ))}
                </div>
              </div>

              {isTradingPaused && (
                <div className="p-3 rounded-xl bg-red-500/[0.04] border border-red-500/15 flex items-start gap-3">
                  <AlertCircle className="shrink-0 text-red-400 mt-0.5" size={15} />
                  <div>
                    <p className="text-sm font-medium text-red-400">Trading is currently paused</p>
                    <p className="text-xs text-red-400/60 mt-1">You've reached your daily loss limit. You can adjust your limit above or resume trading.</p>
                  </div>
                </div>
              )}

              {isSaving && (
                <div className="flex items-center gap-2 text-xs text-dark-400">
                  <Loader className="animate-spin" size={14} />
                  Saving...
                </div>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
              <h3 className="text-sm font-semibold text-white mb-1.5">Trading Explanations</h3>
              <p className="text-xs text-dark-400 mb-4">How detailed should trade explanations be?</p>
              <select
                value={settings?.explanation_level || "detailed"}
                onChange={(e) => {
                  const newLevel = e.target.value;
                  authApi.updateSettings({ explanation_level: newLevel });
                  setSettings(prev => prev ? { ...prev, explanation_level: newLevel } : null);
                }}
                className="input text-sm"
              >
                <option value="simple">Simple - Just the essentials</option>
                <option value="detailed">Detailed - Full analysis</option>
                <option value="metaphor">Metaphor - Easy to understand analogies</option>
              </select>
            </div>

            <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
              <h3 className="text-sm font-semibold text-white mb-1.5">Trading Mode</h3>
              <p className="text-xs text-dark-400 mb-4">How should Unitrader execute trades?</p>
              <select
                value={settings?.trade_mode || "paper"}
                onChange={(e) => {
                  const newMode = e.target.value;
                  authApi.updateSettings({ trade_mode: newMode });
                  setSettings(prev => prev ? { ...prev, trade_mode: newMode } : null);
                }}
                className="input text-sm"
              >
                <option value="paper">Paper Trading - Simulated</option>
                <option value="live">Live Trading - Real money</option>
              </select>
            </div>
          </div>

          <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-6">
            <div className="mb-5 flex items-center gap-2">
              <Bell size={15} className="text-brand-400" />
              <div>
                <h2 className="text-lg font-bold tracking-tight text-white">Notifications</h2>
                <p className="text-sm text-dark-400">How Unitrader should keep you updated.</p>
              </div>
            </div>

            <div className="space-y-5">
              {signalMode === "browse" && (
                <div className="rounded-xl border border-dark-800 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-white">Send me a morning briefing</p>
                      <p className="text-xs text-dark-500">Unitrader sends your top signals before the day starts.</p>
                    </div>
                    <input
                      type="checkbox"
                      checked={settings?.morning_briefing_enabled ?? true}
                      onChange={async (e) => {
                        const next = e.target.checked;
                        setSettings((prev) => prev ? { ...prev, morning_briefing_enabled: next } : prev);
                        await authApi.updateSettings({ morning_briefing_enabled: next });
                      }}
                    />
                  </div>
                  {(settings?.morning_briefing_enabled ?? true) && (
                    <select
                      value={settings?.morning_briefing_time || "08:00"}
                      onChange={async (e) => {
                        const next = e.target.value;
                        setSettings((prev) => prev ? { ...prev, morning_briefing_time: next } : prev);
                        await authApi.updateSettings({ morning_briefing_time: next });
                      }}
                      className="input text-sm"
                    >
                      <option value="06:00">6am</option>
                      <option value="07:00">7am</option>
                      <option value="08:00">8am</option>
                      <option value="09:00">9am</option>
                    </select>
                  )}
                </div>
              )}

              <div className="rounded-xl border border-dark-800 p-4">
                <p className="mb-3 text-sm font-medium text-white">Notification channels</p>
                <div className="space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Send size={14} className="text-sky-400" />
                      <div>
                        <p className="text-sm text-white">Telegram notifications</p>
                        <p className="text-xs text-dark-500">{telegramLinked ? "Unitrader can alert you on Telegram." : "Connect Telegram to receive Unitrader alerts."}</p>
                      </div>
                    </div>
                    {telegramLinked ? (
                      <input
                        type="checkbox"
                        checked={telegramNotificationsEnabled}
                        onChange={async (e) => {
                          const next = e.target.checked;
                          setTelegramNotificationsEnabled(next);
                          await notificationApi.updateSettings({ telegram_notifications_enabled: next });
                        }}
                      />
                    ) : (
                      <button
                        type="button"
                        disabled={linkingInProgress}
                        onClick={async () => {
                          if (linkingInProgress) return;
                          setLinkingInProgress(true);
                          try {
                            const [infoRes, codeRes] = await Promise.all([
                              authApi.botInfo(),
                              authApi.telegramCode(),
                            ]);
                            const bot = infoRes.data?.telegram_bot_username;
                            const code = codeRes.data?.code;
                            if (bot && code) {
                              window.open(`https://t.me/${bot}?start=link_${code}`, "_blank");
                            } else {
                              setError("Telegram is not configured. Please try again later.");
                            }
                          } catch {
                            setError("Could not generate linking code. Please try again.");
                          } finally {
                            setLinkingInProgress(false);
                          }
                        }}
                        className="rounded-lg border border-dark-700 px-3 py-1.5 text-xs text-brand-400 disabled:opacity-50"
                      >
                        Connect Telegram
                      </button>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Send size={14} className="text-emerald-400" />
                      <div>
                        <p className="text-sm text-white">WhatsApp notifications</p>
                        <p className="text-xs text-dark-500">{whatsappLinked ? "Unitrader can alert you on WhatsApp." : "Connect WhatsApp to receive Unitrader alerts."}</p>
                      </div>
                    </div>
                    {whatsappLinked ? (
                      <input
                        type="checkbox"
                        checked={whatsappNotificationsEnabled}
                        onChange={async (e) => {
                          const next = e.target.checked;
                          setWhatsappNotificationsEnabled(next);
                          await notificationApi.updateSettings({ whatsapp_notifications_enabled: next });
                        }}
                      />
                    ) : (
                      <button
                        type="button"
                        disabled={linkingInProgress}
                        onClick={async () => {
                          if (linkingInProgress) return;
                          setLinkingInProgress(true);
                          try {
                            const [infoRes, codeRes] = await Promise.all([
                              authApi.botInfo(),
                              authApi.whatsappCode(),
                            ]);
                            const num = infoRes.data?.whatsapp_number;
                            const code = codeRes.data?.code;
                            if (num && code) {
                              const clean = num.replace(/\D/g, "");
                              window.open(`https://wa.me/${clean}?text=${encodeURIComponent("LINK " + code)}`, "_blank");
                            } else {
                              setError("WhatsApp is not configured. Please try again later.");
                            }
                          } catch {
                            setError("Could not generate linking code. Please try again.");
                          } finally {
                            setLinkingInProgress(false);
                          }
                        }}
                        className="rounded-lg border border-dark-700 px-3 py-1.5 text-xs text-brand-400 disabled:opacity-50"
                      >
                        Connect WhatsApp
                      </button>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm text-white">Push notifications</p>
                      <p className="text-xs text-dark-500">
                        On the web, alerts use email and linked Telegram/WhatsApp. Native push is available when you use the
                        mobile app and register a device token (stored as push_token).
                      </p>
                    </div>
                    <input type="checkbox" disabled checked={!!settings?.push_token} title="Enabled when a mobile device registers push" />
                  </div>
                </div>
              </div>

              {signalMode === "full_auto" && (
                <div className="rounded-xl border border-dark-800 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-white">Daily digest at 8am</p>
                      <p className="text-xs text-dark-500">Unitrader sends a daily summary of all activity.</p>
                    </div>
                    <input
                      type="checkbox"
                      checked={settings?.daily_digest_enabled ?? true}
                      onChange={async (e) => {
                        const next = e.target.checked;
                        setSettings((prev) => prev ? { ...prev, daily_digest_enabled: next } : prev);
                        await authApi.updateSettings({ daily_digest_enabled: next });
                      }}
                    />
                  </div>
                </div>
              )}

              <div className="rounded-xl border border-brand-500/20 bg-brand-500/[0.05] p-4">
                <p className="text-sm font-medium text-white">Trade alerts</p>
                <p className="mt-1 text-xs leading-relaxed text-dark-400">
                  Unitrader always notifies you immediately after every trade. This cannot be disabled — it is your safety net.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

    </>
  );
}
