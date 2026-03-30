import type { ReactNode } from "react";
import React from "react";

type ErrorBoundaryState =
  | { hasError: false }
  | { hasError: true; message: string; stack?: string };

export default class ErrorBoundary extends React.Component<
  { children: ReactNode },
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(err: unknown): ErrorBoundaryState {
    if (err instanceof Error) {
      return { hasError: true, message: err.message, stack: err.stack };
    }
    return { hasError: true, message: String(err) };
  }

  componentDidCatch(err: unknown) {
    // Keep this to console so it’s visible in Vercel logs / browser console.
    // Do NOT send secrets; error objects may include request details.
    // eslint-disable-next-line no-console
    console.error("Client-side exception", err);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="min-h-screen bg-dark-950 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-2xl rounded-2xl border border-red-500/20 bg-red-500/[0.04] p-6">
          <h1 className="text-lg font-semibold text-red-200 mb-2">
            Application error (client-side)
          </h1>
          <p className="text-sm text-red-300 mb-4 break-words">
            {this.state.message}
          </p>
          {this.state.stack ? (
            <pre className="max-h-[420px] overflow-auto rounded-xl border border-red-500/10 bg-black/30 p-4 text-xs text-red-200/80 whitespace-pre-wrap">
              {this.state.stack}
            </pre>
          ) : null}
          <div className="mt-5 flex gap-3">
            <button
              type="button"
              className="btn-primary"
              onClick={() => window.location.reload()}
            >
              Reload
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => this.setState({ hasError: false })}
            >
              Try continue
            </button>
          </div>
        </div>
      </div>
    );
  }
}

