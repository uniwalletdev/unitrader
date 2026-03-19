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
  "Start with £25",
  "Open to everyone",
];

const STATS_DATA = [
  { value: "40+", desc: "Years institutions had AI trading before you could access it" },
  { value: "70%", desc: "Of all stock market volume is already algorithmic or AI-driven" },
  { value: "£25", desc: "Minimum to start. Your money never leaves your exchange account" },
];

const STEPS = [
  {
    num: "01",
    title: "Tell Apex your goal",
    desc: "A short conversation. No forms. Apex learns whether you want to grow savings, generate income, or explore crypto.",
  },
  {
    num: "02",
    title: "Watch Apex prove itself",
    desc: "Apex starts in Watch Mode — trading with paper money first. You see every decision and why. No real money at risk.",
  },
  {
    num: "03",
    title: "Let Apex trade for you",
    desc: "Once you trust Apex, it trades with real money through your own Alpaca or Coinbase account. You keep 100% of profits.",
  },
];

const TRUST_SIGNALS = [
  "Apex never holds your funds",
  "Paper trading first — watch Apex prove itself",
  "FCA risk warnings on every trade",
  "Full audit trail of every AI decision",
  "Pause Apex any time",
];

// ─────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────

export default function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div className="min-h-screen" style={{ backgroundColor: "#080a0f" }}>
      <Head>
        <title>Unitrader — Your Personal AI Trader</title>
        <meta
          name="description"
          content="Apex is your personal AI trader. The same technology that's made hedge funds billions — now available to anyone."
        />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      {/* ── Navbar ─────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-white/5 backdrop-blur-xl" style={{ backgroundColor: "rgba(8,10,15,0.85)" }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#22c55e]">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M4 12L8 4l4 8" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <span className="text-lg font-bold text-white">Unitrader</span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden items-center gap-8 md:flex">
            {[
              { label: "How it works", href: "#how-it-works" },
              { label: "Results", href: "#results" },
              { label: "Pricing", href: "#pricing" },
            ].map((l) => (
              <a key={l.label} href={l.href} className="text-sm text-gray-400 transition hover:text-white">
                {l.label}
              </a>
            ))}
          </nav>

          {/* Desktop CTA */}
          <Link
            href="/register"
            className="hidden rounded-lg bg-[#22c55e] px-5 py-2 text-sm font-semibold text-white transition hover:bg-[#1ea94e] active:scale-95 md:inline-flex"
          >
            Start free
          </Link>

          {/* Mobile toggle */}
          <button className="text-gray-400 md:hidden" onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>
            {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>

        {/* Mobile menu */}
        {mobileMenuOpen && (
          <div className="border-t border-white/5 px-4 pb-4 md:hidden" style={{ backgroundColor: "#080a0f" }}>
            {[
              { label: "How it works", href: "#how-it-works" },
              { label: "Results", href: "#results" },
              { label: "Pricing", href: "#pricing" },
            ].map((l) => (
              <a
                key={l.label}
                href={l.href}
                className="block py-2.5 text-sm text-gray-400"
                onClick={() => setMobileMenuOpen(false)}
              >
                {l.label}
              </a>
            ))}
            <Link
              href="/register"
              className="mt-3 block w-full rounded-lg bg-[#22c55e] py-2.5 text-center text-sm font-semibold text-white"
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
          <div className="pointer-events-none absolute left-1/2 top-0 h-[600px] w-[800px] -translate-x-1/2 rounded-full bg-[#22c55e]/5 blur-[120px]" />

          <div className="relative mx-auto max-w-3xl text-center">
            {/* Eyebrow pill */}
            <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-[#22c55e]/30 px-4 py-1.5 text-sm text-[#22c55e]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#22c55e]" />
              40 years late — but finally here
            </div>

            {/* H1 */}
            <h1 className="mb-6 text-4xl font-extrabold leading-[1.1] tracking-tight text-white sm:text-5xl md:text-6xl">
              Hedge funds have had
              <br />
              <span className="text-[#22c55e]">AI traders</span> for decades.
              <br />
              Now you do too.
            </h1>

            {/* Subheading */}
            <p className="mx-auto mb-10 max-w-[480px] text-base leading-relaxed text-gray-400 sm:text-lg">
              Apex is your personal AI trader. It analyses markets, executes
              trades through your own exchange account, and works 24/7 —
              the same technology that&apos;s made institutions billions,
              now available to anyone.
            </p>

            {/* CTA */}
            <Link
              href="/onboarding"
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#22c55e] px-8 py-4 text-base font-semibold text-white transition hover:bg-[#1ea94e] active:scale-[0.98] sm:w-auto"
            >
              See what Apex would have done with your money
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
                  className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1 text-xs text-gray-400"
                >
                  <Check size={12} className="text-[#22c55e]" />
                  {t}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* ── INEQUALITY COMPARISON ───────────────────────────────── */}
        <section id="results" className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-4xl rounded-2xl border border-white/5 p-6 sm:p-10" style={{ backgroundColor: "#0d1018" }}>
            <div className="grid gap-8 md:grid-cols-[1fr,auto,1fr]">
              {/* Hedge funds column */}
              <div>
                <div className="mb-5 inline-block rounded-full bg-red-500/10 px-3 py-1 text-xs font-semibold text-red-400">
                  Hedge funds — since 1982
                </div>
                <ul className="space-y-3">
                  {HEDGE_FUND_POINTS.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-sm leading-relaxed text-gray-400">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-red-400" />
                      {p}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Centre divider */}
              <div className="flex flex-col items-center justify-center gap-3">
                <div className="hidden h-full w-px bg-white/10 md:block" />
                <div className="flex items-center gap-2 text-sm font-bold text-gray-500">
                  <span>vs</span>
                  <ArrowLeftRight size={14} className="text-gray-600" />
                </div>
                <span className="rounded-full bg-[#22c55e]/10 px-2.5 py-0.5 text-xs font-semibold text-[#22c55e]">
                  now
                </span>
                <div className="hidden h-full w-px bg-white/10 md:block" />
              </div>

              {/* Apex column */}
              <div>
                <div className="mb-5 inline-block rounded-full bg-[#22c55e]/10 px-3 py-1 text-xs font-semibold text-[#22c55e]">
                  You — with Apex
                </div>
                <ul className="space-y-3">
                  {APEX_POINTS.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-sm leading-relaxed text-gray-300">
                      <Check size={14} className="mt-0.5 shrink-0 text-[#22c55e]" />
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
                className="rounded-xl border border-white/5 p-6 text-center"
                style={{ backgroundColor: "#0d1018" }}
              >
                <div className="mb-2 text-4xl font-extrabold text-[#22c55e]">{s.value}</div>
                <p className="text-sm leading-relaxed text-gray-400">{s.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── HOW IT WORKS ────────────────────────────────────────── */}
        <section id="how-it-works" className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-3xl">
            <div className="mb-14 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-[#22c55e]">
                How it works
              </p>
              <h2 className="text-3xl font-bold text-white sm:text-4xl">
                Three steps. No complexity.
              </h2>
            </div>

            <div className="space-y-12">
              {STEPS.map((step) => (
                <div key={step.num} className="flex gap-6">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-[#22c55e]/30 bg-[#22c55e]/10 font-mono text-sm font-bold text-[#22c55e]">
                    {step.num}
                  </div>
                  <div>
                    <h3 className="mb-2 text-lg font-semibold text-white">{step.title}</h3>
                    <p className="max-w-md text-sm leading-relaxed text-gray-400">{step.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── TRUST STRIP ─────────────────────────────────────────── */}
        <section className="border-y border-white/5 px-4 py-6 sm:px-6" style={{ backgroundColor: "#0d1018" }}>
          <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-center gap-x-8 gap-y-3">
            {TRUST_SIGNALS.map((s) => (
              <span key={s} className="inline-flex items-center gap-1.5 text-xs text-gray-400 sm:text-sm">
                <Check size={14} className="text-[#22c55e]" />
                {s}
              </span>
            ))}
          </div>
        </section>

        {/* ── PRICING (simple CTA, no price shown) ────────────────── */}
        <section id="pricing" className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-xl text-center">
            <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-[#22c55e]">
              Pricing
            </p>
            <h2 className="mb-4 text-3xl font-bold text-white sm:text-4xl">
              Start for free. Upgrade when you&apos;re ready.
            </h2>
            <p className="mb-8 text-gray-400">
              No credit card required. Paper trade with Apex first, then go live when you trust it.
            </p>
            <Link
              href="/register"
              className="inline-flex items-center gap-2 rounded-xl bg-[#22c55e] px-8 py-4 text-base font-semibold text-white transition hover:bg-[#1ea94e] active:scale-[0.98]"
            >
              Start free
              <ArrowRight size={18} />
            </Link>
          </div>
        </section>
      </main>

      {/* ── FOOTER ────────────────────────────────────────────────── */}
      <Footer />
    </div>
  );
}
