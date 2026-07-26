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
import type { CausalGraph, CbSentiment, MacroCorrelations, MacroRecommend, MacroStrategies, MacroTiming, MacroTrajectory, StrategyDetail, TacticalHolding, TacticalStrategy } from "@/entities/macro";
import { analysisApi } from "@/entities/macro";
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
import type { AssetStrips, AxisHistory, CycleStrips, KrUsCompare } from "@/entities/macro";

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

export default function MacroCockpit({ core, onTransplant }: { core: MacroCore; onTransplant?: (p: TransplantPayload) => void }) {
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
        </span>
      </div>

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

// ─────────────────────────────────────────────────────────────────────────────
// 01 Overview
// ─────────────────────────────────────────────────────────────────────────────
function OverviewTab({ core, regime, quad, recommend, onTransplant, onDrill, krus }: {
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
function IndicatorsTab({ core, onDrill, cbSent }: { core: MacroCore; onDrill: (id: string) => void; cbSent?: CbSentiment | null }) {
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
function RegimeTab({ regime, traj, strips, axisHist }: {
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
function ValuationTab({ core, aStrips }: { core: MacroCore; aStrips?: AssetStrips | null }) {
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
function MarketToggle({ market, setMarket }: { market: Market; setMarket: (m: Market) => void }) {
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

function StrategiesTab({ strategies, market, setMarket, loading, onTransplant, onOpen }: {
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

function StrategyCard({ s, onTransplant, onOpen }: { s: TacticalStrategy; onTransplant: (sid: string, name: string) => void; onOpen: (sid: string) => void }) {
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
function RecommendTab({ recommend, market, setMarket, loading, onTransplant }: {
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
function CorrelationsTab({ corr, market, setMarket, loading, causal }: {
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
function TimingTab({ timing, market, setMarket, loading }: {
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
