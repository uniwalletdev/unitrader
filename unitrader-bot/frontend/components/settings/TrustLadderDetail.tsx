import { useEffect, useMemo, useState } from "react";
import { authApi, api } from "@/lib/api";
import { Check, Lock, Loader2 } from "lucide-react";

type TraderClass = "complete_novice" | "curious_saver";

type LadderStatus = {
  stage: 1 | 2 | 3;
  completed_at?: Record<string, string | null>;
  conditions?: Record<string, string[]>;
  autonomous_mode_unlocked?: boolean;
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
  // NOTE: these two useState calls USED to live below the early `return null`
  // guards further down, which violated the Rules of Hooks — when traderClass
  // flipped from null → "complete_novice" between renders the hook count
  // grew from 6 to 8 and React threw #310. Keep all hooks unconditional at
  // the top of the component; the early returns below are still fine because
  // they are after every hook call.
  const [unlocking, setUnlocking] = useState(false);
  const [unlockError, setUnlockError] = useState<string | null>(null);
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
        key: "autonomous",
        title: "Autonomous Mode (opt-in)",
        unlocksWhen: [
          "Stage 3 completed",
          "10 live trades placed",
          "Risk disclosure accepted",
          "No active circuit-breaker",
        ],
      },
    ];
  }, []);

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
  const autonomousUnlocked = status?.autonomous_mode_unlocked ?? false;

  const handleUnlockAutonomous = async () => {
    setUnlocking(true);
    setUnlockError(null);
    try {
      await api.post("/api/onboarding/unlock-autonomous", {});
      setStatus((prev) => prev ? { ...prev, autonomous_mode_unlocked: true } : prev);
    } catch (e: any) {
      const failures: string[] | undefined = e?.response?.data?.detail?.failures;
      setUnlockError(
        failures?.join(", ") ?? e?.response?.data?.detail ?? "Unlock failed"
      );
    } finally {
      setUnlocking(false);
    }
  };

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
          const isAutonomousRow = s.key === "autonomous";
          const n = isAutonomousRow ? 0 : idx + 1;
          const isDone = !isAutonomousRow && n < stage;
          const isActive = !isAutonomousRow && n === stage;
          const completionDate = !isAutonomousRow ? formatDate(status?.completed_at?.[String(n)] ?? null) : null;

          if (isAutonomousRow) {
            return (
              <div key={s.key} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={clsx(
                      "relative flex h-7 w-7 items-center justify-center rounded-full",
                      autonomousUnlocked
                        ? "bg-green-500 text-dark-950"
                        : "border border-dark-700 bg-dark-950 text-dark-400",
                    )}
                  >
                    {autonomousUnlocked ? <Check size={14} /> : <Lock size={14} />}
                  </div>
                </div>
                <div className="flex-1 rounded-xl border border-dark-800 bg-dark-950 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-white">{s.title}</div>
                    {autonomousUnlocked && (
                      <div className="text-xs font-semibold text-emerald-400">Unlocked</div>
                    )}
                  </div>
                  {autonomousUnlocked ? (
                    <div className="mt-2 text-xs text-dark-400">
                      Autonomous mode is active. Switch to Auto mode on the Trade page.
                    </div>
                  ) : (
                    <div className="mt-3 flex flex-col gap-2">
                      <ul className="space-y-1 text-xs text-dark-400">
                        {s.unlocksWhen.map((c) => (
                          <li key={c} className="flex items-start gap-2">
                            <span className="mt-1 h-1.5 w-1.5 rounded-full bg-dark-600" />
                            <span>{c}</span>
                          </li>
                        ))}
                      </ul>
                      {stage >= 3 && (
                        <button
                          onClick={handleUnlockAutonomous}
                          disabled={unlocking}
                          className="mt-1 w-fit rounded-lg bg-brand-500 px-4 py-2 text-xs font-semibold text-white hover:bg-brand-400 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                        >
                          {unlocking && <Loader2 className="w-3 h-3 animate-spin" />}
                          Unlock Autonomous Mode
                        </button>
                      )}
                      {unlockError && (
                        <p className="text-[11px] text-red-400">{unlockError}</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          }

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
                  <div className="mt-3 text-xs text-dark-400">Unlocked</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

