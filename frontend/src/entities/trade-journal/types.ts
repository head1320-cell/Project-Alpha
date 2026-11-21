/**
 * 매매일지 — 서버 응답의 모양 (`POST /api/v1/trade-journal/analyze` · `src/engine/trade_journal/__init__.py::analyze`).
 * ★값이 없으면 `null` 이다(0 이 아니다)★ — 분모가 0 인 비율 · 비용을 모르는 거래의 비용 후 손익 · 시각 없는 체결의 보유 시간.
 */

/** 비용의 근거 — 관측(파일의 값) · 추론(세율표로 산출) · 가정(사용자 입력) · 미상 · 해당 없음(매수의 매도세). */
export type CostBasis = "observed" | "inferred" | "assumed" | "unknown" | "not_applicable";
export type PnlBasis = "net" | "gross";

/** 체결 한 줄 — 브라우저가 파일을 읽어 이 모양으로 맞춰 보낸다. 서버는 이 밖의 열을 받지 않는다. */
export type FillRow = {
  executed_at: string | null;
  symbol: string | null;
  side: "buy" | "sell" | null;
  quantity: number | string | null;
  price: number | string | null;
  fee?: number | string | null;
  tax?: number | string | null;
  market?: "KOSPI" | "KOSDAQ" | "KONEX" | null;
  instrument?: "stock" | "etf" | null;
  name?: string | null;
};

export type AnalyzeRequest = {
  fills: FillRow[];
  commission_bp: number | null;
  unknown_market: "KOSPI" | "KOSDAQ" | "KONEX" | null;
  unknown_instrument: "stock" | "etf" | null;
};

export type Summary = {
  n: number; wins: number; losses: number; flats: number;
  win_rate: number | null;
  total: number; gross_profit: number; gross_loss: number;
  avg_win: number | null; avg_loss: number | null;
  payoff: number | null; expectancy: number | null; profit_factor: number | null;
  breakeven_win_rate: number | null; edge_over_breakeven: number | null;
  max_losing_streak: { count: number; amount: number };
  small_sample: boolean;
};

export type CostBlock = {
  fees: number | null; taxes: number | null; total: number | null;
  share_of_gross: number | null;
  share_reason: "no_trades" | "cost_unknown" | "gross_not_positive" | null;
  turnover: number; bp_of_turnover: number | null; per_trade: number | null;
};

export type BucketRow = {
  key: string | number; label: string; n: number; wins: number; losses: number;
  win_rate: number | null; total: number; expectancy: number | null;
};
export type SymbolRow = BucketRow & { name: string | null; gross: number; cost: number | null };

export type TradeRow = {
  symbol: string; name: string | null;
  opened_at: string; closed_at: string; has_time: boolean;
  holding_seconds: number | null; same_day: boolean;
  quantity: number; fills: number;
  buy_amount: number; sell_amount: number; avg_buy: number; avg_sell: number;
  gross: number; fees: number | null; taxes: number | null; cost: number | null; net: number | null;
  after_loss: boolean | null;
};

export type CurvePoint = { at: string; pnl: number; cum: number; drawdown: number };

export type TaxRate = {
  market: string; instrument: string; bp: number;
  parts: { transaction_tax_bp: number; rural_special_tax_bp: number };
  period: { from: string; to: string | null };
  grade: string; sources: { title: string; url: string }[]; note: string | null;
  basis: "inferred" | "assumed"; fills: number;
};

export type Reject = { row: number; reason: string; message: string };

export type Journal = {
  inputs: { rows: number; fills: number; rejected: number; symbols: number; first: string | null; last: string | null };
  rejects: { count: number; by_reason: Record<string, { count: number; message: string }>; sample: Reject[] };
  basis: {
    pnl_basis: PnlBasis;
    fee: Record<"observed" | "assumed" | "unknown", number>;
    tax: Record<CostBasis, number>;
    commission_bp: number | null;
    unknown_market: string | null; unknown_instrument: string | null;
    tax_rates: TaxRate[];
    tax_unknown: { reason: string; count: number; message: string }[];
  };
  summary: {
    gross: Summary; net: Summary | null; net_excluded: number;
    costs: CostBlock;
    open_realized: { n: number; gross: number; net: number | null };
  };
  curve: { basis: PnlBasis; points: CurvePoint[]; max_drawdown: number | null; max_drawdown_at: string | null };
  breakdowns: {
    basis: PnlBasis;
    holding: BucketRow[]; hour: BucketRow[]; weekday: BucketRow[]; symbol: SymbolRow[]; daily: BucketRow[];
    after_loss: { within_minutes: number; after: BucketRow; other: BucketRow };
    without_time: number;
  };
  extremes: { basis: PnlBasis; limit: number; worst: TradeRow[]; best: TradeRow[] };
  trades: TradeRow[]; trades_total: number; trades_limit: number;
  open_positions: {
    symbol: string; name: string | null; opened_at: string;
    open_quantity: number; buy_quantity: number; sold_quantity: number; open_amount: number;
    realized_gross: number; realized_cost: number | null; realized_net: number | null;
  }[];
  unmatched_sells: { count: number; sample: { row: number; symbol: string; quantity: number; reason: string; message: string }[] };
  not_covered: string[];
  limits: { fills: number };
};
