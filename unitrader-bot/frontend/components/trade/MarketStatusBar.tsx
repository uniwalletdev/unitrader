import { useEffect, useMemo, useState } from "react";
import { authApi } from "@/lib/api";
import { ChevronDown, ChevronUp } from "lucide-react";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

type AssetClass = "stocks" | "crypto" | "forex";

type DotTone = "green" | "amber" | "red";

export type MarketStatus = {
  assetClass: AssetClass;
  state: "open" | "pre" | "after" | "closed" | "weekend";
  dot: DotTone;
  message: string;
  /** Optional UI hints for the Analyse button (never blocking). */
  analyzeTooltip?: string;
  analyzeIndicator?: { tone: "amber"; text: string } | null;
  /** For advanced views */
  nyse?: "OPEN" | "CLOSED";
  lse?: "OPEN" | "CLOSED";
  crypto?: "24/7";
};

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function dotClass(tone: DotTone) {
  if (tone === "green") return "bg-green-400";
  if (tone === "amber") return "bg-amber-400";
  return "bg-red-400";
}

function fmtUKTimeFromUTC(hh: number, mm: number) {
  // Convert a UTC wall-clock time today into Europe/London formatted time,
  // respecting DST. We do this by creating a Date in UTC and formatting in UK tz.
  const now = new Date();
  const d = new Date(
    Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate(),
      hh,
      mm,
      0,
      0,
    ),
  );
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    hour: "numeric",
    minute: "2-digit",
  }).format(d);
}

function fmtUTC24(d: Date) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(d);
}

function isWeekendUTC(now: Date) {
  const day = now.getUTCDay(); // 0 Sun ... 6 Sat
  return day === 0 || day === 6;
}

function getAssetClass(exchange?: string, symbol?: string): AssetClass {
  const ex = (exchange || "").toLowerCase();
  if (ex === "binance" || ex === "coinbase" || ex === "kraken") return "crypto";
  if (ex === "oanda") return "forex";
  const s = (symbol || "").toUpperCase();
  if (s.includes("/") || s.endsWith("USDT") || s.endsWith("USDC")) return "crypto";
  if (s.includes("_")) return "forex";
  return "stocks";
}

function nyseStateUTC(now: Date) {
  // US stocks open: Mon-Fri 14:30-21:00 UTC
  // Pre-market: Mon-Fri 09:00-14:30 UTC
  // After-hours: Mon-Fri 21:00-01:00 UTC (crosses midnight)
  const day = now.getUTCDay(); // 0 Sun ... 6 Sat
  const isWeekday = day >= 1 && day <= 5;
  if (!isWeekday) return "weekend" as const;

  const mins = now.getUTCHours() * 60 + now.getUTCMinutes();
  const preStart = 9 * 60;
  const openStart = 14 * 60 + 30;
  const openEnd = 21 * 60;
  const afterEnd = 1 * 60; // 01:00 next day

  if (mins >= openStart && mins < openEnd) return "open" as const;
  if (mins >= preStart && mins < openStart) return "pre" as const;
  if (mins >= openEnd || mins < afterEnd) return "after" as const;
  return "closed" as const;
}

function forexOpenUTC(now: Date) {
  // Forex: Mon 00:00 - Fri 22:00 UTC
  const day = now.getUTCDay();
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes();
  if (day === 0) return false; // Sunday closed until Monday 00:00 UTC
  if (day >= 1 && day <= 4) return true;
  if (day === 5) return mins < 22 * 60;
  return false; // Saturday
}

function lseOpenUK(now: Date) {
  // Not specified in prompt, but needed for the experienced one-liner.
  // Use regular LSE hours: Mon–Fri 08:00–16:30 UK local time.
  const uk = new Date(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/London",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(now)
      .reduce((acc, p) => {
        if (p.type !== "literal") (acc as any)[p.type] = p.value;
        return acc;
      }, {} as Record<string, string>) as any,
  );
  // The hack above isn't reliable for constructing a Date. Instead, derive via UK parts.
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const dayStr = parts.find((p) => p.type === "weekday")?.value ?? "";
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const m = Number(parts.find((p) => p.type === "minute")?.value ?? "0");

  const weekday = ["Mon", "Tue", "Wed", "Thu", "Fri"].includes(dayStr);
  if (!weekday) return false;
  const mins = h * 60 + m;
  return mins >= 8 * 60 && mins < 16 * 60 + 30;
}

function minutesUntilUTC(now: Date, targetHH: number, targetMM: number) {
  const cur = now.getUTCHours() * 60 + now.getUTCMinutes();
  const tgt = targetHH * 60 + targetMM;
  let diff = tgt - cur;
  if (diff < 0) diff += 24 * 60;
  return diff;
}

export default function MarketStatusBar({
  traderClass: traderClassProp,
  exchange,
  symbol,
  onStatusChange,
}: {
  traderClass?: TraderClass;
  exchange?: string;
  symbol?: string;
  onStatusChange?: (s: MarketStatus) => void;
}) {
  const [traderClass, setTraderClass] = useState<TraderClass>(
    traderClassProp ?? "complete_novice",
  );
  const [now, setNow] = useState(() => new Date());
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (traderClassProp) {
      setTraderClass(traderClassProp);
      return;
    }
    let mounted = true;
    (async () => {
      try {
        const res = await authApi.getSettings();
        const tc = res.data?.trader_class as TraderClass | undefined;
        if (!mounted) return;
        if (tc) setTraderClass(tc);
      } catch {
        // ignore
      }
    })();
    return () => {
      mounted = false;
    };
  }, [traderClassProp]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60000);
    return () => window.clearInterval(id);
  }, []);

  const status: MarketStatus = useMemo(() => {
    const assetClass = getAssetClass(exchange, symbol);

    // crypto_native: always minimal crypto line + weekend liquidity note
    if (traderClass === "crypto_native") {
      const weekend = isWeekendUTC(now);
      const msg = weekend
        ? "Crypto 24/7 · Weekend: lower liquidity, wider spreads possible"
        : "Crypto 24/7";
      return {
        assetClass: "crypto",
        state: "open",
        dot: weekend ? "amber" : "green",
        message: msg,
        analyzeTooltip: undefined,
        analyzeIndicator: null,
        nyse: "CLOSED",
        lse: "CLOSED",
        crypto: "24/7",
      };
    }

    // Asset-specific logic (but we never block analysis)
    if (assetClass === "crypto") {
      const msg =
        traderClass === "experienced" || traderClass === "semi_institutional"
          ? "NYSE: CLOSED | LSE: CLOSED | Crypto: 24/7"
          : "Crypto never closes - available 24 hours a day";
      return {
        assetClass,
        state: "open",
        dot: "green",
        message: msg,
        analyzeTooltip: undefined,
        analyzeIndicator: null,
        nyse: "CLOSED",
        lse: "CLOSED",
        crypto: "24/7",
      };
    }

    if (assetClass === "forex") {
      const open = forexOpenUTC(now);
      const msg =
        traderClass === "experienced" || traderClass === "semi_institutional"
          ? `NYSE: ${nyseStateUTC(now) === "open" ? "OPEN" : "CLOSED"} | LSE: ${
              lseOpenUK(now) ? "OPEN" : "CLOSED"
            } | Crypto: 24/7`
          : open
            ? "Good time to trade - markets are open"
            : "Markets are closed for the weekend - back Monday at 2:30pm UK time";
      return {
        assetClass,
        state: open ? "open" : isWeekendUTC(now) ? "weekend" : "closed",
        dot: open ? "green" : open ? "green" : "red",
        message: msg,
        analyzeTooltip: open ? undefined : "Unitrader will use the latest data available",
        analyzeIndicator:
          !open && (traderClass === "experienced" || traderClass === "semi_institutional")
            ? { tone: "amber", text: "After-hours analysis" }
            : null,
        nyse: nyseStateUTC(now) === "open" ? "OPEN" : "CLOSED",
        lse: lseOpenUK(now) ? "OPEN" : "CLOSED",
        crypto: "24/7",
      };
    }

    // Stocks (NYSE schedule)
    const nyse = nyseStateUTC(now);
    const ukOpenTime = fmtUKTimeFromUTC(14, 30);
    const ukNextOpenTime = fmtUKTimeFromUTC(14, 30);

    if (traderClass === "experienced" || traderClass === "semi_institutional") {
      return {
        assetClass,
        state: nyse === "open" ? "open" : "closed",
        dot: nyse === "open" ? "green" : "amber",
        message: `NYSE: ${nyse === "open" ? "OPEN" : "CLOSED"} | LSE: ${
          lseOpenUK(now) ? "OPEN" : "CLOSED"
        } | Crypto: 24/7`,
        analyzeTooltip: undefined,
        analyzeIndicator: nyse !== "open" ? { tone: "amber", text: "After-hours analysis" } : null,
        nyse: nyse === "open" ? "OPEN" : "CLOSED",
        lse: lseOpenUK(now) ? "OPEN" : "CLOSED",
        crypto: "24/7",
      };
    }

    if (traderClass === "self_taught") {
      if (nyse === "open") {
        const mins = minutesUntilUTC(now, 21, 0);
        const h = Math.floor(mins / 60);
        const m = mins % 60;
        return {
          assetClass,
          state: "open",
          dot: "green",
          message: `NYSE open - closes in ${h}h ${m}m`,
          analyzeTooltip: undefined,
          analyzeIndicator: null,
          nyse: "OPEN",
          lse: lseOpenUK(now) ? "OPEN" : "CLOSED",
          crypto: "24/7",
        };
      }
      const pre = fmtUTC24(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 9, 0)));
      const open = fmtUTC24(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 14, 30)));
      return {
        assetClass,
        state: nyse === "weekend" ? "weekend" : "closed",
        dot: nyse === "weekend" ? "red" : "amber",
        message: `NYSE closed - pre-market ${pre} - opens ${open}`,
        analyzeTooltip: "Unitrader will use the latest data available",
        analyzeIndicator: null,
        nyse: "CLOSED",
        lse: lseOpenUK(now) ? "OPEN" : "CLOSED",
        crypto: "24/7",
      };
    }

    // complete_novice / curious_saver (UK-local time wording)
    if (nyse === "open") {
      return {
        assetClass,
        state: "open",
        dot: "green",
        message: "Good time to trade - markets are open",
        analyzeTooltip: undefined,
        analyzeIndicator: null,
        nyse: "OPEN",
        lse: lseOpenUK(now) ? "OPEN" : "CLOSED",
        crypto: "24/7",
      };
    }
    if (nyse === "pre") {
      return {
        assetClass,
        state: "pre",
        dot: "amber",
        message: `Markets open at ${ukOpenTime} - you can still see analysis now`,
        analyzeTooltip: "Unitrader will use the latest data available",
        analyzeIndicator: null,
        nyse: "CLOSED",
        lse: lseOpenUK(now) ? "OPEN" : "CLOSED",
        crypto: "24/7",
      };
    }
    if (nyse === "after") {
      return {
        assetClass,
        state: "after",
        dot: "amber",
        message: `Markets have closed for today - back tomorrow at ${ukNextOpenTime}`,
        analyzeTooltip: "Unitrader will use the latest data available",
        analyzeIndicator: null,
        nyse: "CLOSED",
        lse: lseOpenUK(now) ? "OPEN" : "CLOSED",
        crypto: "24/7",
      };
    }
    if (nyse === "weekend") {
      return {
        assetClass,
        state: "weekend",
        dot: "red",
        message: "Markets are closed for the weekend - back Monday at 2:30pm UK time",
        analyzeTooltip: "Unitrader will use the latest data available",
        analyzeIndicator: null,
        nyse: "CLOSED",
        lse: "CLOSED",
        crypto: "24/7",
      };
    }
    return {
      assetClass,
      state: "closed",
      dot: "red",
      message: `Markets open at ${ukOpenTime} - you can still see analysis now`,
      analyzeTooltip: "Unitrader will use the latest data available",
      analyzeIndicator: null,
      nyse: "CLOSED",
      lse: lseOpenUK(now) ? "OPEN" : "CLOSED",
      crypto: "24/7",
    };
  }, [exchange, symbol, traderClass, now]);

  useEffect(() => {
    onStatusChange?.(status);
  }, [status, onStatusChange]);

  const isProLine = traderClass === "experienced" || traderClass === "semi_institutional";

  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950 px-4 py-3">
      <button
        type="button"
        onClick={() => {
          if (isProLine) setExpanded((v) => !v);
        }}
        className={clsx(
          "flex w-full items-center justify-between gap-3 text-left",
          isProLine ? "cursor-pointer" : "cursor-default",
        )}
      >
        <div className="flex items-center gap-2">
          <span className={clsx("h-2 w-2 rounded-full", dotClass(status.dot))} />
          <span className="text-xs font-semibold text-dark-200">{status.message}</span>
        </div>
        {isProLine && (
          <span className="text-dark-400">
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </span>
        )}
      </button>

      {isProLine && expanded && (
        <div className="mt-3 rounded-xl border border-dark-800 bg-dark-950 p-3 text-xs text-dark-300">
          <div className="flex items-center justify-between">
            <div className="font-semibold text-white">Next economic event</div>
            <div className="font-mono text-dark-400">UTC</div>
          </div>
          <div className="mt-2">FOMC in 2 days</div>
        </div>
      )}
    </div>
  );
}

