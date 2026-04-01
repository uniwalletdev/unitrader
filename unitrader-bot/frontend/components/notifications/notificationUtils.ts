export type NotificationItem = {
  id: string;
  notification_type: string;
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
  undo_token?: string | null;
  undo_expires_at?: string | null;
  approve_expires_at?: string | null;
  data?: Record<string, unknown>;
  can_undo?: boolean;
  can_approve?: boolean;
};

export function relativeTime(iso: string) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.max(0, Math.floor(diffMs / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export function countdownTo(iso?: string | null) {
  if (!iso) return null;
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return null;
  const totalSec = Math.floor(diff / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
