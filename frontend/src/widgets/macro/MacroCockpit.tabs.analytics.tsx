"use client";
// 매크로 분석 탭 — 상관 · 타이밍
// BU5b-2: 데이터마다 불러오는 중(undefined) / 실패(null, 그 자리 alert + 다시 시도) / 값 · 시장을 바꾸면 부모가 옛 시장 값을 먼저 지운다 ·
//   판정(헤지·위험 선호)은 색 없이 글자 · 서버가 쓴 설명은 그대로(`data-server`). 클래스명은 E2E 계약.
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
  CycleStripGrid, AxisStackChart, AssetStripGrid, KrUsCompareTable,
} from "./visualParts";
import type { AssetStrips, AxisHistory, CycleStrips, KrUsCompare } from "@/entities/macro/analysisModel";
import { MarketToggle, TabFail } from "./MacroCockpit.tabs.strategy";
import { signed } from "./macroKo";

export function CorrelationsTab({ corr, market, setMarket, onRetryCorr, causal, onRetryCausal }: {
  /** undefined = 불러오는 중 · null = 실패 · 값 = 받음 */
  corr: MacroCorrelations | null | undefined; market: Market; setMarket: (m: Market) => void; onRetryCorr?: () => void;
  causal?: CausalGraph | null; onRetryCausal?: () => void;
}) {
  const sb = corr?.stock_bond_now;
  const mkt = market === "kr" ? "국내 ETF" : "미국 ETF";
  const edges = causal?.edges ?? [];
  const edgeLine = (e: (typeof edges)[number]) => (
    <><span data-server>{e.from_label}</span> → <b data-server>{e.to_label}</b> <em>{e.lag}개월 앞서요 · 유의확률 {e.p}</em></>
  );
  return (
    <div className="mc-stack">
      <div className="mc-strat-bar">
        <div className="mc-strat-title">자산끼리 함께 움직이는 정도 <span className="mc-card-sub">{corr?.matrix ? `자산 ${corr.matrix.tickers.length}개 · ` : ""}매일 수익률로 쟀어요</span></div>
        <MarketToggle market={market} setMarket={setMarket} />
      </div>
      {corr === undefined && <p className="mc-loading">{mkt} 상관을 계산하는 중이에요</p>}
      {corr === null && <TabFail title={`${mkt} 상관을 불러오지 못했어요`} onRetry={onRetryCorr} />}
      {corr && (
        <div className="mc-grid">
          <div className="mc-card span2">
            <div className="mc-card-h">주식과 채권이 서로 받쳐 주나요
              {sb?.corr != null && <span className="mc-card-sub">지금 상관 {signed(sb.corr)} · 판정 <b className="mc-verdict" data-server>{sb.verdict}</b></span>}</div>
            <RollingCorrChart pairs={corr.pairs} />
            <p className="mc-card-note">주식·장기채(SPY·TLT) 상관이 0보다 작으면 채권이 주식이 떨어질 때 받쳐 줘요(주식 60·채권 40, 위험 균등 배분이 잘 맞는 환경). 0보다 크면 함께 움직여 분산 효과가 약해져요(2022년 같은 환경).</p>
          </div>
          <div className="mc-card span2">
            <div className="mc-card-h">모든 자산 쌍의 평균 상관 <span className="mc-card-sub">1에 가까울수록 다 같이 움직여 분산이 잘 안 돼요</span></div>
            <AvgCorrChart avg={corr.avg_corr} />
            <p className="mc-card-note">점선 0.6은 화면이 그은 참고선이에요(서버가 내린 판정이 아니에요). 위기 때는 평균 상관이 1 쪽으로 몰리는 일이 잦아요.</p>
          </div>
          <div className="mc-card span2">
            <div className="mc-card-h">상관 지도(최근 1년)</div>
            <CorrMatrix m={corr.matrix} />
          </div>
        </div>
      )}
      {/* 상관(방향 없음)을 넘어서 — 누가 누구보다 먼저 움직이나(그레인저 예측 인과). 상관과 따로 불러오므로 따로 실패한다. */}
      <div className="mc-grid">
        <div className="mc-card span2">
          <div className="mc-card-h">먼저 움직이는 지표(그레인저 인과) <span className="mc-card-sub">한 지표의 과거 값이 다른 지표를 미리 맞히는지 검정했어요. 원인이라는 뜻은 아니에요.</span></div>
          {causal === undefined && <p className="mc-loading">관계를 검정하는 중이에요</p>}
          {causal === null && <TabFail title="먼저 움직이는 지표를 불러오지 못했어요" onRetry={onRetryCausal} />}
          {causal && <CausalGraphView nodes={causal.nodes} edges={causal.edges} />}
          {causal && (edges.length ? (
            <>
              <ul className="mc-causal-list">
                {edges.slice(0, 6).map((e, k) => <li key={k} className="mc-causal-edge">{edgeLine(e)}</li>)}
              </ul>
              {edges.length > 6 && (
                <details className="mc-more">
                  <summary>관계 {edges.length}개 모두 보기</summary>
                  <ul className="mc-causal-list">{edges.slice(6).map((e, k) => <li key={k} className="mc-causal-edge">{edgeLine(e)}</li>)}</ul>
                </details>
              )}
            </>
          ) : <div className="mc-empty-sm">유의한 관계가 없어요</div>)}
          {causal && <p className="mc-card-note">선이 굵을수록 유의확률이 낮아요(우연일 가능성이 작아요). 계산 방법: <span data-server>{causal.method}</span>{causal.note && <> · <span data-server>{causal.note}</span></>}</p>}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 타이밍
// ─────────────────────────────────────────────────────────────────────────────
export function TimingTab({ timing, market, setMarket, onRetry }: {
  /** undefined = 불러오는 중 · null = 실패 · 값 = 받음 */
  timing: MacroTiming | null | undefined; market: Market; setMarket: (m: Market) => void; onRetry?: () => void;
}) {
  const comp = timing?.composite;
  const mkt = market === "kr" ? "국내 ETF" : "미국 ETF";
  return (
    <div className="mc-stack">
      <div className="mc-strat-bar">
        <div className="mc-strat-title">시장 타이밍 <span className="mc-card-sub">위험을 더 질 때인지, 줄일 때인지 여러 신호로 쟀어요</span></div>
        <MarketToggle market={market} setMarket={setMarket} />
      </div>
      {timing === undefined && <p className="mc-loading">{mkt} 타이밍을 계산하는 중이에요</p>}
      {timing === null && <TabFail title={`${mkt} 타이밍을 불러오지 못했어요`} onRetry={onRetry} />}
      {timing && !comp && <div className="mc-empty-sm">종합 점수를 받지 못했어요</div>}
      {timing && comp && (
        <div className="mc-grid">
          <div className="mc-card">
            <div className="mc-card-h">위험 선호도 종합</div>
            <ArcGauge value={comp.score} label="/100" sub={comp.label} ends={["0 · 위험 회피", "100 · 위험 선호"]} />
          </div>
          <div className="mc-card">
            <div className="mc-card-h">신호별 점수 <span className="mc-card-sub">0~100, 가중을 곱해 합친 값이 종합 점수예요</span></div>
            <ComponentBars comps={timing.components} />
          </div>
          <div className="mc-card span2">
            <div className="mc-card-h">위험 선호도 추이</div>
            <TimingHistory history={timing.history} />
          </div>
          <div className="mc-card span2">
            <div className="mc-card-h">자산별 추세</div>
            <TrendTable assets={timing.assets} />
          </div>
        </div>
      )}
    </div>
  );
}
