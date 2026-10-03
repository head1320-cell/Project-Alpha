"use client";
// 매크로 분석 탭 — 개요 · 지표 · 국면 · 가치 (MacroCockpit.tsx 에서 분리, props 만 받는 표시 컴포넌트)
// BU5b-1: 카드 제목 한국어(대문자·em-dash 없음) · 색의 뜻 넷(`macroKo.ts`) · "mock" 꼬리표 제거(연습용은 머리 칩 하나 — BU5a 규칙) ·
//   지연 로더마다 불러오는 중 / ★실패 + 다시 시도★ / 값 · 서버가 쓴 설명 문장은 고치지 않고 `data-server` 로 표시한다.
//   그림은 하나도 지우지 않았다(사용자 상시 규칙). 클래스명은 E2E 계약이라 그대로(`.mc-card`·`.mc-heat-cell`·`#mc-panel-*`).

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { Notice, Unknown } from "@/shared/ui/tx";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard, Activity, Target, Scale, Boxes, Sparkles,
  TrendingUp, TrendingDown, ArrowRightLeft, Play, GitCompare, Crosshair,
} from "lucide-react";
import type { MacroSeries } from "@/entities/macro/api";
import { stressColor } from "@/entities/macro/api";
import { MODE_KO, regimeName } from "@/entities/macro/regimeKo";
import type { CausalGraph, CbSentiment, MacroCorrelations, MacroRecommend, MacroStrategies, MacroTiming, MacroTrajectory, StrategyDetail, TacticalHolding, TacticalStrategy } from "@/entities/macro/analysisModel";
import { analysisApi } from "@/entities/macro/analysisApi";
import {
  type MacroCore, type Market, loadStrategies, loadRecommend, loadSeries, resolveQuadrant,
  loadCorrelations, loadTiming, loadTrajectory, loadStrategyDetail,
} from "@/entities/macro/data";
import {
  RegimeScatter, CycleClock, ArcGauge, YieldCurveChart, IndicatorCard, ZHeatmap,
  ValuationBars, HoldingsDonut, donutColor, SignalBadge, CompositeRow,
  fmtNum, fmtZ, fmtPct, sigColor, zFill,
  ProbBars, AxisBreakdown, CbGauge, AllocAttribution, AllocBands, CausalGraphView,
} from "./cockpitParts";
import {
  CorrMatrix, RollingCorrChart, AvgCorrChart, ComponentBars, TimingHistory, TrendTable, RegimeTrajectory,
} from "./analyticsParts";
import {
  CycleStripGrid, AxisStackChart, AssetStripGrid, KrUsCompareTable, LevelLegend,
} from "./visualParts";
import { STRESS_KO, TILT_KO, TILT_STEP, ym } from "./macroKo";
import type { AssetStrips, AxisHistory, CycleStrips, KrUsCompare } from "@/entities/macro/analysisModel";

/** 지연 로더 실패 — 그 카드 안에서 말한다(role=alert) + [다시 시도]. 다른 카드는 산다. */
function LoadFail({ title, onRetry }: { title: string; onRetry?: () => void }) {
  return (
    <Notice tone="danger" title={title}>
      서버에 닿지 못했거나 계산이 실패했어요.
      {onRetry && <div className="mc-act"><button type="button" className="tx-btn tx-btn--sub" onClick={onRetry}>다시 시도</button></div>}
    </Notice>
  );
}
const Loading = ({ children }: { children: React.ReactNode }) => <p className="mc-loading">{children}</p>;

/** 수익률 곡선 역전 글자(서버 bp 그대로). 판단 색 없이 글자로. */
const invTag = (r: { yield_inversion?: boolean; inversion_severity?: number | null }) =>
  r.yield_inversion ? <span className="mc-warn">역전{typeof r.inversion_severity === "number" ? ` ${Math.round(r.inversion_severity)}bp` : ""}</span> : null;

// ─────────────────────────────────────────────────────────────────────────────
// 개요
// ─────────────────────────────────────────────────────────────────────────────
export function OverviewTab({ core, regime, quad, recommend, onTransplant, onDrill, krus, onRetryKrus }: {
  core: MacroCore; regime: NonNullable<MacroCore["regime"]>; quad: string; recommend: MacroRecommend | null;
  onTransplant: (sid: string, name: string) => void; onDrill: (id: string) => void;
  /** undefined = 아직 · null = 실패 · 값 = 받음 */
  krus?: KrUsCompare | null; onRetryKrus?: () => void;
}) {
  const yc = regime.yield_curve;
  const allInd = (core.dashboard?.themes ?? []).flatMap((t) => t.indicators);
  const extreme = [...allInd].filter((i) => i.z_score != null).sort((a, b) => Math.abs(b.z_score!) - Math.abs(a.z_score!)).slice(0, 6);
  const mode = MODE_KO[regime.recommended_mode] ?? regime.recommended_mode;
  return (
    <div className="mc-grid">
      <div className="mc-card span2">
        <div className="mc-card-h">국면 좌표(성장 × 물가)</div>
        <RegimeScatter g={regime.growth_axis} i={regime.inflation_axis} />
        {regime.description && <p className="mc-card-note" data-server>{regime.description}</p>}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">한국 · 미국 비교 <span className="mc-card-sub">같은 방식으로 바꾼 z(지난 평균에서 떨어진 정도)를 나란히 놓았어요</span></div>
        {krus === undefined && <Loading>한국·미국 비교를 계산하는 중이에요</Loading>}
        {krus === null && <LoadFail title="한국·미국 비교를 불러오지 못했어요" onRetry={onRetryKrus} />}
        {krus && <KrUsCompareTable data={krus} />}
        {krus?.note && <p className="mc-card-note" data-server>{krus.note}</p>}
      </div>
      <div className="mc-card">
        <div className="mc-card-h">경기순환 시계</div>
        <div className="mc-center"><CycleClock g={regime.growth_axis} i={regime.inflation_axis} size={196} /></div>
      </div>
      <div className="mc-card">
        <div className="mc-card-h">시장 스트레스 <span className="mc-card-sub">0은 잔잔하고 100은 불안해요</span></div>
        <ArcGauge value={regime.stress_score} label="/100" sub={`권장 단계 ‘${mode}’`} />
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">추천 자산배분 <span className="mc-card-sub">{regimeName(quad)} 국면 기준 · 규칙·성과·AI 점수를 합쳤어요</span></div>
        {recommend?.top && Array.isArray(recommend.top.holdings_final) ? (
          <div className="mc-reco-mini">
            {recommend.low_conviction && (
              <p className="mc-warn mc-warn--line">
                확신이 낮아요(신뢰도 {(recommend.confidence * 100).toFixed(0)}%). 현금성 자산을 {recommend.top.cash_overlay_pct.toFixed(0)}%로 늘렸어요.
              </p>
            )}
            <div className="mc-reco-mini-l">
              <HoldingsDonut holdings={recommend.top.holdings_final} size={120} />
            </div>
            <div className="mc-reco-mini-r">
              <div className="mc-reco-mini-nm"><b>{recommend.top.name}</b><SignalBadge signal={recommend.top.signal} /></div>
              <dl className="mc-reco-mini-stats">
                <div><dt>적합도</dt><dd>{recommend.top.fit_score.toFixed(0)}</dd></div>
                <div><dt>종합</dt><dd>{recommend.top.composite.toFixed(0)}</dd></div>
                <div><dt>신뢰도</dt><dd>{(recommend.confidence * 100).toFixed(0)}%</dd></div>
              </dl>
              <div className="mc-reco-mini-hold">
                {recommend.top.holdings_final.slice(0, 6).map((h, idx) => (
                  <span key={h.ticker} className="mc-hchip"><i style={{ background: donutColor(idx, recommend.top!.holdings_final.length) }} aria-hidden />{h.us_label} {h.weight}%</span>
                ))}
              </div>
              <button type="button" className="mc-bt-btn tx-btn tx-btn--sub" onClick={() => onTransplant(recommend.top.id, recommend.top.name)}>이 전략 백테스트하기</button>
            </div>
          </div>
        ) : <div className="mc-empty-sm">추천 자산배분이 아직 없어요</div>}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">수익률 곡선 {invTag(regime)}</div>
        {yc?.points?.length ? <YieldCurveChart points={yc.points} /> : <div className="mc-empty-sm">곡선 자료가 없어요</div>}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">평균에서 가장 먼 지표 <span className="mc-card-sub">z 크기 순 6개 · 누르면 36개월 흐름을 봐요</span></div>
        <div className="mc-ext">
          {extreme.map((ind) => (
            <button type="button" key={ind.id} className="mc-ext-row" onClick={() => onDrill(ind.id)}>
              <span className="mc-ext-nm">{ind.name}</span>
              <span className="mc-ext-v">{fmtNum(ind.latest)} {ind.unit}</span>
              <span className="mc-ext-z"><i style={{ background: zFill(ind.z_score) }} aria-hidden />z {fmtZ(ind.z_score)}</span>
            </button>
          ))}
          {!extreme.length && <div className="mc-empty-sm">지표 자료가 없어요</div>}
        </div>
        {!!extreme.length && <LevelLegend lo="평균보다 낮아요" hi="평균보다 높아요" />}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 지표
// ─────────────────────────────────────────────────────────────────────────────
export function IndicatorsTab({ core, onDrill, cbSent, onRetryCb }: { core: MacroCore; onDrill: (id: string) => void; cbSent?: CbSentiment | null; onRetryCb?: () => void }) {
  const d = core.dashboard;
  const [q, setQ] = useState("");
  if (!d) return <div className="mc-empty-sm">지표 자료가 없어요</div>;
  // 지표 찾기 — 30개 넘는 지표에서 원하는 것을 바로
  const themes = q.trim()
    ? d.themes.map((t) => ({ ...t, indicators: t.indicators.filter((i) => (i.name + i.id).toLowerCase().includes(q.trim().toLowerCase())) })).filter((t) => t.indicators.length)
    : d.themes;
  const n = d.themes.reduce((a, t) => a + t.indicators.length, 0);
  return (
    <div className="mc-stack">
      <input className="mc-search" placeholder="지표 찾기(예: CPI, 실업, 금리, VIX)"
        value={q} onChange={(e) => setQ(e.target.value)} aria-label="지표 찾기" />
      {/* 글을 자료로: 중앙은행 정책문의 말투(딱딱한 지표가 늦게 나오는 것을 보완) */}
      <div className="mc-card">
        <div className="mc-card-h">중앙은행 말투(긴축 쪽 · 완화 쪽) <span className="mc-card-sub">정책문에서 긴축 쪽 낱말과 완화 쪽 낱말이 얼마나 나오는지 셌어요</span></div>
        {cbSent === undefined && <Loading>정책문을 읽는 중이에요</Loading>}
        {cbSent === null && <LoadFail title="중앙은행 말투를 불러오지 못했어요" onRetry={onRetryCb} />}
        {cbSent && (
          <div className="mc-cbg-grid">
            <CbGauge name="미국 연준(FOMC 성명)" bank={cbSent.banks.fed} />
            <CbGauge name="한국은행(통화정책방향)" bank={cbSent.banks.bok} />
          </div>
        )}
        {cbSent?.method && <p className="mc-card-note">계산 방법: <span data-server>{cbSent.method}</span></p>}
      </div>
      <div className="mc-card">
        <div className="mc-card-h">지표 지도(지표 {n}개) <span className="mc-card-sub">z는 지난 5년 평균에서 표준편차 몇 개만큼 떨어졌는지예요. 칸을 누르면 36개월 흐름을 봐요.</span></div>
        <ZHeatmap themes={themes} onPick={(ind) => onDrill(ind.id)} />
        <LevelLegend lo="평균보다 낮아요" hi="평균보다 높아요" />
      </div>
      {themes.map((t) => (
        <div key={t.key} className="mc-card">
          <div className="mc-card-h">{t.label} <span className="mc-card-sub">지표 {t.indicators.length}개 · ▲▼는 지난번보다 오르고 내린 폭이에요</span></div>
          {t.indicators.length ? (
            <div className="mc-indgrid">{t.indicators.map((ind) => <IndicatorCard key={ind.id} ind={ind} onClick={() => onDrill(ind.id)} />)}</div>
          ) : <div className="mc-empty-sm">이 묶음에는 지표가 없어요</div>}
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 국면
// ─────────────────────────────────────────────────────────────────────────────
export function RegimeTab({ regime, traj, onRetryTraj, strips, onRetryStrips, axisHist, onRetryAxis }: {
  /** undefined = 아직 · null = 실패 · 값 = 받음 */
  regime: NonNullable<MacroCore["regime"]>; traj: MacroTrajectory | null | undefined; onRetryTraj?: () => void;
  strips?: CycleStrips | null; onRetryStrips?: () => void; axisHist?: AxisHistory | null; onRetryAxis?: () => void;
}) {
  const sc = Object.entries(regime.stress_components ?? {}).filter(([, v]) => typeof v === "number" && Number.isFinite(v));
  const tilts = Object.entries(regime.asset_tilts ?? {});
  const mode = MODE_KO[regime.recommended_mode] ?? regime.recommended_mode;
  const pctOrUnknown = (v: number | null | undefined, why: string) =>
    v != null && Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : <Unknown reason={why} />;
  return (
    <div className="mc-grid">
      <div className="mc-card span2">
        <div className="mc-card-h">국면 궤적(최근 18개월) <span className="mc-card-sub">성장·물가 축 점수가 지나온 길이에요</span></div>
        {traj === undefined ? <Loading>궤적을 불러오는 중이에요</Loading>
          : traj === null ? <LoadFail title="국면 궤적을 불러오지 못했어요" onRetry={onRetryTraj} />
          : traj.path?.length ? <RegimeTrajectory path={traj.path} />
          : <div className="mc-empty-sm">궤적을 그릴 관측이 없어요</div>}
        {!!traj?.transitions?.length && (
          <div className="mca-transitions">
            {traj.transitions.map((tr, i) => (
              <span key={i} className="mca-trans"><em>{ym(tr.t)}</em> {regimeName(tr.from)} → <b>{regimeName(tr.to)}</b></span>
            ))}
          </div>
        )}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">지금 국면 좌표(성장 × 물가)</div>
        <RegimeScatter g={regime.growth_axis} i={regime.inflation_axis} />
      </div>
      {/* 사이클 띠 — 지표 × 18개월, 칸 색 = 그 달의 z(축과 같은 방식) */}
      <div className="mc-card span2">
        <div className="mc-card-h">사이클 띠(지표별 18개월) <span className="mc-card-sub">칸 색은 그 달의 z예요(국면 축과 같은 방식으로 바꿨어요)</span></div>
        {strips === undefined && <Loading>띠를 계산하는 중이에요</Loading>}
        {strips === null && <LoadFail title="사이클 띠를 불러오지 못했어요" onRetry={onRetryStrips} />}
        {strips && <CycleStripGrid data={strips} />}
        {strips?.note && <p className="mc-card-note" data-server>{strips.note}</p>}
      </div>
      {/* 축 하위요인 — 축 점수를 지표 기여로 쌓은 달별 그림. 실패해도 카드는 남아서 실패를 말한다(예전엔 조용히 사라졌다). */}
      <div className="mc-card span2">
        <div className="mc-card-h">성장 축 · 물가 축을 만든 지표(달마다) <span className="mc-card-sub">막대는 지표마다의 기여, 선은 축 점수예요</span></div>
        {axisHist === undefined && <Loading>축 기록을 불러오는 중이에요</Loading>}
        {axisHist === null && <LoadFail title="축 기록을 불러오지 못했어요" onRetry={onRetryAxis} />}
        {axisHist && (
          <div className="mc-axstack-grid">
            <section><h4 className="mc-subh">성장 축</h4><AxisStackChart hist={axisHist} axis="growth" /></section>
            <section><h4 className="mc-subh">물가 축</h4><AxisStackChart hist={axisHist} axis="inflation" /></section>
          </div>
        )}
        {axisHist?.note && <p className="mc-card-note" data-server>{axisHist.note}</p>}
      </div>
      {/* 축 분해 — 히트맵의 수준 z 와 축 점수가 왜 다른지: 축이 실제로 먹는 바꾼 z(전년 대비)와 기여를 지표별로 */}
      {regime.axis_detail && (
        <div className="mc-card span2">
          <div className="mc-card-h">축 점수 분해(지표별 기여) <span className="mc-card-sub">전년 대비로 바꾼 수준 z 75% + 3개월 모멘텀 z 25%</span></div>
          <div className="mc-axisbd-grid">
            <AxisBreakdown title="성장 축" detail={regime.axis_detail.growth} />
            <AxisBreakdown title="물가 축" detail={regime.axis_detail.inflation} />
          </div>
          <p className="mc-card-note">지표 지도의 z는 원래 수준으로 잰 값이에요(지수형 지표는 늘 오르니 구조적으로 +가 나와요). 국면 축은 전년 대비로 바꾼 z를 써요. 두 숫자가 다른 건 모순이 아니라 바꾸는 방식이 달라서예요. 이 표가 축에 실제로 들어간 값이에요.</p>
        </div>
      )}
      {regime.regime_probs && (
        <div className="mc-card">
          <div className="mc-card-h">국면 확률 <span className="mc-card-sub">축 점수의 불확실성(±표준오차)으로 셌어요 · 합은 100%</span></div>
          <ProbBars probs={regime.regime_probs} />
        </div>
      )}
      <div className="mc-card">
        <div className="mc-card-h">순환 시계</div>
        <div className="mc-center"><CycleClock g={regime.growth_axis} i={regime.inflation_axis} size={188} /></div>
      </div>
      <div className="mc-card">
        <div className="mc-card-h">스트레스 게이지 <span className="mc-card-sub">0은 잔잔하고 100은 불안해요</span></div>
        <ArcGauge value={regime.stress_score} label="/100" sub={`권장 단계 ‘${mode}’`} />
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">스트레스 구성 항목 <span className="mc-card-sub">항목마다 0~100, 높을수록 불안해요</span></div>
        <div className="mc-stresscomp">
          {sc.map(([k, v]) => (
            <div key={k} className="mc-sc-row"><span className="mc-sc-k">{STRESS_KO[k] ?? k}</span><div className="mc-sc-bar" aria-hidden><i style={{ width: `${Math.max(2, Math.min(100, v))}%` }} /></div><span className="mc-sc-v">{v.toFixed(0)}</span></div>
          ))}
          {!sc.length && <div className="mc-empty-sm">구성 항목을 받지 못했어요</div>}
        </div>
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">수익률 곡선 {invTag(regime)}</div>
        {regime.yield_curve?.points?.length ? <YieldCurveChart points={regime.yield_curve.points} /> : <div className="mc-empty-sm">곡선 자료가 없어요</div>}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">자산군 비중 방향 <span className="mc-card-sub">지금 국면이면 규칙이 어느 쪽으로 기울이는지예요</span></div>
        <div className="mc-tilts">
          {tilts.map(([asset, sym]) => {
            const m = TILT_STEP[String(sym)] ?? { v: 0, lbl: String(sym) };
            return (
              <div key={asset} className="mc-tilt-row">
                <span className="mc-tilt-nm">{TILT_KO[asset] ?? asset}</span>
                <div className="mc-tilt-track" aria-hidden><div className="mc-tilt-fill" style={{ width: `${Math.abs(m.v) * 25}%`, ...(m.v >= 0 ? { left: "50%" } : { right: "50%" }) }} /></div>
                <span className="mc-tilt-lbl">{m.lbl}</span>
              </div>
            );
          })}
          {!tilts.length && <div className="mc-empty-sm">비중 방향을 받지 못했어요</div>}
        </div>
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">다른 계산에 넘기는 값 <span className="mc-card-sub">가치 평가와 손실 차단 기준이 이 값을 받아요</span></div>
        <dl className="mc-dparams">
          <div className="mc-dparam"><dt>무위험 금리(자기자본비용 계산에 써요)</dt><dd>{pctOrUnknown(regime.dynamic_risk_free_rate, "무위험 금리를 받지 못했어요")}</dd></div>
          <div className="mc-dparam"><dt>손실 차단 기준(최대 낙폭)</dt><dd>{pctOrUnknown(regime.dynamic_kill_dd_threshold, "손실 차단 기준을 받지 못했어요")}</dd></div>
        </dl>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 가치
// ─────────────────────────────────────────────────────────────────────────────
export function ValuationTab({ core, aStrips, onRetryAStrips }: { core: MacroCore; aStrips?: AssetStrips | null; onRetryAStrips?: () => void }) {
  const v = core.valuation;
  if (!v) return <div className="mc-empty-sm">가치 자료가 없어요</div>;
  return (
    <div className="mc-grid">
      <div className="mc-card span2">
        <div className="mc-card-h">자산군 가격 위치(18개월) <span className="mc-card-sub">지난 5년 가격 가운데 어디쯤인지(백분위)예요</span></div>
        {aStrips === undefined && <Loading>가격 위치를 계산하는 중이에요</Loading>}
        {aStrips === null && <LoadFail title="자산군 가격 위치를 불러오지 못했어요" onRetry={onRetryAStrips} />}
        {aStrips && <AssetStripGrid data={aStrips} />}
        {aStrips?.note && <p className="mc-card-note" data-server>{aStrips.note}</p>}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">자산군 가격 z(지난 5년) <span className="mc-card-sub">0보다 크면 가격이 지난 5년 평균보다 높은 구간, 작으면 낮은 구간이에요</span></div>
        <ValuationBars assets={v.assets} />
        <LevelLegend lo="가격이 평균보다 낮아요" hi="높아요" />
        <p className="mc-card-note">가격으로만 본 고평가·저평가 구간이에요(이익 대비 배수가 아니에요). 높은 구간은 되돌아올 위험이, 낮은 구간은 나눠 사기를 생각해 볼 여지가 있어요. 자산배분에서 낮은 자산 비중을 늘리는 출발점으로 써요.</p>
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">한국 시장 가치</div>
        {v.kr_market ? (
          <dl className="mc-krval">
            <div className="mc-krval-item"><dt>시장 PER 중앙값</dt><dd>{fmtNum(v.kr_market.per_median)}배</dd></div>
            <div className="mc-krval-item"><dt>시장 PBR 중앙값</dt><dd>{fmtNum(v.kr_market.pbr_median)}배</dd></div>
            <div className="mc-krval-item"><dt>표본 종목 수</dt><dd>{v.kr_market.n.toLocaleString()}개</dd></div>
          </dl>
        ) : <div className="mc-empty-sm">종목 스냅샷을 적재하면 한국 시장 PER·PBR을 보여 드려요</div>}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 05 Strategies (US⇄KR 토글)
// ─────────────────────────────────────────────────────────────────────────────
