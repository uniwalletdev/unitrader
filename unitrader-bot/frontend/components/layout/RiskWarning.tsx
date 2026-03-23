type RiskWarningProps = {
  variant: "bar" | "inline" | "footer";
};

const BAR_TEXT =
  "Risk warning: Trading involves risk of loss. Your capital is at risk.";

const FOOTER_TEXT =
  "Trading involves significant risk of loss and is not suitable for all investors. " +
  "Past performance does not guarantee future results. Unitrader is a software tool, " +
  "not a financial broker or registered investment advisor. Unitrader is an AI tool. " +
  "Always consider your financial situation before trading.";

export default function RiskWarning({ variant }: RiskWarningProps) {
  if (variant === "bar") {
    return (
      <div className="w-full border-b border-dark-800 bg-[#0d1117] px-4 py-2 text-center text-[10px] text-dark-500">
        {BAR_TEXT}
      </div>
    );
  }

  if (variant === "inline") {
    return (
      <div className="rounded-xl border-l-4 border-amber-500 bg-amber-500/[0.05] px-4 py-3 text-[11px] text-dark-500">
        {BAR_TEXT}
      </div>
    );
  }

  // variant === "footer"
  return (
    <p className="text-[10px] leading-relaxed text-dark-600">
      {FOOTER_TEXT}
    </p>
  );
}
