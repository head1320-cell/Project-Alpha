// entities/trading/liveModel — 실거래 도메인 타입(계좌·잔고·주문·킬스위치).
//
// Step 1d 에서 /admin/live-trading 라우트에서 분리할 때 widgets/live-trading/model.ts
// 에 두었으나, 이것은 위젯 소유가 아니라 도메인 모델이다. 위젯에 두면 다른 위젯이
// 재사용할 때 peer import(ESLint 로 차단됨)가 되어야 하므로 entities 로 내렸다.
// 내용 불변 — 타입 선언만 있는 파일이다.

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
