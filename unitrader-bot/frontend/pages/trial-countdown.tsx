/**
 * /trial-countdown — Full-page trial overview.
 * Shows animated countdown, AI performance summary, and path options.
 */
import Head from "next/head";
import Link from "next/link";
import { useState, useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/router";
import {
  TrendingUp, Zap, Shield, BarChart3, Clock, ArrowRight, CheckCircle,
} from "lucide-react";
import { useTrialStatus } from "@/hooks/useTrialStatus";
import TrialChoiceModal from "@/components/TrialChoiceModal";

// ── Animated countdown number ─────────────────────────────────────────────────
function CountdownRing({ days, total = 14 }: { days: number; total?: number }) {
  const pct = Math.max(0, Math.min(1, days / total));
  const r = 54;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - pct);

  const color = days <= 1 ? "#f85149" : days <= 3 ? "#fb8f44" : "#7c3aed";

  return (
    <div className="relative flex items-center justify-center w-36 h-36 mx-auto">
      <svg className="absolute inset-0 -rotate-90" width="144" height="144">
        <circle cx="72" cy="72" r={r} fill="none" stroke="#21262d" strokeWidth="8" />
        <circle
          cx="72" cy="72" r={r}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 1s ease, stroke 0.5s ease" }}
        />
      </svg>
      <div className="text-center z-10">
        <span className="text-4xl font-extrabold text-white">{days}</span>
        <p className="text-xs text-dark-400 mt-0.5">
          day{days !== 1 ? "s" : ""}<br />left
        </p>
      </div>
    </div>
  );
}

// ── Stat pill ─────────────────────────────────────────────────────────────────
function Stat({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950 px-5 py-4 text-center">
      <p className="text-xs text-dark-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${
        positive === undefined ? "text-white" : positive ? "text-brand-400" : "text-red-400"
      }`}>{value}</p>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function TrialCountdownPage() {
  const { isLoaded, isSignedIn } = useAuth();
  const router = useRouter();
  const [showModal, setShowModal] = useState(false);

  const { trial, loading, mustShowModal } = useTrialStatus({ skip: !isSignedIn });

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) { router.replace("/login"); return; }
  }, [isLoaded, isSignedIn, router]);

  useEffect(() => {
    if (mustShowModal || router.query.modal === "trial") setShowModal(true);
  }, [mustShowModal, router.query.modal]);

  if (!isLoaded || loading) {
    return (
      <div className="min-h-screen bg-dark-950 flex items-center justify-center">
        <div className="w-10 h-10 border-4 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isSignedIn || (!loading && !trial)) { return null; }
  if (!trial) return null;

  const p = trial.performance;
  const pnlPositive = p.net_pnl >= 0;
  const endDate = trial.trialEndDate
    ? new Date(trial.trialEndDate).toLocaleDateString("en-GB", {
        day: "numeric", month: "long", year: "numeric",
      })
    : "—";

  return (
    <>
      <Head>
        <title>Your Trial — {trial.ai_name} | Unitrader</title>
      </Head>

      <div className="min-h-screen bg-dark-950 text-white">
        {/* Top nav */}
        <nav className="border-b border-dark-800 px-6 py-4 flex items-center justify-between">
          <Link href="/app" className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-brand-500 flex items-center justify-center">
              <TrendingUp size={13} className="text-dark-950" />
            </div>
            <span className="font-bold text-white">Unitrader</span>
          </Link>
          <Link href="/app" className="btn-outline py-1.5 text-xs">← Back to Dashboard</Link>
        </nav>

        <main className="mx-auto max-w-2xl px-4 py-12">
          {/* Header */}
          <div className="text-center mb-10">
            <div className="inline-flex items-center gap-2 rounded-full border border-brand-500/30 bg-brand-500/10 px-4 py-1.5 text-sm text-brand-400 mb-4">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse" />
              {trial.aiName} — Trial Active
            </div>
            <h1 className="text-3xl font-extrabold text-white mb-3">
              Your 14-Day Trial
            </h1>
            <p className="text-dark-400">{trial.performanceSummary}</p>
          </div>

          {/* Countdown ring */}
          <div className="rounded-2xl border border-dark-700 bg-dark-900 p-8 mb-6 text-center">
            <CountdownRing days={trial.daysRemaining} />
            <p className="mt-4 text-sm text-dark-400">
              Trial ends <span className="text-white font-medium">{endDate}</span>
            </p>

            {trial.daysRemaining <= 1 && (
              <div className="mt-4 rounded-lg bg-red-500/10 border border-red-500/30 px-4 py-3 text-sm text-red-400">
                {trial.daysRemaining === 0
                  ? "Your trial has expired. Choose a plan to continue."
                  : "Your trial expires tomorrow! Choose your plan now."}
              </div>
            )}
          </div>

          {/* AI Performance */}
          <h2 className="text-sm font-semibold uppercase tracking-widest text-dark-400 mb-3">
            {trial.ai_name}&apos;s Performance
          </h2>
          <div className="grid grid-cols-3 gap-3 mb-8">
            <Stat
              label="Net P&L"
              value={`${pnlPositive ? "+" : ""}$${p.net_pnl.toFixed(2)}`}
              positive={pnlPositive}
            />
            <Stat label="Win Rate" value={`${p.win_rate_pct}%`} positive={p.win_rate_pct >= 50} />
            <Stat label="Trades" value={String(p.trades_made)} />
          </div>

          {/* Phase-specific message */}
          <div className={`rounded-xl border px-5 py-4 mb-8 flex items-start gap-3 ${
            trial.phase === "late" || trial.phase === "expired"
              ? "border-red-500/30 bg-red-500/5"
              : trial.phase === "mid"
              ? "border-yellow-500/30 bg-yellow-500/5"
              : "border-brand-500/30 bg-brand-500/5"
          }`}>
            <Clock size={18} className="shrink-0 mt-0.5 text-dark-400" />
            <p className="text-sm text-dark-300">{trial.banner}</p>
          </div>

          {/* Removed TrialStatus interface — now using hook */ }

          {/* CTA */}
          <div className="flex flex-col gap-3">
            <button
              onClick={() => setShowModal(true)}
              className="btn-primary w-full py-3.5 text-base"
            >
              Choose My Plan <ArrowRight size={16} className="ml-1" />
            </button>
            <Link href="/app" className="btn-outline w-full text-center py-3">
              Back to Dashboard
            </Link>
          </div>

          {/* What you get with Pro */}
          <div className="mt-10 rounded-2xl border border-dark-700 bg-dark-900 p-6">
            <h3 className="font-bold text-white mb-4 flex items-center gap-2">
              <Zap size={16} className="text-brand-400" />
              Why Pro is worth $9.99/mo
            </h3>
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                { icon: TrendingUp, text: "Unlimited trades on any exchange" },
                { icon: Shield,     text: "Hard risk guardrails protect your capital" },
                { icon: BarChart3,  text: "Full analytics and performance reports" },
                { icon: Zap,        text: "Priority Claude AI — fastest decisions" },
                { icon: CheckCircle, text: "Email alerts for every trade" },
                { icon: CheckCircle, text: "Cancel anytime, no contracts" },
              ].map(({ icon: Icon, text }) => (
                <div key={text} className="flex items-center gap-2 text-sm text-dark-300">
                  <Icon size={14} className="text-brand-400 shrink-0" />
                  {text}
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>

      {showModal && trial && (
        <TrialChoiceModal
          aiName={trial.aiName}
          daysRemaining={trial.daysRemaining}
          stats={p}
          onClose={mustShowModal ? undefined : () => setShowModal(false)}
        />
      )}
    </>
  );
}
