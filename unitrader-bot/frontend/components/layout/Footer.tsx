export default function Footer() {
  return (
    <footer className="border-t border-dark-800/50 bg-dark-950 px-4 py-12 sm:px-6">
      <div className="mx-auto max-w-4xl space-y-8">
        {/* Links row */}
        <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-[12px] text-[#6b7280]">
          <a href="/privacy" className="transition hover:text-[#9ca3af]">Privacy Policy</a>
          <a href="/terms" className="transition hover:text-[#9ca3af]">Terms of Service</a>
          <a href="/risk" className="transition hover:text-[#9ca3af]">Risk Disclosure</a>
          <a href="/support" className="transition hover:text-[#9ca3af]">Support</a>
        </div>

        {/* Risk warning */}
        <div
          style={{
            fontSize: "10px",
            color: "#374151",
            textAlign: "center",
            maxWidth: "680px",
            margin: "0 auto",
            lineHeight: 1.7,
          }}
        >
          Trading involves significant risk of loss and is not suitable for all investors. Your
          capital is at risk. Past performance does not guarantee future results. Unitrader is a
          software tool operated by Universal Wallet Ltd. We are not regulated by the Financial
          Conduct Authority (FCA). Your funds are held in your own exchange account at all times —
          Universal Wallet Ltd never holds your money.
        </div>

        {/* Company row */}
        <div className="text-center leading-relaxed" style={{ fontSize: "11px", color: "#374151" }}>
          <p>Universal Wallet Ltd — 128 City Road, London, EC1V 2NX</p>
          <p className="mt-1">Company No. 16695347 | ICO Reg: ZC068643</p>
        </div>

        {/* Copyright */}
        <p className="text-center text-xs text-dark-700">
          &copy; {new Date().getFullYear()} Universal Wallet Ltd
        </p>
      </div>
    </footer>
  );
}
