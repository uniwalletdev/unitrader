import type { AppProps } from "next/app";
import { ClerkProvider } from "@clerk/nextjs";
import { useEffect } from "react";
import { StatusBar, Style } from "@capacitor/status-bar";
import "@/styles/globals.css";
import { isNative, platform } from "@/hooks/useCapacitor";
import ErrorBoundary from "@/components/ErrorBoundary";

export default function App({ Component, pageProps }: AppProps) {
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
        hypothesisId: "H1",
        location: "pages/_app.tsx:useEffect(mount)",
        message: "app mounted",
        data: {
          pathname:
            typeof window !== "undefined" ? window.location.pathname : "no-window",
          publishableKeyPresent: Boolean(
            process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
          ),
          isNative,
          platform,
        },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion

    // #region agent log
    const onError = (event: ErrorEvent) => {
      fetch("http://127.0.0.1:7831/ingest/2858cb77-c539-428f-882e-63cb43d8ab6e", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Debug-Session-Id": "026d4d",
        },
        body: JSON.stringify({
          sessionId: "026d4d",
          runId: "pre-fix",
          hypothesisId: "H2",
          location: "pages/_app.tsx:window.error",
          message: "window error event",
          data: {
            message: event.message,
            filename: event.filename,
            lineno: event.lineno,
            colno: event.colno,
          },
          timestamp: Date.now(),
        }),
      }).catch(() => {});
    };
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      const reason =
        event.reason instanceof Error
          ? { name: event.reason.name, message: event.reason.message }
          : { message: String(event.reason) };
      fetch("http://127.0.0.1:7831/ingest/2858cb77-c539-428f-882e-63cb43d8ab6e", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Debug-Session-Id": "026d4d",
        },
        body: JSON.stringify({
          sessionId: "026d4d",
          runId: "pre-fix",
          hypothesisId: "H2",
          location: "pages/_app.tsx:unhandledrejection",
          message: "unhandled rejection",
          data: reason,
          timestamp: Date.now(),
        }),
      }).catch(() => {});
    };
    if (typeof window !== "undefined") {
      window.addEventListener("error", onError);
      window.addEventListener("unhandledrejection", onUnhandledRejection);
    }
    // #endregion

    if (!isNative) return;
    StatusBar.setStyle({ style: Style.Dark }).catch(() => {});

    return () => {
      if (typeof window !== "undefined") {
        window.removeEventListener("error", onError);
        window.removeEventListener("unhandledrejection", onUnhandledRejection);
      }
    };
  }, []);

  return (
    <ClerkProvider
      publishableKey={process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY!}
      appearance={{
        variables: {
          colorPrimary: "#7c3aed",
          colorBackground: "#0d1117",
          colorInputBackground: "#161b22",
          colorInputText: "#e6edf3",
          colorText: "#e6edf3",
          colorTextSecondary: "#8b949e",
          borderRadius: "0.75rem",
        },
        elements: {
          card: "bg-dark-800 border border-dark-700 shadow-2xl",
          headerTitle: "text-white font-bold",
          headerSubtitle: "text-dark-300",
          formButtonPrimary:
            "bg-brand-600 hover:bg-brand-500 text-white font-semibold transition-colors",
          footerActionLink: "text-brand-400 hover:text-brand-300",
          identityPreviewText: "text-white",
          identityPreviewEditButton: "text-brand-400",
        },
      }}
    >
      <ErrorBoundary>
        <Component {...pageProps} />
      </ErrorBoundary>
    </ClerkProvider>
  );
}
