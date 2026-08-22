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

// FastAPI 에러 응답의 detail을 사람이 읽을 수 있는 문자열로 변환.
// 보통은 string이지만, Pydantic 422 검증 실패는 detail이 [{loc,msg,type}, ...] 배열로 옴 —
// 이를 그대로 new Error()에 넣으면 "[object Object]"로 뭉개지므로 여기서 join.
export function extractErrorDetail(err: unknown, fallback: string): string {
  const detail = (err as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => {
        if (d && typeof d === "object") {
          const loc = Array.isArray((d as { loc?: unknown[] }).loc) ? (d as { loc: unknown[] }).loc.join(".") : "";
          const msg = (d as { msg?: string }).msg ?? JSON.stringify(d);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(d);
      })
      .join("; ");
  }
  return fallback;
}

/** JSON POST 단축 — 응답 파싱/에러 처리는 호출자 책임(기존 동작 유지). */
export const postJson = (path: string, body: unknown) =>
  fetch(`${API_BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
