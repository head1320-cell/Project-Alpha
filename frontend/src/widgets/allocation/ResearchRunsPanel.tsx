"use client";
// ResearchRuns 패널 (P1 재현성) — 현재 결과를 run으로 기록(서버 스탬프) + DB 목록 +
// 두 run 나란히 비교(비중 Δ·요약지표 Δ). 저널(localStorage 초안)과 별개의 영속 기록.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { attributionApi } from "@/entities/attribution/api";
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

export function ResearchRunsPanel({ focusRunId = null }: { focusRunId?: string | null } = {}) {
  const { canRun, result, recordRun, activeRunId, runsVersion, reopenRun, holdings } = useAllocation();
  // ★URL 로 지목된 런★ (D6) — `?run=` 이 있으면 그 행을 표시하고 화면 안으로 옮긴다.
  // 목록은 최근 30건이므로 더 오래된 런은 여기 없을 수 있다. 그 경우 조용히 넘어가지
  // 않고 아래에서 "목록에 없다" 고 적는다 — 링크를 눌렀는데 아무 일도 안 일어나면
  // 사용자는 자기가 잘못 눌렀다고 생각한다.
  const focusRef = useRef<HTMLDivElement | null>(null);
  const [reopening, setReopening] = useState<string | null>(null);
  const [reopenErr, setReopenErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [sel, setSel] = useState<string[]>([]);   // 비교 선택 (최대 2)

  const listQ = useQuery({
    queryKey: ["research", "runs", runsVersion],
    queryFn: () => researchApi.list("allocation_analyze", 30).catch(() => null),
  });
  const runs: ResearchRunSummary[] = listQ.data?.runs ?? [];

  // 목록이 도착한 뒤 지목된 행을 화면 안으로 옮긴다.
  useEffect(() => {
    if (focusRunId && focusRef.current) {
      focusRef.current.scrollIntoView({ block: "center", behavior: "auto" });
    }
  }, [focusRunId, listQ.data]);
  const focusMissing = !!focusRunId && listQ.isSuccess
    && !(listQ.data?.runs ?? []).some((r) => r.run_id === focusRunId);

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

  // 되돌리기는 위저드 상태를 **덮어쓴다** — 저장 안 한 작업이 있으면 먼저 확인한다.
  const doReopen = async (rid: string, label: string) => {
    if (holdings.length > 0 && rid !== activeRunId) {
      const ok = window.confirm(
        `현재 구성(${holdings.length}종목)을 "${label}" 런의 입력으로 덮어씁니다.\n` +
        "저장하지 않은 변경은 사라집니다. 계속할까요?"
      );
      if (!ok) return;
    }
    setReopening(rid);
    setReopenErr(null);
    try {
      const ok = await reopenRun(rid);
      if (!ok) setReopenErr(`런을 되돌리지 못했습니다 — ${rid} 를 읽을 수 없습니다.`);
    } finally {
      setReopening(null);
    }
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
      {reopenErr && <div className="as-err as-rr-reopen-err">{reopenErr}</div>}
      {/* ★링크가 가리키는 런이 목록에 없으면 그 사실을 적는다★ (D6)
          목록은 최근 30건이다. 아무 표시 없이 넘어가면 사용자는 링크가 고장났는지
          자기가 잘못 눌렀는지 알 수 없다. */}
      {focusMissing && (
        <div className="as-rr-focus-missing">
          링크가 가리키는 런 <b className="num">{focusRunId}</b> 이(가) 최근 30건 목록에
          없습니다 — 더 오래된 런이거나 삭제되었을 수 있습니다.
        </div>
      )}
      {!dbUnavailable && runs.length === 0 && !listQ.isLoading && (
        <div className="as-empty">기록된 런 없음 — 첫 런을 기록하면 재조회·비교가 가능해집니다.</div>
      )}

      {runs.map((r) => (
        <div key={r.run_id}
          ref={r.run_id === focusRunId ? focusRef : undefined}
          className={`as-rr-item${sel.includes(r.run_id) ? " on" : ""}${activeRunId === r.run_id ? " active" : ""}${r.run_id === focusRunId ? " focused" : ""}`}
          onClick={() => toggle(r.run_id)} role="button" tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") toggle(r.run_id); }}>
          <span className="as-rr-name">
            {activeRunId === r.run_id && <i className="as-rr-dot" title="현재 세션의 런" />}
            {r.name || r.run_id}
          </span>
          <SourceBadge src={r.snapshot?.coverage?.source} />
          <span className="num as-note-inline">{fmtTs(r.created_at)}</span>
          <button className="as-rr-reopen" title="이 런의 입력·국면 스냅샷으로 위저드를 되돌린다"
            disabled={reopening === r.run_id}
            onClick={(e) => { e.stopPropagation(); doReopen(r.run_id, r.name || r.run_id); }}>
            {reopening === r.run_id ? "복원 중…" : "되돌리기"}
          </button>
          <button className="as-x" title="삭제" onClick={(e) => {
            e.stopPropagation();
            researchApi.remove(r.run_id).then(() => listQ.refetch()).catch(() => {});
            setSel((s) => s.filter((x) => x !== r.run_id));
          }}>×</button>
        </div>
      ))}

      {sel.length === 1 && <RunRationale runId={sel[0]} />}
      {sel.length === 2 && cmpQ.data && <CompareTable a={cmpQ.data.a} b={cmpQ.data.b} />}
      {sel.length === 2 && cmpQ.isLoading && <div className="as-empty">비교 로드 중…</div>}
      {sel.length === 1 && <div className="as-note">하나 더 선택하면 나란히 비교합니다.</div>}
    </section>
  );
}

/**
 * 런의 **근거(rationale)** — 스펙 §5 Journal 요구 (Phase 10b).
 *
 * ★텍스트를 런에 복사하지 않는다★ 근거는 저널 항목이 단일 진실이고 런은 `run_id` 로 연결만
 * 한다. 기록 시점에 복사해 두면 사용자가 나중에 저널을 고쳤을 때 두 곳이 조용히 어긋나고,
 * 어느 쪽이 맞는지 화면만 봐서는 알 수 없다.
 *
 * ★"근거 없음" 과 "못 불러옴" 은 다른 사실이다★ 둘 다 빈 화면으로 두면 사용자는 자기가
 * 기록하지 않았다고 오해한다.
 */
function RunRationale({ runId }: { runId: string }) {
  const q = useQuery({
    queryKey: ["allocation", "journal-by-run", runId],
    queryFn: () => attributionApi.journalByRun(runId),
    retry: false,
  });
  if (q.isLoading) return <div className="as-empty">근거 불러오는 중…</div>;
  if (q.isError) {
    return <div className="as-note as-rr-rationale">
      근거를 <b>불러오지 못했습니다</b> — 기록이 없는 것과는 다릅니다(백엔드/DB 확인).
    </div>;
  }
  const e = q.data?.entry ?? null;
  if (!e) {
    return <div className="as-note as-rr-rationale">
      이 런에는 기록된 근거가 없습니다 — 09 JOURNAL 에서 남길 수 있습니다.
    </div>;
  }
  // 저널의 실제 스키마를 따른다 — 근거는 `record` 안에 있고 리뷰만 최상위다.
  const rows: [string, string | null | undefined][] = [
    ["테제", e.record?.thesis], ["결정", e.record?.decision],
    ["바뀐 이유", e.record?.reason_change], ["원인", e.record?.cause],
    ["반대 논거", e.record?.counter_arguments], ["사후분석", e.record?.postmortem],
    ["리뷰", e.review],
  ];
  return (
    <div className="as-rr-rationale">
      <div className="as-card-title">이 런의 근거 <span className="as-note-inline">저널 항목 연결 — 사본이 아닙니다</span></div>
      {rows.filter(([, v]) => v).map(([k, v]) => (
        <div key={k} className="as-rr-rat-row"><em>{k}</em><span>{v}</span></div>
      ))}
    </div>
  );
}
