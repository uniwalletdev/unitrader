/**
 * Clerk middleware — minimal passthrough.
 *
 * We let the page components handle authentication themselves using
 * useAuth() hooks, so we only need Clerk to initialise its context here.
 * No routes are blocked server-side; the client-side redirects in
 * app.tsx and onboarding.tsx take care of unauthenticated access.
 */
import { clerkMiddleware } from "@clerk/nextjs/server";

// Run Clerk on every request so the session is available, but don't
// block any routes — pages do their own auth checks.
export default clerkMiddleware();

export const config = {
  matcher: [
    // Skip Next.js internals and static files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
