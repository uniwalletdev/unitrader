import { useState } from "react";
import { api } from "@/lib/api";
import { Lock, ShieldCheck } from "lucide-react";

type TraderClass = "complete_novice" | "curious_saver";

export interface TrustLadderBannerProps {
  traderClass: TraderClass | string;
  stage: 1 | 2 | 3 | 4;
  paperEnabled: boolean;
  canAdvance: boolean;
  daysAtStage: number;
  paperTradesCount: number;
  /** Display symbol for trust cap (e.g. "$", "£") */
  currencySymbol?: string;
  /** ISO code for copy (e.g. "USD") */
  currencyCode?: string;
  /** User's personalised bot name */
  botName?: string;
}

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

export default function TrustLadderBanner(props: TrustLadderBannerProps) {
  const botName = props.botName ?? "Unitrader";
  const [advancing, setAdvancing] = useState(false);

  const tc = String(props.traderClass ?? "");
  if (tc !== "complete_novice" && tc !== "curious_saver") return null;

  const isStage1 = props.stage === 1;
  const isStage2 = props.stage === 2;

  if (!isStage1 && !isStage2) return null;

  const theme = isStage1
    ? {
        border: "border-l-amber-400",
        bg: "bg-amber-500/10",
        text: "text-amber-200",
      }
    : {
        border: "border-l-blue-400",
        bg: "bg-blue-500/10",
        text: "text-blue-200",
      };

  const sym = props.currencySymbol ?? "$";
  const code = (props.currencyCode ?? "USD").toUpperCase();

  const leftText = isStage1
    ? `Watch Mode - ${botName} is using paper money. Zero real risk to you.`
    : `Micro Mode - trades capped at ${sym}25 (${code}) while ${botName} earns your trust`;

  const progressPct = Math.max(
    0,
    Math.min(100, (props.paperTradesCount / 5) * 100),
  );

  return (
    <div
      className={clsx(
        "rounded-xl border border-dark-800 p-4",
        theme.bg,
        "border-l-4",
        theme.border,
      )}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <div
            className={clsx(
              "mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg border",
              isStage1 ? "border-amber-500/30 bg-amber-500/10" : "border-blue-500/30 bg-blue-500/10",
            )}
          >
            {props.paperEnabled ? (
              <Lock size={16} className={isStage1 ? "text-amber-300" : "text-blue-300"} />
            ) : (
              <ShieldCheck size={16} className="text-green-300" />
            )}
          </div>

          <div className="min-w-0">
            <div className={clsx("text-sm font-semibold", theme.text)}>
              {isStage1 ? "Watch Mode" : "Micro Mode"}
            </div>
            <div className="mt-0.5 text-sm text-dark-200">{leftText}</div>
            <div className="mt-1 text-xs text-dark-400">
              Day {Math.max(1, props.daysAtStage)} at this stage
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 sm:justify-end">
          {props.canAdvance ? (
            <button
              type="button"
              disabled={advancing}
              onClick={async () => {
                if (advancing) return;
                setAdvancing(true);
                try {
                  await api.post("/api/onboarding/trust-ladder/advance", {});
                  window.location.reload();
                } finally {
                  setAdvancing(false);
                }
              }}
              className={clsx(
                "inline-flex items-center justify-center rounded-xl px-4 py-2 text-xs font-semibold",
                "bg-green-500 text-dark-950 hover:bg-green-400 disabled:opacity-60",
              )}
            >
              Unlock real trading
            </button>
          ) : (
            <div className="text-xs text-dark-300">
              <span className="font-semibold text-white">{props.paperTradesCount}</span>{" "}
              paper trades placed
            </div>
          )}
        </div>
      </div>

      {isStage2 && (
        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between text-xs text-dark-400">
            <span>Progress to Stage 3</span>
            <span className="tabular-nums">
              {Math.min(props.paperTradesCount, 5)} / 5
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-dark-900">
            <div
              className="h-2 rounded-full bg-blue-400"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          {props.canAdvance && (
            <div className="mt-3">
              <button
                type="button"
                disabled={advancing}
                onClick={async () => {
                  if (advancing) return;
                  setAdvancing(true);
                  try {
                    await api.post("/api/onboarding/trust-ladder/advance", {});
                    window.location.reload();
                  } finally {
                    setAdvancing(false);
                  }
                }}
                className={clsx(
                  "inline-flex items-center justify-center rounded-xl px-4 py-2 text-xs font-semibold",
                  "bg-green-500 text-dark-950 hover:bg-green-400 disabled:opacity-60",
                )}
              >
                Unlock full trading
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

