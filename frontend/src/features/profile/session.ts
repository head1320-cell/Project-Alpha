"use client";
/**
 * 지금 누구로 로그인했나 (BR R3) — `GET /api/v1/auth/me` 를 읽기만 한다.
 * ==========================================================================
 * ★모름 ≠ 로그아웃★ 네 상태를 가른다:
 *  · 토큰 없음 → 로그인 안 됨(서버를 부르지 않는다)
 *  · 200 → 서버가 준 이름·역할 그대로
 *  · 401 → 토큰이 끝났다: 토큰을 지우고 "로그인이 끝났어요"
 *  · 그 밖(네트워크·5xx·빈 응답) → "확인하지 못했어요" — 토큰을 지우지 않고 이름을 지어내지 않는다
 * 로그아웃은 토큰을 지우는 것이다(JWT — 서버 세션이 없다).
 */
import { useCallback, useEffect, useState } from "react";
import { getWithAuth } from "@/shared/api/apiBase";
import { clearToken, getToken } from "@/shared/api/authToken";

export type Session =
  | { kind: "loading" }
  | { kind: "signed_out"; note: string | null }
  | { kind: "signed_in"; username: string; role: string }
  | { kind: "unknown"; reason: string };

/** 서버 역할 어휘(`src/domain/auth_identity.py` ROLES) → 쉬운 이름. 어휘 밖이면 서버 값 그대로 보인다. */
export const ROLE_KO: Record<string, string> = { admin: "관리자", analyst: "분석가" };

export function useSession() {
  const [session, setSession] = useState<Session>({ kind: "loading" });
  const check = useCallback(async () => {
    if (!getToken()) { setSession({ kind: "signed_out", note: null }); return; }
    setSession({ kind: "loading" });
    try {
      const r = await getWithAuth("/api/v1/auth/me");
      if (r.status === 401) {
        clearToken();
        setSession({ kind: "signed_out", note: "로그인이 끝났어요 — 다시 로그인해 주세요." });
        return;
      }
      if (!r.ok) { setSession({ kind: "unknown", reason: `서버가 ${r.status} 오류로 답했어요.` }); return; }
      const p = ((await r.json()) as { principal?: { username?: unknown; role?: unknown } })?.principal;
      if (!p || typeof p.username !== "string" || !p.username.trim()) {
        setSession({ kind: "unknown", reason: "서버 응답에 사용자 이름이 없어요." });
        return;
      }
      setSession({ kind: "signed_in", username: p.username, role: typeof p.role === "string" ? p.role : "" });
    } catch {
      setSession({ kind: "unknown", reason: "서버에 닿지 못했어요." });
    }
  }, []);
  useEffect(() => { void check(); }, [check]);
  const logout = useCallback(() => {
    clearToken();
    setSession({ kind: "signed_out", note: "로그아웃했어요." });
  }, []);
  return { session, retry: check, logout };
}
