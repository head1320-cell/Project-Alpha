"use client";
// 매크로 콕핏 탭 — 01 Overview · 02 Indicators · 03 Regime · 04 Valuation
// JSX는 한 줄도 바꾸지 않고 그대로 옮겼다 — 클래스명이 E2E 계약이므로.
// (MacroCockpit.tsx에서 분리, props만 받는 표시 컴포넌트)

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard, Activity, Target, Scale, Boxes, Sparkles,
  TrendingUp, TrendingDown, ArrowRightLeft, Play, GitCompare, Crosshair,
} from "lucide-react";
import type { MacroSeries } from "@/entities/macro/api";
import { stressColor } from "@/entities/macro/api";
import type { CausalGraph, CbSentiment, MacroCorrelations, MacroRecommend, MacroStrategies, MacroTiming, MacroTrajectory, StrategyDetail, TacticalHolding, TacticalStrategy } from "@/entities/macro/analysisModel";
import { analysisApi } from "@/entities/macro/analysisApi";
import {
  type MacroCore, type Market, loadStrategies, loadRecommend, loadSeries, resolveQuadrant,
  loadCorrelations, loadTiming, loadTrajectory, loadStrategyDetail,
} from "@/entities/macro/data";
import {
  RegimeScatter, CycleClock, ArcGauge, YieldCurveChart, IndicatorCard, ZHeatmap,
  ValuationBars, HoldingsDonut, donutColor, SignalBadge, CompositeRow,
  fmtNum, fmtZ, fmtPct, sigColor,
  ProbBars, AxisBreakdown, CbGauge, AllocAttribution, AllocBands, CausalGraphView,
} from "./cockpitParts";
import {
  CorrMatrix, RollingCorrChart, AvgCorrChart, ComponentBars, TimingHistory, TrendTable, RegimeTrajectory,
} from "./analyticsParts";
import {
  CycleStripGrid, AxisStackChart, AssetStripGrid, KrUsCompareTable, buildBriefing,
  RegimeDonutCard, StressModeCard,
} from "./visualParts";
import type { AssetStrips, AxisHistory, CycleStrips, KrUsCompare } from "@/entities/macro/analysisModel";

// ─────────────────────────────────────────────────────────────────────────────
// 01 Overview
// ─────────────────────────────────────────────────────────────────────────────
export function OverviewTab({ core, regime, quad, recommend, onTransplant, onDrill, krus }: {
  core: MacroCore; regime: NonNullable<MacroCore["regime"]>; quad: string; recommend: MacroRecommend | null;
  onTransplant: (sid: string, name: string) => void; onDrill: (id: string) => void;
  krus?: KrUsCompare | null;
}) {
  const yc = regime.yield_curve;
  const allInd = (core.dashboard?.themes ?? []).flatMap((t) => t.indicators);
  const extreme = [...allInd].filter((i) => i.z_score != null).sort((a, b) => Math.abs(b.z_score!) - Math.abs(a.z_score!)).slice(0, 6);
  return (
    <div className="mc-grid">
      <div className="mc-card span2">
        <div className="mc-card-h">국면 좌표 — 성장 × 물가</div>
        <RegimeScatter g={regime.growth_axis} i={regime.inflation_axis} />
        <p className="mc-card-note">{regime.description}</p>
      </div>
      {/* 국가경제 비교 (밸리AI '국가경제 분석'의 2국 정직 버전) */}
      <div className="mc-card span2">
        <div className="mc-card-h">국가경제 비교 — KR vs US <span className="mc-card-sub">동일 변환 z 나란히</span></div>
        {krus === undefined && <div className="mc-empty-sm">비교 계산 중…</div>}
        {krus === null && <div className="mc-empty-sm">비교 로드 실패</div>}
        {krus && <KrUsCompareTable data={krus} />}
        {krus && <p className="mc-card-note">{krus.note}</p>}
      </div>
      <div className="mc-card">
        <div className="mc-card-h">경기순환 시계</div>
        <div className="mc-center"><CycleClock g={regime.growth_axis} i={regime.inflation_axis} size={196} /></div>
      </div>
      <div className="mc-card">
        <div className="mc-card-h">시장 스트레스</div>
        <ArcGauge value={regime.stress_score} color={stressColor(regime.stress_score)} label="STRESS" sub={regime.recommended_mode} />
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">추천 자산배분 <span className="mc-card-sub">{quad} 국면 · 규칙+성과+AI</span></div>
        {recommend?.top && Array.isArray(recommend.top.holdings_final) ? (
          <div className="mc-reco-mini">
            {recommend.low_conviction && (
              <div className="mc-warn" style={{ marginBottom: 6 }}>
                저확신(신뢰도 {(recommend.confidence * 100).toFixed(0)}%) — 현금성 {recommend.top.cash_overlay_pct.toFixed(0)}%로 배분 확대
              </div>
            )}
            <div className="mc-reco-mini-l">
              <HoldingsDonut holdings={recommend.top.holdings_final} size={108} />
            </div>
            <div className="mc-reco-mini-r">
              <div className="mc-reco-mini-nm"><b>{recommend.top.name}</b><SignalBadge signal={recommend.top.signal} /></div>
              <div className="mc-reco-mini-stats">
                <span>적합도 <b>{recommend.top.fit_score.toFixed(0)}</b></span>
                <span>종합 <b>{recommend.top.composite.toFixed(0)}</b></span>
                <span>신뢰도 <b>{(recommend.confidence * 100).toFixed(0)}%</b></span>
              </div>
              <div className="mc-reco-mini-hold">
                {recommend.top.holdings_final.slice(0, 6).map((h, idx) => (
                  <span key={h.ticker} className="mc-hchip"><i style={{ background: donutColor(idx) }} />{h.us_label} {h.weight}%</span>
                ))}
              </div>
              <button className="mc-bt-btn" onClick={() => onTransplant(recommend.top.id, recommend.top.name)}><Play size={12} /> 이 전략 백테스트 →</button>
            </div>
          </div>
        ) : <div className="mc-empty-sm">추천 데이터 없음</div>}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">수익률 곡선 {regime.yield_inversion && <span className="mc-warn">역전 {regime.inversion_severity?.toFixed(0)}bp</span>}</div>
        {yc?.points?.length ? <YieldCurveChart points={yc.points} inversion={regime.yield_inversion} /> : <div className="mc-empty-sm">곡선 데이터 없음</div>}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">극단 지표 — |z| 상위 6</div>
        <div className="mc-ext">
          {extreme.map((ind) => (
            <button key={ind.id} className="mc-ext-row" onClick={() => onDrill(ind.id)}>
              <span className="mc-ext-nm">{ind.name}</span>
              <span className="mc-ext-v">{fmtNum(ind.latest)} {ind.unit}</span>
              <span className="mc-ext-z" style={{ color: ind.z_score! >= 0 ? "var(--color-bear)" : "#2563eb" }}>{fmtZ(ind.z_score)}</span>
              {ind.z_score! >= 0 ? <TrendingUp size={13} color="var(--color-bear)" /> : <TrendingDown size={13} color="#2563eb" />}
            </button>
          ))}
          {!extreme.length && <div className="mc-empty-sm">지표 데이터 없음</div>}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 02 Indicators
// ─────────────────────────────────────────────────────────────────────────────
export function IndicatorsTab({ core, onDrill, cbSent }: { core: MacroCore; onDrill: (id: string) => void; cbSent?: CbSentiment | null }) {
  const d = core.dashboard;
  const [q, setQ] = useState("");
  if (!d) return <div className="mc-empty-sm">대시보드 데이터 없음</div>;
  // 지표 검색 (밸리AI 접근성 흡수 — 30+ 지표에서 원하는 것 즉시)
  const themes = q.trim()
    ? d.themes.map((t) => ({ ...t, indicators: t.indicators.filter((i) => (i.name + i.id).toLowerCase().includes(q.trim().toLowerCase())) })).filter((t) => t.indicators.length)
    : d.themes;
  return (
    <div className="mc-stack">
      <input className="mc-search" placeholder="지표 검색 — 예: CPI, 실업, 금리, VIX…"
        value={q} onChange={(e) => setQ(e.target.value)} aria-label="지표 검색" />
      {/* Text-as-Data: 중앙은행 커뮤니케이션 톤 (하드데이터 후행성 보완) */}
      <div className="mc-card">
        <div className="mc-card-h">Central Bank Sentiment — 정책문 매파/비둘기 톤
          <span className="mc-card-sub">{cbSent?.method ?? "렉시콘 기반 (수집 중…)"}</span></div>
        {cbSent === undefined && <div className="mc-empty-sm">정책문 분석 중…</div>}
        {cbSent === null && <div className="mc-empty-sm">센티먼트 로드 실패</div>}
        {cbSent && (
          <div className="mc-cbg-grid">
            <CbGauge name="Fed (FOMC 성명)" bank={cbSent.banks.fed} />
            <CbGauge name="한국은행 (통화정책방향)" bank={cbSent.banks.bok} />
          </div>
        )}
      </div>
      <div className="mc-card">
        <div className="mc-card-h">매크로 히트맵 — 25지표 × Z-Score(5년) <span className="mc-card-sub">{d.sources.fred ? "FRED" : "mock"} · {d.sources.bok ? "ECOS" : "mock"}</span></div>
        <ZHeatmap themes={themes} onPick={(ind) => onDrill(ind.id)} />
        <div className="mc-zlegend"><span>낮음</span><i className="mc-zleg-grad" /><span>높음</span><em>· 셀 클릭 → 36개월 시계열</em></div>
      </div>
      {themes.map((t) => (
        <div key={t.key} className="mc-card">
          <div className="mc-card-h">{t.label} <span className="mc-card-sub">{t.indicators.length}지표</span></div>
          {t.indicators.length ? (
            <div className="mc-indgrid">{t.indicators.map((ind) => <IndicatorCard key={ind.id} ind={ind} onClick={() => onDrill(ind.id)} />)}</div>
          ) : <div className="mc-empty-sm">데이터 없음</div>}
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 03 Regime
// ─────────────────────────────────────────────────────────────────────────────
export function RegimeTab({ regime, traj, strips, axisHist }: {
  regime: NonNullable<MacroCore["regime"]>; traj: MacroTrajectory | null;
  strips?: CycleStrips | null; axisHist?: AxisHistory | null;
}) {
  const sc = Object.entries(regime.stress_components ?? {});
  const tilts = Object.entries(regime.asset_tilts ?? {});
  const tiltMap: Record<string, { v: number; lbl: string }> = {
    "++": { v: 2, lbl: "강한 비중확대" }, "+": { v: 1, lbl: "비중확대" }, "0": { v: 0, lbl: "중립" },
    "-": { v: -1, lbl: "비중축소" }, "--": { v: -2, lbl: "강한 비중축소" },
  };
  return (
    <div className="mc-grid">
      <div className="mc-card span2">
        <div className="mc-card-h">국면 궤적 — 최근 18개월 경로 <span className="mc-card-sub">성장×물가 테마-z</span></div>
        {traj?.path?.length ? <RegimeTrajectory path={traj.path} /> : <div className="mc-empty-sm">궤적 불러오는 중…</div>}
        {!!traj?.transitions?.length && (
          <div className="mca-transitions">
            {traj.transitions.map((tr, i) => (
              <span key={i} className="mca-trans"><em>{tr.t}</em> {tr.from} → <b>{tr.to}</b></span>
            ))}
          </div>
        )}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">국면 좌표 (성장 × 물가) — 현재</div>
        <RegimeScatter g={regime.growth_axis} i={regime.inflation_axis} />
      </div>
      {/* 사이클 히트 스트립 (밸리AI '사이클 분석' 흡수) — 지표×18개월 변환 z 색 띠 */}
      <div className="mc-card span2">
        <div className="mc-card-h">사이클 스트립 — 지표별 18개월 국면 흐름 <span className="mc-card-sub">셀=시점별 z (축과 동일 변환)</span></div>
        {strips === undefined && <div className="mc-empty-sm">스트립 계산 중…</div>}
        {strips === null && <div className="mc-empty-sm">스트립 로드 실패</div>}
        {strips && <CycleStripGrid data={strips} />}
        {strips && <p className="mc-card-note">{strips.note}</p>}
      </div>
      {/* 하위요인 시계열 분해 (밸리AI '하위요인 분석' 흡수) — 축 스코어의 지표 기여 스택 */}
      {axisHist && (
        <>
          <div className="mc-card span2">
            <div className="mc-card-h">성장 축 하위요인 — 시간에 따른 지표 기여 <span className="mc-card-sub">스택=기여 · 검정선=축 스코어</span></div>
            <AxisStackChart hist={axisHist} axis="growth" />
          </div>
          <div className="mc-card span2">
            <div className="mc-card-h">물가 축 하위요인 — 시간에 따른 지표 기여</div>
            <AxisStackChart hist={axisHist} axis="inflation" />
            <p className="mc-card-note">{axisHist.note}</p>
          </div>
        </>
      )}
      {/* 축 분해 — "지표 σ와 축 스코어가 왜 다른가"에 대한 답: 축이 실제로 먹는 변환 z(YoY)와
          레벨/모멘텀 블렌드 기여를 지표별로 공개. 히트맵의 레벨 σ와 구분(투명화). */}
      {regime.axis_detail && (
        <div className="mc-card span2">
          <div className="mc-card-h">축 스코어 분해 — 지표별 기여 <span className="mc-card-sub">레벨 z(YoY 변환) 75% + 3개월 모멘텀 z 25%</span></div>
          <div className="mc-axisbd-grid">
            <AxisBreakdown title="성장 축" detail={regime.axis_detail.growth} />
            <AxisBreakdown title="물가 축" detail={regime.axis_detail.inflation} />
          </div>
          <p className="mc-card-note">히트맵의 σ는 원시 레벨 z(지수형은 항상 우상향 → 구조적 +)이고, 국면 축은 YoY 변환 z를 사용합니다 — 두 수치가 다른 것은 모순이 아니라 변환 차이입니다. 이 표가 축의 실제 입력입니다.</p>
        </div>
      )}
      {regime.regime_probs && (
        <div className="mc-card">
          <div className="mc-card-h">사분면 확률 <span className="mc-card-sub">축 불확실성(±se) 기반 · 합=1</span></div>
          <ProbBars probs={regime.regime_probs} />
        </div>
      )}
      <div className="mc-card">
        <div className="mc-card-h">순환 시계</div>
        <div className="mc-center"><CycleClock g={regime.growth_axis} i={regime.inflation_axis} size={188} /></div>
      </div>
      <div className="mc-card">
        <div className="mc-card-h">스트레스 게이지</div>
        <ArcGauge value={regime.stress_score} color={stressColor(regime.stress_score)} label="STRESS" />
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">스트레스 구성요소</div>
        <div className="mc-stresscomp">
          {sc.map(([k, v]) => (
            <div key={k} className="mc-sc-row"><span className="mc-sc-k">{k}</span><div className="mc-sc-bar"><i style={{ width: `${Math.max(2, Math.min(100, v))}%`, background: stressColor(v) }} /></div><span className="mc-sc-v">{v.toFixed(0)}</span></div>
          ))}
          {!sc.length && <div className="mc-empty-sm">구성요소 없음</div>}
        </div>
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">수익률 곡선 {regime.yield_inversion && <span className="mc-warn">역전 {regime.inversion_severity?.toFixed(0)}bp</span>}</div>
        {regime.yield_curve?.points?.length ? <YieldCurveChart points={regime.yield_curve.points} inversion={regime.yield_inversion} /> : <div className="mc-empty-sm">데이터 없음</div>}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">자산군 틸트 — 국면 기반 비중 가이드</div>
        <div className="mc-tilts">
          {tilts.map(([asset, sym]) => {
            const m = tiltMap[String(sym)] ?? { v: 0, lbl: String(sym) };
            const col = m.v > 0 ? "var(--color-bull)" : m.v < 0 ? "var(--color-bear)" : "var(--t-muted)";
            return (
              <div key={asset} className="mc-tilt-row">
                <span className="mc-tilt-nm">{asset}</span>
                <div className="mc-tilt-track"><div className="mc-tilt-fill" style={{ width: `${Math.abs(m.v) * 25}%`, background: col, ...(m.v >= 0 ? { left: "50%" } : { right: "50%" }) }} /></div>
                <span className="mc-tilt-lbl" style={{ color: col }}>{m.lbl}</span>
              </div>
            );
          })}
          {!tilts.length && <div className="mc-empty-sm">틸트 데이터 없음</div>}
        </div>
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">동적 파라미터 — Valuation·KillSwitch 연동</div>
        <div className="mc-dparams">
          <div className="mc-dparam"><span>무위험금리 (Kₑ 주입)</span><b>{regime.dynamic_risk_free_rate != null ? `${(regime.dynamic_risk_free_rate * 100).toFixed(2)}%` : "—"}</b></div>
          <div className="mc-dparam"><span>Kill Switch DD 임계</span><b>{regime.dynamic_kill_dd_threshold != null ? `${(regime.dynamic_kill_dd_threshold * 100).toFixed(2)}%` : "—"}</b></div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 04 Valuation
// ─────────────────────────────────────────────────────────────────────────────
export function ValuationTab({ core, aStrips }: { core: MacroCore; aStrips?: AssetStrips | null }) {
  const v = core.valuation;
  if (!v) return <div className="mc-empty-sm">밸류에이션 데이터 없음</div>;
  return (
    <div className="mc-grid">
      {/* 자산군 스트립 타임라인 (밸리AI '자산군 밸류에이션' 흡수 — 시세 기반 정직 버전) */}
      <div className="mc-card span2">
        <div className="mc-card-h">자산군 가격 위치 스트립 — 18개월 흐름 <span className="mc-card-sub">트레일링 5년 백분위</span></div>
        {aStrips === undefined && <div className="mc-empty-sm">스트립 계산 중…</div>}
        {aStrips === null && <div className="mc-empty-sm">스트립 로드 실패</div>}
        {aStrips && <AssetStripGrid data={aStrips} />}
        {aStrips && <p className="mc-card-note">{aStrips.note}</p>}
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">자산군 밸류에이션 — 가격 Z-Score(5년) <span className="mc-card-sub">{v.sources.prices ? "KIS 실시세" : "mock"}</span></div>
        <ValuationBars assets={v.assets} />
        <p className="mc-card-note">Z &gt; 0 = 5년 평균 대비 고평가 구간(되돌림 위험), Z &lt; 0 = 저평가 구간(분할매수 기회). 자산배분 시 저평가 자산 비중확대의 출발점.</p>
      </div>
      <div className="mc-card span2">
        <div className="mc-card-h">한국 시장 밸류 <span className="mc-card-sub">{v.sources.fundamentals ? "DART 재무" : "mock"}</span></div>
        {v.kr_market ? (
          <div className="mc-krval">
            <div className="mc-krval-item"><span>시장 PER 중앙값</span><b>{fmtNum(v.kr_market.per_median)}배</b></div>
            <div className="mc-krval-item"><span>시장 PBR 중앙값</span><b>{fmtNum(v.kr_market.pbr_median)}배</b></div>
            <div className="mc-krval-item"><span>표본 종목수</span><b>{v.kr_market.n.toLocaleString()}</b></div>
          </div>
        ) : <div className="mc-empty-sm">한국 시장 밸류는 종목 스냅샷 적재 후 활성됩니다 (GCP factor_snapshot).</div>}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 05 Strategies (US⇄KR 토글)
// ─────────────────────────────────────────────────────────────────────────────
