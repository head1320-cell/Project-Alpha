// ═══════════════════════════════════════════════════════════════════════════════
// 멀티전략 서브시스템 — 백엔드가 말한 "안 되는 이유" 를 꺼낸다 (BF · BG6)
//
// `/api/v1/multibacktest/*` · `/api/v1/realism/backtest` 는 두 가지로 거절한다
// (`src/engine/multistrategy_availability.py`):
//   503 — 코어 모듈이 없다(서브시스템 전체가 없다). `detail.available === false`.
//   422 — 서브시스템은 있는데 ★요청이 아직 없는 기능을 골랐다★(R4 전의
//         `hrp_macro` · `regime_change`). `detail.unsupported[]`.
// ★화면은 그 사유를 그대로 보여 준다★ — 빈 목록이나 모의 수치로 조용히 대체하지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════

export interface MissingModule {
  module: string;
  role: string;
  reason: string;
  features?: string[];
}

/** 요청이 고른 기능 하나가 없다 — 어느 칸의 어느 값인지와 사유. */
export interface UnsupportedFeature {
  feature: string;
  field: string;
  value: string;
  reason: string;
  missing: string[];
}

export interface SubsystemUnavailable {
  available: false;
  missing: MissingModule[];
  data_gap: string;
  reason: string;
  since: string;
}

export interface FeatureUnsupported {
  available: true;
  unsupported: UnsupportedFeature[];
  reason: string;
}

function isUnavailable(d: unknown): d is SubsystemUnavailable {
  if (!d || typeof d !== "object") return false;
  const o = d as Record<string, unknown>;
  return o.available === false && typeof o.reason === "string" && Array.isArray(o.missing);
}

function isUnsupported(d: unknown): d is FeatureUnsupported {
  if (!d || typeof d !== "object") return false;
  const o = d as Record<string, unknown>;
  return typeof o.reason === "string" && Array.isArray(o.unsupported);
}

/**
 * 응답 본문이 "서브시스템 없음(503)" 이나 "없는 기능을 고름(422)" 이면 사람이 읽을
 * 사유, 아니면 `null`.
 */
export function unavailableReason(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as Record<string, unknown>).detail;
  if (isUnavailable(detail)) {
    const roles = detail.missing.map((m) => m.role).filter(Boolean).join(" · ");
    return roles ? `${detail.reason} (없는 것: ${roles})` : detail.reason;
  }
  if (isUnsupported(detail)) {
    const why = detail.unsupported.map((u) => u.reason).filter(Boolean).join(" / ");
    return why ? `${detail.reason} — ${why}` : detail.reason;
  }
  return null;
}
