import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";

export interface StreakData {
  current_wins: number;
  current_losses: number;
  longest_wins: number;
}

export interface PulseData {
  pnl_7d: number;
  pnl_30d: number;
  win_rate_7d: number;
  trades_today: number;
  total_trades: number;
  ai_accuracy_pct: number;
}

export interface EngagementStats {
  ai_name: string;
  streak: StreakData;
  pulse: PulseData;
}

const POLL_MS = 60_000; // 60s — matches backend cache TTL

export function useEngagementStats() {
  const [data, setData] = useState<EngagementStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await api.get("/api/performance/engagement-stats");
      const d = res.data?.data ?? res.data;
      if (d?.streak) setData(d as EngagementStats);
    } catch {
      // silent — non-critical engagement data
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { data, isLoading, refresh };
}
