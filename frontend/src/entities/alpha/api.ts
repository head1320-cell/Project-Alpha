/**
 * alphaApi — Alpha Lab 클라이언트 (Full Expansion P2)
 * /api/v1/alpha-lab/* (fields·lint·validate) + /api/v1/alpha-registry (CRUD·promote)
 */
import { API_BASE } from "@/shared/api/apiBase";

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

export const alphaApi = {
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
