import { useMemo } from "react";
import { Activity, BarChart3, Crosshair, LineChart, Settings } from "lucide-react";
import { isNative } from "@/hooks/useCapacitor";

type TabId = "trade" | "positions" | "chat" | "performance" | "settings";

export default function MobileNav({
  active,
  onChange,
}: {
  active: TabId;
  onChange: (id: TabId) => void;
}) {
  const tabs = useMemo(
    () => [
      { id: "trade" as const, label: "Trade", Icon: Crosshair },
      { id: "positions" as const, label: "Positions", Icon: BarChart3 },
      { id: "chat" as const, label: "Chat", Icon: Activity },
      { id: "performance" as const, label: "Performance", Icon: LineChart },
      { id: "settings" as const, label: "Settings", Icon: Settings },
    ],
    [],
  );

  if (!isNative) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 border-t border-dark-800/60 bg-[#0a0d14]/95 backdrop-blur-lg">
      <div className="mx-auto grid max-w-3xl grid-cols-5">
        {tabs.map(({ id, label, Icon }) => {
          const isActive = active === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onChange(id)}
              className={[
                "flex flex-col items-center justify-center gap-1 px-2 py-2.5 text-[10px] transition-colors",
                isActive ? "text-brand-400" : "text-dark-500 hover:text-dark-300",
              ].join(" ")}
              aria-label={label}
            >
              <Icon size={18} strokeWidth={isActive ? 2.5 : 1.5} />
              <span className="leading-none">{label}</span>
            </button>
          );
        })}
      </div>
      <div className="h-[env(safe-area-inset-bottom)]" />
    </div>
  );
}

