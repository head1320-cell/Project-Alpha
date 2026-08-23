/**
 * Experimental Features API Client (Full Expansion P6)
 * ==========================================================================
 * /api/v1/experimental/* — AutoAlpha 후보 생성 샌드박스.
 * 실험 기능은 자동 채택 금지 — 인간 검증이 필요한 후보 생성기. 스테이징은
 * experimental 상태로만(레지스트리 승급 사다리를 통과해야 실전 사용).
 */

import { API_BASE } from "@/shared/api/apiBase";

export interface AlphaCandidate {
  expr: string;
  fields: string[];
  funcs: string[];
  warnings: { level: string; code: string; message: string }[];
  info: { level: string; code: string; message: string }[];
}

export interface AutoAlphaResult {
  candidates: AlphaCandidate[];
  requested: number;
  generated: number;
  attempts: number;
  mode: string;
  governance: { status_ceiling: string; auto_adopt: boolean; note: string };
  selection_bias: { n_trials: number; expected_max_z: number; note: string };
}

export interface StageResult {
  staged: { alpha_id: string; expr: string; status: string }[];
  rejected: { expr: string; reason: string }[];
  n_staged: number;
  governance: { status: string; auto_adopt: boolean; note: string };
}

export interface ExperimentalFeature {
  id: string; label: string; connected: boolean; kind: string;
  desc: string; governance: string;
}

export const experimentalApi = {
  autoAlpha: async (req: { n: number; seed: number; mode: "random" | "genetic"; seeds?: string[]; universe?: string }):
    Promise<AutoAlphaResult> => {
    const r = await fetch(`${API_BASE}/api/v1/experimental/auto-alpha`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`auto-alpha failed: ${r.status}`);
    return r.json();
  },

  stage: async (exprs: string[], namePrefix = "AutoAlpha", universe = "kospi200"): Promise<StageResult> => {
    const r = await fetch(`${API_BASE}/api/v1/experimental/auto-alpha/stage`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exprs, name_prefix: namePrefix, universe }),
    });
    if (!r.ok) throw new Error(`stage failed: ${r.status}`);
    return r.json();
  },

  catalog: async (): Promise<{ features: ExperimentalFeature[]; note: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/experimental/catalog`);
    if (!r.ok) throw new Error(`experimental catalog failed: ${r.status}`);
    return r.json();
  },
};
