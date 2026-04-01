import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Bell, Shield, Star, SunMedium, CheckCircle2 } from "lucide-react";

import { notificationApi, signalApi } from "@/lib/api";
import { countdownTo, readString, relativeTime, type NotificationItem } from "@/components/notifications/notificationUtils";

function notificationIcon(type: string) {
  switch (type) {
    case "auto_trade_executed":
      return <div className="flex h-8 w-8 items-center justify-center rounded-full bg-green-500/20 text-green-400"><CheckCircle2 size={14} /></div>;
    case "apex_selects_ready":
      return <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-500/20 text-blue-400"><Bell size={14} /></div>;
    case "stop_loss_triggered":
      return <div className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-500/20 text-amber-400"><Shield size={14} /></div>;
    case "take_profit_triggered":
      return <div className="flex h-8 w-8 items-center justify-center rounded-full bg-green-500/20 text-green-400"><Star size={14} /></div>;
    case "browse_morning_briefing":
      return <div className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-500/20 text-amber-400"><SunMedium size={14} /></div>;
    default:
      return <div className="flex h-8 w-8 items-center justify-center rounded-full bg-dark-800 text-dark-300"><AlertTriangle size={14} /></div>;
  }
}

export default function UnitraderNotificationFeed({
  userId,
  maxItems = 20,
}: { userId: string; maxItems?: number }) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = async () => {
    try {
      setLoading(true);
      const res = await notificationApi.list(maxItems);
      const data = res.data?.data || {};
      setItems(data.items || []);
      setUnreadCount(data.unread_count || 0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!userId) return;
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, [userId, maxItems]);

  const actionableCount = useMemo(
    () => items.filter((item) => item.can_undo || item.can_approve).length,
    [items]
  );

  const markRead = async (id: string) => {
    setItems((prev) => prev.map((item) => item.id === id ? { ...item, read_at: new Date().toISOString() } : item));
    setUnreadCount((prev) => Math.max(0, prev - 1));
    try {
      await notificationApi.markRead(id);
    } catch {}
  };

  const handleUndo = async (item: NotificationItem) => {
    if (!item.undo_token) return;
    setBusyId(item.id);
    try {
      await notificationApi.undoTrade(item.undo_token);
      await load();
    } finally {
      setBusyId(null);
    }
  };

  const handleApprove = async (item: NotificationItem) => {
    const token = readString(item.data?.approve_token);
    if (!token) return;
    setBusyId(item.id);
    try {
      await signalApi.approveApexSelects(token);
      await load();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-4">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white">Unitrader notifications</h3>
          <p className="text-[11px] text-dark-500">{unreadCount} unread · {actionableCount} actionable</p>
        </div>
        {unreadCount > 0 && (
          <button
            type="button"
            onClick={async () => {
              setItems((prev) => prev.map((item) => ({ ...item, read_at: item.read_at ?? new Date().toISOString() })));
              setUnreadCount(0);
              try { await notificationApi.markAllRead(); } catch {}
            }}
            className="text-[11px] text-brand-400 hover:text-brand-300"
          >
            Mark all read
          </button>
        )}
      </div>

      {loading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse rounded-xl bg-dark-900" />)}
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dark-800 bg-dark-900/50 p-4 text-xs text-dark-400">
          Unitrader has not sent any notifications yet.
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => {
            const countdown = countdownTo(
              item.notification_type === "apex_selects_ready"
                ? item.approve_expires_at ?? readString(item.data?.expires_at) ?? readString(item.data?.approve_expires_at) ?? null
                : item.undo_expires_at
            );
            return (
              <button
                type="button"
                key={item.id}
                onClick={() => !item.read_at && markRead(item.id)}
                className="w-full rounded-xl border border-dark-800 bg-dark-900/60 p-3 text-left transition hover:border-dark-700"
              >
                <div className="flex items-start gap-3">
                  <div className="relative shrink-0">
                    {notificationIcon(item.notification_type)}
                    {!item.read_at && <span className="absolute -left-1 top-0 h-2.5 w-2.5 rounded-full bg-blue-400" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-xs font-semibold text-white">{item.title}</p>
                      <span className="shrink-0 text-[10px] text-dark-500">{relativeTime(item.created_at)}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-dark-400">{item.body}</p>
                    {(item.can_undo || item.can_approve) && (
                      <div className="mt-3 flex items-center gap-2">
                        {item.can_undo && (
                          <button
                            type="button"
                            disabled={busyId === item.id}
                            onClick={(e) => { e.stopPropagation(); handleUndo(item); }}
                            className="rounded-lg bg-amber-500/15 px-2.5 py-1 text-[11px] font-medium text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
                          >
                            {busyId === item.id ? "Undoing..." : `Undo${countdown ? ` (${countdown})` : ""}`}
                          </button>
                        )}
                        {item.can_approve && (
                          <button
                            type="button"
                            disabled={busyId === item.id}
                            onClick={(e) => { e.stopPropagation(); handleApprove(item); }}
                            className="rounded-lg bg-blue-500/15 px-2.5 py-1 text-[11px] font-medium text-blue-300 hover:bg-blue-500/20 disabled:opacity-50"
                          >
                            {busyId === item.id ? "Approving..." : `Approve${countdown ? ` (${countdown})` : ""}`}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
