/**
 * 고객이 여는 경로 — `/api/v1/share/*` (서버 CF 3부 PB6 · ★유통 관문 뒤★ · 고객 계정 없음).
 * ==========================================================================
 * 주소 토큰 + PIN → 30분 세션(`X-Share-Session` 머리글) → 한 장 · 묻기. ★PB 의 로그인 토큰을 싣지 않는다★ — 같은 브라우저에서
 * PB 가 로그인해 있어도 고객 경로에는 보내지 않는다(그래서 `postJson`·`getWithAuth` 를 쓰지 않는다).
 * 상태 번호가 뜻을 갖는다: 401 주소·PIN·세션이 맞지 않음 · 403 관문 닫힘 · 410 끝난 주소 · 423 잠김.
 */
import { API_BASE } from "@/shared/api/apiBase";
import { call } from "@/shared/api/result";
import type { Sheet, SheetAnswer } from "./api";

const SHARE = "/api/v1/share";
const JSON_HEAD = { "Content-Type": "application/json" };

export const openShare = (token: string, pin: string) =>
  call<{ session: string; expires_at: string }>(fetch(`${API_BASE}${SHARE}/open`, {
    method: "POST", headers: JSON_HEAD, body: JSON.stringify({ token, pin }), referrerPolicy: "no-referrer",
  }));
export const readShared = (session: string) =>
  call<{ sheet_id: string; sheet: Sheet; link_expires_at: string | null }>(fetch(`${API_BASE}${SHARE}/sheet`, {
    headers: { "X-Share-Session": session }, referrerPolicy: "no-referrer",
  }));
export const askShared = (session: string, question: string, previous: { question: string; answer: string } | null) =>
  call<SheetAnswer>(fetch(`${API_BASE}${SHARE}/ask`, {
    method: "POST", headers: { ...JSON_HEAD, "X-Share-Session": session },
    body: JSON.stringify({ question, ...(previous ? { previous } : {}) }), referrerPolicy: "no-referrer",
  }));
