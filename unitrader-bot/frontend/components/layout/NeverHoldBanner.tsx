export default function NeverHoldBanner() {
  return (
    <div
      className="flex w-full items-start gap-3 rounded-xl px-4 py-3"
      style={{
        borderLeft: "4px solid #22c55e",
        backgroundColor: "rgba(34,197,94,0.05)",
      }}
    >
      {/* Green checkmark */}
      <svg
        width={14}
        height={14}
        viewBox="0 0 24 24"
        fill="none"
        stroke="#22c55e"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="mt-0.5 shrink-0"
      >
        <path d="M20 6 9 17l-5-5" />
      </svg>
      <p style={{ fontSize: 11, color: "#86efac", lineHeight: 1.6 }}>
        Apex never holds your money. All trades execute through your own exchange
        account. Your funds stay with you — Apex only places the orders.
      </p>
    </div>
  );
}
