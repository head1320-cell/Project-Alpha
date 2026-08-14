/**
 * 매크로 서브스튜디오 + 능력 사다리 클라이언트 (M1-U)
 * ==========================================================================
 * 서버(M1-C·M1-M)는 이미 다섯 스튜디오의 두 엔진 상태와 능력 레벨을 답한다.
 * 이 파일은 그것을 **좁히지 않으면 읽을 수 없는 타입**으로 받아 온다.
 *
 * ★`available` 로 좁혀야만 `outputs` 를 읽을 수 있다★
 * A7-R1 이 `RegimeEnsemble` 에 쓴 판별 유니온과 같은 기법이다. 이렇게 짜면
 * `outputs.k_factors ?? 0` 같은 코드가 **타입 단계에서 불가능**해진다 — 미가용
 * 스튜디오가 숫자를 내는 것이 이 화면에서 가장 위험한 거짓이기 때문이다.
 *
 * ★네트워크 오류를 삼키지 않는다★
 * `.catch(() => null)` 로 뭉개면 "서버가 미가용이라고 답했다" 와 "서버에 닿지
 * 못했다" 가 한 값이 된다 — R0-S 가 런 목록에서 고친 것과 같은 결함 계열이다.
 */

import { API_BASE } from "@/shared/api/apiBase";

// ─── 능력 사다리 (GET /macro/capability) ────────────────────────────────────

export interface CapabilityProbe {
  ok: boolean;
  description: string;
  reason: string;
  detail: Record<string, unknown> | null;
}

export interface CapabilityLevelInfo {
  label: string;
  note: string;
  requirements: string[];
  failed: string[];
  ok: boolean;
}

export interface Capability {
  level: "L0" | "L1" | "L2" | "L3";
  label: string;
  note?: string;
  /** 바로 위 레벨(더 강한 주장)이 막혔다면 그 레벨 — 없으면 최상단에 있다는 뜻. */
  blocked_level: "L0" | "L1" | "L2" | "L3" | null;
  /** ★사유 없는 강등은 하지 않는다 (M1-C)★ 배지만 그리고 이유를 빼면 안 된다. */
  blocked_reason: string | null;
  levels: Record<string, CapabilityLevelInfo>;
  probes?: Record<string, CapabilityProbe>;
}

// ─── 스튜디오 목록 (GET /macro/studios) ─────────────────────────────────────

/** 프론티어 엔진의 현재 상태 — 요건 프로브 결과를 그대로 반영한다. */
export type StudioFrontier =
  & { name: string; summary: string; requires: string[] }
  & ({ available: true; reason: null; note?: string | null }
   | { available: false; reason: string; missing?: string[] });

export interface StudioDescriptor {
  id: string;
  label: string;
  question: string;
  inputs: string[];
  frontier: StudioFrontier;
  substitute: { name: string; summary: string; requires: string[] };
}

// ─── 스튜디오 실행 (GET /macro/studios/{id}) ────────────────────────────────

export interface StudioSpan {
  first: string | null;
  last: string | null;
  n: number;
  requested: number;
  /** ★요청보다 짧으면 응답이 그 사실을 말한다 (A8 규칙)★ 화면이 마저 말해야 한다. */
  truncated: boolean;
}

export type StudioResult =
  | { available: false; engine: string | null; reason: string }
  | {
      available: true;
      engine: string;
      outputs: Record<string, unknown>;
      note: string | null;
      span: StudioSpan | null;
    };

/** 뷰 하나. ★서버 계약을 실제로 읽고 맞췄다★ — `agentic_views.compile_views` 는
 *  `{asset, direction, value, label?}` 를 받는다(`+1` → `E[r] ≥ value`, `-1` → `≤`).
 *  처음에는 `{kind, op}` 로 짐작해 썼는데, 그 모양은 서버가 조용히 무시하고
 *  `direction` 기본값 `+1` 로 컴파일한다 — 화면이 "이하" 라고 적어도 서버는 "이상"
 *  으로 계산했을 것이다. 소스를 읽고 고쳤다. */
export interface ViewSpec {
  asset: string;
  direction: 1 | -1;
  value: number;
  label?: string;
}

export const studiosApi = {
  capability: async (): Promise<Capability> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/capability`);
    if (!r.ok) throw new Error(`capability failed: ${r.status}`);
    return r.json();
  },

  list: async (): Promise<{ studios: StudioDescriptor[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/studios`);
    if (!r.ok) throw new Error(`studios failed: ${r.status}`);
    return r.json();
  },

  run: async (id: string, months = 60, target = "KOSPI"): Promise<StudioResult> => {
    const q = new URLSearchParams({ months: String(months), target });
    const r = await fetch(`${API_BASE}/api/v1/macro/studios/${encodeURIComponent(id)}?${q}`);
    if (!r.ok) throw new Error(`studio ${id} failed: ${r.status}`);
    return r.json();
  },

  /** 뷰 컴파일 (05 VIEWS). ★`feasible: null` 은 `true` 가 아니다★ —
   *  시나리오 없이 검사하지 않은 것과 통과한 것은 다른 사실이고, 서버가 이미 갈라 둔다. */
  compileViews: async (assets: string[], views: ViewSpec[],
                       scenarios?: number[][]): Promise<StudioResult> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/studios/agentic-mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assets, views, scenarios: scenarios ?? null }),
    });
    if (!r.ok) throw new Error(`view compile failed: ${r.status}`);
    return r.json();
  },
};
