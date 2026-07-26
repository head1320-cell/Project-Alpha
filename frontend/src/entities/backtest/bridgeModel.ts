import type { FilterGroupNode } from "@/shared/model/domain";
// 스크리너 → 백테스터 브릿지 모델 (백테스트 통계·거래·요청 페이로드).
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

export interface BacktestStatistics {
  total_return_pct: number;
  cagr: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  max_drawdown_pct: number;
  num_trades: number;
  win_rate: number;
  profit_factor: number;
  avg_trade_return: number;
  total_commission: number;
  total_slippage: number;
  // ── QuantStats 표준 보강 지표 (옵셔널 — 없으면 "—") ──
  volatility_pct?: number | null;
  downside_deviation_pct?: number | null;
  var_pct?: number | null;
  cvar_pct?: number | null;
  ulcer_index?: number | null;
  max_drawdown_days?: number | null;
  avg_drawdown_pct?: number | null;
  omega?: number | null;
  recovery_factor?: number | null;
  gain_to_pain?: number | null;
  tail_ratio?: number | null;
  skew?: number | null;
  kurtosis?: number | null;
  best_period_pct?: number | null;
  worst_period_pct?: number | null;
  payoff_ratio?: number | null;
  avg_win?: number | null;
  avg_loss?: number | null;
  expectancy?: number | null;
  kelly_pct?: number | null;
  information_ratio?: number | null;
  eod_liquidated?: number;          // 기간종료 청산 종목 수
}

// 종목별 성과 (symbol_results — 라운드트립 기반)
export interface SymbolPerf {
  symbol: string;
  corp_name?: string;
  total_return_pct: number;
  num_trades: number;
  round_trips?: number;
  win_rate: number;
  realized_pnl?: number;
  avg_return_pct?: number;
  avg_hold_days?: number;
  contribution_pct?: number;
}

export interface BacktestTrade {
  stock_code?: string;
  corp_name?: string;
  entry_date?: string;
  exit_date?: string;
  entry_price?: number;
  exit_price?: number;
  return_pct?: number;
  pnl?: number;
  quantity?: number;
  reason?: string;
}

export interface MonthlyReturn {
  month: string;
  return_pct: number;
}

export interface ScreenToBacktestResult {
  error?: boolean;
  message?: string;
  screened_tickers: Array<{ stock_code: string; corp_name: string; composite_score: number | null }>;
  screened_count: number;
  backtest: {
    statistics: BacktestStatistics;
    equity_curve: number[];
    equity_dates: string[];
    drawdown_curve: number[];
    monthly_returns: Array<MonthlyReturn | number>;
    benchmark?: {
      label: string;
      curve: number[];
      total_return_pct: number;
      excess_return_pct: number;
      beta: number;
      alpha_pct: number;
    };
    trades: BacktestTrade[];
    round_trips?: BacktestTrade[];   // 매수/매도 매칭 라운드트립(조건모드) — 거래로그 표시용
    trade_mode?: string;             // "per_trade"(조건모드) | "rebalance"(매크로 월간)
    symbol_results?: SymbolPerf[];   // 종목별 성과 (실현손익·평균수익률·보유일·기여도)
  };
  backtest_config: { strategy: string; period: string; initial_capital: number };
  data_source: { fundamentals: string; market_data: string; fully_real: boolean };
}

// 백테스트 고급 옵션 (수수료/슬리피지/손절/익절)
export interface BacktestAdvancedParams {
  commission_rate?: number;
  slippage_rate?: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
}

// 조건식 토큰 지원 맵 (GET /condition-tokens)
export interface TokenSupportMap {
  supported: Record<string, string>;    // 토큰 → 그룹 (base | ohlcv | fundamental | market | macro | flow | score)
  unsupported: Record<string, string>;  // 토큰 → 사유 (명시된 것만)
  default_reason: string;
  fundamental_note: string;
  market_note?: string;
  macro_note?: string;
  flow_note?: string;
  score_note?: string;                  // 점수 근사(뉴지랭크 공개 레시피) 설명
  substitutes?: Record<string, string[]>;  // 뉴지 점수류 → 대체 제안 토큰(선택 가능)
}

// 조건식 페이로드 (Genport식) — inner_*는 중첩: 순위(변화율_기간(종가,20)) 등
export interface BacktestConditionPayload {
  factor_token: string;
  function_id: string;
  params: Record<string, string>;
  op: string;
  rhs: number;
  rhs2?: number | null;
  inner_function_id?: string | null;
  inner_params?: Record<string, string> | null;
  // 두 팩터 변형(비교/큰값/작은값/변화율_팩터): 두 번째 피연산자 + 자체 중첩
  factor_token2?: string | null;
  inner2_function_id?: string | null;
  inner2_params?: Record<string, string> | null;
  // 자유 산술식 (직접 입력) — 있으면 factor_token/function 무시하고 식 평가
  expr?: string | null;
}

/** screen-to-backtest 요청 바디 — unary(screenToBacktest)와 스트리밍(screenToBacktestStream) 공용. */
export interface ScreenToBacktestBody {
  universe: string;
  custom_tickers?: string[] | null;
  filter_ast: FilterGroupNode;
  liquidity_floor: string;
  max_tickers: number;
  sort_by?: string;
  sort_dir?: string;
  sort_by_secondary?: string | null;
  sort_secondary_dir?: string;
  strategy_name: string;
  start_date: string;
  end_date: string;
  initial_capital?: number;
  commission_rate?: number;
  slippage_rate?: number;
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
  trailing_stop_pct?: number | null;
  max_positions?: number;
  buy_fill_type?: string;
  sell_fill_type?: string;
  buy_fill_offset_pct?: number;
  sell_fill_offset_pct?: number;
  buy_fill_expr?: string | null;
  sell_fill_expr?: string | null;
  expiry_fill_type?: string;
  expiry_fill_offset_pct?: number;
  buy_ladder?: Array<{ move_pct: number; weight_pct: number }> | null;
  sell_ladder?: Array<{ move_pct: number; weight_pct: number }> | null;
  expiry_sell_method?: string;
  max_buy_amount?: number | null;
  cash_reserve_pct?: number;
  asset_alloc?: {
    etf_pct: number; stock_pct: number; rebalance_months: number;
    fill_type: string; offset_pct: number;
    basket: Array<{ ticker: string; weight_pct: number }>;
  } | null;
  max_hold_days?: number | null;
  min_hold_days?: number;
  day_trade?: boolean;
  sell_divide_pct?: number;
  max_sell_divisions?: number | null;
  buy_weight_mode?: string;
  buy_divide_pct?: number;
  max_buy_per_day?: number | null;
  max_buy_count?: number | null;
  breakthrough_buy?: boolean;
  breakthrough_base_type?: string;
  breakthrough_offset_pct?: number;
  breakthrough_direction?: string;
  buy_timing?: string;
  buy_conditions?: BacktestConditionPayload[] | null;
  sell_conditions?: BacktestConditionPayload[] | null;
  buy_logic?: string | null;
  sell_logic?: string | null;
  buy_sort_expr?: string | null;
  buy_sort_desc?: boolean;
  intraday_fill?: boolean;
  buy_time_start?: string;
  buy_time_end?: string;
  sell_time_start?: string;
  sell_time_end?: string;
  rebalance_period?: string | null;
  signal_lag?: number;
  rebuy_block_days?: number;
  market_timing?: {
    index_ticker: string; action: string;
    conditions: BacktestConditionPayload[];
  } | null;
  caps?: string[] | null;
  sectors?: string[] | null;
  etf?: boolean;
  managed?: boolean;
  supervised?: boolean;
  groups?: Array<{ mode: string; tickers: string[] }> | null;
  universe_eval_cap?: number;
  allow_snapshot_fundamentals?: boolean;
}

// FastAPI 에러 응답의 detail을 사람이 읽을 수 있는 문자열로 변환.
// 보통은 string이지만, Pydantic 422 검증 실패는 detail이 [{loc,msg,type}, ...] 배열로 옴 —
// 이를 그대로 new Error()에 넣으면 "[object Object]"로 뭉개지므로 여기서 join.
function extractErrorDetail(err: unknown, fallback: string): string {
  const detail = (err as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => {
        if (d && typeof d === "object") {
          const loc = Array.isArray((d as { loc?: unknown[] }).loc) ? (d as { loc: unknown[] }).loc.join(".") : "";
          const msg = (d as { msg?: string }).msg ?? JSON.stringify(d);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(d);
      })
      .join("; ");
  }
  return fallback;
}
