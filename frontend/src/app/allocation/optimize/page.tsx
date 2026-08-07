"use client";
// Optimization Workspace — 엔진 제어(BL/모델·λ·τ) + P3 제약 조건(박스·그룹·회전율·β·현금)
// + 대형 Efficient Frontier + Allocation Flow + 요약 지표. 제약 결과는 지시서 3분법
// (충족/근사+위반목록/infeasible+사유)으로 정직 표시.
import React, { useMemo, useState } from "react";
import { COV_ONLY, MODELS, useAllocation } from "@/widgets/allocation/AllocationProvider";
import {
  AllocationSankey, FrontierChart, McHistogram, MetricsTable, lambdaOptimalIdx,
} from "@/widgets/allocation/parts";
import { NeutralizePanel } from "@/widgets/allocation/NeutralizePanel";
import { StageBusy } from "@/widgets/allocation/StageBusy";
import { TimingOverlayPanel } from "@/widgets/allocation/TimingOverlayPanel";

function num(v: string): number | null {
  const f = parseFloat(v);
  return Number.isFinite(f) ? f : null;
}

function ConstraintsPanel() {
  const { constraints, setConstraints, runAnalyze, result } = useAllocation();
  const c = constraints ?? {};
  const [groupText, setGroupText] = useState(
    Object.entries(c.group_caps_pct ?? {}).map(([g, v]) => `${g}:${v}`).join(", "));
  const set = (patch: Partial<typeof c>) => setConstraints({ ...c, ...patch });
  const rep = result?.constraints_report;

  const parseGroups = () => {
    const caps: Record<string, number> = {};
    groupText.split(",").map((s) => s.trim()).filter(Boolean).forEach((pair) => {
      const [g, v] = pair.split(":").map((x) => x.trim());
      const f = parseFloat(v);
      if (g && Number.isFinite(f)) caps[g] = f;
    });
    set({ group_caps_pct: caps });
  };

  return (
    <details className="aas-adv" open={!!constraints}>
      <summary>제약 조건 — 종목·그룹 상한 · 회전율 · β · 현금 밴드 {constraints ? "· 적용 중" : ""}</summary>
      <div className="as-ct-grid">
        <label><span>종목당 상한 %</span>
          <input className="as-input num" type="number" min={1} max={100} placeholder="없음"
            value={c.max_weight_pct ?? ""} onChange={(e) => set({ max_weight_pct: num(e.target.value) })} /></label>
        <label><span>종목당 하한 %</span>
          <input className="as-input num" type="number" min={0} max={50} placeholder="0"
            value={c.min_weight_pct ?? ""} onChange={(e) => set({ min_weight_pct: num(e.target.value) ?? 0 })} /></label>
        <label><span>회전율 상한 % <em title="현재 보유 대비 편도 회전율">vs 보유</em></span>
          <input className="as-input num" type="number" min={0} max={200} placeholder="없음"
            value={c.turnover_cap_pct ?? ""} onChange={(e) => set({ turnover_cap_pct: num(e.target.value) })} /></label>
        <label><span>β 상한 <em title="벤치마크(KOSPI) 대비 포트폴리오 베타">KOSPI</em></span>
          <input className="as-input num" type="number" step={0.1} min={-2} max={3} placeholder="없음"
            value={c.beta_max ?? ""} onChange={(e) => set({ beta_max: num(e.target.value) })} /></label>
        <label><span>현금 최소 %</span>
          <input className="as-input num" type="number" min={0} max={90} placeholder="0"
            value={c.cash_min_pct ?? ""} onChange={(e) => set({ cash_min_pct: num(e.target.value) ?? 0 })} /></label>
        <label><span>현금 최대 %</span>
          <input className="as-input num" type="number" min={0} max={90} placeholder="0 (완전투자)"
            value={c.cash_max_pct ?? ""} onChange={(e) => set({ cash_max_pct: num(e.target.value) ?? 0 })} /></label>
      </div>
      <label className="as-tm-set"><span>섹터 그룹 상한 <em>예: 반도체·전자:30, 금융:20</em></span>
        <input value={groupText} placeholder="그룹명:상한%, 그룹명:상한%"
          onChange={(e) => setGroupText(e.target.value)} onBlur={parseGroups} /></label>
      <div className="as-wl-row" style={{ marginTop: 6 }}>
        <button className="as-fb-apply" onClick={() => runAnalyze()}>제약 적용 재최적화 →</button>
        {constraints && <button className="as-chip" onClick={() => { setConstraints(null); runAnalyze(); }}>제약 해제</button>}
      </div>

      {rep && (
        <div className={`as-ct-report ${rep.status}`}>
          <b>
            {rep.status === "ok" ? "✓ 제약 충족 해"
              : rep.status === "approx" ? "△ 근사해 — 위반 목록 확인"
                : "✕ INFEASIBLE — 해 없음"}
          </b>
          {rep.reason && <div className="as-ct-line">{rep.reason}</div>}
          {rep.relaxed.length > 0 && <div className="as-ct-line">완화된 제약: {rep.relaxed.join(", ")} (보고되는 완화 — 임의 완화 아님)</div>}
          {rep.violations.map((v, i) => (
            <div key={i} className="as-ct-line viol">위반 · {v.detail}{v.amount_pct != null ? ` (+${v.amount_pct}%p)` : ""}</div>
          ))}
          {rep.binding.length > 0 && <div className="as-ct-line">바인딩(딱 걸림): {rep.binding.join(" · ")}</div>}
          {rep.notes.map((n, i) => <div key={i} className="as-ct-line">• {n}</div>)}
        </div>
      )}
    </details>
  );
}

export default function OptimizerWorkspace() {
  const {
    result, model, setModel, delta, setDelta, tau, setTau,
    runAnalyze, canRun, pending, analyzeError, views, isResultStale,
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
          <div className="as-engine-cur">현재 엔진 <b>{MODELS.find((m) => m.id === model)?.label ?? model.toUpperCase()}</b></div>
          <button className="as-run" disabled={!canRun || pending} onClick={() => runAnalyze()}>
            {pending ? "최적화 중…" : result ? "Re-optimize" : "최적화 실행"}
          </button>
          {result && isResultStale && (
            <div className="as-note" style={{ color: "var(--t-accent)" }}>설정이 바뀌었습니다 — 재최적화 후 다음 단계로 진행하세요.</div>
          )}
          <details className="aas-adv">
            <summary>고급 설정 — 엔진 · λ · τ</summary>
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
          </details>
          <ConstraintsPanel />
          {!canRun && <div className="as-note">01 CONSTRUCT에서 자산 2개 이상 추가 →</div>}
          {analyzeError && <div className="as-err">{analyzeError}</div>}
          {result && COV_ONLY.includes(result.model) && views.length > 0 && (
            <div className="as-note">뷰는 Black-Litterman 모델에서만 기대수익에 반영됩니다</div>
          )}
          {result && result.cap_missing.length > 0 && (
            <div className="as-note">시총 미보유 {result.cap_missing.length}자산은 중앙값 대체(캡가중 prior)</div>
          )}
        </section>
        <TimingOverlayPanel />
        <NeutralizePanel />
      </aside>
      <main className="as-center">
        <section className={`as-card${pending ? " as-loading" : ""}`} aria-busy={pending}>
          <div className="as-card-title">EFFICIENT FRONTIER
            {result?.views_applied && <span className="as-badge">BL 뷰 적용</span>}
          </div>
          {/* 재계산 중에도 이전 프론티어를 계속 그린다 — 그렇다면 그렇다고 적어야 한다(A4-X1). */}
          {pending && <StageBusy label="최적화 재계산 중…" stale={!!result} />}
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
        {/* ★레일과 메인의 역할이 뒤집혀 있었다 (A5-S2)★ 320px 레일이 엔진 + 4열 지표표 +
            MC 히스토그램 + 7행 오버레이표 + 중립화를 이고 있는 동안, 1fr 메인은 카드 두 장
            뒤로 빈 공간이었다. 규칙을 세운다: **레일 = 컨트롤, 메인 = 근거.**
            지표표와 분포는 근거이므로 여기로 온다 — 넓은 칼럼에서 4열 표가 비로소 읽힌다. */}
        <div className="as-opt-ev">
          <section className="as-card">
            <div className="as-card-title">SUMMARY METRICS</div>
            {result ? <MetricsTable summary={result.summary} /> : <div className="as-empty">Re-optimize 실행 시 표시</div>}
            {result?.enb && (
              <div className="as-enb" title={result.enb.note}>
                <span className="as-enb-k">실질 분산 (ENB)</span>
                <b className="num">{result.enb.enb.toFixed(2)}</b>
                <span className="as-note-inline">/ {result.enb.n_assets}자산 · Neff {result.enb.neff.toFixed(2)} (상관 반영 vs 비중만)</span>
              </div>
            )}
          </section>
          <section className="as-card">
            <div className="as-card-title">RETURN DISTRIBUTION <span className="as-note-inline">MC 1년</span></div>
            {result ? <McHistogram mc={result.mc} /> : <div className="as-empty">Re-optimize 실행 시 표시</div>}
          </section>
        </div>

        <section className={`as-card${pending ? " as-loading" : ""}`} aria-busy={pending}>
          <div className="as-card-title">ALLOCATION FLOW <span className="as-note-inline">시장 → 뷰 반영 → 최적화</span></div>
          {pending && <StageBusy label="가중치 흐름 재계산 중…" stale={!!result} />}
          {result ? <AllocationSankey result={result} /> : <div className="as-empty">가중치 흐름</div>}
        </section>
      </main>
    </div>
  );
}
