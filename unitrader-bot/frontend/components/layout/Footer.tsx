import RiskWarning from "./RiskWarning";

export default function Footer() {
  return (
    <footer
      className="border-t px-4 py-12 sm:px-6"
      style={{ backgroundColor: "#080a0f", borderColor: "rgba(255,255,255,0.05)" }}
    >
      <div className="mx-auto max-w-4xl space-y-8">
        {/* Links row */}
        <div className="flex flex-wrap items-center justify-center gap-6 text-sm text-gray-500">
          <a href="/privacy" className="transition hover:text-white">Privacy Policy</a>
          <span className="text-gray-700">|</span>
          <a href="/terms" className="transition hover:text-white">Terms of Service</a>
          <span className="text-gray-700">|</span>
          <a href="/risk" className="transition hover:text-white">Risk Disclosure</a>
          <span className="text-gray-700">|</span>
          <a href="/contact" className="transition hover:text-white">Support</a>
        </div>

        {/* Company row */}
        <div className="text-center text-xs leading-relaxed text-gray-600">
          <p>Unitrader Ltd — Registered in England and Wales</p>
          <p className="mt-1">
            <a href="mailto:support@unitrader.ai" className="text-gray-500 transition hover:text-white">
              support@unitrader.ai
            </a>
          </p>
        </div>

        {/* Risk warning */}
        <div className="text-center">
          <RiskWarning variant="footer" />
        </div>

        {/* Bottom strip */}
        <div
          className="rounded-lg px-4 py-3 text-center text-xs leading-relaxed"
          style={{ backgroundColor: "#0d1018", color: "#4b5563" }}
        >
          Unitrader is a software tool. We are not a financial broker, investment
          advisor, or FCA regulated firm. Your funds are held in your own exchange
          account at all times.
        </div>

        {/* Copyright */}
        <p className="text-center text-xs text-gray-700">
          &copy; {new Date().getFullYear()} Unitrader
        </p>
      </div>
    </footer>
  );
}
