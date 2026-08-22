"use client";
// 매크로 콕핏 탭 — 05 Strategies · 06 Recommend (+ 시장 토글·전략 카드)
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

export function MarketToggle({ market, setMarket }: { market: Market; setMarket: (m: Market) => void }) {
  return (
    <div className="mc-mkt">
      <ArrowRightLeft size={12} />
      <button className={market === "us" ? "on" : ""} onClick={() => setMarket("us")}>US ETF</button>
      <button className={market === "kr" ? "on" : ""} onClick={() => setMarket("kr")}>국내 ETF</button>
    </div>
  );
}

const FAMILY_LABELS: Record<string, string> = {
  risk: "리스크 기반 · 공분산 구동", optim: "최적화 기반", trend: "추세추종 (매니지드 퓨처스/CTA)",
  sizing: "성장최적 사이징", momentum: "모멘텀 · 추세 타이밍", benchmark: "벤치마크",
};
const FAMILY_ORDER = ["risk", "optim", "trend", "sizing", "momentum", "benchmark"];

export function StrategiesTab({ strategies, market, setMarket, loading, onTransplant, onOpen }: {
  strategies: MacroStrategies | null; market: Market; setMarket: (m: Market) => void; loading: boolean;
  onTransplant: (sid: string, name: string) => void; onOpen: (sid: string) => void;
}) {
  const groups = useMemo(() => {
    const by: Record<string, TacticalStrategy[]> = {};
    for (const s of strategies?.strategies ?? []) {
      const f = s.family ?? "momentum";
      (by[f] ||= []).push(s);
    }
    return FAMILY_ORDER.filter((f) => by[f]?.length).map((f) => ({ family: f, label: FAMILY_LABELS[f] ?? f, items: by[f] }));
  }, [strategies]);
  const total = strategies?.strategies?.length ?? 0;
  return (
    <div className="mc-stack">
      <div className="mc-strat-bar">
        <div className="mc-strat-title">택티컬 자산배분 {total}전략 <span className="mc-card-sub">모멘텀 + 리스크·최적화 · 현재 시점 비중·시그널</span></div>
        <MarketToggle market={market} setMarket={setMarket} />
      </div>
      {loading && <div className="mc-empty-sm">{market === "kr" ? "국내 ETF" : "US ETF"} 비중 계산 중…</div>}
      {!loading && groups.length ? groups.map((g) => (
        <div key={g.family} className="mc-fam">
          <div className="mc-fam-h"><span className="mc-fam-lbl">{g.label}</span><span className="mc-fam-n">{g.items.length}</span></div>
          <div className="mc-stratgrid">
            {g.items.map((s) => <StrategyCard key={s.id} s={s} onTransplant={onTransplant} onOpen={onOpen} />)}
          </div>
        </div>
      )) : !loading && <div className="mc-empty-sm">전략 데이터 없음</div>}
    </div>
  );
}

export function StrategyCard({ s, onTransplant, onOpen }: { s: TacticalStrategy; onTransplant: (sid: string, name: string) => void; onOpen: (sid: string) => void }) {
  const top = [...s.holdings].sort((a, b) => b.weight - a.weight).slice(0, 6);
  return (
    <div className="mc-stratcard mc-stratcard-click" onClick={() => onOpen(s.id)} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter") onOpen(s.id); }}>
      <div className="mc-stratcard-h">
        <div><b>{s.name}</b><SignalBadge signal={s.signal} /></div>
        <button className="mc-bt-btn sm" onClick={(e) => { e.stopPropagation(); onTransplant(s.id, s.name); }}><Play size={11} /> 백테스트</button>
      </div>
      <p className="mc-stratcard-desc">{s.description}</p>
      <div className="mc-stratcard-body">
        <HoldingsDonut holdings={s.holdings} size={104} />
        <div className="mc-stratcard-holds">
          {top.map((h, idx) => (
            <div key={h.ticker} className="mc-hold-row">
              <i style={{ background: donutColor(idx) }} />
              <span className="mc-hold-nm">{h.us_label}</span>
              <span className="mc-hold-tk">{h.ticker}</span>
              <div className="mc-hold-bar"><b style={{ width: `${h.weight}%`, background: donutColor(idx) }} /></div>
              <span className="mc-hold-w">{h.weight}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 06 Recommend
// ─────────────────────────────────────────────────────────────────────────────
export function RecommendTab({ recommend, market, setMarket, loading, onTransplant }: {
  recommend: MacroRecommend | null; market: Market; setMarket: (m: Market) => void; loading: boolean;
  onTransplant: (sid: string, name: string) => void;
}) {
  if (loading) return <div className="mc-empty-sm">추천 재계산 중…</div>;
  if (!recommend) return <div className="mc-empty-sm">추천 데이터 없음</div>;
  // 실데이터에서 추천이 부분 계산되면(top/regime/보유목록 결측) 크래시 대신 정직한 미가용 상태.
  if (!recommend.top || !recommend.regime || !Array.isArray(recommend.top.holdings_final)) {
    return (
      <div className="mc-empty-sm">
        추천 데이터가 불완전합니다 — 국면·전략 계산에 필요한 값이 부족해 표시할 수 없습니다 (데이터 미가용).
        데이터 적재 후 다시 시도하세요.
      </div>
    );
  }
  const top = recommend.top;
  const confPct = (recommend.confidence * 100).toFixed(0);
  return (
    <div className="mc-stack">
      <div className="mc-strat-bar">
        <div className="mc-strat-title">
          국면 기반 추천 <span className="mc-card-sub">{recommend.regime.quadrant_kr} · Stress {recommend.regime.stress.toFixed(0)} · 신뢰도 {confPct}%</span>
        </div>
        <MarketToggle market={market} setMarket={setMarket} />
      </div>
      {recommend.low_conviction && (
        <div className="mc-warn">
          저확신 국면(신뢰도 {confPct}%) — 배분에 현금성 {top.cash_overlay_pct.toFixed(0)}%를 자동 편입해 방향성 오류 리스크를 낮췄습니다.
        </div>
      )}
      <div className="mc-grid">
        {/* ★1순위: 매크로 임베딩 배분 (CIO §3) — 국면 스코어가 직접 입력. 가격 모멘텀 전략이
            매크로 환경과 충돌하던 문제의 해소 + XAI 기여분해 + MC 신뢰구간. */}
        {recommend.macro_allocation && (
          <div className="mc-card span2 mc-featured">
            <div className="mc-card-h">매크로 임베딩 배분 — 국면 직결 (1순위)
              <span className="mc-card-sub">성장 {recommend.macro_allocation.inputs.growth >= 0 ? "+" : ""}{recommend.macro_allocation.inputs.growth.toFixed(2)} · 물가 {recommend.macro_allocation.inputs.inflation >= 0 ? "+" : ""}{recommend.macro_allocation.inputs.inflation.toFixed(2)} · Stress {recommend.macro_allocation.inputs.stress.toFixed(0)} → 4계절 틸트</span></div>
            <div className="mc-reco">
              <div className="mc-reco-l">
                <HoldingsDonut holdings={recommend.macro_allocation.holdings} size={150} />
                {recommend.regime_probs && <ProbBars probs={recommend.regime_probs} compact />}
              </div>
              <div className="mc-reco-r">
                <div className="mc-alloc-sub">Weight Attribution — 비중 결정 요인 (룰 항 정확 분해)</div>
                <AllocAttribution rows={recommend.macro_allocation.attribution} />
                <div className="mc-alloc-sub" style={{ marginTop: 10 }}>비중 신뢰구간 — 몬테카를로 400회</div>
                <AllocBands bands={recommend.macro_allocation.bands} />
              </div>
            </div>
            <p className="mc-card-note">{recommend.macro_allocation.method} · {recommend.macro_allocation.note}</p>
          </div>
        )}
        <div className="mc-card span2">
          <div className="mc-card-h">최우선 추천 <SignalBadge signal={top.signal} /></div>
          <div className="mc-reco">
            <div className="mc-reco-l">
              <HoldingsDonut holdings={top.holdings_final} size={150} />
              <ArcGauge value={top.fit_score} color={sigColor(top.signal)} label="적합도" height={104} />
            </div>
            <div className="mc-reco-r">
              <div className="mc-reco-nm">{top.name}</div>
              <div className="mc-reco-comp">종합점수 <b>{top.composite.toFixed(0)}</b> / 100 · 신뢰도 가중 배분(현금 {top.cash_overlay_pct.toFixed(0)}%)</div>
              <div className="mc-reco-holds">
                {top.holdings_final.map((h, idx) => (
                  <div key={h.ticker} className="mc-hold-row">
                    <i style={{ background: donutColor(idx) }} />
                    <span className="mc-hold-nm">{h.us_label}</span>
                    <span className="mc-hold-tk">{h.ticker}</span>
                    <div className="mc-hold-bar"><b style={{ width: `${h.weight}%`, background: donutColor(idx) }} /></div>
                    <span className="mc-hold-w">{h.weight}%</span>
                  </div>
                ))}
              </div>
              <button className="mc-bt-btn" onClick={() => onTransplant(top.id, top.name)}><Play size={12} /> 이 전략 백테스트 →</button>
            </div>
          </div>
        </div>
        <div className="mc-card span2">
          <div className="mc-card-h">AI 근거 <span className="mc-card-sub">{recommend.narrative_source === "claude" ? "Claude" : "규칙 기반"}</span></div>
          <p className="mc-narr">{recommend.narrative}</p>
          {recommend.narrative_source === "rule" && <p className="mc-narr-note">※ ANTHROPIC_API_KEY 설정 시 Claude가 국면·성과를 종합한 서술을 생성합니다.</p>}
        </div>
        <div className="mc-card span2">
          <div className="mc-card-h">전체 13전략 랭킹 — 적합도(62%) + 트레일링 성과(38%)</div>
          <div className="mc-ranktbl">
            <div className="mc-rankhead"><span>#</span><span>전략</span><span className="mc-rh-bar">종합</span><span>점수</span><span>적합</span><span>12M</span></div>
            {recommend.ranking.map((r, idx) => (
              <CompositeRow key={r.id} rank={idx + 1} name={r.name} composite={r.composite} fit={r.fit_score} perf={r.recent_return_12m} signal={r.signal} active={r.id === top.id} />
            ))}
          </div>
          <p className="mc-card-note">성과는 각 전략의 현재 비중을 트레일링 12개월 수익률에 적용한 추정치입니다(실 ETF 시세 — 키 없으면 mock). 미래 수익을 보장하지 않습니다.</p>
          <p className="mc-card-note">{recommend.data_lag_note}</p>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 07 Correlations
// ─────────────────────────────────────────────────────────────────────────────
