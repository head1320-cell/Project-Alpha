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
import { EvidenceBadge } from "@/shared/ui/evidence";

// 보이는 글자는 `05 ↗` 뿐이다 — 스크린리더에는 "05 버튼"으로만 읽혔다. 목적지는
// title= 안에만 있었고, 호버는 키보드·터치에 존재하지 않는다(P3 가 ContextStrip 에서
// 고친 것과 같은 결함). aria-label 로 접근 가능한 이름을 준다.
function Xlink({ to, label }: { to: string; label: string }) {
  const router = useRouter();
  return (
    <button className="aas-xlink" aria-label={`${label} 스테이지로 이동`}
      onClick={() => router.push(to)}>{label} ↗</button>
  );
}

/** 견고성 한 줄 — 값이 없을 수 있고, 없으면 **사유**가 있어야 한다. */
type RobustRow =
  | { l: string; m: string; v: number; bear: boolean }
  | { l: string; m: string; v: null; why: string };

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

  // ★미측정을 초록 `+0.0%` 로 지어내지 않는다 (A4-V1)★
  // 예전 코드는 `portfolio_shock_pct ?? 0` 을 **값에도 색에도** 썼다. 충격이 산출되지
  // 않은 경우 `0 >= 0` 이 참이라 화면에는 `+0.0%` 가 **초록**으로 찍혔다 — 즉
  // "재지 못했다"가 "포트폴리오가 무사하다"로 읽혔다. 대시보드 첫 화면에서, 가장
  // 안심시키는 방향으로 틀린 값이다.
  //   부수 발견 ①: `fmtSign()`(parts.tsx:39)은 이미 null 을 "—" 로 처리한다.
  //                `?? 0` 이 그 정직함을 정확히 무력화하고 있었다.
  //   부수 발견 ②: historical 갈래의 `max_dd_pct?.toFixed(1)` 은 값이 없으면
  //                문자열 `"undefined%"` 를 렌더했다.
  const sd = stressQ.data;
  const robust: RobustRow[] = !sd
    ? []
    : !sd.available
      ? [{ l: sd.label, m: "견고성", v: null, why: sd.reason || "이 시나리오는 현재 산출되지 않습니다" }]
      : sd.mode === "hypothetical"
        ? [sd.portfolio_shock_pct != null && Number.isFinite(sd.portfolio_shock_pct)
            ? { l: sd.label, m: "추정 충격", v: sd.portfolio_shock_pct, bear: sd.portfolio_shock_pct < 0 }
            : { l: sd.label, m: "추정 충격", v: null, why: sd.reason || "충격이 산출되지 않았습니다" }]
        : [sd.max_dd_pct != null && Number.isFinite(sd.max_dd_pct)
            ? { l: sd.label, m: "최대낙폭", v: sd.max_dd_pct, bear: true }
            : { l: sd.label, m: "최대낙폭", v: null, why: sd.reason || "낙폭이 산출되지 않았습니다" }];

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
                <span className={`num aas-ov-d${d >= 0 ? " bull" : " bear"}`}>{fmtSign(d, 1)}</span>
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
          {/* 인라인 style 로 9px·10.5px 를 박아 두면 어떤 CSS 규칙도 하한을 적용할 수
              없다. 클래스로 내려 §52 가 관리한다 (A4-V2). */}
          {robust.length ? robust.map((r, i) => (
            <div key={i} className="aas-ov-rob">
              <span className="aas-ov-rob-l">{r.l}</span>
              <em className="aas-ov-rob-m">{r.m}</em>
              {r.v == null
                ? <EvidenceBadge kind="unavailable" reason={r.why}>산출 불가</EvidenceBadge>
                : <b className={`num aas-ov-rob-v${r.bear ? " bear" : " bull"}`}>{fmtSign(r.v, 1)}%</b>}
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
