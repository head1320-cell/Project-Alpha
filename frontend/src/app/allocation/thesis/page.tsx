"use client";
// Thesis Workspace — 거시 테제 빌딩 + 자산 구성 + Factor Exposure Preview.
// Factor-first Research 1단계: 최적화 전에 포트폴리오의 팩터 노출을 먼저 본다.
import React from "react";
import { useAllocation } from "@/components/allocation/AllocationProvider";
import { PortfolioBuilder } from "@/components/allocation/PortfolioBuilder";
import { ViewBuilder, overallConfidence } from "@/components/allocation/ViewBuilder";
import { ConfidenceGauge, FactorXRayBars } from "@/components/allocation/parts";

export default function ThesisWorkspace() {
  const {
    holdings, setHoldingsReset, views, setViewsLogged, runAnalyze, xrayQ,
    loadStudy, studiesVersion, result, canRun, pending,
  } = useAllocation();
  const conf = overallConfidence(views);

  return (
    <div className="as-ws2">
      <aside>
        <PortfolioBuilder holdings={holdings} studiesVersion={studiesVersion}
          onChange={setHoldingsReset} onLoadStudy={loadStudy} />
      </aside>
      <main className="as-center">
        <section className="as-card">
          <div className="as-card-title">INVESTMENT THESIS <span className="as-note-inline">Black-Litterman 뷰 — [테제] ➔ [자산] ➔ [방향·크기] ➔ [신뢰도]</span></div>
          <ViewBuilder views={views} holdings={holdings}
            onChange={setViewsLogged} onCommit={() => runAnalyze()} />
          {result && !result.views_applied && views.length > 0 && (
            <div className="as-note">유효한 뷰 없음(대상 자산·크기 확인) — 시장균형으로 계산됨</div>
          )}
        </section>
        <div className="as-mid2">
          <section className="as-card">
            <div className="as-card-title">VIEW CONFIDENCE</div>
            <ConfidenceGauge value={conf} height={120} />
            <div className="as-note">신뢰도는 BL의 Ω(뷰 불확실성)로 매핑 — 100%에 가까울수록 뷰가 균형수익을 지배.</div>
          </section>
          <section className="as-card">
            <div className="as-card-title">FACTOR EXPOSURE PREVIEW <span className="as-note-inline">{xrayQ.data?.benchmark_label || "vs 유니버스"}</span></div>
            {xrayQ.data?.factors?.length ? <FactorXRayBars factors={xrayQ.data.factors} />
              : <div className="as-empty">{holdings.length ? (xrayQ.isLoading ? "계산 중…" : "팩터 데이터 부족") : "자산 추가 시 표시"}</div>}
            <div className="as-note">Factor-first: 최적화 전 현재 구성의 팩터 노출 확인. 테제→팩터 자동 매핑은 R2.</div>
          </section>
        </div>
        <button className="as-run" disabled={!canRun || pending} onClick={() => runAnalyze()}>
          {pending ? "최적화 중…" : "Re-optimize → Optimizer에서 결과 보기"}
        </button>
      </main>
    </div>
  );
}
