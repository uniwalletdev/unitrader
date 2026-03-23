/**
 * ExchangeConnectWizard — Multi-step modal for connecting exchange APIs.
 *
 * Props:
 *   exchange: 'alpaca' | 'coinbase' | 'oanda'
 *   onSuccess: () => void — Called after successful connection
 *   onClose: () => void — Called when user closes wizard
 *
 * Flow:
 *   Step 1: Instructions to get API keys (exchange-specific)
 *   Step 2: Input credentials and test connection
 *   Step 3: Success confirmation with account details
 */

import { useState } from "react";
import { AlertCircle, CheckCircle, Copy, Eye, EyeOff, ExternalLink, Loader2, X } from "lucide-react";
import { exchangeApi } from "@/lib/api";

interface Props {
  exchange: "alpaca" | "coinbase" | "oanda";
  onSuccess: () => void;
  onClose: () => void;
}

const EXCHANGE_CONFIG = {
  alpaca: {
    name: "Alpaca",
    icon: "🦌",
    docsUrl: "https://app.alpaca.markets",
    instructions: [
      { step: 1, text: "Go to app.alpaca.markets" },
      { step: 2, text: 'Click "API Keys" in the left menu' },
      { step: 3, text: 'Click "Generate New Key"' },
    ],
    apiKeyLabel: "API Key ID",
    apiKeyPlaceholder: "PK...",
    secretLabel: "Secret Key",
    secretPlaceholder: "Your Alpaca secret key",
  },
  coinbase: {
    name: "Coinbase Advanced",
    icon: "🪙",
    docsUrl: "https://www.coinbase.com/settings/api",
    instructions: [
      { step: 1, text: "Go to coinbase.com and log in" },
      { step: 2, text: 'Click your profile → Settings → API' },
      { step: 3, text: 'Click "Create API Key" or "New API Key"' },
    ],
    apiKeyLabel: "API Key",
    apiKeyPlaceholder: "Your Coinbase API key",
    secretLabel: "Secret Key",
    secretPlaceholder: "Your Coinbase secret key",
  },
  oanda: {
    name: "OANDA",
    icon: "💱",
    docsUrl: "https://www.oanda.com/account/",
    instructions: [
      { step: 1, text: "Go to oanda.com and log in to your account" },
      { step: 2, text: 'Go to Settings → API Access' },
      { step: 3, text: 'Generate a new API token' },
    ],
    apiKeyLabel: "API Token",
    apiKeyPlaceholder: "Your OANDA API token",
    secretLabel: "Account ID",
    secretPlaceholder: "Your OANDA account ID (e.g., 101-001-...)",
  },
};

type Step = 1 | 2 | 3;

interface TestResult {
  success: boolean;
  accountId?: string;
  buyingPower?: number;
  currency?: string;
  message?: string;
  error?: string;
}

export default function ExchangeConnectWizard({ exchange, onSuccess, onClose }: Props) {
  const config = EXCHANGE_CONFIG[exchange];
  const [step, setStep] = useState<Step>(1);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [isPaper, setIsPaper] = useState(true);

  const handleSaveAndTest = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) {
      setError("Both API key and secret are required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Step 1: Save the API keys
      await exchangeApi.connect(exchange, apiKey, apiSecret, isPaper);

      // Step 2: Test the connection
      const testRes = await exchangeApi.testConnection(exchange);
      const data = testRes.data;

      if (data.success) {
        setTestResult({
          success: true,
          accountId: data.account_id,
          buyingPower: data.buying_power,
          currency: data.currency,
          message: data.message,
        });
        setStep(3);
      } else {
        setError(data.error || "Connection test failed");
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail || "Failed to save or test connection";
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  // ── STEP 1: INSTRUCTIONS ──────────────────────────────────────────────────
  if (step === 1) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-dark-950/90 backdrop-blur-sm p-4">
        <div className="w-full max-w-md rounded-2xl border border-dark-600 bg-dark-900 shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-dark-700 bg-dark-950 px-6 py-4">
            <div className="flex items-center gap-2">
              <span className="text-2xl">{config.icon}</span>
              <div>
                <h2 className="text-base font-bold text-white">Connect {config.name}</h2>
                <p className="text-xs text-dark-500 mt-0.5">Step 1 of 3</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-dark-500 hover:text-dark-300 transition"
              aria-label="Close"
            >
              <X size={20} />
            </button>
          </div>

          {/* Content */}
          <div className="p-6 space-y-6">
            <div>
              <h3 className="text-sm font-semibold text-white mb-3">Go to your {config.name} account:</h3>
              <ol className="space-y-2">
                {config.instructions.map((instr) => (
                  <li key={instr.step} className="flex gap-3 text-sm text-dark-300">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-500/20 text-xs font-semibold text-brand-400 flex-shrink-0">
                      {instr.step}
                    </span>
                    <span>{instr.text}</span>
                  </li>
                ))}
              </ol>
            </div>

            {/* Action buttons */}
            <div className="space-y-3 border-t border-dark-700 pt-4">
              <a
                href={config.docsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="w-full flex items-center justify-center gap-2 rounded-lg bg-brand-500/10 border border-brand-500/30 px-4 py-3 text-sm font-medium text-brand-400 hover:bg-brand-500/20 transition"
              >
                Open {config.name} <ExternalLink size={16} />
              </a>

              <button
                onClick={() => setStep(2)}
                className="w-full flex items-center justify-center gap-2 rounded-lg bg-brand-500 px-4 py-3 text-sm font-medium text-white hover:bg-brand-600 transition"
              >
                I have my API keys <span className="text-lg">→</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── STEP 2: ENTER CREDENTIALS ─────────────────────────────────────────────
  if (step === 2) {
    const bothFilled = apiKey.trim() && apiSecret.trim();

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-dark-950/90 backdrop-blur-sm p-4">
        <div className="w-full max-w-md rounded-2xl border border-dark-600 bg-dark-900 shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-dark-700 bg-dark-950 px-6 py-4">
            <div>
              <h2 className="text-base font-bold text-white">Enter your API keys</h2>
              <p className="text-xs text-dark-500 mt-0.5">Step 2 of 3</p>
            </div>
            <button
              onClick={onClose}
              className="text-dark-500 hover:text-dark-300 transition"
              aria-label="Close"
            >
              <X size={20} />
            </button>
          </div>

          {/* Content */}
          <div className="p-6 space-y-4">
            {error && (
              <div className="flex items-start gap-3 rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2">
                <AlertCircle size={14} className="text-red-400 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-red-400">{error}</p>
              </div>
            )}

            {/* API Key field */}
            <div>
              <label className="block text-xs font-medium text-dark-300 mb-1.5">
                {config.apiKeyLabel}
              </label>
              <input
                type="text"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setError(null);
                }}
                placeholder={config.apiKeyPlaceholder}
                className="input w-full text-sm font-mono"
                autoComplete="off"
              />
            </div>

            {/* Secret Key field */}
            <div>
              <label className="block text-xs font-medium text-dark-300 mb-1.5">
                {config.secretLabel}
              </label>
              <div className="relative">
                <input
                  type={showSecret ? "text" : "password"}
                  value={apiSecret}
                  onChange={(e) => {
                    setApiSecret(e.target.value);
                    setError(null);
                  }}
                  placeholder={config.secretPlaceholder}
                  className="input w-full pr-10 text-sm font-mono"
                  autoComplete="off"
                />
                <button
                  type="button"
                  onClick={() => setShowSecret(!showSecret)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-dark-500 hover:text-dark-300 transition"
                  aria-label={showSecret ? "Hide" : "Show"}
                >
                  {showSecret ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* Security note */}
            <p className="text-[10px] text-dark-500 border-t border-dark-700 pt-4 mt-4">
              Your API credentials are encrypted and stored securely. We only use them to execute trades on your behalf and will never share them with third parties.
            </p>

            {/* Paper / Live toggle */}
            <div className="flex items-center justify-between rounded-lg border border-dark-700 bg-dark-800/50 px-4 py-3">
              <div>
                <p className="text-xs font-medium text-white">{isPaper ? "Paper Trading" : "Live Trading"}</p>
                <p className="text-[10px] text-dark-500 mt-0.5">
                  {isPaper ? "Simulated trades — no real money at risk" : "Real-money trades — funds will be used"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsPaper((v) => !v)}
                className={`relative h-6 w-11 rounded-full transition-colors ${
                  isPaper ? "bg-amber-500" : "bg-emerald-500"
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
                    !isPaper ? "translate-x-5" : ""
                  }`}
                />
              </button>
            </div>
          </div>

          {/* Footer */}
          <div className="flex gap-3 border-t border-dark-700 bg-dark-950 px-6 py-4">
            <button
              onClick={() => {
                setStep(1);
                setError(null);
              }}
              className="flex-1 rounded-lg border border-dark-600 px-4 py-2 text-xs font-medium text-dark-300 hover:bg-dark-800 transition disabled:opacity-50"
              disabled={loading}
            >
              Back
            </button>
            <button
              onClick={handleSaveAndTest}
              disabled={!bothFilled || loading}
              className="flex-1 flex items-center justify-center gap-2 rounded-lg bg-brand-500 px-4 py-2 text-xs font-medium text-white hover:bg-brand-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              {loading ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  Testing connection...
                </>
              ) : (
                "Save and test connection"
              )}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── STEP 3: SUCCESS ───────────────────────────────────────────────────────
  if (step === 3 && testResult?.success) {
    const currency = testResult.currency || "USD";
    const buyingPower = testResult.buyingPower || 0;

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-dark-950/90 backdrop-blur-sm p-4">
        <div className="w-full max-w-md rounded-2xl border border-dark-600 bg-dark-900 shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-dark-700 bg-dark-950 px-6 py-4">
            <div>
              <h2 className="text-base font-bold text-white">Ready to trade</h2>
              <p className="text-xs text-dark-500 mt-0.5">Step 3 of 3</p>
            </div>
            <button
              onClick={onClose}
              className="text-dark-500 hover:text-dark-300 transition"
              aria-label="Close"
            >
              <X size={20} />
            </button>
          </div>

          {/* Content */}
          <div className="p-6 space-y-6">
            {/* Success checkmark */}
            <div className="flex justify-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-500/20 animate-in fade-in duration-500">
                <CheckCircle size={32} className="text-brand-400" />
              </div>
            </div>

            {/* Success message */}
            <div className="text-center space-y-2">
              <h3 className="text-lg font-bold text-white">
                Unitrader connected to {config.name} successfully
              </h3>
              <p className="text-sm text-dark-400">
                Unitrader is ready to start trading for you
              </p>
            </div>

            {/* Account details */}
            <div className="space-y-3 bg-dark-950/50 border border-dark-700 rounded-lg p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs text-dark-400">Account ID</span>
                <span className="text-xs font-mono text-white">{testResult.accountId || "—"}</span>
              </div>
              <div className="flex items-center justify-between border-t border-dark-700 pt-3">
                <span className="text-xs text-dark-400">Available balance</span>
                <span className="text-sm font-semibold text-brand-400">
                  {currency === "USD" ? "$" : currency === "GBP" ? "£" : currency} {buyingPower.toLocaleString()}
                </span>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="border-t border-dark-700 bg-dark-950 px-6 py-4">
            <button
              onClick={() => {
                onSuccess();
                onClose();
              }}
              className="w-full flex items-center justify-center gap-2 rounded-lg bg-brand-500 px-4 py-3 text-sm font-medium text-white hover:bg-brand-600 transition"
            >
              Start trading <span className="text-lg">→</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  return null;
}

