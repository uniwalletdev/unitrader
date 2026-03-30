import { SignUp } from "@clerk/nextjs";
import Head from "next/head";
import Link from "next/link";
import { useEffect } from "react";

export default function RegisterPage() {
  useEffect(() => {
    // #region agent log
    fetch("http://127.0.0.1:7831/ingest/2858cb77-c539-428f-882e-63cb43d8ab6e", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Debug-Session-Id": "026d4d",
      },
      body: JSON.stringify({
        sessionId: "026d4d",
        runId: "pre-fix",
        hypothesisId: "H3",
        location: "pages/register/[[...index]].tsx:useEffect(mount)",
        message: "register page mounted",
        data: {
          pathname:
            typeof window !== "undefined" ? window.location.pathname : "no-window",
          afterSignUpUrl: "/onboarding",
        },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion
  }, []);

  return (
    <>
      <Head>
        <title>Create Account — Unitrader</title>
      </Head>

      <div className="min-h-screen bg-dark-950 flex flex-col items-center justify-center px-4">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 mb-8">
          <div className="w-9 h-9 rounded-xl bg-brand-600 flex items-center justify-center">
            <span className="text-white font-bold text-lg">U</span>
          </div>
          <span className="text-white font-bold text-xl tracking-tight">Unitrader</span>
        </Link>

        <p className="text-dark-300 text-sm mb-6 text-center max-w-sm">
          Sign up with Google or email — takes 30 seconds.
          <br />
          <span className="text-brand-400 font-medium">14-day free trial included.</span>
        </p>

        {/* Clerk handles Google, email, OTP — all in one */}
        <SignUp
          path="/register"
          routing="path"
          signInUrl="/login"
          afterSignUpUrl="/onboarding"
          appearance={{
            elements: {
              rootBox: "w-full max-w-md",
              card: "rounded-2xl border border-dark-700 shadow-2xl",
            },
          }}
        />

        <p className="mt-6 text-dark-400 text-sm">
          Already have an account?{" "}
          <Link href="/login" className="text-brand-400 hover:text-brand-300 font-medium">
            Sign in
          </Link>
        </p>

        <p className="mt-3 text-center text-[12px] text-[#6b7280]">
          By creating an account you agree to our{" "}
          <Link href="/terms" className="text-[#22c55e] hover:underline">
            Terms of Service
          </Link>{" "}
          and{" "}
          <Link href="/privacy" className="text-[#22c55e] hover:underline">
            Privacy Policy
          </Link>
          .
        </p>
      </div>
    </>
  );
}
