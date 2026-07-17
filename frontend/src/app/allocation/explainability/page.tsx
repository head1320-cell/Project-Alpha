"use client";
// Explainability Workspace — "왜 이 비중인가" 전 자산 Attribution 분해 +
// 리스크 기여 + 상관 구조. R1 미니트리의 전개판(전 자산 테이블).
import React from "react";
import { useAllocation } from "@/components/allocation/AllocationProvider";
import { CorrelationMini, RiskContribDonut, fmtSign } from "@/components/allocation/parts";

export default function ExplainabilityWorkspace() {
  const { result } = useAllocation();

  if (!result) {
    return (
      <section className="as-card">
        <div className="as-card-title">EXPLAINABILITY</div>
        <div className="as-empty">Optimizer에서 Re-optimize 실행 후 표시됩니다 — Market Prior → User View(BL) → Optimizer 제약의 단계별 비중 분해.</div>
      </section>
    );
  }

  const rows = Object.entries(result.weights.optimized).sort((a, b) => b[1] - a[1]);

  return (
    <div className="as-ws2 as-ws-exp">
      <main className="as-center">
        <section className="as-card">
          <div className="as-card-title">ATTRIBUTION — 단계별 비중 분해 <span className="as-note-inline">① Market Prior → ② User View(BL) → ③ Optimizer·제약</span></div>
          <table className="as-metrics">
            <thead>
              <tr>
                <th>자산</th>
                <th>① Market Prior</th>
                <th>② User View(BL)</th>
                <th>Δ 뷰</th>
                <th>③ Optimized</th>
                <th>Δ 제약</th>
                <th>리스크 기여</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([c, w]) => {
                const mkt = result.flow.market[c] ?? 0;
                const vw = result.flow.view_applied[c] ?? 0;
                const rc = result.risk_contributions[c];
                return (
                  <tr key={c}>
                    <td>{result.labels[c] || c}</td>
                    <td className="num">{mkt.toFixed(1)}%</td>
                    <td className="num">{vw.toFixed(1)}%</td>
                    <td className="num" style={{ color: vw - mkt >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{fmtSign(vw - mkt, 1)}%p</td>
                    <td className="num"><b>{w.toFixed(1)}%</b></td>
                    <td className="num" style={{ color: w - vw >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{fmtSign(w - vw, 1)}%p</td>
                    <td className="num">{rc != null ? `${rc.toFixed(1)}%` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="as-note">
            {result.views_applied
              ? "② = BL posterior max-sharpe (뷰·신뢰도 반영). Δ 뷰 = 뷰가 만든 이동, Δ 제약 = 최종 모델·long-only 정규화가 만든 이동."
              : "뷰 미적용 — ①=②(시장균형). Regime·Factor 단계 분해는 R2(레짐 연동 prior) 로드맵."}
          </div>
        </section>
      </main>
      <aside className="as-center">
        <section className="as-card">
          <div className="as-card-title">RISK CONTRIBUTION</div>
          <RiskContribDonut contributions={result.risk_contributions} labels={result.labels} />
          <div className="as-note">한계 리스크 기여(marginal × weight) — 비중이 아니라 변동성 기여 기준.</div>
        </section>
        <section className="as-card">
          <div className="as-card-title">CORRELATION STRUCTURE</div>
          <CorrelationMini correlation={result.correlation} names={result.names} labels={result.labels} />
          <div className="as-note">높은 상관 쌍은 분산 효과가 작아 동반 축소/확대되기 쉬움 — Sensitivity Heatmap의 비대각 반응과 함께 볼 것.</div>
        </section>
      </aside>
    </div>
  );
}
