"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// SleeveStudio — 전략 슬리브 결합 + 리스크 예산 + 상관/군집 분석 (P3 잔여, Construct)
//   현재 포트폴리오를 명명 슬리브로 저장 → 여러 슬리브를 결합(2단계 배분) →
//   슬리브 배분·리스크 기여·상관·군집·꼬리의존 → 결합 비중을 포트폴리오로 적용.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { sleeveApi, type CombineResult, type SleeveAnalyticsResult } from "@/lib/sleeveApi";
import { deleteSleeve, listSleeves, saveSleeve, type SavedSleeve } from "@/lib/sleeveStorage";
import { useAllocation } from "./AllocationProvider";

const METHODS: [string, string][] = [
  ["risk_parity", "리스크 패리티"], ["risk_budget", "리스크 예산"], ["equal", "동일가중"],
  ["inverse_vol", "역변동성"], ["hrp", "HRP"], ["min_var", "최소분산"],
];

export function SleeveStudio() {
  const { holdings, holdingsMap, setHoldingsReset, logEvent } = useAllocation();
  const [sleeves, setSleeves] = useState<SavedSleeve[]>([]);
  const [name, setName] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [method, setMethod] = useState("risk_parity");
  const [budgets, setBudgets] = useState<Record<string, number>>({});
  const [combined, setCombined] = useState<CombineResult | null>(null);
  const [analytics, setAnalytics] = useState<SleeveAnalyticsResult | null>(null);

  useEffect(() => { setSleeves(listSleeves()); }, []);
  const refresh = () => setSleeves(listSleeves());

  const picked = sleeves.filter((s) => sel.has(s.id));
  const sleeveInputs = picked.map((s) => ({ name: s.name, weights: s.weights }));

  const combineMut = useMutation({
    mutationFn: () => sleeveApi.combineSleeves({
      sleeves: sleeveInputs, method,
      risk_budget: method === "risk_budget" ? Object.fromEntries(picked.map((s) => [s.name, budgets[s.id] ?? 1])) : null,
    }),
    onSuccess: (d) => { setCombined(d); logEvent(`슬리브 결합 — ${method} (${picked.length}개)`); },
  });
  const analyticsMut = useMutation({
    mutationFn: () => sleeveApi.sleeveAnalytics({ sleeves: sleeveInputs }),
    onSuccess: (d) => setAnalytics(d),
  });

  const doSave = () => {
    if (holdings.length < 1) return;
    const names: Record<string, string> = {};
    holdings.forEach((h) => { names[h.code] = h.name; });
    saveSleeve(name, holdingsMap, names); setName(""); refresh();
  };
  const toggle = (id: string) => setSel((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const applyCombined = () => {
    if (!combined?.combined_weights_pct) return;
    const labelOf: Record<string, string> = {};
    picked.forEach((s) => Object.assign(labelOf, s.names || {}));
    setHoldingsReset(Object.entries(combined.combined_weights_pct)
      .map(([code, w]) => ({ code, name: labelOf[code] || code, weight: w })));
    logEvent("결합 슬리브 → 포트폴리오 적용");
  };

  return (
    <section className="as-card as-slv">
      <div className="as-card-title">SLEEVE STUDIO <span className="as-note-inline">슬리브 결합 · 리스크 예산 · 상관/군집</span></div>

      {/* 현재 포트폴리오를 슬리브로 저장 */}
      <div className="as-slv-save">
        <input className="as-input" placeholder="현재 포트폴리오를 슬리브로 저장 — 이름" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="as-chip" disabled={holdings.length < 1} onClick={doSave}>슬리브 저장</button>
      </div>

      {sleeves.length === 0 ? (
        <div className="as-empty">저장된 슬리브 없음 — 포트폴리오를 구성하고 위에서 슬리브로 저장하세요. 여러 슬리브를 결합할 수 있습니다.</div>
      ) : (
        <>
          <div className="as-slv-list">
            {sleeves.map((s) => (
              <div key={s.id} className={`as-slv-item${sel.has(s.id) ? " on" : ""}`}>
                <label><input type="checkbox" checked={sel.has(s.id)} onChange={() => toggle(s.id)} /></label>
                <span className="as-slv-name">{s.name}</span>
                <span className="as-note-inline num">{Object.keys(s.weights).length}종목</span>
                {method === "risk_budget" && sel.has(s.id) && (
                  <input className="num as-slv-budget" type="number" min={0.1} step={0.5} value={budgets[s.id] ?? 1}
                    onChange={(e) => setBudgets((b) => ({ ...b, [s.id]: Number(e.target.value) || 1 }))} title="리스크 예산" />
                )}
                <button className="as-x" onClick={() => { deleteSleeve(s.id); refresh(); }}>×</button>
              </div>
            ))}
          </div>

          <div className="as-slv-ctrl">
            <select className="as-fb-add" value={method} onChange={(e) => setMethod(e.target.value)}>
              {METHODS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
            </select>
            <button className="as-fb-apply" disabled={sel.size < 1 || combineMut.isPending} onClick={() => combineMut.mutate()}>결합</button>
            <button className="as-chip" disabled={sel.size < 2 || analyticsMut.isPending} onClick={() => analyticsMut.mutate()}>상관·군집 분석</button>
          </div>

          {combined && !combined.error && (
            <div className="as-slv-res">
              <div className="as-card-title" style={{ marginTop: 4 }}>슬리브 배분 · 리스크 기여</div>
              <table className="as-metrics">
                <thead><tr><th>슬리브</th><th>배분</th><th>리스크 기여</th><th>변동성</th></tr></thead>
                <tbody>
                  {Object.keys(combined.sleeve_allocation ?? {}).map((nm) => (
                    <tr key={nm}><td>{nm}</td>
                      <td className="num">{combined.sleeve_allocation![nm]}%</td>
                      <td className="num">{combined.risk_contribution_pct?.[nm]}%</td>
                      <td className="num">{combined.sleeve_vol_pct?.[nm]}%</td></tr>
                  ))}
                </tbody>
              </table>
              <div className="as-note num">결합 {combined.n_stocks}종목 · <button className="as-chip on sm" onClick={applyCombined}>결합 비중 → 포트폴리오</button></div>
            </div>
          )}
          {combined?.error && <div className="as-note">{combined.message}</div>}

          {analytics && !analytics.error && (
            <div className="as-slv-res">
              <div className="as-card-title" style={{ marginTop: 6 }}>상관 · 군집 · 꼬리의존</div>
              <div className="as-note num">평균 상관 {analytics.avg_correlation} · 군집 {analytics.n_clusters}개 ·
                하위꼬리 동반 {analytics.tail_dependency?.lower_tail_coexceedance ?? "—"}
                {analytics.tail_dependency && analytics.tail_dependency.lower_tail_coexceedance != null &&
                  analytics.tail_dependency.lower_tail_coexceedance > 1.3 && <b className="as-neu-bad"> (분산효과 약화)</b>}
              </div>
              <div className="as-slv-clusters">
                {analytics.sleeves?.map((nm) => (
                  <span key={nm} className={`as-slv-cl cl-${(analytics.clusters?.[nm] ?? 0) % 6}`} title={`군집 ${analytics.clusters?.[nm]}`}>
                    {nm} <b className="num">{analytics.risk_contribution_pct?.[nm]}%</b>
                  </span>
                ))}
              </div>
              <div className="as-note">{analytics.note}</div>
            </div>
          )}
          {analytics?.error && <div className="as-note">{analytics.message}</div>}
        </>
      )}
    </section>
  );
}
