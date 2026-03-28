import { useState } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import { CheckCircle2, AlertCircle, Loader } from "lucide-react";
import { authApi } from "@/lib/api";
import { devLogError } from "@/lib/devLog";

const DISCLOSURES = [
  "I understand that trading involves risk of loss, and I could lose some or all of my invested capital.",
  "I understand that Unitrader is an AI tool, not a regulated financial advisor. Past performance does not guarantee future results.",
  "I understand that Unitrader never holds my funds — I trade through my own exchange account.",
];

export default function RiskDisclosurePage() {
  const router = useRouter();
  const [checkedItems, setCheckedItems] = useState([false, false, false]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allChecked = checkedItems.every((item) => item);

  const handleCheck = (index: number) => {
    const newChecked = [...checkedItems];
    newChecked[index] = !newChecked[index];
    setCheckedItems(newChecked);
  };

  const handleAccept = async () => {
    if (!allChecked) return;

    setLoading(true);
    setError(null);

    try {
      await authApi.acceptRiskDisclosure();
      // Redirect to trade page with welcome flag
      router.push("/trade?welcome=true");
    } catch (err: unknown) {
      devLogError("Risk disclosure error", err);
      setError("Something went wrong — please try again");
      setLoading(false);
    }
  };

  return (
    <>
      <Head>
        <title>Risk Disclosure - Unitrader Trading</title>
      </Head>

      <div className="min-h-screen flex items-center justify-center bg-dark-950 px-4 py-8">
        <div className="w-full max-w-2xl">
          {/* Unitrader Avatar */}
          <div className="flex justify-center mb-8">
            <div className="relative w-24 h-24 rounded-full bg-gradient-to-br from-brand-500 to-brand-600 flex items-center justify-center shadow-lg">
              <svg
                className="w-12 h-12 text-white"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
          </div>

          {/* Heading */}
          <h1 className="text-3xl md:text-4xl font-bold text-white text-center mb-3">
            Before Unitrader trades with real money
          </h1>

          <p className="text-base md:text-lg text-dark-400 text-center mb-12">
            We want to make sure you understand what you're signing up for.
          </p>

          {/* Disclosure Items */}
          <div className="space-y-4 mb-8">
            {DISCLOSURES.map((disclosure, index) => (
              <button
                key={index}
                onClick={() => handleCheck(index)}
                className="w-full flex items-start gap-4 p-4 rounded-lg border-2 border-dark-800 bg-dark-900 hover:border-dark-700 transition-all duration-200 text-left group"
              >
                {/* Checkbox */}
                <div className="flex-shrink-0 mt-0.5">
                  <div
                    className={`w-6 h-6 rounded border-2 flex items-center justify-center transition-all duration-200 ${
                      checkedItems[index]
                        ? "bg-brand-500 border-brand-500"
                        : "border-dark-600 bg-dark-800 group-hover:border-dark-500"
                    }`}
                  >
                    {checkedItems[index] && (
                      <CheckCircle2 className="w-5 h-5 text-white" strokeWidth={3} />
                    )}
                  </div>
                </div>

                {/* Text */}
                <p
                  className={`text-sm md:text-base leading-relaxed transition-colors ${
                    checkedItems[index]
                      ? "text-white font-medium"
                      : "text-dark-400 group-hover:text-dark-300"
                  }`}
                >
                  {disclosure}
                </p>
              </button>
            ))}
          </div>

          {/* Error Message */}
          {error && (
            <div className="mb-6 flex items-start gap-3 rounded-lg bg-red-500/10 border border-red-500/30 p-4">
              <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          {/* Action Button */}
          <button
            onClick={handleAccept}
            disabled={!allChecked || loading}
            className={`w-full py-3 md:py-4 rounded-lg font-semibold text-base md:text-lg transition-all duration-200 flex items-center justify-center gap-2 ${
              allChecked && !loading
                ? "bg-brand-500 text-white hover:bg-brand-600 active:scale-95 cursor-pointer"
                : "bg-dark-800 text-dark-500 cursor-not-allowed"
            }`}
          >
            {loading && <Loader className="w-5 h-5 animate-spin" />}
            {loading ? "Accepting..." : "I understand, let's start"}
          </button>

          {/* Info Text */}
          <p className="text-xs text-dark-500 text-center mt-6">
            By clicking the button above, you acknowledge and accept the risks
            described. Unitrader is not responsible for trading losses.
          </p>

          {/* Small Print */}
          <div className="mt-12 pt-8 border-t border-dark-800">
            <p className="text-center text-xs leading-relaxed text-dark-600">
              Unitrader operates as a software tool, not a financial broker.
              <br />
              Your funds remain in your own exchange account at all times.
              <br />
              For support:{" "}
              <a
                href="mailto:support@unitrader.ai"
                className="text-brand-500 hover:text-brand-400 transition-colors"
              >
                support@unitrader.ai
              </a>
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
