"use client";

import { useState, useEffect } from "react";
import {
  backtestBridgeApi, type ScreenToBacktestResult,
  type FilterGroupNode, type BacktestTrade, type MonthlyReturn,
} from "@/lib/screenerApi";
import { getScreenerHandoff, clearScreenerHandoff, type ScreenerStrategyHandoff } from "@/lib/screenerHandoff";
import { exportTradesCsv, exportSummaryCsv } from "@/lib/strategyStorage";
import {
  STRATEGY_TEMPLATES, listSavedStrategies, saveBacktestStrategy, deleteSavedStrategy,
  mergeStrategy, type SavedBacktestStrategy,
} from "@/lib/backtest/strategyLibrary";
import BuyConditionPanel from "./panels/BuyConditionPanel";
import SellConditionPanel from "./panels/SellConditionPanel";
import UniversePanel, { CAPS } from "./panels/UniversePanel";
import ConditionSummary from "./panels/ConditionSummary";
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

const today = () => new Date().toISOString().slice(0, 10);
const yearsAgo = (n: number) => {
  const d = today();
  return `${Number(d.slice(0, 4)) - n}${d.slice(4)}`;
};

const initialStrategy = (): BacktestStrategy => ({
  name: "내 전략",
  capital: 5000, startDate: yearsAgo(3), endDate: today(), feePct: 0.15, slippagePct: 0.05,
  rebalancePeriod: "daily", signalLag: 0, cashReservePct: 0, intradayFill: false,
  assetAlloc: { enabled: false, preset: "aggressive", etfPct: 30, stockPct: 60, basket: [],
    rebalanceMonths: 3, fillType: "prev_close", offsetPct: 0 },
  marketTiming: { on: false, index: "KOSPI", mode: "block_buy", conditions: [] },
  buy: {
    enabled: true, conditions: [], logicExpr: "", primarySort: { expr: "composite_score", dir: "DESC" },
    sortExpr: "", sortExprDesc: true,
    limitType: "LIMIT", maxStocks: 10, weightPct: 10, weightMode: "equal",
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
function strategyToRun(s: BacktestStrategy, handoff: ScreenerStrategyHandoff | null) {
  const { buy, sell } = s;
  return {
    universe: capsToUniverse(s.universe.caps),
    custom_tickers: null as string[] | null,
    filter_ast: handoff ? handoff.filterAst : largeCapFilter(),
    liquidity_floor: "standard",
    max_tickers: buy.maxStocks,
    sort_by: buy.primarySort.expr,
    sort_dir: buy.primarySort.dir === "ASC" ? "asc" : "desc",
    sort_by_secondary: buy.secondarySort?.expr ?? null,
    sort_secondary_dir: (buy.secondarySort?.dir ?? "DESC") === "ASC" ? "asc" : "desc",
    max_positions: buy.maxStocks,
    full_universe_eval: buy.conditions.length > 0,
    universe_eval_cap: 200,
    allow_snapshot_fundamentals: buy.allowFundamentals,
    strategy_name: "GoldenCross",
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
    caps: s.universe.caps,
    sectors: s.universe.sectors,
    etf: s.universe.etf,
    managed: s.universe.managed,
    supervised: s.universe.supervised,
    groups: s.universe.groups.map((g) => ({ mode: g.mode, tickers: g.tickers })),
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

export default function TerminalBacktester() {
  const [s, setS] = useState<BacktestStrategy>(initialStrategy);
  const [tab, setTab] = useState<SummaryTab>("buy");
  const [result, setResult] = useState<ScreenToBacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<ScreenerStrategyHandoff | null>(null);
  const [saved, setSaved] = useState<SavedBacktestStrategy[]>([]);

  useEffect(() => {
    const h = getScreenerHandoff();
    if (h) setHandoff(h);
    setSaved(listSavedStrategies());
  }, []);

  const handleSaveStrategy = () => {
    saveBacktestStrategy(s);
    setSaved(listSavedStrategies());
  };
  const handleLoadStrategy = (item: SavedBacktestStrategy) =>
    setS(mergeStrategy(initialStrategy(), item.strategy));
  const handleDeleteStrategy = (id: string) => {
    deleteSavedStrategy(id);
    setSaved(listSavedStrategies());
  };

  const run = async () => {
    setLoading(true); setErr(null); setResult(null);
    try {
      const r = await backtestBridgeApi.screenToBacktest(strategyToRun(s, handoff));
      if (r.error) setErr(r.message || "백테스트 실패");
      else setResult(r);
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  };

  const st = result?.backtest?.statistics;
  const fmt = (v: number | undefined, suffix = "", digits = 1) =>
    v === undefined ? "—" : `${v >= 0 && suffix === "%" ? "+" : ""}${v.toFixed(digits)}${suffix}`;
  const posColor = (v: number | undefined) => ((v ?? 0) >= 0 ? "#16a34a" : "#dc2626");

  return (
    <div>
      <div className="meta-stamp">
        REF_ID: ALPHA_BT_088<br />
        ENGINE: V2.0.4<br />
        AUTH: SIG_VERIFIED
      </div>

      <div className="terminal-breadcrumb">Modules / <span>Backtester</span></div>
      <h1 className="terminal-h1">Strategy Performance Engine</h1>

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

      {/* 전략 라이브러리: 이름·저장 + 템플릿 + 저장된 전략 */}
      <div style={{ marginTop: 14, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
        <input
          value={s.name}
          onChange={(e) => setS((x) => ({ ...x, name: e.target.value }))}
          placeholder="전략 이름"
          style={{ fontSize: 13, color: "var(--text-primary)", border: "1px solid var(--border-strong)",
            borderRadius: "var(--bs-border-radius)", padding: "7px 11px", width: 170, background: "var(--bg-card)" }}
        />
        <button type="button" onClick={handleSaveStrategy}
          style={{ fontSize: 13, color: "#fff", background: "var(--text-primary)", border: "none",
            borderRadius: "var(--bs-border-radius)", padding: "8px 14px", cursor: "pointer" }}>
          저장
        </button>
        <span style={{ width: 1, alignSelf: "stretch", background: "var(--border)", margin: "0 4px" }} />
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>템플릿</span>
        {STRATEGY_TEMPLATES.map((t) => (
          <button key={t.id} type="button" title={t.desc} onClick={() => setS(t.apply(initialStrategy()))}
            style={{ fontSize: 12, color: "var(--text-secondary)", background: "var(--bg-section)",
              border: "1px solid var(--border)", borderRadius: "var(--bs-border-radius)", padding: "7px 11px", cursor: "pointer" }}>
            {t.name}
          </button>
        ))}
        {saved.length > 0 && (
          <>
            <span style={{ width: 1, alignSelf: "stretch", background: "var(--border)", margin: "0 4px" }} />
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>내 전략 {saved.length}</span>
            {saved.map((item) => (
              <span key={item.id} style={{ display: "inline-flex", alignItems: "center", gap: 5,
                border: "1px solid var(--border-strong)", borderRadius: "var(--bs-border-radius)",
                background: "var(--bg-card)", padding: "6px 9px" }}>
                <button type="button" title={`불러오기 · ${new Date(item.savedAt).toLocaleDateString()}`}
                  onClick={() => handleLoadStrategy(item)}
                  style={{ fontSize: 12, color: "var(--text-primary)", background: "none", border: "none",
                    cursor: "pointer", padding: 0, maxWidth: 140, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {item.name}
                </button>
                <button type="button" aria-label="삭제" onClick={() => handleDeleteStrategy(item.id)}
                  style={{ fontSize: 12, color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                  ✕
                </button>
              </span>
            ))}
          </>
        )}
      </div>

      {/* 편집 영역(좌) + 조건 요약(우) — 젠포트식 2컬럼 */}
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

        <ConditionSummary s={s} activeTab={tab} onTabChange={setTab} />
      </div>

      {/* 실행 — 매매 대상 설정 탭에서만 노출 (혼동 방지) */}
      {tab === "universe" && (
        <div style={{ marginTop: 16 }}>
          <button className="tbt-run" onClick={run} disabled={loading} style={{ width: "100%" }}>
            {loading ? "백테스트 실행 중..." : "백테스트 실행"}
          </button>
          {loading && (
            <div style={{ fontFamily: "var(--t-mono)", fontSize: 10, color: "var(--t-muted)", marginTop: 8, lineHeight: 1.5 }}>
              과거 시세 로드 + 전략 시뮬레이션 중...<br />최대 ~15초 소요됩니다.
            </div>
          )}
        </div>
      )}

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
              <BacktestProgress />
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
                <button className="tbt-export-btn" onClick={() => exportTradesCsv((result.backtest.trades || []) as unknown as Array<Record<string, unknown>>, s.name)}>
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
              </div>

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

              {/* 거래 내역 */}
              {result.backtest.trades?.length > 0 && (
                <div className="tbt-chart">
                  <div className="tbt-chart-head">
                    <div className="tbt-chart-title">Trade Log ({result.backtest.trades.length})</div>
                    <div className="tbt-chart-title">최근 {Math.min(15, result.backtest.trades.length)}건</div>
                  </div>
                  <TradeLog trades={result.backtest.trades} />
                </div>
              )}

              {/* 종목 + 데이터 출처 */}
              <div className="tbt-chart">
                <div className="tbt-chart-head">
                  <div className="tbt-chart-title">Constituents ({result.screened_count})</div>
                  <span style={{ fontFamily: "var(--t-mono)", fontSize: 10, padding: "2px 8px", borderRadius: 2, background: result.data_source.fully_real ? "#dcfce7" : "#fafafa", color: result.data_source.fully_real ? "#15803d" : "var(--t-muted)", border: "1px solid var(--t-border)" }}>
                    {result.data_source.fully_real ? "REAL_DATA" : "MOCK_DATA"}
                  </span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {result.screened_tickers.slice(0, 12).map((t) => (
                    <span key={t.stock_code} style={{ fontFamily: "var(--t-mono)", fontSize: 12, padding: "4px 10px", border: "1px solid var(--t-border)", borderRadius: 2 }}>
                      {t.corp_name || t.stock_code}
                    </span>
                  ))}
                </div>
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

// 거래 내역 테이블
function TradeLog({ trades }: { trades: BacktestTrade[] }) {
  const rows = trades.slice(-15).reverse();
  const f = (v: number | undefined) => (v == null ? "—" : v.toLocaleString());
  return (
    <table className="tbt-tradelog">
      <thead>
        <tr>
          <th>종목</th><th>진입일</th><th>청산일</th>
          <th className="num">진입가</th><th className="num">청산가</th><th className="num">수익률</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((t, i) => (
          <tr key={i}>
            <td>{t.corp_name || t.stock_code || "—"}</td>
            <td>{t.entry_date || "—"}</td>
            <td>{t.exit_date || "—"}</td>
            <td className="num">{f(t.entry_price)}</td>
            <td className="num">{f(t.exit_price)}</td>
            <td className="num" style={{ color: (t.return_pct ?? 0) >= 0 ? "#16a34a" : "#dc2626", fontWeight: 600 }}>
              {t.return_pct == null ? "—" : `${t.return_pct >= 0 ? "+" : ""}${t.return_pct.toFixed(2)}%`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// 백테스트 진행 단계 표시 (15초 대기 체감 단축)
function BacktestProgress() {
  const stages = [
    "과거 시세 데이터 로드",
    "종목별 지표 계산",
    "진입·청산 시그널 생성",
    "포지션 시뮬레이션",
    "성과 지표 집계",
  ];
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setStage((s) => Math.min(s + 1, stages.length - 1)), 3200);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="tbt-stages">
      {stages.map((label, i) => (
        <div key={i} className={`tbt-stage${i < stage ? " done" : i === stage ? " active" : ""}`}>
          <span className="tbt-stage-dot">{i < stage ? "✓" : i + 1}</span>
          <span className="tbt-stage-label">{label}</span>
        </div>
      ))}
    </div>
  );
}
