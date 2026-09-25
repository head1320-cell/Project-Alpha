// ═══════════════════════════════════════════════════════════════════════════════
// 멀티전략 — 등록된 전략 · 출처 · 가용성 (BG6)
//
// 백엔드: `src/api/stage11_routes.py` (`/api/v1/multibacktest/strategies` ·
// `/availability`) · 레지스트리 `src/engine/strategy_registry.py`.
//
// ★전략은 저장된 백테스트 실행에서 온다★ — 등록은 그 실행을 **다시 돌려** 자산곡선이
// 저장본과 전부 같을 때만 받아들인다. 다르면 409 + 사유(+ 첫 불일치 날짜)다. 화면은
// 그 사유를 그대로 보여 준다.
// ═══════════════════════════════════════════════════════════════════════════════

import { API_BASE } from "@/shared/api/apiBase";

// ★같은 계층의 다른 슬라이스(entities/realism)를 import 하지 않는다★ (FSD) — 모양이
// 같은 두 타입을 여기 둔다. 백엔드 `multistrategy_availability.status()` 가 원본이다.
export interface MissingModule {
  module: string;
  role: string;
  reason: string;
  features?: string[];
}

export interface UnsupportedFeature {
  feature: string;
  field: string;
  value: string;
  reason: string;
  missing: string[];
}

export interface ReproCheck {
  equal: boolean;
  compared_points: number;
  first_mismatch: {
    index: number;
    date: string | null;
    stored: number | null;
    rerun: number | null;
  } | null;
}

/** 등록된 전략 — `StrategyRegistry._row`. */
export interface RegisteredStrategy {
  id: number;
  name: string;
  source_run_id: string;
  is_active: boolean;
  /** 원천 실행의 데이터 축. `null` = 원천이 말하지 않았다(미상). */
  is_mock_data: boolean | null;
  is_pit_verified: boolean | null;
  symbols: string[];
  registered_at: number | null;
  repro: ReproCheck | null;
}

/** 결과의 `sources.strategies[]` — 전략별 원천. */
export interface StrategySource {
  strategy_id: number;
  registered: boolean;
  name?: string;
  source_run_id?: string;
  is_active?: boolean;
  is_mock_data: boolean | null;
  is_pit_verified: boolean | null;
  repro_equal?: boolean | null;
  repro_compared_points?: number | null;
  reason?: string;
}

export interface SourcesBlock {
  available: boolean;
  strategies: StrategySource[];
  reason: string | null;
}

/** `GET /availability` — `multistrategy_availability.status()`. */
export interface MultistrategyAvailability {
  available: boolean;
  missing: MissingModule[];
  unsupported_features: UnsupportedFeature[];
  data_gap: string;
  reason: string | null;
  since: string;
}

export type RegisterOutcome =
  | { ok: true; strategy: RegisteredStrategy }
  | { ok: false; status: number; reason: string; firstMismatchDate: string | null };

async function readJson(res: Response): Promise<any> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

function detailReason(body: any, status: number): string {
  const d = body?.detail;
  if (d && typeof d === "object" && typeof d.reason === "string") return d.reason;
  if (typeof d === "string") return d;
  return `요청이 실패했습니다 (HTTP ${status})`;
}

export const multibacktestApi = {
  /** 등록된 전략 목록. 실패하면 ★빈 목록이 아니라★ 사유를 던진다. */
  strategies: async (activeOnly = true): Promise<RegisteredStrategy[]> => {
    const res = await fetch(
      `${API_BASE}/api/v1/multibacktest/strategies?active_only=${activeOnly}`);
    const body = await readJson(res);
    if (!res.ok) throw new Error(detailReason(body, res.status));
    return (body?.strategies ?? []) as RegisteredStrategy[];
  },

  /** 저장된 실행 → 전략. 거절(409)은 예외가 아니라 결과다 — 사유를 그린다. */
  register: async (runId: string, name?: string): Promise<RegisterOutcome> => {
    const res = await fetch(`${API_BASE}/api/v1/multibacktest/strategies`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, name: name?.trim() || null }),
    });
    const body = await readJson(res);
    if (res.ok) return { ok: true, strategy: body as RegisteredStrategy };
    return {
      ok: false,
      status: res.status,
      reason: detailReason(body, res.status),
      firstMismatchDate: body?.detail?.first_mismatch?.date ?? null,
    };
  },

  /** 비활성 — 지우지 않는다(지난 실행의 출처가 남아야 한다). */
  deactivate: async (id: number): Promise<void> => {
    const res = await fetch(`${API_BASE}/api/v1/multibacktest/strategies/${id}`,
                            { method: "DELETE" });
    if (!res.ok) throw new Error(detailReason(await readJson(res), res.status));
  },

  availability: async (): Promise<MultistrategyAvailability> => {
    const res = await fetch(`${API_BASE}/api/v1/multibacktest/availability`);
    const body = await readJson(res);
    if (!res.ok) throw new Error(detailReason(body, res.status));
    return body as MultistrategyAvailability;
  },
};

/** 이 필드의 이 값이 지금 안 되면 그 사유, 되면 `null`. */
export function unsupportedReason(
  availability: MultistrategyAvailability | null,
  field: string,
  value: string,
): string | null {
  const hit = availability?.unsupported_features?.find(
    (u) => u.field === field && u.value === value);
  return hit ? hit.reason : null;
}
