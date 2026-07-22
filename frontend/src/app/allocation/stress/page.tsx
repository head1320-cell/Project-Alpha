"use client";
// 05 STRESS — 견고성 검증. 좌: 시나리오 + 강도(severity) + μ충격 + 상관-국면 컨트롤 /
// 우: Sensitivity Heatmap(기댓값→비중 민감도) + 상관-국면 스트레스(위기 상관 수렴 → Δ변동성·ΔVaR)
// + 시나리오 상세. 백엔드: /sensitivity · /stress(severity) · /stress-correlation.
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { allocationApi } from "@/lib/allocationApi";
import { useAllocation } from "@/components/allocation/AllocationProvider";
import { SensitivityHeatmap, StressChart, fmtSign } from "@/components/allocation/parts";
import { KrScenarioPack } from "@/components/allocation/KrScenarioPack";

export default function RobustnessWorkspace() {
  const {
    holdings, holdingsMap, views, delta, tau, scenario, pickScenario, scenarios,
    stressQ, canRun, severity, setSeverity,
  } = useAllocation();
  const [bump, setBump] = useState(2.0);          // μ 충격 크기 (연 %p) — 커밋 시 재계산
  const [bumpCommitted, setBumpCommitted] = useState(2.0);
  // 상관-국면 스트레스
  const [rho, setRho] = useState(0.9);
  const [rhoC, setRhoC] = useState(0.9);
  const [intensity, setIntensity] = useState(1.0);
  const [intensityC, setIntensityC] = useState(1.0);
  const [conf, setConf] = useState(0.95);

  const codesKey = JSON.stringify(holdings.map((h) => h.code));
  const viewsKey = JSON.stringify(views);
  const sensQ = useQuery({
    queryKey: ["allocation", "sensitivity", codesKey, viewsKey, bumpCommitted, delta, tau],
    queryFn: () => allocationApi.sensitivity({
      tickers: holdings.map((h) => h.code),
      views: views.filter((v) => v.assets.length > 0 && v.magnitude_pct > 0),
      delta, tau, bump_pct: bumpCommitted,
    }).catch(() => null),
    enabled: canRun,
  });
  const corrQ = useQuery({
    queryKey: ["allocation", "stress-corr", codesKey, rhoC, intensityC, conf],
    queryFn: () => allocationApi.stressCorrelation({
      tickers: holdings.map((h) => h.code), weights: holdingsMap,
      target_rho: rhoC, intensity: intensityC, confidence_level: conf,
    }).catch(() => null),
    enabled: canRun,
  });
  const cr = corrQ.data && !corrQ.data.error ? corrQ.data : null;
  const varPct = (v: number) => (v / 1e8 * 100);

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
          <label className="as-param">
            <span>시나리오 강도 (severity) <b className="num">{severity.toFixed(2)}×</b></span>
            <input type="range" min={0.25} max={3} step={0.25} value={severity}
              onChange={(e) => setSeverity(parseFloat(e.target.value))} />
            <em className="as-note-inline">가상 시나리오 충격을 배율만큼 확대/축소 (역사 리플레이 제외)</em>
          </label>
        </section>
        <section className="as-card">
          <div className="as-card-title">SENSITIVITY 충격 변수</div>
          <label className="as-param">
            <span>기대수익 충격 (μ bump) <b className="num">+{bump.toFixed(1)}%p</b></span>
            <input type="range" min={0.5} max={10} step={0.5} value={bump}
              onChange={(e) => setBump(parseFloat(e.target.value))}
              onMouseUp={() => setBumpCommitted(bump)} onTouchEnd={() => setBumpCommitted(bump)}
              onKeyUp={() => setBumpCommitted(bump)} />
            <em className="as-note-inline">릴리스 시 N회 재최적화 실행 (자산 수만큼)</em>
          </label>
          {sensQ.data && (sensQ.data.coverage as { source?: string })?.source === "mock" && (
            <span className="as-badge" style={{ color: "#a16207", borderColor: "#a16207", alignSelf: "flex-start" }}>MOCK 데이터</span>
          )}
        </section>
        <section className="as-card">
          <div className="as-card-title">상관-국면 스트레스 <span className="as-note-inline">위기 시 상관 수렴</span></div>
          <label className="as-param">
            <span>목표 상관 ρ <b className="num">{rho.toFixed(2)}</b></span>
            <input type="range" min={0} max={0.99} step={0.01} value={rho}
              onChange={(e) => setRho(parseFloat(e.target.value))}
              onMouseUp={() => setRhoC(rho)} onTouchEnd={() => setRhoC(rho)} onKeyUp={() => setRhoC(rho)} />
          </label>
          <label className="as-param">
            <span>충격 강도 <b className="num">{(intensity * 100).toFixed(0)}%</b></span>
            <input type="range" min={0} max={1} step={0.05} value={intensity}
              onChange={(e) => setIntensity(parseFloat(e.target.value))}
              onMouseUp={() => setIntensityC(intensity)} onTouchEnd={() => setIntensityC(intensity)} onKeyUp={() => setIntensityC(intensity)} />
          </label>
          <label className="as-tm-set">
            <span>VaR 신뢰수준</span>
            <select value={conf} onChange={(e) => setConf(parseFloat(e.target.value))}>
              <option value={0.9}>90%</option>
              <option value={0.95}>95%</option>
              <option value={0.99}>99%</option>
            </select>
          </label>
          <div className="as-note">위기엔 상관이 1로 수렴 → 분산효과 소멸. ρ·강도로 위기 공분산을 구성해 VaR 변화를 검증.</div>
        </section>
      </aside>
      <main className="as-center">
        <KrScenarioPack />
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

        <section className={`as-card${corrQ.isLoading ? " as-loading" : ""}`}>
          <div className="as-card-title">상관-국면 스트레스 결과 <span className="as-note-inline">base → 위기 상관</span></div>
          {!canRun && <div className="as-empty">01 CONSTRUCT에서 자산 2개 이상 추가 →</div>}
          {canRun && corrQ.isLoading && <div className="as-empty">위기 상관 재계산 중…</div>}
          {corrQ.data?.error && <div className="as-err">{corrQ.data.message}</div>}
          {cr && (
            <>
              <div className="as-tm-corr-head">
                <div><span>연 변동성</span><b className="num">{cr.base.port_vol_pct}% → {cr.stressed.port_vol_pct}%</b>
                  <em className="num" style={{ color: (cr.delta_vol_pct ?? 0) >= 0 ? "var(--color-bear)" : "var(--color-bull)" }}>{cr.delta_vol_pct != null ? `${fmtSign(cr.delta_vol_pct, 1)}%` : ""}</em></div>
                <div><span>VaR({Math.round(cr.confidence_level * 100)}%)</span><b className="num">{varPct(cr.base.var_amount).toFixed(1)}% → {varPct(cr.stressed.var_amount).toFixed(1)}%</b>
                  <em className="num" style={{ color: (cr.delta_var_pct ?? 0) >= 0 ? "var(--color-bear)" : "var(--color-bull)" }}>{cr.delta_var_pct != null ? `${fmtSign(cr.delta_var_pct, 1)}%` : ""}</em></div>
                <div><span>평균 상관</span><b className="num">{cr.corr_shift.from_avg_rho} → {cr.corr_shift.to_avg_rho}</b></div>
              </div>
              <table className="as-metrics">
                <thead><tr><th>자산</th><th>기여VaR base</th><th>기여VaR 위기</th><th>Δ</th></tr></thead>
                <tbody>
                  {cr.names.map((n) => {
                    const b = varPct(cr.base.component_var[n] ?? 0);
                    const s = varPct(cr.stressed.component_var[n] ?? 0);
                    return (
                      <tr key={n}>
                        <td>{cr.labels[n] || n}</td>
                        <td className="num">{b.toFixed(2)}%</td>
                        <td className="num">{s.toFixed(2)}%</td>
                        <td className="num" style={{ color: s - b >= 0 ? "var(--color-bear)" : "var(--color-bull)" }}>{fmtSign(s - b, 2)}%p</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {(cr.coverage as { source?: string })?.source === "mock" && (
                <span className="as-badge" style={{ color: "#a16207", borderColor: "#a16207", alignSelf: "flex-start" }}>MOCK 데이터</span>
              )}
            </>
          )}
        </section>

        <section className="as-card">
          <div className="as-card-title">SCENARIO DETAIL — {stressQ.data?.label || ""}{severity !== 1 && stressQ.data?.mode === "hypothetical" ? ` (${severity}×)` : ""}</div>
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
