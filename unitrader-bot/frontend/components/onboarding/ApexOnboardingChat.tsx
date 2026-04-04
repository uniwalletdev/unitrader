/*
 * components/onboarding/ApexOnboardingChat.tsx — Trader-class-aware onboarding wizard.
 *
 * On mount, loads user settings to resume partial progress automatically.
 * Stage 0 shows universal goal options so any experience level can self-identify.
 * Class is detected locally from the stage-0 answer — no API round-trip per step.
 *
 * Stage counts by class:
 *   complete_novice / curious_saver : 4 (goal → risk → budget → exchange)
 *   self_taught / crypto_native     : 3 (goal → risk → exchange)
 *   experienced                     : 2 (goal → risk)
 *   semi_institutional               : 2 (goal → setup)
 *
 * Routing:
 *   complete → completeWizard() → /risk-disclosure → /trade
 *   skip     → skipOnboarding() → /trade
 */

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { authApi } from "@/lib/api";
import { devLog } from "@/lib/devLog";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface QuickReply {
  label: string;
  value: string;
}

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "crypto_native"
  | "semi_institutional";

// ─────────────────────────────────────────────────────────────────────────────
// Stage field map — field name at each stage index per class
// ─────────────────────────────────────────────────────────────────────────────

const STAGE_MAP: Record<TraderClass, string[]> = {
  complete_novice:    ["goal", "risk", "budget", "exchange"],
  curious_saver:      ["goal", "risk", "budget", "exchange"],
  self_taught:        ["goal", "risk", "exchange"],
  experienced:        ["goal", "risk"],
  crypto_native:      ["goal", "risk", "exchange"],
  semi_institutional: ["goal", "setup"],
};

// ─────────────────────────────────────────────────────────────────────────────
// Stage question text — aligned with STAGE_MAP
// ─────────────────────────────────────────────────────────────────────────────

const STAGE_QUESTIONS: Record<TraderClass, string[]> = {
  complete_novice:    ["What's your main goal?", "How comfortable are you with market risk?", "What's your starting budget?", "What would you like to trade?"],
  curious_saver:      ["What's your main goal?", "How comfortable are you with market risk?", "What's your starting budget?", "What would you like to trade?"],
  self_taught:        ["What can Unitrader help you with?", "What's your risk tolerance?", "Which markets do you trade?"],
  experienced:        ["How can Unitrader work for you?", "What's your execution preference?"],
  crypto_native:      ["What's your crypto trading goal?", "How do you feel about volatility?", "Which exchange do you use?"],
  semi_institutional: ["What's your primary objective?", "How would you like to set up?"],
};

// ─────────────────────────────────────────────────────────────────────────────
// Quick reply options
// Stage 0 uses universal options (all classes see the same first question).
// ─────────────────────────────────────────────────────────────────────────────

const UNIVERSAL_GOAL_REPLIES: QuickReply[] = [
  { label: "Grow my savings",                    value: "grow_savings" },
  { label: "Generate extra income",              value: "generate_income" },
  { label: "I'm new — I want to learn",          value: "learn_trading" },
  { label: "Automate my existing strategy",      value: "automate" },
  { label: "Trade crypto / Bitcoin",             value: "crypto_focus" },
  { label: "I'm an experienced trader",          value: "enhance_algo" },
  { label: "Institutional / fund management",    value: "institutional" },
];

const QUICK_REPLIES: Record<TraderClass, Record<string, QuickReply[]>> = {
  complete_novice: {
    goal: UNIVERSAL_GOAL_REPLIES,
    risk: [
      { label: "Very stressed — keep it safe",      value: "conservative" },
      { label: "A bit nervous but I'd trust you",   value: "balanced" },
      { label: "Fine, markets go up and down",      value: "moderate" },
      { label: "I want bigger swings",              value: "aggressive" },
    ],
    budget: [
      { label: "£25 — just testing",  value: "25" },
      { label: "£100 — comfortable",  value: "100" },
      { label: "£250 — ready",        value: "250" },
      { label: "£500 or more",        value: "500" },
    ],
    exchange: [
      { label: "Stocks — Apple, Tesla etc", value: "alpaca" },
      { label: "Crypto — Bitcoin etc",      value: "binance" },
      { label: "Mix of everything",         value: "mixed" },
    ],
  },
  curious_saver: {
    goal: UNIVERSAL_GOAL_REPLIES,
    risk: [
      { label: "Careful — I've seen losses",          value: "conservative" },
      { label: "Moderate — I understand volatility",  value: "balanced" },
      { label: "I'm comfortable with risk",           value: "moderate" },
    ],
    budget: [
      { label: "£50 — topping up", value: "50"  },
      { label: "£100",             value: "100" },
      { label: "£250",             value: "250" },
      { label: "£500 or more",     value: "500" },
    ],
    exchange: [
      { label: "Stocks — Apple, Tesla etc", value: "alpaca" },
      { label: "Crypto — Bitcoin etc",      value: "binance" },
      { label: "Mix of everything",         value: "mixed" },
    ],
  },
  self_taught: {
    goal: UNIVERSAL_GOAL_REPLIES,
    risk: [
      { label: "Moderate",                       value: "balanced" },
      { label: "Aggressive",                     value: "aggressive" },
      { label: "Let me set precise parameters",  value: "custom" },
    ],
    exchange: [
      { label: "Stocks (Alpaca)",  value: "alpaca" },
      { label: "Crypto (Binance)", value: "binance" },
      { label: "Crypto (Kraken)",  value: "kraken" },
      { label: "Both",             value: "mixed" },
    ],
  },
  experienced: {
    goal: UNIVERSAL_GOAL_REPLIES,
    risk: [
      { label: "Volatility-based sizing", value: "volatility_based" },
      { label: "Fixed allocation",        value: "fixed" },
    ],
  },
  crypto_native: {
    goal: UNIVERSAL_GOAL_REPLIES,
    risk: [
      { label: "I can handle volatility",          value: "aggressive" },
      { label: "Balanced approach",                value: "balanced" },
      { label: "Conservative — stablecoins only",  value: "conservative" },
    ],
    exchange: [
      { label: "Coinbase Advanced Trade", value: "coinbase" },
      { label: "Binance",                 value: "binance" },
      { label: "Kraken",                  value: "kraken" },
      { label: "I use a DEX mostly",      value: "dex" },
    ],
  },
  semi_institutional: {
    goal: UNIVERSAL_GOAL_REPLIES,
    setup: [
      { label: "Connect via API",       value: "api" },
      { label: "Manual setup for now",  value: "manual" },
    ],
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Local class detection from stage-0 answer
// ─────────────────────────────────────────────────────────────────────────────

function detectClassFromGoal(value: string): TraderClass {
  if (["institutional", "risk_weighted", "multi_asset"].includes(value))              return "semi_institutional";
  if (["enhance_algo", "portfolio_opt", "risk_adjusted"].includes(value))             return "experienced";
  if (["improve_strategy", "automate", "ai_confirmation", "save_time"].includes(value)) return "self_taught";
  if (["crypto_focus", "yield", "defi_strat", "alt_season", "diversify"].includes(value)) return "crypto_native";
  return "complete_novice";
}

// ─────────────────────────────────────────────────────────────────────────────
// Local response generator — instant, no API round-trip
// ─────────────────────────────────────────────────────────────────────────────

function getLocalResponse(cls: TraderClass, field: string, value: string): string {
  if (field === "goal") {
    const responses: Record<string, string> = {
      grow_savings:    "Great — growing savings steadily is exactly what I'm built for. How comfortable are you with market risk?",
      generate_income: "Income-focused trading — I'll target steady, consistent returns. How do you feel about risk?",
      learn_trading:   "I'll explain every trade as I make it so you build real market knowledge. How comfortable are you with volatility?",
      crypto_focus:    "Crypto mode — I'll focus on Bitcoin, Ethereum and top altcoins. How do you feel about market swings?",
      improve_strategy:"I'll add AI signal analysis on top of your existing approach. What's your risk tolerance?",
      automate:        "Let's automate your edge — I'll execute to your parameters. What's your risk tolerance?",
      ai_confirmation: "I'll act as your second opinion on every trade. What's your risk preference?",
      save_time:       "I'll handle the monitoring and execution — you set the rules. Risk preference?",
      enhance_algo:    "Experienced trader mode — I'll skip the basics. What's your execution preference?",
      portfolio_opt:   "Portfolio optimisation mode — I'll run correlation analysis and rebalancing. Execution preference?",
      risk_adjusted:   "Risk-adjusted focus — Sharpe ratio matters here. Execution preference?",
      yield:           "Yield maximisation — I'll scan for the best opportunities. How do you handle crypto volatility?",
      diversify:       "Cross-asset diversification — smart risk spreading. Volatility tolerance?",
      defi_strat:      "DeFi automation mode active. Volatility tolerance?",
      alt_season:      "Alt season strategy locked in — I'll watch rotation signals. Which exchange do you use?",
      institutional:   "Institutional-grade setup confirmed. How would you like to connect?",
      risk_weighted:   "Risk-weighted portfolio mode. How would you like to set up?",
      multi_asset:     "Multi-asset execution across markets. Connection preference?",
    };
    return responses[value] ?? "Got it — noted.";
  }

  if (field === "risk") {
    const nextPrompt: Partial<Record<TraderClass, string>> = {
      complete_novice:  " What's your starting budget?",
      curious_saver:    " What's your starting budget?",
      self_taught:      " Which markets do you trade?",
      crypto_native:    " Which exchange do you use?",
      experienced:      " You're all set — let's get you trading.",
    };
    const riskLabels: Record<string, string> = {
      conservative:     "Conservative approach locked in — I'll protect your capital first.",
      balanced:         "Balanced — steady growth without unnecessary exposure.",
      moderate:         "Moderate risk — I'll pursue good opportunities without over-extending.",
      aggressive:       "Aggressive mode — I'll chase high-conviction opportunities.",
      volatility_based: "Volatility-based sizing — dynamic risk management.",
      fixed:            "Fixed allocation confirmed — disciplined sizing.",
      systematic:       "Systematic model confirmed.",
      discretionary:    "Discretionary with guardrails — noted.",
      custom:           "Custom parameters — you can fine-tune everything in Settings.",
    };
    return (riskLabels[value] ?? "Risk preference noted.") + (nextPrompt[cls] ?? "");
  }

  if (field === "budget") {
    const budgetLabels: Record<string, string> = {
      "25":  "£25 noted — a sensible starting point.",
      "50":  "£50 confirmed.",
      "100": "£100 confirmed — I'll build positions carefully.",
      "250": "£250 — solid capital to work with.",
      "500": "£500 or more — excellent, I'll build a diversified portfolio.",
    };
    return (budgetLabels[value] ?? "Budget noted.") + " What would you like to trade?";
  }

  if (field === "exchange") {
    const exchangeLabels: Record<string, string> = {
      alpaca:   "Alpaca confirmed — I'll trade US stocks and ETFs on your behalf.",
      binance:  "Binance confirmed — I'll trade crypto.",
      coinbase: "Coinbase Advanced Trade confirmed.",
      kraken:   "Kraken confirmed — I'll trade crypto on your Kraken account.",
      mixed:    "Both markets — I'll diversify across stocks and crypto.",
      dex:      "DEX noted — I'll use centralised exchanges for now. DEX support coming soon.",
    };
    return (exchangeLabels[value] ?? "Exchange noted.") + " You're all set — completing your setup now.";
  }

  if (field === "setup") {
    if (value === "manual") return "Manual setup confirmed — add exchange API keys in Settings whenever you're ready.";
    return "Let's get your API connected — redirecting you now.";
  }

  return "Got it — you're all set!";
}

// ─────────────────────────────────────────────────────────────────────────────
// Class display labels
// ─────────────────────────────────────────────────────────────────────────────

const CLASS_LABEL: Record<TraderClass, string> = {
  complete_novice:    "",
  curious_saver:      "Saver-focused mode",
  self_taught:        "Self-taught trader",
  experienced:        "Professional mode",
  crypto_native:      "Crypto trading mode",
  semi_institutional: "Institutional setup",
};

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export default function BotOnboardingChat() {
  const navigate = (href: string) => {
    if (typeof window === "undefined") return;
    window.location.href = href;
  };

  const [initializing, setInitializing]   = useState(true);
  const [messages, setMessages]           = useState<Message[]>([]);
  const [detectedClass, setDetectedClass] = useState<TraderClass>("complete_novice");
  const [currentStage, setCurrentStage]   = useState(0);
  const [userResponses, setUserResponses] = useState<Record<string, string>>({});
  const [skipping, setSkipping]           = useState(false);
  const [completing, setCompleting]       = useState(false);
  const messagesEndRef                    = useRef<HTMLDivElement>(null);

  // ── Load settings on mount — resume partial progress if found ──────────────
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await authApi.getSettings();
        if (!mounted) return;
        const s = res.data;

        const savedClass = (s.trader_class || "complete_novice") as TraderClass;
        const hasGoal    = !!s.financial_goal;
        const hasRisk    = !!s.risk_level_setting;
        const isResuming = hasGoal || savedClass !== "complete_novice";

        if (isResuming) {
          const cls = savedClass;
          const saved: Record<string, string> = {};
          if (hasGoal && s.financial_goal)    saved["stage_0"] = s.financial_goal;
          if (hasRisk && s.risk_level_setting) saved["stage_1"] = s.risk_level_setting;

          const resumeStage = Math.min(
            Object.keys(saved).length,
            STAGE_QUESTIONS[cls].length - 1,
          );

          setDetectedClass(cls);
          setUserResponses(saved);
          setCurrentStage(resumeStage);
          setMessages([{
            id: "resume",
            role: "assistant",
            content: `Welcome back! Let's pick up where you left off. ${STAGE_QUESTIONS[cls][resumeStage]}`,
            timestamp: new Date(),
          }]);
          devLog(`Onboarding resume: class=${cls} stage=${resumeStage}`);
        } else {
          setMessages([{
            id: "welcome",
            role: "assistant",
            content: "Hi! I'm Unitrader, your AI trading companion. Takes about 30 seconds. What's your main goal?",
            timestamp: new Date(),
          }]);
        }
      } catch {
        // Non-fatal — start fresh if settings unavailable
        setMessages([{
          id: "welcome",
          role: "assistant",
          content: "Hi! I'm Unitrader, your AI trading companion. Takes about 30 seconds. What's your main goal?",
          timestamp: new Date(),
        }]);
      } finally {
        if (mounted) setInitializing(false);
      }
    })();
    return () => { mounted = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const maxStages      = STAGE_QUESTIONS[detectedClass].length;
  const progressPercent = Math.round(((currentStage + 1) / maxStages) * 100);

  const getQuickReplies = (): QuickReply[] => {
    const field = STAGE_MAP[detectedClass][currentStage];
    return QUICK_REPLIES[detectedClass]?.[field] ?? [];
  };

  const handleQuickReply = (value: string) => {
    if (completing || skipping) return;

    // Semi-institutional API routing
    if (detectedClass === "semi_institutional" && value === "api") {
      setCompleting(true);
      setTimeout(async () => {
        try { await authApi.completeWizard({ trader_class: "semi_institutional", goal: userResponses["stage_0"] }); } catch { /* non-fatal */ }
        navigate("/settings/api?setup=onboarding");
      }, 600);
      return;
    }

    const field           = STAGE_MAP[detectedClass][currentStage];
    const updatedResponses = { ...userResponses, [`stage_${currentStage}`]: value };
    setUserResponses(updatedResponses);

    // Show the human-readable label in the user bubble
    const label = getQuickReplies().find(r => r.value === value)?.label ?? value;
    setMessages(prev => [...prev, {
      id: `user-${Date.now()}`,
      role: "user",
      content: label,
      timestamp: new Date(),
    }]);

    // Detect class from stage-0 answer before computing next stage
    let nextClass = detectedClass;
    if (currentStage === 0) {
      nextClass = detectClassFromGoal(value);
      if (nextClass !== detectedClass) {
        setDetectedClass(nextClass);
        devLog(`Trader class detected: ${nextClass}`);
      }
    }

    const nextMaxStages = STAGE_QUESTIONS[nextClass].length;
    const nextStage     = currentStage + 1;
    const isComplete    = nextStage >= nextMaxStages;

    const responseText = getLocalResponse(nextClass, field, value);
    setMessages(prev => [...prev, {
      id: `ai-${Date.now()}`,
      role: "assistant",
      content: isComplete ? `${responseText} Setting you up now — one moment...` : responseText,
      timestamp: new Date(),
    }]);

    if (isComplete) {
      setCompleting(true);

      // Map stage responses back to named fields
      const fields  = STAGE_MAP[nextClass];
      const byField: Record<string, string> = {};
      fields.forEach((f, i) => {
        const val = i === currentStage ? value : updatedResponses[`stage_${i}`];
        if (val) byField[f] = val;
      });

      setTimeout(async () => {
        try {
          await authApi.completeWizard({
            goal:         byField.goal,
            risk_level:   byField.risk,
            budget:       byField.budget ? Number(byField.budget) : undefined,
            exchange:     byField.exchange ?? byField.setup,
            trader_class: nextClass,
          });
        } catch { /* non-fatal — proceed to risk disclosure regardless */ }
        try {
          window.localStorage.setItem("unitrader_onboarding_chat_completed_v1", "true");
        } catch { /* ignore */ }
        navigate("/risk-disclosure");
      }, 1500);
    } else {
      setCurrentStage(nextStage);
    }
  };

  const handleSkip = async () => {
    if (skipping || completing) return;
    setSkipping(true);
    try { await authApi.skipOnboarding(); } catch { /* non-fatal */ }
    navigate("/trade");
  };

  // ── Loading screen while settings load ─────────────────────────────────────
  if (initializing) {
    return (
      <div className="flex h-screen items-center justify-center bg-gradient-to-b from-slate-900 to-slate-800">
        <div className="flex space-x-2">
          <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" />
          <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "100ms" }} />
          <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "200ms" }} />
        </div>
      </div>
    );
  }

  const quickReplies = getQuickReplies();

  return (
    <div className="flex flex-col h-screen bg-gradient-to-b from-slate-900 to-slate-800 text-white">

      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700 bg-slate-800/50">
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-lg font-semibold">Unitrader Setup</h1>
          <div className="flex items-center gap-3">
            <button
              onClick={handleSkip}
              disabled={skipping || completing}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors underline underline-offset-2 disabled:opacity-40"
            >
              {skipping ? "Skipping…" : "Skip — trade now"}
            </button>
            <span className="text-xs text-slate-400">
              {currentStage + 1} of {maxStages}
            </span>
          </div>
        </div>
        <div className="w-full bg-slate-700 rounded-full h-1 overflow-hidden">
          <div
            className="bg-gradient-to-r from-cyan-500 to-blue-500 h-full transition-all duration-500"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        {CLASS_LABEL[detectedClass] && (
          <p className="text-xs text-cyan-400 mt-1.5">{CLASS_LABEL[detectedClass]}</p>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-xs sm:max-w-sm px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-cyan-600 text-white rounded-br-none"
                  : "bg-slate-700 text-slate-100 rounded-bl-none"
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {/* Typing indicator while completing */}
        {completing && (
          <div className="flex justify-start">
            <div className="bg-slate-700 px-4 py-3 rounded-2xl rounded-bl-none">
              <div className="flex space-x-1.5">
                <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" />
                <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "100ms" }} />
                <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "200ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick Replies */}
      {!completing && (
        <div className="px-4 pb-4 space-y-2 max-h-[45vh] overflow-y-auto">
          {quickReplies.map((reply) => (
            <button
              key={reply.value}
              onClick={() => handleQuickReply(reply.value)}
              className="w-full px-3 py-2.5 text-sm font-medium text-left bg-slate-700 hover:bg-slate-600 rounded-xl transition border border-slate-600 hover:border-slate-500 active:scale-[0.98]"
            >
              {reply.label}
            </button>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="px-4 py-3 text-center text-xs text-slate-500 border-t border-slate-700">
        <p>
          Already have an account?{" "}
          <Link href="/login" className="text-cyan-400 hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
