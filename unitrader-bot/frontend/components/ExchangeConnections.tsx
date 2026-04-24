import { useState, useEffect } from "react";
import {
  Link2, Unlink, ChevronDown, ChevronUp, Eye, EyeOff,
  CheckCircle, AlertCircle, Loader2, ExternalLink, Clipboard,
  Inbox,
} from "lucide-react";
import { authApi, exchangeApi, type ExchangeSpecPublic } from "@/lib/api";
import ExchangeConnectWizard from "@/components/settings/ExchangeConnectWizard";
import {
  getExchangeVisual,
  assetClassColors,
  connectionBarClass,
} from "@/lib/exchangeVisuals";

interface ConnectedExchange {
  trading_account_id?: string | null;
  exchange: string;
  account_label?: string | null;
  connected_at: string | null;
  is_paper: boolean;
  last_used: string | null;
}

// The hardcoded `EXCHANGES` array and `ExchangeDef` / `ExchangeField` types
// that used to live here were removed in Commit 6. This component now fetches
// the list of exchanges (plus their credential fields + connect instructions)
// from `GET /api/exchanges/list`, so the backend registry — including the
// `FEATURE_ETORO_ENABLED` filter — is the single source of truth.

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
  // Coinbase smart-paste — collapsed by default so Coinbase feels
  // consistent with every other exchange (manual fields visible first).
  // Users who know what a CDP JSON blob is can still expand the
  // one-paste shortcut via the "Got the raw JSON?" toggle.
  const [cbPasteRaw, setCbPasteRaw] = useState("");
  const [cbPasteStatus, setCbPasteStatus] = useState<CoinbasePasteStatus>({ kind: "idle" });
  const [cbSmartPasteOpen, setCbSmartPasteOpen] = useState(false);

  // Registry-driven list of available exchanges (GET /api/exchanges/list).
  const [specs, setSpecs] = useState<ExchangeSpecPublic[]>([]);
  const [specsLoading, setSpecsLoading] = useState(true);
  const [specsError, setSpecsError] = useState<string | null>(null);

  // eToro (and any future exchange with has_environment_toggle) uses the
  // full ExchangeConnectWizard modal because the env selector + single-key
  // credential shape doesn't map cleanly onto the inline api_key + api_secret
  // form used for the other exchanges.
  const [wizardExchangeId, setWizardExchangeId] = useState<string | null>(null);

  // Inline confirm-in-place for destructive Disconnect clicks. Keyed by
  // targetId so clicking one account's Disconnect doesn't arm confirms
  // on sibling rows. A 5s auto-dismiss prevents a stale armed state
  // from persisting if the user walks away.
  const [disconnectArmed, setDisconnectArmed] = useState<string | null>(null);
  useEffect(() => {
    if (!disconnectArmed) return;
    const t = window.setTimeout(() => setDisconnectArmed(null), 5000);
    return () => window.clearTimeout(t);
  }, [disconnectArmed]);

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

  const loadSpecs = async () => {
    setSpecsError(null);
    setSpecsLoading(true);
    try {
      const res = await exchangeApi.listExchanges();
      setSpecs(res.data.exchanges ?? []);
    } catch {
      setSpecsError("Couldn't load the list of exchanges. Please try again.");
      setSpecs([]);
    } finally {
      setSpecsLoading(false);
    }
  };

  useEffect(() => {
    loadConnected();
    loadSpecs();
  }, []);

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
      const isPaper = exchangeId === "coinbase" ? false : (connectModes[exchangeId] ?? true);
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
    const displayMode =
      String(connection.exchange || "").toLowerCase() === "coinbase"
        ? "live"
        : connection.is_paper
          ? "paper"
          : "live";
    const targetId = connection.trading_account_id || `${connection.exchange}-${displayMode}`;
    setDisconnectArmed(null);
    setDisconnecting(targetId);
    setMessage(null);
    try {
      await exchangeApi.disconnect(connection.exchange, {
        trading_account_id: connection.trading_account_id || undefined,
        is_paper: connection.is_paper,
      });
      setMessage({ type: "success", text: `${connection.account_label || `${connection.exchange} ${displayMode}`} disconnected.` });
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

  // Extracted render helper so the grouped "Connected" / "Available"
  // sections can share the exact same card markup. Previously inlined
  // inside specs.map; no behavioural change vs the pre-refactor render.
  const renderExchangeCard = (spec: ExchangeSpecPublic) => {
    const active = isConnected(spec.id);
    const connInfo = connectionsForExchange(spec.id);
    const expanded = expandedId === spec.id;
    const usesWizard = spec.has_environment_toggle === true;
    const docsUrl = spec.connect_instructions_url ?? "";
    const visual = getExchangeVisual(spec.id);
    const dotColors = assetClassColors(spec.asset_classes ?? []);
    const barClass = connectionBarClass(connInfo);

    const actionClass = active
      ? "flex items-center gap-1.5 rounded-lg border border-brand-500/30 px-3 py-1.5 text-xs text-brand-400 transition hover:bg-brand-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/50 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-950"
      : "flex items-center gap-1.5 rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-brand-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-950";

    return (
      <div
        key={spec.id}
        className={`relative overflow-hidden rounded-xl border bg-dark-950 transition ${
          active ? "border-brand-500/30" : "border-dark-800"
        }`}
      >
        {barClass && (
          <span
            aria-hidden="true"
            className={`absolute left-0 top-0 h-full w-[3px] ${barClass}`}
          />
        )}

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <div
              className={`flex h-9 w-9 items-center justify-center rounded-lg text-sm font-bold ${visual.tileBg} ${visual.tileFg}`}
            >
              {spec.display_name.charAt(0)}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-white">{spec.display_name}</span>
                {active && connInfo.length > 1 && (
                  <span className="text-[10px] text-dark-500">
                    · {connInfo.length} accounts
                  </span>
                )}
              </div>
              <div className="mt-0.5 flex items-center gap-1.5">
                {dotColors.length > 0 && (
                  <span className="flex items-center gap-0.5" aria-hidden="true">
                    {dotColors.map((c, i) => (
                      <span
                        key={i}
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ backgroundColor: c }}
                      />
                    ))}
                  </span>
                )}
                <p className="text-xs text-dark-500">{spec.tagline}</p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                if (usesWizard) {
                  setWizardExchangeId(spec.id);
                  setMessage(null);
                } else {
                  setExpandedId(expanded ? null : spec.id);
                  setMessage(null);
                }
              }}
              className={actionClass}
            >
              <Link2 size={12} />
              {active ? "Manage" : "Connect"}
              {!usesWizard && (expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
            </button>
          </div>
        </div>

        {/* Connected info */}
        {active && connInfo.length > 0 && (
          <div className="border-t border-dark-800 px-4 py-2">
            <div className="space-y-2 text-[10px] text-dark-500">
              {connInfo.map((connection) => {
                const displayMode =
                  String(connection.exchange || "").toLowerCase() === "coinbase"
                    ? "live"
                    : connection.is_paper
                      ? "paper"
                      : "live";
                const targetId = connection.trading_account_id || `${connection.exchange}-${displayMode}`;
                const isLive = displayMode === "live";
                return (
                  <div key={targetId} className="flex items-center justify-between gap-3 rounded-lg border border-dark-800 bg-dark-900/40 px-2.5 py-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`rounded px-1.5 py-[1px] text-[9px] font-semibold tracking-wider ${
                            isLive
                              ? "bg-brand-500/15 text-brand-400"
                              : "bg-amber-400/15 text-amber-300"
                          }`}
                        >
                          {isLive ? "LIVE" : "PAPER"}
                        </span>
                        <span className="truncate text-dark-300">
                          {connection.account_label || spec.display_name}
                        </span>
                      </div>
                      <div className="mt-0.5">
                        Connected {connection.connected_at ? new Date(connection.connected_at).toLocaleDateString() : ""}
                        {connection.last_used && ` · Last used ${new Date(connection.last_used).toLocaleDateString()}`}
                      </div>
                    </div>
                    {disconnectArmed === targetId ? (
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          onClick={() => handleDisconnect(connection)}
                          disabled={disconnecting === targetId}
                          className="flex items-center gap-1 rounded-lg bg-red-500/90 px-2.5 py-1 text-[10px] font-semibold text-white transition hover:bg-red-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-950 disabled:opacity-50"
                        >
                          {disconnecting === targetId ? (
                            <Loader2 size={11} className="animate-spin" />
                          ) : (
                            <Unlink size={11} />
                          )}
                          Confirm
                        </button>
                        <button
                          onClick={() => setDisconnectArmed(null)}
                          disabled={disconnecting === targetId}
                          className="rounded-lg border border-dark-700 px-2 py-1 text-[10px] text-dark-300 transition hover:bg-dark-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-dark-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-950"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDisconnectArmed(targetId)}
                        disabled={disconnecting === targetId}
                        className="flex shrink-0 items-center gap-1 rounded-lg border border-red-500/30 px-2.5 py-1 text-[10px] text-red-400 transition hover:bg-red-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/50 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-950 disabled:opacity-50"
                        aria-label={`Disconnect ${connection.account_label || spec.display_name}`}
                      >
                        <Unlink size={11} />
                        Disconnect
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Expansion form */}
        {expanded && !usesWizard && (
          <div className="border-t border-dark-800 p-3 sm:p-4">
            <div className="mb-4 flex items-center justify-between rounded-lg border border-dark-800 bg-dark-900/40 px-3 py-2">
              <div>
                <div className="text-xs font-medium text-white">Connection mode</div>
                <div className="text-[10px] text-dark-500">Keep paper and live accounts separate per exchange.</div>
              </div>
              {spec.id === "coinbase" ? (
                <span className="rounded-lg border border-dark-800 bg-dark-950 px-2.5 py-1 text-[11px] text-dark-400">
                  Live
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() =>
                    setConnectModes((prev) => ({ ...prev, [spec.id]: !(prev[spec.id] ?? true) }))
                  }
                  className="rounded-lg border border-dark-700 px-2.5 py-1 text-[11px] text-dark-200"
                >
                  {(connectModes[spec.id] ?? true) ? "Paper" : "Live"}
                </button>
              )}
            </div>
            {/* Registry-driven "how to get your keys" guide — rendered
                for EVERY exchange now, including Coinbase, so the
                expansion shape is consistent. */}
            {spec.connect_instructions_steps.length > 0 && (
              <div className="mb-3 rounded-lg border border-dark-800 bg-dark-900/40 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-[11px] font-semibold text-dark-300">
                    How to get your {spec.display_name} API keys
                  </div>
                  {docsUrl && (
                    <a
                      href={docsUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-[10px] text-brand-400 hover:underline"
                    >
                      Open portal <ExternalLink size={9} />
                    </a>
                  )}
                </div>
                <ol className="list-decimal space-y-1 pl-4 text-[11px] text-dark-400">
                  {spec.connect_instructions_steps.map((step, i) => (
                    <li key={i}>{step}</li>
                  ))}
                </ol>
              </div>
            )}

            {/* Coinbase-only: optional smart-paste shortcut, collapsed
                by default. Fills the two credential fields below from a
                pasted CDP JSON blob or PEM block. */}
            {spec.id === "coinbase" && (
              <div className="mb-3 rounded-lg border border-dark-800 bg-dark-900/40">
                <button
                  type="button"
                  onClick={() => setCbSmartPasteOpen((v) => !v)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[11px] font-medium text-dark-300 transition hover:bg-dark-900/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/40 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-950"
                  aria-expanded={cbSmartPasteOpen}
                >
                  <span className="flex items-center gap-1.5">
                    <Clipboard size={12} className="text-brand-400" />
                    Got the raw JSON? Paste it here
                  </span>
                  {cbSmartPasteOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </button>
                {cbSmartPasteOpen && (
                  <div className="border-t border-dark-800 p-3">
                    <p className="mb-2 text-[10px] text-dark-500">
                      Paste the full JSON from{" "}
                      <a
                        href={docsUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-brand-400 hover:underline"
                      >
                        portal.cdp.coinbase.com <ExternalLink size={8} className="inline" />
                      </a>
                      {" "}or a PEM block — we fill the fields below automatically.
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
                        Both fields filled below — scroll down to Connect &amp; Verify.
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
                        Key string detected — please also paste your Private Key (PEM) below.
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Standard credential fields — one shape for every
                exchange, including Coinbase. isSecret drives the show/
                hide eye toggle; multiline drives textarea vs input. */}
            <div className="space-y-3">
              {spec.credential_fields.map((field) => {
                const fieldId = `${spec.id}_${field.name}`;
                const isSecret = field.name === "api_secret" || field.type === "password";
                return (
                  <div key={field.name}>
                    <label className="mb-1 block text-xs text-dark-400">{field.label}</label>
                    <div className="relative">
                      {field.multiline ? (
                        <textarea
                          rows={6}
                          value={formValues[fieldId] || ""}
                          onChange={(e) =>
                            setFormValues((v) => ({ ...v, [fieldId]: e.target.value }))
                          }
                          placeholder={field.placeholder ?? ""}
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
                          placeholder={field.placeholder ?? ""}
                          className="input w-full pr-9 font-mono text-xs"
                          autoComplete="off"
                        />
                      )}
                      {isSecret && !field.multiline && (
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

            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
              <button
                onClick={() => handleConnect(spec.id)}
                disabled={submitting}
                className="btn-primary flex items-center gap-2 px-4 py-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-950 disabled:opacity-50"
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
                  setCbSmartPasteOpen(false);
                }}
                className="text-xs text-dark-500 hover:text-dark-300 focus-visible:outline-none focus-visible:underline"
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
  };

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

      {specsLoading && (
        <div className="flex items-center justify-center py-6 text-xs text-dark-500">
          <Loader2 size={14} className="mr-2 animate-spin" />
          Loading exchanges…
        </div>
      )}

      {!specsLoading && specsError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-3 text-xs text-red-300">
          <div className="mb-2 flex items-center gap-2">
            <AlertCircle size={13} />
            <span>{specsError}</span>
          </div>
          <button
            type="button"
            onClick={loadSpecs}
            className="rounded-md border border-red-500/30 px-2.5 py-1 text-[11px] text-red-200 hover:bg-red-500/10"
          >
            Retry
          </button>
        </div>
      )}

      {!specsLoading && !specsError && specs.length === 0 && (
        <div className="rounded-xl border border-dark-800 bg-dark-900/40 px-4 py-8 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-dark-800">
            <Inbox size={18} className="text-dark-500" />
          </div>
          <div className="text-sm font-medium text-dark-200">
            Nothing to connect yet
          </div>
          <p className="mx-auto mt-1 max-w-xs text-[11px] leading-relaxed text-dark-500">
            This usually means your session expired or the registry is
            still loading. Retry to refresh the list.
          </p>
          <button
            type="button"
            onClick={loadSpecs}
            className="mt-4 rounded-lg border border-brand-500/30 px-3 py-1.5 text-xs text-brand-400 transition hover:bg-brand-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/50 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-950"
          >
            Retry
          </button>
        </div>
      )}

      {/* Soft grouping: connected exchanges float to the top under a
          "Connected" header; everything else sits under "Available".
          Preserves backend spec priority order WITHIN each group. */}
      {(() => {
        const connectedSpecs = specs.filter((s) => isConnected(s.id));
        const availableSpecs = specs.filter((s) => !isConnected(s.id));
        const showGroupLabels =
          connectedSpecs.length > 0 && availableSpecs.length > 0;
        const groups: Array<{ label: string; items: ExchangeSpecPublic[] }> = [];
        if (connectedSpecs.length > 0) {
          groups.push({ label: "Connected", items: connectedSpecs });
        }
        if (availableSpecs.length > 0) {
          groups.push({ label: "Available", items: availableSpecs });
        }
        return groups.map((group) => (
          <div key={group.label} className="space-y-3">
            {showGroupLabels && (
              <div className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-dark-500">
                {group.label}
              </div>
            )}
            {group.items.map((spec) => renderExchangeCard(spec))}
          </div>
        ));
      })()}


      {/* Environment-toggle exchanges (e.g. eToro) open the full wizard modal
          because their credential shape (single user key + demo/real toggle)
          doesn't map onto the inline api_key+api_secret form. */}
      {wizardExchangeId && (
        <ExchangeConnectWizard
          exchange={wizardExchangeId}
          onSuccess={async () => {
            setWizardExchangeId(null);
            await loadConnected();
            onConnected?.();
          }}
          onClose={() => setWizardExchangeId(null)}
        />
      )}
    </div>
  );
}
