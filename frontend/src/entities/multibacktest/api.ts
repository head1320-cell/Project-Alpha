// ═══════════════════════════════════════════════════════════════════════════════
// 등록된 전략 — 캔버스 전략 고르기 · 결과 화면의 "전략으로 등록" (BG6 · ST2)
//
// 백엔드: `src/api/stage11_routes.py` (`/api/v1/multibacktest/strategies`) ·
// 레지스트리 `src/engine/strategy_registry.py`.
//
// ★전략은 저장된 백테스트 실행에서 온다★ — 등록은 그 실행을 **다시 돌려** 자산곡선이
// 저장본과 전부 같을 때만 받아들인다. 다르면 409 + 사유(+ 첫 불일치 날짜)다. 화면은
// 그 사유를 그대로 보여 준다.
// ═══════════════════════════════════════════════════════════════════════════════

import { API_BASE } from "@/shared/api/apiBase";

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
  return `요청이 실패했어요 (HTTP ${status})`;
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

};
