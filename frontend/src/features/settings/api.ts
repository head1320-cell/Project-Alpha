/**
 * 설정 화면이 부르는 계정 라우트 (BS1) — 모두 `POST/GET /api/v1/auth/*`, 인증 헤더는 apiBase 가 한 곳에서 붙인다.
 * ★실패는 서버 사유 그대로★ — 사유가 없으면 상태 번호와 함께 "사유를 받지 못했어요" 라고 적는다(지어내지 않는다).
 */
import { extractErrorDetail, getWithAuth, postJson } from "@/shared/api/apiBase";

export type Result<T> = { ok: true; value: T } | { ok: false; error: string; status: number };

async function call<T>(res: Promise<Response>): Promise<Result<T>> {
  try {
    const r = await res;
    const body = await r.json().catch(() => null);
    if (!r.ok) return { ok: false, status: r.status, error: extractErrorDetail(body, `서버가 ${r.status} 로 답했어요 — 사유를 받지 못했어요.`) };
    return { ok: true, value: body as T };
  } catch {
    return { ok: false, status: 0, error: "서버에 닿지 못했어요." };
  }
}

export type Account = {
  username: string; role: string; created_at: string | null;
  must_change_password: boolean; password_changed_at: string | null;
};

export const changePassword = (current: string, next: string) =>
  call<{ access_token: string }>(postJson("/api/v1/auth/password", { current_password: current, new_password: next }));

export const listAccounts = () => call<{ users: Account[] }>(getWithAuth("/api/v1/auth/users"));

export const issueAccount = (username: string, role: string) =>
  call<{ username: string; temporary_password: string }>(postJson("/api/v1/auth/users", { username, role }));

export const resetAccount = (username: string) =>
  call<{ username: string; temporary_password: string }>(postJson(`/api/v1/auth/users/${encodeURIComponent(username)}/reset-password`, {}));

// ── 내 증권 계좌 (BV8 · 서버 BV3·BV4) — 서버가 가린 값만 돌아온다(앱 키·시크릿·전체 계좌번호 0) ──

export type BrokerAccount = {
  account_id: string; label: string; is_paper: boolean; account_prdt: string;
  app_key_last4: string; account_no_masked: string; created_at: string | null;
};

export type BrokerCheck = {
  account_id: string; state: "practice" | "ok" | "failed"; reason: string; detail?: string; checked_at: string;
};

export type BrokerConnect = {
  label: string; app_key: string; app_secret: string; account_no: string; is_paper: boolean; account_prdt: string;
};

const BROKER = "/api/v1/broker-accounts";

export const listBrokerAccounts = () => call<{ accounts: BrokerAccount[] }>(getWithAuth(BROKER));

export const connectBrokerAccount = (body: BrokerConnect) => call<BrokerAccount>(postJson(BROKER, body));

export const checkBrokerAccount = (id: string) =>
  call<BrokerCheck>(postJson(`${BROKER}/${encodeURIComponent(id)}/check`, {}));

export const deleteBrokerAccount = (id: string) =>
  call<{ deleted: string }>(getWithAuth(`${BROKER}/${encodeURIComponent(id)}`, { method: "DELETE" }));
