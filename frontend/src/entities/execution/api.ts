/**
 * Execution Readiness API Client (Full Expansion P4)
 * ==========================================================================
 * /api/v1/allocation/execution-plan* — 오더 diff·비용·pre-trade·승인 워크플로.
 * v1은 "실행 준비실" — 실 주문·계좌 제어·자동매매 없음. paper_submitted 이후
 * 자동 시뮬 없음(체결은 수동 입력).
 */

import { API_BASE } from "@/shared/api/apiBase";

// ─── Types ───────────────────────────────────────────────────────────────────

export type OrderSide = "buy" | "sell";
export type CheckStatus = "pass" | "warning" | "block";
export type PlanStatus =
  | "draft" | "reviewed" | "approved" | "paper_submitted"
  | "partially_filled" | "filled" | "cancelled" | "rejected" | "reconciled";

export interface OrderRow {
  stock_code: string;
  corp_name: string;
  side: OrderSide;
  quantity: number;
  price_est: number;
  tick_size: number;
  notional: number;
  cur_shares: number;
  tgt_shares: number;
  cur_weight_pct: number;
  tgt_weight_pct: number;
  participation_pct: number | null;
  cost_breakdown: { commission: number; tax: number; spread: number; impact: number };
  cost_bp: number;
  warnings: string[];
  priority: number;
  stage: number;
}

export interface PlanSummary {
  n_orders: number; n_buy: number; n_sell: number;
  gross_notional: number; buy_notional: number; sell_notional: number;
  est_cost: number; est_cost_bp: number; turnover_pct: number; net_cash_change: number;
}

export interface ExecutionPlan {
  orders: OrderRow[];
  summary: PlanSummary;
  missing_price: string[];
  rules: {
    commission_bp: number; sell_tax_bp: number; spread_bp: number; impact_coeff: number;
    board_lot: number; price_limit_pct: number;
    tick_table: { up_to: number | null; tick: number }[];
    source: string;
  };
  notes: string[];
}

export interface PreTradeCheck { name: string; status: CheckStatus; detail: string }
export interface PreTrade {
  overall: CheckStatus;
  n_block: number; n_warning: number;
  checks: PreTradeCheck[];
  can_approve: boolean;
  note: string;
}

export interface PlanPreview { error: boolean; plan: ExecutionPlan; pretrade: PreTrade }

export interface AuditEntry {
  ts: number; action: string; status?: string; from?: string;
  actor?: string; note?: string; detail?: string;
}

export interface SavedPlan {
  plan_id: string; created_at: number; updated_at: number;
  name: string; status: PlanStatus; run_id: string | null;
  audit: AuditEntry[];
  plan?: ExecutionPlan;
  pretrade?: PreTrade;
  fills?: { stock_code: string; filled_qty: number; avg_price: number }[] | null;
}

export interface ExecPlanRequest {
  current_weights: Record<string, number>;   // %
  /** ★R0: 목표는 이것으로 지정하는 것이 정본이다★ 서버가 이 id 의 `final_weights` 를
   *  주문 목표로 쓰고, 승인되지 않은 목표(`research_only`)면 사유와 함께 거부한다. */
  tpv_id?: string | null;
  target_weights: Record<string, number>;    // % (tpv_id 와 함께 보내면 서버가 대조한다)
  portfolio_value: number;
  restricted?: string[];
  limits?: Record<string, number>;            // turnover_cap_pct 등
  data_fresh?: boolean;
}

export interface TransitionResult { ok: boolean; reason?: string; plan?: SavedPlan }

// ─── Client ──────────────────────────────────────────────────────────────────

export const executionApi = {
  preview: async (req: ExecPlanRequest): Promise<PlanPreview> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/execution-plan`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`execution-plan failed: ${r.status}`);
    return r.json();
  },

  save: async (req: ExecPlanRequest & { name: string; run_id?: string | null }):
    Promise<{ saved: boolean; plan_id: string | null; message?: string; plan: ExecutionPlan; pretrade: PreTrade }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/execution-plan/save`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`execution-plan/save failed: ${r.status}`);
    return r.json();
  },

  list: async (): Promise<{ plans: SavedPlan[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/execution-plans`);
    if (!r.ok) throw new Error(`execution-plans failed: ${r.status}`);
    return r.json();
  },

  get: async (planId: string): Promise<SavedPlan> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/execution-plan/${planId}`);
    if (!r.ok) throw new Error(`execution-plan get failed: ${r.status}`);
    return r.json();
  },

  transition: async (planId: string, toStatus: PlanStatus, note = "", actor = "user"): Promise<TransitionResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/execution-plan/${planId}/transition`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_status: toStatus, note, actor }),
    });
    if (!r.ok) throw new Error(`transition failed: ${r.status}`);
    return r.json();
  },

  fills: async (planId: string, fills: { stock_code: string; filled_qty: number; avg_price: number }[], actor = "user"):
    Promise<TransitionResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/execution-plan/${planId}/fills`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fills, actor }),
    });
    if (!r.ok) throw new Error(`fills failed: ${r.status}`);
    return r.json();
  },

  remove: async (planId: string): Promise<{ deleted: boolean }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/execution-plan/${planId}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`delete failed: ${r.status}`);
    return r.json();
  },
};
