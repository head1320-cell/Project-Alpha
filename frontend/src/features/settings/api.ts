/**
 * 설정 화면이 부르는 계정 라우트 (BS1) — 모두 `POST/GET /api/v1/auth/*`, 인증 헤더는 apiBase 가 한 곳에서 붙인다.
 * ★실패는 서버 사유 그대로★ — 사유가 없으면 상태 번호와 함께 "사유를 받지 못했어요" 라고 적는다(지어내지 않는다).
 */
import { getWithAuth, postJson } from "@/shared/api/apiBase";
import { call } from "@/shared/api/result";

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
