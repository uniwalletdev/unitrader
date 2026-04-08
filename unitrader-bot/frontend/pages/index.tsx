import Head from "next/head";
import Link from "next/link";
import { useState, useEffect, useRef } from "react";
import {
  ArrowRight, Check, Menu, X, ArrowLeftRight, Shield, Zap,
  Bot, TrendingUp, BarChart3, Lock, Clock, Sparkles, ChevronDown,
  MessageSquare, Activity, Globe, Eye,
} from "lucide-react";
import Footer from "@/components/layout/Footer";

// ─────────────────────────────────────────────
// Animated counter hook
// ─────────────────────────────────────────────

function useCounter(end: number, duration = 2000, start = 0) {
  const [value, setValue] = useState(start);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        obs.disconnect();
        const t0 = performance.now();
        const step = (now: number) => {
          const p = Math.min((now - t0) / duration, 1);
          setValue(Math.floor(start + (end - start) * p));
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      },
      { threshold: 0.3 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [end, duration, start]);
  return { value, ref };
}

// ─────────────────────────────────────────────
// Data
// ─────────────────────────────────────────────

const HEDGE_FUND_POINTS = [
  "AI reads 10,000+ news articles per second",
  "Teams of PhDs building proprietary models",
  "24/7 automated risk management",
  "$1M+ minimum investment",
  "Closed to the public",
];

const APEX_POINTS = [
  "Same AI analyses sentiment + technicals",
  "10 specialised AI agents working for you",
  "Position monitor checks every 5 minutes",
  "Start with any budget — even $10",
  "Open to everyone, right now",
];

const STATS = [
  { value: 40, suffix: "+", label: "Years", desc: "Institutions had AI trading before you" },
  { value: 70, suffix: "%", label: "Volume", desc: "Of all stock trades are already AI-driven" },
  { value: 10, suffix: "", label: "AI Agents", desc: "Working together to manage your portfolio" },
  { value: 24, suffix: "/7", label: "Non-stop", desc: "Monitoring, analysing, protecting your money" },
];

const STEPS = [
  {
    num: "01",
    icon: MessageSquare,
    title: "Have a conversation",
    desc: "Tell Unitrader your goals in plain English. No forms, no jargon. It adapts to your experience level — from complete beginner to crypto native.",
  },
  {
    num: "02",
    icon: Eye,
    title: "Watch it prove itself",
    desc: "Unitrader starts with paper money — zero risk. You see every trade, every decision, every reason. Build confidence before committing a single penny.",
  },
  {
    num: "03",
    icon: Zap,
    title: "Go live when you're ready",
    desc: "Connect your own exchange account. Unitrader trades for you while you sleep, eat, and live your life. You keep 100% of the profits.",
  },
];

const FEATURES = [
  { icon: Bot, title: "10 AI Agents", desc: "Specialised agents for research, risk, execution, and more — working as a team." },
  { icon: Shield, title: "Your Money, Your Account", desc: "Funds never leave your exchange. Unitrader connects via read/trade API only." },
  { icon: Activity, title: "Real-time Monitoring", desc: "Every position checked every 5 minutes. Stop-losses, take-profits, auto-adjustments." },
  { icon: MessageSquare, title: "Chat with Your AI", desc: "Ask anything — market analysis, trade rationale, portfolio advice. Unlimited." },
  { icon: Globe, title: "Stocks & Crypto", desc: "Trade US stocks via Alpaca and crypto via Coinbase — more exchanges coming." },
  { icon: Lock, title: "Paper Trading First", desc: "Prove the AI works with zero risk. No credit card needed to start." },
];

const TRUST_SIGNALS = [
  "Your money never leaves your exchange account",
  "Paper trading first — prove it before you risk anything",
  "Full audit trail of every AI decision",
  "Pause or stop AI trading at any time",
  "FCA risk warnings on every trade",
];

// ─────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────

export default function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Animated counters
  const c1 = useCounter(40, 1800);
  const c2 = useCounter(70, 1800);
  const c3 = useCounter(10, 1200);
  const c4 = useCounter(24, 1400);
  const counters = [c1, c2, c3, c4];

  return (
    <div className="min-h-screen bg-dark-950">
      <Head>
        <title>Unitrader — Your Personal AI Trader</title>
        <meta
          name="description"
          content="Unitrader is your personal AI trader. The same technology hedge funds use — 10 AI agents managing your portfolio 24/7. Start free, no credit card."
        />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" type="image/png" href="/logo-galaxy.png" />
        <link rel="apple-touch-icon" href="/logo-galaxy.png" />
        <meta property="og:title" content="Unitrader — Your Personal AI Trader" />
        <meta property="og:description" content="10 AI agents managing your portfolio 24/7. The same technology hedge funds use — now available to anyone." />
        <meta property="og:image" content="/logo-galaxy.png" />
        <meta name="twitter:card" content="summary_large_image" />
      </Head>

      {/* ── Navbar ──────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-white/[0.04] bg-dark-950/80 backdrop-blur-2xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3.5 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <img src="/logo-galaxy.png" alt="Unitrader" className="h-8 w-8 object-contain" />
            <span className="text-lg font-bold text-white tracking-tight">Unitrader</span>
          </Link>

          <nav className="hidden items-center gap-8 md:flex">
            {[
              { label: "How it works", href: "#how-it-works" },
              { label: "Features", href: "#features" },
              { label: "Pricing", href: "#pricing" },
            ].map((l) => (
              <a key={l.label} href={l.href} className="text-[13px] font-medium text-dark-400 transition hover:text-white">
                {l.label}
              </a>
            ))}
          </nav>

          <div className="hidden items-center gap-3 md:flex">
            <Link href="/login" className="text-[13px] font-medium text-dark-400 transition hover:text-white">
              Sign in
            </Link>
            <Link
              href="/register"
              className="rounded-xl bg-brand-500 px-5 py-2 text-[13px] font-semibold text-black transition hover:bg-brand-400 active:scale-95"
            >
              Start free
            </Link>
          </div>

          <button className="text-dark-400 md:hidden" onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>
            {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>

        {mobileMenuOpen && (
          <div className="border-t border-white/[0.04] px-4 pb-4 md:hidden bg-dark-950">
            {[
              { label: "How it works", href: "#how-it-works" },
              { label: "Features", href: "#features" },
              { label: "Pricing", href: "#pricing" },
            ].map((l) => (
              <a key={l.label} href={l.href} className="block py-2.5 text-sm text-dark-400" onClick={() => setMobileMenuOpen(false)}>
                {l.label}
              </a>
            ))}
            <div className="mt-2 flex gap-2">
              <Link href="/login" className="flex-1 rounded-xl border border-dark-700 py-2.5 text-center text-sm font-medium text-white" onClick={() => setMobileMenuOpen(false)}>
                Sign in
              </Link>
              <Link href="/register" className="flex-1 rounded-xl bg-brand-500 py-2.5 text-center text-sm font-semibold text-black" onClick={() => setMobileMenuOpen(false)}>
                Start free
              </Link>
            </div>
          </div>
        )}
      </header>

      <main>
        {/* ── HERO ──────────────────────────────────────────────── */}
        <section className="relative overflow-hidden px-4 pb-24 pt-20 sm:px-6 sm:pt-28 lg:pt-36">
          {/* Ambient glows */}
          <div className="pointer-events-none absolute left-1/2 top-0 h-[700px] w-[900px] -translate-x-1/2 rounded-full bg-brand-500/[0.06] blur-[160px]" />
          <div className="pointer-events-none absolute -left-40 top-40 h-[400px] w-[400px] rounded-full bg-purple-500/[0.04] blur-[120px]" />

          <div className="relative mx-auto max-w-3xl text-center">
            {/* Eyebrow */}
            <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-brand-500/20 bg-brand-500/[0.06] px-4 py-1.5 text-[13px] text-brand-400">
              <Sparkles size={14} />
              Your unfair advantage starts here
            </div>

            <h1 className="mb-6 text-[2.5rem] font-extrabold leading-[1.08] tracking-tight text-white sm:text-5xl md:text-[3.5rem]">
              10 AI agents.
              <br />
              <span className="bg-gradient-to-r from-brand-400 to-emerald-300 bg-clip-text text-transparent">
                One personal trader.
              </span>
              <br />
              Working 24/7 for you.
            </h1>

            <p className="mx-auto mb-10 max-w-[520px] text-base leading-relaxed text-dark-400 sm:text-lg">
              The same AI technology that made hedge funds billions is now
              available to everyone. Unitrader analyses markets, executes
              trades, and manages risk — while you live your life.
            </p>

            {/* CTAs */}
            <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
              <Link
                href="/register"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-500 px-8 py-4 text-base font-semibold text-black transition hover:bg-brand-400 hover:shadow-[0_0_40px_rgba(10,219,106,0.2)] active:scale-[0.98] sm:w-auto"
              >
                Start free — no credit card
                <ArrowRight size={18} />
              </Link>
              <a
                href="#how-it-works"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-dark-700 bg-dark-900/50 px-6 py-4 text-base font-medium text-dark-300 transition hover:border-dark-600 hover:text-white sm:w-auto"
              >
                See how it works
                <ChevronDown size={16} />
              </a>
            </div>

            {/* Trust pills */}
            <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
              {[
                "Your money stays in your account",
                "Paper trading first — zero risk",
                "No experience needed",
              ].map((t) => (
                <span key={t} className="inline-flex items-center gap-1.5 rounded-full border border-dark-800/60 bg-dark-900/40 px-3.5 py-1.5 text-xs text-dark-400">
                  <Check size={12} className="text-brand-400" />
                  {t}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* ── ANIMATED STATS ────────────────────────────────────── */}
        <section className="border-y border-dark-800/40 px-4 py-16 sm:px-6">
          <div className="mx-auto grid max-w-5xl gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {STATS.map((s, i) => (
              <div key={s.label} ref={counters[i].ref} className="rounded-2xl border border-dark-800/60 bg-[#0a0e14] p-6 text-center">
                <div className="mb-1 text-4xl font-extrabold tabular-nums text-brand-400">
                  {counters[i].value}{s.suffix}
                </div>
                <div className="mb-1 text-sm font-bold text-white">{s.label}</div>
                <p className="text-xs leading-relaxed text-dark-500">{s.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── INEQUALITY COMPARISON ─────────────────────────────── */}
        <section id="results" className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-3xl mb-14 text-center">
            <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
              The playing field, levelled
            </p>
            <h2 className="text-3xl font-bold text-white sm:text-4xl">
              What hedge funds had.<br className="hidden sm:block" /> What you get now.
            </h2>
          </div>

          <div className="mx-auto max-w-4xl rounded-2xl border border-dark-800/60 p-6 sm:p-10 bg-[#0a0e14]">
            <div className="grid gap-8 md:grid-cols-[1fr,auto,1fr]">
              <div>
                <div className="mb-5 inline-block rounded-full bg-red-500/10 px-3 py-1 text-xs font-semibold text-red-400 border border-red-500/15">
                  Hedge funds — since 1982
                </div>
                <ul className="space-y-3">
                  {HEDGE_FUND_POINTS.map((p) => (
                    <li key={p} className="flex items-start gap-2.5 text-sm leading-relaxed text-dark-400">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-red-400/60" />
                      {p}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="flex flex-col items-center justify-center gap-3">
                <div className="hidden h-full w-px bg-dark-800 md:block" />
                <div className="flex items-center gap-2 text-sm font-bold text-dark-500">
                  <span>vs</span>
                  <ArrowLeftRight size={14} className="text-dark-600" />
                </div>
                <span className="rounded-full bg-brand-500/10 px-2.5 py-0.5 text-xs font-semibold text-brand-400">
                  now
                </span>
                <div className="hidden h-full w-px bg-dark-800 md:block" />
              </div>

              <div>
                <div className="mb-5 inline-block rounded-full bg-brand-500/10 px-3 py-1 text-xs font-semibold text-brand-400 border border-brand-500/15">
                  You — with Unitrader
                </div>
                <ul className="space-y-3">
                  {APEX_POINTS.map((p) => (
                    <li key={p} className="flex items-start gap-2.5 text-sm leading-relaxed text-dark-300">
                      <Check size={14} className="mt-0.5 shrink-0 text-brand-400" />
                      {p}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* ── HOW IT WORKS ──────────────────────────────────────── */}
        <section id="how-it-works" className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-3xl">
            <div className="mb-14 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
                How it works
              </p>
              <h2 className="text-3xl font-bold text-white sm:text-4xl">
                Three steps. No complexity.
              </h2>
              <p className="mt-4 text-dark-400 max-w-md mx-auto">
                From sign-up to your first AI trade in under 5 minutes.
              </p>
            </div>

            <div className="space-y-10">
              {STEPS.map((step) => (
                <div key={step.num} className="flex gap-5 sm:gap-6">
                  <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-brand-500/20 bg-brand-500/[0.07]">
                    <step.icon size={22} className="text-brand-400" />
                  </div>
                  <div>
                    <div className="mb-1 text-[11px] font-bold uppercase tracking-widest text-dark-600">Step {step.num}</div>
                    <h3 className="mb-2 text-lg font-semibold text-white">{step.title}</h3>
                    <p className="max-w-md text-sm leading-relaxed text-dark-400">{step.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── FEATURES GRID ─────────────────────────────────────── */}
        <section id="features" className="px-4 py-20 sm:px-6 border-t border-dark-800/40">
          <div className="mx-auto max-w-5xl">
            <div className="mb-14 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
                Built different
              </p>
              <h2 className="text-3xl font-bold text-white sm:text-4xl">
                Everything a hedge fund has.<br className="hidden sm:block" /> Nothing you don&apos;t need.
              </h2>
            </div>

            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((f) => (
                <div
                  key={f.title}
                  className="group rounded-2xl border border-dark-800/60 bg-[#0a0e14] p-6 transition hover:border-brand-500/20 hover:bg-brand-500/[0.02]"
                >
                  <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-brand-500/10 text-brand-400 transition group-hover:bg-brand-500/15">
                    <f.icon size={20} />
                  </div>
                  <h3 className="mb-2 font-semibold text-white">{f.title}</h3>
                  <p className="text-sm leading-relaxed text-dark-400">{f.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── TRUST STRIP ─────────────────────────────────────── */}
        <section className="border-y border-dark-800/40 px-4 py-6 sm:px-6 bg-[#0a0e14]">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-center gap-x-8 gap-y-3">
            {TRUST_SIGNALS.map((s) => (
              <span key={s} className="inline-flex items-center gap-1.5 text-xs text-dark-400 sm:text-[13px]">
                <Check size={14} className="text-brand-400" />
                {s}
              </span>
            ))}
          </div>
        </section>

        {/* ── PRICING ────────────────────────────────────────── */}
        <section id="pricing" className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-5xl">
            <div className="mb-14 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
                Pricing
              </p>
              <h2 className="mb-4 text-3xl font-bold text-white sm:text-4xl">
                Start free. Upgrade when you&apos;re ready.
              </h2>
              <p className="text-dark-400 max-w-md mx-auto">
                No credit card required. No hidden fees. You keep 100% of your trading profits.
              </p>
            </div>

            <div className="grid gap-6 sm:grid-cols-3">
              {/* Free plan */}
              <div className="flex flex-col rounded-2xl border border-dark-800/60 bg-[#0a0e14] p-8">
                <div className="mb-6">
                  <p className="text-sm font-semibold uppercase tracking-widest text-dark-500">Free</p>
                  <div className="mt-2 flex items-end gap-1">
                    <span className="text-4xl font-bold text-white">$0</span>
                    <span className="mb-1 text-sm text-dark-500">forever</span>
                  </div>
                  <p className="mt-2 text-sm text-dark-400">Everything you need to start</p>
                </div>
                <ul className="mb-8 flex-1 space-y-3 text-sm text-dark-300">
                  {[
                    "1 exchange connection",
                    "5 AI trades per month",
                    "Unlimited AI chat",
                    "Live & paper trading",
                    "Performance dashboard",
                    "Telegram & WhatsApp alerts",
                  ].map((f) => (
                    <li key={f} className="flex items-center gap-2.5">
                      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-dark-800 text-[10px] text-dark-500">✓</span>
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/register"
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-dark-700 bg-dark-900 py-3 text-sm font-semibold text-dark-200 transition hover:border-dark-600 hover:text-white"
                >
                  Get started free
                </Link>
              </div>

              {/* Pro plan */}
              <div className="relative flex flex-col rounded-2xl border border-brand-500/30 bg-brand-500/[0.03] p-8 shadow-[0_0_60px_-15px_rgba(10,219,106,0.08)]">
                <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                  <span className="rounded-full border border-brand-500/30 bg-brand-500/20 px-4 py-1 text-[11px] font-bold uppercase tracking-wider text-brand-300">
                    Most popular
                  </span>
                </div>
                <div className="mb-6">
                  <p className="text-sm font-semibold uppercase tracking-widest text-brand-400">Pro</p>
                  <div className="mt-2 flex items-end gap-1">
                    <span className="text-4xl font-bold text-white">$9.99</span>
                    <span className="mb-1 text-sm text-dark-400">/ month</span>
                  </div>
                  <p className="mt-2 text-sm text-dark-400">14-day free trial included</p>
                </div>
                <ul className="mb-8 flex-1 space-y-3 text-sm text-dark-200">
                  {[
                    "3 exchange connections",
                    "Unlimited AI trades",
                    "Priority Claude AI (Opus)",
                    "Apex Selects signals",
                    "Daily AI briefings",
                    "Advanced analytics",
                    "Everything in Free",
                  ].map((f) => (
                    <li key={f} className="flex items-center gap-2.5">
                      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-[10px] text-brand-400">✓</span>
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/register"
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-500 py-3 text-sm font-semibold text-black transition hover:bg-brand-400 hover:shadow-[0_0_30px_rgba(10,219,106,0.15)] active:scale-[0.98]"
                >
                  Start 14-day free trial
                  <ArrowRight size={15} />
                </Link>
                <p className="mt-3 text-center text-[11px] text-dark-500">
                  No credit card required · Cancel anytime
                </p>
              </div>

              {/* Elite plan */}
              <div className="flex flex-col rounded-2xl border border-purple-500/25 bg-purple-500/[0.02] p-8">
                <div className="mb-6">
                  <p className="text-sm font-semibold uppercase tracking-widest text-purple-400">Elite</p>
                  <div className="mt-2 flex items-end gap-1">
                    <span className="text-4xl font-bold text-white">$29.99</span>
                    <span className="mb-1 text-sm text-dark-400">/ month</span>
                  </div>
                  <p className="mt-2 text-sm text-dark-400">Maximum power, full automation</p>
                </div>
                <ul className="mb-8 flex-1 space-y-3 text-sm text-dark-200">
                  {[
                    "Unlimited exchanges",
                    "Full Auto trading mode",
                    "Custom risk rules",
                    "API access",
                    "Priority support",
                    "Everything in Pro",
                  ].map((f) => (
                    <li key={f} className="flex items-center gap-2.5">
                      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-purple-500/20 text-[10px] text-purple-400">✓</span>
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/register?plan=elite"
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-purple-500 py-3 text-sm font-semibold text-white transition hover:bg-purple-400 active:scale-[0.98]"
                >
                  Go Elite
                  <ArrowRight size={15} />
                </Link>
                <p className="mt-3 text-center text-[11px] text-dark-500">
                  14-day free trial · Cancel anytime
                </p>
              </div>
            </div>

            <p className="mt-10 text-center text-sm text-dark-500">
              Already have an account?{" "}
              <Link href="/login" className="text-brand-400 hover:underline">Sign in</Link>
            </p>
          </div>
        </section>

        {/* ── FINAL CTA ──────────────────────────────────────── */}
        <section className="relative overflow-hidden px-4 py-24 sm:px-6">
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-brand-500/[0.04] to-transparent" />
          <div className="relative mx-auto max-w-2xl text-center">
            <h2 className="mb-4 text-3xl font-bold text-white sm:text-4xl">
              Ready to put AI to work<br />for your money?
            </h2>
            <p className="mb-8 text-dark-400">
              Join thousands of traders who let Unitrader handle the hard part. Free forever to get started.
            </p>
            <Link
              href="/register"
              className="inline-flex items-center gap-2 rounded-xl bg-brand-500 px-8 py-4 text-base font-semibold text-black transition hover:bg-brand-400 hover:shadow-[0_0_40px_rgba(10,219,106,0.2)] active:scale-[0.98]"
            >
              Create your free account
              <ArrowRight size={18} />
            </Link>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
