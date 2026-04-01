"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Bell, CheckCircle2, Loader2, Shield, Star, Undo2 } from "lucide-react";

import { notificationApi, signalApi } from "@/lib/api";
import { countdownTo, readString, relativeTime, type NotificationItem } from "@/components/notifications/notificationUtils";

function pickSurfaceItem(items: NotificationItem[]) {
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  return items.find((item) => {
    const created = new Date(item.created_at).getTime();
    if (Number.isNaN(created) || created < cutoff) return false;
    return (
      item.can_undo ||
      item.can_approve ||
      ["stop_loss_triggered", "take_profit_triggered", "browse_morning_briefing", "daily_digest"].includes(item.notification_type)
    );
  }) ?? null;
}

function tickerIcon(item: NotificationItem) {
  switch (item.notification_type) {
    case "auto_trade_executed":
      return <CheckCircle2 size={14} className="text-emerald-300" />;
    case "apex_selects_ready":
      return <Bell size={14} className="text-sky-300" />;
    case "stop_loss_triggered":
      return <Shield size={14} className="text-amber-300" />;
    case "take_profit_triggered":
      return <Star size={14} className="text-emerald-300" />;
    default:
      return <Bell size={14} className="text-dark-300" />;
  }
}

export default function ApexNotificationTicker() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [hiddenId, setHiddenId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await notificationApi.list(8, {
        type: "auto_trade_executed,apex_selects_ready,stop_loss_triggered,take_profit_triggered,browse_morning_briefing,daily_digest",
      });
      setItems(res.data?.data?.items ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [load]);

  const item = useMemo(() => pickSurfaceItem(items), [items]);

  useEffect(() => {
    if (!item?.read_at) return;
    const timer = window.setTimeout(() => setHiddenId(item.id), 10000);
    return () => window.clearTimeout(timer);
  }, [item?.id, item?.read_at]);

  useEffect(() => {
    if (!item || item.read_at || hiddenId === item.id) return;
    notificationApi.markRead(item.id).catch(() => {});
    setItems((prev) => prev.map((entry) => (
      entry.id === item.id ? { ...entry, read_at: new Date().toISOString() } : entry
    )));
  }, [hiddenId, item]);

  if (loading && items.length === 0) return null;
  if (!item || hiddenId === item.id) return null;

  const countdown = countdownTo(
    item.can_approve
      ? item.approve_expires_at ?? readString(item.data?.expires_at) ?? readString(item.data?.approve_expires_at) ?? null
      : item.undo_expires_at
  );

  const handleUndo = async () => {
    if (!item.undo_token) return;
    setBusy(true);
    try {
      await notificationApi.undoTrade(item.undo_token);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const handleApprove = async () => {
    const token = readString(item.data?.approve_token);
    if (!token) return;
    setBusy(true);
    try {
      await signalApi.approveApexSelects(token);
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mb-3 rounded-xl border border-dark-800 bg-dark-900/80 px-3 py-2">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-2">
          <div className="mt-0.5 shrink-0">{busy ? <Loader2 size={14} className="animate-spin text-brand-300" /> : tickerIcon(item)}</div>
          <div className="min-w-0">
            <p className="truncate text-xs font-semibold text-white">{item.title}</p>
            <p className="line-clamp-1 text-[11px] text-dark-400">{item.body}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-dark-500">{relativeTime(item.created_at)}</span>
          {item.can_undo && (
            <button
              type="button"
              onClick={handleUndo}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2.5 py-1 font-medium text-amber-300 hover:bg-amber-500/20 disabled:opacity-60"
            >
              <Undo2 size={12} />
              {busy ? "Undoing..." : `Undo${countdown ? ` (${countdown})` : ""}`}
            </button>
          )}
          {item.can_approve && (
            <button
              type="button"
              onClick={handleApprove}
              disabled={busy}
              className="rounded-md bg-sky-500/15 px-2.5 py-1 font-medium text-sky-300 hover:bg-sky-500/20 disabled:opacity-60"
            >
              {busy ? "Approving..." : `Approve${countdown ? ` (${countdown})` : ""}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
