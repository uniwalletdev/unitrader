import type { AppProps } from "next/app";
import { ClerkProvider } from "@clerk/nextjs";
import { useEffect } from "react";
import { StatusBar, Style } from "@capacitor/status-bar";
import "@/styles/globals.css";
import { isNative } from "@/hooks/useCapacitor";
import ErrorBoundary from "@/components/ErrorBoundary";

export default function App({ Component, pageProps }: AppProps) {
  useEffect(() => {
    if (!isNative) return;
    StatusBar.setStyle({ style: Style.Dark }).catch(() => {});
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
