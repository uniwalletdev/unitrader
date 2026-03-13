import { useState, useEffect } from "react";
import {
  Brain, Loader2, TrendingUp, MessageSquare, BookOpen,
  RefreshCw, Zap, AlertCircle, Target, Lightbulb,
} from "lucide-react";
import { learningApi } from "@/lib/api";

interface User {
  id: string;
  email: string;
  ai_name: string;
  subscription_tier: string;
}

interface DashboardData {
  patterns_count?: number;
  active_instructions?: number;
  recent_outputs?: number;
  last_analysis?: string;
  patterns?: any[];
  instructions?: Record<string, any[]>;
  outputs?: any[];
}

interface Insight {
  type?: string;
  insight?: string;
  recommendation?: string;
  confidence?: number;
  data?: any;
}

const INSIGHT_TYPES = [
  { id: "trading", label: "Trading", icon: TrendingUp, color: "text-brand-400" },
  { id: "content", label: "Content", icon: BookOpen, color: "text-purple-400" },
  { id: "support", label: "Support", icon: MessageSquare, color: "text-sky-400" },
];

export default function LearningPanel({ user }: { user: User | null }) {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [insights, setInsights] = useState<Record<string, Insight[]>>({});
  const [activeInsight, setActiveInsight] = useState("trading");
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await learningApi.dashboard();
      setDashboard(res.data.data || res.data);
    } catch {
      setDashboard(null);
    }

    for (const t of INSIGHT_TYPES) {
      try {
        const res = await learningApi.insights(t.id);
        const data = res.data.data?.insights || res.data.data || [];
        setInsights((prev) => ({ ...prev, [t.id]: Array.isArray(data) ? data : [data] }));
      } catch {
        setInsights((prev) => ({ ...prev, [t.id]: [] }));
      }
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleTrigger = async () => {
    setTriggering(true);
    setMessage(null);
    try {
      await learningApi.trigger();
      setMessage({ type: "success", text: "Analysis triggered! Results will appear shortly." });
      setTimeout(load, 3000);
    } catch (err: any) {
      const detail = err.response?.data?.detail || "Failed to trigger analysis.";
      setMessage({ type: "error", text: detail });
    } finally {
      setTriggering(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-dark-500">
        <Loader2 size={16} className="mr-2 animate-spin" /> Loading learning data...
      </div>
    );
  }

  const currentInsights = insights[activeInsight] || [];

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 md:gap-4">
        <div className="flex items-center gap-2">
          <Brain size={16} className="md:size-[18px] text-brand-400" />
          <h1 className="text-base md:text-xl font-bold text-white">Learning Hub</h1>
        </div>
        <div className="flex flex-col md:flex-row gap-2">
          <button onClick={load} className="btn-outline gap-2 py-2 text-xs touch-target w-full md:w-auto">
            <RefreshCw size={13} /> Refresh
          </button>
          <button
            onClick={handleTrigger}
            disabled={triggering}
            className="btn-primary gap-2 py-2 text-xs disabled:opacity-50 touch-target w-full md:w-auto"
            title=""
          >
            {triggering ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
            Run Analysis
          </button>
        </div>
      </div>

      {message && (
        <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${
          message.type === "success" ? "bg-brand-500/10 text-brand-400" : "bg-red-500/10 text-red-400"
        }`}>
          {message.text}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-2 md:gap-4 lg:grid-cols-4">
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-4">
          <p className="text-xs text-dark-500">Active Patterns</p>
          <p className="mt-1 text-xl md:text-2xl font-bold text-white">{dashboard?.patterns_count ?? 0}</p>
        </div>
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-4">
          <p className="text-xs text-dark-500">Agent Instructions</p>
          <p className="mt-1 text-xl md:text-2xl font-bold text-white">{dashboard?.active_instructions ?? 0}</p>
        </div>
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-4">
          <p className="text-xs text-dark-500">Recorded Outputs</p>
          <p className="mt-1 text-xl md:text-2xl font-bold text-white">{dashboard?.recent_outputs ?? 0}</p>
        </div>
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-4">
          <p className="text-xs text-dark-500">Last Analysis</p>
          <p className="mt-1 text-xs md:text-sm font-medium text-dark-300">
            {dashboard?.last_analysis ? new Date(dashboard.last_analysis).toLocaleDateString() : "Never"}
          </p>
        </div>
      </div>

      {/* Insight type tabs */}
      <div className="flex gap-1 rounded-lg bg-dark-900 p-1 flex-wrap">
        {INSIGHT_TYPES.map(({ id, label, icon: Icon, color }) => (
          <button
            key={id}
            onClick={() => setActiveInsight(id)}
            className={`flex items-center gap-1 md:gap-2 rounded-md px-2 md:px-4 py-1 md:py-2 text-xs md:text-sm font-medium transition ${
              activeInsight === id ? "bg-dark-800 text-white" : "text-dark-400 hover:text-dark-200"
            }`}
          >
            <Icon size={13} className={`md:size-[14px] ${activeInsight === id ? color : ""}`} />
            <span className="hidden md:inline">{label}</span>
          </button>
        ))}
      </div>

      {/* Insights list */}
      {currentInsights.length === 0 ? (
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-6 md:p-10 text-center">
          <Lightbulb size={24} className="md:size-[28px] mx-auto mb-3 text-dark-600" />
          <p className="text-xs md:text-sm text-dark-500">
            No {activeInsight} insights yet. The learning hub analyzes data hourly, or click "Run Analysis" to generate insights now.
          </p>
        </div>
      ) : (
        <div className="space-y-2 md:space-y-3">
          {currentInsights.map((insight, i) => (
            <div key={i} className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-4">
              {insight.insight && (
                <p className="text-xs md:text-sm leading-relaxed text-dark-200">{insight.insight}</p>
              )}
              {insight.recommendation && (
                <div className="mt-2 flex items-start gap-2 rounded-lg bg-brand-500/5 p-2 md:p-3">
                  <Target size={12} className="md:size-[13px] mt-0.5 shrink-0 text-brand-400" />
                  <p className="text-xs text-brand-300">{insight.recommendation}</p>
                </div>
              )}
              {insight.confidence !== undefined && (
                <p className="mt-2 text-xs text-dark-500">Confidence: {insight.confidence}%</p>
              )}
              {typeof insight === "string" && (
                <p className="text-xs md:text-sm leading-relaxed text-dark-200">{insight}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Active Patterns */}
      {dashboard?.patterns && dashboard.patterns.length > 0 && (
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-5">
          <h2 className="mb-3 text-xs md:text-sm font-semibold text-dark-200">Active Patterns</h2>
          <div className="space-y-2">
            {dashboard.patterns.slice(0, 10).map((p: any, i: number) => (
              <div key={i} className="flex items-center justify-between rounded-lg bg-dark-900 px-2 md:px-3 py-1.5 md:py-2 text-xs">
                <span className="text-dark-300 truncate">{p.pattern_data || p.description || JSON.stringify(p).slice(0, 100)}</span>
                {p.confidence && <span className="text-dark-500 shrink-0 ml-2">{p.confidence}%</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
