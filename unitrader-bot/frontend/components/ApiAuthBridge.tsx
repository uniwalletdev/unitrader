"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect } from "react";
import { authApi, setApiTokenRefreshHandler } from "@/lib/api";

/**
 * Registers Clerk-based JWT refresh for axios (see lib/api.ts TOKEN_EXPIRED handling).
 * Must render under ClerkProvider.
 */
export default function ApiAuthBridge() {
  const { getToken, isSignedIn } = useAuth();

  useEffect(() => {
    if (!isSignedIn) {
      setApiTokenRefreshHandler(null);
      return;
    }
    setApiTokenRefreshHandler(async () => {
      const clerkToken = await getToken();
      if (!clerkToken) throw new Error("Clerk session token unavailable");
      const res = await authApi.clerkSync(clerkToken);
      const next = res.data?.access_token as string | undefined;
      if (!next) throw new Error("clerk-sync did not return access_token");
      localStorage.setItem("access_token", next);
    });
    return () => setApiTokenRefreshHandler(null);
  }, [getToken, isSignedIn]);

  return null;
}
