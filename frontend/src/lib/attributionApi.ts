/**
 * Attribution · Journal · Strategy Health API Client (Full Expansion P5)
 * ==========================================================================
 * /api/v1/allocation/attribution/{run_id} · /journal · /strategy-health
 * Attribution = 사전(ResearchRun) 기대 vs 사후(결정일 이후 실측) 비교. Journal은
 * 같은 run_id로 Attribution에 연결.
 */

import { API_BASE } from "@/lib/apiBase";

export type Basis = "real" | "mock" | "unavailable";

export interface AttributionReport {
  run_id: string;
  kind?: string;
  name?: string;
  decision_date: string;
  as_of: string;
  elapsed_days: number;
  period_years: number;
  coverage: { tickers: number; covered: number; missing: string[]; source: string; has_expost: boolean };
  returns: { portfolio_pct: number | null; benchmark_pct: number | null; excess_pct: number | null; benchmark_label: string; basis: Basis };
  expected_vs_actual: { expected_return_pct: number | null; expected_return_annual_pct: number | null; actual_return_pct: number | null; gap_pct: number | null; basis: Basis };
  decomposition: {
    model_alpha_pct: number | null; execution_slippage_pct: number | null; cost_pct: number | null; residual_pct: number | null;
    basis: { model_alpha: Basis; slippage: Basis; cost: Basis; residual: Basis }; note: string;
  };
  risk_compare: {
    ex_ante: { vol_pct: number | null; var_pct: number | null; cvar_pct: number | null };
    ex_post: { vol_pct: number | null; beta: number | null };
    vol_gap_pct: number | null; basis: Basis;
  };
  contribution: { assets: { code: string; weight_pct: number; return_pct: number; contribution_pct: number }[]; basis: Basis };
  fill_quality: {
    basis: Basis; note?: string; avg_slippage_bp?: number | null;
    rows?: { stock_code: string; filled_qty: number; avg_price: number; target_price: number; slippage_bp: number | null }[];
  };
  dependency: { basis: Basis; hhi?: number; effective_n?: number | null; top_name_share_pct?: number | null; top_name?: string | null; concentrated?: boolean; note?: string };
  brinson_effects: { selection: null; allocation: null; factor: null; timing: null; hedge: null; basis: Basis; note: string };
  note: string;
  journal_entry_id?: string | null;
}

export interface JournalRecord {
  thesis?: string; data_model_versions?: string; counter_arguments?: string;
  decision?: string; reason_change?: string; cause?: string;
  next_experiment?: string; postmortem?: string;
}
export interface JournalLinks {
  alpha_version?: string; sleeve_version?: string; opt_settings?: string;
  scenario_pack?: string; execution_plan_id?: string; approvers?: string[];
}
export type DecisionQuality =
  | "good_outcome_good_process" | "good_outcome_bad_process"
  | "bad_outcome_good_process" | "bad_outcome_bad_process" | "too_early";

export interface JournalEntry {
  entry_id: string; created_at: number; updated_at: number;
  run_id: string | null; title: string;
  links: JournalLinks; record: JournalRecord;
  decision_quality: DecisionQuality | null; review: string | null;
  attribution: AttributionReport | null;
}

export interface HealthSignal { key: string; label: string; value: unknown; status: "ok" | "warn" | "bad" | "unmeasured"; basis: Basis; detail?: string }
export interface HealthItem { alpha_id: string; name: string; registry_status?: string; status: "healthy" | "watch" | "de_risk" | "paused" | "retired"; signals: HealthSignal[] }
export interface HealthResult {
  items: HealthItem[];
  counts: Record<string, number>;
  n: number;
  derisk_alphas: { alpha_id: string; name: string; status: string }[];
  note: string;
}

export const attributionApi = {
  get: async (runId: string): Promise<AttributionReport> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/attribution/${runId}`);
    if (!r.ok) throw new Error(`attribution failed: ${r.status}`);
    return r.json();
  },

  createJournal: async (req: {
    title: string; run_id?: string | null; links?: JournalLinks; record?: JournalRecord;
    decision_quality?: DecisionQuality | null; attach_attribution?: boolean;
  }): Promise<{ saved: boolean; entry_id: string | null; message?: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/journal`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`journal create failed: ${r.status}`);
    return r.json();
  },

  listJournal: async (): Promise<{ entries: JournalEntry[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/journal`);
    if (!r.ok) throw new Error(`journal list failed: ${r.status}`);
    return r.json();
  },

  journalByRun: async (runId: string): Promise<{ entry: JournalEntry | null }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/journal/by-run/${runId}`);
    if (!r.ok) throw new Error(`journal by-run failed: ${r.status}`);
    return r.json();
  },

  reviewJournal: async (entryId: string, review: string, decisionQuality?: DecisionQuality):
    Promise<{ ok: boolean; reason?: string; entry?: JournalEntry }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/journal/${entryId}/review`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review, decision_quality: decisionQuality ?? null }),
    });
    if (!r.ok) throw new Error(`journal review failed: ${r.status}`);
    return r.json();
  },

  deleteJournal: async (entryId: string): Promise<{ deleted: boolean }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/journal/${entryId}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`journal delete failed: ${r.status}`);
    return r.json();
  },

  strategyHealth: async (): Promise<HealthResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/strategy-health`);
    if (!r.ok) throw new Error(`strategy-health failed: ${r.status}`);
    return r.json();
  },
};
