"use client";

import { useState, useEffect, useMemo } from "react";
import {
  backtestBridgeApi, type ScreenToBacktestResult,
  type FilterGroupNode, type BacktestTrade, type MonthlyReturn, type BacktestStatistics,
  type SymbolPerf,
} from "@/lib/screenerApi";
import { getScreenerHandoff, clearScreenerHandoff, type ScreenerStrategyHandoff } from "@/lib/screenerHandoff";
import { getMacroHandoff, clearMacroHandoff, type MacroBacktestHandoff } from "@/lib/macroHandoff";
import type { StrategyBacktestConfig } from "@/lib/screenerApi";
import type { Condition } from "./ConditionFormulaEditor";
import { exportTradesCsv, exportSummaryCsv } from "@/lib/strategyStorage";
import {
  listSavedStrategies, saveBacktestStrategy, deleteSavedStrategy,
  mergeStrategy, type SavedBacktestStrategy,
} from "@/lib/backtest/strategyLibrary";
import BuyConditionPanel from "./panels/BuyConditionPanel";
import SellConditionPanel from "./panels/SellConditionPanel";
import UniversePanel, { CAPS } from "./panels/UniversePanel";
import ConditionSummary from "./panels/ConditionSummary";
import PageHeader from "@/components/layout/PageHeader";
import type { BacktestStrategy, SummaryTab } from "@/lib/backtest/strategy";

// ═══════════════════════════════════════════════════════════════════════════════
// TerminalBacktester — Variant "Strategy Performance Engine" 스타일
//   실제 run_backtest (screen-to-backtest 브릿지) 사용. 대형주 유니버스 자동 선정.
// ═══════════════════════════════════════════════════════════════════════════════

// 유동성 게이트 통과용 최소 필터 (PER은 mock에서도 항상 존재)
function largeCapFilter(): FilterGroupNode {
  return {
    logic: "AND",
    conditions: [{ kind: "field", field: "per", op: "gt", value: 0 }] as FilterGroupNode["conditions"],
    groups: [],
  };
}

// 전종목 모드: 빈 필터(사전 스크리닝 없음). per>0(적자기업 탈락)조차 걸지 않아 선택한 전 종목이
// 백테스트 유니버스로 들어간다. 진입/청산은 매 봉 조건식으로 판단.
function emptyFilter(): FilterGroupNode {
  return { logic: "AND", conditions: [] as FilterGroupNode["conditions"], groups: [] };
}

const today = () => new Date().toISOString().slice(0, 10);
const yearsAgo = (n: number) => {
  const d = today();
  return `${Number(d.slice(0, 4)) - n}${d.slice(4)}`;
};

const initialStrategy = (): BacktestStrategy => ({
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
function capsToUniverse(caps: string[]): string {
  const hasKospi = caps.some((c) => c.startsWith("kospi"));
  const hasKosdaq = caps.some((c) => c.startsWith("kosdaq"));
  if (hasKosdaq && !hasKospi) return "kosdaq150";
  return "kospi200";
}

// 조건식 → 백엔드 condition dict
const mapConds = (cs: BacktestStrategy["buy"]["conditions"]) =>
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
function strategyToRun(s: BacktestStrategy, handoff: ScreenerStrategyHandoff | null, macroCfg: StrategyBacktestConfig | null = null) {
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
function applyMacroConfig(prev: BacktestStrategy, cfg: StrategyBacktestConfig): BacktestStrategy {
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

export default function TerminalBacktester() {
  const [s, setS] = useState<BacktestStrategy>(initialStrategy);
  const [tab, setTab] = useState<SummaryTab>("buy");
  const [result, setResult] = useState<ScreenToBacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<{ phase: string; done?: number; total?: number; count?: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<ScreenerStrategyHandoff | null>(null);
  const [macroHandoff, setMacroHandoffState] = useState<MacroBacktestHandoff | null>(null);
  const [saved, setSaved] = useState<SavedBacktestStrategy[]>([]);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  useEffect(() => {
    const h = getScreenerHandoff();
    if (h) setHandoff(h);
    // 매크로 전략 백테스트 이식 → mode별(conditions/asset_alloc/engine) 백테스터 구성 프리필
    const mh = getMacroHandoff();
    if (mh?.config) {
      setMacroHandoffState(mh);
      setS((prev) => applyMacroConfig(prev, mh.config));
    }
    setSaved(listSavedStrategies());
  }, []);

  const handleSaveStrategy = () => {
    saveBacktestStrategy(s);
    setSaved(listSavedStrategies());
    setSaveMsg(`'${s.name || "내 전략"}' 저장됨 — 새로고침·재방문 후에도 유지됩니다`);
    setTimeout(() => setSaveMsg(null), 4000);
  };
  const handleLoadStrategy = (item: SavedBacktestStrategy) => {
    setS(mergeStrategy(initialStrategy(), item.strategy));
    setSaveMsg(`'${item.name}' 불러옴`);
    setTimeout(() => setSaveMsg(null), 3000);
  };
  const handleDeleteStrategy = (id: string) => {
    deleteSavedStrategy(id);
    setSaved(listSavedStrategies());
  };

  const run = async () => {
    setLoading(true); setErr(null); setResult(null); setProgress(null);
    try {
      // 스트리밍: 진행률(스크리닝→시세로드 k/total→시뮬레이션)을 받으며 실행 → 프록시 타임아웃 면제
      const r = await backtestBridgeApi.screenToBacktestStream(
        strategyToRun(s, handoff, macroHandoff?.config ?? null),
        (evt) => setProgress(evt),
      );
      if (r.error) setErr(r.message || "백테스트 실패");
      else setResult(r);
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); setProgress(null); }
  };

  const st = result?.backtest?.statistics;
  const fmt = (v: number | undefined, suffix = "", digits = 1) =>
    v === undefined ? "—" : `${v >= 0 && suffix === "%" ? "+" : ""}${v.toFixed(digits)}${suffix}`;
  const posColor = (v: number | undefined) => ((v ?? 0) >= 0 ? "#16a34a" : "#dc2626");

  return (
    <div className="tpage-fade">
      <PageHeader
        eyebrow="BACKTEST / STRATEGY ENGINE"
        index="02 / 05"
        title="Strategy Performance Engine"
        intro="룰 기반 조건식으로 매수·매도 전략을 설계하고, 과거 시세로 수익·낙폭·벤치마크 대비를 검증합니다."
        status="ENGINE · V2.0.4"
      />

      {/* 스크리너 전략 전달 배너 */}
      {handoff && (
        <div className="tscreener-handoff">
          <div className="tscreener-handoff-main">
            <span className="tscreener-handoff-badge">스크리너 전략</span>
            <span className="tscreener-handoff-text">
              {handoff.conditionSummary.length}개 조건으로 검색된 종목에 백테스트
              {handoff.resultCount > 0 && <span className="tscreener-handoff-count"> · {handoff.resultCount}종목 매칭</span>}
            </span>
            <div className="tscreener-handoff-conds">
              {handoff.conditionSummary.map((c, i) => (
                <span key={i} className="tscreener-handoff-cond">{c}</span>
              ))}
            </div>
          </div>
          <button className="tscreener-handoff-clear" onClick={() => { clearScreenerHandoff(); setHandoff(null); }}>
            ✕ 해제
          </button>
        </div>
      )}

      {/* 매크로 전략 백테스트 이식 배너 (mode별) */}
      {macroHandoff && (() => {
        const cfg = macroHandoff.config;
        const modeLabel = cfg.mode === "conditions" ? "조건식 (편집 가능)"
          : cfg.mode === "asset_alloc" ? "ETF 자산배분" : "동적 엔진 (최적화형)";
        const uni = cfg.universe_codes?.length ?? cfg.basket?.length ?? 0;
        return (
          <div className="tscreener-handoff" style={{ borderColor: "var(--t-accent)" }}>
            <div className="tscreener-handoff-main">
              <span className="tscreener-handoff-badge" style={{ background: "var(--t-accent)" }}>매크로 전략</span>
              <span className="tscreener-handoff-text">
                {cfg.name} · {modeLabel} · {uni}종 → RUN으로 백테스트
              </span>
              <div className="tscreener-handoff-conds">
                {cfg.mode === "conditions" && (cfg.buy_conditions || []).map((c, i) => (
                  <span key={i} className="tscreener-handoff-cond">{c.expr} ≥ {c.rhs ?? 0}</span>
                ))}
                {cfg.mode === "asset_alloc" && (cfg.basket || []).map((b, i) => (
                  <span key={i} className="tscreener-handoff-cond">{b.name} {b.weight_pct}%</span>
                ))}
                {cfg.mode === "engine" && <span className="tscreener-handoff-cond">{cfg.note}</span>}
              </div>
            </div>
            <button className="tscreener-handoff-clear" onClick={() => { clearMacroHandoff(); setMacroHandoffState(null); }}>
              ✕ 해제
            </button>
          </div>
        );
      })()}

      {/* 편집 영역(좌) + 조건 요약·액션(우) — 젠포트식 2컬럼 */}
      <div className="tbt-config-row">
        <div className="tbt-config-main">
          {/* 매수 / 매도 / 매매 대상 탭 */}
          <div className="tbt-mode-switch">
            <button className={`tbt-mode${tab === "buy" ? " active" : ""}`} onClick={() => setTab("buy")}>
              <span className="tbt-mode-num">01</span>
              매수 조건
              <span className="tbt-mode-sub">Buy</span>
            </button>
            <button className={`tbt-mode${tab === "sell" ? " active" : ""}`} onClick={() => setTab("sell")}>
              <span className="tbt-mode-num">02</span>
              매도 조건
              <span className="tbt-mode-sub">Sell</span>
            </button>
            <button className={`tbt-mode${tab === "universe" ? " active" : ""}`} onClick={() => setTab("universe")}>
              <span className="tbt-mode-num">03</span>
              매매 대상
              <span className="tbt-mode-sub">Universe</span>
            </button>
          </div>

          {/* 조건 설정 패널 */}
          <div style={{ marginTop: 16 }}>
            {tab === "buy" && <BuyConditionPanel s={s} set={setS} />}
            {tab === "sell" && <SellConditionPanel s={s} set={setS} />}
            {tab === "universe" && <UniversePanel s={s} set={setS} />}
          </div>
        </div>

        {/* 우측 컬럼: 조건 요약(스크롤) + 액션 박스(하단 고정) */}
        <div className="tbt-right-col">
          <ConditionSummary s={s} activeTab={tab} onTabChange={setTab} />

          {/* 액션 박스 — 전략 저장 + 백테스트 실행 (현재 설정 그대로 동작) */}
          <div className="tbt-action-box">
            <div className="tbt-action-row">
              <input value={s.name} onChange={(e) => setS((x) => ({ ...x, name: e.target.value }))}
                placeholder="전략 이름" className="tbt-action-name" />
              <button type="button" onClick={handleSaveStrategy} className="tbt-action-save"
                title="현재 설정을 브라우저에 저장 (새로고침·재방문 후에도 유지)">
                전략 저장
              </button>
            </div>
            <button type="button" onClick={run} disabled={loading} className="tbt-run" style={{ width: "100%" }}>
              {loading ? "백테스트 실행 중..." : "백테스트 실행"}
            </button>
            {saveMsg && <div className="tbt-action-msg">{saveMsg}</div>}
            {loading && (
              <div style={{ fontFamily: "var(--t-mono)", fontSize: 10, color: "var(--text-muted)", lineHeight: 1.5 }}>
                과거 시세 로드 + 전략 시뮬레이션 중... 최대 ~15초.
              </div>
            )}

            {/* 저장된 전략 — 불러오기/삭제 (영속) */}
            {saved.length > 0 && (
              <div className="tbt-saved-list">
                <div className="tbt-saved-head">저장된 전략 {saved.length}</div>
                {saved.map((item) => (
                  <div key={item.id} className="tbt-saved-item">
                    <button type="button" className="tbt-saved-load"
                      title={`불러오기 · ${new Date(item.savedAt).toLocaleString()}`}
                      onClick={() => handleLoadStrategy(item)}>
                      {item.name}
                    </button>
                    <button type="button" aria-label="삭제" className="tbt-saved-del"
                      onClick={() => handleDeleteStrategy(item.id)}>✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

        {/* 분석 뷰포트 */}
        <div className="tbt-viewport">
          {err && (
            <div className="tbt-empty" style={{ color: "#dc2626" }}>
              <div>
                <div style={{ fontFamily: "var(--t-mono)", fontSize: 11, marginBottom: 8 }}>[ ERROR ]</div>
                {err}
              </div>
            </div>
          )}

          {!result && !err && !loading && (
            <div className="tbt-empty">
              <div>
                <div style={{ fontFamily: "var(--t-mono)", fontSize: 11, marginBottom: 16 }}>[ EMPTY_STATE_NULL ]</div>
                Initialize simulation parameters to begin analysis
              </div>
            </div>
          )}

          {loading && (
            <div className="animate-fade-in">
              <div className="tbt-progress-head">
                <span className="tbt-spinner" />
                <span className="tbt-progress-label">SIMULATION RUNNING</span>
              </div>
              <BacktestProgress progress={progress} />
              {/* 결과 스켈레톤 미리보기 */}
              <div className="tbt-skeleton-stats">
                {[...Array(6)].map((_, i) => (
                  <div className="tbt-skeleton-card" key={i} style={{ animationDelay: `${i * 0.08}s` }}>
                    <div className="tbt-skeleton-line short" />
                    <div className="tbt-skeleton-line" />
                  </div>
                ))}
              </div>
              <div className="tbt-skeleton-chart" />
            </div>
          )}

          {result && st && (
            <div className="animate-fade-in">
              {/* 데이터 출처 배너 (Phase ① 실데이터 준비) */}
              <div className={`tbt-prov ${result.data_source.fully_real ? "real" : "mock"}`}>
                <span className="tbt-prov-dot" />
                <span className="tbt-prov-main">
                  {result.data_source.fully_real ? "실데이터 백테스트" : "Mock 데이터 백테스트"}
                </span>
                <span className="tbt-prov-detail">
                  시세 <b className={result.data_source.market_data === "kis_real" ? "on" : ""}>{result.data_source.market_data === "kis_real" ? "KIS 실데이터" : "mock"}</b>
                  <span className="tbt-prov-sep">·</span>
                  재무 <b className={result.data_source.fundamentals === "dart_real" ? "on" : ""}>{result.data_source.fundamentals === "dart_real" ? "DART 실데이터" : "mock"}</b>
                </span>
                {!result.data_source.fully_real && (
                  <span className="tbt-prov-note">결과는 합성 데이터 기준 — 실데이터는 GCP 배포 시</span>
                )}
              </div>
              {/* CSV 내보내기 툴바 (Phase 5-B) */}
              <div className="tbt-export-bar">
                <span className="tbt-export-label">내보내기</span>
                <button className="tbt-export-btn" onClick={() => exportTradesCsv((result.backtest.round_trips || result.backtest.trades || []) as unknown as Array<Record<string, unknown>>, s.name)}>
                  거래내역 CSV
                </button>
                <button className="tbt-export-btn" onClick={() => exportSummaryCsv(st as unknown as Record<string, number>, result.backtest.monthly_returns || [], s.name)}>
                  요약·월별 CSV
                </button>
              </div>
              {/* 6개 지표 카드 */}
              <div className="tbt-stats tbt-stats-6">
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Total Return</div>
                  <div className="tbt-stat-value" style={{ color: posColor(st.total_return_pct) }}>{fmt(st.total_return_pct, "%")}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">CAGR</div>
                  <div className="tbt-stat-value" style={{ color: posColor(st.cagr) }}>{fmt(st.cagr, "%")}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Sharpe</div>
                  <div className="tbt-stat-value" style={{ color: (st.sharpe_ratio ?? 0) >= 1 ? "#16a34a" : "var(--t-ink)" }}>{fmt(st.sharpe_ratio, "", 2)}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Sortino</div>
                  <div className="tbt-stat-value">{fmt(st.sortino_ratio, "", 2)}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Calmar</div>
                  <div className="tbt-stat-value" style={{ color: (st.calmar_ratio ?? 0) >= 0 ? "var(--t-ink)" : "#dc2626" }}>{fmt(st.calmar_ratio, "", 2)}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Max DD</div>
                  <div className="tbt-stat-value" style={{ color: "#dc2626" }}>-{Math.abs(st.max_drawdown_pct)}%</div>
                </div>
              </div>

              {/* 보조 지표 바 (승률·손익비·수수료) */}
              <div className="tbt-substats">
                <span>승률 <b>{st.win_rate}%</b></span>
                <span>손익비(PF) <b style={{ color: (st.profit_factor ?? 0) >= 1 ? "#16a34a" : "#dc2626" }}>{fmt(st.profit_factor, "", 2)}</b></span>
                <span>거래 <b>{st.num_trades}회</b></span>
                <span>평균손익 <b style={{ color: posColor(st.avg_trade_return) }}>{fmt(st.avg_trade_return, "%", 2)}</b></span>
                <span>수수료 <b>₩{Math.round(st.total_commission).toLocaleString()}</b></span>
                <span>슬리피지 <b>₩{Math.round(st.total_slippage).toLocaleString()}</b></span>
                {(st.eod_liquidated ?? 0) > 0 && (
                  <span title="백테스트 종료일에 보유 중이던 종목을 종가로 청산해 통계에 반영">기간종료 청산 <b>{st.eod_liquidated}종목</b></span>
                )}
              </div>

              {/* 전체 성과지표 — QuantStats 티어시트 */}
              <MetricsTearsheet st={st} />

              {/* 자산 곡선 */}
              <div className="tbt-chart">
                <div className="tbt-chart-head">
                  <div className="tbt-chart-title">Equity Curve</div>
                  <div className="tbt-chart-title">{result.backtest_config.period}</div>
                </div>
                {result.backtest.benchmark?.curve && result.backtest.benchmark.curve.length > 1 && (
                  <div className="tbt-bench-legend">
                    <span className="tbt-bench-item"><span className="tbt-bench-line strat" />전략</span>
                    <span className="tbt-bench-item"><span className="tbt-bench-line bench" />{result.backtest.benchmark.label}</span>
                  </div>
                )}
                <EquityChart curve={result.backtest.equity_curve} benchmark={result.backtest.benchmark?.curve} />
                {result.backtest.benchmark && result.backtest.benchmark.curve?.length > 1 && (
                  <div className="tbt-bench-metrics">
                    <div className="tbt-bench-metric">
                      <span className="tbt-bench-label">벤치마크 수익</span>
                      <span className="tbt-bench-val">{result.backtest.benchmark.total_return_pct >= 0 ? "+" : ""}{result.backtest.benchmark.total_return_pct}%</span>
                    </div>
                    <div className="tbt-bench-metric">
                      <span className="tbt-bench-label">초과수익 (α 원천)</span>
                      <span className="tbt-bench-val" style={{ color: result.backtest.benchmark.excess_return_pct >= 0 ? "#16a34a" : "#dc2626" }}>
                        {result.backtest.benchmark.excess_return_pct >= 0 ? "+" : ""}{result.backtest.benchmark.excess_return_pct}%
                      </span>
                    </div>
                    <div className="tbt-bench-metric">
                      <span className="tbt-bench-label">베타 (β)</span>
                      <span className="tbt-bench-val">{result.backtest.benchmark.beta}</span>
                    </div>
                    <div className="tbt-bench-metric">
                      <span className="tbt-bench-label">알파 (α, 연율)</span>
                      <span className="tbt-bench-val">{result.backtest.benchmark.alpha_pct >= 0 ? "+" : ""}{result.backtest.benchmark.alpha_pct}%</span>
                    </div>
                  </div>
                )}
              </div>

              {/* 낙폭 곡선 (Drawdown) */}
              {result.backtest.drawdown_curve?.length > 0 && (
                <div className="tbt-chart">
                  <div className="tbt-chart-head">
                    <div className="tbt-chart-title">Drawdown</div>
                    <div className="tbt-chart-title" style={{ color: "#dc2626" }}>최대 -{Math.abs(st.max_drawdown_pct)}%</div>
                  </div>
                  <DrawdownChart curve={result.backtest.drawdown_curve} />
                </div>
              )}

              {/* 월별 수익률 히트맵 */}
              {result.backtest.monthly_returns?.length > 0 && (
                <div className="tbt-chart">
                  <div className="tbt-chart-head">
                    <div className="tbt-chart-title">Monthly Returns</div>
                  </div>
                  <MonthlyHeatmap data={result.backtest.monthly_returns} />
                </div>
              )}

              {/* 매크로 월간 리밸런싱 전략은 개별 체결 로그가 없음 — 안내 */}
              {(result.backtest.round_trips?.length ?? 0) === 0 && result.backtest.trade_mode === "rebalance" && (
                <div className="tbt-chart">
                  <div className="tbt-chart-head"><div className="tbt-chart-title">거래내역</div></div>
                  <div style={{ padding: "14px 4px", color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 12, lineHeight: 1.6 }}>
                    월간 리밸런싱 전략 — 개별 체결 로그가 없습니다.<br />
                    월 단위 성과는 위의 <strong>Monthly Returns</strong> 히트맵을 참고하세요.
                  </div>
                </div>
              )}

              {/* 거래내역 — 종목별 요약(구 Constituents)·전체 거래내역(구 Trade Log) 통합 뷰.
                  둘 다 같은 round_trips/symbol_results 데이터를 공유 — 데이터 손실 없이 병합. */}
              <div className="tbt-chart">
                <div className="tbt-chart-head">
                  <div className="tbt-chart-title">거래내역 ({result.screened_count})</div>
                  <span style={{ fontFamily: "var(--t-mono)", fontSize: 10, padding: "2px 8px", borderRadius: 2, background: result.data_source.fully_real ? "#dcfce7" : "#fafafa", color: result.data_source.fully_real ? "#15803d" : "var(--t-muted)", border: "1px solid var(--t-border)" }}>
                    {result.data_source.fully_real ? "REAL_DATA" : "MOCK_DATA"}
                  </span>
                </div>
                <SymbolPerfTable
                  rows={result.backtest.symbol_results ?? []}
                  roundTrips={result.backtest.round_trips ?? []}
                  screened={result.screened_tickers}
                />
              </div>
            </div>
          )}
        </div>
    </div>
  );
}

// 자산 곡선 SVG
function EquityChart({ curve, benchmark }: { curve: number[]; benchmark?: number[] }) {
  if (!curve || curve.length < 2) {
    return <div style={{ height: 240, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 11 }}>NO_DATA</div>;
  }
  const W = 1000, H = 240;
  // 전략·벤치마크 공통 스케일 (둘 다 같은 축에서 비교)
  const hasBench = benchmark && benchmark.length >= 2;
  const allVals = hasBench ? [...curve, ...benchmark!] : curve;
  const min = Math.min(...allVals), max = Math.max(...allVals);
  const range = max - min || 1;
  const toPts = (arr: number[]) => arr.map((v, i) => {
    const x = (i / (arr.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const pts = toPts(curve);
  const up = curve[curve.length - 1] >= curve[0];
  const color = up ? "#16a34a" : "#dc2626";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 240, borderBottom: "1px solid var(--t-border)", borderLeft: "1px solid var(--t-border)" }} preserveAspectRatio="none">
      <polygon points={`0,${H} ${pts} ${W},${H}`} fill={color} opacity="0.06" />
      {hasBench && (
        <polyline points={toPts(benchmark!)} fill="none" stroke="#71717a" strokeWidth="1.5" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" opacity="0.8" />
      )}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// 낙폭 곡선 (0 이하 음수 영역)
function DrawdownChart({ curve }: { curve: number[] }) {
  if (!curve || curve.length < 2) {
    return <div style={{ height: 140, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 11 }}>NO_DATA</div>;
  }
  // drawdown_curve는 음수(%) 또는 비율. 절대값 최대로 정규화
  const W = 1000, H = 140;
  const vals = curve.map((v) => (v > 0 ? -v : v)); // 양수로 들어오면 음수화
  const minV = Math.min(...vals, 0);
  const range = Math.abs(minV) || 1;
  const pts = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * W;
    const y = (Math.abs(v) / range) * H; // 위에서 아래로 (0=top)
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 140, borderTop: "1px solid var(--t-border)" }} preserveAspectRatio="none">
      <polygon points={`0,0 ${pts} ${W},0`} fill="#dc2626" opacity="0.08" />
      <polyline points={pts} fill="none" stroke="#dc2626" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// 월별 수익률 히트맵
function MonthlyHeatmap({ data }: { data: Array<MonthlyReturn | number> }) {
  // data가 숫자 배열이거나 {month, return_pct} 배열 둘 다 지원
  const cells = data.map((d, i) => {
    if (typeof d === "number") return { label: `M${i + 1}`, val: d };
    return { label: d.month || `M${i + 1}`, val: d.return_pct ?? 0 };
  });
  const maxAbs = Math.max(...cells.map((c) => Math.abs(c.val)), 1);
  const colorFor = (v: number) => {
    const intensity = Math.min(1, Math.abs(v) / maxAbs);
    if (v >= 0) return `rgba(22, 163, 74, ${0.15 + intensity * 0.6})`;
    return `rgba(220, 38, 38, ${0.15 + intensity * 0.6})`;
  };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(64px, 1fr))", gap: 4 }}>
      {cells.map((c, i) => (
        <div key={i} style={{ padding: "10px 4px", borderRadius: 2, background: colorFor(c.val), textAlign: "center" }}>
          <div style={{ fontFamily: "var(--t-mono)", fontSize: 9, color: "var(--t-muted)", marginBottom: 2 }}>{c.label}</div>
          <div style={{ fontFamily: "var(--t-mono)", fontSize: 12, fontWeight: 600, color: c.val >= 0 ? "#15803d" : "#b91c1c" }}>
            {c.val >= 0 ? "+" : ""}{c.val.toFixed(1)}
          </div>
        </div>
      ))}
    </div>
  );
}

// 전체 성과지표 — QuantStats 티어시트식 그룹 표 (헤드라인 6카드 보강)
function MetricsTearsheet({ st }: { st: BacktestStatistics }) {
  const has = (x: number | null | undefined): x is number => x !== null && x !== undefined;
  const pct = (x: number | null | undefined, dp = 2) => (has(x) ? `${x.toFixed(dp)}%` : "—");
  const num = (x: number | null | undefined, dp = 2) => (has(x) ? x.toFixed(dp) : "—");
  const won = (x: number | null | undefined) => (has(x) ? `₩${Math.round(x).toLocaleString()}` : "—");
  const days = (x: number | null | undefined) => (has(x) ? `${Math.round(x)}일` : "—");
  const RED = "#dc2626", GREEN = "#16a34a";

  type Row = { label: string; value: string; hint?: string; color?: string };
  const groups: { title: string; rows: Row[] }[] = [
    {
      title: "위험 · Risk",
      rows: [
        { label: "연변동성", value: pct(st.volatility_pct), hint: "Volatility (ann.)" },
        { label: "하방변동성", value: pct(st.downside_deviation_pct), hint: "Downside deviation" },
        { label: "VaR 95%", value: pct(st.var_pct), hint: "1기간 하위 5% 손실", color: has(st.var_pct) ? RED : undefined },
        { label: "CVaR 95%", value: pct(st.cvar_pct), hint: "꼬리손실 평균", color: has(st.cvar_pct) ? RED : undefined },
        { label: "Ulcer Index", value: num(st.ulcer_index), hint: "낙폭 깊이·지속" },
        { label: "평균낙폭", value: pct(st.avg_drawdown_pct), hint: "Avg drawdown", color: has(st.avg_drawdown_pct) ? RED : undefined },
        { label: "최장 수중기간", value: days(st.max_drawdown_days), hint: "Max DD duration" },
      ],
    },
    {
      title: "위험조정 · Risk-Adjusted",
      rows: [
        { label: "Omega", value: num(st.omega, 3), hint: "이익합/손실합" },
        { label: "Gain-to-Pain", value: num(st.gain_to_pain, 3), hint: "순수익/총손실" },
        { label: "Recovery Factor", value: num(st.recovery_factor, 3), hint: "총수익/최대낙폭" },
        { label: "Tail Ratio", value: num(st.tail_ratio, 3), hint: "우측/좌측 꼬리" },
        { label: "Information Ratio", value: num(st.information_ratio, 3), hint: "벤치 초과/추적오차" },
      ],
    },
    {
      title: "분포 · Distribution",
      rows: [
        { label: "왜도 Skew", value: num(st.skew, 3), hint: "수익분포 비대칭" },
        { label: "첨도 Kurtosis", value: num(st.kurtosis, 3), hint: "초과첨도(정규=0)" },
        { label: "최고 기간수익", value: pct(st.best_period_pct), color: has(st.best_period_pct) ? GREEN : undefined },
        { label: "최저 기간수익", value: pct(st.worst_period_pct), color: has(st.worst_period_pct) ? RED : undefined },
      ],
    },
    {
      title: "거래 · Trades",
      rows: [
        { label: "손익비 Payoff", value: num(st.payoff_ratio), hint: "평균이익/평균손실" },
        { label: "기대값 Expectancy", value: won(st.expectancy), hint: "거래당 기대손익", color: has(st.expectancy) ? (st.expectancy! >= 0 ? GREEN : RED) : undefined },
        { label: "평균이익", value: won(st.avg_win), color: has(st.avg_win) ? GREEN : undefined },
        { label: "평균손실", value: won(st.avg_loss), color: has(st.avg_loss) ? RED : undefined },
        { label: "Kelly 비중", value: pct(st.kelly_pct), hint: "최적 베팅비율" },
      ],
    },
  ];
  // 값이 전부 "—"인 그룹은 숨김(엔진모드/무거래 시 거래 그룹 자동 제거)
  const visible = groups.filter((g) => g.rows.some((r) => r.value !== "—"));
  if (visible.length === 0) return null;

  return (
    <div className="tbt-chart">
      <div className="tbt-chart-head">
        <div className="tbt-chart-title">전체 성과지표</div>
        <div className="tbt-chart-title" style={{ color: "var(--t-muted)" }}>QuantStats 표준</div>
      </div>
      <div className="tbt-tearsheet">
        {visible.map((g) => (
          <div key={g.title} className="tbt-ts-group">
            <div className="tbt-ts-gtitle">{g.title}</div>
            {g.rows.map((r) => (
              <div key={r.label} className="tbt-ts-row" title={r.hint || ""}>
                <span className="tbt-ts-label">{r.label}</span>
                <span className="tbt-ts-value" style={r.color && r.value !== "—" ? { color: r.color } : undefined}>{r.value}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// 종목별 성과 테이블 — 실현손익/평균수익률/보유일/기여도, 행 클릭 → 개별 거래 상세
// 거래내역 — "종목별 요약"(구 Constituents: 종목당 집계 + 행 클릭 상세)과 "전체 거래내역"
// (구 Trade Log의 상위호환: 모든 라운드트립을 종목 구분 없이 최신순 나열, 수량/손익/사유/
// 보유일수 포함) 두 뷰를 토글. 두 뷰 모두 같은 rows/roundTrips를 공유 — 데이터 손실 없음.
function SymbolPerfTable({ rows, roundTrips, screened }: {
  rows: SymbolPerf[];
  roundTrips: BacktestTrade[];
  screened: Array<{ stock_code: string; corp_name: string }>;
}) {
  const [view, setView] = useState<"summary" | "flat">("summary");
  const [sortKey, setSortKey] = useState<string>("contribution_pct");
  const [desc, setDesc] = useState(true);
  const [tradedOnly, setTradedOnly] = useState(true);
  const [page, setPage] = useState(0);
  const [openSym, setOpenSym] = useState<string | null>(null);
  const PER_PAGE = 20;

  const sorted = useMemo(() => {
    const base = tradedOnly ? rows.filter((r) => (r.round_trips ?? 0) > 0) : [...rows];
    base.sort((a, b) => {
      const av = ((a as unknown as Record<string, unknown>)[sortKey] as number) ?? -Infinity;
      const bv = ((b as unknown as Record<string, unknown>)[sortKey] as number) ?? -Infinity;
      return desc ? bv - av : av - bv;
    });
    return base;
  }, [rows, sortKey, desc, tradedOnly]);

  // 전체 거래내역(플랫) — 청산일 기준 최신순, 청산일 없으면 진입일 기준
  const flatTrades = useMemo(() => {
    const dateOf = (t: BacktestTrade) => t.exit_date || t.entry_date || "";
    return [...roundTrips].sort((a, b) => dateOf(b).localeCompare(dateOf(a)));
  }, [roundTrips]);

  useEffect(() => { setPage(0); }, [sortKey, desc, tradedOnly, rows, view]);

  const won = (v: number | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}₩${Math.abs(Math.round(v)).toLocaleString()}`);
  const pct = (v: number | undefined, dp = 2) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(dp)}%`);
  const col = (v: number | undefined) => ((v ?? 0) >= 0 ? "#16a34a" : "#dc2626");
  const daysOf = (t: BacktestTrade) => {
    try {
      if (!t.entry_date || !t.exit_date) return "—";
      const d = Math.round((new Date(t.exit_date).getTime() - new Date(t.entry_date).getTime()) / 864e5);
      return `${Math.max(0, d)}일`;
    } catch { return "—"; }
  };
  const tradeRow = (t: BacktestTrade, i: number | string) => (
    <tr key={i}>
      <td>{t.corp_name || t.stock_code || "—"}</td>
      <td>{t.entry_date || "—"}</td>
      <td>{t.exit_date || "—"}</td>
      <td className="num">{t.entry_price?.toLocaleString() ?? "—"}</td>
      <td className="num">{t.exit_price?.toLocaleString() ?? "—"}</td>
      <td className="num">{t.quantity?.toLocaleString() ?? "—"}</td>
      <td className="num" style={{ color: col(t.return_pct), fontWeight: 600 }}>{pct(t.return_pct)}</td>
      <td className="num" style={{ color: col(t.pnl) }}>{won(t.pnl)}</td>
      <td>{daysOf(t)}</td>
      <td style={{ color: "var(--t-muted)", fontSize: 11 }}>{t.reason || "—"}</td>
    </tr>
  );

  const viewToggle = (
    <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
      {([["summary", "종목별 요약"], ["flat", "전체 거래내역"]] as const).map(([id, label]) => (
        <button key={id} type="button" onClick={() => setView(id)}
          className="tbt-export-btn" aria-pressed={view === id}
          style={view === id ? { borderColor: "var(--t-accent)", color: "var(--t-accent)" } : undefined}>
          {label}
        </button>
      ))}
    </div>
  );

  // 구버전/엔진모드 응답(symbol_results 없음) → 기존 칩 폴백 (요약 뷰만 해당, 플랫 뷰는 그대로 동작)
  if (!rows.length && view === "summary") {
    return (
      <div>
        {viewToggle}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {screened.slice(0, 12).map((t) => (
            <span key={t.stock_code} style={{ fontFamily: "var(--t-mono)", fontSize: 12, padding: "4px 10px", border: "1px solid var(--t-border)", borderRadius: 2 }}>
              {t.corp_name || t.stock_code}
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (view === "flat") {
    const pageCount = Math.max(1, Math.ceil(flatTrades.length / PER_PAGE));
    const cur = Math.min(page, pageCount - 1);
    const pageRows = flatTrades.slice(cur * PER_PAGE, (cur + 1) * PER_PAGE);
    return (
      <div>
        {viewToggle}
        {flatTrades.length === 0 ? (
          <span style={{ fontSize: 12, color: "var(--t-muted)" }}>거래 내역 없음</span>
        ) : (
          <>
            <table className="tbt-tradelog">
              <thead>
                <tr><th>종목</th><th>진입일</th><th>청산일</th><th className="num">진입가</th><th className="num">청산가</th><th className="num">수량</th><th className="num">수익률</th><th className="num">손익</th><th>보유</th><th>사유</th></tr>
              </thead>
              <tbody>
                {pageRows.map((t, i) => tradeRow(t, i))}
              </tbody>
            </table>
            {pageCount > 1 && (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, padding: "10px 0 2px", fontFamily: "var(--t-mono)", fontSize: 12 }}>
                <button className="tbt-export-btn" onClick={() => setPage(Math.max(0, cur - 1))} disabled={cur === 0}>◀ 이전</button>
                <span>{cur + 1} / {pageCount}</span>
                <button className="tbt-export-btn" onClick={() => setPage(Math.min(pageCount - 1, cur + 1))} disabled={cur >= pageCount - 1}>다음 ▶</button>
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  const pageCount = Math.max(1, Math.ceil(sorted.length / PER_PAGE));
  const cur = Math.min(page, pageCount - 1);
  const pageRows = sorted.slice(cur * PER_PAGE, (cur + 1) * PER_PAGE);
  const head = (key: string, label: string) => (
    <th className="num" style={{ cursor: "pointer" }} onClick={() => { if (sortKey === key) setDesc(!desc); else { setSortKey(key); setDesc(true); } }}>
      {label}{sortKey === key ? (desc ? " ▼" : " ▲") : ""}
    </th>
  );

  return (
    <div>
      {viewToggle}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8, fontSize: 12, color: "var(--t-muted)" }}>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
          <input type="checkbox" checked={tradedOnly} onChange={(e) => setTradedOnly(e.target.checked)} style={{ accentColor: "var(--t-accent)" }} />
          거래 발생 종목만 ({rows.filter((r) => (r.round_trips ?? 0) > 0).length}/{rows.length})
        </label>
        <span style={{ marginLeft: "auto", fontFamily: "var(--t-mono)", fontSize: 11 }}>
          행 클릭 → 개별 거래 상세
        </span>
      </div>
      <table className="tbt-tradelog">
        <thead>
          <tr>
            <th>종목</th>
            {head("round_trips", "거래")}
            {head("win_rate", "승률")}
            {head("realized_pnl", "실현손익")}
            {head("avg_return_pct", "평균수익률")}
            {head("avg_hold_days", "평균보유")}
            {head("contribution_pct", "기여도")}
          </tr>
        </thead>
        <tbody>
          {pageRows.map((r) => {
            const open = openSym === r.symbol;
            const trs = open ? roundTrips.filter((t) => t.stock_code === r.symbol) : [];
            return [
              <tr key={r.symbol} onClick={() => setOpenSym(open ? null : r.symbol)} style={{ cursor: "pointer", background: open ? "var(--t-surface)" : undefined }}>
                <td>{r.corp_name || r.symbol} <span style={{ color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 10 }}>{r.symbol}</span></td>
                <td className="num">{r.round_trips ?? 0}회</td>
                <td className="num">{(r.win_rate ?? 0).toFixed(0)}%</td>
                <td className="num" style={{ color: col(r.realized_pnl), fontWeight: 600 }}>{won(r.realized_pnl)}</td>
                <td className="num" style={{ color: col(r.avg_return_pct) }}>{pct(r.avg_return_pct)}</td>
                <td className="num">{r.avg_hold_days != null ? `${r.avg_hold_days}일` : "—"}</td>
                <td className="num">{r.contribution_pct != null ? `${r.contribution_pct}%` : "—"}</td>
              </tr>,
              open && (
                <tr key={`${r.symbol}-detail`}>
                  <td colSpan={7} style={{ padding: "6px 10px 12px", background: "var(--t-surface)" }}>
                    {trs.length === 0
                      ? <span style={{ fontSize: 12, color: "var(--t-muted)" }}>표시 가능한 개별 거래 없음 (거래 로그 500건 초과분은 생략될 수 있음)</span>
                      : (
                        <table className="tbt-tradelog" style={{ margin: 0 }}>
                          <thead>
                            <tr><th>진입일</th><th>청산일</th><th className="num">진입가</th><th className="num">청산가</th><th className="num">수량</th><th className="num">수익률</th><th className="num">손익</th><th>보유</th><th>사유</th></tr>
                          </thead>
                          <tbody>
                            {trs.map((t, i) => (
                              <tr key={i}>
                                <td>{t.entry_date || "—"}</td>
                                <td>{t.exit_date || "—"}</td>
                                <td className="num">{t.entry_price?.toLocaleString() ?? "—"}</td>
                                <td className="num">{t.exit_price?.toLocaleString() ?? "—"}</td>
                                <td className="num">{t.quantity?.toLocaleString() ?? "—"}</td>
                                <td className="num" style={{ color: col(t.return_pct), fontWeight: 600 }}>{pct(t.return_pct)}</td>
                                <td className="num" style={{ color: col(t.pnl) }}>{won(t.pnl)}</td>
                                <td>{daysOf(t)}</td>
                                <td style={{ color: "var(--t-muted)", fontSize: 11 }}>{t.reason || "—"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                  </td>
                </tr>
              ),
            ];
          })}
        </tbody>
      </table>
      {pageCount > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, padding: "10px 0 2px", fontFamily: "var(--t-mono)", fontSize: 12 }}>
          <button className="tbt-export-btn" onClick={() => setPage(Math.max(0, cur - 1))} disabled={cur === 0}>◀ 이전</button>
          <span>{cur + 1} / {pageCount}</span>
          <button className="tbt-export-btn" onClick={() => setPage(Math.min(pageCount - 1, cur + 1))} disabled={cur >= pageCount - 1}>다음 ▶</button>
        </div>
      )}
    </div>
  );
}

// 백테스트 진행 단계 — 백엔드 스트림의 실제 진행률(phase/done/total)로 구동.
// 가장 긴 "시세 데이터 로드" 단계는 종목 k/total·% 를 실시간 표시 → 빈 화면/체감 대기 제거.
function BacktestProgress({ progress }: {
  progress: { phase: string; done?: number; total?: number; count?: number } | null;
}) {
  const stages = [
    { keys: ["screening", "screened"], label: "종목 스크리닝" },
    { keys: ["loading"], label: "과거 시세 데이터 로드" },
    { keys: ["simulating", "done"], label: "포지션 시뮬레이션·성과 집계" },
  ];
  const phase = progress?.phase ?? "screening";
  const foundIdx = stages.findIndex((s) => s.keys.includes(phase));
  const activeIdx = foundIdx < 0 ? 0 : foundIdx;
  const pct = progress?.total ? Math.round(((progress.done ?? 0) / progress.total) * 100) : 0;
  return (
    <div className="tbt-stages">
      {stages.map((s, i) => {
        const cls = i < activeIdx ? " done" : i === activeIdx ? " active" : "";
        const showCount = i === activeIdx
          && (phase === "loading" || phase === "screening" || phase === "simulating")
          && !!progress?.total;
        return (
          <div key={i} className={`tbt-stage${cls}`}>
            <span className="tbt-stage-dot">{i < activeIdx ? "✓" : i + 1}</span>
            <span className="tbt-stage-label">
              {s.label}
              {showCount ? ` — ${progress?.done ?? 0}/${progress?.total} 종목 (${pct}%)` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
