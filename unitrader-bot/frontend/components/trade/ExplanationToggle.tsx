import { useEffect, useMemo, useRef, useState } from "react";
import { api, authApi } from "@/lib/api";
import { Check, Copy } from "lucide-react";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

export type ExplanationLevel = "expert" | "simple" | "metaphor";

export default function ExplanationToggle({
  explanations,
  onLevelChange,
}: {
  explanations: { expert: string; simple: string; metaphor: string };
  onLevelChange?: (level: ExplanationLevel) => void;
}) {
  const [traderClass, setTraderClass] = useState<TraderClass>("complete_novice");
  const [settingsLevel, setSettingsLevel] = useState<ExplanationLevel | null>(null);
  const [activeLevel, setActiveLevel] = useState<ExplanationLevel>("metaphor");
  const [displayText, setDisplayText] = useState<string>(explanations.metaphor);
  const [fading, setFading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const savedTimerRef = useRef<number | null>(null);

  const classDefault: ExplanationLevel = useMemo(() => {
    const map: Record<TraderClass, ExplanationLevel> = {
      complete_novice: "metaphor",
      curious_saver: "simple",
      self_taught: "simple",
      experienced: "expert",
      semi_institutional: "expert",
      crypto_native: "expert",
    };
    return map[traderClass] ?? "simple";
  }, [traderClass]);

  // Load userSettings on mount (trader_class + explanation_level)
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await authApi.getSettings();
        if (!mounted) return;
        const tc = (res.data?.trader_class as TraderClass | undefined) ?? "complete_novice";
        const lvl = (res.data?.explanation_level as ExplanationLevel | undefined) ?? null;
        setTraderClass(tc);
        setSettingsLevel(lvl);
      } catch {
        // fall back to defaults
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  // Resolve active level with priority:
  // 1) localStorage apex_explanation_level
  // 2) userSettings.explanation_level
  // 3) class default
  useEffect(() => {
    let override: ExplanationLevel | null = null;
    try {
      if (typeof window !== "undefined") {
        const raw = window.localStorage.getItem("apex_explanation_level");
        if (raw === "expert" || raw === "simple" || raw === "metaphor") override = raw;
      }
    } catch {
      // ignore
    }
    const next = override ?? settingsLevel ?? classDefault;

    // experienced + semi_institutional: expert first, always default
    const enforced =
      traderClass === "experienced" || traderClass === "semi_institutional"
        ? "expert"
        : next;
    setActiveLevel(enforced);
  }, [classDefault, settingsLevel, traderClass]);

  // Update displayed text with fade transition 150ms
  useEffect(() => {
    const nextText = explanations[activeLevel];
    setFading(true);
    const t = window.setTimeout(() => {
      setDisplayText(nextText);
      setFading(false);
      onLevelChange?.(activeLevel);
    }, 150);
    return () => window.clearTimeout(t);
  }, [activeLevel, explanations, onLevelChange]);

  useEffect(() => {
    return () => {
      if (savedTimerRef.current) window.clearTimeout(savedTimerRef.current);
    };
  }, []);

  const buttons = useMemo(() => {
    if (traderClass === "complete_novice" || traderClass === "curious_saver") {
      return [
        { level: "metaphor" as const, label: "Explain like I'm 5" },
        { level: "simple" as const, label: "Simple" },
        { level: "expert" as const, label: "Expert" },
      ];
    }
    if (traderClass === "self_taught") {
      return [
        { level: "simple" as const, label: "Simple" },
        { level: "expert" as const, label: "Expert" },
        { level: "metaphor" as const, label: "Explain like I'm 5" },
      ];
    }
    if (traderClass === "experienced" || traderClass === "semi_institutional") {
      return [
        { level: "expert" as const, label: "Expert" },
        { level: "simple" as const, label: "Simple" },
      ];
    }
    if (traderClass === "crypto_native") {
      return [
        { level: "expert" as const, label: "Technical" },
        { level: "simple" as const, label: "Plain English" },
        { level: "metaphor" as const, label: "ELI5" },
      ];
    }
    return [
      { level: "simple" as const, label: "Simple" },
      { level: "expert" as const, label: "Expert" },
    ];
  }, [traderClass]);

  const canSelectLevel = (level: ExplanationLevel) => {
    if (traderClass === "experienced" || traderClass === "semi_institutional") {
      // "Expert first, always default": keep toggle UI but enforce expert active
      return level === "expert" || level === "simple";
    }
    return true;
  };

  const setLevel = (level: ExplanationLevel) => {
    if (!canSelectLevel(level)) return;
    if (traderClass === "experienced" || traderClass === "semi_institutional") {
      setActiveLevel("expert");
      return;
    }
    setActiveLevel(level);
  };

  const handleSaveDefault = async () => {
    if (saving) return;
    setSaving(true);
    try {
      if (typeof window !== "undefined") {
        window.localStorage.setItem("apex_explanation_level", activeLevel);
      }
      await authApi.updateSettings({ explanation_level: activeLevel });
      setSaved(true);
      if (savedTimerRef.current) window.clearTimeout(savedTimerRef.current);
      savedTimerRef.current = window.setTimeout(() => setSaved(false), 2000);
    } catch {
      // ignore; localStorage already saved
      setSaved(true);
      if (savedTimerRef.current) window.clearTimeout(savedTimerRef.current);
      savedTimerRef.current = window.setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  const showEncouragingText =
    traderClass === "complete_novice" || traderClass === "curious_saver";

  return (
    <div className="space-y-3">
      <div className="inline-flex flex-wrap items-center gap-2 rounded-xl border border-dark-800 bg-dark-950 p-2">
        {buttons.map((b) => {
          const selected = activeLevel === b.level;
          return (
            <button
              key={b.level}
              type="button"
              onClick={() => setLevel(b.level)}
              className={[
                "rounded-lg px-3 py-2 text-xs font-semibold transition",
                selected
                  ? "bg-brand-500/15 text-brand-300"
                  : "text-dark-300 hover:bg-dark-900 hover:text-white",
                (traderClass === "experienced" || traderClass === "semi_institutional") &&
                b.level !== "expert"
                  ? "opacity-70"
                  : "",
              ].join(" ")}
            >
              {b.label}
            </button>
          );
        })}

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={handleSaveDefault}
            disabled={saving}
            className="text-xs font-semibold text-brand-400 hover:underline disabled:opacity-60"
          >
            Set as my default
          </button>
          {saved && (
            <span className="inline-flex items-center gap-1 text-xs text-green-300">
              <Check size={14} /> Saved
            </span>
          )}
        </div>
      </div>

      {showEncouragingText && (
        <div className="text-xs text-dark-400">
          Most beginners prefer Simple or simpler
        </div>
      )}

      <div
        className={[
          "rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-200",
          "transition-opacity duration-150",
          fading ? "opacity-0" : "opacity-100",
        ].join(" ")}
      >
        {displayText}

        {traderClass === "semi_institutional" && (
          <div className="mt-4">
            <button
              type="button"
              onClick={async () => {
                try {
                  const res = await api.get("/api/trading/last-decision-json");
                  const payload = res.data?.data ?? res.data;
                  const text = JSON.stringify(payload, null, 2);
                  await navigator.clipboard.writeText(text);
                } catch {
                  // ignore
                }
              }}
              className="inline-flex items-center gap-2 rounded-xl border border-dark-800 bg-dark-900 px-3 py-2 text-xs font-semibold text-dark-200 hover:text-white"
            >
              <Copy size={14} />
              Copy reasoning JSON
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

