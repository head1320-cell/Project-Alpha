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
import { EvidenceBadge } from "@/shared/ui/evidence";
import { StressBasisBand, useTargetBasis } from "@/widgets/allocation/StressBasisBand";

export default function RobustnessWorkspace() {
  const {
    holdings, holdingsMap, views, delta, tau, scenario, pickScenario, scenarios,
    stressQ, canRun, severity, setSeverity, setScenarioPackId, result, timingOverlay,
  } = useAllocation();

  // ★목표 기준 — 없으면 요청하지 않고, 없다는 사실을 화면이 말한다 (R0-B)★
  const optimized = result?.weights.optimized ?? null;
  const tvQ = useTargetBasis(optimized, timingOverlay);
  const tv = tvQ.data ?? null;
  const tvReason = !optimized
    ? "05 OPTIMIZE 에서 최적 비중을 산출해야 목표가 생깁니다."
    : tvQ.isLoading ? "목표를 컴파일하는 중입니다." : "목표 컴파일에 실패했습니다.";
  const nameOfCode = (c: string) =>
    result?.labels[c] || holdings.find((h) => h.code === c)?.name || c;
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
  // ★`?? 0` 을 걷어냈다 (A6-Z)★ 예전 시그니처는 `(v: number)` 였고 호출부가
  // `component_var[n] ?? 0` 으로 결측을 0 으로 만들어 넘겼다. 그러면 "이 자산의 기여
  // VaR 를 계산하지 못했다" 와 "기여 VaR 가 정말 0 이다" 가 같은 `0.00%` 로 찍힌다.
  // 이제 결측은 null 로 통과하고, 표가 미계산이라고 쓴다.
  const varPct = (v: number | null | undefined): number | null =>
    v == null || !Number.isFinite(v) ? null : (v / 1e8 * 100);
  const na = <span className="aas-cmp-na">미계산</span>;

  return (
    <div className="as-ws2 as-ws-rob">
      <aside className="as-center">
        {/* ★무엇을 스트레스하는지부터 밝힌다 (R0-B)★ 이 화면의 모든 숫자는 아래에서
            고른 기준을 따른다 — 기준을 말하지 않으면 결과는 해석할 수 없다. */}
        <StressBasisBand current={holdingsMap} tv={tv} nameOf={nameOfCode} reason={tvReason} />
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
          {/* ★설명은 접고 경고는 접지 않는다 (A5 에서 받은 규칙)★
              이 문단은 시나리오 창이 무엇인지 한 번 읽으면 되는 개념 설명이다. 반면 위
              칩의 model_type 배지(가정/리플레이)·강도 적용 여부와 아래 카드들의 MOCK
              배지·미가용 사유·산출 불가는 **접지 않는다** — 그것들은 지금 보고 있는
              숫자의 조건이지 교육이 아니다. */}
          <details className="as-adv as-rob-learn">
            <summary className="as-adv-s">시나리오 창은 무엇을 모아 두었나
              <span className="as-note-inline">12 패밀리 · 역사 vs 가정</span></summary>
            <div className="as-adv-b as-note">
              스펙 §5 의 12 패밀리로 분류된 시나리오를 한 창에서 검색·비교합니다. 분류와 별개로
              각 항목은 <b>역사 리플레이인지 가정 충격인지</b>를 스스로 밝힙니다. 미가용 시나리오는
              창에 사유가 함께 표시됩니다.
            </div>
          </details>
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
          <details className="as-adv as-rob-learn">
            <summary className="as-adv-s">상관 수렴이란 <span className="as-note-inline">왜 ρ 를 올리나</span></summary>
            <div className="as-adv-b as-note">위기엔 상관이 1로 수렴 → 분산효과 소멸. ρ·강도로 위기 공분산을 구성해 VaR 변화를 검증.</div>
          </details>
        </section>
      </aside>
      <main className="as-center">
        {/* 선택한 엔진의 결과를 위로 — 두 상세 카드는 항상 렌더(정보 손실 없음), 순서만 포커스 */}
        {engine === "kr_pack" && <KrScenarioPack scenario={krScenario} onPick={setKrScenario} />}
        <>
                {/* 3다리 패널에 기준 축을 하나 더 얹으면 읽을 수 없다 — 확장 대신
                    **어느 기준인지 명시**한다(R0-B 에서 의도적으로 그은 한계). */}
                <div className="as-note as-3w-basis">이 비교는 <b>현재 보유</b> 기준입니다.</div>
                <ScenarioThreeWay packId={activeId} holdings={holdingsMap} severity={severity} />
              </>
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
                {/* Δ 가 null 이면 예전에는 빈 문자열을 그리면서 **색은 `?? 0` 으로 bear**
                    를 입혔다. 보이는 숫자가 없어 눈에 띄진 않았지만, 없는 값에 방향을
                    칠하는 것은 같은 실수의 잠복형이다. 색도 값도 조건을 따라간다. */}
                <div><span>연 변동성</span><b className="num">{cr.base.port_vol_pct}% → {cr.stressed.port_vol_pct}%</b>
                  <em className="num" style={cr.delta_vol_pct == null ? undefined : { color: cr.delta_vol_pct >= 0 ? "var(--color-bear)" : "var(--color-bull)" }}>{cr.delta_vol_pct != null ? `${fmtSign(cr.delta_vol_pct, 1)}%` : na}</em></div>
                <div><span>VaR({Math.round(cr.confidence_level * 100)}%)</span><b className="num">{varPct(cr.base.var_amount)?.toFixed(1) ?? "—"}% → {varPct(cr.stressed.var_amount)?.toFixed(1) ?? "—"}%</b>
                  <em className="num" style={cr.delta_var_pct == null ? undefined : { color: cr.delta_var_pct >= 0 ? "var(--color-bear)" : "var(--color-bull)" }}>{cr.delta_var_pct != null ? `${fmtSign(cr.delta_var_pct, 1)}%` : na}</em></div>
                <div><span>평균 상관</span><b className="num">{cr.corr_shift.from_avg_rho} → {cr.corr_shift.to_avg_rho}</b></div>
              </div>
              <table className="as-metrics">
                <thead><tr><th>자산</th><th>기여VaR base</th><th>기여VaR 위기</th><th>Δ</th></tr></thead>
                <tbody>
                  {cr.names.map((n) => {
                    const b = varPct(cr.base.component_var[n]);
                    const s = varPct(cr.stressed.component_var[n]);
                    // Δ 는 양쪽이 다 있을 때만 존재한다. 한쪽이 없으면 차이도 없다 —
                    // 0 으로 채우면 "위기에도 기여가 안 변했다" 는 결론이 지어진다.
                    const d = b != null && s != null ? s - b : null;
                    return (
                      <tr key={n}>
                        <td>{cr.labels[n] || n}</td>
                        <td className="num">{b != null ? `${b.toFixed(2)}%` : na}</td>
                        <td className="num">{s != null ? `${s.toFixed(2)}%` : na}</td>
                        <td className="num" style={d == null ? undefined : { color: d >= 0 ? "var(--color-bear)" : "var(--color-bull)" }}>
                          {d != null ? `${fmtSign(d, 2)}%p` : na}</td>
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
              {/* ★초록 +0.0% 는 여기서도 살아 있었다 (A6-Z)★
                  A4-V1 이 00 OVERVIEW 에서 고친 것과 **같은 결함**이다: 시나리오가
                  `available: true` 인데 `portfolio_shock_pct` 가 null 이면 `?? 0` 이
                  0 을 만들고, 그 0 이 `>= 0` 이라 bull 색을 입어 **초록 `+0.0%`** 로
                  찍혔다. 스트레스 화면에서 초록 0% 는 "이 시나리오는 내 포트폴리오를
                  건드리지 않는다" 로 읽힌다 — 실제로는 산출을 못 한 것이다.
                  눈으로는 잡히지 않는다. 건강해 보이기 때문이다. */}
              <div className="as-shock-head">
                포트폴리오 추정 충격{" "}
                {stressQ.data.portfolio_shock_pct != null && Number.isFinite(stressQ.data.portfolio_shock_pct)
                  ? <b className="num" style={{ color: stressQ.data.portfolio_shock_pct >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>
                      {fmtSign(stressQ.data.portfolio_shock_pct, 1)}%</b>
                  : <EvidenceBadge kind="unavailable"
                      reason={stressQ.data.reason || "이 시나리오의 포트폴리오 충격이 산출되지 않았습니다"}>
                      산출 불가
                    </EvidenceBadge>}
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
