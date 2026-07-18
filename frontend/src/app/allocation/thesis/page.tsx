"use client";
// 02 THESIS — 거시 테제 → Black-Litterman 뷰 + 신뢰도 + 팩터 노출 프리뷰.
// 자산 구성은 01 CONSTRUCT로 분리됨. 최적화는 상단 헤더의 Re-optimize.
import React from "react";
import { useAllocation } from "@/components/allocation/AllocationProvider";
import { ViewBuilder, overallConfidence } from "@/components/allocation/ViewBuilder";
import { ConfidenceGauge, FactorXRayBars } from "@/components/allocation/parts";

export default function ThesisStage() {
  const { holdings, views, setViewsLogged, runAnalyze, xrayQ, result } = useAllocation();
  const conf = overallConfidence(views);

  return (
    <div className="as-ws2 as-ws-exp">
      <main className="as-center">
        <section className="as-card">
          <div className="as-card-title">INVESTMENT THESIS <span className="as-note-inline">Black-Litterman 뷰 — [테제] ➔ [자산] ➔ [방향·크기] ➔ [신뢰도]</span></div>
          {holdings.length === 0 && (
            <div className="as-empty">먼저 01 CONSTRUCT에서 자산을 구성하세요 — 뷰는 보유 자산에 대해 설정합니다.</div>
          )}
          <ViewBuilder views={views} holdings={holdings}
            onChange={setViewsLogged} onCommit={() => runAnalyze()} />
          {result && !result.views_applied && views.length > 0 && (
            <div className="as-note">유효한 뷰 없음(대상 자산·크기 확인) — 시장균형으로 계산됨</div>
          )}
        </section>
      </main>
      <aside className="as-center">
        <section className="as-card">
          <div className="as-card-title">VIEW CONFIDENCE</div>
          <ConfidenceGauge value={conf} height={120} />
          <div className="as-note">신뢰도는 BL의 Ω(뷰 불확실성)로 매핑 — 100%에 가까울수록 뷰가 균형수익을 지배.</div>
        </section>
        <section className="as-card">
          <div className="as-card-title">FACTOR EXPOSURE PREVIEW <span className="as-note-inline">{xrayQ.data?.benchmark_label || "vs 유니버스"}</span></div>
          {xrayQ.data?.factors?.length ? <FactorXRayBars factors={xrayQ.data.factors} />
            : <div className="as-empty">{holdings.length ? (xrayQ.isLoading ? "계산 중…" : "팩터 데이터 부족") : "01 CONSTRUCT에서 자산 추가 시 표시"}</div>}
          <div className="as-note">Factor-first: 최적화 전 현재 구성의 팩터 노출 확인.</div>
        </section>
      </aside>
    </div>
  );
}
