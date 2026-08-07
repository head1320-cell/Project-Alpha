"use client";
// 02 THESIS — 거시 테제 → Black-Litterman 뷰 + 신뢰도 + 팩터 노출 프리뷰.
// 자산 구성은 01 CONSTRUCT로 분리됨. 최적화는 상단 헤더의 Re-optimize.
import React, { useMemo } from "react";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { ViewBuilder, overallConfidence } from "@/widgets/allocation/ViewBuilder";
import { ConfidenceGauge, FactorXRayBars, ViewEffect, type ViewEffectRow } from "@/widgets/allocation/parts";

export default function ThesisStage() {
  const { holdings, views, setViewsLogged, runAnalyze, xrayQ, result } = useAllocation();
  const conf = overallConfidence(views);

  // ★이 스테이지에는 근거가 하나도 없었다 (A5)★ 1fr 칼럼에 컨트롤 한 줄만 있고 나머지는
  // 빈 공간이었다. 뷰를 세우는 화면이 정작 **뷰가 무엇을 바꿨는지**를 보여 주지 않았다.
  //
  // 새 엔드포인트는 만들지 않는다 — `result.flow.market`(캡가중 사전)과
  // `flow.view_applied`(BL 사후)가 이미 있고, 05 의 산키가 같은 데이터를 쓴다.
  // 여기서는 그걸 자산별 표로 읽는다. 실행 전에는 `null` → 표가 '미계산'이라고 쓴다
  // (A3 의 WeightComparison 과 같은 규약 — 0 으로 지어내지 않는다).
  const effect: ViewEffectRow[] = useMemo(() => holdings.map((h) => {
    const mkt = result ? result.flow.market[h.code] ?? null : null;
    const applied = result ? result.flow.view_applied[h.code] ?? null : null;
    return {
      code: h.code,
      name: result?.labels[h.code] || h.name,
      market: mkt,
      applied,
      delta: mkt != null && applied != null ? applied - mkt : null,
    };
  }), [holdings, result]);

  // 뷰가 실제로 반영됐는가 — 셋 중 하나이지 둘이 아니다.
  const effectState = !result ? "미계산"
    : !result.views_applied ? "미반영"
      : "반영됨";

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

        <section className="as-card">
          <div className="as-card-title">
            VIEW EFFECT
            <span className="as-note-inline">시장(캡가중) → 뷰 반영(BL) · Δ = 내 테제가 움직인 폭</span>
            <span className={`as-badge as-thesis-state s-${effectState === "반영됨" ? "on" : "off"}`}>
              {effectState}
            </span>
          </div>
          {effect.length
            ? <ViewEffect rows={effect} />
            : <div className="as-empty">01 CONSTRUCT에서 자산을 추가하면 표시됩니다.</div>}
          {!result && effect.length > 0 && (
            <div className="as-note">
              상단 Re-optimize 를 실행하면 채워집니다 — 실행 전에는 시장 사전분포도 뷰 사후분포도
              존재하지 않습니다.
            </div>
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
