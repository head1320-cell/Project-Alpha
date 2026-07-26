// ═══════════════════════════════════════════════════════════════════════════════
// shared/api/legacyApi — 초기 대시보드/파생상품 시절의 단일 api 객체.
//
// ★현황(실측)★ 외부에서 import 되는 것은 `api` 하나뿐이고, 실제로 호출되는 메서드는
// 4개다: optionPrice(/derivatives) · dbStatus/ingest/ingestDoctor(widgets/admin).
// 이 파일의 타입 12개는 **어디에서도 import 되지 않는다** — 파일 내부 반환형 주석 전용.
//
// 그래서 BacktestResult/Position/SymbolItem 세 이름이 entities 의 정본과 충돌해
// grep 이 두 곳을 물어 왔다. Legacy* 접두사를 붙여 정본 쪽만 검색되게 했다
// (타입 전용 개명 — 런타임 영향 0). 정본은 각각:
//   entities/backtest/chartModel.ts · entities/trading/liveModel.ts · entities/company/model.ts
//
// 미사용 메서드 정리는 별개 판단이라 손대지 않았다.
// ═══════════════════════════════════════════════════════════════════════════════
import { API_BASE as BASE } from "@/shared/api/apiBase";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

const get  = <T>(path: string) => req<T>(path);
const post = <T>(path: string, body: unknown) =>
  req<T>(path, { method: "POST", body: JSON.stringify(body) });

// ── Dashboard ──────────────────────────────────────────────────────────────
export const api = {
  // VaR
  var: (body: { ticker: string; portfolio_value: number; confidence_level: number; use_ewma: boolean }) =>
    post<{ var_amount: number; var_pct: number; method: string }>("/calculate-var", body),

  // Screener
  screenerFactors: () => get<{ equity: string[]; ficc: string[] }>("/screener/factors"),
  screenerStatus:  () => get<{ equity_rows: number; ficc_rows: number; equity_updated_at: string | null }>("/screener/status"),
  runScreener: (body: {
    universe: string;
    conditions: Record<string, { field: string; operator: string; value: number }>;
    logic_expression: string;
    sort_by?: string;
    limit?: number;
  }) => post<{ count: number; results: Record<string, unknown>[]; sql: string }>("/screener", body),

  // KIS Strategies
  strategyList: () =>
    get<{ strategies: Array<{ name: string; class: string; required_days: number }> }>("/api/v1/strategies/list"),

  runBacktest: (body: {
    symbols: string[];
    strategy: string;
    params: Record<string, number>;
    start_date: string;
    end_date: string;
    initial_capital: number;
    commission_rate: number;
    slippage_rate: number;
    stop_loss_pct?: number | null;
    take_profit_pct?: number | null;
    max_positions?: number;
  }) => post<LegacyBacktestResult>("/api/v1/strategies/backtest", body),

  dslValidate: (expression: string) =>
    post<{ valid: boolean; message: string }>("/api/v1/strategies/dsl/validate", { expression }),

  dslBacktest: (body: {
    name: string;
    buy_condition: string;
    sell_condition: string;
    symbols: string[];
    start_date: string;
    end_date: string;
    initial_capital: number;
    commission_rate: number;
  }) => post<LegacyBacktestResult>("/api/v1/strategies/dsl/backtest", body),

  batchSignal: (body: {
    stocks: Array<{ code: string; name: string }>;
    strategy: string;
    params: Record<string, number>;
  }) => post<{ strategy: string; signals: Signal[]; buy_count: number; sell_count: number; total_scanned: number }>(
    "/api/v1/strategies/batch-signal", body
  ),

  // Portfolio
  portfolioAnalyze: (body: {
    tickers: string[];
    start_date: string;
    end_date: string;
    weights?: Record<string, number> | null;
    compute_frontier?: boolean;
    compute_optimal?: boolean;
  }) => post<PortfolioAnalysis>("/api/v1/portfolio/analyze", body),

  portfolioRebalance: (body: {
    tickers: string[];
    start_date: string;
    end_date: string;
    frequency: string;
    initial_capital: number;
    commission_rate: number;
  }) => post<RebalanceResult>("/api/v1/portfolio/rebalance", body),

  // ── Phase 4: Symbols + Account + Orders ───────────────────────────────────
  collectMaster: () =>
    post<{ KOSPI: number; KOSDAQ: number; total: number; elapsed_sec: number }>(
      "/api/v1/symbols/collect-master", {}
    ),

  symbolSearch: (q: string, market?: string, limit = 30) => {
    const params = new URLSearchParams({ q, limit: String(limit) });
    if (market) params.set("market", market);
    return get<{ query: string; total: number; items: LegacySymbolItem[] }>(
      `/api/v1/symbols/search?${params}`
    );
  },

  symbolStatus: () =>
    get<{ loaded: boolean; total: number; markets: Record<string, number>; last_fetched: string | null }>(
      "/api/v1/symbols/status"
    ),

  // ── 통합 DB 적재 점검 + 적재 트리거 ──
  dbStatus: () =>
    get<{
      available: boolean;
      config: Record<string, boolean>;
      tables: Record<string, Record<string, number | string | null>>;
      tools: Record<string, boolean>;
      ingest_running: Record<string, boolean>;
      universe_progress?: {
        progress: Record<string, { master: number; ingested: number }>;
        composition: Record<string, Record<string, number>>;
      };
      ingest_status?: Record<string, {
        running?: boolean; started_at?: string | null; finished_at?: string | null;
        last_error?: string | null;
        progress?: { stage?: string; done?: number; total?: number; saved?: number; failures?: number } | null;
      }>;
      dart_usage?: {
        requests: number; errors: Record<string, number>;
        last_error: { endpoint?: string; status?: string; message?: string } | null;
        quota_exhausted: boolean;
      } | null;
    }>("/api/v1/data/db-status"),

  // 적재 소스(DART/KRX/KIS) 실도달 진단 — 각 소스 경량 실호출 1건
  ingestDoctor: () =>
    get<{
      dart: { ok: boolean; message: string; latency_ms?: number };
      krx: { ok: boolean; message: string; latency_ms?: number };
      kis: { ok: boolean; message: string; latency_ms?: number };
      dart_usage: { requests: number; quota_exhausted: boolean } | null;
    }>("/api/v1/data/ingest-doctor"),

  // target ∈ index | etf | stocks | factors | financials | flows | all
  ingest: (target: string) =>
    post<{ started: string[]; running: Record<string, boolean>; message: string }>(
      `/api/v1/data/ingest/${target}`, {}),

  getHoldings: () =>
    get<{ mode: string; count: number; positions: LegacyPosition[] }>(
      "/api/v1/account/holdings"
    ),

  getBalance: () =>
    get<{ mode: string; deposit: number; eval_amount: number; profit_loss: number; profit_rate: number }>(
      "/api/v1/account/balance"
    ),

  executeOrder: (body: {
    stock_code: string; stock_name: string;
    action: "buy" | "sell"; quantity?: number;
    target_price?: number; strength?: number;
  }) => post<OrderResult>("/api/v1/orders/execute", body),

  batchOrders: (orders: OrderRequest[]) =>
    post<{ total: number; success: number; failed: number; orders: OrderResult[] }>(
      "/api/v1/orders/batch", { orders }
    ),

  // Stocks
  stocks: (params?: { market?: string; search?: string; limit?: number }) => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return get<{ count: number; stocks: Stock[] }>(`/api/v1/stocks${q ? `?${q}` : ""}`);
  },
  prices: (ticker: string, days = 60) =>
    get<{ ticker: string; prices: OHLCV[] }>(`/api/v1/prices/${ticker}?days=${days}`),

  // Options (existing endpoints)
  priceCurve: (body: unknown) => post<unknown>("/price-curve", body),
  optionPrice: (body: unknown) => post<unknown>("/option-price", body),
};

// ── Types ──────────────────────────────────────────────────────────────────

export interface LegacyBacktestResult {
  error?: boolean;
  message?: string;
  result: {
    statistics: {
      total_return_pct: number;
      cagr: number;
      sharpe_ratio: number;
      sortino_ratio: number;
      calmar_ratio: number;
      max_drawdown_pct: number;
      num_trades: number;
      win_rate: number;
      profit_factor: number;
      total_commission: number;
      total_slippage: number;
      avg_trade_return: number;
    };
    equity_curve: number[];
    equity_dates: string[];
    drawdown_curve: number[];
    monthly_returns: Array<{ year: number; month: number; return_pct: number }>;
    trades: Trade[];
    symbol_results: SymbolResult[];
  };
  cost_analysis?: { total_trades: number; total_commission: number; total_slippage: number };
}

export interface Trade {
  date: string; ticker: string; side: "buy" | "sell";
  price: number; quantity: number; value: number;
  commission: number; slippage: number; pnl: number | null; reason: string;
}

export interface SymbolResult {
  symbol: string; total_return_pct: number; num_trades: number; win_rate: number;
}

export interface Signal {
  stock_code: string; stock_name: string;
  action: "buy" | "sell" | "hold";
  strength: number; reason: string;
}

export interface PortfolioAnalysis {
  statistics: { 기대수익률: number; 변동성: number; 샤프비율: number; 분산비율: number };
  correlation: Record<string, Record<string, number>>;
  volatilities: Record<string, number>;
  risk_contributions: Record<string, number>;
  weights: Record<string, number>;
  efficient_frontier: Array<{ return: number; volatility: number; sharpe: number }>;
  optimal_weights: Record<string, number>;
}

export interface RebalanceResult {
  summary: { 리밸런싱_수익률: number; BuyHold_수익률: number; 리밸런싱_효과: number; 거래비용: number; 리밸런싱_횟수: number };
  equity_curve: { dates: string[]; rebalanced: number[]; buy_hold: number[] };
  rebalance_dates: string[];
}

export interface Stock { ticker: string; name: string; market: string; sector: string }
export interface OHLCV { date: string; open: number; high: number; low: number; close: number; volume: number }

// Phase 4 types
export interface LegacySymbolItem { ticker: string; name: string; market: string }
export interface LegacyPosition {
  stock_code: string; stock_name: string; quantity: number;
  avg_price: number; current_price: number;
  eval_amount: number; profit_loss: number; profit_rate: number;
}
export interface OrderResult {
  success: boolean; stock_code: string; stock_name: string;
  action: string; quantity: number; price: number;
  order_no: string; message: string; timestamp: string;
}
export interface OrderRequest {
  stock_code: string; stock_name: string;
  action: "buy" | "sell"; quantity?: number;
  target_price?: number; strength?: number;
}
