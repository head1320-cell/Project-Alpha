// TerminalBacktester 전략 모델 — 순수 로직(JSX·React 없음).
// 초기 전략 · 유니버스 매핑 · 조건 변환 · 매크로 설정 반영 · run 페이로드 조립.
// (TerminalBacktester.tsx에서 분리 — 내용 불변)

import type { FilterGroupNode } from "@/shared/model";
import type { ScreenerStrategyHandoff } from "@/shared/lib/screenerHandoff";
import type { StrategyBacktestConfig } from "@/entities/macro";
import type { BacktestStrategy } from "@/entities/backtest/strategy";
import type { Condition } from "@/entities/backtest/conditionTypes";
import { CAPS } from "./panels/UniversePanel";

// ═══════════════════════════════════════════════════════════════════════════════
// TerminalBacktester — Variant "Strategy Performance Engine" 스타일
//   실제 run_backtest (screen-to-backtest 브릿지) 사용. 대형주 유니버스 자동 선정.
// ═══════════════════════════════════════════════════════════════════════════════

// 유동성 게이트 통과용 최소 필터 (PER은 mock에서도 항상 존재)
export function largeCapFilter(): FilterGroupNode {
  return {
    logic: "AND",
    conditions: [{ kind: "field", field: "per", op: "gt", value: 0 }] as FilterGroupNode["conditions"],
    groups: [],
  };
}

// 전종목 모드: 빈 필터(사전 스크리닝 없음). per>0(적자기업 탈락)조차 걸지 않아 선택한 전 종목이
// 백테스트 유니버스로 들어간다. 진입/청산은 매 봉 조건식으로 판단.
export function emptyFilter(): FilterGroupNode {
  return { logic: "AND", conditions: [] as FilterGroupNode["conditions"], groups: [] };
}

export const today = () => new Date().toISOString().slice(0, 10);
export const yearsAgo = (n: number) => {
  const d = today();
  return `${Number(d.slice(0, 4)) - n}${d.slice(4)}`;
};

export const initialStrategy = (): BacktestStrategy => ({
  name: "내 전략",
  capital: 5000, startDate: yearsAgo(3), endDate: today(), feePct: 0.15, slippagePct: 0.05,
  // 평가 종목 상한 — 기본 200(조건 추가 시에도 안전한 속도). 조건 추가만으로 자동 전종목(4000)
  // 평가로 튀어 타임아웃/네트워크 에러가 나던 문제 수정 — 큰 값은 UniversePanel에서 사용자가
  // 명시적으로 선택.
  evalCap: 200,
  liquidityGate: "off",  // 기본 전종목 — 유동성/per>0 필터로 선택이 잘리지 않게
  rebalancePeriod: "daily", signalLag: 0, cashReservePct: 0, intradayFill: false,
  assetAlloc: { enabled: false, preset: "aggressive", etfPct: 30, stockPct: 60, basket: [],
    rebalanceMonths: 3, fillType: "prev_close", offsetPct: 0 },
  marketTiming: { on: false, index: "KOSPI", mode: "block_buy", conditions: [] },
  buy: {
    enabled: true, conditions: [], logicExpr: "", primarySort: { expr: "composite_score", dir: "DESC" },
    sortExpr: "", sortExprDesc: true,
    maxStocks: 10, weightPct: 10, weightMode: "equal",
    fillType: "close", fillExpr: "", fillOffsetPct: 0, maxBuyAmount: 0,
    reBuyBlockDays: 0, maxBuyPerDay: 0, timeStart: "09:00", timeEnd: "15:30",
    splitBuy: false, ladder: [], splitBuyPct: 50, splitBuyCount: 2,
    breakthrough: false, breakthroughBaseType: "prev_high", breakthroughOffsetPct: 0,
    breakthroughDirection: "up", buyTiming: "pre_open", allowFundamentals: false,
  },
  sell: {
    enabled: true, orderType: "MARKET", fillType: "close", fillExpr: "", fillOffsetPct: 0,
    expiryFillType: "close", expiryFillOffsetPct: 0,
    takeProfit: { on: false, pct: 15 }, stopLoss: { on: false, pct: 5 },
    trailing: { on: false, pct: 3 }, holdPeriod: { on: false, min: 5 }, dayTrade: false, conditions: [], logicExpr: "",
    liquidate: { on: false, mode: "close" }, timeStart: "09:00", timeEnd: "15:30",
    splitTakeProfit: false, ladder: [], splitSellPct: 50, splitSellCount: 3,
    expirySellMethod: "all", expiryDateSell: false,
  },
  universe: {
    etf: false, managed: false, supervised: false,
    caps: CAPS.map((c) => c.id), sectors: [],
    groups: [], matched: 0, totalUniverse: 0,
    survivorshipMode: "off",
  },
});

// granular 시총군 → 백엔드 universe 프리셋(coarse). 시총군/업종 정밀 반영은 run 엔드포인트 확장 시.
export function capsToUniverse(caps: string[]): string {
  const hasKospi = caps.some((c) => c.startsWith("kospi"));
  const hasKosdaq = caps.some((c) => c.startsWith("kosdaq"));
  if (hasKosdaq && !hasKospi) return "kosdaq150";
  return "kospi200";
}

// 조건식 → 백엔드 condition dict
export const mapConds = (cs: BacktestStrategy["buy"]["conditions"]) =>
  cs.map((c) => ({
    factor_token: c.factorToken, function_id: c.functionId, params: c.params,
    op: c.op, rhs: Number(c.rhs), rhs2: c.rhs2 != null ? Number(c.rhs2) : null,
    inner_function_id: c.innerFunctionId ?? null,
    inner_params: c.innerParams ?? null,
    factor_token2: c.factorToken2 ?? null,
    inner2_function_id: c.inner2FunctionId ?? null,
    inner2_params: c.inner2Params ?? null,
    expr: c.direct ? c.expr : null,  // 직접 입력(자유 산술식)
  }));

// 전략 상태 → screenToBacktest payload 어댑터
export function strategyToRun(s: BacktestStrategy, handoff: ScreenerStrategyHandoff | null, macroCfg: StrategyBacktestConfig | null = null) {
  const { buy, sell } = s;
  const macroUniverse = macroCfg && (macroCfg.mode === "conditions" || macroCfg.mode === "engine") && macroCfg.universe_codes?.length
    ? macroCfg.universe_codes : null;
  // 생존편향 보정 모드: 시작일 당시 실제 거래 종목(상장폐지 포함) 기준으로 백엔드가 직접
  // 유니버스를 구성 — caps 등 세분화 필터는 보내지 않는다(분기 우선순위상 세분화 필터가
  // 먼저 체크되므로, 안 비우면 이 모드가 있으나 마나가 됨).
  const survivorship = s.universe.survivorshipMode ?? "off";
  return {
    universe: survivorship !== "off"
      ? (survivorship === "all" ? "all_asof" : "top200_asof")
      : capsToUniverse(s.universe.caps),
    custom_tickers: macroUniverse as string[] | null,
    // 전종목 모드(off): 사전 필터 없음 → 선택한 전 종목이 유니버스. 필터 모드: per>0 최소필터.
    filter_ast: handoff ? handoff.filterAst : (s.liquidityGate === "off" ? emptyFilter() : largeCapFilter()),
    liquidity_floor: s.liquidityGate ?? "off",
    max_tickers: buy.maxStocks,
    sort_by: buy.primarySort.expr,
    sort_dir: buy.primarySort.dir === "ASC" ? "asc" : "desc",
    sort_by_secondary: buy.secondarySort?.expr ?? null,
    sort_secondary_dir: (buy.secondarySort?.dir ?? "DESC") === "ASC" ? "asc" : "desc",
    max_positions: buy.maxStocks,
    // 스크리닝 후보 풀 크기 — 조건식 유무와 무관하게 항상 적용(백엔드가 더 이상 게이팅하지
    // 않음). 기본 200(안전) — 큰 값은 UniversePanel "평가 종목 상한"에서 명시 선택.
    universe_eval_cap: s.evalCap || 200,
    allow_snapshot_fundamentals: buy.allowFundamentals,
    // "GoldenCross"는 사용자가 이 화면에서 선택할 방법이 없는 내부 기본값이었음 — 조건 칩이
    // 비어 있어도(리스크룰만 설정) "Condition" 전략을 명시 전송해, 하드코딩된 이동평균
    // 크로스 전략(예: "데드크로스" 매도사유)이 조용히 대신 실행되는 것을 막는다. 진입/재편입은
    // 동적 재편입(빈자리 보충) 로직이 담당하고, 청산은 사용자가 설정한 조건·손절/익절/트레일링/
    // 보유기간 룰만 적용된다.
    strategy_name: macroCfg?.mode === "engine" && macroCfg.engine_strategy
      ? `tactical:${macroCfg.engine_strategy}` : "Condition",
    start_date: s.startDate, end_date: s.endDate,
    initial_capital: s.capital * 10000,
    commission_rate: s.feePct / 100,
    slippage_rate: s.slippagePct / 100,
    stop_loss_pct: sell.stopLoss.on ? sell.stopLoss.pct : null,
    take_profit_pct: sell.takeProfit.on ? sell.takeProfit.pct : null,
    trailing_stop_pct: sell.trailing.on ? sell.trailing.pct : null,
    buy_fill_type: buy.fillType,
    sell_fill_type: sell.fillType,
    buy_fill_offset_pct: buy.fillOffsetPct,
    sell_fill_offset_pct: sell.fillOffsetPct,
    buy_fill_expr: buy.fillType === "expr" ? (buy.fillExpr.trim() || null) : null,
    sell_fill_expr: sell.fillType === "expr" ? (sell.fillExpr.trim() || null) : null,
    expiry_fill_type: sell.expiryFillType,
    expiry_fill_offset_pct: sell.expiryFillOffsetPct,
    max_buy_amount: buy.maxBuyAmount > 0 ? buy.maxBuyAmount * 10000 : null,  // 만원 → 원
    cash_reserve_pct: s.cashReservePct,
    asset_alloc: s.assetAlloc.enabled && s.assetAlloc.basket.length > 0 ? {
      etf_pct: s.assetAlloc.etfPct,
      stock_pct: s.assetAlloc.stockPct,
      rebalance_months: s.assetAlloc.rebalanceMonths,
      fill_type: s.assetAlloc.fillType,
      offset_pct: s.assetAlloc.offsetPct,
      basket: s.assetAlloc.basket.map((l) => ({ ticker: l.ticker, weight_pct: l.weightPct })),
    } : null,
    max_hold_days: sell.dayTrade ? null : (sell.holdPeriod.max ?? null),
    min_hold_days: sell.dayTrade ? 0 : (sell.holdPeriod.on ? sell.holdPeriod.min : 0),
    day_trade: sell.dayTrade,
    sell_divide_pct: sell.splitTakeProfit && sell.ladder.length === 0 ? sell.splitSellPct : 100,
    max_sell_divisions: sell.splitTakeProfit && sell.ladder.length === 0 ? sell.splitSellCount : null,
    buy_weight_mode: buy.weightMode,  // equal | atr (엔진 역변동성 사이징)
    // 분할: 래더 우선 (래더 행이 있으면 가격 단계 모델, 없으면 레거시 횟수 모델)
    buy_ladder: buy.splitBuy && buy.ladder.length > 0
      ? buy.ladder.map((l) => ({ move_pct: l.movePct, weight_pct: l.weightPct })) : null,
    sell_ladder: sell.splitTakeProfit && sell.ladder.length > 0
      ? sell.ladder.map((l) => ({ move_pct: l.movePct, weight_pct: l.weightPct })) : null,
    expiry_sell_method: sell.expirySellMethod,
    buy_divide_pct: buy.splitBuy && buy.ladder.length === 0 ? buy.splitBuyPct : 100,
    max_buy_per_day: buy.maxBuyPerDay > 0 ? buy.maxBuyPerDay : null,
    max_buy_count: buy.splitBuy && buy.ladder.length === 0 ? buy.splitBuyCount : null,
    breakthrough_buy: buy.breakthrough,
    breakthrough_base_type: buy.breakthroughBaseType,
    breakthrough_offset_pct: buy.breakthroughOffsetPct,
    breakthrough_direction: buy.breakthroughDirection,
    buy_timing: buy.buyTiming,
    rebuy_block_days: buy.reBuyBlockDays,
    caps: survivorship !== "off" ? [] : s.universe.caps,
    sectors: survivorship !== "off" ? [] : s.universe.sectors,
    etf: survivorship !== "off" ? false : s.universe.etf,
    managed: survivorship !== "off" ? false : s.universe.managed,
    supervised: survivorship !== "off" ? false : s.universe.supervised,
    groups: survivorship !== "off" ? [] : s.universe.groups.map((g) => ({ mode: g.mode, tickers: g.tickers })),
    buy_conditions: mapConds(buy.conditions),
    sell_conditions: mapConds(sell.conditions),
    buy_logic: buy.logicExpr.trim() || null,
    sell_logic: sell.logicExpr.trim() || null,
    buy_sort_expr: buy.sortExpr.trim() || null,
    buy_sort_desc: buy.sortExprDesc,
    intraday_fill: s.intradayFill,
    buy_time_start: buy.timeStart.replace(":", ""),
    buy_time_end: buy.timeEnd.replace(":", ""),
    sell_time_start: sell.timeStart.replace(":", ""),
    sell_time_end: sell.timeEnd.replace(":", ""),
    rebalance_period: s.rebalancePeriod === "daily" ? null : s.rebalancePeriod,
    signal_lag: s.signalLag,
    market_timing: s.marketTiming.on && s.marketTiming.conditions.length ? {
      index_ticker: s.marketTiming.index,
      action: s.marketTiming.mode,
      conditions: mapConds(s.marketTiming.conditions),
    } : null,
  };
}

// 매크로 전략 백테스트 구성(mode별) → 백테스터 상태 프리필
export function applyMacroConfig(prev: BacktestStrategy, cfg: StrategyBacktestConfig): BacktestStrategy {
  if (cfg.mode === "asset_alloc") {
    return {
      ...prev, name: cfg.name,
      assetAlloc: {
        ...prev.assetAlloc, enabled: true, preset: "custom", etfPct: 100, stockPct: 0,
        rebalanceMonths: cfg.rebalance_months || 3,
        basket: (cfg.basket || []).map((b) => ({ ticker: b.ticker, name: b.name, weightPct: b.weight_pct })),
      },
    };
  }
  if (cfg.mode === "conditions") {
    const conds: Condition[] = (cfg.buy_conditions || []).map((c, i) => ({
      id: `mc${i}`, factorName: cfg.name, factorToken: "", functionId: "expr", params: {},
      expr: c.expr, label: cfg.name, direct: true,
      op: (c.op as Condition["op"]) || "gte", rhs: String(c.rhs ?? 0),
    }));
    return {
      ...prev, name: cfg.name, rebalancePeriod: "monthly",
      buy: {
        ...prev.buy, enabled: true, conditions: conds, logicExpr: cfg.buy_logic || "",
        maxStocks: cfg.max_tickers || prev.buy.maxStocks,
        sortExpr: cfg.sort_expr || "", sortExprDesc: cfg.sort_desc ?? true,
        primarySort: cfg.sort_expr
          ? { expr: cfg.sort_expr, dir: (cfg.sort_desc ?? true) ? "DESC" : "ASC" }
          : prev.buy.primarySort,
      },
      assetAlloc: { ...prev.assetAlloc, enabled: false },
    };
  }
  // engine: 조건 비움(백엔드가 strategy_name="tactical:.." 유지) — strategy_name·custom_tickers는 strategyToRun에서
  return { ...prev, name: cfg.name, buy: { ...prev.buy, conditions: [] }, assetAlloc: { ...prev.assetAlloc, enabled: false } };
}

