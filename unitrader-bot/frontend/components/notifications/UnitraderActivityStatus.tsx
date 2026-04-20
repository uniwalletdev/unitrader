"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Bell, ChevronRight, Radar, Sparkles, SunMedium, Zap } from "lucide-react";

import { notificationApi, signalApi } from "@/lib/api";
import { countdownTo, readString, relativeTime, type NotificationItem } from "@/components/notifications/notificationUtils";

type SignalMode = "watch" | "assisted" | "guided" | "autonomous";

type SignalSummary = {
  id: string;
  symbol: string;
  asset_name: string;
  confidence: number;
  signal: string;
};

type SignalStackResponse = {
  signals?: SignalSummary[];
  last_scan_at?: string | null;
  next_scan_in_minutes?: number | null;
};

function statusTone(botName: string, mode: SignalMode) {
  if (mode === "autonomous") {
    return {
      dot: "bg-emerald-400",
      badge: "bg-emerald-500/12 text-emerald-300 border-emerald-500/20",
      title: `${botName} Autopilot is active`,
      subtitle: "Scanning live markets and managing trades autonomously.",
      icon: <Zap size={14} />,
    };
  }
  if (mode === "guided") {
    return {
      dot: "bg-brand-400",
      badge: "bg-brand-500/12 text-brand-300 border-brand-500/20",
      title: `${botName} is auto-confirming at threshold`,
      subtitle: "Trades that meet your confidence threshold execute automatically.",
      icon: <Radar size={14} />,
    };
  }
  if (mode === "assisted") {
    return {
      dot: "bg-sky-400",
      badge: "bg-sky-500/12 text-sky-300 border-sky-500/20",
      title: `${botName} is curating your shortlist`,
      subtitle: "Signals are being ranked against your approval settings.",
      icon: <Radar size={14} />,
    };
  }
  return {
    dot: "bg-amber-400",
    badge: "bg-amber-500/12 text-amber-300 border-amber-500/20",
    title: `${botName} is scanning for your next idea`,
    subtitle: `Fresh signals and briefings appear here as ${botName} finds them.`,
    icon: <SunMedium size={14} />,
  };
}

function activityLabel(item: NotificationItem) {
  if (item.notification_type === "stop_loss_triggered") return "Stop-loss managed";
  if (item.notification_type === "take_profit_triggered") return "Profit locked";
  if (item.notification_type === "auto_trade_executed") return "Auto trade placed";
  if (item.notification_type === "apex_selects_executed") return "Approved trades executed";
  return item.title;
}

export default function UnitraderActivityStatus({
  botName,
  mode,
  onOpenTrade,
  tradingAccountId,
}: {
  botName: string;
  mode: SignalMode;
  onOpenTrade: () => void;
  tradingAccountId?: string | null;
}) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [stackMeta, setStackMeta] = useState<SignalStackResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const typeFilter =
        mode === "autonomous"
          ? "auto_trade_executed,stop_loss_triggered,take_profit_triggered"
          : mode === "guided"
            ? "auto_trade_executed,stop_loss_triggered,take_profit_triggered"
            : mode === "assisted"
              ? "apex_selects_ready,apex_selects_executed"
              : "browse_morning_briefing,daily_digest";

      const [notifRes, stackRes] = await Promise.all([
        notificationApi.list(mode === "autonomous" || mode === "guided" ? 3 : 5, { type: typeFilter }),
        signalApi.stack({ trading_account_id: tradingAccountId ?? undefined }),
      ]);

      setItems(notifRes.data?.data?.items ?? []);
      setStackMeta({
        signals: stackRes.data?.signals ?? [],
        last_scan_at: stackRes.data?.last_scan_at ?? null,
        next_scan_in_minutes: stackRes.data?.next_scan_in_minutes ?? null,
      });
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    load();
  }, [load]);

  const pendingApproval = useMemo(
    () => items.find((item) => item.can_approve),
    [items]
  );

  const recentActivity = useMemo(
    () => items.filter((item) => item.notification_type !== "apex_selects_ready").slice(0, 3),
    [items]
  );

  const topSignal = stackMeta?.signals?.[0] ?? null;
  const tone = statusTone(botName, mode);

  const handleApprove = async (item: NotificationItem) => {
    const token = readString(item.data?.approve_token);
    if (!token) return;
    setBusyId(item.id);
    try {
      await signalApi.approveApexSelects(token);
      await load();
      onOpenTrade();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="mb-4 rounded-2xl border border-dark-800 bg-[#0d1117] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${tone.dot} animate-pulse`} />
            <p className="text-sm font-semibold text-white">{botName} is working</p>
          </div>
          <p className="mt-1 text-xs text-dark-400">{tone.subtitle}</p>
        </div>
        <div className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium ${tone.badge}`}>
          {tone.icon}
          <span>{tone.title}</span>
        </div>
      </div>

      {loading ? (
        <div className="mt-4 space-y-2">
          <div className="h-12 animate-pulse rounded-xl bg-dark-900" />
          <div className="h-12 animate-pulse rounded-xl bg-dark-900" />
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {(mode === "autonomous" || mode === "guided") && (
            <>
              <div className="rounded-xl border border-dark-800 bg-dark-900/70 p-3 text-xs text-dark-300">
                Last scan {stackMeta?.last_scan_at ? relativeTime(stackMeta.last_scan_at) : "recently"}.
                {" "}Next scan in {stackMeta?.next_scan_in_minutes ?? 30} minutes.
              </div>
              {recentActivity.length > 0 ? recentActivity.map((item) => (
                <div key={item.id} className="flex items-center justify-between gap-3 rounded-xl border border-dark-800 bg-dark-900/50 p-3">
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-white">{activityLabel(item)}</p>
                    <p className="mt-1 text-[11px] text-dark-400 line-clamp-2">{item.body}</p>
                  </div>
                  <span className="shrink-0 text-[10px] text-dark-500">{relativeTime(item.created_at)}</span>
                </div>
              )) : (
                <div className="rounded-xl border border-dark-800 bg-dark-900/50 p-3 text-xs text-dark-400">
                  {botName} has not placed or managed a trade yet today.
                </div>
              )}
            </>
          )}

          {mode === "assisted" && pendingApproval && (
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/8 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-amber-300">
                    <Bell size={14} />
                    <p className="text-xs font-semibold">Approval waiting</p>
                  </div>
                  <p className="mt-1 text-sm text-white">{pendingApproval.title}</p>
                  <p className="mt-1 text-[11px] text-amber-100/80">{pendingApproval.body}</p>
                </div>
                <button
                  type="button"
                  onClick={() => handleApprove(pendingApproval)}
                  disabled={busyId === pendingApproval.id}
                  className="shrink-0 rounded-lg bg-amber-400 px-3 py-2 text-xs font-semibold text-dark-950 transition hover:bg-amber-300 disabled:opacity-60"
                >
                  {busyId === pendingApproval.id
                    ? "Approving..."
                    : `Approve now${countdownTo(pendingApproval.approve_expires_at ?? readString(pendingApproval.data?.expires_at)) ? ` (${countdownTo(pendingApproval.approve_expires_at ?? readString(pendingApproval.data?.expires_at))})` : " ->"}`}
                </button>
              </div>
            </div>
          )}

          {mode === "assisted" && !pendingApproval && (
            <div className="rounded-xl border border-dark-800 bg-dark-900/50 p-3 text-xs text-dark-400">
              {botName} is monitoring your thresholds and will ask for approval when a shortlist is ready.
            </div>
          )}

          {mode === "watch" && (
            <>
              <div className="rounded-xl border border-dark-800 bg-dark-900/60 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-[11px] text-amber-300">
                      <Sparkles size={13} />
                      <span>Top signal right now</span>
                    </div>
                    {topSignal ? (
                      <>
                        <p className="mt-1 text-sm font-semibold text-white">{topSignal.asset_name} · {topSignal.signal.toUpperCase()}</p>
                        <p className="mt-1 text-[11px] text-dark-400">{topSignal.symbol} · {Math.round(topSignal.confidence)}% confidence</p>
                      </>
                    ) : (
                      <p className="mt-1 text-sm text-dark-300">{botName} is reviewing the market for your next setup.</p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={onOpenTrade}
                    className="shrink-0 rounded-lg border border-dark-700 px-3 py-2 text-xs font-medium text-white transition hover:border-dark-600"
                  >
                    View all signals <ChevronRight className="inline-block" size={12} />
                  </button>
                </div>
              </div>
              <div className="rounded-xl border border-dark-800 bg-dark-900/50 p-3 text-xs text-dark-400">
                Morning briefing {items[0]?.created_at ? `last sent ${relativeTime(items[0].created_at)}` : "will appear here once enabled"}.
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
