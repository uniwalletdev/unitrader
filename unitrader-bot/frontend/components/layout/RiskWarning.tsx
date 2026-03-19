type RiskWarningProps = {
  variant: "bar" | "inline" | "footer";
};

const BAR_TEXT =
  "Risk warning: Trading involves risk of loss. Your capital is at risk.";

const FOOTER_TEXT =
  "Trading involves significant risk of loss and is not suitable for all investors. " +
  "Past performance does not guarantee future results. Unitrader is a software tool, " +
  "not a financial broker or registered investment advisor. Apex is an AI tool. " +
  "Always consider your financial situation before trading.";

export default function RiskWarning({ variant }: RiskWarningProps) {
  if (variant === "bar") {
    return (
      <div
        className="w-full border-b px-4 py-2 text-center"
        style={{
          backgroundColor: "#0d1018",
          borderColor: "#1e2330",
          fontSize: 10,
          color: "#4b5563",
        }}
      >
        {BAR_TEXT}
      </div>
    );
  }

  if (variant === "inline") {
    return (
      <div
        className="rounded-lg border-l-4 px-4 py-3"
        style={{
          borderColor: "#f59e0b",
          backgroundColor: "rgba(245,158,11,0.05)",
          fontSize: 11,
          color: "#4b5563",
        }}
      >
        {BAR_TEXT}
      </div>
    );
  }

  // variant === "footer"
  return (
    <p
      className="leading-relaxed"
      style={{ fontSize: 10, color: "#374151" }}
    >
      {FOOTER_TEXT}
    </p>
  );
}
