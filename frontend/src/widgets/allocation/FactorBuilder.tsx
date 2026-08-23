"use client";
// 팩터 기반 포트폴리오 빌더 — 팩터 다중 선택(방향·가중치) → 방향 인지 z 가중합으로
// 유니버스를 점수화, 상위 K종목 선정 → 비중화(균등/팩터틸트/역변동성/리스크패리티/최소분산/HRP).
// 백엔드 POST /allocation/factor-portfolio (스크리너 팩터 스토어 + allocation 가중 엔진 재사용).
import React, { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { screenerApiAdvanced } from "@/entities/screener/api/ast";
import type { FieldMeta } from "@/shared/model/domain";
import { allocationApi, type FactorWeighting } from "@/entities/allocation/api";
import type { Holding } from "./PortfolioBuilder";

interface FSel { id: string; label: string; weight: number; direction: number; higher_better: boolean }

const WEIGHTINGS: { id: FactorWeighting; label: string }[] = [
  { id: "equal", label: "균등" },
  { id: "factor_tilt", label: "팩터 틸트" },
  { id: "inverse_vol", label: "역변동성" },
  { id: "risk_parity", label: "리스크 패리티" },
  { id: "min_var", label: "최소 분산" },
  { id: "hrp", label: "HRP" },
];

// 빠른 프리셋 — 카탈로그에 존재하는 id만 반영
const PRESETS: { label: string; ids: string[] }[] = [
  { label: "가치", ids: ["earnings_yield", "book_to_market", "fcf_yield", "per"] },
  { label: "퀄리티", ids: ["roe", "gp_to_assets", "operating_margin", "roic"] },
  { label: "모멘텀", ids: ["momentum_12_1", "return_6m", "price_momentum_12_1"] },
  { label: "저변동", ids: ["volatility_60d", "beta_1y", "downside_vol"] },
  { label: "배당", ids: ["dividend_yield", "shareholder_yield", "payout_ratio"] },
];

const DIR_LABEL: Record<number, string> = { 0: "자동", 1: "높은값", [-1]: "낮은값" };

export function FactorBuilder({ holdings, onApply }: { holdings: Holding[]; onApply: (h: Holding[]) => void }) {
  const fieldsQ = useQuery({ queryKey: ["screener", "fields"], queryFn: () => screenerApiAdvanced.fields() });
  const [sel, setSel] = useState<FSel[]>([]);
  const [topK, setTopK] = useState(10);
  const [weighting, setWeighting] = useState<FactorWeighting>("equal");
  const [universe, setUniverse] = useState<"sample" | "holdings">("sample");

  const cats = fieldsQ.data?.categories ?? [];
  const byId = useMemo(() => {
    const m = new Map<string, FieldMeta>();
    cats.forEach((c) => c.fields.forEach((f) => m.set(f.id, f)));
    return m;
  }, [cats]);

  const addId = (id: string) => {
    const f = byId.get(id);
    if (!f || sel.some((s) => s.id === id)) return;
    setSel((prev) => [...prev, { id: f.id, label: f.label, weight: 1, direction: 0, higher_better: f.higher_better }]);
  };
  const upd = (id: string, patch: Partial<FSel>) => setSel((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  const rm = (id: string) => setSel((prev) => prev.filter((s) => s.id !== id));
  const applyPreset = (ids: string[]) => { setSel([]); setTimeout(() => ids.forEach(addId), 0); };

  const build = useMutation({
    mutationFn: () => allocationApi.factorPortfolio({
      factors: sel.map((s) => ({ id: s.id, weight: s.weight, direction: s.direction })),
      tickers: universe === "holdings" ? holdings.map((h) => h.code) : null,
      top_k: topK, weighting,
    }),
  });
  const res = build.data;

  const apply = () => {
    if (!res || res.error || !res.holdings?.length) return;
    onApply(res.holdings.map((h) => ({ code: h.code, name: h.name || h.code, weight: h.weight })));
  };

  return (
    <div className="as-fb">
      {/* 팩터 선택 */}
      <div className="as-fb-row">
        <select className="as-fb-add" value="" onChange={(e) => addId(e.target.value)}>
          <option value="">+ 팩터 추가…</option>
          {cats.map((c) => (
            <optgroup key={c.id} label={c.label}>
              {c.fields.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </optgroup>
          ))}
        </select>
        <div className="as-fb-presets">
          {PRESETS.map((p) => (
            <button key={p.label} className="as-chip sm" onClick={() => applyPreset(p.ids)}>{p.label}</button>
          ))}
        </div>
      </div>

      {/* 선택된 팩터: 가중치 + 방향 */}
      {sel.length === 0 && <div className="as-empty">위에서 팩터를 1개 이상 추가하세요 (예: 가치·퀄리티·모멘텀).</div>}
      {sel.map((s) => (
        <div key={s.id} className="as-fb-fac">
          <button className="as-x" title="제거" onClick={() => rm(s.id)}>×</button>
          <span className="as-fb-fac-nm" title={`${s.id} · 기본 방향 ${s.higher_better ? "높은값 선호" : "낮은값 선호"}`}>{s.label}</span>
          <span className="as-fb-fac-w">
            가중 <input type="number" className="num" min={0.5} max={5} step={0.5} value={s.weight}
              onChange={(e) => upd(s.id, { weight: parseFloat(e.target.value) || 0 })} />
          </span>
          <div className="as-fb-dir">
            {[0, 1, -1].map((d) => (
              <button key={d} className={s.direction === d ? "on" : ""} onClick={() => upd(s.id, { direction: d })}>{DIR_LABEL[d]}</button>
            ))}
          </div>
        </div>
      ))}

      {/* 파라미터 */}
      <div className="as-fb-params">
        <label>유니버스
          <select value={universe} onChange={(e) => setUniverse(e.target.value as "sample" | "holdings")}>
            <option value="sample">유니버스 표본(전체)</option>
            <option value="holdings" disabled={holdings.length < 3}>현재 보유 종목 재랭킹</option>
          </select>
        </label>
        <label>보유 종목 수 <b className="num">{topK}</b>
          <input type="range" min={2} max={30} step={1} value={topK} onChange={(e) => setTopK(parseInt(e.target.value))} />
        </label>
        <label>비중 방식
          <select value={weighting} onChange={(e) => setWeighting(e.target.value as FactorWeighting)}>
            {WEIGHTINGS.map((w) => <option key={w.id} value={w.id}>{w.label}</option>)}
          </select>
        </label>
      </div>

      <button className="as-run" disabled={sel.length === 0 || build.isPending} onClick={() => build.mutate()}>
        {build.isPending ? "빌드 중…" : "팩터 포트폴리오 빌드"}
      </button>
      {build.isError && <div className="as-err">빌드 실패 — 잠시 후 다시 시도하세요.</div>}

      {/* 결과 */}
      {res?.error && <div className="as-err">{res.message}</div>}
      {res && !res.error && (
        <div className="as-fb-result">
          <div className="as-fb-result-head">
            <span>후보 {res.candidates} · 점수화 {res.ranked} → 상위 {res.holdings.length}</span>
            <button className="as-fb-apply" onClick={apply}>이 포트폴리오로 적용 →</button>
          </div>
          <table className="as-metrics">
            <thead><tr><th>#</th><th>종목</th><th>비중</th><th>팩터점수</th><th>커버리지</th></tr></thead>
            <tbody>
              {res.holdings.map((h, i) => (
                <tr key={h.code}>
                  <td className="num">{i + 1}</td>
                  <td>{h.name}<span className="as-fb-code num"> {h.code}</span></td>
                  <td className="num">{h.weight.toFixed(1)}%</td>
                  <td className="num" style={{ color: h.score >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{h.score.toFixed(2)}</td>
                  <td className="num">{h.coverage_pct.toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="as-note">
            {res.factors.filter((f) => !f.covered).length > 0
              ? `일부 팩터 결측(${res.factors.filter((f) => !f.covered).map((f) => f.label).join("·")}) — 커버된 팩터로 재정규화. `
              : ""}
            방향 인지 z-score 가중합 · {WEIGHTINGS.find((w) => w.id === res.weighting)?.label} 비중.
          </div>
        </div>
      )}
    </div>
  );
}
