"use client";
// Optimization Workspace — 엔진 제어(BL/모델·λ·τ) + 대형 Efficient Frontier +
// Allocation Flow + 요약 지표. λ는 클라이언트 사이드 프론티어 점 선택(재계산 0).
import React, { useMemo } from "react";
import { COV_ONLY, MODELS, useAllocation } from "@/components/allocation/AllocationProvider";
import {
  AllocationSankey, FrontierChart, McHistogram, MetricsTable, lambdaOptimalIdx,
} from "@/components/allocation/parts";

export default function OptimizerWorkspace() {
  const {
    result, model, setModel, delta, setDelta, tau, setTau,
    runAnalyze, canRun, pending, analyzeError, views,
  } = useAllocation();

  const lamIdx = result ? lambdaOptimalIdx(result.frontier.curve, delta) : -1;
  const lamWeights = useMemo(() => {
    if (!result || lamIdx < 0) return null;
    const pt = result.frontier.curve[lamIdx];
    if (!pt) return null;
    const w: Record<string, number> = {};
    result.names.forEach((n) => { const v = pt[`w_${n}`]; if (typeof v === "number" && v > 0.05) w[n] = v; });
    return w;
  }, [result, lamIdx]);

  return (
    <div className="as-ws2 as-ws-opt">
      <aside className="as-center">
        <section className="as-card">
          <div className="as-card-title">OPTIMIZATION ENGINE</div>
          <div className="as-seg as-models">
            {MODELS.map((m) => (
              <button key={m.id} className={model === m.id ? "on" : ""}
                onClick={() => { setModel(m.id); runAnalyze({ model: m.id }); }}>{m.label}</button>
            ))}
          </div>
          <label className="as-param">
            <span>Risk Aversion (λ) <b className="num">{delta.toFixed(1)}</b></span>
            <input type="range" min={0.5} max={8} step={0.1} value={delta}
              onChange={(e) => setDelta(parseFloat(e.target.value))} />
            <em className="as-note-inline">드래그 = 프론티어 위 선택점 이동 (재계산 없음)</em>
          </label>
          <label className="as-param">
            <span>Uncertainty (τ) <b className="num">{tau.toFixed(3)}</b></span>
            <input type="range" min={0.01} max={0.2} step={0.005} value={tau}
              onChange={(e) => setTau(parseFloat(e.target.value))}
              onMouseUp={() => runAnalyze()} onTouchEnd={() => runAnalyze()} onKeyUp={() => runAnalyze()} />
          </label>
          <button className="as-run" disabled={!canRun || pending} onClick={() => runAnalyze()}>
            {pending ? "최적화 중…" : "Re-optimize"}
          </button>
          {!canRun && <div className="as-note">Thesis 워크스페이스에서 자산 2개 이상 추가</div>}
          {analyzeError && <div className="as-err">{analyzeError}</div>}
          {result && COV_ONLY.includes(result.model) && views.length > 0 && (
            <div className="as-note">뷰는 Black-Litterman 모델에서만 기대수익에 반영됩니다</div>
          )}
          {result && result.cap_missing.length > 0 && (
            <div className="as-note">시총 미보유 {result.cap_missing.length}자산은 중앙값 대체(캡가중 prior)</div>
          )}
        </section>
        <section className="as-card">
          <div className="as-card-title">SUMMARY METRICS</div>
          {result ? <MetricsTable summary={result.summary} /> : <div className="as-empty">Re-optimize 실행 시 표시</div>}
        </section>
        <section className="as-card">
          <div className="as-card-title">RETURN DISTRIBUTION <span className="as-note-inline">MC 1년</span></div>
          {result ? <McHistogram mc={result.mc} /> : <div className="as-empty">Re-optimize 실행 시 표시</div>}
        </section>
      </aside>
      <main className="as-center">
        <section className={`as-card${pending ? " as-loading" : ""}`}>
          <div className="as-card-title">EFFICIENT FRONTIER
            {result?.views_applied && <span className="as-badge">BL 뷰 적용</span>}
          </div>
          {result ? <FrontierChart result={result} lam={delta} height={340} />
            : <div className="as-empty" style={{ height: 340, display: "flex", alignItems: "center", justifyContent: "center" }}>Re-optimize 실행 시 표시</div>}
          {lamWeights && (
            <div className="as-lam-w">
              <span className="as-note-inline">λ 선택점 비중:</span>
              {Object.entries(lamWeights).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([c, w]) => (
                <span key={c} className="as-chip sm">{result?.labels[c] || c} <b className="num">{w.toFixed(1)}%</b></span>
              ))}
            </div>
          )}
        </section>
        <section className={`as-card${pending ? " as-loading" : ""}`}>
          <div className="as-card-title">ALLOCATION FLOW <span className="as-note-inline">시장 → 뷰 반영 → 최적화</span></div>
          {result ? <AllocationSankey result={result} /> : <div className="as-empty">가중치 흐름</div>}
        </section>
      </main>
    </div>
  );
}
