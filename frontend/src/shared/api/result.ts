/**
 * 서버 호출 결과 — 성공 값 또는 사람이 읽을 실패 사유 (BS1 설정 화면에서 BV9 때 내렸다 — 설정·내 계좌가 함께 쓴다).
 * ★실패는 서버 사유 그대로★ — 사유가 없으면 상태 번호와 함께 "사유를 받지 못했어요" 라고 적는다(지어내지 않는다).
 * `status` 0 은 서버에 닿지 못한 것(네트워크) — 서버가 답한 실패와 가른다.
 */
import { extractErrorDetail } from "./apiBase";

export type Result<T> = { ok: true; value: T } | { ok: false; error: string; status: number };

export async function call<T>(res: Promise<Response>): Promise<Result<T>> {
  try {
    const r = await res;
    const body = await r.json().catch(() => null);
    if (!r.ok) return { ok: false, status: r.status, error: extractErrorDetail(body, `서버가 ${r.status} 로 답했어요 — 사유를 받지 못했어요.`) };
    return { ok: true, value: body as T };
  } catch {
    return { ok: false, status: 0, error: "서버에 닿지 못했어요." };
  }
}
