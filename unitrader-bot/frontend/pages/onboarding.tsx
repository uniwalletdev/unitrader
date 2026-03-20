/**
 * Onboarding — shown after Clerk sign-up.
 * Step 0: Context screen ("Before we start")
 * Step 1: Name your AI (existing Apex chat / setup)
 */
import { useAuth } from "@clerk/nextjs";
import Head from "next/head";
import { useRouter } from "next/router";
import { useState, useEffect, useCallback } from "react";
import { ArrowRight, Zap, RefreshCw } from "lucide-react";
import { authApi } from "@/lib/api";

// ─────────────────────────────────────────────
// Comparison table data
// ─────────────────────────────────────────────

const COMPARISON_ROWS = [
  { need: "Market analysis", institution: "£10M trading desk", apex: "Apex — included" },
  { need: "Sentiment analysis", institution: "Bloomberg Terminal £24k/yr", apex: "Built into Apex" },
  { need: "24/7 position watch", institution: "Operations team", apex: "Position Monitor Agent" },
  { need: "Risk management", institution: "Risk department", apex: "Risk Agent + circuit breaker" },
  { need: "Trade execution", institution: "Execution desk", apex: "Direct to Alpaca or Coinbase" },
];

// ─────────────────────────────────────────────
// Step 0 — Context screen
// ─────────────────────────────────────────────

function ContextStep({ onContinue }: { onContinue: () => void }) {
  return (
    <div className="min-h-screen flex flex-col items-center px-4 py-12 sm:py-16 bg-dark-950">
      <div className="w-full max-w-2xl animate-fade-in">
        <p className="mb-10 text-center text-[11px] uppercase tracking-widest text-dark-500">1 of 5</p>

        <h1 className="mb-4 text-center text-3xl font-bold tracking-tight text-white sm:text-4xl">
          Before we start — what you should know
        </h1>
        <p className="mx-auto mb-12 max-w-lg text-center text-sm leading-relaxed text-dark-400">
          Apex is the same type of AI technology that hedge funds have used for 40 years.
          The difference is you now have access to it.
        </p>

        <div className="mb-8 rounded-2xl border border-dark-800 bg-[#0d1117] p-6">
          <h2 className="section-label mb-5" style={{display:'block',fontSize:'11px',fontWeight:600,textTransform:'uppercase',letterSpacing:'0.08em',color:'#6b7280'}}>
            What Apex gives you that was previously only for institutions
          </h2>

          <div className="mb-3 grid grid-cols-3 gap-3 text-[11px] font-semibold uppercase tracking-wider">
            <span className="text-dark-500">What you need</span>
            <span className="text-red-400">What institutions pay</span>
            <span className="text-brand-400">What Apex provides</span>
          </div>

          <div className="space-y-1.5">
            {COMPARISON_ROWS.map((row) => (
              <div
                key={row.need}
                className="grid grid-cols-3 gap-3 rounded-xl border border-dark-800/50 px-3 py-2.5 text-xs sm:text-sm bg-white/[0.01]"
              >
                <span className="text-dark-300">{row.need}</span>
                <span className="text-red-400/70">{row.institution}</span>
                <span className="text-brand-400">{row.apex}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="mb-8 flex gap-4 rounded-2xl border-l-2 border-brand-500 bg-[#0d1117] p-5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-500/15">
            <Zap size={18} className="text-brand-400" />
          </div>
          <p className="text-sm leading-relaxed text-dark-300">
            Hi, I&apos;m <strong className="text-white">Apex</strong> — your personal AI trader.
            I&apos;ll analyse the markets, tell you exactly what I&apos;m thinking and why,
            and trade on your behalf. Your money stays in your own exchange account — I only
            place the orders. You can pause me any time. Let&apos;s set you up.
          </p>
        </div>

        <button
          onClick={onContinue}
          className="btn-primary w-full py-4 text-base"
        >
          Meet Apex — let&apos;s talk
          <ArrowRight size={18} />
        </button>

        <p className="mt-6 text-center text-[10px] leading-relaxed text-dark-600">
          Trading involves risk of loss. Past performance does not guarantee future results.
          Apex is an AI tool, not a regulated financial advisor.
        </p>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Main onboarding page
// ─────────────────────────────────────────────

export default function OnboardingPage() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState(0); // 0 = context, 1 = name AI
  const [aiName, setAiName] = useState("");
  const [formError, setFormError] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(true);
  const [syncError, setSyncError] = useState("");
  const [userId, setUserId] = useState<string | null>(null);

  const runSync = useCallback(async () => {
    setSyncing(true);
    setSyncError("");
    try {
      const token = await getToken();
      if (!token) throw new Error("No auth token — please sign in again.");
      const res = await authApi.clerkSync(token);
      if (res.data.status === "logged_in") {
        localStorage.setItem("access_token", res.data.access_token);
        router.replace("/app");
      } else if (res.data.status === "needs_setup") {
        setUserId(res.data.user_id);
        setSyncing(false);
      } else {
        setSyncError("Unexpected server response. Please try again.");
        setSyncing(false);
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSyncError(msg || "Could not connect to the server. Please try again.");
      setSyncing(false);
    }
  }, [getToken, router]);

  // On mount, sync Clerk session with our backend
  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      router.replace("/register");
      return;
    }
    runSync();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId) {
      setFormError("Session expired — please refresh the page.");
      return;
    }
    setFormError("");

    const trimmed = aiName.trim();
    if (!/^[A-Za-z0-9_]{2,20}$/.test(trimmed)) {
      setFormError("2–20 characters, letters/numbers/underscores only.");
      return;
    }

    setLoading(true);
    try {
      const res = await authApi.clerkSetup(userId, trimmed);
      localStorage.setItem("access_token", res.data.access_token);
      router.replace("/app");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setFormError(msg || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  if (!isLoaded || syncing) {
    return (
      <div className="min-h-screen bg-dark-950 flex items-center justify-center">
        <div className="text-center">
          <RefreshCw size={18} className="animate-spin text-brand-400 mx-auto mb-4" />
          <p className="text-dark-400 text-sm">Setting up your account…</p>
        </div>
      </div>
    );
  }

  if (syncError) {
    return (
      <div className="min-h-screen bg-dark-950 flex items-center justify-center px-4">
        <div className="w-full max-w-sm text-center">
          <div className="mb-5 rounded-2xl border border-red-500/20 bg-red-500/[0.04] px-5 py-5 text-sm text-red-300">
            <p className="font-semibold mb-1">Could not connect</p>
            <p className="text-xs text-red-400">{syncError}</p>
          </div>
          <button
            type="button"
            onClick={runSync}
            className="btn-primary gap-2 w-full"
          >
            <RefreshCw size={15} /> Try again
          </button>
        </div>
      </div>
    );
  }

  // Step 0 — Context screen
  if (step === 0) {
    return (
      <>
        <Head>
          <title>Before we start — Unitrader</title>
        </Head>
        <ContextStep onContinue={() => setStep(1)} />
      </>
    );
  }

  // Step 1 — Name your AI
  return (
    <>
      <Head>
        <title>Name Your AI — Unitrader</title>
      </Head>

      <div className="min-h-screen bg-dark-950 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-md animate-fade-in">
          <div className="flex items-center gap-2.5 mb-8 justify-center">
            <div className="w-9 h-9 rounded-xl bg-brand-500/15 flex items-center justify-center">
              <span className="text-brand-400 font-bold text-lg">U</span>
            </div>
            <span className="text-white font-bold text-xl tracking-tight">Unitrader</span>
          </div>

          <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-8 text-center">
            <div className="w-16 h-16 rounded-2xl bg-brand-500/10 flex items-center justify-center mx-auto mb-5">
              <span className="text-3xl">😊</span>
            </div>

            <h1 className="text-2xl font-bold tracking-tight text-white mb-2">
              Name your AI
            </h1>
            <p className="text-dark-400 text-sm mb-8 leading-relaxed">
              Give your personal trading AI a name. You&apos;ll see it throughout the dashboard.
              <br />
              <span className="text-dark-500 text-xs mt-1 block">e.g. TradeMaster, AlphaBot, Nexus</span>
            </p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <input
                type="text"
                value={aiName}
                onChange={(e) => setAiName(e.target.value)}
                placeholder="e.g. TradeMaster"
                maxLength={20}
                className="input text-center text-lg font-semibold tracking-wide"
                autoFocus
              />

              {formError && (
                <p className="text-red-400 text-sm">{formError}</p>
              )}

              <button
                type="submit"
                disabled={loading || !aiName.trim()}
                className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? "Saving…" : "Launch My AI →"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
