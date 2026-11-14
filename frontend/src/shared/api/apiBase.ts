/**
 * 백엔드 API 주소 — "API 호출이 어디로 가는가"의 한 자리. 백엔드를 부르는 모든 코드가 여기의 `API_BASE` 를 쓴다.
 * ==========================================================================
 *  · 브라우저: 늘 같은 출처의 런타임 프록시 `/api/backend`. Next 서버의 라우트 핸들러
 *    (`src/app/api/backend/[...path]/route.ts`)가 ★요청마다★ 서버 환경변수 `BACKEND_URL` 을 읽어 넘긴다.
 *    주소를 번들에 박지 않으므로 같은 이미지가 localhost · IP · 도메인 어디서든 그대로 돈다(CORS·:8000 공개·mixed-content 없음).
 *  · 서버(SSR·서버 컴포넌트): 상대 주소에는 호스트가 없으므로 `BACKEND_URL` 로 백엔드를 직접 부른다.
 *
 * ★API 주소를 빌드 타임에 박지 않는다★(CLAUDE.md §6) — `NEXT_PUBLIC_*` 는 `next build` 때 번들에 글자로 박힌다.
 * 2026-11-13 까지 여기에 "별도 API 도메인을 쓸 때만"이라는 `NEXT_PUBLIC_API_URL` override 가 있었고, 빌드에서 값을
 * 빠뜨리면 브라우저가 사용자의 `localhost:8000` 을 불렀다. 걷어 냈다 — 다른 도메인의 백엔드는 `BACKEND_URL` 로 준다
 * (프록시가 서버에서 넘긴다). `tests/test_no_build_time_api_address.py` 가 정적으로 건다.
 */

import { authHeaders } from "@/shared/api/authToken";

/** 서버 쪽 기본값 — `BACKEND_URL` 이 없을 때(로컬 개발). */
const LOCAL_BACKEND = "http://localhost:8000";

function resolveApiBase(): string {
  if (typeof window !== "undefined") return "/api/backend";          // 브라우저 → 같은 출처 런타임 프록시
  return (process.env.BACKEND_URL || LOCAL_BACKEND).replace(/\/+$/, "");   // 서버 → 백엔드 직접
}

export const API_BASE: string = resolveApiBase();

// FastAPI 에러 응답의 detail을 사람이 읽을 수 있는 문자열로 변환.
// 보통은 string이지만, Pydantic 422 검증 실패는 detail이 [{loc,msg,type}, ...] 배열로 옴 —
// 이를 그대로 new Error()에 넣으면 "[object Object]"로 뭉개지므로 여기서 join.
export function extractErrorDetail(err: unknown, fallback: string): string {
  const detail = (err as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  // 사유를 갖춘 객체(예: 유통 관문 `{code, reason, missing}`) — 사유 문장을 그대로.
  const reason = (detail as { reason?: unknown } | null)?.reason;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && typeof reason === "string" && reason) return reason;
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

/** JSON POST 단축 — 응답 파싱/에러 처리는 호출자 책임(기존 동작 유지).
 *  ★인증 헤더는 여기서 한 번만 붙인다★(AC7) — 토큰이 없으면 아무것도 붙지 않으므로
 *  공개 라우트는 이전과 똑같이 동작한다. */
export const postJson = (path: string, body: unknown, headers?: Record<string, string>) =>
  fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers, ...authHeaders() },
    body: JSON.stringify(body),
  });

/** GET 단축 — 위와 같은 이유로 인증 헤더를 한 곳에서 얹는다. */
export const getWithAuth = (path: string, init?: RequestInit) =>
  fetch(`${API_BASE}${path}`, { ...init, headers: { ...init?.headers, ...authHeaders() } });
