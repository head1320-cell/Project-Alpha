"use client";
// 00 OVERVIEW — 전체 워크플로우 요약 대시보드. 6칸 KPI + 12-col 그리드.
// 각 카드 우상단 NN↗ 크로스링크로 해당 스테이지 드릴다운 (Master-Detail).
// (위저드 진입점은 게이트(/allocation) — 이 화면은 "요약" 북엔드로 접근.)
import React from "react";
import { useRouter } from "next/navigation";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { overallConfidence } from "@/widgets/allocation/ViewBuilder";
import { ResearchTimeline } from "@/widgets/allocation/ResearchTimeline";
import { ResearchIndex } from "@/widgets/allocation/ResearchIndex";
import {
  FactorXRayBars, FrontierChart, RiskContribDonut, fmtSign,
} from "@/widgets/allocation/parts";

function Xlink({ to, label }: { to: string; label: string }) {
  const router = useRouter();
  return <button className="aas-xlink" title={`${label} 스테이지로 이동`} onClick={() => router.push(to)}>{label} ↗</button>;
}

export default function OverviewStage() {
  const { holdings, result, xrayQ, stressQ, timeline, delta, views } = useAllocation();
  const pf = result?.summary?.portfolio;
  const conf = Math.round(overallConfidence(views));

  const kpis = [
    { l: "기대수익(연)", v: pf ? `${fmtSign(pf.expected_return_pct, 1)}%` : "—", vc: undefined, s: "최적화 포트폴리오", sc: "var(--t-muted)" },
    { l: "변동성(연)", v: pf ? `${pf.volatility_pct}%` : "—", vc: undefined, s: "연율화 σ", sc: "var(--t-muted)" },
    { l: "Sharpe", v: pf ? pf.sharpe.toFixed(2) : "—", vc: undefined, s: "위험조정수익", sc: "var(--t-muted)" },
    { l: "95% VaR", v: result ? `-${result.mc.var95_pct}%` : "—", vc: "var(--color-bear)", s: "MC 1년", sc: "var(--color-bear)" },
    { l: "최대낙폭", v: pf ? `${pf.max_drawdown_pct}%` : "—", vc: "var(--color-bear)", s: "히스토리컬", sc: "var(--color-bear)" },
    { l: "뷰 신뢰도", v: views.length ? `${conf}%` : "—", vc: "var(--t-accent)", s: `${views.length} 뷰`, sc: "var(--t-muted)" },
  ];

  const optW = result ? Object.entries(result.weights.optimized).sort((a, b) => b[1] - a[1]) : [];
  const robust = [
    stressQ.data?.available && stressQ.data.mode === "hypothetical"
      ? { l: stressQ.data.label, m: "추정 충격", v: `${fmtSign(stressQ.data.portfolio_shock_pct ?? 0, 1)}%`, c: (stressQ.data.portfolio_shock_pct ?? 0) >= 0 ? "var(--color-bull)" : "var(--color-bear)" }
      : stressQ.data?.available && stressQ.data.mode === "historical"
        ? { l: stressQ.data.label, m: "최대낙폭", v: `${stressQ.data.max_dd_pct?.toFixed(1)}%`, c: "var(--color-bear)" }
        : null,
  ].filter(Boolean) as { l: string; m: string; v: string; c: string }[];

  return (
    <>
      {/* ★신원이 수치보다 먼저다★ (P4)
          대시보드는 숫자를 먼저 보여주지만 리서치 색인은 "무엇을 연구 중인가" 를 먼저
          보여준다. 아래 KPI·분석 격자는 그대로 둔다 — 쓸모 있는 분석을 지우는 것은
          색인화가 아니다. 순서만 바꿨다. */}
      <ResearchIndex />

      <div className="aas-kpi">
        {kpis.map((k) => (
          <div key={k.l} className="aas-kpi-c">
            <div className="aas-kpi-l">{k.l}</div>
            <div className="aas-kpi-v" style={{ color: k.vc }}>{k.v}</div>
            <div className="aas-kpi-s" style={{ color: k.sc }}>{k.s}</div>
          </div>
        ))}
      </div>

      <div className="aas-ov">
        <section className="as-card" style={{ gridColumn: "span 5" }}>
          <div className="as-card-title">EFFICIENT FRONTIER
            {result?.views_applied && <span className="as-badge">BL 뷰 적용</span>}
            <Xlink to="/allocation/optimize" label="05" />
          </div>
          {result ? <FrontierChart result={result} lam={delta} height={210} />
            : <div className="as-empty" style={{ height: 210, display: "flex", alignItems: "center", justifyContent: "center" }}>01 CONSTRUCT → 03 OPTIMIZE에서 실행</div>}
        </section>

        <section className="as-card" style={{ gridColumn: "span 4" }}>
          <div className="as-card-title">OPTIMIZED WEIGHTS <span className="as-note-inline">Δ vs 현재</span><Xlink to="/allocation/explain" label="07" /><Xlink to="/allocation/execution" label="08" /></div>
          {optW.length ? optW.slice(0, 6).map(([c, w]) => {
            const cur = holdings.find((h) => h.code === c)?.weight ?? 0;
            const d = w - cur;
            return (
              <div key={c} className="as-wrow">
                <span className="as-wrow-nm">{result?.labels[c] || c}</span>
                <div className="as-wrow-bar"><i style={{ width: `${Math.min(w, 100)}%` }} /></div>
                <span className="num">{w.toFixed(1)}%</span>
                <span className="num" style={{ fontSize: 9.5, color: d >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{fmtSign(d, 1)}</span>
              </div>
            );
          }) : <div className="as-empty">Re-optimize 실행 시 표시</div>}
        </section>

        <section className="as-card" style={{ gridColumn: "span 3" }}>
          <div className="as-card-title">RISK CONTRIBUTION<Xlink to="/allocation/explain" label="07" /></div>
          {result ? <RiskContribDonut contributions={result.risk_contributions} labels={result.labels} size={96} />
            : <div className="as-empty">미실행</div>}
        </section>

        <section className="as-card" style={{ gridColumn: "span 4" }}>
          <div className="as-card-title">FACTOR X-RAY <span className="as-note-inline">{xrayQ.data?.benchmark_label || "vs 유니버스"}</span><Xlink to="/allocation/thesis" label="03" /></div>
          {xrayQ.data?.factors?.length ? <FactorXRayBars factors={xrayQ.data.factors.slice(0, 6)} />
            : <div className="as-empty">{holdings.length ? "계산 중…" : "01 CONSTRUCT에서 자산 추가"}</div>}
        </section>

        <section className="as-card" style={{ gridColumn: "span 4" }}>
          <div className="as-card-title">ROBUSTNESS <span className="as-note-inline">최악 시나리오</span><Xlink to="/allocation/stress" label="06" /></div>
          {robust.length ? robust.map((r, i) => (
            <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 10, fontSize: 10.5 }}>
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.l}</span>
              <em style={{ fontStyle: "normal", fontSize: 9, color: "var(--t-muted)" }}>{r.m}</em>
              <b className="num" style={{ color: r.c }}>{r.v}</b>
            </div>
          )) : <div className="as-empty">{holdings.length ? "시나리오 계산 중…" : "자산 추가 후 표시"}</div>}
          <div className="as-note">기댓값 변동 → 비중 민감도 히트맵은 04 STRESS에서</div>
        </section>

        <section className="as-card" style={{ gridColumn: "span 4" }}>
          <div className="as-card-title">RESEARCH TIMELINE <span className="as-note-inline">세션 실기록</span><Xlink to="/allocation/journal" label="09" /></div>
          <ResearchTimeline events={timeline.slice(0, 6)} />
        </section>
      </div>
    </>
  );
}
