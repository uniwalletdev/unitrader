import { useState, useEffect } from "react";
import {
  Shield, Loader2, Smartphone, MessageCircle, Send as SendIcon,
  Link2, Unlink, Copy, Check, AlertCircle, QrCode,
} from "lucide-react";
import { authApi } from "@/lib/api";

interface ExternalAccount {
  platform: string;
  external_id: string;
  linked_at?: string;
}

export default function SecuritySettings() {
  const [accounts, setAccounts] = useState<ExternalAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [twoFASetup, setTwoFASetup] = useState<{ secret?: string; qr_uri?: string } | null>(null);
  const [twoFACode, setTwoFACode] = useState("");
  const [verifying2FA, setVerifying2FA] = useState(false);
  const [linkingCode, setLinkingCode] = useState<{ platform: string; code: string } | null>(null);
  const [generatingCode, setGeneratingCode] = useState<string | null>(null);
  const [unlinking, setUnlinking] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    authApi.externalAccounts()
      .then((r) => {
        const d = r.data?.data || r.data?.accounts || r.data || [];
        setAccounts(Array.isArray(d) ? d : []);
      })
      .catch(() => setAccounts([]))
      .finally(() => setLoading(false));
  }, []);

  const isLinked = (platform: string) => accounts.some((a) => a.platform === platform);

  const handleSetup2FA = async () => {
    setMessage(null);
    try {
      const res = await authApi.setup2FA();
      setTwoFASetup(res.data.data || res.data);
    } catch (err: any) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Failed to set up 2FA." });
    }
  };

  const handleVerify2FA = async () => {
    if (!twoFACode.trim()) return;
    setVerifying2FA(true);
    setMessage(null);
    try {
      await authApi.verify2FA(twoFACode.trim());
      setMessage({ type: "success", text: "Two-factor authentication enabled!" });
      setTwoFASetup(null);
      setTwoFACode("");
    } catch (err: any) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Invalid code. Please try again." });
    } finally {
      setVerifying2FA(false);
    }
  };

  const handleGenerateCode = async (platform: "telegram" | "whatsapp") => {
    setGeneratingCode(platform);
    setMessage(null);
    setLinkingCode(null);
    try {
      const res = platform === "telegram"
        ? await authApi.telegramCode()
        : await authApi.whatsappCode();
      const code = res.data.data?.code || res.data.code;
      setLinkingCode({ platform, code });
    } catch (err: any) {
      setMessage({ type: "error", text: err.response?.data?.detail || `Failed to generate ${platform} code.` });
    } finally {
      setGeneratingCode(null);
    }
  };

  const handleUnlink = async (platform: string) => {
    if (!confirm(`Unlink ${platform}?`)) return;
    setUnlinking(platform);
    setMessage(null);
    try {
      await authApi.unlinkAccount(platform);
      setAccounts((prev) => prev.filter((a) => a.platform !== platform));
      setMessage({ type: "success", text: `${platform} unlinked.` });
    } catch {
      setMessage({ type: "error", text: `Failed to unlink ${platform}.` });
    } finally {
      setUnlinking(null);
    }
  };

  const copyCode = () => {
    if (linkingCode?.code) {
      navigator.clipboard.writeText(linkingCode.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-6 text-sm text-dark-500">
        <Loader2 size={14} className="mr-2 animate-spin" /> Loading...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Shield size={16} className="text-brand-400" />
        <h2 className="text-sm font-semibold text-dark-200">Security & Connected Apps</h2>
      </div>

      {message && (
        <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${
          message.type === "success" ? "bg-brand-500/10 text-brand-400" : "bg-red-500/10 text-red-400"
        }`}>
          {message.type === "error" ? <AlertCircle size={12} /> : <Check size={12} />}
          {message.text}
        </div>
      )}

      {/* 2FA Section */}
      <div className="rounded-lg border border-dark-700 p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Smartphone size={14} className="text-dark-400" />
            <span className="text-sm text-dark-300">Two-Factor Authentication</span>
          </div>
          {!twoFASetup && (
            <button onClick={handleSetup2FA} className="text-xs text-brand-400 hover:underline">
              Enable 2FA
            </button>
          )}
        </div>

        {twoFASetup && (
          <div className="mt-3 space-y-3 border-t border-dark-700 pt-3">
            <p className="text-xs text-dark-400">
              Scan this code with your authenticator app (Google Authenticator, Authy, etc.):
            </p>
            {twoFASetup.qr_uri && (
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-white p-2">
                  <QrCode size={20} className="text-dark-950" />
                </div>
                <code className="flex-1 break-all rounded bg-dark-900 px-2 py-1 text-[10px] text-dark-400">
                  {twoFASetup.secret}
                </code>
              </div>
            )}
            <div className="flex gap-2">
              <input
                value={twoFACode}
                onChange={(e) => setTwoFACode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                onKeyDown={(e) => e.key === "Enter" && handleVerify2FA()}
                placeholder="6-digit code"
                className="input flex-1 font-mono text-center tracking-widest"
                maxLength={6}
              />
              <button
                onClick={handleVerify2FA}
                disabled={twoFACode.length !== 6 || verifying2FA}
                className="btn-primary px-4 text-xs disabled:opacity-50"
              >
                {verifying2FA ? <Loader2 size={12} className="animate-spin" /> : "Verify"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Telegram */}
      <div className="rounded-lg border border-dark-700 p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <SendIcon size={14} className="text-sky-400" />
            <span className="text-sm text-dark-300">Telegram</span>
            {isLinked("telegram") && (
              <span className="rounded-full bg-brand-500/10 px-2 py-0.5 text-[10px] font-medium text-brand-400">
                Connected
              </span>
            )}
          </div>
          {isLinked("telegram") ? (
            <button
              onClick={() => handleUnlink("telegram")}
              disabled={unlinking === "telegram"}
              className="flex items-center gap-1 text-xs text-red-400 hover:underline disabled:opacity-50"
            >
              {unlinking === "telegram" ? <Loader2 size={10} className="animate-spin" /> : <Unlink size={10} />}
              Unlink
            </button>
          ) : (
            <button
              onClick={() => handleGenerateCode("telegram")}
              disabled={generatingCode === "telegram"}
              className="flex items-center gap-1 text-xs text-brand-400 hover:underline disabled:opacity-50"
            >
              {generatingCode === "telegram" ? <Loader2 size={10} className="animate-spin" /> : <Link2 size={10} />}
              Link
            </button>
          )}
        </div>
        {linkingCode?.platform === "telegram" && (
          <div className="mt-2 flex items-center gap-2 rounded-md bg-dark-900 px-3 py-2">
            <code className="flex-1 text-center font-mono text-lg tracking-widest text-brand-400">
              {linkingCode.code}
            </code>
            <button onClick={copyCode} className="text-dark-500 hover:text-dark-300">
              {copied ? <Check size={14} className="text-brand-400" /> : <Copy size={14} />}
            </button>
          </div>
        )}
      </div>

      {/* WhatsApp */}
      <div className="rounded-lg border border-dark-700 p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageCircle size={14} className="text-green-400" />
            <span className="text-sm text-dark-300">WhatsApp</span>
            {isLinked("whatsapp") && (
              <span className="rounded-full bg-brand-500/10 px-2 py-0.5 text-[10px] font-medium text-brand-400">
                Connected
              </span>
            )}
          </div>
          {isLinked("whatsapp") ? (
            <button
              onClick={() => handleUnlink("whatsapp")}
              disabled={unlinking === "whatsapp"}
              className="flex items-center gap-1 text-xs text-red-400 hover:underline disabled:opacity-50"
            >
              {unlinking === "whatsapp" ? <Loader2 size={10} className="animate-spin" /> : <Unlink size={10} />}
              Unlink
            </button>
          ) : (
            <button
              onClick={() => handleGenerateCode("whatsapp")}
              disabled={generatingCode === "whatsapp"}
              className="flex items-center gap-1 text-xs text-brand-400 hover:underline disabled:opacity-50"
            >
              {generatingCode === "whatsapp" ? <Loader2 size={10} className="animate-spin" /> : <Link2 size={10} />}
              Link
            </button>
          )}
        </div>
        {linkingCode?.platform === "whatsapp" && (
          <div className="mt-2 flex items-center gap-2 rounded-md bg-dark-900 px-3 py-2">
            <code className="flex-1 text-center font-mono text-lg tracking-widest text-brand-400">
              {linkingCode.code}
            </code>
            <button onClick={copyCode} className="text-dark-500 hover:text-dark-300">
              {copied ? <Check size={14} className="text-brand-400" /> : <Copy size={14} />}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
