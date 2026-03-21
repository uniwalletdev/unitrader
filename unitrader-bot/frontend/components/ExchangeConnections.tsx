import { useState, useEffect } from "react";
import {
  Link2, Unlink, ChevronDown, ChevronUp, Eye, EyeOff,
  CheckCircle, AlertCircle, Loader2, ExternalLink,
} from "lucide-react";
import { exchangeApi } from "@/lib/api";

interface ConnectedExchange {
  exchange: string;
  connected_at: string | null;
  last_used: string | null;
}

const EXCHANGES = [
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
    id: "oanda",
    name: "OANDA",
    description: "Forex & CFDs — practice & live accounts",
    docsUrl: "https://www.oanda.com/account/",
    fields: [
      { key: "api_key", label: "API Token", placeholder: "Your OANDA API token" },
      { key: "api_secret", label: "Account ID", placeholder: "Your OANDA account ID" },
    ],
  },
];

export default function ExchangeConnections({ onConnected }: { onConnected?: () => void } = {}) {
  const [connected, setConnected] = useState<ConnectedExchange[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

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

  const isConnected = (exchangeId: string) =>
    connected.some((c) => c.exchange === exchangeId);

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
      const res = await exchangeApi.connect(exchangeId, apiKey, apiSecret);
      const balance = res.data.data?.balance_usd;
      setMessage({
        type: "success",
        text: `${exchangeId.charAt(0).toUpperCase() + exchangeId.slice(1)} connected! Balance: $${balance?.toLocaleString() ?? "—"}`,
      });
      setFormValues((v) => ({ ...v, [`${exchangeId}_api_key`]: "", [`${exchangeId}_api_secret`]: "" }));
      setExpandedId(null);
      await loadConnected();
      // Notify parent (e.g. dashboard) that an exchange was connected
      onConnected?.();
    } catch (err: any) {
      const detail = err.response?.data?.detail || "Connection failed. Check your keys and try again.";
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
      setMessage({ type: "success", text: `${exchangeId.charAt(0).toUpperCase() + exchangeId.slice(1)} disconnected.` });
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
    <div className="space-y-4">
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
        const connInfo = connected.find((c) => c.exchange === exchange.id);
        const expanded = expandedId === exchange.id;

        return (
          <div
            key={exchange.id}
            className={`rounded-xl border bg-dark-950 transition ${
              active ? "border-brand-500/30" : "border-dark-800"
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
                    <span className="text-sm font-medium text-white">{exchange.name}</span>
                    {active && (
                      <span className="flex items-center gap-1 rounded-full bg-brand-500/10 px-2 py-0.5 text-[10px] font-medium text-brand-400">
                        <span className="h-1.5 w-1.5 rounded-full bg-brand-400" />
                        Connected
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-dark-500">{exchange.description}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {active ? (
                  <button
                    onClick={() => handleDisconnect(exchange.id)}
                    disabled={disconnecting === exchange.id}
                    className="flex items-center gap-1.5 rounded-lg border border-red-500/30 px-3 py-1.5 text-xs text-red-400 transition hover:bg-red-500/10 disabled:opacity-50"
                  >
                    {disconnecting === exchange.id ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Unlink size={12} />
                    )}
                    Disconnect
                  </button>
                ) : (
                  <button
                    onClick={() => {
                      setExpandedId(expanded ? null : exchange.id);
                      setMessage(null);
                    }}
                    className="flex items-center gap-1.5 rounded-lg border border-brand-500/30 px-3 py-1.5 text-xs text-brand-400 transition hover:bg-brand-500/10"
                  >
                    <Link2 size={12} />
                    Connect
                    {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  </button>
                )}
              </div>
            </div>

            {/* Connected info */}
            {active && connInfo && (
              <div className="border-t border-dark-800 px-4 py-2 text-[10px] text-dark-500">
                Connected {connInfo.connected_at ? new Date(connInfo.connected_at).toLocaleDateString() : ""}
                {connInfo.last_used && ` · Last used ${new Date(connInfo.last_used).toLocaleDateString()}`}
              </div>
            )}

            {/* Expansion form */}
            {expanded && !active && (
              <div className="border-t border-dark-800 p-4">
                <div className="mb-3 flex items-center gap-1 text-[10px] text-dark-500">
                  Get your API keys from
                  <a
                    href={exchange.docsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-0.5 text-brand-400 hover:underline"
                  >
                    {exchange.name} dashboard <ExternalLink size={9} />
                  </a>
                </div>
                <div className="space-y-3">
                  {exchange.fields.map((field) => {
                    const fieldId = `${exchange.id}_${field.key}`;
                    const isSecret = field.key === "api_secret";
                    return (
                      <div key={field.key}>
                        <label className="mb-1 block text-xs text-dark-400">{field.label}</label>
                        <div className="relative">
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
                          {isSecret && (
                            <button
                              type="button"
                              onClick={() =>
                                setShowSecrets((s) => ({ ...s, [fieldId]: !s[fieldId] }))
                              }
                              className="absolute right-2 top-1/2 -translate-y-1/2 text-dark-500 hover:text-dark-300"
                            >
                              {showSecrets[fieldId] ? <EyeOff size={14} /> : <Eye size={14} />}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-4 flex items-center gap-3">
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
                    onClick={() => { setExpandedId(null); setMessage(null); }}
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
