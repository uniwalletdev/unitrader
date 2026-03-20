import Head from "next/head";
import { useState, useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/router";
import {
  Link2,
  Unlink,
  Eye,
  EyeOff,
  CheckCircle,
  AlertCircle,
  Loader2,
  ExternalLink,
  ArrowLeft,
  Shield,
  ToggleLeft,
  ToggleRight,
  TrendingUp,
} from "lucide-react";
import { exchangeApi, type ConnectedExchange } from "@/lib/api";
import NeverHoldBanner from "@/components/layout/NeverHoldBanner";

const EXCHANGES = [
  {
    id: "alpaca",
    name: "Alpaca",
    tagline: "Stocks & ETFs",
    description:
      "Trade US equities and ETFs commission-free. Supports paper trading for risk-free practice.",
    color: "brand",
    signupUrl: "https://app.alpaca.markets/signup",
    docsUrl: "https://app.alpaca.markets/paper/dashboard/overview",
    keyLabel: "API Key ID",
    keyPlaceholder: "PK...",
    secretLabel: "Secret Key",
    secretPlaceholder: "Your Alpaca secret key",
  },
  {
    id: "binance",
    name: "Binance",
    tagline: "Crypto",
    description:
      "Access the world's largest crypto exchange. Trade BTC, ETH, and hundreds of altcoins.",
    color: "yellow",
    signupUrl: "https://accounts.binance.com/register",
    docsUrl: "https://www.binance.com/en/my/settings/api-management",
    keyLabel: "API Key",
    keyPlaceholder: "Your Binance API key",
    secretLabel: "Secret Key",
    secretPlaceholder: "Your Binance secret key",
  },
  {
    id: "oanda",
    name: "OANDA",
    tagline: "Forex",
    description:
      "Trade major, minor and exotic forex pairs. Practice accounts available for all users.",
    color: "blue",
    signupUrl: "https://www.oanda.com/apply/",
    docsUrl: "https://www.oanda.com/account/",
    keyLabel: "API Token",
    keyPlaceholder: "Your OANDA API token",
    secretLabel: "Account ID",
    secretPlaceholder: "e.g. 001-001-12345-001",
  },
  {
    id: "coinbase",
    name: "Coinbase",
    tagline: "Crypto",
    description:
      "Trade Bitcoin, Ethereum and hundreds of crypto assets on one of the world's most trusted exchanges.",
    color: "blue",
    signupUrl: "https://www.coinbase.com/signup",
    docsUrl: "https://www.coinbase.com/settings/api",
    keyLabel: "API Key",
    keyPlaceholder: "Your Coinbase API key",
    secretLabel: "API Secret",
    secretPlaceholder: "Your Coinbase API secret",
  },
] as const;

type ExchangeId = (typeof EXCHANGES)[number]["id"];

export default function ConnectExchangePage() {
  const { isLoaded, isSignedIn } = useAuth();
  const router = useRouter();

  const [connected, setConnected] = useState<ConnectedExchange[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<ExchangeId | null>(null);

  const [formKey, setFormKey] = useState("");
  const [formSecret, setFormSecret] = useState("");
  const [isPaper, setIsPaper] = useState(true);
  const [showKey, setShowKey] = useState(false);
  const [showSecret, setShowSecret] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  useEffect(() => {
    if (isLoaded && !isSignedIn) {
      router.replace("/login");
    }
  }, [isLoaded, isSignedIn, router]);

  const loadConnected = async () => {
    try {
      const res = await exchangeApi.list();
      setConnected(res.data.data || []);
    } catch {
      setConnected([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isSignedIn) loadConnected();
  }, [isSignedIn]);

  const isConnected = (id: string) => connected.some((c) => c.exchange === id);
  const getConnection = (id: string) => connected.find((c) => c.exchange === id);

  const resetForm = () => {
    setFormKey("");
    setFormSecret("");
    setIsPaper(true);
    setShowKey(false);
    setShowSecret(false);
    setMessage(null);
  };

  const handleExpand = (id: ExchangeId) => {
    if (expandedId === id) {
      setExpandedId(null);
      resetForm();
    } else {
      setExpandedId(id);
      resetForm();
    }
  };

  const handleConnect = async (exchangeId: string) => {
    if (!formKey.trim() || !formSecret.trim()) {
      setMessage({ type: "error", text: "Both fields are required." });
      return;
    }

    setSubmitting(true);
    setMessage(null);
    try {
      const res = await exchangeApi.connect(exchangeId, formKey.trim(), formSecret.trim(), isPaper);
      const data = res.data.data;
      setMessage({
        type: "success",
        text: `${data.message}${data.balance_usd != null ? ` Balance: $${data.balance_usd.toLocaleString()}` : ""}`,
      });
      resetForm();
      setExpandedId(null);
      await loadConnected();
    } catch (err: any) {
      const detail =
        err.response?.data?.detail || "Connection failed. Check your keys and try again.";
      setMessage({ type: "error", text: detail });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDisconnect = async (exchangeId: string) => {
    if (!confirm(`Disconnect ${exchangeId}? You can reconnect later.`)) return;
    setDisconnecting(exchangeId);
    setMessage(null);
    try {
      await exchangeApi.disconnect(exchangeId);
      setMessage({
        type: "success",
        text: `${exchangeId.charAt(0).toUpperCase() + exchangeId.slice(1)} disconnected.`,
      });
      await loadConnected();
    } catch {
      setMessage({ type: "error", text: "Failed to disconnect. Please try again." });
    } finally {
      setDisconnecting(null);
    }
  };

  if (!isLoaded || !isSignedIn) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-dark-950">
        <Loader2 className="h-6 w-6 animate-spin text-brand-400" />
      </div>
    );
  }

  return (
    <>
      <Head>
        <title>Connect Exchange | Unitrader</title>
      </Head>

      <div className="min-h-screen bg-dark-950">
        <header className="border-b border-dark-800/60">
          <div className="mx-auto flex max-w-5xl items-center gap-4 px-6 py-4">
            <button
              onClick={() => router.push("/app")}
              className="flex items-center gap-2 text-sm text-dark-400 transition-colors hover:text-white"
            >
              <ArrowLeft size={15} />
              Back to Dashboard
            </button>
          </div>
        </header>

        <main className="mx-auto max-w-5xl px-6 py-10 animate-fade-in">
          <div className="mb-8">
            <h1 className="page-title text-2xl">Connect Exchange</h1>
            <p className="page-subtitle">Link your brokerage accounts to enable AI-powered trading</p>
          </div>

          <div className="mb-8">
            <NeverHoldBanner />
          </div>

          {message && !expandedId && (
            <div
              className={`mb-6 flex items-center gap-2 rounded-xl px-4 py-3 text-sm ${
                message.type === "success"
                  ? "bg-brand-500/[0.06] border border-brand-500/15 text-brand-400"
                  : "bg-red-500/[0.04] border border-red-500/15 text-red-400"
              }`}
            >
              {message.type === "success" ? <CheckCircle size={15} /> : <AlertCircle size={15} />}
              {message.text}
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-5 w-5 animate-spin text-brand-400" />
            </div>
          ) : (
            <div className="grid gap-5 lg:grid-cols-3">
              {EXCHANGES.map((ex) => {
                const active = isConnected(ex.id);
                const conn = getConnection(ex.id);
                const expanded = expandedId === ex.id;

                return (
                  <div
                    key={ex.id}
                    className={`rounded-2xl border transition-all ${
                      active
                        ? "border-brand-500/30 bg-[#0d1117]"
                        : expanded
                          ? "border-brand-500/15 bg-[#0d1117]"
                          : "border-dark-800 bg-[#0d1117] hover:border-dark-700"
                    }`}
                  >
                    <div className="p-5">
                      <div className="mb-4 flex items-start justify-between">
                        <div className="flex items-center gap-3">
                          <div
                            className={`flex h-11 w-11 items-center justify-center rounded-xl text-base font-bold ${
                              active
                                ? "bg-brand-500/15 text-brand-400"
                                : "bg-dark-800 text-dark-400"
                            }`}
                          >
                            {ex.name.charAt(0)}
                          </div>
                          <div>
                            <h3 className="text-base font-semibold text-white">{ex.name}</h3>
                            <span className="text-xs text-dark-500">{ex.tagline}</span>
                          </div>
                        </div>
                        {active && (
                          <span className="badge-green">
                            <span className="h-1.5 w-1.5 rounded-full bg-brand-400" />
                            Connected
                          </span>
                        )}
                      </div>

                      <p className="mb-4 text-sm leading-relaxed text-dark-400">
                        {ex.description}
                      </p>

                      {active && conn && (
                        <div className="mb-4 space-y-2">
                          <div className="flex items-center gap-2 rounded-xl bg-brand-500/[0.06] border border-brand-500/10 px-3 py-2 text-xs">
                            <CheckCircle size={13} className="text-brand-400" />
                            <span className="text-brand-400 font-medium">
                              {conn.is_paper ? "Paper Trading" : "Live Trading"}
                            </span>
                          </div>
                          {conn.connected_at && (
                            <p className="text-[10px] text-dark-600">
                              Connected {new Date(conn.connected_at).toLocaleDateString()}
                              {conn.last_used &&
                                ` · Last used ${new Date(conn.last_used).toLocaleDateString()}`}
                            </p>
                          )}
                        </div>
                      )}

                      {active ? (
                        <button
                          onClick={() => handleDisconnect(ex.id)}
                          disabled={disconnecting === ex.id}
                          className="flex w-full items-center justify-center gap-2 rounded-xl border border-red-500/20 py-2.5 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-50"
                        >
                          {disconnecting === ex.id ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <Unlink size={13} />
                          )}
                          Disconnect
                        </button>
                      ) : (
                        <button
                          onClick={() => handleExpand(ex.id)}
                          className={`flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-xs font-medium transition-all ${
                            expanded
                              ? "border border-dark-700 text-dark-400 hover:text-dark-200"
                              : "btn-primary"
                          }`}
                        >
                          <Link2 size={13} />
                          {expanded ? "Cancel" : "Connect"}
                        </button>
                      )}
                    </div>

                    {expanded && !active && (
                      <div className="border-t border-dark-800/50 p-5">
                        {message && (
                          <div
                            className={`mb-4 flex items-center gap-2 rounded-xl px-3 py-2 text-xs ${
                              message.type === "success"
                                ? "bg-brand-500/[0.06] border border-brand-500/15 text-brand-400"
                                : "bg-red-500/[0.04] border border-red-500/15 text-red-400"
                            }`}
                          >
                            {message.type === "success" ? (
                              <CheckCircle size={13} />
                            ) : (
                              <AlertCircle size={13} />
                            )}
                            {message.text}
                          </div>
                        )}

                        <div className="space-y-3">
                          {/* API Key */}
                          <div>
                            <label className="mb-1 block text-xs font-medium text-dark-400">
                              {ex.keyLabel}
                            </label>
                            <div className="relative">
                              <input
                                type={showKey ? "text" : "password"}
                                value={formKey}
                                onChange={(e) => setFormKey(e.target.value)}
                                placeholder={ex.keyPlaceholder}
                                className="input pr-9 font-mono text-xs"
                                autoComplete="off"
                              />
                              <button
                                type="button"
                                onClick={() => setShowKey((v) => !v)}
                                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-dark-500 hover:text-dark-300"
                              >
                                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                              </button>
                            </div>
                          </div>

                          {/* Secret Key */}
                          <div>
                            <label className="mb-1 block text-xs font-medium text-dark-400">
                              {ex.secretLabel}
                            </label>
                            <div className="relative">
                              <input
                                type={showSecret ? "text" : "password"}
                                value={formSecret}
                                onChange={(e) => setFormSecret(e.target.value)}
                                placeholder={ex.secretPlaceholder}
                                className="input pr-9 font-mono text-xs"
                                autoComplete="off"
                              />
                              <button
                                type="button"
                                onClick={() => setShowSecret((v) => !v)}
                                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-dark-500 hover:text-dark-300"
                              >
                                {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
                              </button>
                            </div>
                          </div>

                          <div className="flex items-center justify-between rounded-xl border border-dark-800 px-3 py-2.5">
                            <span className="text-xs text-dark-400">Trading Mode</span>
                            <button
                              type="button"
                              onClick={() => setIsPaper((v) => !v)}
                              className="flex items-center gap-2 text-xs font-medium"
                            >
                              {isPaper ? (
                                <>
                                  <ToggleLeft size={20} className="text-brand-400" />
                                  <span className="text-brand-400">Paper Trading</span>
                                </>
                              ) : (
                                <>
                                  <ToggleRight size={20} className="text-yellow-400" />
                                  <span className="text-yellow-400">Live Trading</span>
                                </>
                              )}
                            </button>
                          </div>
                        </div>

                        {/* Docs link */}
                        <div className="mt-4 flex items-center gap-1 text-[10px] text-dark-500">
                          Don&apos;t have an account?
                          <a
                            href={ex.signupUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-0.5 text-brand-400 hover:underline"
                          >
                            Create free account <ExternalLink size={9} />
                          </a>
                        </div>

                        <button
                          onClick={() => handleConnect(ex.id)}
                          disabled={submitting}
                          className="btn-primary mt-4 w-full justify-center py-2.5 text-xs disabled:opacity-50"
                        >
                          {submitting ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <CheckCircle size={14} />
                          )}
                          {submitting ? "Validating..." : "Connect & Verify"}
                        </button>

                        {/* Security notice */}
                        <div className="mt-3 flex items-start gap-2 text-[10px] text-dark-600">
                          <Shield size={12} className="mt-0.5 shrink-0" />
                          Your keys are encrypted with AES-256 and never displayed again after saving.
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="mt-10 rounded-2xl border border-dark-800 bg-[#0d1117] p-6">
            <h2 className="mb-3 text-sm font-semibold text-white">How it works</h2>
            <div className="grid gap-4 text-xs text-dark-400 sm:grid-cols-3">
              <div className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/10 text-[10px] font-bold text-brand-400">
                  1
                </span>
                <p>Create an API key on your exchange with trade permissions enabled.</p>
              </div>
              <div className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/10 text-[10px] font-bold text-brand-400">
                  2
                </span>
                <p>Paste your key and secret here. We validate them instantly.</p>
              </div>
              <div className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/10 text-[10px] font-bold text-brand-400">
                  3
                </span>
                <p>Start trading. Your AI agent uses your keys to execute decisions.</p>
              </div>
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
