"use client";
// ResearchRuns 패널 (P1 재현성) — 현재 결과를 run으로 기록(서버 스탬프) + DB 목록 +
// 두 run 나란히 비교(비중 Δ·요약지표 Δ). 저널(localStorage 초안)과 별개의 영속 기록.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { attributionApi } from "@/entities/attribution/api";
import { researchApi, type ReproduceResult, type ResearchRunFull, type ResearchRunSummary } from "@/entities/research/api";
import { useAllocation } from "./AllocationProvider";

const fmtTs = (sec: number) => {
  try { return new Date(sec * 1000).toISOString().slice(0, 16).replace("T", " "); }
  catch { return "—"; }
};

function SourceBadge({ src }: { src?: string }) {
  if (!src) return null;
  const mock = src !== "db";
  // ★라이트 전용 리터럴이었다 (P1-D 에서 발견)★ 예전에는 인라인으로 `#16a34a`/`#15803d`
  // 를 박았는데, `#15803d` 는 라이트 zinc-50 에서 4.85:1 이지만 **다크 zinc-900 에서
  // 3.53:1** 이다. 기존 다크 감사(`aas-dark.spec.ts`)는 런이 하나도 없는 세션을 보므로
  // 이 배지가 아예 렌더되지 않아 통과했다 — 런을 스텁한 P1 스펙이 처음 잡았다.
  // `.as-bt-badge.real`(:6016)이 이미 쓰는 `--chart-up` 토큰으로 옮긴다(다크에서 뒤집힌다).
  return (
    <span className={`as-rr-src num${mock ? "" : " real"}`}>{mock ? "MOCK" : "REAL"}</span>
  );
}

/**
 * 재현 결과 — 다섯 상태를 **서로 다른 문장**으로 그린다 (P1-D).
 *
 *   재현됨 / 달라짐 / 비교 불가 / 재현 불가 / 응답 없음
 *
 * ★"비교 불가" 를 초록으로 그리지 않는다★ 대조할 것이 없었다는 사실은 일치가 아니다.
 * ★추정 재현이면 반드시 그렇게 적는다★ `basis: "coverage_end"` 는 요청 시점의 as_of 가
 * 아니라 관측 마지막 날로 맞춘 것이라, 확정 재현과 같은 무게로 읽히면 안 된다.
 */
const BASIS_LABEL: Record<string, string> = {
  recorded_as_of: "기록된 as_of",
  server_stamped: "서버가 쓴 절단일",
  coverage_end: "관측 마지막 날 (추정)",
};

function ReproduceOut({ res }: { res: ReproduceResult | { net: string } }) {
  if ("net" in res) {
    return (
      <div className="as-err as-rr-repro-out as-rr-repro-net">
        재현 요청에 <b>응답이 없습니다</b> (네트워크/서버) — 재현에 실패한 것과는 다릅니다.
      </div>
    );
  }
  if (!res.reproducible) {
    return (
      <div className="as-note as-rr-repro-out as-rr-repro-no">
        <b>재현할 수 없습니다</b> — {res.reason}
      </div>
    );
  }
  const est = res.estimated ? (
    <span className="as-rr-repro-est" title="요청 시점의 as_of 가 아니라 관측 마지막 날로 맞춘 추정 재현입니다">
      추정 재현
    </span>
  ) : null;
  const coord = (
    <span className="as-note-inline">
      기준일 <b className="num">{res.as_of}</b> · {BASIS_LABEL[res.basis] ?? res.basis}
    </span>
  );

  if (res.verdict === "incomparable") {
    return (
      <div className="as-note as-rr-repro-out as-rr-repro-incomp">
        다시 돌렸지만 <b>대조할 수 없습니다</b> — {res.reason} {coord} {est}
      </div>
    );
  }
  const uc = res.universe_changed ?? { dropped: [], added: [] };
  if (res.verdict === "identical") {
    return (
      <div className="as-rr-repro-out as-rr-repro-ok">
        <b>재현됨</b> — 최대 Δ <span className="num">0.00%p</span> {coord} {est}
      </div>
    );
  }
  const worst = (res.deltas ?? [])[0];
  return (
    <div className="as-rr-repro-out as-rr-repro-drift">
      <b>달라졌습니다</b> — 최대 Δ{" "}
      <span className="num">{(res.max_delta_pp ?? 0).toFixed(2)}%p</span>
      {worst && <> (<span className="num">{worst.code}</span>{" "}
        <span className="num">{worst.recorded.toFixed(1)}%</span> →{" "}
        <span className="num">{worst.fresh.toFixed(1)}%</span>)</>}
      {" "}{coord} {est}
      {(uc.dropped.length > 0 || uc.added.length > 0) && (
        <div className="as-rr-repro-uni">
          유니버스도 바뀌었습니다 —
          {uc.dropped.length > 0 && <> 빠짐 <span className="num">{uc.dropped.join(", ")}</span></>}
          {uc.added.length > 0 && <> 추가 <span className="num">{uc.added.join(", ")}</span></>}
          {" "}(비중 이동과는 다른 사실이라 Δ 에 넣지 않습니다)
        </div>
      )}
    </div>
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
  // ── 재현 (P1-C) ────────────────────────────────────────────────────────────
  // `"loading"` · 결과 · `{ net: 사유 }` 셋을 **다른 값**으로 들고 있는다. 네트워크
  // 오류를 `null` 로 뭉개면 "재현 실패" 와 "응답 없음" 이 한 화면이 된다 —
  // R0-S 가 목록에서 고친 결함과 같은 계열이라 여기서 반복하지 않는다.
  const [repro, setRepro] = useState<Record<string, "loading" | ReproduceResult | { net: string }>>({});

  const listQ = useQuery({
    queryKey: ["research", "runs", runsVersion],
    // ★`catch` 로 뭉개지 않는다 (R0-S)★ 예전에는 `.catch(() => null)` 이라 **네트워크
    // 오류가 null 이 되고**, 그 null 이 아래에서 "기록된 런 없음" 으로 그려졌다. 저장소
    // 장애·네트워크 오류·기록 없음이 화면에서 같은 문장이 되면, 사용자는 연구 기록이
    // 사라졌다고 읽는다. 실패는 그대로 두고 네 상태를 각각 그린다.
    queryFn: () => researchApi.list("allocation_analyze", 30),
    retry: 1,
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

  /**
   * 재현 — 서버가 **같은 코드로** 다시 돌려 결과를 대조한다 (P1-C).
   *
   * ★되돌리기와는 다른 동작이다★ 되돌리기는 이 런의 입력으로 위저드를 덮어쓰고
   * `activeRunId` 를 바꾼다. 재현은 **아무것도 바꾸지 않는다** — 과거 결정이
   * 지금도 같은 답을 내는지 묻기만 한다. 둘을 한 버튼으로 합치면 "확인하려다
   * 작업 중인 런을 잃는" 일이 생긴다.
   */
  const doReproduce = async (rid: string) => {
    setRepro((m) => ({ ...m, [rid]: "loading" }));
    try {
      const out = await researchApi.reproduce(rid);
      setRepro((m) => ({ ...m, [rid]: out }));
    } catch (e) {
      // 응답을 못 받은 것은 "재현 실패" 와 다른 사실이다 — 다른 문장을 쓴다.
      setRepro((m) => ({ ...m, [rid]: { net: e instanceof Error ? e.message : String(e) } }));
    }
  };

  // ★네 상태를 각각 구분한다 (R0-S)★ 로딩 / 저장소 장애 / 네트워크 오류 / 기록 없음.
  // `available:false` 는 서버가 "저장소를 못 읽었다" 고 답한 것이고, `isError` 는 그
  // 답조차 못 받은 것이다 — 사용자에게 다른 사실이므로 다른 문장을 쓴다.
  const storageDown = listQ.data?.available === false;
  const networkDown = listQ.isError;
  const dbUnavailable = storageDown || networkDown;   // 기존 소비 지점 호환

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

      {storageDown && (
        <div className="as-err as-rr-storage-down">
          {listQ.data?.reason ?? "연구 기록 저장소를 읽을 수 없습니다"} —
          <b> 기록이 없는 것이 아닙니다.</b>
        </div>
      )}
      {networkDown && (
        <div className="as-err as-rr-network-down">
          런 목록 요청이 실패했습니다 (네트워크/서버 응답 없음) — <b>기록이 없는 것이 아닙니다.</b>
        </div>
      )}
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
      {listQ.isLoading && <div className="as-empty as-rr-loading">런 목록을 불러오는 중…</div>}
      {/* ★빈 상태는 여전히 빈 상태다★ 장애를 구분한다고 "기록 없음"을 없애면 안 된다 —
          기록이 없다는 것도 사용자가 알아야 하는 사실이다. */}
      {!dbUnavailable && !listQ.isLoading && runs.length === 0 && (
        <div className="as-empty as-rr-empty">기록된 런 없음 — 첫 런을 기록하면 재조회·비교가 가능해집니다.</div>
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
          {/* 재현은 위저드를 건드리지 않는다 — 되돌리기와 나란히 두되 다른 동작이다. */}
          <button className="as-rr-repro"
            title="이 런을 서버가 같은 코드로 다시 돌려 결과를 대조한다 (화면 상태는 바뀌지 않는다)"
            disabled={repro[r.run_id] === "loading"}
            onClick={(e) => { e.stopPropagation(); doReproduce(r.run_id); }}>
            {repro[r.run_id] === "loading" ? "재현 중…" : "재현"}
          </button>
          <button className="as-x" title="삭제" onClick={(e) => {
            e.stopPropagation();
            researchApi.remove(r.run_id).then(() => listQ.refetch()).catch(() => {});
            setSel((s) => s.filter((x) => x !== r.run_id));
            setRepro((m) => { const n = { ...m }; delete n[r.run_id]; return n; });
          }}>×</button>
          {repro[r.run_id] && repro[r.run_id] !== "loading" && (
            <ReproduceOut res={repro[r.run_id] as ReproduceResult | { net: string }} />
          )}
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
