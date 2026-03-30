import type { NextPageContext } from "next";
import Head from "next/head";

type ErrorPageProps = {
  statusCode?: number;
  message?: string;
  stack?: string;
};

function safeString(x: unknown) {
  if (typeof x === "string") return x;
  if (x == null) return "";
  return String(x);
}

export default function ErrorPage({ statusCode, message, stack }: ErrorPageProps) {
  const title = statusCode ? `Error ${statusCode} — Unitrader` : "Application error — Unitrader";

  return (
    <div className="min-h-screen bg-dark-950 flex items-center justify-center px-6 py-12">
      <Head>
        <title>{title}</title>
        <meta name="robots" content="noindex,nofollow" />
        <link rel="icon" type="image/png" href="/logo-galaxy.png" />
      </Head>

      <div className="w-full max-w-3xl rounded-2xl border border-red-500/20 bg-red-500/[0.04] p-6">
        <h1 className="text-lg font-semibold text-red-200 mb-2">{title}</h1>
        <p className="text-sm text-red-300 mb-4 break-words">
          {message || "A client-side exception has occurred."}
        </p>

        {stack ? (
          <pre className="max-h-[520px] overflow-auto rounded-xl border border-red-500/10 bg-black/30 p-4 text-xs text-red-200/80 whitespace-pre-wrap">
            {stack}
          </pre>
        ) : (
          <p className="text-xs text-red-200/70">
            No stack was captured on this screen. Please check the browser console for the full stack trace.
          </p>
        )}

        <div className="mt-5 flex gap-3">
          <button
            type="button"
            className="btn-primary"
            onClick={() => window.location.reload()}
          >
            Reload
          </button>
          <a href="/" className="btn-secondary">
            Home
          </a>
        </div>
      </div>
    </div>
  );
}

ErrorPage.getInitialProps = async (ctx: NextPageContext): Promise<ErrorPageProps> => {
  const statusCode = ctx.res?.statusCode ?? ctx.err?.statusCode;
  const err = ctx.err;

  // #region agent log
  // No network posting here; this runs on server or client depending on the failure mode.
  // Keep data minimal and non-sensitive.
  // eslint-disable-next-line no-console
  console.error("Next.js _error", {
    statusCode,
    pathname: (ctx as any)?.asPath,
    message: safeString((err as any)?.message),
  });
  // #endregion

  return {
    statusCode,
    message: safeString((err as any)?.message),
    stack: safeString((err as any)?.stack),
  };
};

