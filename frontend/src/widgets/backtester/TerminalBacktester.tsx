"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { backtestRunApi } from "@/entities/backtest-run/api";
import { type BacktestStatistics, type BacktestTrade, type MonthlyReturn, type ScreenToBacktestResult, type SymbolPerf } from "@/entities/backtest/bridgeModel";
import type { FilterGroupNode } from "@/shared/model/domain";
import { getScreenerHandoff, clearScreenerHandoff, type ScreenerStrategyHandoff } from "@/shared/lib/screenerHandoff";
import { getMacroHandoff, clearMacroHandoff, type MacroBacktestHandoff } from "@/entities/macro/handoff";
import type { StrategyBacktestConfig } from "@/entities/macro/analysisModel";
import type { Condition } from "./ConditionFormulaEditor";
import { exportTradesCsv, exportSummaryCsv } from "@/shared/lib/strategyStorage";
import {
  listSavedStrategies, saveBacktestStrategy, deleteSavedStrategy,
  mergeStrategy, type SavedBacktestStrategy,
} from "@/entities/backtest/strategyLibrary";
import BuyConditionPanel from "./panels/BuyConditionPanel";
import SellConditionPanel from "./panels/SellConditionPanel";
import UniversePanel, { CAPS } from "./panels/UniversePanel";
import ConditionSummary from "./panels/ConditionSummary";
import type { BacktestStrategy, SummaryTab } from "@/entities/backtest/strategy";
import {
  applyMacroConfig, capsToUniverse, emptyFilter, initialStrategy, strategyToRun, today, yearsAgo,
} from "./strategyModel";
import {
  BacktestProgress, DrawdownChart, EquityChart, MetricsTearsheet, MonthlyHeatmap, SymbolPerfTable,
} from "./TerminalBacktester.ui";

// ═══════════════════════════════════════════════════════════════════════════════
// TerminalBacktester — Variant "Strategy Performance Engine" 스타일
//   실제 run_backtest (screen-to-backtest 브릿지) 사용. 대형주 유니버스 자동 선정.
// ═══════════════════════════════════════════════════════════════════════════════

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

  const router = useRouter();
  // Backtest 클릭 → durable BacktestRun 생성 → 전용 로딩 페이지로 이동(결과는 고정 URL에서).
  // 설정 폼 아래에 결과를 렌더하지 않는다(스펙). 유효 run_id 확보 전엔 이동하지 않는다.
  const run = async () => {
    setLoading(true); setErr(null); setResult(null); setProgress(null);
    try {
      const config = strategyToRun(s, handoff, macroHandoff?.config ?? null) as unknown as Record<string, unknown>;
      const stratName = String(config.strategy_name ?? handoff?.conditionSummary?.[0] ?? "백테스트").slice(0, 100);
      const { run_id } = await backtestRunApi.create({ config, strategy_name: stratName });
      router.push(`/backtest/runs/${run_id}/loading`);
    } catch (e) {
      setErr((e as Error).message || "백테스트 생성 실패");
      setLoading(false);
    }
  };

  const st = result?.backtest?.statistics;
  const fmt = (v: number | undefined, suffix = "", digits = 1) =>
    v === undefined ? "—" : `${v >= 0 && suffix === "%" ? "+" : ""}${v.toFixed(digits)}${suffix}`;
  const posColor = (v: number | undefined) => ((v ?? 0) >= 0 ? "#16a34a" : "#dc2626");

  return (
    <div className="tpage-fade bt2">
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
              <div className="bt-empty-glyph" aria-hidden="true">
                <svg width="26" height="26" viewBox="0 0 26 26" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2 22h22" />
                  <path d="M4 22V13l5 4 5-8 5 6 3-9" />
                </svg>
              </div>
              <div className="bt-empty-kbd">[ AWAITING_SIMULATION ]</div>
              <div className="bt-empty-title">전략을 실행할 준비가 되었습니다</div>
              <div className="bt-empty-sub">
                좌측에서 매수·매도 조건과 매매 대상을 설정한 뒤 우측의 <b>백테스트 실행</b>을 누르면
                자산곡선·성과지표·거래내역이 여기에 표시됩니다.
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
                <div className="tbt-stat tbt-stat-hero">
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
