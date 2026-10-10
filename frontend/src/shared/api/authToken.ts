/**
 * shared/api/authToken — 토큰 보관 ★한 곳★ (AC7)
 * ==========================================================================
 * 백엔드 P-1 이 돈·PII 라우트를 `Authorization: Bearer` 로 잠갔다. 프런트가 토큰을
 * 여기저기서 읽고 쓰면 로그아웃이 반쯤만 되는 상태가 생기므로 보관·삭제를 한 곳에 둔다.
 *
 * ★보관 위치의 한계를 알고 고른다★ — `localStorage` 는 XSS 로 읽힌다. HttpOnly 쿠키는
 * 그 위험이 없지만 CSRF 표면과 서버측 세션 저장소를 부르고, 사용자가 헤더 방식을 택했다.
 * 즉 이것은 **모르고 고른 것이 아니라 아는 채로 고른 절충**이고, 그 사실을 여기 적는다.
 *
 * ★`localStorage` 접근이 던질 수 있다★ — 사생활 보호 창·차단된 사이트 데이터·SSR
 * (window 없음). 전부 try/catch 로 감싸고 실패는 "토큰 없음" 으로 읽는다(로그인 화면으로
 * 보내면 될 뿐, 화면이 깨지지는 않는다).
 */

const STORAGE_KEY = "project-alpha.auth-token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
  } catch {
    /* 저장할 수 없어도 이번 세션은 동작한다 — 조용히 실패하되 지어내지 않는다. */
  }
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* 지울 수 없으면 만료가 대신 처리한다(TTL 12시간). */
  }
}

/**
 * 요청 헤더에 얹을 인증 조각. ★토큰이 없으면 빈 객체★ — 공개 라우트는 헤더 없이
 * 그대로 동작해야 하므로 `Bearer null` 같은 값을 만들지 않는다.
 */
export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** 401 을 사람이 읽을 수 있는 한 문장으로. 화면마다 다른 말을 하지 않도록 한 곳에 둔다. */
export const UNAUTHORIZED_MESSAGE =
  "로그인이 필요해요 — 이 화면은 계좌·주문을 다루므로 인증된 사용자만 볼 수 있어요.";
