import { useState, useEffect } from "react";
import {
  Link2, Unlink, ChevronDown, ChevronUp, Eye, EyeOff,
  CheckCircle, AlertCircle, Loader2, ExternalLink, Clipboard,
} from "lucide-react";
import { authApi, exchangeApi } from "@/lib/api";
import ExchangeApiKeyGuide from "@/components/exchange/ExchangeApiKeyGuide";
import { getExchangeApiKeyGuide } from "@/lib/exchangeApiKeyGuides";

interface ConnectedExchange {
  trading_account_id?: string | null;
  exchange: string;
  account_label?: string | null;
  connected_at: string | null;
  is_paper: boolean;
  last_used: string | null;
}

type ExchangeField = {
  key: "api_key" | "api_secret";
  label: string;
  placeholder: string;
  multiline?: boolean;
};

type ExchangeDef = {
  id: string;
  name: string;
  description: string;
  docsUrl: string;
  fields: ExchangeField[];
  comingSoon?: boolean;
};

const EXCHANGES: ExchangeDef[] = [
  {
    id: "alpaca",
    name: "Alpaca",
    description: "US stocks & crypto — paper & live trading",
    docsUrl: "https://app.alpaca.markets/paper/dashboard/overview",
    fields: [
      { key: "api_key", label: "API Key ID", placeholder: "PK..." },
      { key: "api_secret", label: "Secret Key", placeholder: "Your Alpaca secret key" },
    ],
  },
  {
    id: "coinbase",
    name: "Coinbase",
    description: "Crypto exchange — Advanced Trade (CDP keys)",
    docsUrl: "https://portal.cdp.coinbase.com/",
    fields: [
      { key: "api_key", label: "API Key Name", placeholder: "organizations/.../apiKeys/..." },
      {
        key: "api_secret",
        label: "Private Key (PEM)",
        placeholder: "-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----",
        multiline: true,
      },
    ],
  },
  {
    id: "binance",
    name: "Binance",
    description: "Global crypto exchange — spot trading",
    docsUrl: "https://www.binance.com/en/my/settings/api-management",
    fields: [
      { key: "api_key", label: "API Key", placeholder: "Your Binance API key" },
      { key: "api_secret", label: "Secret Key", placeholder: "Your Binance secret key" },
    ],
  },
  {
    id: "kraken",
    name: "Kraken",
    description: "Crypto exchange — spot trading (API key + base64 private key)",
    docsUrl: "https://docs.kraken.com/rest/#section/Authentication/API-Keys",
    fields: [
      { key: "api_key", label: "API Key", placeholder: "Your Kraken API key" },
      { key: "api_secret", label: "Private Key", placeholder: "Base64 private key from Kraken" },
    ],
  },
  {
    id: "oanda",
    name: "OANDA",
    description: "Forex & CFDs — practice & live accounts",
    docsUrl: "https://www.oanda.com/account/",
    comingSoon: true,
    fields: [
      { key: "api_key", label: "API Token", placeholder: "Your OANDA API token" },
      { key: "api_secret", label: "Account ID", placeholder: "Your OANDA account ID" },
    ],
  },
];

// ─── Coinbase smart-paste helpers ─────────────────────────────────────────────

type CoinbasePasteStatus =
  | { kind: "idle" }
  | { kind: "json_full"; name: string; privateKey: string }
  | { kind: "pem_only" }
  | { kind: "key_only" };

function parseCoinbasePaste(raw: string): CoinbasePasteStatus {
  const trimmed = raw.trim();
  if (!trimmed) return { kind: "idle" };

  // CDP JSON blob: {"name":"organizations/…","privateKey":"-----BEGIN…"}
  try {
    const obj = JSON.parse(trimmed);
    if (obj && typeof obj.name === "string" && typeof obj.privateKey === "string") {
      return { kind: "json_full", name: obj.name.trim(), privateKey: obj.privateKey.trim() };
    }
  } catch {
    // not JSON — fall through
  }

  // Bare PEM block
  if (trimmed.includes("-----BEGIN") && trimmed.includes("PRIVATE KEY-----")) {
    return { kind: "pem_only" };
  }

  // Anything else — treat as an API key name or legacy key string
  return { kind: "key_only" };
}

// ──────────────────────────────────────────────────────────────────────────────

export default function ExchangeConnections({ onConnected }: { onConnected?: () => void } = {}) {
  const [connected, setConnected] = useState<ConnectedExchange[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [connectModes, setConnectModes] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  // Coinbase smart-paste
  const [cbPasteRaw, setCbPasteRaw] = useState("");
  const [cbPasteStatus, setCbPasteStatus] = useState<CoinbasePasteStatus>({ kind: "idle" });

  const handleCoinbaseSmartPaste = (raw: string) => {
    setCbPasteRaw(raw);
    const status = parseCoinbasePaste(raw);
    setCbPasteStatus(status);

    if (status.kind === "json_full") {
      setFormValues((v) => ({
        ...v,
        coinbase_api_key: status.name,
        coinbase_api_secret: status.privateKey,
      }));
    } else if (status.kind === "pem_only") {
      setFormValues((v) => ({ ...v, coinbase_api_secret: raw.trim() }));
    } else if (status.kind === "key_only") {
      setFormValues((v) => ({ ...v, coinbase_api_key: raw.trim() }));
    }
  };

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

  useEffect(() => { loadConnected(); }, []);

  const connectionsForExchange = (exchangeId: string) =>
    connected.filter((c) => c.exchange === exchangeId);

  const isConnected = (exchangeId: string) =>
    connectionsForExchange(exchangeId).length > 0;

  const handleConnect = async (exchangeId: string) => {
    const apiKey = formValues[`${exchangeId}_api_key`]?.trim();
    const apiSecret = formValues[`${exchangeId}_api_secret`]?.trim();

    if (!apiKey || !apiSecret) {
      setMessage({ type: "error", text: "Both fields are required." });
      return;
    }

    setSubmitting(true);
    setMessage(null);
    try {
      const isPaper = connectModes[exchangeId] ?? true;
      const res = await exchangeApi.connect(exchangeId, apiKey, apiSecret, isPaper);
      const payload = res.data.data;
      const balance = payload?.balance_usd;
      if (payload?.trading_account_id) {
        await authApi.updateSettings({ preferred_trading_account_id: payload.trading_account_id }).catch(() => {});
      }
      setMessage({
        type: "success",
        text: `${exchangeId.charAt(0).toUpperCase() + exchangeId.slice(1)} ${isPaper ? "paper" : "live"} account connected. Balance: $${balance?.toLocaleString() ?? "—"}`,
      });
      setFormValues((v) => ({ ...v, [`${exchangeId}_api_key`]: "", [`${exchangeId}_api_secret`]: "" }));
      if (exchangeId === "coinbase") {
        setCbPasteRaw("");
        setCbPasteStatus({ kind: "idle" });
      }
      setExpandedId(null);
      await loadConnected();
      onConnected?.();
    } catch (err: any) {
      const detail = err.response?.data?.detail || "Connection failed. Check your keys and try again.";
      setMessage({ type: "error", text: detail });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDisconnect = async (connection: ConnectedExchange) => {
    if (!confirm(`Disconnect ${connection.account_label || `${connection.exchange} ${connection.is_paper ? "paper" : "live"}`}? You can reconnect later.`)) return;
    const targetId = connection.trading_account_id || `${connection.exchange}-${connection.is_paper ? "paper" : "live"}`;
    setDisconnecting(targetId);
    setMessage(null);
    try {
      await exchangeApi.disconnect(connection.exchange, {
        trading_account_id: connection.trading_account_id || undefined,
        is_paper: connection.is_paper,
      });
      setMessage({ type: "success", text: `${connection.account_label || `${connection.exchange} ${connection.is_paper ? "paper" : "live"}`} disconnected.` });
      await loadConnected();
    } catch {
      setMessage({ type: "error", text: "Failed to disconnect. Please try again." });
    } finally {
      setDisconnecting(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-dark-500">
        <Loader2 size={16} className="mr-2 animate-spin" /> Loading exchanges...
      </div>
    );
  }

  return (
    <div className="mobile-safe space-y-4">
      <div className="flex items-center gap-2">
        <Link2 size={16} className="text-brand-400" />
        <h2 className="text-sm font-semibold text-dark-200">Exchange Connections</h2>
      </div>
      <p className="text-xs text-dark-500">
        Connect your exchange API keys to enable AI-powered trading. Keys are encrypted and stored securely.
      </p>

      {message && (
        <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${
          message.type === "success"
            ? "bg-brand-500/10 text-brand-400"
            : "bg-red-500/10 text-red-400"
        }`}>
          {message.type === "success" ? <CheckCircle size={13} /> : <AlertCircle size={13} />}
          {message.text}
        </div>
      )}

      {EXCHANGES.map((exchange) => {
        const active = isConnected(exchange.id);
        const connInfo = connectionsForExchange(exchange.id);
        const expanded = expandedId === exchange.id;
        const disabled = exchange.comingSoon && !active;

        return (
          <div
            key={exchange.id}
            className={`rounded-xl border bg-dark-950 transition ${
              active ? "border-brand-500/30" : disabled ? "border-dark-800 opacity-60" : "border-dark-800"
            }`}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-3">
                <div className={`flex h-8 w-8 items-center justify-center rounded-lg text-xs font-bold ${
                  active ? "bg-brand-500/20 text-brand-400" : "bg-dark-800 text-dark-500"
                }`}>
                  {exchange.name.charAt(0)}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium ${disabled ? "text-dark-400" : "text-white"}`}>{exchange.name}</span>
                    {active && (
                      <span className="flex items-center gap-1 rounded-full bg-brand-500/10 px-2 py-0.5 text-[10px] font-medium text-brand-400">
                        <span className="h-1.5 w-1.5 rounded-full bg-brand-400" />
                        {connInfo.length} connected
                      </span>
                    )}
                    {disabled && (
                      <span className="rounded-full border border-dark-700 bg-dark-900 px-2 py-0.5 text-[10px] font-medium text-dark-500">
                        Coming Soon
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-dark-500">{exchange.description}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {disabled ? null : (
                  <button
                    onClick={() => {
                      setExpandedId(expanded ? null : exchange.id);
                      setMessage(null);
                    }}
                    className="flex items-center gap-1.5 rounded-lg border border-brand-500/30 px-3 py-1.5 text-xs text-brand-400 transition hover:bg-brand-500/10"
                  >
                    <Link2 size={12} />
                    {active ? "Manage" : "Connect"}
                    {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  </button>
                )}
              </div>
            </div>

            {/* Connected info */}
            {active && connInfo.length > 0 && (
              <div className="border-t border-dark-800 px-4 py-2">
                <div className="space-y-2 text-[10px] text-dark-500">
                  {connInfo.map((connection) => {
                    const targetId = connection.trading_account_id || `${connection.exchange}-${connection.is_paper ? "paper" : "live"}`;
                    return (
                      <div key={targetId} className="flex items-center justify-between gap-3 rounded-lg border border-dark-800 bg-dark-900/40 px-2.5 py-2">
                        <div>
                          <div className="text-dark-300">
                            {connection.account_label || `${exchange.name} ${connection.is_paper ? "paper" : "live"}`}
                          </div>
                          <div>
                            Connected {connection.connected_at ? new Date(connection.connected_at).toLocaleDateString() : ""}
                            {connection.last_used && ` · Last used ${new Date(connection.last_used).toLocaleDateString()}`}
                          </div>
                        </div>
                        <button
                          onClick={() => handleDisconnect(connection)}
                          disabled={disconnecting === targetId}
                          className="flex items-center gap-1 rounded-lg border border-red-500/30 px-2.5 py-1 text-[10px] text-red-400 transition hover:bg-red-500/10 disabled:opacity-50"
                        >
                          {disconnecting === targetId ? <Loader2 size={11} className="animate-spin" /> : <Unlink size={11} />}
                          Disconnect
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Expansion form */}
            {expanded && !disabled && (
              <div className="border-t border-dark-800 p-3 sm:p-4">
                <div className="mb-4 flex items-center justify-between rounded-lg border border-dark-800 bg-dark-900/40 px-3 py-2">
                  <div>
                    <div className="text-xs font-medium text-white">Connection mode</div>
                    <div className="text-[10px] text-dark-500">Keep paper and live accounts separate per exchange.</div>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      setConnectModes((prev) => ({ ...prev, [exchange.id]: !(prev[exchange.id] ?? true) }))
                    }
                    className="rounded-lg border border-dark-700 px-2.5 py-1 text-[11px] text-dark-200"
                  >
                    {(connectModes[exchange.id] ?? true) ? "Paper" : "Live"}
                  </button>
                </div>
                {exchange.id === "coinbase" ? (
                  <>
                    {/* Smart paste box */}
                    <div className="mb-4">
                      <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-dark-300">
                        <Clipboard size={12} className="text-brand-400" />
                        Paste your Coinbase key here
                      </div>
                      <p className="mb-2 text-[10px] text-dark-500">
                        Paste the full JSON from{" "}
                        <a
                          href={exchange.docsUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-brand-400 hover:underline"
                        >
                          portal.cdp.coinbase.com <ExternalLink size={8} className="inline" />
                        </a>
                        {" "}or paste a PEM block or key string — we sort it out automatically.
                      </p>
                      <textarea
                        rows={5}
                        value={cbPasteRaw}
                        onChange={(e) => handleCoinbaseSmartPaste(e.target.value)}
                        placeholder={`Paste JSON e.g.\n{\n  "name": "organizations/.../apiKeys/...",\n  "privateKey": "-----BEGIN EC PRIVATE KEY-----\\n..."\n}`}
                        className="input w-full font-mono text-[11px] resize-none"
                        autoComplete="off"
                      />
                      {cbPasteStatus.kind === "json_full" && (
                        <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-brand-400">
                          <CheckCircle size={11} />
                          Both fields filled automatically — click Connect &amp; Verify below.
                        </div>
                      )}
                      {cbPasteStatus.kind === "pem_only" && (
                        <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-amber-400">
                          <AlertCircle size={11} />
                          Private Key detected — please also enter the API Key Name below.
                        </div>
                      )}
                      {cbPasteStatus.kind === "key_only" && (
                        <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-amber-400">
                          <AlertCircle size={11} />
                          Key string detected — please also paste your Private Key (PEM) in the field below.
                        </div>
                      )}
                    </div>

                    {/* Divider */}
                    <div className="relative mb-4 flex items-center gap-2">
                      <div className="flex-1 border-t border-dark-800" />
                      <span className="text-[10px] text-dark-700">or fill in manually</span>
                      <div className="flex-1 border-t border-dark-800" />
                    </div>

                    {/* Individual fields */}
                    <div className="space-y-3">
                      {exchange.fields.map((field) => {
                        const fieldId = `${exchange.id}_${field.key}`;
                        return (
                          <div key={field.key}>
                            <label className="mb-1 block text-xs text-dark-400">{field.label}</label>
                            {field.multiline ? (
                              <textarea
                                rows={5}
                                value={formValues[fieldId] || ""}
                                onChange={(e) =>
                                  setFormValues((v) => ({ ...v, [fieldId]: e.target.value }))
                                }
                                placeholder={field.placeholder}
                                className="input w-full font-mono text-xs resize-none"
                                autoComplete="off"
                              />
                            ) : (
                              <input
                                type="text"
                                value={formValues[fieldId] || ""}
                                onChange={(e) =>
                                  setFormValues((v) => ({ ...v, [fieldId]: e.target.value }))
                                }
                                placeholder={field.placeholder}
                                className="input w-full font-mono text-xs"
                                autoComplete="off"
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>

                    {/* Collapsible how-to guide */}
                    <details className="mt-3">
                      <summary className="flex min-h-11 cursor-pointer list-none items-center text-xs text-dark-600 hover:text-dark-400 sm:min-h-0 sm:text-[10px] [&::-webkit-details-marker]:hidden">
                        How to get your Coinbase CDP keys
                      </summary>
                      <ol className="mt-2 list-decimal space-y-1 pl-4 text-[10px] text-dark-500">
                        <li>Go to portal.cdp.coinbase.com → Projects → your project → API Keys</li>
                        <li>Click Create API Key (name it "Unitrader"), enable trade permissions</li>
                        <li>On the confirmation screen click the copy icon next to the JSON</li>
                        <li>Paste the copied JSON into the box above — done</li>
                      </ol>
                    </details>
                  </>
                ) : (
                  <>
                    {(() => {
                      const g = getExchangeApiKeyGuide(exchange.id);
                      return g ? (
                        <div className="mb-3">
                          <ExchangeApiKeyGuide guide={g} />
                        </div>
                      ) : null;
                    })()}
                    <div className="space-y-3">
                      {exchange.fields.map((field) => {
                        const fieldId = `${exchange.id}_${field.key}`;
                        const isSecret = field.key === "api_secret";
                        return (
                          <div key={field.key}>
                            <label className="mb-1 block text-xs text-dark-400">{field.label}</label>
                            <div className="relative">
                              {field.multiline ? (
                                <textarea
                                  rows={6}
                                  value={formValues[fieldId] || ""}
                                  onChange={(e) =>
                                    setFormValues((v) => ({ ...v, [fieldId]: e.target.value }))
                                  }
                                  placeholder={field.placeholder}
                                  className="input w-full font-mono text-xs resize-none"
                                  autoComplete="off"
                                />
                              ) : (
                                <input
                                  type={isSecret && !showSecrets[fieldId] ? "password" : "text"}
                                  value={formValues[fieldId] || ""}
                                  onChange={(e) =>
                                    setFormValues((v) => ({ ...v, [fieldId]: e.target.value }))
                                  }
                                  placeholder={field.placeholder}
                                  className="input w-full pr-9 font-mono text-xs"
                                  autoComplete="off"
                                />
                              )}
                              {isSecret && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    setShowSecrets((s) => ({ ...s, [fieldId]: !s[fieldId] }))
                                  }
                                  className="absolute right-1 top-1/2 flex min-h-11 min-w-11 -translate-y-1/2 items-center justify-center text-dark-500 hover:text-dark-300 sm:right-2 sm:min-h-0 sm:min-w-0"
                                >
                                  {showSecrets[fieldId] ? <EyeOff size={14} /> : <Eye size={14} />}
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}
                <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
                  <button
                    onClick={() => handleConnect(exchange.id)}
                    disabled={submitting}
                    className="btn-primary flex items-center gap-2 px-4 py-2 text-xs disabled:opacity-50"
                  >
                    {submitting ? (
                      <Loader2 size={13} className="animate-spin" />
                    ) : (
                      <CheckCircle size={13} />
                    )}
                    {submitting ? "Validating..." : "Connect & Verify"}
                  </button>
                  <button
                    onClick={() => {
                      setExpandedId(null);
                      setMessage(null);
                      setCbPasteRaw("");
                      setCbPasteStatus({ kind: "idle" });
                    }}
                    className="text-xs text-dark-500 hover:text-dark-300"
                  >
                    Cancel
                  </button>
                </div>
                <p className="mt-3 text-[10px] text-dark-600">
                  Your keys are encrypted with AES-256 before storage and never exposed in plaintext.
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
