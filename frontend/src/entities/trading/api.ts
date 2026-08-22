// 자동매매 — 모드·계좌·안전설정·주문 실행.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE } from "@/shared/api/apiBase";
import type { FilterGroupNode } from "@/shared/model/domain";

export interface TradingMode {
  mode: "mock" | "paper" | "real";
  description: string;
  kis_use_mock: boolean;
  kis_is_paper: boolean;
  has_key: boolean;
}

export interface AccountStatus {
  mode: string;
  cash_krw: number;
  evaluated_total: number;
  stock_value: number;
  n_positions: number;
  positions: Array<{ ticker: string; name: string; quantity: number; avg_price: number; current_price: number; eval_amount: number; pnl_pct: number }>;
  safety: Record<string, unknown>;
}

export interface SafetyConfig {
  kill_switch: boolean;
  dry_run: boolean;
  max_position_pct: number;
  max_order_amount_krw: number;
  max_daily_invest_krw: number;
  max_positions: number;
  daily_loss_limit_pct: number;
  min_order_amount_krw: number;
  allow_duplicate_buy: boolean;
}

export interface TradeExecutionResult {
  mode: string;
  executed: Array<{ stock_code: string; stock_name: string; action: string; quantity: number; price: number; amount_krw: number; success: boolean; message: string }>;
  blocked: Array<{ stock_code: string; stock_name: string; blocked_by: string; amount_krw: number }>;
  summary: { n_signals: number; n_executed: number; n_blocked: number; daily_invested_krw: number; warnings: string[] };
  screened_tickers?: Array<{ stock_code: string; corp_name: string; composite_score: number | null }>;
  screened_count?: number;
}

const DEFAULT_SAFETY: SafetyConfig = {
  kill_switch: false, dry_run: true, max_position_pct: 0.20,
  max_order_amount_krw: 10_000_000, max_daily_invest_krw: 50_000_000,
  max_positions: 10, daily_loss_limit_pct: -5.0, min_order_amount_krw: 100_000,
  allow_duplicate_buy: false,
};

export const tradingApi = {
  mode: async (): Promise<TradingMode> => {
    const r = await fetch(`${API_BASE}/api/v1/trading/mode`);
    if (!r.ok) throw new Error(`Mode failed: ${r.status}`);
    return r.json();
  },
  status: async (): Promise<AccountStatus> => {
    const r = await fetch(`${API_BASE}/api/v1/trading/status`);
    if (!r.ok) throw new Error(`Status failed: ${r.status}`);
    return r.json();
  },
  screenToTrade: async (body: {
    universe: string; filter_ast: FilterGroupNode; liquidity_floor: string;
    max_tickers: number; action?: string; equal_weight?: boolean;
    safety?: Partial<SafetyConfig>;
  }): Promise<TradeExecutionResult> => {
    const r = await fetch(`${API_BASE}/api/v1/trading/screen-to-trade`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "buy", equal_weight: true, ...body,
        safety: { ...DEFAULT_SAFETY, ...(body.safety || {}) } }),
    });
    if (!r.ok) throw new Error(`Screen-to-trade failed: ${r.status}`);
    return r.json();
  },
};

export { DEFAULT_SAFETY };
