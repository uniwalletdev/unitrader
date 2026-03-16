/*
 * components/onboarding/ApexOnboardingChat.tsx — Full-screen trader-class-aware onboarding.
 *
 * The Conversation Agent (Phase 9) now returns metadata.detected_class in each response.
 * This component tracks class detection and adapts the conversation flow:
 *
 * - complete_novice (default): 5 full stages with detailed explanations
 * - curious_saver: 5 stages, saver-focused language
 * - self_taught: 3 compressed stages, skip basics
 * - experienced: 2 stages + optional skip-to-pro mode
 * - crypto_native: 3 stages, no stock questions, crypto-only exchanges
 * - semi_institutional: 1-2 stages + API routing option
 *
 * Routing on completion:
 *   novice/curious: /risk-disclosure -> /trade?welcome=true
 *   self_taught: /risk-disclosure -> /trade
 *   experienced: /risk-disclosure -> /trade
 *   crypto: /risk-disclosure -> /trade?welcome=true
 *   semi_institutional: /risk-disclosure -> /trade (or API setup)
 */

import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/router";
import Link from "next/link";
import { api } from "@/lib/api";

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

interface OnboardingMeta {
  stage?: number;
  detected_class?: string;
  goal?: string;
  risk?: string;
  budget?: string;
  exchange?: string;
}

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "crypto_native"
  | "semi_institutional";

// ─────────────────────────────────────────────────────────────────────────────
// Quick Reply Options by Trader Class
// ─────────────────────────────────────────────────────────────────────────────

const QUICK_REPLIES: Record<TraderClass, Record<string, QuickReply[]>> = {
  complete_novice: {
    goal: [
      { label: "My savings aren't growing", value: "grow_savings" },
      { label: "I want extra income", value: "generate_income" },
      { label: "I want to learn", value: "learn_trading" },
      { label: "Curious about crypto", value: "crypto_focus" },
    ],
    risk: [
      { label: "Very stressed - keep it safe", value: "conservative" },
      { label: "A bit nervous but I'd trust you", value: "balanced" },
      { label: "Fine, markets go up and down", value: "moderate" },
      { label: "I want bigger swings", value: "aggressive" },
    ],
    budget: [
      { label: "£25 - just testing", value: "25" },
      { label: "£100 - comfortable", value: "100" },
      { label: "£250 - ready", value: "250" },
      { label: "£500 or more", value: "500" },
    ],
    exchange: [
      { label: "Stocks - Apple, Tesla etc", value: "alpaca" },
      { label: "Crypto - Bitcoin etc", value: "binance" },
      { label: "Mix of everything", value: "mixed" },
    ],
  },
  curious_saver: {
    goal: [
      { label: "Grow beyond my ISA returns", value: "grow_savings" },
      { label: "Complement my index funds", value: "learn_trading" },
      { label: "Learn active trading", value: "learn_trading" },
      { label: "Try crypto", value: "crypto_focus" },
    ],
    risk: [
      { label: "Careful - I've seen losses", value: "conservative" },
      { label: "Moderate - I understand volatility", value: "balanced" },
      { label: "I'm comfortable with risk", value: "moderate" },
    ],
    budget: [
      { label: "£50 - topping up", value: "50" },
      { label: "£100", value: "100" },
      { label: "£250", value: "250" },
      { label: "£500 or more", value: "500" },
    ],
    exchange: [
      { label: "Stocks - Apple, Tesla etc", value: "alpaca" },
      { label: "Crypto - Bitcoin etc", value: "binance" },
      { label: "Mix of everything", value: "mixed" },
    ],
  },
  self_taught: {
    goal: [
      { label: "Improve my current strategy", value: "improve_strategy" },
      { label: "Automate my trading", value: "automate" },
      { label: "Get AI signal confirmation", value: "ai_confirmation" },
      { label: "Save time on analysis", value: "save_time" },
    ],
    risk: [
      { label: "Moderate", value: "balanced" },
      { label: "Aggressive", value: "aggressive" },
      { label: "Let me set precise parameters", value: "custom" },
    ],
    exchange: [
      { label: "Stocks (Alpaca)", value: "alpaca" },
      { label: "Crypto (Binance)", value: "binance" },
      { label: "Both", value: "mixed" },
    ],
  },
  experienced: {
    goal: [
      { label: "Enhance algorithmic execution", value: "enhance_algo" },
      { label: "Portfolio optimization", value: "portfolio_opt" },
      { label: "Risk-adjusted returns", value: "risk_adjusted" },
    ],
    risk: [
      { label: "Volatility-based sizing", value: "volatility_based" },
      { label: "Fixed allocation", value: "fixed" },
    ],
  },
  crypto_native: {
    goal: [
      { label: "Maximize yield farming", value: "yield" },
      { label: "Diversify across chains", value: "diversify" },
      { label: "Automate DeFi strategies", value: "defi_strat" },
      { label: "Catch Alt Season", value: "alt_season" },
    ],
    risk: [
      { label: "I can handle volatility", value: "aggressive" },
      { label: "Balanced approach", value: "balanced" },
      { label: "Conservative - stable coins only", value: "conservative" },
    ],
    budget: [
      { label: "0.1 BTC equivalent (USDT)", value: "1000" },
      { label: "1 BTC equivalent", value: "10000" },
      { label: "5 BTC+", value: "50000" },
    ],
    exchange: [
      { label: "Coinbase Advanced Trade", value: "coinbase" },
      { label: "Binance", value: "binance" },
      { label: "I use a DEX mostly", value: "dex" },
    ],
  },
  semi_institutional: {
    goal: [
      { label: "Institutional-grade automation", value: "institutional" },
      { label: "Risk-weighted portfolio", value: "risk_weighted" },
      { label: "Multi-asset execution", value: "multi_asset" },
    ],
    risk: [
      { label: "Systematic (model-based)", value: "systematic" },
      { label: "Discretionary with guardrails", value: "discretionary" },
    ],
  },
};

const STAGE_QUESTIONS: Record<TraderClass, string[]> = {
  complete_novice: [
    "What's your main goal?",
    "How comfortable are you with market risk?",
    "What's your starting budget?",
    "What would you like to trade?",
    "Great — let's get your exchange connected.",
  ],
  curious_saver: [
    "What's your main goal?",
    "How comfortable are you with market risk?",
    "What's your starting budget?",
    "What would you like to trade?",
    "Let's connect your exchange.",
  ],
  self_taught: [
    "What can Apex help you with?",
    "What's your risk tolerance?",
    "Which markets do you trade?",
  ],
  experienced: [
    "How can Apex optimize your strategy?",
    "What's your execution preference?",
  ],
  crypto_native: [
    "What's your crypto trading goal?",
    "How do you feel about volatility?",
    "Which exchange do you use?",
  ],
  semi_institutional: [
    "Let's set up your institutional integration.",
    "API-first or manual for now?",
  ],
};

export default function ApexOnboardingChat() {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "Hi! I'm Apex, your AI trading companion. Let's get you started. What's your main goal?",
      timestamp: new Date(),
    },
  ]);
  const [detectedClass, setDetectedClass] = useState<TraderClass>("complete_novice");
  const [currentStage, setCurrentStage] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [userResponses, setUserResponses] = useState<Record<string, string>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [showApiOption, setShowApiOption] = useState(false);

  const maxStages = STAGE_QUESTIONS[detectedClass].length;

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Get quick replies for current stage
  const getQuickReplies = (): QuickReply[] => {
    const stageMap: Record<TraderClass, string[]> = {
      complete_novice: ["goal", "risk", "budget", "exchange"],
      curious_saver: ["goal", "risk", "budget", "exchange"],
      self_taught: ["goal", "risk", "exchange"],
      experienced: ["goal", "risk"],
      crypto_native: ["goal", "risk", "exchange"],
      semi_institutional: ["api_option", "continue"],
    };

    const fields = stageMap[detectedClass];
    const field = fields[currentStage];

    if (field === "api_option") {
      return [
        { label: "Connect via API", value: "api" },
        { label: "Manual setup", value: "manual" },
      ];
    }

    return QUICK_REPLIES[detectedClass][field] || [];
  };

  // Handle user response
  const handleQuickReply = async (value: string) => {
    if (isLoading) return;

    // Special handlers
    if (detectedClass === "experienced" && currentStage === 0) {
      if (value === "skip_to_pro") {
        router.push("/risk-disclosure");
        return;
      }
    }

    if (detectedClass === "semi_institutional" && value === "api") {
      router.push("/settings/api?setup=onboarding");
      return;
    }

    // Add user message
    const userMsg: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: value,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setUserResponses((prev) => ({ ...prev, [`stage_${currentStage}`]: value }));

    // Send to backend
    setIsLoading(true);
    try {
      const response = await api.post("/api/onboarding/message", {
        message: value,
        stage: currentStage,
        trader_class: detectedClass,
      });

      // Parse detected class from response
      if (response.data.metadata?.detected_class) {
        const newClass = response.data.metadata.detected_class as TraderClass;
        if (newClass !== detectedClass) {
          setDetectedClass(newClass);
          console.log(`💡 Detected trader class: ${newClass}`);
        }
      }

      // Add assistant response
      const assistantMsg: Message = {
        id: `msg-${Date.now()}`,
        role: "assistant",
        content: response.data.message,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Move to next stage
      const nextStage = currentStage + 1;
      if (nextStage >= maxStages) {
        // Completion
        setTimeout(() => {
          try {
            if (typeof window !== "undefined") {
              window.localStorage.setItem("unitrader_onboarding_chat_completed_v1", "true");
            }
          } catch {
            // ignore
          }
          router.push("/risk-disclosure");
        }, 1500);
      } else {
        setCurrentStage(nextStage);
      }
    } catch (error) {
      console.error("Onboarding error:", error);
      const errorMsg: Message = {
        id: `msg-${Date.now()}`,
        role: "assistant",
        content: "Sorry, something went wrong. Please try again.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const quickReplies = getQuickReplies();
  const progressPercent = ((currentStage + 1) / maxStages) * 100;

  return (
    <div className="flex flex-col h-screen bg-gradient-to-b from-slate-900 to-slate-800 text-white">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700 bg-slate-800/50">
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-lg font-semibold">Welcome to Apex</h1>
          <span className="text-xs text-slate-400">
            {currentStage + 1} of {maxStages}
          </span>
        </div>
        <div className="w-full bg-slate-700 rounded-full h-1 overflow-hidden">
          <div
            className="bg-gradient-to-r from-cyan-500 to-blue-500 h-full transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        {detectedClass !== "complete_novice" && (
          <p className="text-xs text-cyan-400 mt-2">
            {detectedClass === "crypto_native" && "🚀 Crypto trading mode active"}
            {detectedClass === "experienced" && "⚡ Professional mode"}
            {detectedClass === "semi_institutional" && "🏦 Institutional setup"}
            {detectedClass === "self_taught" && "📊 Self-taught trader"}
            {detectedClass === "curious_saver" && "💰 Saver focused"}
          </p>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-xs px-4 py-3 rounded-lg ${
                msg.role === "user"
                  ? "bg-cyan-600 text-white rounded-br-none"
                  : "bg-slate-700 text-slate-100 rounded-bl-none"
              }`}
            >
              <p className="text-sm leading-relaxed">{msg.content}</p>
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-slate-700 px-4 py-3 rounded-lg rounded-bl-none">
              <div className="flex space-x-2">
                <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" />
                <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce delay-100" />
                <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce delay-200" />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick Replies */}
      <div className="px-4 pb-4 space-y-2 max-h-[40vh] overflow-y-auto">
        {currentStage === 0 && detectedClass === "experienced" && (
          <button
            onClick={() => handleQuickReply("skip_to_pro")}
            disabled={isLoading}
            className="w-full px-3 py-2 text-sm font-medium bg-gradient-to-r from-purple-600 to-pink-600 rounded-lg hover:from-purple-700 hover:to-pink-700 disabled:opacity-50 transition"
          >
            ⚡ Skip to Pro mode
          </button>
        )}

        {quickReplies.map((reply) => (
          <button
            key={reply.value}
            onClick={() => handleQuickReply(reply.value)}
            disabled={isLoading}
            className="w-full px-3 py-2 text-sm font-medium text-left bg-slate-700 hover:bg-slate-600 rounded-lg disabled:opacity-50 transition border border-slate-600 hover:border-slate-500"
          >
            {reply.label}
          </button>
        ))}
      </div>

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
