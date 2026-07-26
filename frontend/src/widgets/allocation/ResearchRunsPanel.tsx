"use client";
// ResearchRuns 패널 (P1 재현성) — 현재 결과를 run으로 기록(서버 스탬프) + DB 목록 +
// 두 run 나란히 비교(비중 Δ·요약지표 Δ). 저널(localStorage 초안)과 별개의 영속 기록.
import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { researchApi, type ResearchRunFull, type ResearchRunSummary } from "@/entities/research/api";
import { useAllocation } from "./AllocationProvider";

const fmtTs = (sec: number) => {
  try { return new Date(sec * 1000).toISOString().slice(0, 16).replace("T", " "); }
  catch { return "—"; }
};

function SourceBadge({ src }: { src?: string }) {
  if (!src) return null;
  const mock = src !== "db";
  return (
    <span className="as-rr-src num" style={mock ? undefined : { borderColor: "#16a34a", color: "#15803d" }}>
      {mock ? "MOCK" : "REAL"}
    </span>
  );
}

function CompareTable({ a, b }: { a: ResearchRunFull; b: ResearchRunFull }) {
  const wa = a.outputs.weights?.optimized ?? {};
  const wb = b.outputs.weights?.optimized ?? {};
  const labels = { ...(a.outputs.labels ?? {}), ...(b.outputs.labels ?? {}) };
  const codes = Array.from(new Set([...Object.keys(wa), ...Object.keys(wb)]))
    .sort((x, y) => (wb[y] ?? 0) + (wa[y] ?? 0) - (wb[x] ?? 0) - (wa[x] ?? 0));
  const sa = a.outputs.summary?.portfolio ?? {};
  const sb = b.outputs.summary?.portfolio ?? {};
  const METRICS: [string, string][] = [
    ["expected_return_pct", "기대수익 %"], ["volatility_pct", "변동성 %"],
    ["sharpe", "Sharpe"], ["max_drawdown_pct", "최대낙폭 %"],
  ];
  const col = (v: number) => (v > 0 ? "var(--color-bull)" : v < 0 ? "var(--color-bear)" : "var(--t-muted)");
  return (
    <div className="as-rr-cmp">
      <table className="as-metrics">
        <thead><tr><th>자산</th><th className="num">A</th><th className="num">B</th><th className="num">Δ (B−A)</th></tr></thead>
        <tbody>
          {codes.map((c) => {
            const va = wa[c] ?? 0, vb = wb[c] ?? 0, d = vb - va;
            return (
              <tr key={c}>
                <td>{labels[c] || c}</td>
                <td className="num">{va.toFixed(1)}%</td>
                <td className="num">{vb.toFixed(1)}%</td>
                <td className="num" style={{ color: col(d), fontWeight: 600 }}>{d >= 0 ? "+" : ""}{d.toFixed(1)}%p</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <table className="as-metrics" style={{ marginTop: 8 }}>
        <thead><tr><th>지표</th><th className="num">A</th><th className="num">B</th><th className="num">Δ</th></tr></thead>
        <tbody>
          {METRICS.map(([k, label]) => {
            const va = (sa as Record<string, number>)[k], vb = (sb as Record<string, number>)[k];
            if (va == null && vb == null) return null;
            const d = (vb ?? 0) - (va ?? 0);
            return (
              <tr key={k}>
                <td>{label}</td>
                <td className="num">{va != null ? va : "—"}</td>
                <td className="num">{vb != null ? vb : "—"}</td>
                <td className="num" style={{ color: col(d) }}>{d >= 0 ? "+" : ""}{d.toFixed(2)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="as-note num">
        A: {a.name || a.run_id} ({a.inputs.model as string ?? "?"}, {fmtTs(a.created_at)}) ·
        B: {b.name || b.run_id} ({b.inputs.model as string ?? "?"}, {fmtTs(b.created_at)}) ·
        코드 {a.code_version}{a.code_version !== b.code_version ? ` → ${b.code_version}` : ""}
      </div>
    </div>
  );
}

export function ResearchRunsPanel() {
  const { canRun, result, recordRun, activeRunId, runsVersion } = useAllocation();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [sel, setSel] = useState<string[]>([]);   // 비교 선택 (최대 2)

  const listQ = useQuery({
    queryKey: ["research", "runs", runsVersion],
    queryFn: () => researchApi.list("allocation_analyze", 30).catch(() => null),
  });
  const runs: ResearchRunSummary[] = listQ.data?.runs ?? [];

  const [idA, idB] = sel;
  const cmpQ = useQuery({
    queryKey: ["research", "cmp", idA, idB],
    queryFn: async () => {
      const [a, b] = await Promise.all([researchApi.get(idA!), researchApi.get(idB!)]);
      return { a, b };
    },
    enabled: sel.length === 2,
  });

  const toggle = (rid: string) =>
    setSel((s) => (s.includes(rid) ? s.filter((x) => x !== rid) : [...s, rid].slice(-2)));

  const doRecord = async () => {
    setSaving(true);
    try { await recordRun(name); setName(""); } finally { setSaving(false); }
  };

  const dbUnavailable = useMemo(
    () => !listQ.isLoading && listQ.data === null, [listQ.isLoading, listQ.data]);

  return (
    <section className="as-card">
      <div className="as-card-title">
        RESEARCH RUNS <span className="as-note-inline">DB 영속 · run_id 재현성 단위 — 두 개 선택 시 비교</span>
      </div>
      <div className="as-rr-record">
        <input className="as-input" placeholder="런 이름 — 예: BL 뷰 v2 (반도체 80%)"
          value={name} onChange={(e) => setName(e.target.value)} />
        <button className="as-fb-apply" disabled={!canRun || saving} onClick={doRecord}
          title="현재 입력으로 서버가 재계산·기록 (inputs/outputs 정합 보장)">
          {saving ? "기록 중…" : "현재 결과를 런으로 기록"}
        </button>
      </div>
      {!result && <div className="as-note">Re-optimize 실행 후 기록하면 결과 요약이 함께 저장됩니다.</div>}

      {dbUnavailable && <div className="as-err">런 목록을 불러오지 못했습니다 (백엔드/DB 미가용).</div>}
      {!dbUnavailable && runs.length === 0 && !listQ.isLoading && (
        <div className="as-empty">기록된 런 없음 — 첫 런을 기록하면 재조회·비교가 가능해집니다.</div>
      )}

      {runs.map((r) => (
        <div key={r.run_id}
          className={`as-rr-item${sel.includes(r.run_id) ? " on" : ""}${activeRunId === r.run_id ? " active" : ""}`}
          onClick={() => toggle(r.run_id)} role="button" tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") toggle(r.run_id); }}>
          <span className="as-rr-name">
            {activeRunId === r.run_id && <i className="as-rr-dot" title="현재 세션의 런" />}
            {r.name || r.run_id}
          </span>
          <SourceBadge src={r.snapshot?.coverage?.source} />
          <span className="num as-note-inline">{fmtTs(r.created_at)}</span>
          <button className="as-x" title="삭제" onClick={(e) => {
            e.stopPropagation();
            researchApi.remove(r.run_id).then(() => listQ.refetch()).catch(() => {});
            setSel((s) => s.filter((x) => x !== r.run_id));
          }}>×</button>
        </div>
      ))}

      {sel.length === 2 && cmpQ.data && <CompareTable a={cmpQ.data.a} b={cmpQ.data.b} />}
      {sel.length === 2 && cmpQ.isLoading && <div className="as-empty">비교 로드 중…</div>}
      {sel.length === 1 && <div className="as-note">하나 더 선택하면 나란히 비교합니다.</div>}
    </section>
  );
}
