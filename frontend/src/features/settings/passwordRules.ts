/**
 * 새 비밀번호 규칙 (BS1) — 서버 `src/domain/password_policy.py` 와 같은 규칙을 입력하는 동안 미리 보인다.
 * ==========================================================================
 * ★판정은 서버가 한다★ — 여기 규칙은 안내일 뿐이고, 서버가 거절하면 그 사유를 그대로 보인다.
 * 알려진 기본값 목록이 두 곳에서 같은지는 `tests/test_account_security_frontend.py` 가 본다.
 */
export const MIN_LENGTH = 8;
export const MAX_BYTES = 72;
export const KNOWN_DEFAULTS = ["frm123!", "temp", "changeme"];

export type Rule = { id: "length" | "bytes" | "differs" | "username" | "known" | "confirm"; text: string; ok: boolean };

const bytes = (s: string) => new TextEncoder().encode(s).length;

export function passwordRules(next: string, opts: { current: string; username: string; confirm: string }): Rule[] {
  const low = next.trim().toLowerCase();
  return [
    { id: "length", text: `${MIN_LENGTH}자 이상`, ok: next.length >= MIN_LENGTH },
    { id: "bytes", text: `${MAX_BYTES}바이트 이하`, ok: next.length > 0 && bytes(next) <= MAX_BYTES },
    { id: "differs", text: "지금 비밀번호와 다름", ok: next.length > 0 && next !== opts.current },
    { id: "username", text: "아이디와 다름", ok: next.length > 0 && low !== opts.username.trim().toLowerCase() },
    { id: "known", text: "알려진 기본 비밀번호 아님", ok: next.length > 0 && !KNOWN_DEFAULTS.includes(low) },
    { id: "confirm", text: "확인 칸과 같음", ok: next.length > 0 && next === opts.confirm },
  ];
}
