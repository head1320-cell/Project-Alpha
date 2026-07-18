"use client";
// Robustness & Sensitivity Workspace — 좌: 시나리오 선택 + 충격 변수 조절 /
// 우: 대형 Sensitivity Heatmap(기댓값 변동 → Weight 민감도) + 스트레스 상세.
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { allocationApi } from "@/lib/allocationApi";
import { useAllocation } from "@/components/allocation/AllocationProvider";
import { SensitivityHeatmap, StressChart, fmtSign } from "@/components/allocation/parts";

export default function RobustnessWorkspace() {
  const {
    holdings, views, delta, tau, scenario, pickScenario, scenarios, stressQ, canRun,
  } = useAllocation();
  const [bump, setBump] = useState(2.0);        // μ 충격 크기 (연 %p) — 커밋 시 재계산
  const [bumpCommitted, setBumpCommitted] = useState(2.0);

  const viewsKey = JSON.stringify(views);
  const sensQ = useQuery({
    queryKey: ["allocation", "sensitivity",
      JSON.stringify(holdings.map((h) => h.code)), viewsKey, bumpCommitted, delta, tau],
    queryFn: () => allocationApi.sensitivity({
      tickers: holdings.map((h) => h.code),
      views: views.filter((v) => v.assets.length > 0 && v.magnitude_pct > 0),
      delta, tau, bump_pct: bumpCommitted,
    }).catch(() => null),
    enabled: canRun,
  });

  return (
    <div className="as-ws2 as-ws-rob">
      <aside className="as-center">
        <section className="as-card">
          <div className="as-card-title">SCENARIOS</div>
          <div className="as-scenario-list">
            {scenarios.map((s) => (
              <button key={s.id} disabled={!s.available} title={s.reason || s.description}
                className={`as-scen${scenario === s.id ? " on" : ""}${!s.available ? " off" : ""}`}
                onClick={() => pickScenario(s.id)}>
                <span>{s.label}</span>
                <em>{s.mode === "historical" ? (s.available ? "역사 리플레이" : "데이터 미보유") : "가상"}</em>
              </button>
            ))}
          </div>
        </section>
        <section className="as-card">
          <div className="as-card-title">SENSITIVITY 충격 변수</div>
          <div className="as-note">기대수익 충격 <b className="num" style={{ color: "var(--t-ink)" }}>+{bump.toFixed(1)}%p</b> 기준 민감도</div>
          <details className="aas-adv">
            <summary>고급 — 충격 크기 조절</summary>
            <label className="as-param">
              <span>기대수익 충격 (μ bump) <b className="num">+{bump.toFixed(1)}%p</b></span>
              <input type="range" min={0.5} max={5} step={0.5} value={bump}
                onChange={(e) => setBump(parseFloat(e.target.value))}
                onMouseUp={() => setBumpCommitted(bump)} onTouchEnd={() => setBumpCommitted(bump)}
                onKeyUp={() => setBumpCommitted(bump)} />
              <em className="as-note-inline">릴리스 시 N회 재최적화 실행 (자산 수만큼)</em>
            </label>
          </details>
          {sensQ.data && (sensQ.data.coverage as { source?: string })?.source === "mock" && (
            <span className="as-badge" style={{ color: "#a16207", borderColor: "#a16207", alignSelf: "flex-start" }}>MOCK 데이터</span>
          )}
        </section>
      </aside>
      <main className="as-center">
        <section className={`as-card${sensQ.isLoading ? " as-loading" : ""}`}>
          <div className="as-card-title">SENSITIVITY HEATMAP <span className="as-note-inline">기댓값 변동 → 최적 비중 반응 (Δ%p)</span></div>
          {!canRun && <div className="as-empty">01 CONSTRUCT에서 자산 2개 이상 추가 →</div>}
          {canRun && sensQ.isLoading && <div className="as-empty">민감도 계산 중… (자산별 재최적화)</div>}
          {sensQ.data && !sensQ.data.error && (
            <SensitivityHeatmap names={sensQ.data.names} labels={sensQ.data.labels}
              matrix={sensQ.data.matrix} baseWeights={sensQ.data.base_weights}
              bumpPct={sensQ.data.bump_pct} />
          )}
          {sensQ.data?.error && <div className="as-err">{sensQ.data.message}</div>}
        </section>
        <section className="as-card">
          <div className="as-card-title">SCENARIO DETAIL — {stressQ.data?.label || ""}</div>
          {!holdings.length && <div className="as-empty">포트폴리오 구성 후 표시</div>}
          {holdings.length > 0 && stressQ.isLoading && <div className="as-empty">시나리오 계산 중…</div>}
          {stressQ.data && stressQ.data.mode === "hypothetical" && stressQ.data.available && (
            <div>
              <div className="as-shock-head">
                포트폴리오 추정 충격 <b className="num" style={{ color: (stressQ.data.portfolio_shock_pct ?? 0) >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>
                  {fmtSign(stressQ.data.portfolio_shock_pct ?? 0, 1)}%</b>
              </div>
              <table className="as-metrics">
                <thead><tr><th>종목</th><th>비중</th><th>충격</th><th>기여</th></tr></thead>
                <tbody>
                  {(stressQ.data.rows || []).map((r) => (
                    <tr key={r.stock_code}>
                      <td>{r.corp_name}</td>
                      <td className="num">{r.weight_pct.toFixed(1)}%</td>
                      <td className="num" style={{ color: r.shock_pct >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{fmtSign(r.shock_pct, 1)}%</td>
                      <td className="num">{fmtSign(r.contribution_pct, 2)}%p</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="as-note">{stressQ.data.note}</div>
            </div>
          )}
          {stressQ.data && stressQ.data.mode === "historical" && stressQ.data.available && (
            <StressChart result={stressQ.data} />
          )}
          {stressQ.data && !stressQ.data.available && (
            <div className="as-empty">{stressQ.data.reason || "해당 시나리오 데이터 미보유"}</div>
          )}
        </section>
      </main>
    </div>
  );
}
