import type { FilterGroupNode } from "@/shared/model/domain";
import type { PerfLabelValue } from "@/shared/ui/PerfLabel";
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
  /**
   * ★성과의 **종류**★ — `data_source` 와 **다른 축**이다(전자: 무슨 데이터,
   * 후자: 무슨 성과). 서버가 `src/domain/perf_kind.py` 로 파생해 싣는다.
   * 없으면 화면이 `unknown` 을 그린다 — ★화면이 종류를 추론하지 않는다★.
   */
  perf_label?: PerfLabelValue | null;
  /**
   * 매크로 토큰이 **어느 시점의 값으로** 평가됐는가.
   *
   * ★매크로 토큰을 안 쓴 실행은 `null`/부재다★ — `{pit:0, live:0, ...}` 이 아니다.
   * 0 으로 채우면 "재봤더니 전부 0" 으로 읽히는데, 그것은 하지 않은 진술이다.
   * 반대로 **썼는데 전부 라이브**면 `pit_pct: 0` 이다 — 그건 측정된 사실이다.
   *
   * `live` = 그 토큰이 현재 개정본으로 평가됐다(= 룩어헤드).
   * `revision.flip_pct` = 개정이 그 **레그**의 판정을 뒤집은 봉 비율.
   * ★최종 신호가 갈린 비율이 아니다★ — 논리 결합이 흡수·증폭한다.
   */
  macro_lookahead?: {
    pit: number;
    live: number;
    blocked: number;
    pit_pct: number | null;
    tokens: Record<string, {
      path: "pit" | "live" | "blocked";
      reason: string;
      revision?: { bars: number; flip: number; flip_pct: number | null; reason: string; note: string };
    }>;
    note: string;
  } | null;
  /**
   * 재무 공시일이 **실측 접수일이었나 정적 시차 추정이었나**.
   *
   * ★PIT 재무 토큰을 안 쓴 실행은 `null`/부재다★ — `{measured:0, …}` 이 아니다.
   * 반대로 **썼는데 전부 추정**이면 `measured_pct: 0` 이다(측정된 사실).
   * `unknown` 은 빈티지 유무를 **확인하지 못한** 수이고 분모에 남는다 —
   * 추정과 같은 칸에 세면 DB 가 죽었을 때 비율이 정상으로 보인다.
   *
   * ★세는 단위는 `(종목, 기간)`★ 이지 봉도 신호도 아니다(`unit` 이 밝힌다).
   * 종목별 맵은 싣지 않는다 — 종목 수백 × 기간 수십이라 페이로드가 터진다.
   * 대신 `reasons` 가 사유 히스토그램(예시 종목 ≤3)을 든다.
   */
  fundamentals_pit?: {
    unit: string;
    measured: number;
    estimated: number;
    unknown: number;
    measured_pct: number | null;
    tickers: { measured_any: number; all_estimated: number; unknown: number; no_financials: number };
    reasons: Record<string, {
      periods: number; tickers: number; sample_tickers: string[]; reason: string;
    }>;
    lag_days: { annual: number; quarterly: number };
    same_day_guard_days: number;
    note: string;
    value_note: string;
  } | null;
  /**
   * 신호가 **어느 경로로** 났는가 — 벡터화인가 per-bar 폴백인가.
   * 실행 시간을 5배까지 가르는 값이고, 분모가 0이면 `vectorized_pct` 는 `null` 이다.
   */
  signal_path?: {
    vectorized: number; per_bar: number; failed: number;
    vectorized_pct: number | null;
  } | null;
  /**
   * 이 백테스트가 **무슨 가격을 봤는가** (`price_quality.basis_rollup`).
   *
   * ★프레임을 하나도 못 읽은 실행은 `null`★ — `{tickers: 0, …}` 이 아니다.
   * `state` 는 셋이고 **미상은 통과가 아니다**:
   *   `ok`        전부 수정주가이고 정의가 섞이지 않았다
   *   `degraded`  ★관측된★ 결함이 있다(`mixed`·`raw`·`chain_broken`·`missing`)
   *   `unknown`   결함은 안 보이지만 **못 잰 것**이 있다(라벨 없음·정의 미기록)
   *
   * ★`unlabeled` 는 `missing` 이 아니다★ — `missing` 은 "행이 없다" 는 판단이고
   * `unlabeled` 는 판단 자체가 없다(DB 를 못 읽었거나 로더를 안 거쳤다).
   * `*_tickers` 는 **표본**(최대 5)이고 정확한 개수는 `basis`/`adj_status` 에 있다.
   */
  price_basis?: {
    unit: string;
    tickers: number;
    basis: Record<string, number>;
    adj_status: Record<string, number>;
    uniform_adjusted_pct: number | null;
    adjusted_pct: number | null;
    mixed_tickers: string[];
    unadjusted_tickers: string[];
    unlabeled_tickers: string[];
    state: "ok" | "degraded" | "unknown";
    reason: string | null;
    source: string;
    version: string;
    note: string;
    /**
     * 정의가 섞인 종목을 어떻게 다뤘나 (로드맵 4단계).
     *
     * ★`excluded.count > 0` 이어도 `state` 는 `ok` 가 되지 않는다★ — 위 개수는
     * **제외 전에** 센 것이라 `mixed` 가 그대로 남아 있고, 그래야 한다.
     * 30종목을 버린 실행에 "검증됨" 을 다는 것이 *동등 품질로 위장*이다.
     * `tickers` 는 표본(최대 5), 정확한 개수는 `count` 다.
     */
    policy: "exclude" | "pass_labeled";
    excluded: { count: number; tickers: string[]; reason: string | null };
  } | null;
  /**
   * 이 백테스트의 **결정을 장 시작 전에 계산할 수 있었나** (AG).
   *
   * ★`perf_label` 과 다른 축이다★ — 저것은 *"이 수치가 무엇인가"*(백테스트/
   * 페이퍼/실계좌)이고 이것은 *"어떤 실행 가정 위에 섰나"* 다.
   *
   * 불변식은 하나다: `signal_lag >= 1` ⟺ 결정이 장 시작 전 계산 가능.
   * 체결가 유형은 **실리되 판정을 바꾸지 않는다**(별개 축).
   *
   * ★`unrecorded` 는 통과가 아니다★ — 기록 이전 런은 `signal_lag` 이 `0`
   * 이었는지 더 컸는지 **알 수 없다**. `precomputable_before_open` 이 `null`
   * 인 것이 그 뜻이고, `false` 로 그리면 없는 사실이 생긴다.
   */
  execution_assumption?: {
    state: "precomputable" | "same_bar" | "unrecorded";
    reason: string | null;
    precomputable_before_open: boolean | null;
    signal_lag: number | null;
    buy_fill_type: string | null;
    sell_fill_type: string | null;
  } | null;
  /**
   * 유니버스가 **생존편향을 보정했는가**.
   *
   * ★`effective !== requested` 그 자체가 폴백의 증거다★ — 시점 유니버스를
   * 만들지 못하면 오늘자 프리셋으로 떨어지는데, 그러면 상장폐지 종목이 빠진다.
   *
   * 네 값이고 **셋으로 줄이지 않는다**: `corrected`(실제로 세웠다) ·
   * `approximated`(시총 상위 재구성 — 지수 편입의 근사) · `not_corrected`
   * (오늘자 멤버십) · `unknown`(사용자 목록이라 **알 수 없다**).
   * ★`unknown` 은 "보정 안 됨" 이 아니다★ — 우리가 모른다는 뜻이다.
   */
  universe?: {
    requested: string;
    effective: string;
    fell_back: boolean;
    survivorship: "corrected" | "approximated" | "not_corrected" | "unknown";
    asof_date: string | null;
    reason: string | null;
    tickers_screened: number;
    note: string;
  } | null;
  /**
   * 네 축을 모은 **실행 판정** (`src/engine/run_evidence.py`).
   *
   * ★boolean 이 아니다★ — `verified`/`partial`/`unverified`/`unknown`.
   * 못 잰 것(`unknown`)과 재봤더니 나쁜 것(`degraded`)은 처방이 달라 끝까지
   * 따로 센다: `broken_axes` 와 `unknown_axes` 가 그것이다.
   *
   * `axes.macro` / `axes.fundamentals` 가 `null` 이면 **해당 없음**이다(그 토큰을
   * 안 쓴 실행). 반면 `axes.price` / `axes.universe` 는 절대 `null` 이 아니다 —
   * 못 재면 `state: "unknown"` 으로 남는다.
   */
  pit_evidence?: {
    status: "verified" | "partial" | "unverified" | "unknown";
    axes: Record<string, {
      state: "ok" | "degraded" | "unknown";
      reason: string | null;
    } | null>;
    applicable: string[];
    ok_axes: string[];
    broken_axes: string[];
    unknown_axes: string[];
    summary: string;
    note: string;
  } | null;
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
  /**
   * 매크로 토큰의 **표시 그룹** — ★목록의 단일 출처★.
   *
   * 픽커의 매크로 그룹은 이걸로 그린다. 프런트에 손으로 든 목록이 있으면 백엔드에
   * 토큰을 더해도 화면에 안 나온다(실측: 20개 중 8개가 그랬다).
   * 없거나 비면 프런트 폴백을 쓰되, 그때는 화면이 "기본값을 보이는 중" 이라 말한다.
   */
  macro_groups?: { label: string; tokens: string[] }[];
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
  /**
   * 가격 정의가 섞인 종목 처리 — 생략하면 백엔드 기본값 `exclude` 다.
   * ★기본이 제외인 이유★ 정의가 섞인 계열의 수익률은 정의가 섞인 수익률이고,
   * 소스 경계의 점프 하나(누적 수정계수 전체)가 공분산·팩터 추정을 흔든다.
   */
  price_basis_policy?: "exclude" | "pass_labeled";
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
