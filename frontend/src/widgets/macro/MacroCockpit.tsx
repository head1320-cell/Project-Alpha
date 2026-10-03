"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// MacroCockpit — 매크로 분석 (BU5a: 머리 · 탭 · 실패를 실패로)
//   머리 = 답 한 문장(서버 국면의 번역 — ADR-003 §2.6) + 근거 숫자·칩 + 행동 하나[포트폴리오 설계에 넣기].
//   탭 8: 개요 · 지표 · 국면 · 가치 · 전략 · 추천 · 상관 · 타이밍 (id `mc-tab-{id}` · 로빙 tabindex 는 그대로).
//   ★연습용 표시는 connection-status.mock_allowed 로만★ — 예전처럼 대시보드 출처(fred/bok/prices)로 추론하지 않는다(홈과 같은 규칙).
//   ★실패는 실패로★ 코어 데이터가 실패하면 그 탭 안 alert + [다시 시도] · 한국·미국 비교·국면 궤적은 "계산 중"에 영원히 머물지 않는다.
//   탭 안쪽 카드(영어 제목·툴팁·등락색)는 BU5b.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState, useEffect, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
// ★기본이 '닫힘' 인 창은 첫 로드에 있을 이유가 없다★ 두 창이 Radix Dialog 를 쓰면서
// /macro 첫 로드가 243 → 263 kB 로 뛰었다(실측). ADR 001 은 설명되지 않는 4 kB 증가를
// 되돌리라고 한다 — 되돌리는 대신 **필요할 때 가져온다**.
const StrategyModal = dynamic(() => import("./StrategyModal"), { ssr: false });
const DrillDownModal = dynamic(
  () => import("./DrillDownModal").then((m) => m.DrillDownModal), { ssr: false });
import { useQuery } from "@tanstack/react-query";
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
import { macroApi } from "@/entities/macro/api";
import { MODE_KO, regimeFig, regimeName, sourceChip, when } from "@/entities/macro/regimeKo";
import { Answer, Notice, Unknown, type Chip, type Figure } from "@/shared/ui/tx";
import { RegimeVisual } from "./RegimeVisual";
import type { AssetStrips, AxisHistory, CycleStrips, KrUsCompare } from "@/entities/macro/analysisModel";

/** 탭은 순서가 아니라 주제라 번호를 달지 않는다. id 는 E2E 계약(`#mc-tab-{id}`) — 이름을 바꿔도 id 는 그대로. */
const TABS = [
  { id: "overview", label: "개요" },
  { id: "indicators", label: "지표" },
  { id: "regime", label: "국면" },
  { id: "valuation", label: "가치" },
  { id: "strategies", label: "전략" },
  { id: "recommend", label: "추천" },
  { id: "correlations", label: "상관" },
  { id: "timing", label: "타이밍" },
] as const;
type TabId = typeof TABS[number]["id"];

/** 화면이 함께 불러오는 코어 데이터 — 실패한 것만 `coreFail` 에 [다시 시도] 함수로 들어온다. */
export type CoreKey = "dashboard" | "valuation" | "strategies" | "recommend";
/** 이름 + 목적격 조사(받침에 따라 을/를) — 조사를 계산하지 않고 적어 둔다(넷뿐이다). */
const CORE_KO: Record<CoreKey, string> = {
  dashboard: "지표 대시보드를", valuation: "자산 가치를", strategies: "전략 목록을", recommend: "추천 배분을",
};
/** 탭이 무엇을 주 데이터로 쓰는지 — 주 데이터가 실패하면 탭 몸통 대신 실패를 말한다. 개요는 국면만으로도 그려지므로 위에 알리기만 한다. */
const TAB_NEEDS: Partial<Record<TabId, { main?: CoreKey; also?: CoreKey[] }>> = {
  overview: { also: ["dashboard", "recommend"] },
  indicators: { main: "dashboard" },
  valuation: { main: "valuation" },
  strategies: { main: "strategies" },
  recommend: { main: "recommend" },
};

function CoreFail({ k, retry }: { k: CoreKey; retry: () => void }) {
  return (
    <Notice tone="danger" title={`${CORE_KO[k]} 불러오지 못했어요`}>
      서버에 닿지 못했거나 계산이 실패했어요. 받은 데이터로 그릴 수 있는 것만 보여 드려요.
      <div className="mc-act"><button type="button" className="tx-btn tx-btn--sub" onClick={retry}>다시 시도</button></div>
    </Notice>
  );
}

export interface TransplantPayload { sid: string; name: string; market: Market }
import { IndicatorsTab, OverviewTab, RegimeTab, ValuationTab } from "./MacroCockpit.tabs.core";
import { RecommendTab, StrategiesTab } from "./MacroCockpit.tabs.strategy";
import { CorrelationsTab, TimingTab } from "./MacroCockpit.tabs.analytics";


export default function MacroCockpit({ core, coreFail = {}, onTransplant, onOpenInAAS, aasBusy, aasError }: {
  core: MacroCore & { regime: NonNullable<MacroCore["regime"]> };
  /** 실패한 코어 데이터 → 다시 묻는 함수. 비어 있으면 모두 받았다. */
  coreFail?: Partial<Record<CoreKey, () => void>>;
  onTransplant?: (p: TransplantPayload) => void;
  /** 현재 국면을 스냅샷으로 굳혀 포트폴리오 설계(캔버스)로 넘긴다(서버 저장 → ?snapshot=<id>). */
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
  // undefined = 아직 · null = 실패 · 값 = 받음 (예전엔 실패도 "불러오는 중"으로 영원히 남았다)
  const [traj, setTraj] = useState<MacroTrajectory | null | undefined>(undefined);
  const [tabLoading, setTabLoading] = useState(false);
  // v2 lazy: CB 센티먼트(Indicators) + 그레인저 인과 그래프(Correlations)
  const [cbSent, setCbSent] = useState<CbSentiment | null | undefined>(undefined);
  const [causal, setCausal] = useState<CausalGraph | null | undefined>(undefined);
  // v3 lazy (밸리AI 흡수): 사이클 스트립·하위요인(Regime), 자산 스트립(Valuation), KR/US(Overview)
  const [strips, setStrips] = useState<CycleStrips | null | undefined>(undefined);
  const [axisHist, setAxisHist] = useState<AxisHistory | null | undefined>(undefined);
  const [aStrips, setAStrips] = useState<AssetStrips | null | undefined>(undefined);
  // krus(개요 기본탭)는 마운트 시 항상 발화하던 유일한 호출이라 useQuery로 캐시(다른
  // 서브탭 7종은 이미 탭 클릭 시에만 발화하는 지연로딩이라 그대로 유지).
  // ★실패는 null★ — 예전엔 실패가 undefined 로 남아 "비교 계산 중…"이 영원히 보였다.
  const krusQ = useQuery({ queryKey: ["macro", "compare-krus"], queryFn: () => analysisApi.compareKrUs() });
  const krus = krusQ.isError ? null : krusQ.data;
  const cs = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus() });
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
    // 실패(null)는 자동으로 다시 묻지 않는다(되풀이 요청 방지) — 화면이 실패를 말한다.
    if (tab === "regime" && traj === undefined) loadTrajectory().then(setTraj);
  }, [tab, traj]);

  const regime = core.regime;
  const quad = resolveQuadrant(regime);

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

  // ── 답 한 문장 — 서버 국면을 옮긴 것뿐(새 판단 없음). 한국 = markets.kr(없으면 최상위 = 한국 축 모형). ──
  const kr = regime.markets?.kr ?? regime;
  const us = regime.markets?.us;
  const sentence = us
    ? `한국은 ‘${regimeName(kr.regime)}’, 미국은 ‘${regimeName(us.regime)}’ 쪽이에요`
    : `한국은 ‘${regimeName(kr.regime)}’ 쪽이에요`;
  const figures: Figure[] = [
    { label: "한국", value: regimeFig(kr) },
    { label: "미국", value: us ? regimeFig(us) : <Unknown reason="미국 국면을 받지 못했어요" /> },
    { label: "시장 스트레스", value: Number.isFinite(regime.stress_score) ? `${Math.round(regime.stress_score)}/100` : <Unknown reason="스트레스 값을 받지 못했어요" /> },
    { label: "권장 단계", value: MODE_KO[regime.recommended_mode] ?? regime.recommended_mode },
    ...(typeof regime.yield_inversion === "boolean" ? [{
      label: "수익률 곡선",
      value: regime.yield_inversion
        ? `역전${regime.inversion_severity != null && Number.isFinite(regime.inversion_severity) ? ` ${Math.round(regime.inversion_severity)}bp` : ""}`
        : "역전 아님",
    }] : []),
  ];
  const at = when(regime.timestamp);
  const chips: Chip[] = [
    ...sourceChip({ data: cs.data, isError: cs.isError, isLoading: cs.isLoading }),
    { label: "국면 확률은 축 모형 하나로 쟀어요", tone: "info" },
    ...(at ? [{ label: at, tone: "plain" as const }] : []),
  ];
  const need = TAB_NEEDS[tab];
  const mainFail = need?.main && (tab !== "strategies" && tab !== "recommend" || market === "kr") ? coreFail[need.main] : undefined;

  return (
    <div className="mc tx-page tx-page--wide">
      <header className="mc-head">
        {/* 제목(PageHead "매크로 분석")은 레이아웃이 내비 위에 단다 — 여기서는 답부터. */}
        <Answer sentence={sentence} figures={figures} chips={chips}
          action={onOpenInAAS ? (<>
            {/* 현재 국면을 불변 스냅샷으로 고정해 캔버스로 — 휘발성 복사가 아니라 서버 ID 전달 */}
            <button type="button" className="tx-btn tx-btn--main mc-open-aas" onClick={onOpenInAAS} disabled={aasBusy}>
              {aasBusy ? "스냅샷을 저장하는 중이에요…" : "포트폴리오 설계에 넣기"}
            </button>
            <span className="mc-head-note">지금 국면을 스냅샷으로 저장해 포트폴리오 설계의 국면 노드에 넣어요.</span>
          </>) : undefined} />
        {aasError && (
          <Notice tone="danger" title="포트폴리오 설계로 넘기지 못했어요">{aasError}</Notice>
        )}
      </header>

      {/* BU5a+ — 답과 같은 서버 값을 그림으로(도넛 2 + 스트레스 반원). 옛 도넛 카드를 지운 BU5a 의 잘못을 되돌리며 더 낫게. */}
      <RegimeVisual regime={regime} />

      {/* ── 서브탭 ──
          ★Radix Tabs 를 썼다가 되돌렸다 — 실측 +11 kB★
          /macro 는 243 → 254 kB 가 됐다. ADR 001 한도는 4 kB 이고, 탭 바는 늘 보이므로
          `next/dynamic` 으로 뺄 수도 없다(EvidenceDrawer 와 다른 점이다).
          Radix 가 주는 것은 roving tabindex 와 aria 연결인데, 방향 전환도 수동 활성화도
          없는 단순 수평 탭 바에서는 아래 30줄로 같은 것을 얻는다 — 11 kB 를 낼 이유가 없다.
          (계획서는 "손수 만들지 말라" 고 했지만 그 근거는 비용을 재기 전 판단이었다.)
          동작은 스펙(macro-tabs.spec.ts)이 지킨다 — 구현이 무엇이든 계약은 같다. */}
      <div className="mc-tabs" role="tablist" aria-label="매크로 분석 보기"
        onKeyDown={(e) => {
          const i = TABS.findIndex((t) => t.id === tab);
          const to = e.key === "ArrowRight" ? (i + 1) % TABS.length
            : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length
            : e.key === "Home" ? 0
            : e.key === "End" ? TABS.length - 1 : -1;
          if (to < 0) return;
          e.preventDefault();
          setTab(TABS[to].id);
          // 포커스도 함께 옮긴다 — 선택만 바뀌고 포커스가 남으면 키보드 사용자는 길을 잃는다.
          (e.currentTarget.children[to] as HTMLElement | undefined)?.focus();
        }}>
        {TABS.map((t) => { const on = tab === t.id; return (
          <button key={t.id} type="button" className={`mc-tab${on ? " on" : ""}`} onClick={() => setTab(t.id)}
            role="tab" id={`mc-tab-${t.id}`} aria-controls={`mc-panel-${t.id}`}
            aria-selected={on} tabIndex={on ? 0 : -1}>
            {t.label}
          </button>
        ); })}
      </div>

      {/* 패널은 활성 탭만 마운트한다(기존 동작 그대로). */}
      <div role="tabpanel" id={`mc-panel-${tab}`} aria-labelledby={`mc-tab-${tab}`}>
        {/* 주 데이터가 실패한 탭은 몸통 대신 실패를 말한다(빈 카드를 "데이터 없음"처럼 두지 않는다) · 보조 데이터 실패는 위에 알린다 */}
        {mainFail && need?.main && <CoreFail k={need.main} retry={mainFail} />}
        {!mainFail && (need?.also ?? []).filter((k) => coreFail[k]).map((k) => <CoreFail key={k} k={k} retry={coreFail[k]!} />)}
        {mainFail ? null : <>
        {tab === "overview" && <OverviewTab core={core} regime={regime} quad={quad} recommend={recommend} onTransplant={transplant} onDrill={openDrill} krus={krus} onRetryKrus={() => { void krusQ.refetch(); }} />}
        {tab === "indicators" && <IndicatorsTab core={core} onDrill={openDrill} cbSent={cbSent} />}
        {tab === "regime" && <RegimeTab regime={regime} traj={traj} onRetryTraj={() => setTraj(undefined)} strips={strips} axisHist={axisHist} />}
        {tab === "valuation" && <ValuationTab core={core} aStrips={aStrips} />}
        {tab === "strategies" && <StrategiesTab strategies={strategies} market={market} setMarket={setMarket} loading={mktLoading} onTransplant={transplant} onOpen={openStrategy} />}
        {tab === "recommend" && <RecommendTab recommend={recommend} market={market} setMarket={setMarket} loading={mktLoading} onTransplant={transplant} />}
        {tab === "correlations" && <CorrelationsTab corr={corr} market={market} setMarket={setMarket} loading={tabLoading} causal={causal} />}
        {tab === "timing" && <TimingTab timing={timing} market={market} setMarket={setMarket} loading={tabLoading} />}
        </>}
      </div>

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

