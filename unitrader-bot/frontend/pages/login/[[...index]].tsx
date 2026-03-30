import { SignIn } from "@clerk/nextjs";
import Head from "next/head";
import Link from "next/link";

export default function LoginPage() {
  return (
    <>
      <Head>
        <title>Sign In — Unitrader</title>
      </Head>

      <div className="min-h-screen bg-dark-950 flex flex-col items-center justify-center px-4">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 mb-8">
          <div className="w-9 h-9 rounded-xl bg-brand-600 flex items-center justify-center">
            <span className="text-white font-bold text-lg">U</span>
          </div>
          <span className="text-white font-bold text-xl tracking-tight">Unitrader</span>
        </Link>

        {/* Clerk handles Google, email/password, 2FA — all in one */}
        <SignIn
          path="/login"
          routing="path"
          signUpUrl="/register"
          afterSignInUrl="/app"
          appearance={{
            elements: {
              rootBox: "w-full max-w-md",
              card: "rounded-2xl border border-dark-700 shadow-2xl",
            },
          }}
        />

        <p className="mt-6 text-dark-400 text-sm">
          Don&apos;t have an account?{" "}
          <Link href="/register" className="text-brand-400 hover:text-brand-300 font-medium">
            Sign up free
          </Link>
        </p>
      </div>
    </>
  );
}
