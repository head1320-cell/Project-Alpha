"use client";
// 매크로 분석 탭 — 전략 · 추천 (+ 시장 토글·전략 카드)
// BU5b-2: 한국어 제목 · 판단(신호·적합도)은 중립 · 12개월 성과는 등락색 · 미국 전략/추천 실패는 "데이터 없음"이 아니라 실패 + 다시 시도 ·
//   서버가 쓴 설명은 그대로(`data-server`). 클래스명은 E2E 계약(`.mc-stratcard`·`.mc-rankrow`·`.mc-tab`).
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
import { Notice } from "@/shared/ui/tx";
import { regimeName } from "@/entities/macro/regimeKo";
import { signed } from "./macroKo";
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
  CycleStripGrid, AxisStackChart, AssetStripGrid, KrUsCompareTable,
} from "./visualParts";
import type { AssetStrips, AxisHistory, CycleStrips, KrUsCompare } from "@/entities/macro/analysisModel";

export function MarketToggle({ market, setMarket }: { market: Market; setMarket: (m: Market) => void }) {
  return (
    <div className="mc-mkt" role="group" aria-label="시장 선택">
      <button type="button" className={market === "kr" ? "on" : ""} aria-pressed={market === "kr"} onClick={() => setMarket("kr")}>국내 ETF</button>
      <button type="button" className={market === "us" ? "on" : ""} aria-pressed={market === "us"} onClick={() => setMarket("us")}>미국 ETF</button>
    </div>
  );
}

/** 지연 데이터 실패 — 그 자리에서 말한다(role=alert) + [다시 시도]. */
export function TabFail({ title, onRetry }: { title: string; onRetry?: () => void }) {
  return (
    <Notice tone="danger" title={title}>
      서버 연결 실패 또는 계산 실패
      {onRetry && <div className="mc-act"><button type="button" className="tx-btn tx-btn--sub" onClick={onRetry}>재시도</button></div>}
    </Notice>
  );
}
const mktName = (m: Market) => (m === "kr" ? "국내 ETF" : "미국 ETF");

const FAMILY_LABELS: Record<string, string> = {
  risk: "위험을 균등 배분하는 전략(공분산 기반)", optim: "최적화 전략", trend: "추세 추종 전략(매니지드 퓨처스)",
  sizing: "성장 최적 비중 전략", momentum: "모멘텀 · 추세 타이밍 전략", benchmark: "비교 기준",
};
const FAMILY_ORDER = ["risk", "optim", "trend", "sizing", "momentum", "benchmark"];

export function StrategiesTab({ strategies, market, setMarket, loading, failed, onRetry, onTransplant, onOpen }: {
  strategies: MacroStrategies | null; market: Market; setMarket: (m: Market) => void; loading: boolean;
  /** 이 시장 전략 요청이 실패했다(빈 결과와 다르다) */
  failed?: boolean; onRetry?: () => void;
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
        <div className="mc-strat-title">전술적 자산배분 전략{total ? ` ${total}개` : ""} <span className="mc-card-sub">모멘텀·위험·최적화 규칙으로 현재 시점의 비중과 신호를 산출했습니다. 카드를 누르면 상세를 표시합니다.</span></div>
        <MarketToggle market={market} setMarket={setMarket} />
      </div>
      {loading && <p className="mc-loading">{mktName(market)} 포트폴리오 최적화 중</p>}
      {!loading && failed && <TabFail title={`${mktName(market)} 전략 조회 실패`} onRetry={onRetry} />}
      {!loading && !failed && (groups.length ? groups.map((g) => (
        <section key={g.family} className="mc-fam">
          <h3 className="mc-fam-h"><span className="mc-fam-lbl">{g.label}</span><span className="mc-fam-n">{g.items.length}개</span></h3>
          <div className="mc-stratgrid">
            {g.items.map((s) => <StrategyCard key={s.id} s={s} onTransplant={onTransplant} onOpen={onOpen} />)}
          </div>
        </section>
      )) : <div className="mc-empty-sm">이 시장에는 전략이 아직 없습니다</div>)}
    </div>
  );
}

export function StrategyCard({ s, onTransplant, onOpen }: { s: TacticalStrategy; onTransplant: (sid: string, name: string) => void; onOpen: (sid: string) => void }) {
  const sorted = [...s.holdings].sort((a, b) => b.weight - a.weight);
  const top = sorted.slice(0, 6);
  return (
    <div className="mc-stratcard mc-stratcard-click" onClick={() => onOpen(s.id)} role="button" tabIndex={0} aria-label={`${s.name} 상세 보기`}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(s.id); } }}>
      <div className="mc-stratcard-h">
        <div><b>{s.name}</b><SignalBadge signal={s.signal} /></div>
        <button type="button" className="mc-bt-btn sm tx-btn tx-btn--sub" onClick={(e) => { e.stopPropagation(); onTransplant(s.id, s.name); }}>백테스트하기</button>
      </div>
      <p className="mc-stratcard-desc" data-server>{s.description}</p>
      <div className="mc-stratcard-body">
        <HoldingsDonut holdings={sorted} size={104} />
        <div className="mc-stratcard-holds">
          {top.map((h, idx) => (
            <div key={h.ticker} className="mc-hold-row">
              <i style={{ background: donutColor(idx, sorted.length) }} aria-hidden />
              <span className="mc-hold-nm">{h.us_label}</span>
              <span className="mc-hold-tk" data-mono>{h.ticker}</span>
              <div className="mc-hold-bar" aria-hidden><b style={{ width: `${h.weight}%`, background: donutColor(idx, sorted.length) }} /></div>
              <span className="mc-hold-w">{h.weight}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 추천
// ─────────────────────────────────────────────────────────────────────────────
export function RecommendTab({ recommend, market, setMarket, loading, failed, onRetry, onTransplant }: {
  recommend: MacroRecommend | null; market: Market; setMarket: (m: Market) => void; loading: boolean;
  failed?: boolean; onRetry?: () => void;
  onTransplant: (sid: string, name: string) => void;
}) {
  const bar = (sub?: React.ReactNode) => (
    <div className="mc-strat-bar">
      <div className="mc-strat-title">국면 기반 추천 {sub}</div>
      <MarketToggle market={market} setMarket={setMarket} />
    </div>
  );
  if (loading) return <div className="mc-stack">{bar()}<p className="mc-loading">{mktName(market)} 추천을 재계산하는 중입니다</p></div>;
  if (failed) return <div className="mc-stack">{bar()}<TabFail title={`${mktName(market)} 추천 조회 실패`} onRetry={onRetry} /></div>;
  if (!recommend) return <div className="mc-stack">{bar()}<div className="mc-empty-sm">추천 데이터 없음 · 이 시장의 추천이 아직 없습니다</div></div>;
  // 실데이터에서 추천이 부분 계산되면(top/regime/보유 목록 결측) 무너지는 대신 정직하게 말한다.
  if (!recommend.top || !recommend.regime || !Array.isArray(recommend.top.holdings_final)) {
    return (
      <div className="mc-stack">{bar()}
        <div className="mc-empty-sm">
          추천 데이터가 불완전합니다. 국면·전략 계산에 필요한 값이 부족해 표시할 수 없습니다(데이터 미가용). 데이터를 적재한 뒤 다시 확인하십시오.
        </div>
      </div>
    );
  }
  const top = recommend.top;
  const confPct = (recommend.confidence * 100).toFixed(0);
  const ma = recommend.macro_allocation;
  const finalSorted = top.holdings_final;
  return (
    <div className="mc-stack">
      {bar(<span className="mc-card-sub"><span data-server>{recommend.regime.quadrant_kr}</span> · 스트레스 {recommend.regime.stress.toFixed(0)} · 신뢰도 {confPct}%</span>)}
      {recommend.low_conviction && (
        <p className="mc-warn mc-warn--line">
          신뢰도가 낮은 국면입니다(신뢰도 {confPct}%). 방향성 판단 오류 위험을 줄이기 위해 현금성 자산을 {top.cash_overlay_pct.toFixed(0)}% 편입했습니다.
        </p>
      )}
      <div className="mc-grid">
        {/* 1순위: 국면 점수를 바로 넣어 정한 배분 + 비중이 정해진 이유 + 몬테카를로 범위 */}
        {ma && (
          <div className="mc-card span2 mc-featured">
            <div className="mc-card-h">국면에서 바로 정한 배분(1순위)
              <span className="mc-card-sub">성장 {signed(ma.inputs.growth)} · 물가 {signed(ma.inputs.inflation)} · 스트레스 {ma.inputs.stress.toFixed(0)}을 네 계절 비중으로 환산했습니다</span></div>
            <div className="mc-reco">
              <div className="mc-reco-l">
                <HoldingsDonut holdings={ma.holdings} size={150} />
                {recommend.regime_probs && <ProbBars probs={recommend.regime_probs} compact />}
              </div>
              <div className="mc-reco-r">
                <h4 className="mc-subh">비중이 정해진 이유</h4>
                <AllocAttribution rows={ma.attribution} />
                <h4 className="mc-subh mc-subh--gap">비중의 변동 가능 폭(몬테카를로 400회)</h4>
                <AllocBands bands={ma.bands} />
              </div>
            </div>
            <p className="mc-card-note"><span data-server>{ma.method}</span> · <span data-server>{ma.note}</span></p>
          </div>
        )}
        <div className="mc-card span2">
          <div className="mc-card-h">최우선 추천 전략 <SignalBadge signal={top.signal} /></div>
          <div className="mc-reco">
            <div className="mc-reco-l">
              <HoldingsDonut holdings={finalSorted} size={150} />
              <ArcGauge value={top.fit_score} label="/100" sub="국면 적합도" ends={["0", "100"]} />
            </div>
            <div className="mc-reco-r">
              <div className="mc-reco-nm">{top.name}</div>
              <div className="mc-reco-comp">종합 점수 <b>{top.composite.toFixed(0)}</b> / 100 · 신뢰도에 맞춰 현금 {top.cash_overlay_pct.toFixed(0)}%를 혼합했습니다</div>
              <div className="mc-reco-holds">
                {finalSorted.map((h, idx) => (
                  <div key={h.ticker} className="mc-hold-row">
                    <i style={{ background: donutColor(idx, finalSorted.length) }} aria-hidden />
                    <span className="mc-hold-nm">{h.us_label}</span>
                    <span className="mc-hold-tk" data-mono>{h.ticker}</span>
                    <div className="mc-hold-bar" aria-hidden><b style={{ width: `${h.weight}%`, background: donutColor(idx, finalSorted.length) }} /></div>
                    <span className="mc-hold-w">{h.weight}%</span>
                  </div>
                ))}
              </div>
              <button type="button" className="mc-bt-btn tx-btn tx-btn--sub" onClick={() => onTransplant(top.id, top.name)}>이 전략 백테스트하기</button>
            </div>
          </div>
        </div>
        <div className="mc-card span2">
          <div className="mc-card-h">추천한 까닭 <span className="mc-card-sub">{recommend.narrative_source === "claude" ? "AI가 국면과 성과를 바탕으로 작성한 해설입니다" : "규칙 기반 해설입니다 · AI 해설은 관리자가 키를 등록하면 활성화됩니다"}</span></div>
          <p className="mc-narr" data-server>{recommend.narrative}</p>
        </div>
        <div className="mc-card span2">
          <div className="mc-card-h">전략 {recommend.ranking.length}개 순위 <span className="mc-card-sub">종합 점수 = 국면 적합도 62% + 지난 성과 38%</span></div>
          <div className="mc-tablewrap">
            <div className="mc-ranktbl">
              <div className="mc-rankhead"><span>순위</span><span>전략</span><span className="mc-rh-bar">종합 점수</span><span>점수</span><span>적합도</span><span>12개월</span></div>
              {recommend.ranking.map((r, idx) => (
                <CompositeRow key={r.id} rank={idx + 1} name={r.name} composite={r.composite} fit={r.fit_score} perf={r.recent_return_12m} signal={r.signal} active={r.id === top.id} />
              ))}
            </div>
          </div>
          <p className="mc-card-note">12개월 성과는 각 전략의 현재 비중을 지난 12개월 ETF 수익률에 적용한 추정치입니다(합성 데이터에서는 합성 시세). 향후 수익률을 보장하지 않습니다.</p>
          {recommend.data_lag_note && <p className="mc-card-note" data-server>{recommend.data_lag_note}</p>}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 07 Correlations
// ─────────────────────────────────────────────────────────────────────────────
