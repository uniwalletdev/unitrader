import type { ReactNode } from "react";
import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import ApiAuthBridge from "@/components/ApiAuthBridge";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "Unitrader — Your Personal AI Trader",
  icons: {
    icon: "/logo-galaxy.png",
    apple: "/logo-galaxy.png",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ClerkProvider
          publishableKey={process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}
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
          <ApiAuthBridge />
          {children}
        </ClerkProvider>
      </body>
    </html>
  );
}

