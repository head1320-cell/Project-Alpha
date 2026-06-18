/**
 * Backend API base URL — deployment-agnostic resolver.
 * ==========================================================================
 * Single source of truth for "where do API calls go?". Every client/lib that
 * talks to the FastAPI backend imports `API_BASE` from here.
 *
 * Precedence:
 *  1. NEXT_PUBLIC_API_URL / NEXT_PUBLIC_API_BASE — explicit absolute override,
 *     baked at build time. Use ONLY when you deliberately point the browser
 *     straight at the backend (e.g. a separate API domain like
 *     https://api.example.com). The literal default "http://localhost:8000"
 *     is treated as "unset" so a misconfigured build falls through to (2).
 *  2. Same-origin proxy "/api/backend" (browser) — the default and the robust
 *     choice for any real deployment. The browser calls the Next.js server on
 *     its OWN origin; `next.config.js` rewrites forward "/api/backend/*" to the
 *     backend via the server-side BACKEND_URL. No IP/domain baking, no CORS, no
 *     need to expose backend :8000 publicly, no http/https mixed-content. Works
 *     identically on localhost, a GCP IP, or a custom domain.
 *  3. BACKEND_URL (server) — for SSR / server components, where a relative URL
 *     has no host. Calls the backend directly over the internal network.
 *
 * Why this matters: NEXT_PUBLIC_* vars are inlined at BUILD time. A GCP build
 * that forgot to pass NEXT_PUBLIC_API_URL used to bake "http://localhost:8000",
 * so every browser request hit the user's own machine and silently failed.
 */

const SENTINEL = "http://localhost:8000";

function resolveApiBase(): string {
  // NEXT_PUBLIC_* must be referenced literally so Next can inline them.
  const raw = process.env.NEXT_PUBLIC_API_URL ?? process.env.NEXT_PUBLIC_API_BASE;
  const explicit = raw?.trim();
  if (explicit && explicit !== SENTINEL) {
    return explicit.replace(/\/+$/, "");
  }
  if (typeof window !== "undefined") {
    // Browser → same-origin proxy (handled by next.config.js rewrites).
    return "/api/backend";
  }
  // Server-side (SSR / server components) → reach the backend directly.
  return (process.env.BACKEND_URL || SENTINEL).replace(/\/+$/, "");
}

export const API_BASE: string = resolveApiBase();
