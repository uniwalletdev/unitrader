/**
 * Claim page — lets a chat-only (provisional) user upgrade to a full web account.
 *
 * Flow:
 *   1. User arrives from a link like /claim/abc123 (token from bot)
 *   2. They sign up / sign in via Clerk
 *   3. We POST /api/auth/claim with { claim_token, clerk_token }
 *   4. Backend merges data → returns JWT → redirect to /app
 */
import { useAuth, SignUp } from "@clerk/nextjs";
import { useRouter } from "next/router";
import Head from "next/head";
import { useState, useEffect } from "react";
import { authApi } from "@/lib/api";
import GalaxyLoader from "@/components/layout/GalaxyLoader";

export default function ClaimPage() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const router = useRouter();
  const { token } = router.query; // claim token from URL
  const [error, setError] = useState("");
  const [claiming, setClaiming] = useState(false);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !token || claiming) return;

    const doClaim = async () => {
      setClaiming(true);
      try {
        const clerkToken = await getToken();
        if (!clerkToken) {
          setError("Could not get auth token. Please sign in again.");
          return;
        }
        const res = await authApi.claim(String(token), clerkToken);
        localStorage.setItem("access_token", res.data.access_token);
        router.replace("/app");
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        setError(msg || "Could not claim account. The link may have expired.");
      } finally {
        setClaiming(false);
      }
    };

    doClaim();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn, token]);

  if (!isLoaded) {
    return (
      <div className="min-h-screen bg-dark-950 flex items-center justify-center">
        <GalaxyLoader size={72} label="Loading…" />
      </div>
    );
  }

  // Show error state
  if (error) {
    return (
      <>
        <Head>
          <title>Claim Account — Unitrader</title>
          <link rel="icon" type="image/png" href="/logo-galaxy.png" />
        </Head>
        <div className="min-h-screen bg-dark-950 flex items-center justify-center px-4">
          <div className="w-full max-w-sm text-center">
            <div className="mb-5 rounded-2xl border border-red-500/20 bg-red-500/[0.04] px-5 py-5 text-sm text-red-300">
              <p className="font-semibold mb-1">Could not claim account</p>
              <p className="text-xs text-red-400">{error}</p>
            </div>
            <button onClick={() => router.push("/register")} className="btn-primary w-full">
              Sign up instead
            </button>
          </div>
        </div>
      </>
    );
  }

  // Already signed in — claiming in progress
  if (isSignedIn) {
    return (
      <div className="min-h-screen bg-dark-950 flex items-center justify-center">
        <GalaxyLoader size={72} label="Linking your account…" />
      </div>
    );
  }

  // Not signed in — show Clerk SignUp
  return (
    <>
      <Head>
        <title>Claim Account — Unitrader</title>
        <link rel="icon" type="image/png" href="/logo-galaxy.png" />
      </Head>
      <div className="min-h-screen bg-dark-950 flex flex-col items-center justify-center px-4 py-12">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-white mb-2">Upgrade to Full Access</h1>
          <p className="text-dark-400 text-sm">
            Create a web account to unlock the dashboard, exchange connections, and more.
            All your chat history and settings will carry over.
          </p>
        </div>
        <SignUp
          routing="hash"
          afterSignUpUrl={`/claim/${token}`}
          afterSignInUrl={`/claim/${token}`}
        />
      </div>
    </>
  );
}
