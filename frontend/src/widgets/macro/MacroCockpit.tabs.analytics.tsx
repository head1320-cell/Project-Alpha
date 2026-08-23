"use client";
// 매크로 콕핏 탭 — 07 Correlations · 08 Timing
// JSX는 한 줄도 바꾸지 않고 그대로 옮겼다 — 클래스명이 E2E 계약이므로.
// (MacroCockpit.tsx에서 분리, props만 받는 표시 컴포넌트)
// MarketToggle은 여러 탭이 공유하는 작은 컨트롤 — 같은 슬라이스 안에서 가져온다.

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
import { MarketToggle } from "./MacroCockpit.tabs.strategy";

export function CorrelationsTab({ corr, market, setMarket, loading, causal }: {
  corr: MacroCorrelations | null; market: Market; setMarket: (m: Market) => void; loading: boolean;
  causal?: CausalGraph | null;
}) {
  const sb = corr?.stock_bond_now;
  const sbColor = sb?.verdict === "헤지" ? "var(--color-bull)" : sb?.verdict === "동조" ? "var(--color-bear)" : "var(--t-muted)";
  return (
    <div className="mc-stack">
      <div className="mc-strat-bar">
        <div className="mc-strat-title">자산 상관관계 <span className="mc-card-sub">13자산 · 일간수익률 · {corr?.sources.prices ? "실시세" : "mock"}</span></div>
        <MarketToggle market={market} setMarket={setMarket} />
      </div>
      {loading && !corr && <div className="mc-empty-sm">상관 계산 중…</div>}
      {corr && (
        <div className="mc-grid">
          <div className="mc-card span2">
            <div className="mc-card-h">주식-채권 상관 추이 — 헤지 작동 여부 {sb?.corr != null && <span className="mc-card-sub" style={{ color: sbColor }}>현재 {sb.corr.toFixed(2)} · {sb.verdict}</span>}</div>
            <RollingCorrChart pairs={corr.pairs} />
            <p className="mc-card-note">주식-장기채(SPY-TLT) 상관이 음(−)이면 채권이 주식 위험을 헤지(전통 60/40·리스크패리티 유효), 양(+)이면 동조화(2022형 — 분산 효과 약화). 자산배분 마켓타이밍 핵심 신호.</p>
          </div>
          <div className="mc-card span2">
            <div className="mc-card-h">평균 페어 상관 — 분산 국면</div>
            <AvgCorrChart avg={corr.avg_corr} />
            <p className="mc-card-note">전체 자산쌍 평균 상관. 1에 근접할수록 "상관 붕괴"(전부 동조 → 분산 무력화, 위기 동반). 낮을수록 건강한 분산 효과.</p>
          </div>
          <div className="mc-card span2">
            <div className="mc-card-h">상관 매트릭스 — 최근 1년</div>
            <CorrMatrix m={corr.matrix} />
            <div className="mc-zlegend"><span>음(−) 분산</span><i className="mca-corr-grad" /><span>양(+) 동조</span></div>
          </div>
          {/* 상관(무방향)을 넘어선 방향성 선행 구조 — 그레인저 예측 인과 */}
          <div className="mc-card span2">
            <div className="mc-card-h">Causal Graph — 그레인저 예측 인과
              <span className="mc-card-sub">{causal?.method ?? "검정 중…"}</span></div>
            {causal === undefined && <div className="mc-empty-sm">인과 검정 중…</div>}
            {causal === null && <div className="mc-empty-sm">인과 그래프 로드 실패</div>}
            {causal && <CausalGraphView nodes={causal.nodes} edges={causal.edges} />}
            {causal?.edges?.length ? (
              <div className="mc-causal-list">
                {causal.edges.slice(0, 6).map((e, k) => (
                  <span key={k} className="mc-causal-edge">{e.from_label} → <b>{e.to_label}</b> <em>lag {e.lag}M · p={e.p}</em></span>
                ))}
              </div>
            ) : null}
            <p className="mc-card-note">{causal?.note ?? ""} 엣지 굵기 = 유의성(p 낮을수록 굵음). 상관 히트맵이 답하지 못하는 &quot;누가 누구를 선행하는가&quot;를 보여줍니다.</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 08 Timing
// ─────────────────────────────────────────────────────────────────────────────
export function TimingTab({ timing, market, setMarket, loading }: {
  timing: MacroTiming | null; market: Market; setMarket: (m: Market) => void; loading: boolean;
}) {
  const comp = timing?.composite;
  const cColor = comp ? (comp.score >= 60 ? "var(--color-bull)" : comp.score <= 40 ? "var(--color-bear)" : "var(--color-caution)") : "var(--t-muted)";
  return (
    <div className="mc-stack">
      <div className="mc-strat-bar">
        <div className="mc-strat-title">마켓타이밍 <span className="mc-card-sub">위험 온/오프 · {timing?.sources.fred ? "FRED" : "mock"}</span></div>
        <MarketToggle market={market} setMarket={setMarket} />
      </div>
      {loading && !timing && <div className="mc-empty-sm">타이밍 계산 중…</div>}
      {timing && comp && (
        <div className="mc-grid">
          <div className="mc-card">
            <div className="mc-card-h">위험 선호도 종합</div>
            <ArcGauge value={comp.score} color={cColor} label={comp.label} />
          </div>
          <div className="mc-card">
            <div className="mc-card-h">신호별 기여 (가중)</div>
            <ComponentBars comps={timing.components} />
          </div>
          <div className="mc-card span2">
            <div className="mc-card-h">위험 선호도 추이 — 온(≥60)/오프(≤40)</div>
            <TimingHistory history={timing.history} />
          </div>
          <div className="mc-card span2">
            <div className="mc-card-h">자산별 추세 상태 — 어디가 타이밍상 유리한가</div>
            <TrendTable assets={timing.assets} />
          </div>
        </div>
      )}
    </div>
  );
}

