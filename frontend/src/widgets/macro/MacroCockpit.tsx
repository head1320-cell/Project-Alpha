"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// MacroCockpit — Macro Allocation Cockpit (자산배분·마켓타이밍 의사결정 콕핏)
//   고정 레짐 배너 + 6 서브탭: 01 Overview · 02 Indicators · 03 Regime ·
//   04 Valuation · 05 Strategies(US⇄KR) · 06 Recommend(규칙+성과+AI).
//   전부 실데이터(키 있으면) — 백엔드 mock 폴백 시 출처 배지로 정직 표기.
// ═══════════════════════════════════════════════════════════════════════════════
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
import StrategyModal from "./StrategyModal";
import {
  RegimeScatter, CycleClock, ArcGauge, YieldCurveChart, IndicatorCard, ZHeatmap,
  ValuationBars, HoldingsDonut, donutColor, SignalBadge, CompositeRow, DrillDownModal,
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

const TABS = [
  { id: "overview", label: "Overview", n: "01", icon: LayoutDashboard },
  { id: "indicators", label: "Indicators", n: "02", icon: Activity },
  { id: "regime", label: "Regime", n: "03", icon: Target },
  { id: "valuation", label: "Valuation", n: "04", icon: Scale },
  { id: "strategies", label: "Strategies", n: "05", icon: Boxes },
  { id: "recommend", label: "Recommend", n: "06", icon: Sparkles },
  { id: "correlations", label: "Correlations", n: "07", icon: GitCompare },
  { id: "timing", label: "Timing", n: "08", icon: Crosshair },
] as const;
type TabId = typeof TABS[number]["id"];

// 사분면 명칭·색은 visualParts(RegimeDonutCard)의 통일 맵 사용 — 배너 카드화로 이 파일 로컬 맵 제거

export interface TransplantPayload { sid: string; name: string; market: Market }
import { IndicatorsTab, OverviewTab, RegimeTab, ValuationTab } from "./MacroCockpit.tabs.core";
import { RecommendTab, StrategiesTab } from "./MacroCockpit.tabs.strategy";
import { CorrelationsTab, TimingTab } from "./MacroCockpit.tabs.analytics";


export default function MacroCockpit({ core, onTransplant, onOpenInAAS, aasBusy, aasError }: {
  core: MacroCore;
  onTransplant?: (p: TransplantPayload) => void;
  /** 현재 국면을 스냅샷으로 굳혀 Allocation Studio 로 넘긴다(서버 저장 → ?snapshot=<id>). */
  onOpenInAAS?: () => void;
  aasBusy?: boolean;
  aasError?: string | null;
}) {
  const [tab, setTab] = useState<TabId>("overview");
  const [market, setMarket] = useState<Market>("kr");
  const [strategies, setStrategies] = useState<MacroStrategies | null>(core.strategies);
  const [recommend, setRecommend] = useState<MacroRecommend | null>(core.recommend);
  const [mktLoading, setMktLoading] = useState(false);
  // 드릴다운
  const [drill, setDrill] = useState<{ id: string; series: MacroSeries | null; loading: boolean } | null>(null);
  // 07/08 lazy (탭 진입·시장 변경 시 로드) + 국면 궤적
  const [corr, setCorr] = useState<MacroCorrelations | null>(null);
  const [timing, setTiming] = useState<MacroTiming | null>(null);
  const [traj, setTraj] = useState<MacroTrajectory | null>(null);
  const [tabLoading, setTabLoading] = useState(false);
  // v2 lazy: CB 센티먼트(Indicators) + 그레인저 인과 그래프(Correlations)
  const [cbSent, setCbSent] = useState<CbSentiment | null | undefined>(undefined);
  const [causal, setCausal] = useState<CausalGraph | null | undefined>(undefined);
  // v3 lazy (밸리AI 흡수): 사이클 스트립·하위요인(Regime), 자산 스트립(Valuation), KR/US(Overview)
  const [strips, setStrips] = useState<CycleStrips | null | undefined>(undefined);
  const [axisHist, setAxisHist] = useState<AxisHistory | null | undefined>(undefined);
  const [aStrips, setAStrips] = useState<AssetStrips | null | undefined>(undefined);
  // krus(overview 기본탭)는 마운트 시 항상 발화하던 유일한 호출이라 useQuery로 캐시(다른
  // 서브탭 7종은 이미 탭 클릭 시에만 발화하는 지연로딩이라 그대로 유지).
  const { data: krusData } = useQuery({ queryKey: ["macro", "compare-krus"], queryFn: () => analysisApi.compareKrUs() });
  const krus = krusData ?? undefined;
  useEffect(() => {
    if (tab === "indicators" && cbSent === undefined)
      analysisApi.cbSentiment().then(setCbSent).catch(() => setCbSent(null));
    if (tab === "correlations" && causal === undefined)
      analysisApi.causalGraph().then(setCausal).catch(() => setCausal(null));
    if (tab === "regime" && strips === undefined) {
      analysisApi.cycleStrips("kr").then(setStrips).catch(() => setStrips(null));
      analysisApi.axisHistory("kr").then(setAxisHist).catch(() => setAxisHist(null));
    }
    if (tab === "valuation" && aStrips === undefined)
      analysisApi.assetStrips("kr").then(setAStrips).catch(() => setAStrips(null));
  }, [tab, cbSent, causal, strips, aStrips]);
  // 전략 상세 모달
  const [stratModal, setStratModal] = useState<{ sid: string; detail: StrategyDetail | null; loading: boolean } | null>(null);

  useEffect(() => {
    if (tab !== "correlations") return;
    let ok = true; setTabLoading(true);
    loadCorrelations(market).then((c) => { if (ok) { setCorr(c); setTabLoading(false); } });
    return () => { ok = false; };
  }, [tab, market]);
  useEffect(() => {
    if (tab !== "timing") return;
    let ok = true; setTabLoading(true);
    loadTiming(market).then((t) => { if (ok) { setTiming(t); setTabLoading(false); } });
    return () => { ok = false; };
  }, [tab, market]);
  useEffect(() => {
    if (tab === "regime" && !traj) loadTrajectory().then(setTraj);
  }, [tab, traj]);

  const regime = core.regime;
  const quad = resolveQuadrant(regime);
  const asOf = (core.dashboard?.as_of ?? regime?.timestamp ?? "").slice(0, 16).replace("T", " ");
  const realData = !!(core.dashboard?.sources.fred || core.dashboard?.sources.bok || core.valuation?.sources.prices);

  // 시장 토글 → strategies/recommend 재로드 (us는 코어 캐시 사용)
  useEffect(() => {
    let ok = true;
    if (market === "kr") { setStrategies(core.strategies); setRecommend(core.recommend); return; }
    setMktLoading(true);
    Promise.all([loadStrategies(market), loadRecommend(market)]).then(([s, r]) => {
      if (!ok) return; setStrategies(s); setRecommend(r); setMktLoading(false);
    });
    return () => { ok = false; };
  }, [market, core.strategies, core.recommend]);

  const openDrill = useCallback((id: string) => {
    setDrill({ id, series: null, loading: true });
    loadSeries(id).then((s) => setDrill((d) => (d && d.id === id ? { ...d, series: s, loading: false } : d)));
  }, []);

  const transplant = (sid: string, name: string) =>
    onTransplant?.({ sid, name, market });

  const openStrategy = useCallback((sid: string) => {
    setStratModal({ sid, detail: null, loading: true });
    loadStrategyDetail(sid, market).then((d) =>
      setStratModal((m) => (m && m.sid === sid ? { ...m, detail: d, loading: false } : m)));
  }, [market]);

  if (!regime) return <div className="mc-empty">매크로 데이터를 불러올 수 없습니다. 백엔드 연결을 확인하세요.</div>;

  return (
    <div className="mc">
      {/* ── 상단 3분할 카드 — 도넛 중심 국면 요약 (정보 위계: 결론 먼저, 서브지표 톤다운) ── */}
      <div className="mc-banner3">
        <RegimeDonutCard label="KR 국면" state={regime.markets?.kr ?? regime} />
        {regime.markets?.us && <RegimeDonutCard label="US 국면" state={regime.markets.us} />}
        <StressModeCard state={regime} realData={realData} asOf={asOf} />
      </div>

      {/* ── 한줄 브리핑 + 스토리 앵커 (밸리AI '차례로 짚어보기' UX) ── */}
      <div className="mc-brief">
        <span className="mc-brief-txt">{buildBriefing(regime.markets?.kr ?? regime)}</span>
        <span className="mc-brief-chips">
          {([["성장·물가", "regime"], ["지표·CB톤", "indicators"], ["자산 밸류", "valuation"],
             ["상관·인과", "correlations"], ["배분 추천", "recommend"]] as const).map(([lbl, t]) => (
            <button key={t} className={`mc-brief-chip${tab === t ? " on" : ""}`} onClick={() => setTab(t)}>{lbl} →</button>
          ))}
          {/* 현재 국면을 불변 스냅샷으로 고정해 AAS 로 — 휘발성 복사가 아니라 서버 ID 전달 */}
          {onOpenInAAS && (
            <button className="mc-brief-chip mc-open-aas" onClick={onOpenInAAS} disabled={aasBusy}
              title="현재 국면 판정을 스냅샷으로 저장하고 Allocation Studio 에서 엽니다">
              {aasBusy ? "스냅샷 생성 중…" : "Allocation Studio에서 열기 →"}
            </button>
          )}
        </span>
      </div>
      {aasError && <div className="mc-aas-err" role="alert">{aasError}</div>}

      {/* ── 서브탭 ── */}
      <div className="mc-tabs">
        {TABS.map((t) => { const I = t.icon; return (
          <button key={t.id} className={`mc-tab${tab === t.id ? " on" : ""}`} onClick={() => setTab(t.id)}>
            <span className="mc-tab-n">{t.n}</span><I size={14} />{t.label}
          </button>
        ); })}
      </div>

      {tab === "overview" && <OverviewTab core={core} regime={regime} quad={quad} recommend={recommend} onTransplant={transplant} onDrill={openDrill} krus={krus} />}
      {tab === "indicators" && <IndicatorsTab core={core} onDrill={openDrill} cbSent={cbSent} />}
      {tab === "regime" && <RegimeTab regime={regime} traj={traj} strips={strips} axisHist={axisHist} />}
      {tab === "valuation" && <ValuationTab core={core} aStrips={aStrips} />}
      {tab === "strategies" && <StrategiesTab strategies={strategies} market={market} setMarket={setMarket} loading={mktLoading} onTransplant={transplant} onOpen={openStrategy} />}
      {tab === "recommend" && <RecommendTab recommend={recommend} market={market} setMarket={setMarket} loading={mktLoading} onTransplant={transplant} />}
      {tab === "correlations" && <CorrelationsTab corr={corr} market={market} setMarket={setMarket} loading={tabLoading} causal={causal} />}
      {tab === "timing" && <TimingTab timing={timing} market={market} setMarket={setMarket} loading={tabLoading} />}

      {drill && <DrillDownModal series={drill.series} loading={drill.loading} onClose={() => setDrill(null)} />}
      {stratModal && (
        <StrategyModal
          detail={stratModal.detail} loading={stratModal.loading} currentQuad={quad} market={market}
          onClose={() => setStratModal(null)}
          onBacktest={(d) => { transplant(d.id, d.name); setStratModal(null); }}
        />
      )}
    </div>
  );
}

