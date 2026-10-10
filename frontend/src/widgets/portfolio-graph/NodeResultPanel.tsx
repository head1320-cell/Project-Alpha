"use client";
/**
 * 선택한 노드의 실행 결과 (BI3)
 * ==========================================================================
 * ★수와 함께 그 수의 신원을 보인다★ — 상태·사유·데이터 출처(합성/미상)·성과 라벨이 결과보다
 * 먼저 온다. 막힌 노드는 결과를 지어내지 않는다(`view` 가 `null`).
 */
import type { ReactNode } from "react";
import { RecordRobustnessResult } from "./RobustnessResults";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PerfLabel } from "@/shared/ui/PerfLabel";
import type { PerfLabelValue } from "@/shared/ui/PerfLabel";
import type { NodeRunResult } from "@/entities/portfolio-graph";
import { concentration, exposureLegs } from "@/shared/lib/exposure";
import { CorrStressResult, FactorXrayResult, ScenarioStressResult, SensitivityResult } from "./CheckResults";
import { NeutralizeResult, PortfolioCombineResult, ScoresResult, ScoresToWeightsResult, ScreenerResult, SleeveResult } from "./SignalResults";
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
import {
  CompanyValuationResult, FinancialDeepResult, MacroSensitivityResult, ReverseDcfResult, RiskDeepResult, ThesisCheckResult,
  ValuationDistributionResult,
} from "./CompanyResults";
import {
  DecisionTreeResult, DriverMcResult, EvaResult, MultiplesResult, RealOptionResult, ScenariosResult, SotpResult, ValueLayersResult,
} from "./CompanyModelResults";
import {
  BondCalcResult, CvaCalcResult, DccResult, FrtbResult, FuturesHedgeResult, HoldingVarResult, IrcCalcResult, McVarResult,
  OptionCalcResult, RollingSharpeResult, VarEsResult, VolModelsResult,
} from "./RiskResults";
import {
  CapacityResult, CashResult, CounterfactualResult, ImpactResult, ImplementResult, PairResult, RebalanceResult,
} from "./AllocExtraResults";

type Dict = Record<string, unknown>;
const STATUS_TEXT = { ok: "완료", blocked: "막힘", failed: "실패" } as const;
const pct = (v: unknown, d = 2) => (typeof v === "number" && Number.isFinite(v) ? `${v.toFixed(d)}%` : "—");
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
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

/** 서버가 찍은 μ 엔진 → 이름. ★모델 이름으로 추측하지 않는다★ — 뷰가 없으면 BL 도 시장균형이라 μ 엔진은 BL 이 아니다. */
const ENGINE_LABEL: Record<string, string> = { ep: "Entropy Pooling", bl: "Black-Litterman", mvo: "트레일링 평균 (MVO)" };
/** 비중에 μ 를 쓰지 않는 방식 — 공분산만으로 나눈다. μ 엔진 줄이 비중을 정했다고 읽히지 않게 적는다. */
const COV_ONLY = new Set(["risk_parity", "hrp", "min_var", "max_div"]);

function EngineEvidence({ v }: { v: Dict }) {
  const eng = typeof v.mu_engine === "string" ? v.mu_engine : null;
  const ep = (v.ep as Dict | null) ?? null;
  const ens = num(ep?.ens);
  const ensPrior = num(ep?.ens_prior);
  const ensDrop = ens !== null && ensPrior !== null && ens < 0.1 * ensPrior;
  return (
    <div className="pg-eng">
      <p className="pg-eng-row">
        <span>이 비중의 기대 수익(μ)</span>
        <b className="pg-eng-v" data-engine={eng ?? "unknown"}>{eng ? (ENGINE_LABEL[eng] ?? eng) : "미상"}</b>
        {ep && <span className={`pg-tag pg-tag--${ep.feasible ? "confirmed" : "failed"}`}>{ep.feasible ? "뷰 실현 가능" : "뷰 실현 불가"}</span>}
      </p>
      {COV_ONLY.has(String(v.model)) && <p className="pg-note">이 방식은 비중을 정할 때 μ 를 쓰지 않아요 — 공분산만으로 나눠요.</p>}
      {ep && (
        <>
          <p className="pg-note">반영한 뷰 {String(ep.n_views ?? "—")}개 · 유효 시나리오 {ensPrior === null ? "—" : Math.round(ensPrior)} → {ens === null ? "—" : Math.round(ens)}</p>
          {ep.confidence_used === false && (
            <p className="pg-note pg-eng-conf">엔트로피 풀링은 뷰의 신뢰도를 쓰지 않아요 — 부등식 뷰는 경성 제약이라 대응하는 손잡이가 없어요. 뷰가 과한지는 유효 시나리오 수로 봐요.</p>
          )}
          {ensDrop && <p className="pg-warn" role="status">유효 시나리오 수가 크게 무너졌어요 — 뷰가 사전분포보다 강해서 표본 몇 개에 기댄 상태예요.</p>}
          {ep.note ? <p className="pg-note">{String(ep.note)}</p> : null}
        </>
      )}
    </div>
  );
}

/** ★숏이 있으면 넷 하나로 뭉개지 않는다★ gross·net·롱·숏 네 축 + gross 기준 집중도. 롱온리면 그리지 않는다(짝). */
function LongShortLegs({ weights }: { weights: Record<string, number> }) {
  const w = Object.values(weights).filter((x) => Number.isFinite(x));
  const legs = exposureLegs(w);
  if (!legs.hasShort) return null;
  const c = concentration(w);
  const p1 = (x: number) => `${x.toFixed(1)}%`;
  return (
    <div className="pg-ls-exposure" role="note">
      <KV rows={[["총 노출 (gross)", p1(legs.gross)], ["순 노출 (net)", p1(legs.net)], ["롱", p1(legs.long)], ["숏", p1(legs.short)],
                 [`집중도 HHI (${c.basis} 기준)`, Math.round(c.hhi).toLocaleString("ko-KR")]]} />
      <p className="pg-note">숏이 있어 집중도는 |비중| 합(gross)으로 쟀어요. 롱숏 비중은 연구·백테스트용이에요 — 실행 목표로 만들면 실행할 수 없다고 막혀요.</p>
    </div>
  );
}

function Optimizer({ v }: { v: Dict }) {
  const cr = v.constraints_report as Dict | null;
  const belief = v.belief as Dict | undefined;
  const cap = (v.cap_missing as string[] | undefined) ?? [];
  const weights = (v.weights as Record<string, number>) ?? {};
  return (
    <>
      <KV rows={[
        ["모델", String(v.model)],
        ["뷰 적용", v.views_applied ? "적용" : "적용 안 됨"],
        ["제약", cr ? `${String(cr.status)}${cr.reason ? ` — ${String(cr.reason)}` : ""}` : "없음"],
      ]} />
      <EngineEvidence v={v} />
      {belief?.blocked && <p className="pg-warn">조건부 μ/Σ 가 막혀서 표본 추정으로 계산했어요 — {String(belief.blocked_reason)}</p>}
      {cap.length > 0 && <p className="pg-note">시가총액 미상 종목 {cap.length}개 — 시장 균형 가중은 그 종목에 대해 가정입니다.</p>}
      {((v.skipped_views as unknown[]) ?? []).length > 0 && (
        <p className="pg-warn">건너뛴 뷰: {JSON.stringify(v.skipped_views)}</p>
      )}
      <LongShortLegs weights={weights} />
      <h4 className="pg-h4">최적 비중</h4>
      <WeightBars weights={weights} labels={v.labels as Record<string, string>} />
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

/**
 * 룩어헤드 통제 — ★응답이 말한 것만 옮긴다★ 없거나 모르는 상태면 `unknown`(확인으로 기울지 않는다).
 * 안 잰 축은 툴팁이 아니라 목록으로 적는다 — 롤업 한 줄만으로는 묻힌다.
 */
const LA_TEXT: Record<string, string> = {
  verified: "룩어헤드 통제 확인", partial: "룩어헤드 통제 부분", unverified: "룩어헤드 결함", unknown: "룩어헤드 미상",
};
function Lookahead({ la }: { la: Dict | undefined }) {
  const st = la && typeof la.status === "string" && la.status in LA_TEXT ? la.status : "unknown";
  const axes = (la?.axes as Record<string, Dict | null> | undefined) ?? {};
  const unmeasured = ((la?.unmeasured as string[] | undefined) ?? []).map((n) => String(axes[n]?.reason ?? n));
  return (
    <div className="pg-la">
      <p className="pg-la-row">
        <span className={`pg-tag pg-tag--${st === "verified" ? "confirmed" : st === "unverified" ? "failed" : "assumed"}`} data-lookahead={st}>{LA_TEXT[st]}</span>
        {la?.summary ? <span className="pg-note">{String(la.summary)}</span> : !la ? <span className="pg-note">이 결과는 룩어헤드를 어디까지 통제했는지 말하지 않아요.</span> : null}
      </p>
      {unmeasured.length > 0 && <ul className="pg-list pg-la-unmeasured">{unmeasured.map((t, i) => <li key={i}>안 잰 것: {t}</li>)}</ul>}
    </div>
  );
}

/** 다음 구간 예측(분포 무가정) — ★적중률은 홀드아웃에서 센 값(분수까지)★ 이론값 1−α 를 적지 않는다. 없으면 사유. */
function Conformal({ cf }: { cf: Dict | null | undefined }) {
  if (!cf) return null;
  const np = cf.next_period as Dict | undefined;
  const mc = cf.measured_coverage as Dict | undefined;
  const p3 = (x: unknown) => (num(x) === null ? "—" : `${((x as number) * 100).toFixed(3)}%`);
  return (
    <div className="pg-bt-cf">
      <h4 className="pg-h4">다음 구간 예측 (분포 무가정)</h4>
      {cf.available && np ? (
        <>
          <KV rows={[
            [`일평균 수익률 ${Math.round((1 - (num(cf.alpha) ?? 0.1)) * 100)}% 구간`, `${p3(np.lower)} ~ ${p3(np.upper)}`],
            ["점추정", p3(np.point)], ["보정 쌍", String(cf.n_pairs ?? "—")],
            ["실측 적중률", mc?.available && num(mc.coverage) !== null && num(mc.hits) !== null && num(mc.n) !== null
              ? `${((mc.coverage as number) * 100).toFixed(1)}% (${String(mc.hits)}/${String(mc.n)})`
              : <span className="pg-bt-cf-na">{String(mc?.reason ?? "적중률을 잴 표본이 없어요.")}</span>],
          ]} />
        </>
      ) : <p className="pg-warn pg-bt-cf-na">{String(cf.reason ?? "구간을 계산할 수 없어요.")}</p>}
      {cf.note ? <p className="pg-note">{String(cf.note).replace(/\*\*/g, "")}</p> : null}
    </div>
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
      <Lookahead la={la} />
      <Conformal cf={v.conformal as Dict | null | undefined} />
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

function Current({ v }: { v: Dict }) {
  const zero = (v.zero_filled as string[] | undefined) ?? [];
  const labels = (v.labels as Record<string, string>) ?? {};
  return (
    <>
      <p className="pg-note pg-current-basis">{String(v.basis ?? "")}</p>
      <LongShortLegs weights={(v.weights as Record<string, number>) ?? {}} />
      <WeightBars weights={(v.weights as Record<string, number>) ?? {}} labels={labels} />
      {zero.length > 0 && <p className="pg-note">비중을 적지 않은 종목은 0% 예요: {zero.map((z) => labels[z] ?? z).join(", ")}</p>}
    </>
  );
}

// ── BT7 — 종목 고르기 · 내 생각 · 기대 수익 설정: 원시 JSON 대신 표·목록. 서버 값만 쓴다(모르는 값은 그대로 · 지어내지 않는다).

function UniverseResult({ v }: { v: Dict }) {
  const tickers = (v.tickers as string[] | undefined) ?? [];
  const labels = (v.labels as Record<string, string> | undefined) ?? {};
  const weights = v.weights as Record<string, number> | null | undefined;
  const unknown = (v.unknown_tickers as { codes?: string[]; note?: string | null } | undefined) ?? {};
  return (
    <>
      <p className="pg-note">종목 {tickers.length}개{v.benchmark ? ` · 비교 기준 ${String(v.benchmark)}` : ""}</p>
      {weights ? <WeightBars weights={weights} labels={labels} /> : (
        <table className="pg-table pg-universe-table">
          <tbody>
            {tickers.map((t) => (
              <tr key={t}><td className="pg-td-name">{labels[t] && labels[t] !== t ? `${labels[t]} ` : ""}<span className="pg-code">{t}</span></td></tr>
            ))}
          </tbody>
        </table>
      )}
      {!weights && <p className="pg-note">지금 비중은 적지 않았어요 — 비중이 필요한 노드는 이 목록만 받아요.</p>}
      {(unknown.codes ?? []).length > 0 && (
        <p className="pg-warn">이름을 찾지 못한 종목: {(unknown.codes ?? []).join(", ")}{unknown.note ? ` — ${unknown.note}` : ""}</p>
      )}
    </>
  );
}

function ViewsResult({ v }: { v: Dict }) {
  type View = { assets?: string[]; weights?: Record<string, number> | null; direction?: number; magnitude_pct?: number | null;
                confidence?: number | null; label?: string | null };
  const views = (v.views as View[] | undefined) ?? [];
  if (!views.length) return <p className="pg-note">적은 생각이 없어요 — 비중 계산은 과거 기준으로만 해요.</p>;
  return (
    <ul className="pg-list pg-views-list">
      {views.map((x, i) => (
        <li key={i} className="pg-view-row">
          <b>{x.label ?? (x.assets ?? []).join(" · ")}</b>
          {" "}{x.direction == null ? "방향 모름" : x.direction > 0 ? "오를 것" : x.direction < 0 ? "내릴 것" : "그대로"}
          {typeof x.magnitude_pct === "number" ? ` ${x.magnitude_pct > 0 ? "+" : ""}${x.magnitude_pct.toFixed(1)}%` : ""}
          {typeof x.confidence === "number" ? ` · 확신 ${Math.round(x.confidence * 100)}%` : " · 확신 모름"}
        </li>
      ))}
    </ul>
  );
}

const ESTIMATE_KEYS: Record<string, string> = {
  conditional: "경기 국면 반영", require_verified_macro: "확인된 매크로만", regime_weighting: "국면 가중 방식",
  regime_mode: "국면 판정 시점", rebalance: "다시 정하는 주기",
};

function EstimateResult({ v }: { v: Dict }) {
  const settings = (v.settings as Record<string, unknown> | undefined) ?? {};
  const show = (x: unknown) => (x === true ? "켬" : x === false ? "끔" : x == null ? "모름" : String(x));
  return (
    <>
      {v.note ? <p className="pg-note">{String(v.note)}</p> : null}
      <table className="pg-table pg-estimate-table">
        <tbody>
          {Object.entries(settings).map(([k, x]) => (
            <tr key={k}><td className="pg-td-name">{ESTIMATE_KEYS[k] ?? <span className="pg-code">{k}</span>}</td>
              <td className="pg-td-num">{typeof x === "string" ? <span className="pg-code">{x}</span> : show(x)}</td></tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Generic({ v }: { v: Dict }) {
  return <pre className="pg-raw">{JSON.stringify(v, null, 2)}</pre>;
}

const OWN_PERF_LABEL = new Set(["scenario_stress", "strategy_backtest", "alpha_validate", "backtest_load", "counterfactual"]);

/** 노드 종류 → 결과 그림. 없는 종류는 원자료 JSON(Generic) — 지어낸 요약을 그리지 않는다. */
const RENDERERS: Record<string, (p: { v: Dict; prov: Dict }) => ReactNode> = {
  optimizer: ({ v }) => <Optimizer v={v} />,
  current_weights: ({ v }) => <Current v={v} />,
  risk: ({ v }) => <Risk v={v} />,
  backtest: ({ v }) => <Backtest v={v} />,
  universe: ({ v }) => <UniverseResult v={v} />,
  views: ({ v }) => <ViewsResult v={v} />,
  estimate: ({ v }) => <EstimateResult v={v} />,
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
  portfolio_combine: ({ v }) => <PortfolioCombineResult v={v} />,
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
  record_robustness: ({ v }) => <RecordRobustnessResult v={v} />,
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
  company_valuation: ({ v }) => <CompanyValuationResult v={v} />,
  reverse_dcf: ({ v }) => <ReverseDcfResult v={v} />,
  valuation_distribution: ({ v }) => <ValuationDistributionResult v={v} />,
  financial_deep: ({ v }) => <FinancialDeepResult v={v} />,
  risk_deep: ({ v }) => <RiskDeepResult v={v} />,
  company_macro_sensitivity: ({ v }) => <MacroSensitivityResult v={v} />,
  thesis_check: ({ v }) => <ThesisCheckResult v={v} />,
  company_eva: ({ v }) => <EvaResult v={v} />,
  company_value_layers: ({ v }) => <ValueLayersResult v={v} />,
  company_multiples: ({ v }) => <MultiplesResult v={v} />,
  company_driver_mc: ({ v }) => <DriverMcResult v={v} />,
  company_scenarios: ({ v }) => <ScenariosResult v={v} />,
  company_decision_tree: ({ v }) => <DecisionTreeResult v={v} />,
  company_sotp: ({ v }) => <SotpResult v={v} />,
  company_real_option: ({ v }) => <RealOptionResult v={v} />,
  var_es: ({ v }) => <VarEsResult v={v} />,
  mc_var: ({ v }) => <McVarResult v={v} />,
  vol_models: ({ v }) => <VolModelsResult v={v} />,
  holding_var: ({ v }) => <HoldingVarResult v={v} />,
  frtb_es: ({ v }) => <FrtbResult v={v} />,
  rolling_sharpe: ({ v }) => <RollingSharpeResult v={v} />,
  dcc_corr: ({ v }) => <DccResult v={v} />,
  option_calc: ({ v }) => <OptionCalcResult v={v} />,
  bond_calc: ({ v }) => <BondCalcResult v={v} />,
  futures_hedge: ({ v }) => <FuturesHedgeResult v={v} />,
  cva_calc: ({ v }) => <CvaCalcResult v={v} />,
  irc_calc: ({ v }) => <IrcCalcResult v={v} />,
  rebalance_decision: ({ v }) => <RebalanceResult v={v} />,
  implement_exposures: ({ v }) => <ImplementResult v={v} />,
  pair_spread: ({ v }) => <PairResult v={v} />,
  market_impact: ({ v }) => <ImpactResult v={v} />,
  cash_yield: ({ v }) => <CashResult v={v} />,
  strategy_capacity: ({ v }) => <CapacityResult v={v} />,
  counterfactual: ({ v, prov }) => <CounterfactualResult v={v} prov={prov} />,
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
    return <p className="pg-panel-note">아직 계산하지 않았어요 — 위의 ‘계산하기’를 누르세요.</p>;
  }
  const v = result.view;
  const prov = result.provenance ?? {};
  return (
    <section className={`pg-result${stale ? " pg-result--stale" : ""}`}>
      {stale && <p className="pg-warn">설정이 바뀌어서 이 결과는 지금 그래프와 달라요 — 다시 계산해 주세요.</p>}
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
