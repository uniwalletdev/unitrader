import Head from "next/head";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Check, Menu, X, ArrowLeftRight } from "lucide-react";
import Footer from "@/components/layout/Footer";

// ─────────────────────────────────────────────
// Data
// ─────────────────────────────────────────────

const HEDGE_FUND_POINTS = [
  "AI reads 10,000 news articles per second",
  "Teams of PhDs building proprietary models",
  "24/7 automated risk management",
  "$1M+ minimum investment",
  "Closed to the public",
];

const APEX_POINTS = [
  "AI analyses sentiment + technical indicators",
  "10 agents built on the same underlying AI",
  "Position monitor checks every 5 minutes",
  "Start with your own budget",
  "Open to everyone",
];

const STATS_DATA = [
  { value: "40+", desc: "Years institutions had AI trading before you could access it" },
  { value: "70%", desc: "Of all stock market volume is already algorithmic or AI-driven" },
  { value: "Any size", desc: "Start at your pace. Your money never leaves your exchange account" },
];

const STEPS = [
  {
    num: "01",
    title: "Tell Unitrader your goal",
    desc: "A short conversation. No forms. Unitrader learns whether you want to grow savings, generate income, or explore crypto.",
  },
  {
    num: "02",
    title: "Watch Unitrader prove itself",
    desc: "Unitrader starts in Watch Mode — trading with paper money first. You see every decision and why. No real money at risk.",
  },
  {
    num: "03",
    title: "Let Unitrader trade for you",
    desc: "Once you trust Unitrader, it trades with real money through your own Alpaca or Coinbase account. You keep 100% of profits.",
  },
];

const TRUST_SIGNALS = [
  "Unitrader never holds your funds",
  "Paper trading first — watch Unitrader prove itself",
  "FCA risk warnings on every trade",
  "Full audit trail of every AI decision",
  "Pause Unitrader any time",
];

// ─────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────

export default function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div className="min-h-screen bg-dark-950">
      <Head>
        <title>Unitrader — Your Personal AI Trader</title>
        <meta
          name="description"
          content="Unitrader is your personal AI trader. The same technology that's made hedge funds billions — now available to anyone."
        />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" type="image/png" href="/logo-galaxy.png" />
        <link rel="apple-touch-icon" href="/logo-galaxy.png" />
      </Head>

      {/* ── Navbar ─────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-dark-800/40 bg-dark-950/85 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo-galaxy.png" alt="Unitrader" className="h-9 w-9 object-contain" />
            <span className="text-lg font-bold text-white">Unitrader</span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden items-center gap-8 md:flex">
            {[
              { label: "How it works", href: "#how-it-works" },
              { label: "Results", href: "#results" },
              { label: "Pricing", href: "#pricing" },
            ].map((l) => (
              <a key={l.label} href={l.href} className="text-sm text-dark-400 transition hover:text-white">
                {l.label}
              </a>
            ))}
          </nav>

          {/* Desktop CTA */}
          <Link
            href="/register"
            className="hidden rounded-xl bg-brand-500 px-5 py-2 text-sm font-semibold text-black transition hover:bg-brand-400 active:scale-95 md:inline-flex"
          >
            Start free
          </Link>

          {/* Mobile toggle */}
          <button className="text-dark-400 md:hidden" onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>
            {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>

        {/* Mobile menu */}
        {mobileMenuOpen && (
          <div className="border-t border-dark-800/40 px-4 pb-4 md:hidden bg-dark-950">
            {[
              { label: "How it works", href: "#how-it-works" },
              { label: "Results", href: "#results" },
              { label: "Pricing", href: "#pricing" },
            ].map((l) => (
              <a
                key={l.label}
                href={l.href}
                className="block py-2.5 text-sm text-dark-400"
                onClick={() => setMobileMenuOpen(false)}
              >
                {l.label}
              </a>
            ))}
            <Link
              href="/register"
              className="mt-3 block w-full rounded-xl bg-brand-500 py-2.5 text-center text-sm font-semibold text-black"
              onClick={() => setMobileMenuOpen(false)}
            >
              Start free
            </Link>
          </div>
        )}
      </header>

      <main>
        {/* ── HERO ─────────────────────────────────────────────────── */}
        <section className="relative overflow-hidden px-4 pb-20 pt-24 sm:px-6 sm:pt-32">
          {/* Subtle glow */}
          <div className="pointer-events-none absolute left-1/2 top-0 h-[600px] w-[800px] -translate-x-1/2 rounded-full bg-brand-500/5 blur-[120px]" />

          <div className="relative mx-auto max-w-3xl text-center">
            {/* Eyebrow pill */}
            <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-brand-500/30 px-4 py-1.5 text-sm text-brand-400">
              <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
              40 years late — but finally here
            </div>

            {/* H1 */}
            <h1 className="mb-6 text-4xl font-extrabold leading-[1.1] tracking-tight text-white sm:text-5xl md:text-6xl">
              Hedge funds have had
              <br />
              <span className="text-brand-400">AI traders</span> for decades.
              <br />
              Now you do too.
            </h1>

            {/* Subheading */}
            <p className="mx-auto mb-10 max-w-[480px] text-base leading-relaxed text-dark-400 sm:text-lg">
              Unitrader is your personal AI trader. It analyses markets, executes
              trades through your own exchange account, and works 24/7 —
              the same technology that&apos;s made institutions billions,
              now available to anyone.
            </p>

            {/* CTA */}
            <Link
              href="/onboarding"
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-500 px-8 py-4 text-base font-semibold text-black transition hover:bg-brand-400 active:scale-[0.98] sm:w-auto"
            >
              See what Unitrader would have done with your money
              <ArrowRight size={18} />
            </Link>

            {/* Trust pills */}
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              {[
                "Your money stays in your account",
                "No trading experience needed",
                "Paper trading first — no risk",
              ].map((t) => (
                <span
                  key={t}
                  className="inline-flex items-center gap-1.5 rounded-full border border-dark-800 px-3 py-1 text-xs text-dark-400"
                >
                  <Check size={12} className="text-brand-400" />
                  {t}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* ── INEQUALITY COMPARISON ───────────────────────────────── */}
        <section id="results" className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-4xl rounded-2xl border border-dark-800 p-6 sm:p-10 bg-[#0d1117]">
            <div className="grid gap-8 md:grid-cols-[1fr,auto,1fr]">
              {/* Hedge funds column */}
              <div>
                <div className="mb-5 inline-block rounded-full bg-red-500/10 px-3 py-1 text-xs font-semibold text-red-400 border border-red-500/15">
                  Hedge funds — since 1982
                </div>
                <ul className="space-y-3">
                  {HEDGE_FUND_POINTS.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-sm leading-relaxed text-dark-400">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-red-400" />
                      {p}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Centre divider */}
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

              {/* Unitrader column */}
              <div>
                <div className="mb-5 inline-block rounded-full bg-brand-500/10 px-3 py-1 text-xs font-semibold text-brand-400 border border-brand-500/15">
                  You — with Unitrader
                </div>
                <ul className="space-y-3">
                  {APEX_POINTS.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-sm leading-relaxed text-dark-300">
                      <Check size={14} className="mt-0.5 shrink-0 text-brand-400" />
                      {p}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* ── THREE STATS ─────────────────────────────────────────── */}
        <section className="px-4 py-16 sm:px-6">
          <div className="mx-auto grid max-w-4xl gap-6 sm:grid-cols-3">
            {STATS_DATA.map((s) => (
              <div
                key={s.value}
                className="rounded-2xl border border-dark-800 p-6 text-center bg-[#0d1117]"
              >
                <div className="mb-2 text-4xl font-extrabold text-brand-400 tabular-nums">{s.value}</div>
                <p className="text-sm leading-relaxed text-dark-400">{s.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── HOW IT WORKS ────────────────────────────────────────── */}
        <section id="how-it-works" className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-3xl">
            <div className="mb-14 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
                How it works
              </p>
              <h2 className="text-3xl font-bold text-white sm:text-4xl">
                Three steps. No complexity.
              </h2>
            </div>

            <div className="space-y-12">
              {STEPS.map((step) => (
                <div key={step.num} className="flex gap-6">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-brand-500/30 bg-brand-500/10 font-mono text-sm font-bold text-brand-400">
                    {step.num}
                  </div>
                  <div>
                    <h3 className="mb-2 text-lg font-semibold text-white">{step.title}</h3>
                    <p className="max-w-md text-sm leading-relaxed text-dark-400">{step.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── TRUST STRIP ─────────────────────────────────────────── */}
        <section className="border-y border-dark-800/50 px-4 py-6 sm:px-6 bg-[#0d1117]">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-center gap-x-8 gap-y-3">
            {TRUST_SIGNALS.map((s) => (
              <span key={s} className="inline-flex items-center gap-1.5 text-xs text-dark-400 sm:text-sm">
                <Check size={14} className="text-brand-400" />
                {s}
              </span>
            ))}
          </div>
        </section>

        {/* ── PRICING ────────────────────────────────────────────── */}
        <section id="pricing" className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-4xl">
            <div className="mb-12 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
                Pricing
              </p>
              <h2 className="mb-4 text-3xl font-bold text-white sm:text-4xl">
                Simple, transparent pricing
              </h2>
              <p className="text-dark-400">
                14-day free trial. No credit card required. You keep 100% of your profits.
              </p>
            </div>

            <div className="mx-auto grid max-w-3xl gap-6 sm:grid-cols-2">
              {/* Free plan */}
              <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-8">
                <div className="mb-6">
                  <p className="text-sm font-semibold uppercase tracking-widest text-dark-500">Free</p>
                  <div className="mt-2 flex items-end gap-1">
                    <span className="text-4xl font-bold text-white">$0</span>
                    <span className="mb-1 text-sm text-dark-500">/ month</span>
                  </div>
                  <p className="mt-2 text-sm text-dark-400">Get started, no commitment</p>
                </div>
                <ul className="mb-8 space-y-3 text-sm text-dark-300">
                  {["1 exchange connection", "10 AI trades per month", "Paper trading", "Basic chat support", "Performance dashboard"].map((f) => (
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
              <div className="relative rounded-2xl border border-brand-500/40 bg-brand-500/[0.04] p-8">
                <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                  <span className="rounded-full border border-brand-500/40 bg-brand-500/20 px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-brand-300">
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
                <ul className="mb-8 space-y-3 text-sm text-dark-200">
                  {[
                    "Unlimited exchange connections",
                    "Unlimited AI trades",
                    "Priority Claude AI",
                    "Advanced analytics",
                    "Email trade alerts",
                    "Telegram & WhatsApp alerts",
                    "Premium support",
                  ].map((f) => (
                    <li key={f} className="flex items-center gap-2.5">
                      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-[10px] text-brand-400">✓</span>
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/register"
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-500 py-3 text-sm font-semibold text-black transition hover:bg-brand-400 active:scale-[0.98]"
                >
                  Start free trial
                  <ArrowRight size={15} />
                </Link>
                <p className="mt-3 text-center text-[11px] text-dark-500">
                  No credit card required · Cancel anytime
                </p>
                <div className="relative flex items-center gap-2 py-1">
                  <div className="flex-1 border-t border-dark-800" />
                  <span className="text-[11px] text-dark-700">or</span>
                  <div className="flex-1 border-t border-dark-800" />
                </div>
                <Link
                  href="/register?checkout=1"
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-brand-500/30 py-3 text-sm font-medium text-brand-300 transition hover:border-brand-400 hover:text-brand-200"
                >
                  Go Pro now — $9.99/mo
                </Link>
                <p className="mt-2 text-center text-[11px] text-dark-600">
                  Skip the trial · Billed monthly · Cancel anytime
                </p>
              </div>
            </div>

            <p className="mt-8 text-center text-sm text-dark-500">
              Already have an account?{" "}
              <Link href="/login" className="text-brand-400 hover:underline">Sign in</Link>
            </p>
          </div>
        </section>
      </main>

      {/* ── FOOTER ────────────────────────────────────────────────── */}
      <Footer />
    </div>
  );
}
