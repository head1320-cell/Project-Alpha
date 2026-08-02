"use client";
// Decision-Quality Journal (Full Expansion P5) — 서버 영속 의사결정 저널.
//   지시서: "저널은 메모장이 아니라 의사결정 품질 DB." 각 항목이 run_id에 연결되고
//   Attribution 스냅샷을 첨부(같은 run_id). 필수 기록(테제·반론·결정·이유·원인·다음
//   실험·사후회고) + "결과 vs 결정" 자기평가. review는 결과가 나온 뒤 편집.
import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { attributionApi, type DecisionQuality, type JournalEntry } from "@/entities/attribution/api";
import { useAllocation } from "./AllocationProvider";
import { researchApi } from "@/entities/research/api";
import { EvidenceBadge } from "@/shared/ui/evidence";

const DQ_KO: Record<DecisionQuality, string> = {
  good_outcome_good_process: "결과◎ 결정◎", good_outcome_bad_process: "결과◎ 결정✗ (운)",
  bad_outcome_good_process: "결과✗ 결정◎ (불운)", bad_outcome_bad_process: "결과✗ 결정✗", too_early: "판단 이르름",
};

function ReviewRow({ entry, onSaved }: { entry: JournalEntry; onSaved: () => void }) {
  const [review, setReview] = useState(entry.review || "");
  const [dq, setDq] = useState<DecisionQuality | "">(entry.decision_quality || "");
  const [editing, setEditing] = useState(false);
  const mut = useMutation({
    mutationFn: () => attributionApi.reviewJournal(entry.entry_id, review.trim(), (dq || undefined) as DecisionQuality | undefined),
    onSuccess: () => { setEditing(false); onSaved(); },
  });
  if (!editing) {
    return (
      <div className="as-jr-review">
        <em>사후 회고 / 의사결정 품질</em>
        {entry.review ? <p>{entry.review}</p> : <p className="as-note">미작성 — 결과가 나온 뒤 실제와 대조해 기록.</p>}
        {entry.decision_quality && <span className={`as-dq ${entry.decision_quality}`}>{DQ_KO[entry.decision_quality]}</span>}
        <button className="as-chip sm" onClick={() => setEditing(true)}>{entry.review ? "수정" : "작성"}</button>
      </div>
    );
  }
  return (
    <div className="as-jr-review">
      <em>사후 회고 / 의사결정 품질</em>
      <textarea className="as-input" rows={2} value={review} onChange={(e) => setReview(e.target.value)}
        placeholder="예: 3개월 후 실제 +8%p — 방향 적중, 신뢰도는 과소했음" />
      <select className="as-input" value={dq} onChange={(e) => setDq(e.target.value as DecisionQuality)}>
        <option value="">— 의사결정 품질 —</option>
        {(Object.keys(DQ_KO) as DecisionQuality[]).map((k) => <option key={k} value={k}>{DQ_KO[k]}</option>)}
      </select>
      <div className="as-wl-row">
        <button className="as-chip on" disabled={mut.isPending} onClick={() => mut.mutate()}>저장</button>
        <button className="as-chip" onClick={() => setEditing(false)}>취소</button>
      </div>
    </div>
  );
}

export function DecisionJournal() {
  const { activeRunId, result } = useAllocation();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [thesis, setThesis] = useState("");
  const [counter, setCounter] = useState("");
  const [decision, setDecision] = useState("");
  const [nextExp, setNextExp] = useState("");

  const listQ = useQuery({ queryKey: ["allocation", "journal", "server"], queryFn: () => attributionApi.listJournal().catch(() => null) });
  const entries = listQ.data?.entries ?? [];

  // ★신원 사슬을 요청 한 번으로 잇는다★ (P9)
  // 저널 항목이 저장하는 것은 run_id 뿐이다 — 스냅샷·룰셋 버전·팩 해시는 **런 쪽**에 있다.
  // 행마다 researchApi.get() 을 부르면 N+1 이 되므로 목록을 한 번 받아 조인한다.
  // 목록 응답은 inputs/outputs 를 빼고 오므로(research_runs.py::list_runs) 여기서 얻는 것은
  // 데이터 출처와 코드 버전까지다. 그 이상은 **지어내지 않고** 런을 열어야 한다고 적는다.
  const runsQ = useQuery({
    queryKey: ["research-runs", "journal-chain"],
    queryFn: () => researchApi.list(undefined, 50),
    staleTime: 30_000,
  });
  const runById = new Map((runsQ.data?.runs ?? []).map((r) => [r.run_id, r]));

  const createMut = useMutation({
    mutationFn: () => attributionApi.createJournal({
      title: title.trim() || "의사결정 기록", run_id: activeRunId,
      record: { thesis, counter_arguments: counter, decision, next_experiment: nextExp },
      attach_attribution: true,
    }),
    onSuccess: () => {
      setTitle(""); setThesis(""); setCounter(""); setDecision(""); setNextExp("");
      qc.invalidateQueries({ queryKey: ["allocation", "journal", "server"] });
    },
  });

  const delMut = useMutation({
    mutationFn: (id: string) => attributionApi.deleteJournal(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["allocation", "journal", "server"] }),
  });

  return (
    <section className="as-card">
      <div className="as-card-title">DECISION JOURNAL <span className="as-note-inline">run_id 연결 · Attribution 첨부 · 서버 영속</span></div>

      <div className="as-dj-form">
        <div className="as-dj-runrow">
          {activeRunId
            ? <span className="as-dj-run num">연결 런: {activeRunId}</span>
            : <span className="as-note">런 미기록 — 07 ATTRIBUTION에서 결정을 런으로 기록하면 Attribution이 자동 첨부됩니다(미기록도 저장 가능).</span>}
        </div>
        <input className="as-input" placeholder="제목 — 예: AI Capex 사이클 1차 결정" value={title} onChange={(e) => setTitle(e.target.value)} />
        <textarea className="as-input" rows={2} placeholder="테제(그 시점의 논거)" value={thesis} onChange={(e) => setThesis(e.target.value)} />
        <textarea className="as-input" rows={2} placeholder="핵심 반론(counter-arguments)" value={counter} onChange={(e) => setCounter(e.target.value)} />
        <input className="as-input" placeholder="내린 결정(decision)" value={decision} onChange={(e) => setDecision(e.target.value)} />
        <input className="as-input" placeholder="다음 실험(next experiment)" value={nextExp} onChange={(e) => setNextExp(e.target.value)} />
        <button className="as-run" disabled={createMut.isPending || !result} onClick={() => createMut.mutate()}>
          {createMut.isPending ? "저장 중…" : "의사결정 저널 저장"}
        </button>
        {createMut.isSuccess && createMut.data && !createMut.data.saved && <div className="as-note">DB 미가용 — 저장되지 않음(정직).</div>}
        {!result && <div className="as-note">Re-optimize 후 저장 가능(결과 스냅샷 연결).</div>}
      </div>

      <div className="as-dj-list">
        {entries.length === 0 ? <div className="as-empty">서버 저장 저널 없음.</div> : entries.map((e) => (
          <div key={e.entry_id} className="as-jr-entry">
            <div className="as-jr-head">
              <b>{e.title}</b>
              <span className="num as-note-inline">
                {new Date(e.created_at * 1000).toLocaleString("ko-KR").slice(0, 17)}
                {e.attribution ? " · Attribution✔" : ""}
              </span>
              <button className="as-x" title="삭제" onClick={() => delMut.mutate(e.entry_id)}>×</button>
            </div>

            {/* ★재현 사슬 — 결정 → 런 → 스냅샷 → 코드★
                run_id 가 없는 항목은 재현 좌표가 없다. 그것은 사소한 누락이 아니라
                "이 결정은 나중에 검증할 수 없다" 는 뜻이므로 경고로 적는다. */}
            <div className="as-dj-chain">
              {e.run_id ? (() => {
                const r = runById.get(e.run_id);
                const src = r?.snapshot?.coverage?.source;
                return (
                  <>
                    <span className="as-dj-link"><em>런</em><b className="num">{e.run_id}</b></span>
                    <span className="as-dj-arrow">→</span>
                    <span className="as-dj-link"><em>데이터</em>
                      <b className="num">{src === "mock" ? "합성(mock)" : src === "real" ? "실데이터" : "미기록"}</b></span>
                    <span className="as-dj-arrow">→</span>
                    <span className="as-dj-link"><em>코드</em><b className="num">{r?.code_version ?? "미기록"}</b></span>
                    {!r && (
                      <EvidenceBadge kind="caution" reason="최근 50건 목록에서 이 런을 찾지 못했습니다 — 삭제되었거나 더 오래된 런일 수 있습니다.">
                        런 조회 불가
                      </EvidenceBadge>
                    )}
                    {/* 룰셋 버전·시나리오 팩 해시는 런의 inputs 에 있고 목록 응답에는 없다.
                        여기서 채워 넣지 않고 어디서 볼 수 있는지만 말한다. */}
                    <span className="as-dj-more">룰셋 버전·팩 해시는 이 런을 열면 보입니다</span>
                  </>
                );
              })() : (
                <EvidenceBadge kind="caution" reason="이 결정에는 연결된 런이 없어 입력·스냅샷·코드 버전을 되짚을 수 없습니다. 재현·귀인이 성립하지 않습니다.">
                  재현 좌표 없음
                </EvidenceBadge>
              )}
            </div>
            <div className="as-jr-grid">
              <div><em>테제</em><p>{e.record?.thesis || "—"}</p></div>
              <div><em>반론</em><p>{e.record?.counter_arguments || "—"}</p></div>
              <div><em>결정</em><p>{e.record?.decision || "—"}</p></div>
              <div><em>다음 실험</em><p>{e.record?.next_experiment || "—"}</p></div>
            </div>
            {e.attribution && (
              <div className="as-dj-attr num">
                Attribution: 실현 {e.attribution.returns.portfolio_pct ?? "—"}% · 초과 {e.attribution.returns.excess_pct ?? "—"}%
                {" "}({e.attribution.coverage.has_expost ? "사후 실측" : "사후 데이터 없음"})
              </div>
            )}
            <ReviewRow entry={e} onSaved={() => qc.invalidateQueries({ queryKey: ["allocation", "journal", "server"] })} />
          </div>
        ))}
      </div>
    </section>
  );
}
