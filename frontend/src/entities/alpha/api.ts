/**
 * alphaApi — Alpha Lab 클라이언트 (Full Expansion P2)
 * /api/v1/alpha-lab/* (fields·lint·validate) + /api/v1/alpha-registry (CRUD·promote)
 */
import { API_BASE } from "@/shared/api/apiBase";
import { getActiveCaseId } from "@/shared/lib/caseStorage";

export interface AlphaFieldMeta { id: string; label: string; family: "price" | "fund"; desc: string }
export interface AlphaFuncMeta { id: string; label: string; desc: string }

// ── 통합 표현식 카탈로그 (팩터 창) — 백엔드 alpha_routes._FUNC_META/_FAMILY_LABEL과 1:1 ──
export type AlphaFamily = "price" | "fund" | "transform" | "combine";
export interface AlphaCatalogItem {
  id: string;
  label: string;
  family: AlphaFamily;
  desc: string;
  kind: "field" | "function";
  insert: "append" | "wrap" | "wrap2";
  provenance: string;
}
export interface AlphaCatalog {
  fields: AlphaFieldMeta[];
  functions: AlphaFuncMeta[];
  groups: { family: AlphaFamily; label: string; items: AlphaCatalogItem[] }[];
  families: { id: AlphaFamily; label: string }[];
  note: string;
  notes: string[];
}

export interface LintIssue { level: "error" | "warn" | "info"; code: string; message: string }
export interface LintResult { ok: boolean; issues: LintIssue[]; fields: string[]; funcs: string[] }

export interface IcAgg { mean: number | null; icir: number | null; t_stat: number | null; hit_rate: number | null }

export interface AlphaValidationReport {
  error: boolean;
  message?: string;
  expr?: string;
  n_periods?: number;
  period_start?: string;
  period_end?: string;
  universe_size?: number;
  avg_coverage?: number;
  ic?: IcAgg;
  decay?: { "1m": number | null; "2m": number | null; "3m": number | null };
  is_oos?: { is_ic: number | null; oos_ic: number | null; split: string };
  quantiles?: { n: number; ann_return_pct: (number | null)[]; monotonicity: number | null };
  long_short?: { curve: number[]; total_return_pct: number; sharpe: number | null; mdd_pct: number };
  turnover_proxy?: number | null;
  latest_scores_top?: { ticker: string; name: string; score: number }[];
  notes?: string[];
  lint?: LintResult;
  run_id?: string | null;
  run_recorded?: boolean;
}

export type AlphaStatus = "draft" | "experimental" | "validated" | "approved" | "retired";

export interface AlphaDef {
  alpha_id: string;
  name: string;
  expr: string;
  description: string;
  universe: string;
  tags: string[];
  status: AlphaStatus;
  version: number;
  is_template: boolean;
  last_run_id: string | null;
  parent_id: string | null;
  notes: string;
  created_at: number;
  updated_at: number;
}

// ── 알파 포트폴리오 (P2-R) ──────────────────────────────────────────────────
// ★`available` 로 좁혀야만 비중을 읽을 수 있다★ 막힌 응답에서 `base_weights` 를
// 읽으려 하면 타입이 막는다 — 사다리에 걸린 알파로 포트폴리오를 그리는 것이 이
// 화면에서 가장 위험한 거짓이기 때문이다.

export interface AlphaPairwise {
  a: string; b: string; rho: number | null; duplicate?: boolean; reason?: string;
}

export interface AlphaHolding {
  code: string; name: string; weight: number; score: number;
}

export interface AlphaPortfolioBlocked {
  available: false;
  blocked?: { alpha_id: string; name: string | null; status: string | null; reason: string }[];
  excluded?: { alpha_id: string; reason: string }[];
  reason?: string;
  as_of_effective?: string | null;
}

export interface AlphaPortfolioDone {
  available: true;
  as_of_requested: string | null;
  as_of_effective: string | null;
  base_weights: Record<string, number>;
  holdings: AlphaHolding[];
  used: { alpha_id: string; weight: number }[];
  excluded: { alpha_id: string; reason: string }[];
  pairwise: AlphaPairwise[];
  effective_n: number | null;
  warnings: string[];
  weighting: string;
  top_k: number;
  universe_resolved_n: number;
  note: string;
  run_id?: string | null;
  run_recorded?: boolean;
}

export type AlphaPortfolioResult = AlphaPortfolioDone | AlphaPortfolioBlocked;

export interface AlphaPortfolioRequest {
  alphas: { alpha_id: string; weight: number }[];
  tickers?: string[];
  universe?: string;
  top_k?: number;
  weighting?: string;
  lookback_days?: number;
  as_of?: string | null;
  case_id?: string | null;
  record_run?: boolean;
}

export const alphaApi = {
  /** 승인된 알파 → 목표 비중. ★네트워크 오류를 삼키지 않는다★ (R0-S 어휘) */
  portfolio: async (req: AlphaPortfolioRequest): Promise<AlphaPortfolioResult> => {
    const body = { ...req, ...(req.case_id === undefined ? { case_id: getActiveCaseId() } : {}) };
    const r = await fetch(`${API_BASE}/api/v1/alpha-lab/portfolio`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`alpha portfolio failed: ${r.status}`);
    return r.json();
  },

  fields: async (): Promise<AlphaCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/alpha-lab/fields`);
    if (!r.ok) throw new Error(`fields failed: ${r.status}`);
    return r.json();
  },
  lint: async (expr: string): Promise<LintResult> => {
    const r = await fetch(`${API_BASE}/api/v1/alpha-lab/lint`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expr }),
    });
    if (!r.ok) throw new Error(`lint failed: ${r.status}`);
    return r.json();
  },
  validate: async (req: {
    expr: string; tickers?: string[]; universe?: string; months?: number;
    quantiles?: number; alpha_id?: string; record_run?: boolean;
  }): Promise<AlphaValidationReport> => {
    const r = await fetch(`${API_BASE}/api/v1/alpha-lab/validate`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`validate failed: ${r.status}`);
    return r.json();
  },
  registry: async (status?: AlphaStatus): Promise<{ alphas: AlphaDef[] }> => {
    const q = status ? `?status=${status}` : "";
    const r = await fetch(`${API_BASE}/api/v1/alpha-registry${q}`);
    if (!r.ok) throw new Error(`registry failed: ${r.status}`);
    return r.json();
  },
  upsert: async (req: {
    alpha_id?: string; name: string; expr: string; description?: string;
    universe?: string; tags?: string[]; notes?: string;
  }): Promise<{ error: boolean; message?: string; lint?: LintResult; alpha?: AlphaDef }> => {
    const r = await fetch(`${API_BASE}/api/v1/alpha-registry`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`upsert failed: ${r.status}`);
    return r.json();
  },
  promote: async (alphaId: string, toStatus: AlphaStatus, note = ""):
    Promise<{ ok: boolean; reason?: string; alpha?: AlphaDef }> => {
    const r = await fetch(`${API_BASE}/api/v1/alpha-registry/${encodeURIComponent(alphaId)}/promote`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_status: toStatus, note }),
    });
    if (!r.ok) throw new Error(`promote failed: ${r.status}`);
    return r.json();
  },
  remove: async (alphaId: string): Promise<{ deleted: boolean }> => {
    const r = await fetch(`${API_BASE}/api/v1/alpha-registry/${encodeURIComponent(alphaId)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`delete failed: ${r.status}`);
    return r.json();
  },
};
