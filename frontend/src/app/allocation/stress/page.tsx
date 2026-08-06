"use client";
// 05 STRESS — 견고성 검증. 좌: 통합 시나리오 창 + μ충격 + 상관-국면 컨트롤 /
// 우: Sensitivity Heatmap(기댓값→비중 민감도) + 상관-국면 스트레스(위기 상관 수렴 → Δ변동성·ΔVaR)
// + 선택 시나리오 상세. 백엔드: /sensitivity · /stress(severity) · /stress-correlation ·
// /stress-scenarios(통합 카탈로그).
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { allocationApi, MODEL_TYPE_SHORT, type StressEngine } from "@/entities/allocation/api";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { SensitivityHeatmap, StressChart, fmtSign } from "@/widgets/allocation/parts";
import { KrScenarioPack } from "@/widgets/allocation/KrScenarioPack";
import { ScenarioThreeWay } from "@/widgets/allocation/ScenarioThreeWay";
import { StressScenarioModal } from "@/widgets/allocation/StressScenarioModal";

export default function RobustnessWorkspace() {
  const {
    holdings, holdingsMap, views, delta, tau, scenario, pickScenario, scenarios,
    stressQ, canRun, severity, setSeverity, setScenarioPackId,
  } = useAllocation();
  const [pickerOpen, setPickerOpen] = useState(false);
  // ★어느 창에 결과를 그릴지는 **실행 엔진**이 정한다★ (Phase 9)
  // 예전에는 패밀리로 갈랐는데, 패밀리는 이제 스펙 §5 의 분류(12종)이고 국내팩은 그 중
  // 여러 패밀리에 흩어져 있다. "어느 엔진이 돌리는가" 가 원래 묻고 싶던 질문이다.
  const [engine, setEngine] = useState<StressEngine>("m8");
  const [krScenario, setKrScenario] = useState("semi_selloff");
  const activeId = engine === "kr_pack" ? krScenario : scenario;
  // 라벨·강도적용 여부는 통합 카탈로그에서 (모달과 동일 쿼리 키 → 캐시 공유, 추가 요청 0)
  const scenCatQ = useQuery({
    queryKey: ["allocation", "stress-scenarios"],
    queryFn: () => allocationApi.stressScenarios(),
    staleTime: Infinity,
  });
  const activeMeta = (scenCatQ.data?.groups ?? [])
    .flatMap((g) => g.items).find((i) => i.id === activeId);
  const activeLabel = activeMeta?.label
    ?? scenarios.find((s) => s.id === scenario)?.label ?? activeId;
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
          <div className="as-card-title">SCENARIO <span className="as-note-inline">가상 · 역사 리플레이 · 국내팩 통합</span></div>
          <div className="tfc-list">
            <div className="tfc-chip">
              <div className="tfc-chip-main">
                <span className="tfc-chip-t">{activeLabel}</span>
                <span className="tfc-chip-tk">{activeMeta?.family_label ?? ""}</span>
                {/* ★결과 옆에도 model_type 이 있어야 한다★ 선택 창에만 있으면 "이건 가정입니다"
                    가 정작 숫자를 보는 자리에서 사라진다(스펙 §5). */}
                {activeMeta && (
                  <span className={`as-model-type mt-${activeMeta.model_type}`}>
                    {MODEL_TYPE_SHORT[activeMeta.model_type]}
                  </span>
                )}
                <span className="tfc-chip-cond num">
                  {activeMeta?.severity_applies === false ? "강도 미적용" : `${severity.toFixed(2)}×`}
                </span>
              </div>
            </div>
          </div>
          <button className="as-fb-apply" onClick={() => setPickerOpen(true)}>+ 시나리오 창에서 선택</button>
          <div className="as-note">
            스펙 §5 의 12 패밀리로 분류된 시나리오를 한 창에서 검색·비교합니다. 분류와 별개로
            각 항목은 <b>역사 리플레이인지 가정 충격인지</b>를 스스로 밝힙니다. 미가용 시나리오는
            창에 사유가 함께 표시됩니다.
          </div>
          <StressScenarioModal open={pickerOpen} onClose={() => setPickerOpen(false)}
            selectedId={activeId} severity={severity} onSeverity={setSeverity}
            onPick={(s) => {
              setEngine(s.engine);
              setScenarioPackId(s.pack_id);   // 컨텍스트 스트립이 팩 신원을 그린다 (§4 ⑦)
              if (s.engine === "kr_pack") setKrScenario(s.id); else pickScenario(s.id);
            }} />
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
            <span className="as-badge as-badge-mock">MOCK 데이터</span>
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
        {/* 선택한 엔진의 결과를 위로 — 두 상세 카드는 항상 렌더(정보 손실 없음), 순서만 포커스 */}
        {engine === "kr_pack" && <KrScenarioPack scenario={krScenario} onPick={setKrScenario} />}
        <ScenarioThreeWay packId={activeId} holdings={holdingsMap} severity={severity} />
        <section className={`as-card${sensQ.isLoading ? " as-loading" : ""}`} aria-busy={sensQ.isLoading}>
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

        <section className={`as-card${corrQ.isLoading ? " as-loading" : ""}`} aria-busy={corrQ.isLoading}>
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
                <span className="as-badge as-badge-mock">MOCK 데이터</span>
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
        {engine !== "kr_pack" && <KrScenarioPack scenario={krScenario} onPick={(id) => { setKrScenario(id); setEngine("kr_pack"); }} />}
      </main>
    </div>
  );
}
