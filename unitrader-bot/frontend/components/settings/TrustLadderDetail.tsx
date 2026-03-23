import { useEffect, useMemo, useState } from "react";
import { authApi, api } from "@/lib/api";
import { Check, Lock } from "lucide-react";

type TraderClass = "complete_novice" | "curious_saver";

type LadderStatus = {
  stage: 1 | 2 | 3 | 4;
  completed_at?: Record<string, string | null>;
  conditions?: Record<string, string[]>;
};

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" });
}

export default function TrustLadderDetail() {
  const [traderClass, setTraderClass] = useState<TraderClass | "other" | null>(null);
  const [status, setStatus] = useState<LadderStatus | null>(null);

  // CRITICAL RULE: check trader_class before rendering anything.
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await authApi.getSettings();
        const tc = String(res.data?.trader_class ?? "");
        if (!mounted) return;
        if (tc === "complete_novice" || tc === "curious_saver") setTraderClass(tc);
        else setTraderClass("other");
      } catch {
        if (!mounted) return;
        setTraderClass("other");
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (traderClass !== "complete_novice" && traderClass !== "curious_saver") return;
    let mounted = true;
    (async () => {
      // Best-effort: endpoint may not exist yet.
      try {
        const res = await api.get("/api/onboarding/trust-ladder/status");
        const d = res.data?.data ?? res.data;
        if (!mounted) return;
        if (d && typeof d === "object" && typeof d.stage === "number") {
          setStatus(d as LadderStatus);
        } else {
          setStatus({ stage: 1 });
        }
      } catch {
        if (!mounted) return;
        setStatus({ stage: 1 });
      }
    })();
    return () => {
      mounted = false;
    };
  }, [traderClass]);

  if (traderClass === null) return null;
  if (traderClass === "other") return null;

  const stage = status?.stage ?? 1;

  const stages = useMemo(() => {
    return [
      {
        key: "1",
        title: "Stage 1 — Watch Mode",
        unlocksWhen: ["Paper trading enabled"],
      },
      {
        key: "2",
        title: "Stage 2 — Micro Mode",
        unlocksWhen: ["Complete onboarding", "Unitrader places a few paper trades"],
      },
      {
        key: "3",
        title: "Stage 3 — Full Trading",
        unlocksWhen: ["5 paper trades completed", "Risk disclosure accepted"],
      },
      {
        key: "4",
        title: "Stage 4 — Autonomy",
        unlocksWhen: ["Sustained performance", "No recent circuit breaker triggers"],
      },
    ];
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <div className="text-sm font-semibold text-white">Trust Ladder</div>
        <div className="mt-1 text-xs text-dark-400">
          A structured path that unlocks more trading capability as Unitrader earns your trust.
        </div>
      </div>

      <div className="space-y-4">
        {stages.map((s, idx) => {
          const n = idx + 1;
          const isDone = n < stage;
          const isActive = n === stage;
          const completionDate = formatDate(status?.completed_at?.[String(n)] ?? null);

          return (
            <div key={s.key} className="flex gap-3">
              <div className="flex flex-col items-center">
                <div
                  className={clsx(
                    "relative flex h-7 w-7 items-center justify-center rounded-full",
                    isDone
                      ? "bg-green-500 text-dark-950"
                      : isActive
                        ? "border-2 border-green-400 bg-dark-950"
                        : "border border-dark-700 bg-dark-950 text-dark-400",
                  )}
                >
                  {isDone ? (
                    <Check size={14} />
                  ) : isActive ? (
                    <span className="absolute inset-0 rounded-full border-2 border-green-400/40 animate-pulse" />
                  ) : (
                    <Lock size={14} />
                  )}
                </div>
                {idx < stages.length - 1 && (
                  <div className="mt-2 h-full w-px bg-dark-800" />
                )}
              </div>

              <div className="flex-1 rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-semibold text-white">{s.title}</div>
                  {isDone && completionDate && (
                    <div className="text-xs text-dark-400">Completed {completionDate}</div>
                  )}
                  {isActive && (
                    <div className="text-xs font-semibold text-green-300">Active</div>
                  )}
                </div>

                {isActive ? (
                  <div className="mt-3">
                    <div className="text-xs font-semibold text-dark-200">Unlock conditions</div>
                    <ul className="mt-2 space-y-1 text-xs text-dark-400">
                      {(status?.conditions?.[String(n)] ?? s.unlocksWhen).map((c) => (
                        <li key={c} className="flex items-start gap-2">
                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-green-400" />
                          <span>{c}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : !isDone ? (
                  <div className="mt-3 text-xs text-dark-400">
                    Unlocks when:{" "}
                    <span className="text-dark-200">
                      {(status?.conditions?.[String(n)] ?? s.unlocksWhen).join(", ")}
                    </span>
                  </div>
                ) : (
                  <div className="mt-3 text-xs text-dark-400">
                    Unlocked
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

