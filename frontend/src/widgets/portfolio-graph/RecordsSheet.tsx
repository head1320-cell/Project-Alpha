"use client";
/**
 * 기록함 서랍 (BL2 · 마법사 JOURNAL·EXPLAIN 의 기록 화면에서 옮김)
 * ==========================================================================
 * 캔버스가 저장한 것(판단 기록·연구 기록·실행 목표·국면 스냅샷)을 한 곳에서 다시 본다. 노드가 아니다 — 계산하지
 * 않고, 서버에 이미 있는 기록을 읽고 고치고 지운다. ★목록을 못 읽은 것과 목록이 빈 것은 다른 문장으로 말한다★.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { attributionApi, type DecisionQuality, type JournalEntry } from "@/entities/attribution/api";
import { researchApi, type ReproduceResult } from "@/entities/research/api";
import { targetVersionApi } from "@/entities/allocation/targetVersion";
import { regimeSnapshotApi } from "@/entities/regime-snapshot/api";
import { USAGE_LABEL } from "@/entities/regime-snapshot/model";

type Tab = "journal" | "runs" | "targets" | "snapshots";
const TABS: { id: Tab; label: string }[] = [
  { id: "journal", label: "판단 기록" }, { id: "runs", label: "연구 기록" },
  { id: "targets", label: "실행 목표" }, { id: "snapshots", label: "국면 스냅샷" },
];
const DQ_KO: Record<DecisionQuality, string> = {
  good_outcome_good_process: "결과 좋음 · 판단 좋음", good_outcome_bad_process: "결과 좋음 · 판단 나쁨(운)",
  bad_outcome_good_process: "결과 나쁨 · 판단 좋음(불운)", bad_outcome_bad_process: "결과 나쁨 · 판단 나쁨",
  too_early: "판단하기 일러요",
};
const when = (t: number) => new Date(t * 1000).toLocaleString("ko-KR", { year: "2-digit", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

function Loading() { return <p className="pg-help" role="status">불러오는 중이에요.</p>; }
function Failed({ what, err }: { what: string; err: unknown }) {
  return <p className="pg-field-err" role="alert">{what}을(를) 불러오지 못했어요 — {err instanceof Error ? err.message : "사유 미상"}. 기록이 없는 것과 달라요.</p>;
}

function JournalRow({ e }: { e: JournalEntry }) {
  const qc = useQueryClient();
  const [edit, setEdit] = useState(false);
  const [review, setReview] = useState(e.review ?? "");
  const [dq, setDq] = useState<DecisionQuality | "">(e.decision_quality ?? "");
  const refresh = () => qc.invalidateQueries({ queryKey: ["records", "journal"] });
  const save = useMutation({
    mutationFn: () => attributionApi.reviewJournal(e.entry_id, review.trim(), dq || undefined),
    onSuccess: (r) => { if (r.ok) { setEdit(false); refresh(); } },
  });
  const del = useMutation({ mutationFn: () => attributionApi.deleteJournal(e.entry_id), onSuccess: refresh });
  return (
    <li className="pg-rec-item" data-entry={e.entry_id}>
      <div className="pg-rec-row">
        <b className="pg-rec-name">{e.title}</b>
        {e.decision_quality && <span className="pg-tag pg-tag--unknown">{DQ_KO[e.decision_quality]}</span>}
      </div>
      <p className="pg-pick-sub">{when(e.created_at)}{e.run_id ? ` · 연구 기록 ${e.run_id}` : " · 연구 기록과 이어지지 않았어요"}</p>
      {e.record.decision && <p className="pg-rec-text">{e.record.decision}</p>}
      {!edit && (
        <>
          {e.review ? <p className="pg-rec-text">회고: {e.review}</p> : <p className="pg-help">회고가 아직 없어요 — 결과가 나온 뒤 실제와 대조해 적어요.</p>}
          <div className="pg-rec-actions">
            <button type="button" className="pg-btn" onClick={() => setEdit(true)}>{e.review ? "회고 고치기" : "회고 쓰기"}</button>
            <button type="button" className="pg-btn" aria-label={`${e.title} 삭제`} disabled={del.isPending}
                    onClick={() => { if (window.confirm(`‘${e.title}’ 기록을 지울까요? 되돌릴 수 없어요.`)) del.mutate(); }}>지우기</button>
          </div>
        </>
      )}
      {edit && (
        <div className="pg-rec-edit">
          <label className="pg-rec-field">회고
            <textarea className="pg-field-input" rows={3} value={review} onChange={(ev) => setReview(ev.target.value)}
                      placeholder="예: 3개월 뒤 실제 +8%p — 방향은 맞았고 확신은 낮게 잡았어요" />
          </label>
          <label className="pg-rec-field">판단의 질
            <select className="pg-field-input" value={dq} onChange={(ev) => setDq(ev.target.value as DecisionQuality | "")}>
              <option value="">고르지 않음</option>
              {(Object.keys(DQ_KO) as DecisionQuality[]).map((k) => <option key={k} value={k}>{DQ_KO[k]}</option>)}
            </select>
          </label>
          <div className="pg-rec-actions">
            <button type="button" className="pg-btn pg-btn--primary" disabled={save.isPending} onClick={() => save.mutate()}>회고 저장</button>
            <button type="button" className="pg-btn" onClick={() => setEdit(false)}>그만두기</button>
          </div>
          {save.data && !save.data.ok && <p className="pg-warn" role="status">저장하지 않았어요 — {save.data.reason ?? "사유 미상"}</p>}
          {save.isError && <p className="pg-field-err">저장하지 못했어요 — {(save.error as Error).message}</p>}
        </div>
      )}
    </li>
  );
}

function JournalTab() {
  const q = useQuery({ queryKey: ["records", "journal"], queryFn: () => attributionApi.listJournal() });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <Failed what="판단 기록" err={q.error} />;
  const list = q.data?.entries ?? [];
  if (list.length === 0) return <p className="pg-help">판단 기록이 없어요 — 캔버스의 ‘판단 기록’ 노드에서 저장하면 여기에 모여요.</p>;
  return <ul className="pg-rec-list">{list.map((e) => <JournalRow key={e.entry_id} e={e} />)}</ul>;
}

/**
 * 재현 판정 — ★다섯 상태는 서로 다른 문장이다★ 같음 · 달라짐(무엇이) · 대조할 것 없음 · 재현할 수 없음 · 응답 없음(네트워크).
 * 재현 좌표가 관측 마지막 날로 추정된 것이면 그 사실을 적는다.
 */
function Verdict({ r }: { r: ReproduceResult }) {
  if (!r.reproducible) {
    return <p className="pg-warn pg-rec-verdict" role="status" data-verdict="refused">재현할 수 없어요 — {r.reason}</p>;
  }
  const tag = r.verdict === "identical" ? "confirmed" : r.verdict === "drifted" ? "assumed" : "unknown";
  const text = r.verdict === "identical" ? "같은 비중이 다시 나왔어요"
    : r.verdict === "drifted" ? `비중이 달라졌어요 — 가장 큰 차이 ${r.max_delta_pp == null ? "미상" : r.max_delta_pp.toFixed(2)}%p`
      : `대조할 것이 없었어요 — ${r.reason ?? "사유 미상"}`;
  const moved = (r.deltas ?? []).slice().sort((a, b) => Math.abs(b.delta_pp) - Math.abs(a.delta_pp)).slice(0, 3);
  return (
    <div className="pg-rec-verdict" role="status" data-verdict={r.verdict}>
      <p className="pg-rec-text">
        <span className={`pg-tag pg-tag--${tag}`}>{r.verdict === "identical" ? "같음" : r.verdict === "drifted" ? "달라짐" : "대조 불가"}</span>
        {" "}{text} · 기준일 {r.as_of}{r.estimated ? " (관측 마지막 날로 추정한 기준일)" : ""}
      </p>
      {r.verdict === "drifted" && moved.length > 0 && (
        <ul>{moved.map((d) => <li key={d.code}>{d.code} {d.recorded.toFixed(2)}% → {d.fresh.toFixed(2)}% ({d.delta_pp >= 0 ? "+" : ""}{d.delta_pp.toFixed(2)}%p)</li>)}</ul>
      )}
    </div>
  );
}

function RunsTab() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["records", "runs"], queryFn: () => researchApi.list(undefined, 50) });
  const [res, setRes] = useState<Record<string, ReproduceResult>>({});
  const repro = useMutation({
    mutationFn: (id: string) => researchApi.reproduce(id, false),
    onSuccess: (r, id) => setRes((m) => ({ ...m, [id]: r })),
  });
  const del = useMutation({ mutationFn: (id: string) => researchApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["records", "runs"] }) });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <Failed what="연구 기록" err={q.error} />;
  if (q.data && !q.data.available) return <p className="pg-warn">{q.data.reason ?? "연구 기록 저장소를 읽을 수 없어요 — 기록이 없는 것과 달라요."}</p>;
  const list = q.data?.runs ?? [];
  if (list.length === 0) return <p className="pg-help">연구 기록이 없어요 — ‘비중 계산’ 노드의 ‘연구 기록 남기기’로 남겨요.</p>;
  return (
    <ul className="pg-rec-list">{list.map((r) => {
      const cov = r.snapshot?.coverage;
      return (
        <li key={r.run_id} className="pg-rec-item" data-run={r.run_id}>
          <div className="pg-rec-row"><b className="pg-rec-name">{r.name ?? r.kind}</b><span className="pg-tag pg-tag--unknown">{r.kind}</span></div>
          <p className="pg-pick-sub">{when(r.created_at)} · {r.run_id}{cov?.start ? ` · 데이터 ${cov.start} ~ ${cov.end ?? "미상"}` : " · 데이터 기간 기록 없음"}</p>
          <div className="pg-rec-actions">
            <button type="button" className="pg-btn" disabled={repro.isPending && repro.variables === r.run_id}
                    onClick={() => repro.mutate(r.run_id)}>다시 계산해 대조</button>
            <button type="button" className="pg-btn" aria-label={`${r.run_id} 삭제`} disabled={del.isPending}
                    onClick={() => { if (window.confirm("이 연구 기록을 지울까요? 되돌릴 수 없어요.")) del.mutate(r.run_id); }}>지우기</button>
          </div>
          {res[r.run_id] && <Verdict r={res[r.run_id]} />}
          {repro.isError && repro.variables === r.run_id && (
            <p className="pg-field-err pg-rec-verdict" data-verdict="network">응답을 받지 못했어요 — 재현이 실패한 것과 달라요. 연결을 확인하고 다시 눌러 주세요. ({(repro.error as Error).message})</p>
          )}
        </li>
      );
    })}</ul>
  );
}

function TargetsTab() {
  const q = useQuery({ queryKey: ["target-versions"], queryFn: () => targetVersionApi.list() });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <Failed what="실행 목표" err={q.error} />;
  if (q.data && !q.data.available) return <p className="pg-warn">{q.data.reason}</p>;
  const list = q.data?.versions ?? [];
  if (list.length === 0) return <p className="pg-help">실행 목표가 없어요 — ‘실행 목표 만들기’ 노드에서 저장해요.</p>;
  return (
    <ul className="pg-rec-list">{list.map((t) => (
      <li key={t.tpv_id ?? ""} className="pg-rec-item" data-tpv={t.tpv_id}>
        <div className="pg-rec-row">
          <b className="pg-rec-name">{Object.keys(t.final_weights).length}종목</b>
          <span className={`pg-tag pg-tag--${t.status === "executable" ? "confirmed" : "assumed"}`}>{t.status === "executable" ? "실행 가능" : "연구용"}</span>
        </div>
        <p className="pg-pick-sub">{t.created_at ? when(t.created_at) : "시각 미상"} · {t.tpv_id}
          {t.cash_weight == null ? " · 현금 비중 없음(롱숏)" : ` · 현금 ${t.cash_weight.toFixed(1)}%`}</p>
        {t.status_reason && <p className="pg-rec-text">{t.status_reason}</p>}
      </li>
    ))}</ul>
  );
}

function SnapshotsTab() {
  const qc = useQueryClient();
  const [market, setMarket] = useState<"kr" | "us">("kr");
  // ★regimeSnapshotApi.list 는 실패를 빈 목록으로 돌려준다★ — 여기서는 두 사실을 가르려고 직접 읽는다.
  const q = useQuery({ queryKey: ["records", "snapshots"], queryFn: () => regimeSnapshotApi.listStrict(30) });
  const make = useMutation({ mutationFn: () => regimeSnapshotApi.createFromCurrent(market),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["records", "snapshots"] }) });
  return (
    <>
      <div className="pg-rec-row pg-rec-make">
        <select className="pg-field-input" aria-label="시장" value={market} onChange={(e) => setMarket(e.target.value as "kr" | "us")}>
          <option value="kr">한국</option><option value="us">미국</option>
        </select>
        <button type="button" className="pg-btn pg-btn--primary" disabled={make.isPending} onClick={() => make.mutate()}>
          {make.isPending ? "만드는 중" : "지금 국면으로 스냅샷 만들기"}
        </button>
      </div>
      <p className="pg-note">지금 수집한 값으로 만든 스냅샷은 앞으로의 연구에만 써요 — 과거 백테스트에는 쓸 수 없어요(빈티지 미상).</p>
      {make.isError && <p className="pg-field-err" role="alert">만들지 못했어요 — {(make.error as Error).message}</p>}
      {make.data && (make.data.recorded
        ? <p className="pg-save-msg" role="status">스냅샷을 만들었어요 · {make.data.snapshot_id}</p>
        : <p className="pg-warn" role="status">저장하지 않았어요 — {make.data.message ?? "사유 미상"}</p>)}
      {q.isLoading && <Loading />}
      {q.isError && <Failed what="국면 스냅샷" err={q.error} />}
      {q.data && q.data.length === 0 && <p className="pg-help">스냅샷이 없어요 — 위 버튼으로 지금 국면을 굳혀 두면 ‘경기 국면’ 노드가 읽어요.</p>}
      {q.data && q.data.length > 0 && (
        <ul className="pg-rec-list">{q.data.map((s) => (
          <li key={s.snapshot_id} className="pg-rec-item" data-snapshot={s.snapshot_id}>
            <div className="pg-rec-row"><b className="pg-rec-name">{s.regime ?? "국면 미상"}</b>
              <span className="pg-tag pg-tag--unknown">{USAGE_LABEL[s.research_usage] ?? "쓰임 미상"}</span></div>
            <p className="pg-pick-sub">기준일 {s.as_of ?? "미상"} · {s.snapshot_id}</p>
          </li>
        ))}</ul>
      )}
    </>
  );
}

export function RecordsSheetBody() {
  const [tab, setTab] = useState<Tab>("journal");
  return (
    <>
      <div className="pg-chips" role="tablist" aria-label="기록함">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
                  className={`pg-chip${tab === t.id ? " on" : ""}`} onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>
      <div role="tabpanel" aria-label={TABS.find((t) => t.id === tab)?.label}>
        {tab === "journal" && <JournalTab />}
        {tab === "runs" && <RunsTab />}
        {tab === "targets" && <TargetsTab />}
        {tab === "snapshots" && <SnapshotsTab />}
      </div>
    </>
  );
}
