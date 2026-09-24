// ═══════════════════════════════════════════════════════════════════════════════
// 멀티전략 서브시스템 부재 — 백엔드의 503 사유를 꺼낸다 (BF)
//
// `/api/v1/multibacktest/*` · `/api/v1/realism/backtest` 는 필요한 모듈 다섯이
// 저장소에 없어 503 + `detail` 을 낸다(`src/engine/multistrategy_availability.py`).
// ★화면은 그 사유를 그대로 보여 준다★ — 빈 목록이나 모의 수치로 조용히 대체하지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════

export interface MissingModule {
  module: string;
  role: string;
  reason: string;
}

export interface SubsystemUnavailable {
  available: false;
  missing: MissingModule[];
  data_gap: string;
  reason: string;
  since: string;
}

function isUnavailable(d: unknown): d is SubsystemUnavailable {
  if (!d || typeof d !== "object") return false;
  const o = d as Record<string, unknown>;
  return o.available === false && typeof o.reason === "string" && Array.isArray(o.missing);
}

/** 응답 본문이 "서브시스템 없음(503)" 이면 사람이 읽을 사유, 아니면 `null`. */
export function unavailableReason(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as Record<string, unknown>).detail;
  if (!isUnavailable(detail)) return null;
  const roles = detail.missing.map((m) => m.role).filter(Boolean).join(" · ");
  return roles ? `${detail.reason} (없는 것: ${roles})` : detail.reason;
}
