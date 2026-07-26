// Live Trading Cockpit 도메인 타입 — 라우트 파일에서 분리(내용 불변).

export type Mode = "SHADOW" | "PAPER" | "LIVE";

export interface Position {
  ticker: string;
  name?: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  eval_amount: number;
  pnl_pct: number;
  pnl_krw: number;
}

export interface Balance {
  cash_krw: number;
  evaluated_total: number;
  stock_value: number;
  positions: Position[];
  n_positions: number;
}

export interface Order {
  client_order_id: string;
  ticker: string;
  side: string;
  quantity: number;
  filled_quantity?: number;
  price?: number;
  status: string;
  execution_mode: string;
  strategy_id?: number;
  reason_code?: string;
  created_at: string;
}

export interface KillStatus {
  is_active: boolean;
  active_event?: { event_id: string; trigger_reason: string; triggered_at: string };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Main Page
// ═══════════════════════════════════════════════════════════════════════════════
