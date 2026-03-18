import Head from "next/head";
import Link from "next/link";
import { useState, useEffect, useRef } from "react";
import {
  TrendingUp, Shield, Brain, Zap, BarChart3, Bell,
  Check, ChevronRight, ArrowRight, Star, Menu, X,
} from "lucide-react";

// ─────────────────────────────────────────────
// Data
// ─────────────────────────────────────────────

const NAV_LINKS = ["Features", "How It Works", "Pricing", "FAQ"];

const STATS = [
  { label: "Trades Analysed", value: 284_193, suffix: "+" },
  { label: "Average Win Rate", value: 73, suffix: "%" },
  { label: "Active Users", value: 1_240, suffix: "+" },
  { label: "Avg Monthly Return", value: 11.4, suffix: "%" },
];

const FEATURES = [
  {
    icon: Brain,
    title: "Claude AI Decisions",
    desc: "Powered by Anthropic's Claude Opus. Analyses 100+ technical indicators in seconds to make data-driven trade decisions — without emotion.",
  },
  {
    icon: Shield,
    title: "Hard Risk Guardrails",
    desc: "Max 2% per trade. Mandatory stop-loss. Daily loss limits. Circuit breakers. Your capital is protected even when Claude wants to trade.",
  },
  {
    icon: TrendingUp,
    title: "Multi-Exchange Support",
    desc: "Trade Binance, Alpaca, and OANDA from one place. Your AI works across crypto, stocks, and forex simultaneously.",
  },
  {
    icon: Zap,
    title: "Executes in Milliseconds",
    desc: "No hesitation, no slippage from second-guessing. Orders, stop-losses, and take-profits placed simultaneously the moment conditions align.",
  },
  {
    icon: BarChart3,
    title: "Live Performance Tracking",
    desc: "Win rate, P&L, drawdown, and confidence scores updated in real-time. Know exactly how your AI is performing at every moment.",
  },
  {
    icon: Bell,
    title: "Instant Notifications",
    desc: "Email and in-app alerts when trades open, close, hit targets, or when daily loss limits are approaching.",
  },
];

const HOW_IT_WORKS = [
  {
    step: "01",
    title: "Connect Your Exchange",
    desc: "Link Binance, Alpaca, or OANDA with encrypted API keys. Your credentials never leave your server.",
  },
  {
    step: "02",
    title: "Your AI Analyses the Market",
    desc: "Every 5 minutes, Claude reviews RSI, MACD, moving averages, support/resistance, and market sentiment.",
  },
  {
    step: "03",
    title: "Trades Execute Automatically",
    desc: "When confidence exceeds your threshold, orders are placed with stops and targets. You get notified instantly.",
  },
];

const TESTIMONIALS = [
  {
    name: "Marcus T.",
    role: "Crypto Trader",
    avatar: "MT",
    text: "I named my AI 'Apex'. It turned $10k into $13.2k in my first month. The discipline it has is something I could never maintain manually.",
    stars: 5,
  },
  {
    name: "Sarah K.",
    role: "Equity Investor",
    avatar: "SK",
    text: "The stop-loss enforcement alone saved me from a $4,000 loss last October. I would have held hoping for a recovery. The AI just closed it at -2%.",
    stars: 5,
  },
  {
    name: "James R.",
    role: "Forex Trader",
    avatar: "JR",
    text: "What I love most is the transparency. Every trade shows Claude's reasoning and confidence score. I've learned more about technical analysis just by watching it.",
    stars: 5,
  },
];

const FAQ_ITEMS = [
  {
    q: "Is my money safe?",
    a: "Unitrader never holds your funds. It connects to your exchange via API keys with trading permissions only — withdrawals are always disabled. Your money stays in your exchange account.",
  },
  {
    q: "Do I need trading experience?",
    a: "No. The AI handles all analysis and execution. The dashboard is designed so beginners can understand what's happening, and advanced traders can dive deep into the data.",
  },
  {
    q: "What exchanges are supported?",
    a: "Currently Binance (crypto), Alpaca (US stocks, paper trading supported), and OANDA (forex). More exchanges are added regularly.",
  },
  {
    q: "Can I lose money?",
    a: "Yes. All trading carries risk. Unitrader enforces strict risk management (max 2% per trade, daily loss limits) but cannot guarantee profits. Past performance does not guarantee future results.",
  },
  {
    q: "Can I control what the AI trades?",
    a: "Yes, completely. You set approved assets, trading hours, max position sizes, and can pause or stop the AI at any time from your dashboard.",
  },
  {
    q: "How is the 14-day trial different from free?",
    a: "The 14-day trial gives you full Pro access with unlimited trades. The free tier continues after the trial with 10 trades per month.",
  },
];

// ─────────────────────────────────────────────
// Animated counter hook
// ─────────────────────────────────────────────

function useCounter(target: number, duration = 2000) {
  const [count, setCount] = useState(0);
  const ref = useRef(false);

  useEffect(() => {
    if (ref.current) return;
    ref.current = true;
    const start = Date.now();
    const timer = setInterval(() => {
      const elapsed = Date.now() - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.floor(eased * target));
      if (progress >= 1) clearInterval(timer);
    }, 16);
    return () => clearInterval(timer);
  }, [target, duration]);

  return count;
}

// ─────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────

function StatCard({ label, value, suffix }: { label: string; value: number; suffix: string }) {
  const count = useCounter(value);
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="font-mono text-3xl font-bold text-brand-400 md:text-4xl">
        {count.toLocaleString()}{suffix}
      </span>
      <span className="text-sm text-gray-500">{label}</span>
    </div>
  );
}

function FeatureCard({ icon: Icon, title, desc }: { icon: any; title: string; desc: string }) {
  return (
    <div className="group rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition-all hover:border-brand-500/40 hover:bg-gray-50">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-500 transition-colors group-hover:bg-brand-500/20">
        <Icon size={20} />
      </div>
      <h3 className="mb-2 font-semibold text-gray-900">{title}</h3>
      <p className="text-sm leading-relaxed text-gray-500">{desc}</p>
    </div>
  );
}

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="cursor-pointer rounded-xl border border-gray-200 bg-white p-5 transition-all hover:border-gray-300"
      onClick={() => setOpen(!open)}
    >
      <div className="flex items-center justify-between gap-4">
        <span className="font-medium text-gray-900">{q}</span>
        <ChevronRight
          size={18}
          className={`shrink-0 text-gray-400 transition-transform ${open ? "rotate-90" : ""}`}
        />
      </div>
      {open && <p className="mt-3 text-sm leading-relaxed text-gray-500">{a}</p>}
    </div>
  );
}

// ─────────────────────────────────────────────
// Ticker bar
// ─────────────────────────────────────────────

const TICKER_ITEMS = [
  "BTC/USD +2.4% ↑", "ETH/USD +1.8% ↑", "AAPL +0.9% ↑",
  "TSLA -1.2% ↓", "EUR/USD +0.3% ↑", "SOL/USD +5.1% ↑",
  "NVDA +3.7% ↑", "GBP/USD -0.1% ↓", "BNB/USD +1.4% ↑",
];

function TickerBar() {
  const items = [...TICKER_ITEMS, ...TICKER_ITEMS];
  return (
    <div className="overflow-hidden border-b border-gray-200 bg-gray-50 py-2">
      <div className="flex animate-ticker gap-8 whitespace-nowrap">
        {items.map((item, i) => (
          <span
            key={i}
            className={`font-mono text-xs ${item.includes("↑") ? "text-brand-400" : "text-red-400"}`}
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────

export default function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div className="bg-white min-h-screen">
      <Head>
        <title>Unitrader — Your Personal AI Trading Companion</title>
        <meta
          name="description"
          content="Unitrader uses Claude AI to analyse markets, execute trades, and enforce risk management 24/7. Start your 14-day free trial."
        />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      {/* ── Navbar ──────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-gray-200 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500">
              <TrendingUp size={16} className="text-white" />
            </div>
            <span className="text-lg font-bold text-gray-900">Unitrader</span>
          </div>

          {/* Desktop nav */}
          <nav className="hidden items-center gap-6 md:flex">
            {NAV_LINKS.map((link) => (
              <a
                key={link}
                href={`#${link.toLowerCase().replace(/\s/g, "-")}`}
                className="text-sm text-gray-500 transition hover:text-gray-900"
              >
                {link}
              </a>
            ))}
          </nav>

          <div className="hidden items-center gap-3 md:flex">
            <Link href="/login" className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-300 px-5 py-2 text-xs font-semibold text-gray-700 transition-all hover:border-brand-500 hover:text-brand-500 active:scale-95">
              Log In
            </Link>
            <Link href="/register" className="btn-primary py-2 text-xs">
              Start Free Trial
            </Link>
          </div>

          {/* Mobile menu toggle */}
          <button
            className="md:hidden text-gray-500"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          >
            {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>

        {mobileMenuOpen && (
          <div className="border-t border-gray-200 bg-white px-4 pb-4 md:hidden">
            {NAV_LINKS.map((link) => (
              <a
                key={link}
                href={`#${link.toLowerCase().replace(/\s/g, "-")}`}
                className="block py-2.5 text-sm text-gray-500"
                onClick={() => setMobileMenuOpen(false)}
              >
                {link}
              </a>
            ))}
            <div className="mt-3 flex flex-col gap-2">
              <Link href="/login" className="inline-flex items-center justify-center rounded-lg border border-gray-300 px-5 py-2.5 text-xs font-semibold text-gray-700 transition-all hover:border-brand-500 hover:text-brand-500 text-center">Log In</Link>
              <Link href="/register" className="btn-primary text-center text-xs">Start Free Trial</Link>
            </div>
          </div>
        )}
      </header>

      {/* ── Ticker ──────────────────────────────────────────────────── */}
      <TickerBar />

      <main>
        {/* ── Hero ────────────────────────────────────────────────────── */}
        <section className="relative overflow-hidden px-4 py-24 sm:px-6 sm:py-32">
          {/* Glow blobs */}
          <div className="pointer-events-none absolute -left-40 -top-40 h-96 w-96 rounded-full bg-brand-500/10 blur-3xl" />
          <div className="pointer-events-none absolute -right-40 top-20 h-96 w-96 rounded-full bg-brand-500/10 blur-3xl" />

          <div className="relative mx-auto max-w-4xl text-center">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-brand-500/30 bg-brand-500/10 px-4 py-1.5 text-sm text-brand-400">
              <span className="h-1.5 w-1.5 animate-pulse-slow rounded-full bg-brand-400" />
              AI-powered trading — now in your hands
            </div>

            <h1 className="mb-6 text-4xl font-extrabold leading-tight tracking-tight text-gray-900 sm:text-6xl md:text-7xl">
              Your Personal{" "}
              <span className="bg-gradient-to-r from-brand-400 to-brand-300 bg-clip-text text-transparent">
                AI Trading
              </span>{" "}
              Companion
            </h1>

            <p className="mx-auto mb-10 max-w-2xl text-lg leading-relaxed text-gray-500 sm:text-xl">
              Name your AI. Watch it analyse markets, execute trades, and enforce
              risk management — 24 hours a day, without emotion.
            </p>

            <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
              <Link href="/register" className="btn-primary px-8 py-3.5 text-base shadow-lg shadow-brand-500/20">
                Start Free Trial — 14 Days Free
                <ArrowRight size={18} />
              </Link>
              <Link href="#how-it-works" className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-300 px-8 py-3.5 text-base font-semibold text-gray-700 transition-all hover:border-brand-500 hover:text-brand-500 active:scale-95">
                See How It Works
              </Link>
            </div>

            <p className="mt-4 text-xs text-gray-400">
              No credit card required for free tier · Cancel anytime
            </p>
          </div>
        </section>

        {/* ── Stats ───────────────────────────────────────────────────── */}
        <section className="border-y border-gray-200 bg-gray-50 px-4 py-12 sm:px-6">
          <div className="mx-auto grid max-w-4xl grid-cols-2 gap-8 md:grid-cols-4">
            {STATS.map((s) => (
              <StatCard key={s.label} {...s} />
            ))}
          </div>
        </section>

        {/* ── Features ────────────────────────────────────────────────── */}
        <section id="features" className="px-4 py-24 sm:px-6">
          <div className="mx-auto max-w-7xl">
            <div className="mb-14 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
                Features
              </p>
              <h2 className="text-3xl font-bold text-gray-900 sm:text-4xl">
                Everything your trading needs
              </h2>
            </div>
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((f) => (
                <FeatureCard key={f.title} {...f} />
              ))}
            </div>
          </div>
        </section>

        {/* ── How It Works ────────────────────────────────────────────── */}
        <section id="how-it-works" className="bg-gray-50 px-4 py-24 sm:px-6">
          <div className="mx-auto max-w-5xl">
            <div className="mb-14 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
                How It Works
              </p>
              <h2 className="text-3xl font-bold text-gray-900 sm:text-4xl">
                Up and running in 10 minutes
              </h2>
            </div>
            <div className="relative grid gap-8 md:grid-cols-3">
              {/* Connector line */}
              <div className="absolute left-0 right-0 top-8 hidden h-px bg-gradient-to-r from-transparent via-brand-500/30 to-transparent md:block" />
              {HOW_IT_WORKS.map((step) => (
                <div key={step.step} className="relative flex flex-col items-center text-center">
                  <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full border border-brand-500/30 bg-brand-500/10 font-mono text-xl font-bold text-brand-400">
                    {step.step}
                  </div>
                  <h3 className="mb-2 font-semibold text-gray-900">{step.title}</h3>
                  <p className="text-sm leading-relaxed text-gray-500">{step.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Testimonials ────────────────────────────────────────────── */}
        <section className="px-4 py-24 sm:px-6">
          <div className="mx-auto max-w-7xl">
            <div className="mb-14 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
                Testimonials
              </p>
              <h2 className="text-3xl font-bold text-gray-900 sm:text-4xl">
                Traders love their AI
              </h2>
            </div>
            <div className="grid gap-6 md:grid-cols-3">
              {TESTIMONIALS.map((t) => (
                <div key={t.name} className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
                  <div className="mb-3 flex gap-0.5">
                    {Array.from({ length: t.stars }).map((_, i) => (
                      <Star key={i} size={14} className="fill-brand-400 text-brand-400" />
                    ))}
                  </div>
                  <p className="mb-4 text-sm leading-relaxed text-gray-600">"{t.text}"</p>
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-500/20 text-xs font-bold text-brand-500">
                      {t.avatar}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-gray-900">{t.name}</p>
                      <p className="text-xs text-gray-400">{t.role}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Pricing ─────────────────────────────────────────────────── */}
        <section id="pricing" className="bg-gray-50 px-4 py-24 sm:px-6">
          <div className="mx-auto max-w-4xl">
            <div className="mb-14 text-center">
              <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-brand-400">
                Pricing
              </p>
              <h2 className="text-3xl font-bold text-gray-900 sm:text-4xl">
                Simple, transparent pricing
              </h2>
              <p className="mt-3 text-gray-500">14-day free trial. Cancel anytime.</p>
            </div>

            <div className="grid gap-6 md:grid-cols-2">
              {/* Free */}
              <div className="rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
                <h3 className="mb-1 text-lg font-bold text-gray-900">Free</h3>
                <p className="mb-6 text-sm text-gray-500">Perfect for getting started</p>
                <div className="mb-6 flex items-end gap-1">
                  <span className="text-4xl font-extrabold text-gray-900">$0</span>
                  <span className="mb-1 text-gray-500">/month</span>
                </div>
                <ul className="mb-8 space-y-3">
                  {["1 exchange connection", "10 AI trades / month", "Basic chat support", "Performance dashboard"].map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm text-gray-600">
                      <Check size={16} className="text-brand-500" />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link href="/register" className="inline-flex w-full items-center justify-center rounded-lg border border-gray-300 px-5 py-2.5 text-sm font-semibold text-gray-700 transition-all hover:border-brand-500 hover:text-brand-500 active:scale-95 text-center">
                  Get Started Free
                </Link>
              </div>

              {/* Pro */}
              <div className="relative rounded-xl border border-brand-500/50 bg-white p-8 glow-green shadow-sm">
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-brand-500 px-3 py-0.5 text-xs font-bold text-white">
                  MOST POPULAR
                </div>
                <h3 className="mb-1 text-lg font-bold text-gray-900">Pro</h3>
                <p className="mb-6 text-sm text-gray-500">For serious traders</p>
                <div className="mb-6 flex items-end gap-1">
                  <span className="text-4xl font-extrabold text-gray-900">$9.99</span>
                  <span className="mb-1 text-gray-500">/month</span>
                </div>
                <ul className="mb-8 space-y-3">
                  {["Unlimited exchange connections", "Unlimited AI trades", "Priority Claude AI (Opus)", "Advanced analytics", "Email alerts", "API access", "Premium support"].map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm text-gray-600">
                      <Check size={16} className="text-brand-500" />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link href="/register?plan=pro" className="btn-primary w-full text-center shadow-lg shadow-brand-500/20">
                  Start 14-Day Free Trial — $9.99/mo
                  <ArrowRight size={16} />
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* ── FAQ ─────────────────────────────────────────────────────── */}
        <section id="faq" className="px-4 py-24 sm:px-6">
          <div className="mx-auto max-w-2xl">
            <div className="mb-12 text-center">
              <h2 className="text-3xl font-bold text-gray-900">Frequently asked questions</h2>
            </div>
            <div className="space-y-3">
              {FAQ_ITEMS.map((item) => (
                <FaqItem key={item.q} {...item} />
              ))}
            </div>
          </div>
        </section>

        {/* ── CTA ─────────────────────────────────────────────────────── */}
        <section className="px-4 py-24 sm:px-6">
          <div className="mx-auto max-w-3xl rounded-2xl border border-brand-500/20 bg-gradient-to-br from-brand-500/10 to-brand-50 p-12 text-center">
            <h2 className="mb-4 text-3xl font-bold text-gray-900 sm:text-4xl">
              Ready to meet your AI trader?
            </h2>
            <p className="mb-8 text-gray-500">
              Name it, configure it, and watch it go to work. 14 days free, no card required.
            </p>
            <Link href="/register" className="btn-primary px-10 py-4 text-base shadow-xl shadow-brand-500/20">
              Create Your AI Now — It's Free
              <ArrowRight size={20} />
            </Link>
          </div>
        </section>
      </main>

      {/* ── Footer ──────────────────────────────────────────────────── */}
      <footer className="border-t border-gray-200 bg-gray-50 px-4 py-10 sm:px-6">
        <div className="mx-auto max-w-7xl">
          <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-500">
                <TrendingUp size={14} className="text-white" />
              </div>
              <span className="font-bold text-gray-900">Unitrader</span>
            </div>
            <p className="text-xs text-gray-400">
              © {new Date().getFullYear()} Unitrader. Trading involves risk. Past performance is not indicative of future results.
            </p>
            <div className="flex gap-4 text-xs text-gray-400">
              <a href="#" className="hover:text-gray-600">Privacy</a>
              <a href="#" className="hover:text-gray-600">Terms</a>
              <a href="#" className="hover:text-gray-600">Support</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
