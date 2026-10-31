/**
 * 로그인 뒤 돌아갈 곳(`?next=`) — BU8b.
 * ★이 앱 안의 경로만 받는다★ `/` 로 시작하고 `//`·`/\`(브라우저가 다른 호스트로 읽는다)·제어 문자가 없을 때만.
 * 바깥 주소로 보내는 열린 리다이렉트를 만들지 않는다 — 아니면 `null`(부르는 쪽이 홈으로 보낸다).
 */
export function safeNext(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return null;
  if (/[\u0000-\u001f\u007f]/.test(raw)) return null;
  return raw;
}

/** 지금 화면으로 돌아오는 로그인 주소. 로그인 화면·첫 화면에서는 `next` 를 붙이지 않는다(돌아올 이유가 없다). */
export function loginHref(path: string | null | undefined): string {
  const p = safeNext(path ?? null);
  return p && p !== "/" && !p.startsWith("/login") ? `/login?next=${encodeURIComponent(p)}` : "/login";
}
