"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// MacroCockpit — Macro Allocation Cockpit (자산배분·마켓타이밍 의사결정 콕핏)
//   고정 레짐 배너 + 6 서브탭: 01 Overview · 02 Indicators · 03 Regime ·
//   04 Valuation · 05 Strategies(US⇄KR) · 06 Recommend(규칙+성과+AI).
//   전부 실데이터(키 있으면) — 백엔드 mock 폴백 시 출처 배지로 정직 표기.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  LayoutDashboard, Activity, Target, Scale, Boxes, Sparkles,
  TrendingUp, TrendingDown, ArrowRightLeft, Play,
} from "lucide-react";
import type { MacroSeries } from "@/lib/macroApi";
import { stressColor } from "@/lib/macroApi";
import type { MacroStrategies, MacroRecommend, TacticalStrategy, TacticalHolding } from "@/lib/screenerApi";
import {
  type MacroCore, type Market, loadStrategies, loadRecommend, loadSeries, resolveQuadrant,
} from "@/lib/macroData";
import {
  RegimeScatter, CycleClock, ArcGauge, YieldCurveChart, IndicatorCard, ZHeatmap,
  ValuationBars, HoldingsDonut, donutColor, SignalBadge, CompositeRow, DrillDownModal,
  fmtNum, fmtZ, fmtPct, sigColor,
} from "./cockpitParts";

const TABS = [
  { id: "overview", label: "Overview", n: "01", icon: LayoutDashboard },
  { id: "indicators", label: "Indicators", n: "02", icon: Activity },
  { id: "regime", label: "Regime", n: "03", icon: Target },
  { id: "valuation", label: "Valuation", n: "04", icon: Scale },
  { id: "strategies", label: "Strategies", n: "05", icon: Boxes },
  { id: "recommend", label: "Recommend", n: "06", icon: Sparkles },
] as const;
type TabId = typeof TABS[number]["id"];

const QUAD_KR: Record<string, string> = {
  Reflation: "리플레이션 · 성장↑·물가↓", Overheating: "과열 · 성장↑·물가↑",
  Stagflation: "스태그플레이션 · 성장↓·물가↑", Disinflation: "디스인플레이션 · 성장↓·물가↓",
};
const QUAD_TONE: Record<string, string> = {
  Reflation: "var(--color-bull)", Overheating: "#ea580c", Stagflation: "var(--color-bear)", Disinflation: "#2563eb",
};

export interface TransplantPayload { strategyName: string; holdings: TacticalHolding[]; market: Market }

export default function MacroCockpit({ core, onTransplant }: { core: MacroCore; onTransplant?: (p: TransplantPayload) => void }) {
  const [tab, setTab] = useState<TabId>("overview");
  const [market, setMarket] = useState<Market>("us");
  const [strategies, setStrategies] = useState<MacroStrategies | null>(core.strategies);
  const [recommend, setRecommend] = useState<MacroRecommend | null>(core.recommend);
  const [mktLoading, setMktLoading] = useState(false);
  // 드릴다운
  const [drill, setDrill] = useState<{ id: string; series: MacroSeries | null; loading: boolean } | null>(null);

  const regime = core.regime;
  const quad = resolveQuadrant(regime);
  const asOf = (core.dashboard?.as_of ?? regime?.timestamp ?? "").slice(0, 16).replace("T", " ");
  const realData = !!(core.dashboard?.sources.fred || core.dashboard?.sources.bok || core.valuation?.sources.prices);

  // 시장 토글 → strategies/recommend 재로드 (us는 코어 캐시 사용)
  useEffect(() => {
    let ok = true;
    if (market === "us") { setStrategies(core.strategies); setRecommend(core.recommend); return; }
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

  const transplant = (s: { name: string; holdings: TacticalHolding[] }) =>
    onTransplant?.({ strategyName: s.name, holdings: s.holdings, market });

  if (!regime) return <div className="mc-empty">매크로 데이터를 불러올 수 없습니다. 백엔드 연결을 확인하세요.</div>;

  return (
    <div className="mc">
      {/* ── 고정 레짐 배너 ── */}
      <div className="mc-banner">
        <div className="mc-banner-quad" style={{ borderColor: QUAD_TONE[quad] }}>
          <span className="mc-banner-lbl">현재 국면</span>
          <b style={{ color: QUAD_TONE[quad] }}>{quad}</b>
          <em>{QUAD_KR[quad]}</em>
        </div>
        <div className="mc-banner-axes">
          <div className="mc-axis"><span>성장</span><b style={{ color: regime.growth_axis >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{regime.growth_axis >= 0 ? "+" : ""}{regime.growth_axis.toFixed(2)}</b></div>
          <div className="mc-axis"><span>물가</span><b style={{ color: regime.inflation_axis >= 0 ? "var(--color-bear)" : "var(--color-bull)" }}>{regime.inflation_axis >= 0 ? "+" : ""}{regime.inflation_axis.toFixed(2)}</b></div>
          <div className="mc-axis"><span>Stress</span><b style={{ color: stressColor(regime.stress_score) }}>{regime.stress_score.toFixed(0)}</b></div>
          <div className="mc-axis"><span>모드</span><b className="mc-axis-mode">{regime.recommended_mode}</b></div>
          <div className="mc-axis"><span>신뢰도</span><b>{(regime.confidence * 100).toFixed(0)}%</b></div>
        </div>
        <div className="mc-banner-meta">
          <span className={`mc-src ${realData ? "real" : "mock"}`}>{realData ? "실데이터" : "MOCK"}</span>
          <span className="mc-asof">{asOf}</span>
        </div>
      </div>

      {/* ── 서브탭 ── */}
      <div className="mc-tabs">
        {TABS.map((t) => { const I = t.icon; return (
          <button key={t.id} className={`mc-tab${tab === t.id ? " on" : ""}`} onClick={() => setTab(t.id)}>
            <span className="mc-tab-n">{t.n}</span><I size={14} />{t.label}
          </button>
        ); })}
      </div>

      {tab === "overview" && <OverviewTab core={core} regime={regime} quad={quad} recommend={recommend} onTransplant={transplant} onDrill={openDrill} />}
      {tab === "indicators" && <IndicatorsTab core={core} onDrill={openDrill} />}
      {tab === "regime" && <RegimeTab regime={regime} />}
      {tab === "valuation" && <ValuationTab core={core} />}
      {tab === "strategies" && <StrategiesTab strategies={strategies} market={market} setMarket={setMarket} loading={mktLoading} onTransplant={transplant} />}
      {tab === "recommend" && <RecommendTab recommend={recommend} market={market} setMarket={setMarket} loading={mktLoading} onTransplant={transplant} />}

      {drill && <DrillDownModal series={drill.series} loading={drill.loading} onClose={() => setDrill(null)} />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 01 Overview
// ─────────────────────────────────────────────────────────────────────────────
function OverviewTab({ core, regime, quad, recommend, onTransplant, onDrill }: {
  core: MacroCore; regime: NonNullable<MacroCore["regime"]>; quad: string; recommend: MacroRecommend | null;
  onTransplant: (s: { name: string; holdings: TacticalHolding[] }) => void; onDrill: (id: string) => void;
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
        {recommend?.top ? (
          <div className="mc-reco-mini">
            <div className="mc-reco-mini-l">
              <HoldingsDonut holdings={recommend.top.holdings} size={108} />
            </div>
            <div className="mc-reco-mini-r">
              <div className="mc-reco-mini-nm"><b>{recommend.top.name}</b><SignalBadge signal={recommend.top.signal} /></div>
              <div className="mc-reco-mini-stats">
                <span>적합도 <b>{recommend.top.fit_score.toFixed(0)}</b></span>
                <span>종합 <b>{recommend.top.composite.toFixed(0)}</b></span>
              </div>
              <div className="mc-reco-mini-hold">
                {recommend.top.holdings.slice(0, 6).map((h, idx) => (
                  <span key={h.ticker} className="mc-hchip"><i style={{ background: donutColor(idx) }} />{h.us_label} {h.weight}%</span>
                ))}
              </div>
              <button className="mc-bt-btn" onClick={() => onTransplant({ name: recommend.top.name, holdings: recommend.top.holdings })}><Play size={12} /> 이 배분으로 백테스트 →</button>
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
function IndicatorsTab({ core, onDrill }: { core: MacroCore; onDrill: (id: string) => void }) {
  const d = core.dashboard;
  if (!d) return <div className="mc-empty-sm">대시보드 데이터 없음</div>;
  return (
    <div className="mc-stack">
      <div className="mc-card">
        <div className="mc-card-h">매크로 히트맵 — 25지표 × Z-Score(5년) <span className="mc-card-sub">{d.sources.fred ? "FRED" : "mock"} · {d.sources.bok ? "ECOS" : "mock"}</span></div>
        <ZHeatmap themes={d.themes} onPick={(ind) => onDrill(ind.id)} />
        <div className="mc-zlegend"><span>낮음</span><i className="mc-zleg-grad" /><span>높음</span><em>· 셀 클릭 → 36개월 시계열</em></div>
      </div>
      {d.themes.map((t) => (
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
function RegimeTab({ regime }: { regime: NonNullable<MacroCore["regime"]> }) {
  const sc = Object.entries(regime.stress_components ?? {});
  const tilts = Object.entries(regime.asset_tilts ?? {});
  const tiltMap: Record<string, { v: number; lbl: string }> = {
    "++": { v: 2, lbl: "강한 비중확대" }, "+": { v: 1, lbl: "비중확대" }, "0": { v: 0, lbl: "중립" },
    "-": { v: -1, lbl: "비중축소" }, "--": { v: -2, lbl: "강한 비중축소" },
  };
  return (
    <div className="mc-grid">
      <div className="mc-card span2">
        <div className="mc-card-h">국면 좌표 (성장 × 물가)</div>
        <RegimeScatter g={regime.growth_axis} i={regime.inflation_axis} />
      </div>
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
function ValuationTab({ core }: { core: MacroCore }) {
  const v = core.valuation;
  if (!v) return <div className="mc-empty-sm">밸류에이션 데이터 없음</div>;
  return (
    <div className="mc-grid">
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

function StrategiesTab({ strategies, market, setMarket, loading, onTransplant }: {
  strategies: MacroStrategies | null; market: Market; setMarket: (m: Market) => void; loading: boolean;
  onTransplant: (s: { name: string; holdings: TacticalHolding[] }) => void;
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
            {g.items.map((s) => <StrategyCard key={s.id} s={s} onTransplant={onTransplant} />)}
          </div>
        </div>
      )) : !loading && <div className="mc-empty-sm">전략 데이터 없음</div>}
    </div>
  );
}

function StrategyCard({ s, onTransplant }: { s: TacticalStrategy; onTransplant: (s: { name: string; holdings: TacticalHolding[] }) => void }) {
  const top = [...s.holdings].sort((a, b) => b.weight - a.weight).slice(0, 6);
  return (
    <div className="mc-stratcard">
      <div className="mc-stratcard-h">
        <div><b>{s.name}</b><SignalBadge signal={s.signal} /></div>
        <button className="mc-bt-btn sm" onClick={() => onTransplant({ name: s.name, holdings: s.holdings })}><Play size={11} /> 백테스트</button>
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
  onTransplant: (s: { name: string; holdings: TacticalHolding[] }) => void;
}) {
  if (loading) return <div className="mc-empty-sm">추천 재계산 중…</div>;
  if (!recommend) return <div className="mc-empty-sm">추천 데이터 없음</div>;
  const top = recommend.top;
  return (
    <div className="mc-stack">
      <div className="mc-strat-bar">
        <div className="mc-strat-title">국면 기반 추천 <span className="mc-card-sub">{recommend.regime.quadrant_kr} · Stress {recommend.regime.stress.toFixed(0)}</span></div>
        <MarketToggle market={market} setMarket={setMarket} />
      </div>
      <div className="mc-grid">
        <div className="mc-card span2">
          <div className="mc-card-h">최우선 추천 <SignalBadge signal={top.signal} /></div>
          <div className="mc-reco">
            <div className="mc-reco-l">
              <HoldingsDonut holdings={top.holdings} size={150} />
              <ArcGauge value={top.fit_score} color={sigColor(top.signal)} label="적합도" height={104} />
            </div>
            <div className="mc-reco-r">
              <div className="mc-reco-nm">{top.name}</div>
              <div className="mc-reco-comp">종합점수 <b>{top.composite.toFixed(0)}</b> / 100</div>
              <div className="mc-reco-holds">
                {top.holdings.map((h, idx) => (
                  <div key={h.ticker} className="mc-hold-row">
                    <i style={{ background: donutColor(idx) }} />
                    <span className="mc-hold-nm">{h.us_label}</span>
                    <span className="mc-hold-tk">{h.ticker}</span>
                    <div className="mc-hold-bar"><b style={{ width: `${h.weight}%`, background: donutColor(idx) }} /></div>
                    <span className="mc-hold-w">{h.weight}%</span>
                  </div>
                ))}
              </div>
              <button className="mc-bt-btn" onClick={() => onTransplant({ name: top.name, holdings: top.holdings })}><Play size={12} /> 이 배분으로 백테스트 →</button>
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
        </div>
      </div>
    </div>
  );
}
