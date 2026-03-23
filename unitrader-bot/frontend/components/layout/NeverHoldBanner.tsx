export default function NeverHoldBanner() {
  return (
    <div className="flex w-full items-start gap-3 rounded-xl border-l-4 border-brand-500 bg-brand-500/[0.05] px-4 py-3">
      {/* Green checkmark */}
      <svg
        width={14}
        height={14}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="mt-0.5 shrink-0 text-brand-400"
      >
        <path d="M20 6 9 17l-5-5" />
      </svg>
      <p className="text-[11px] leading-relaxed text-brand-300">
        Unitrader never holds your money. All trades execute through your own exchange
        account. Your funds stay with you — Unitrader only places the orders.
      </p>
    </div>
  );
}
