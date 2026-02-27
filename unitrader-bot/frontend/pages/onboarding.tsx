/**
 * Onboarding — shown after Clerk sign-up.
 * The user chooses a name for their AI before entering the dashboard.
 */
import { useAuth } from "@clerk/nextjs";
import Head from "next/head";
import { useRouter } from "next/router";
import { useState, useEffect } from "react";
import { authApi } from "@/lib/api";

export default function OnboardingPage() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const router = useRouter();

  const [aiName, setAiName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(true);
  const [userId, setUserId] = useState<string | null>(null);

  // On mount, sync Clerk session with our backend
  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      router.replace("/register");
      return;
    }

    (async () => {
      try {
        const token = await getToken();
        const res = await authApi.clerkSync(token!);

        if (res.data.status === "logged_in") {
          // User already has an AI name — go straight to dashboard
          localStorage.setItem("access_token", res.data.access_token);
          router.replace("/app");
        } else if (res.data.status === "needs_setup") {
          setUserId(res.data.user_id);
          setSyncing(false);
        }
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        setError(msg || "Sync failed. Please try refreshing.");
        setSyncing(false);
      }
    })();
  }, [isLoaded, isSignedIn, getToken, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId) return;
    setError("");

    const trimmed = aiName.trim();
    if (!/^[A-Za-z0-9_]{2,20}$/.test(trimmed)) {
      setError("2–20 characters, letters/numbers/underscores only.");
      return;
    }

    setLoading(true);
    try {
      const res = await authApi.clerkSetup(userId, trimmed);
      localStorage.setItem("access_token", res.data.access_token);
      router.replace("/app");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  if (!isLoaded || syncing) {
    return (
      <div className="min-h-screen bg-dark-950 flex items-center justify-center">
        <div className="text-center">
          <div className="w-10 h-10 border-4 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-dark-400">Setting up your account…</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <Head>
        <title>Name Your AI — Unitrader</title>
      </Head>

      <div className="min-h-screen bg-dark-950 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-md">
          {/* Logo */}
          <div className="flex items-center gap-2 mb-8 justify-center">
            <div className="w-9 h-9 rounded-xl bg-brand-600 flex items-center justify-center">
              <span className="text-white font-bold text-lg">U</span>
            </div>
            <span className="text-white font-bold text-xl tracking-tight">Unitrader</span>
          </div>

          <div className="bg-dark-800 border border-dark-700 rounded-2xl p-8 shadow-2xl text-center">
            <div className="w-16 h-16 rounded-2xl bg-brand-600/20 flex items-center justify-center mx-auto mb-5">
              <span className="text-3xl">🤖</span>
            </div>

            <h1 className="text-2xl font-bold text-white mb-2">
              Name your AI
            </h1>
            <p className="text-dark-400 text-sm mb-8">
              Give your personal trading AI a name. You&apos;ll see it throughout the dashboard.
              <br />
              <span className="text-dark-500 text-xs mt-1 block">e.g. TradeMaster, AlphaBot, Nexus</span>
            </p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <input
                type="text"
                value={aiName}
                onChange={(e) => setAiName(e.target.value)}
                placeholder="e.g. TradeMaster"
                maxLength={20}
                className="input-field text-center text-lg font-semibold tracking-wide"
                autoFocus
              />

              {error && (
                <p className="text-red-400 text-sm">{error}</p>
              )}

              <button
                type="submit"
                disabled={loading || !aiName.trim()}
                className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? "Saving…" : "Launch My AI →"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
