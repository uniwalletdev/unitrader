"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("App Router global error", error);
  }, [error]);

  return (
    <html lang="en">
      <body>
        <div className="min-h-screen bg-dark-950 flex items-center justify-center px-6 py-12">
          <div className="w-full max-w-3xl rounded-2xl border border-red-500/20 bg-red-500/[0.04] p-6">
            <h1 className="text-lg font-semibold text-red-200 mb-2">
              Application error (App Router)
            </h1>
            <p className="text-sm text-red-300 mb-4 break-words">
              {error?.message || "A client-side exception has occurred."}
            </p>
            <pre className="max-h-[520px] overflow-auto rounded-xl border border-red-500/10 bg-black/30 p-4 text-xs text-red-200/80 whitespace-pre-wrap">
              {(error?.stack || "").split("\n").slice(0, 18).join("\n")}
            </pre>
            {error?.digest ? (
              <p className="mt-3 text-[11px] text-red-200/60">digest: {error.digest}</p>
            ) : null}
            <div className="mt-5 flex gap-3">
              <button type="button" className="btn-primary" onClick={() => reset()}>
                Retry
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => window.location.reload()}
              >
                Reload
              </button>
            </div>
          </div>
        </div>
      </body>
    </html>
  );
}

