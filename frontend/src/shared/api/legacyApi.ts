// ═══════════════════════════════════════════════════════════════════════════════
// shared/api/legacyApi — 초기 대시보드/파생상품 시절의 단일 api 객체.
//
// ★현황(실측)★ 외부에서 import 되는 것은 `api` 하나뿐이고, 실제로 호출되는 메서드는
// 7개다: optionPrice·bondAnalytics·futuresHedge·cva(widgets/derivatives, BU7c) · dbStatus/ingest/ingestDoctor(widgets/admin).
// 이 파일의 타입 12개는 **어디에서도 import 되지 않는다** — 파일 내부 반환형 주석 전용.
// (BU7c 의 `BondOut`·`HedgeOut`·`CvaOut` 셋은 예외 — `widgets/derivatives` 가 import 한다.)
//
// 그래서 BacktestResult/Position/SymbolItem 세 이름이 entities 의 정본과 충돌해
// grep 이 두 곳을 물어 왔다. Legacy* 접두사를 붙여 정본 쪽만 검색되게 했다
// (타입 전용 개명 — 런타임 영향 0). 정본은 각각:
//   entities/backtest/chartModel.ts · entities/trading/liveModel.ts · entities/company/model.ts
//
// 미사용 메서드 정리는 별개 판단이라 손대지 않았다.
// ═══════════════════════════════════════════════════════════════════════════════
import { API_BASE as BASE } from "@/shared/api/apiBase";
import { authHeaders } from "@/shared/api/authToken";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    // ★인증 헤더를 한 곳에서 얹는다★(AC7). `...init` 뒤에 두어 호출자의 headers 를
    // 덮어쓰지 않도록 병합한다 — 예전엔 `...init` 이 headers 를 통째로 날렸다.
    headers: { "Content-Type": "application/json", ...init?.headers, ...authHeaders() },
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
      // ★적재 레지스트리 — UI 가 테이블 목록을 하드코딩하지 않는다★
      // 예전엔 DbStatusPanel 이 라벨 6개와 버튼 6개를 직접 들고 있었고, 그래서
      // 백엔드에 macro 를 더해도 화면에는 안 나왔다. 이제 백엔드가 열거한다.
      // null = 레지스트리를 못 읽음(빈 목록 아님 — datasets_error 에 사유).
      datasets?: Array<{
        key: string; label: string; source: string; table: string;
        slice_of: string | null; tools: string[]; required_env: string[];
        env_ready: boolean | null; triggerable: boolean; note: string | null;
      }> | null;
      datasets_error?: string;
      // 매크로 가용성 — 적재 테이블이 아니라 **조회 시점 라이브 호출**의 상태다.
      macro?: {
        ok: string[];
        unavailable: Record<string, { reason: string; at: number }>;
        note: string; fail_ttl_sec?: number;
      } | null;
    }>("/api/v1/data/db-status"),

  /** 종목별 커버리지 — ★온디맨드★ (daily_prices 는 수백만 행이라 자동 실행 금지) */
  dataCoverage: (target: string, start: string, end: string) =>
    get<{
      key: string; label: string; table: string; start: string; end: string;
      tickers_total: number | null; tickers_covering: number | null;
      covering_pct?: number | null; measured: boolean; reason: string | null;
    }>(`/api/v1/data/coverage?target=${encodeURIComponent(target)}`
       + `&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),

  /**
   * 출처별 연구 등급 (스펙 §6.1 · Phase 8b).
   * ★"가져올 수 있다" 와 "과거 검증에 쓸 수 있다" 는 다른 축이다★ 두 축을 따로 받는다 —
   * 합쳐서 보여주면 조회되는 모든 것을 백테스트에 써도 된다고 읽힌다.
   */
  sourceHonesty: () =>
    get<{
      mock_mode: boolean;
      sources: {
        id: string; label: string;
        data_status: string; research_usage: string; reason: string;
        rows?: number; max_date?: string | null;
      }[];
    }>("/api/v1/data/source-honesty"),

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

  // 옵션 — 백엔드 `derivatives_routes.analyze_option`(블랙-숄즈 유럽형). 예전 `/option-price`·`/price-curve` 는
  // 서버에 없는 주소였다(BL3 W4 감사) — 없는 주소를 부르는 함수를 남기지 않는다.
  optionPrice: (body: unknown) => post<unknown>("/analyze-option", body),
  // BU7c — 서버에 있던 계산기 셋을 /derivatives 탭으로 잇는다(본문 칸 이름은 서버 스키마 `legacy_schemas` 그대로).
  bondAnalytics: (body: { face_value: number; coupon_rate: number; ytm: number; years_to_maturity: number; freq: number }) =>
    post<BondOut>("/analyze-bond", body),
  futuresHedge: (body: { portfolio_value: number; current_beta: number; target_beta: number; futures_price: number; multiplier: number }) =>
    post<HedgeOut>("/calculate-hedge", body),
  cva: (body: Record<string, number | string>) => post<CvaOut>("/calculate-cva", body),
};

// ── 파생 계산기 응답(BU7c) — 서버 `FICCEngine.bond_analytics` · `HedgingSimulator.equity_futures_hedge` · `CVAEngine.full_cva_report` ──
export interface BondOut { Price: number; Macaulay_Duration: number; Modified_Duration: number; Convexity: number; BPV: number; DV01: number }
export interface HedgeOut {
  current_beta: number; target_beta: number; contract_value: number; raw_contracts: number; contracts_to_trade: number;
  action: string; beta_after_rounding: number; expected_var_reduction_pct: number | null; reduction_basis: string;
  reduction_reason: string | null; hedge_notional: number;
}
export interface CvaOut {
  pd_from_cds: Record<string, number>;
  exposure_profile: { epe: number; peak_ee: number; ee_values: number[] };
  unilateral_cva: { cva_amount: number; cva_pct_of_notional: number; cva_spread_bps: number; n_intervals: number };
  bilateral_cva: { cva_amount: number; dva_amount: number; bcva_amount: number; interpretation: string };
  stressed_cva: { base_cva: number; stressed_cva: number; stress_loss: number; stress_loss_pct: number; shocks_applied: { spread_shock_bps: number; exposure_shock_pct: number } };
}

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
      // 누락 비용 옵트인 셋 (AK). ★기본 0 — 안 켠 것이지 없는 것이 아니다★
      // 성분별 상태와 사유는 `cost_model` 블록에 있다.
      total_tax?: number;
      total_spread?: number;
      total_impact?: number;
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
  commission: number; slippage: number;
  // ★어느 거래가 세금을 냈는지 총액만으로는 볼 수 없다★ (AK) — 기본 0.
  // `tax` 는 매도에만 붙고, `impact` 는 참여율을 못 구하면 0 이지만 그때는
  // `cost_model.components.impact.state` 가 `unmeasurable` 이다.
  tax?: number; spread?: number; impact?: number;
  pnl: number | null; reason: string;
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
