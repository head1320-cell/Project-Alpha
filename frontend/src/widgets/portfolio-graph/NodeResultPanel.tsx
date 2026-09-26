"use client";
/**
 * 선택한 노드의 실행 결과 (BI3)
 * ==========================================================================
 * ★수와 함께 그 수의 신원을 보인다★ — 상태·사유·데이터 출처(합성/미상)·성과 라벨이 결과보다
 * 먼저 온다. 막힌 노드는 결과를 지어내지 않는다(`view` 가 `null`).
 */
import type { ReactNode } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PerfLabel } from "@/shared/ui/PerfLabel";
import type { PerfLabelValue } from "@/shared/ui/PerfLabel";
import type { NodeRunResult } from "@/entities/portfolio-graph";
import { CorrStressResult, FactorXrayResult, ScenarioStressResult, SensitivityResult } from "./CheckResults";
import { NeutralizeResult, ScoresResult, ScoresToWeightsResult, ScreenerResult, SleeveResult } from "./SignalResults";
import { OverlayResult, RegimeResult, SimulationResult, TimingResult } from "./MacroResults";
import { JournalResult, OrdersResult, TargetResult } from "./ActResults";
import { AttributionResult, CompanyViewsResult, StrategyBacktestResult, ValuationScoresResult } from "./StrategyResults";
import {
  AlphaPortfolioResult, AlphaValidateResult, EnsembleResult, FrontierResult, HealthResult, RegimeExplainResult,
  SleeveAnalyticsResult, ThreeWayResult,
} from "./Bl2Results";
import {
  BacktestAttributionResult, BacktestCompareResult, BacktestLoadResult, BacktestSetupResult, RunProgress,
} from "./BacktestResults";
import {
  ConsensusResult, CoverageResult, LongRunResult, MacroDashboardResult, StudioResult, YieldCurveResult,
} from "./MacroW2Results";

type Dict = Record<string, unknown>;
const STATUS_TEXT = { ok: "완료", blocked: "막힘", failed: "실패" } as const;
const pct = (v: unknown, d = 2) => (typeof v === "number" && Number.isFinite(v) ? `${v.toFixed(d)}%` : "—");
const fmt = (v: unknown, d = 2) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "—");

function WeightBars({ weights, labels }: { weights: Record<string, number>; labels?: Record<string, string> }) {
  const rows = Object.entries(weights).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const max = Math.max(1, ...rows.map(([, v]) => Math.abs(v)));
  return (
    <table className="pg-table">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td className="pg-td-name" title={k}>{labels?.[k] && labels[k] !== k ? `${labels[k]} ` : ""}<span className="pg-code">{k}</span></td>
            <td className="pg-td-bar">
              <span className={`pg-bar${v < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(v) / max) * 100}%` }} />
            </td>
            <td className="pg-td-num">{pct(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="pg-kv">
      {rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
    </dl>
  );
}

function Optimizer({ v }: { v: Dict }) {
  const cr = v.constraints_report as Dict | null;
  const belief = v.belief as Dict | undefined;
  const cap = (v.cap_missing as string[] | undefined) ?? [];
  return (
    <>
      <KV rows={[
        ["모델", String(v.model)],
        ["μ 엔진", String(v.mu_engine ?? "미상")],
        ["뷰 적용", v.views_applied ? "적용" : "적용 안 됨"],
        ["제약", cr ? `${String(cr.status)}${cr.reason ? ` — ${String(cr.reason)}` : ""}` : "없음"],
      ]} />
      {belief?.blocked && <p className="pg-warn">조건부 μ/Σ 가 막혀 표본 추정으로 계산했습니다 — {String(belief.blocked_reason)}</p>}
      {cap.length > 0 && <p className="pg-note">시가총액 미상 종목 {cap.length}개 — 시장 균형 가중은 그 종목에 대해 가정입니다.</p>}
      {((v.skipped_views as unknown[]) ?? []).length > 0 && (
        <p className="pg-warn">건너뛴 뷰: {JSON.stringify(v.skipped_views)}</p>
      )}
      <h4 className="pg-h4">최적 비중</h4>
      <WeightBars weights={(v.weights as Record<string, number>) ?? {}} labels={v.labels as Record<string, string>} />
    </>
  );
}

function Risk({ v }: { v: Dict }) {
  const rc = v.risk_contribution_optimized as Dict;
  const enb = v.enb as Dict;
  return (
    <>
      <KV rows={[
        ["포트폴리오 변동성", pct(rc?.portfolio_volatility_pct)],
        ["ENB (상관 반영)", enb?.enb == null ? `미상 — ${String(enb?.enb_reason ?? "")}` : fmt(enb.enb)],
        ["Neff (비중 집중)", enb?.neff == null ? `미상 — ${String(enb?.neff_reason ?? "")}` : fmt(enb.neff)],
        ["Σ 출처", String(rc?.sigma_source ?? "미상")],
      ]} />
      {rc?.pct ? (
        <>
          <h4 className="pg-h4">리스크 기여 (%)</h4>
          <WeightBars weights={rc.pct as Record<string, number>} />
        </>
      ) : <p className="pg-warn">리스크 기여 미상 — {String(rc?.reason ?? "사유 없음")}</p>}
    </>
  );
}

function Backtest({ v }: { v: Dict }) {
  const s = (v.summary as Dict) ?? {};
  const dates = (v.dates as string[]) ?? [];
  const eq = (v.equity_curve as number[]) ?? [];
  const bench = (v.bench_curve as number[] | null) ?? null;
  const step = Math.max(1, Math.floor(eq.length / 300));
  const data = eq.map((y, i) => ({ d: dates[i], p: y, b: bench?.[i] ?? null })).filter((_, i) => i % step === 0);
  const la = v.lookahead_evidence as Dict | undefined;
  return (
    <>
      <KV rows={[
        ["총수익", pct(s.total_return_pct)], ["CAGR", pct(s.cagr_pct)],
        ["변동성", pct(s.volatility_pct)], ["Sharpe", fmt(s.sharpe_ratio)],
        ["MDD", pct(s.max_drawdown_pct)], ["리밸런싱", `${String(v.n_rebalances ?? "—")}회`],
      ]} />
      {v.belief_note ? <p className="pg-warn">{String(v.belief_note)}</p> : null}
      {la && <p className="pg-note">룩어헤드 통제: {String(la.status ?? "미상")}{la.summary ? ` — ${String(la.summary)}` : ""}</p>}
      <div className="pg-chart">
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="d" hide />
            <YAxis domain={["auto", "auto"]} width={40} tick={{ fontSize: 10 }} />
            <Tooltip formatter={(x: number) => x?.toFixed?.(3)} />
            <Line dataKey="p" name="포트폴리오" dot={false} stroke="var(--chart-line)" strokeWidth={1.5} isAnimationActive={false} />
            {bench && <Line dataKey="b" name="벤치마크" dot={false} stroke="var(--chart-bench)" strokeWidth={1} isAnimationActive={false} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

function Returns({ v, prov }: { v: Dict; prov: Dict }) {
  const cov = (v.coverage as Dict) ?? {};
  const ex = (v.excluded as { ticker: string; reason: string }[]) ?? [];
  return (
    <>
      <KV rows={[
        ["자산 수", String(v.n_assets)],
        ["구간", `${String(cov.start ?? "?")} ~ ${String(cov.end ?? "?")} (${String(cov.n_obs ?? "?")}일)`],
        ["출처", String(cov.source ?? "미상")],
        ["데이터 등급", prov.data_grade ? String(prov.data_grade) : `미상 — ${String(prov.data_grade_reason ?? "")}`],
        ["절단일", String(cov.as_of_effective ?? "미상")],
      ]} />
      {ex.length > 0 && (
        <>
          <h4 className="pg-h4">제외된 종목</h4>
          <ul className="pg-list">{ex.map((x) => <li key={x.ticker}><span className="pg-code">{x.ticker}</span> — {x.reason}</li>)}</ul>
        </>
      )}
    </>
  );
}

function Generic({ v }: { v: Dict }) {
  return <pre className="pg-raw">{JSON.stringify(v, null, 2)}</pre>;
}

const OWN_PERF_LABEL = new Set(["scenario_stress", "strategy_backtest", "alpha_validate", "backtest_load"]);

/** 노드 종류 → 결과 그림. 없는 종류는 원자료 JSON(Generic) — 지어낸 요약을 그리지 않는다. */
const RENDERERS: Record<string, (p: { v: Dict; prov: Dict }) => ReactNode> = {
  optimizer: ({ v }) => <Optimizer v={v} />,
  risk: ({ v }) => <Risk v={v} />,
  backtest: ({ v }) => <Backtest v={v} />,
  returns: ({ v, prov }) => <Returns v={v} prov={prov} />,
  scenario_stress: ({ v, prov }) => <ScenarioStressResult v={v} prov={prov} />,
  corr_stress: ({ v }) => <CorrStressResult v={v} />,
  sensitivity: ({ v }) => <SensitivityResult v={v} />,
  factor_xray: ({ v }) => <FactorXrayResult v={v} />,
  screener: ({ v }) => <ScreenerResult v={v} />,
  factor_scores: ({ v }) => <ScoresResult v={v} />,
  alpha_score: ({ v }) => <ScoresResult v={v} />,
  scores_to_weights: ({ v }) => <ScoresToWeightsResult v={v} />,
  neutralize: ({ v }) => <NeutralizeResult v={v} />,
  sleeve_combine: ({ v }) => <SleeveResult v={v} />,
  regime: ({ v }) => <RegimeResult v={v} />,
  timing_signal: ({ v }) => <TimingResult v={v} />,
  exposure_overlay: ({ v }) => <OverlayResult v={v} />,
  timing_simulation: ({ v }) => <SimulationResult v={v} />,
  order_preview: ({ v }) => <OrdersResult v={v} />,
  target_version: ({ v }) => <TargetResult v={v} />,
  decision_journal: ({ v }) => <JournalResult v={v} />,
  strategy_backtest: ({ v }) => <StrategyBacktestResult v={v} />,
  company_views: ({ v }) => <CompanyViewsResult v={v} />,
  valuation_scores: ({ v }) => <ValuationScoresResult v={v} />,
  attribution_review: ({ v }) => <AttributionResult v={v} />,
  frontier: ({ v }) => <FrontierResult v={v} />,
  regime_ensemble: ({ v }) => <EnsembleResult v={v} />,
  regime_explain: ({ v }) => <RegimeExplainResult v={v} />,
  scenario_three_way: ({ v }) => <ThreeWayResult v={v} />,
  custom_scenario: ({ v, prov }) => <ScenarioStressResult v={v} prov={prov} />,
  strategy_health: ({ v }) => <HealthResult v={v} />,
  sleeve_analytics: ({ v }) => <SleeveAnalyticsResult v={v} />,
  alpha_validate: ({ v, prov }) => <AlphaValidateResult v={v} prov={prov} />,
  backtest_setup: ({ v }) => <BacktestSetupResult v={v} />,
  backtest_load: ({ v, prov }) => <BacktestLoadResult v={v} prov={prov} />,
  backtest_attribution: ({ v }) => <BacktestAttributionResult v={v} />,
  backtest_compare: ({ v }) => <BacktestCompareResult v={v} />,
  yield_curve: ({ v }) => <YieldCurveResult v={v} />,
  macro_dashboard: ({ v }) => <MacroDashboardResult v={v} />,
  regime_consensus: ({ v }) => <ConsensusResult v={v} />,
  regime_forecast_coverage: ({ v }) => <CoverageResult v={v} />,
  long_run: ({ v }) => <LongRunResult v={v} />,
  macro_studio: ({ v }) => <StudioResult v={v} />,
  alpha_portfolio: ({ v }) => (
    <AlphaPortfolioResult v={v} bars={<WeightBars weights={(v.weights as Record<string, number>) ?? {}}
                                                  labels={v.labels as Record<string, string> | undefined} />} />
  ),
};

export function NodeResultPanel({ kind, result, stale, extra, params, onReload }: {
  kind: string;
  result: NodeRunResult | undefined;
  stale: boolean;
  extra?: ReactNode;
  /** 노드 파라미터 — 백테스트 불러오기가 진행 중인 실행을 읽을 때 쓴다(BL3 W1). */
  params?: Record<string, unknown>;
  /** 이 노드만 다시 계산 — 진행 카드의 '결과 불러오기'. */
  onReload?: () => void;
}) {
  if (!result) {
    return <p className="pg-panel-note">아직 실행 결과가 없습니다 — 위의 “실행” 을 누르세요.</p>;
  }
  const v = result.view;
  const prov = result.provenance ?? {};
  return (
    <section className={`pg-result${stale ? " pg-result--stale" : ""}`}>
      {stale && <p className="pg-warn">이 결과는 현재 그래프의 결과가 아닙니다 — 그래프가 바뀌었습니다. 다시 실행하세요.</p>}
      <div className={`pg-node-status pg-node-status--${result.status}`}>
        <span className="pg-node-status-k">{STATUS_TEXT[result.status]}</span>
        {result.reason && <span className="pg-node-status-why">{result.reason}</span>}
      </div>
      {/* 성과 라벨 — 자기 렌더러가 숫자 옆에 직접 그리는 종류는 여기서 겹쳐 그리지 않는다. */}
      {prov.perf_label && !OWN_PERF_LABEL.has(kind) ? <div className="pg-perf"><PerfLabel value={prov.perf_label as PerfLabelValue} /></div> : null}
      {v && (RENDERERS[kind] ? RENDERERS[kind]({ v, prov }) : <Generic v={v} />)}
      {/* 진행 중·끝난 실행은 노드가 '아직' 으로 실패한다 — 그 실행을 읽기만 하며 끝나기를 기다린다. */}
      {kind === "backtest_load" && result.status === "failed" && typeof params?.run_id === "string" && onReload
        && result.reason?.startsWith("아직") && <RunProgress runId={params.run_id} onReload={onReload} />}
      {extra}
    </section>
  );
}
