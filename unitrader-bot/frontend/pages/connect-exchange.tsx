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
  Clipboard,
} from "lucide-react";
import {
  authApi,
  exchangeApi,
  type ConnectedExchange,
  type ConnectExchangeResponse,
} from "@/lib/api";
import NeverHoldBanner from "@/components/layout/NeverHoldBanner";
import ExchangeApiKeyGuide from "@/components/exchange/ExchangeApiKeyGuide";
import { getExchangeApiKeyGuide } from "@/lib/exchangeApiKeyGuides";

const EXCHANGES = [
  {
    id: "alpaca",
    name: "Alpaca",
    tagline: "Stocks & ETFs",
    description:
      "Trade US equities and ETFs commission-free. Supports paper trading for risk-free practice.",
    signupUrl: "https://app.alpaca.markets/signup",
    docsUrl: "https://app.alpaca.markets/paper/dashboard/overview",
    keyLabel: "API Key ID",
    keyPlaceholder: "PK...",
    secretLabel: "Secret Key",
    secretPlaceholder: "Your Alpaca secret key",
    secretMultiline: false,
  },
  {
    id: "binance",
    name: "Binance",
    tagline: "Crypto",
    description:
      "Access the world's largest crypto exchange. Trade BTC, ETH, and hundreds of altcoins.",
    signupUrl: "https://accounts.binance.com/register",
    docsUrl: "https://www.binance.com/en/my/settings/api-management",
    keyLabel: "API Key",
    keyPlaceholder: "Your Binance API key",
    secretLabel: "Secret Key",
    secretPlaceholder: "Your Binance secret key",
    secretMultiline: false,
  },
  {
    id: "oanda",
    name: "OANDA",
    tagline: "Forex",
    description:
      "Trade major, minor and exotic forex pairs. Practice accounts available for all users.",
    signupUrl: "https://www.oanda.com/apply/",
    docsUrl: "https://www.oanda.com/account/",
    keyLabel: "API Token",
    keyPlaceholder: "Your OANDA API token",
    secretLabel: "Account ID",
    secretPlaceholder: "e.g. 001-001-12345-001",
    secretMultiline: false,
  },
  {
    id: "coinbase",
    name: "Coinbase",
    tagline: "Crypto",
    description:
      "Trade Bitcoin, Ethereum and hundreds of crypto assets on one of the world's most trusted exchanges.",
    signupUrl: "https://portal.cdp.coinbase.com/",
    docsUrl: "https://portal.cdp.coinbase.com/",
    keyLabel: "API Key Name",
    keyPlaceholder: "organizations/.../apiKeys/...",
    secretLabel: "Private Key (PEM)",
    secretPlaceholder: "-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----",
    secretMultiline: true,
  },
  {
    id: "kraken",
    name: "Kraken",
    tagline: "Crypto",
    description:
      "Trade Bitcoin, Ethereum, and major crypto pairs on Kraken. Spot trading via REST API.",
    signupUrl: "https://www.kraken.com/sign-up",
    docsUrl: "https://docs.kraken.com/rest/#section/Authentication/API-Keys",
    keyLabel: "API Key",
    keyPlaceholder: "Your Kraken API key",
    secretLabel: "Private Key",
    secretPlaceholder: "Base64-encoded private key from Kraken",
    secretMultiline: false,
  },
] as const;

// ─── Coinbase smart-paste helpers ─────────────────────────────────────────────

type CbPasteStatus =
  | { kind: "idle" }
  | { kind: "json_full"; name: string; privateKey: string }
  | { kind: "pem_only" }
  | { kind: "key_only" };

function parseCbPaste(raw: string): CbPasteStatus {
  const trimmed = raw.trim();
  if (!trimmed) return { kind: "idle" };
  try {
    const obj = JSON.parse(trimmed);
    if (obj && typeof obj.name === "string" && typeof obj.privateKey === "string") {
      return { kind: "json_full", name: obj.name.trim(), privateKey: obj.privateKey.trim() };
    }
  } catch { /* not JSON */ }
  if (trimmed.includes("-----BEGIN") && trimmed.includes("PRIVATE KEY-----")) {
    return { kind: "pem_only" };
  }
  return { kind: "key_only" };
}

type ExchangeId = (typeof EXCHANGES)[number]["id"];

function connectResponseToConnected(data: ConnectExchangeResponse): ConnectedExchange {
  return {
    trading_account_id: data.trading_account_id ?? null,
    exchange: data.exchange,
    account_label: data.account_label ?? null,
    connected_at: data.connected_at ?? null,
    is_paper: data.is_paper,
    last_used: null,
  };
}

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
  // Coinbase smart paste
  const [cbPasteRaw, setCbPasteRaw] = useState("");
  const [cbPasteStatus, setCbPasteStatus] = useState<CbPasteStatus>({ kind: "idle" });

  const [submitting, setSubmitting] = useState(false);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
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
      const res = await exchangeApi.list({ timeout: 30000 });
      setConnected(res.data.data || []);
      setListError(null);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401) {
        setConnected([]);
      }
      if (status !== 401) {
        setListError(
          "Could not refresh connections. If you just connected, try refreshing the page."
        );
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isSignedIn) loadConnected();
  }, [isSignedIn]);

  const connectionsForExchange = (exchangeId: string) =>
    connected.filter((c) => c.exchange === exchangeId);

  const isConnected = (id: string) => connectionsForExchange(id).length > 0;

  const resetForm = () => {
    setFormKey("");
    setFormSecret("");
    setIsPaper(true);
    setShowKey(false);
    setShowSecret(false);
    setCbPasteRaw("");
    setCbPasteStatus({ kind: "idle" });
  };

  const handleCbPaste = (raw: string) => {
    setCbPasteRaw(raw);
    const status = parseCbPaste(raw);
    setCbPasteStatus(status);
    if (status.kind === "json_full") {
      setFormKey(status.name);
      setFormSecret(status.privateKey);
    } else if (status.kind === "pem_only") {
      setFormSecret(raw.trim());
    } else if (status.kind === "key_only") {
      setFormKey(raw.trim());
    }
  };

  const handleExpand = (id: ExchangeId) => {
    if (expandedId === id) {
      setExpandedId(null);
      setMessage(null);
      resetForm();
    } else {
      setExpandedId(id);
      setMessage(null);
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
      const optimistic = connectResponseToConnected(data);
      setConnected((prev) => {
        const filtered = prev.filter((c) => {
          if (c.exchange !== optimistic.exchange) return true;
          if (c.trading_account_id && optimistic.trading_account_id) {
            return c.trading_account_id !== optimistic.trading_account_id;
          }
          return c.is_paper !== optimistic.is_paper;
        });
        return [...filtered, optimistic];
      });
      setMessage({
        type: "success",
        text: `${data.message}${data.balance_usd != null ? ` Balance: $${data.balance_usd.toLocaleString()}` : ""}`,
      });
      if (data.trading_account_id) {
        await authApi.updateSettings({ preferred_trading_account_id: data.trading_account_id }).catch(() => {});
      }
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

  const handleDisconnect = async (connection: ConnectedExchange) => {
    const label =
      connection.account_label ||
      `${connection.exchange} ${connection.is_paper ? "paper" : "live"}`;
    if (!confirm(`Disconnect ${label}? You can reconnect later.`)) return;
    const targetId =
      connection.trading_account_id ||
      `${connection.exchange}-${connection.is_paper ? "paper" : "live"}`;
    setDisconnecting(targetId);
    setMessage(null);
    try {
      await exchangeApi.disconnect(connection.exchange, {
        trading_account_id: connection.trading_account_id || undefined,
        is_paper: connection.is_paper,
      });
      setMessage({
        type: "success",
        text: `${label} disconnected.`,
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

      <div className="min-h-screen bg-dark-950 mobile-safe">
        <header className="border-b border-dark-800/60">
          <div className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-4 sm:px-6">
            <button
              onClick={() => router.push("/app")}
              className="flex items-center gap-2 text-sm text-dark-400 transition-colors hover:text-white"
            >
              <ArrowLeft size={15} />
              Back to Dashboard
            </button>
          </div>
        </header>

        <main className="mx-auto max-w-5xl px-4 py-8 animate-fade-in sm:px-6 sm:py-10">
          <div className="mb-8">
            <h1 className="page-title text-2xl">Connect Exchange</h1>
            <p className="page-subtitle">Link your brokerage accounts to enable AI-powered trading</p>
          </div>

          <div className="mb-8">
            <NeverHoldBanner />
          </div>

          {listError && (
            <div className="mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/20 bg-amber-500/[0.06] px-4 py-3 text-sm text-amber-200">
              <AlertCircle size={16} className="shrink-0 text-amber-400" />
              <p className="min-w-0 flex-1 text-xs leading-relaxed">{listError}</p>
              <button
                type="button"
                onClick={() => {
                  setListError(null);
                  setLoading(true);
                  void loadConnected();
                }}
                className="shrink-0 rounded-lg border border-amber-500/30 px-3 py-1 text-xs font-medium text-amber-400 transition hover:bg-amber-500/10"
              >
                Retry
              </button>
            </div>
          )}

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
                const connInfo = connectionsForExchange(ex.id);
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

                      {active && connInfo.length > 0 && (
                        <div className="mb-4 space-y-2">
                          {connInfo.map((connection) => {
                            const targetId =
                              connection.trading_account_id ||
                              `${connection.exchange}-${connection.is_paper ? "paper" : "live"}`;
                            const rowLabel =
                              connection.account_label ||
                              `${ex.name} ${connection.is_paper ? "paper" : "live"}`;
                            return (
                              <div
                                key={targetId}
                                className="flex flex-col gap-2 rounded-xl border border-brand-500/15 bg-brand-500/[0.04] px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"
                              >
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2 text-xs">
                                    <CheckCircle size={13} className="shrink-0 text-brand-400" />
                                    <span className="font-medium text-brand-400">{rowLabel}</span>
                                  </div>
                                  {connection.connected_at && (
                                    <p className="mt-1 pl-[21px] text-[10px] text-dark-500">
                                      Connected{" "}
                                      {new Date(connection.connected_at).toLocaleDateString()}
                                      {connection.last_used &&
                                        ` · Last used ${new Date(connection.last_used).toLocaleDateString()}`}
                                    </p>
                                  )}
                                </div>
                                <button
                                  type="button"
                                  onClick={() => handleDisconnect(connection)}
                                  disabled={disconnecting === targetId}
                                  className="flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-red-500/25 px-3 py-1.5 text-[10px] font-medium text-red-400 transition hover:bg-red-500/10 disabled:opacity-50"
                                >
                                  {disconnecting === targetId ? (
                                    <Loader2 size={12} className="animate-spin" />
                                  ) : (
                                    <Unlink size={12} />
                                  )}
                                  Disconnect
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {!active ? (
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
                      ) : null}
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

                        {ex.id === "coinbase" ? (
                          /* ── Coinbase smart-paste UI ── */
                          <div className="space-y-3">
                            <div>
                              <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-dark-400">
                                <Clipboard size={12} />
                                Paste your Coinbase key here
                              </label>
                              <textarea
                                rows={4}
                                value={cbPasteRaw}
                                onChange={(e) => handleCbPaste(e.target.value)}
                                placeholder={`Paste the JSON from Coinbase CDP portal\nor paste just the Private Key PEM block`}
                                className="input w-full resize-none font-mono text-[11px] leading-relaxed"
                                autoComplete="off"
                                spellCheck={false}
                              />
                              {cbPasteStatus.kind === "json_full" && (
                                <p className="mt-1 text-[10px] text-brand-400">
                                  ✓ Detected full CDP key — both fields filled automatically
                                </p>
                              )}
                              {cbPasteStatus.kind === "pem_only" && (
                                <p className="mt-1 text-[10px] text-yellow-400">
                                  PEM detected — please also fill in the API Key Name below
                                </p>
                              )}
                              {cbPasteStatus.kind === "key_only" && (
                                <p className="mt-1 text-[10px] text-dark-500">
                                  Plain text detected — fill both fields below manually
                                </p>
                              )}
                            </div>

                            <div className="relative border-t border-dark-800/50 pt-3">
                              <span className="absolute -top-2 left-3 bg-[#0d1117] px-1 text-[9px] uppercase tracking-widest text-dark-600">
                                or fill in manually
                              </span>
                            </div>

                            {/* API Key Name */}
                            <div>
                              <label className="mb-1 block text-xs font-medium text-dark-400">
                                API Key Name
                              </label>
                              <input
                                type="text"
                                value={formKey}
                                onChange={(e) => setFormKey(e.target.value)}
                                placeholder="organizations/.../apiKeys/..."
                                className="input font-mono text-xs"
                                autoComplete="off"
                              />
                            </div>

                            {/* Private Key */}
                            <div>
                              <label className="mb-1 block text-xs font-medium text-dark-400">
                                Private Key (PEM)
                              </label>
                              <textarea
                                rows={4}
                                value={formSecret}
                                onChange={(e) => setFormSecret(e.target.value)}
                                placeholder={"-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----"}
                                className="input w-full resize-none font-mono text-[11px] leading-relaxed"
                                autoComplete="off"
                                spellCheck={false}
                              />
                            </div>

                            <div className="flex min-h-11 items-center justify-between gap-3 rounded-xl border border-dark-800 px-3 py-2.5 sm:min-h-0">
                              <span className="text-xs text-dark-400">Trading Mode</span>
                              <button
                                type="button"
                                onClick={() => setIsPaper((v) => !v)}
                                className="flex min-h-10 min-w-[8rem] items-center justify-end gap-2 text-xs font-medium sm:min-h-0 sm:min-w-0"
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

                            <details className="rounded-xl border border-dark-800 p-3 text-[10px] text-dark-500">
                              <summary className="cursor-pointer text-dark-400 hover:text-white">
                                How to get your Coinbase CDP key
                              </summary>
                              <ol className="mt-2 list-decimal space-y-1 pl-4">
                                <li>Go to <a href="https://portal.cdp.coinbase.com/" target="_blank" rel="noopener noreferrer" className="text-brand-400 hover:underline">portal.cdp.coinbase.com</a></li>
                                <li>Create an API key with <strong className="text-dark-300">Trade</strong> permission</li>
                                <li>Copy the JSON shown — paste it directly above</li>
                              </ol>
                            </details>
                          </div>
                        ) : (
                          /* ── Standard exchange form ── */
                          <div className="space-y-3">
                            {(() => {
                              const g = getExchangeApiKeyGuide(ex.id);
                              return g ? (
                                <div className="mb-1">
                                  <ExchangeApiKeyGuide guide={g} />
                                </div>
                              ) : null;
                            })()}
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
                                  className="absolute right-1 top-1/2 flex min-h-11 min-w-11 -translate-y-1/2 items-center justify-center text-dark-500 hover:text-dark-300 sm:right-2.5 sm:min-h-0 sm:min-w-0"
                                  aria-label={showKey ? "Hide API key" : "Show API key"}
                                >
                                  {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                                </button>
                              </div>
                            </div>

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
                                  className="absolute right-1 top-1/2 flex min-h-11 min-w-11 -translate-y-1/2 items-center justify-center text-dark-500 hover:text-dark-300 sm:right-2.5 sm:min-h-0 sm:min-w-0"
                                  aria-label={showSecret ? "Hide secret" : "Show secret"}
                                >
                                  {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
                                </button>
                              </div>
                            </div>

                            <div className="flex min-h-11 items-center justify-between gap-3 rounded-xl border border-dark-800 px-3 py-2.5 sm:min-h-0">
                              <span className="text-xs text-dark-400">Trading Mode</span>
                              <button
                                type="button"
                                onClick={() => setIsPaper((v) => !v)}
                                className="flex min-h-10 min-w-[8rem] items-center justify-end gap-2 text-xs font-medium sm:min-h-0 sm:min-w-0"
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
                        )}

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

          <div className="mt-10 rounded-2xl border border-dark-800 bg-[#0d1117] p-4 sm:p-6">
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
