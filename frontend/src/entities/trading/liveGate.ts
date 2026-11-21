/**
 * 실계좌(LIVE) 관문 — `/api/v1/admin/live-gate` (서버 BV7 · 관리자만).
 * ==========================================================================
 * 운영자가 "무슨 근거로·누구에게" 실계좌를 여는지 선언하고 거둔다. 판정은 서버(`src/domain/live_gate.py`)가 한다 —
 * 화면은 칸을 모아 보내고, 서버가 거절하면 그 사유를 그대로 보인다.
 * `GATE_FIELDS` 는 서버 `AUTH_FIELDS` 와 같은 순서다(`tests/test_live_gate_form_contract.py` 가 건다).
 */
import { getWithAuth, postJson } from "@/shared/api/apiBase";
import { call } from "@/shared/api/result";

export const GATE_FIELDS = ["basis", "authority", "reference_no", "verified_at", "scope", "allowed_users"] as const;
export type GateField = (typeof GATE_FIELDS)[number];
/** 안내 글에 드는 '모두에게 여는 값' 예 — 서버 `_WILDCARDS` 안의 값이어야 한다(같은 pytest 가 건다). 화면은 막지 않고 서버가 거절한다. */
export const WILDCARD_EXAMPLES = ["*", "모두"] as const;

/** 선언 한 건 — 서버 `live_gate_store._row_dict` 그대로. 거둔 선언은 `revoked_*` 가 찬다. */
export type GateRecord = {
  basis: string; authority: string; reference_no: string; verified_at: string; scope: string; allowed_users: string[];
  declared_by: string | null; declared_at: string | null; revoked_by: string | null; revoked_at: string | null;
};
export type GateState = { current: GateRecord | null; history: GateRecord[] };
export type GateDeclare = { basis: string; authority: string; reference_no: string; verified_at: string; scope: string; allowed_users: string[] };

export const getLiveGate = () => call<GateState>(getWithAuth("/api/v1/admin/live-gate"));
export const declareLiveGate = (body: GateDeclare) =>
  call<{ current: GateRecord; live_dropped_to_shadow: boolean }>(postJson("/api/v1/admin/live-gate", body));
export const revokeLiveGate = () =>
  call<{ revoked: boolean; revoked_by: string; live_dropped_to_shadow: boolean }>(getWithAuth("/api/v1/admin/live-gate", { method: "DELETE" }));
