"use client";
/**
 * 고객 칩 (CF 3부 PB3) — 고객 문서를 연 캔버스의 도구줄: 누구의 무슨 문서인지 · 저장 상태 · '고객 문서에 저장'.
 * ==========================================================================
 * ★저장은 서버뿐이다★(`/pb/clients/…/docs`) — 이 탭의 작업 중 문서와 섞지 않는다(`clientMode`). 저장 기준은 '연 순간의 문서' —
 * 캔버스가 이 문서를 실은 뒤(`loadSeq` 가 오른 뒤)의 모양이다. 고친 것이 있는 채로 탭을 닫으면 브라우저가 묻는다.
 * 보관한 고객은 읽기만 — 단추가 꺼지고 그렇다고 말한다. 저장 실패는 서버 사유 그대로(캔버스 안내 줄 — 칩은 짧게 '저장 못 함').
 * ★도구줄을 두 줄로 밀지 않게 짧게★ — 별칭 · 짧은 상태 · '저장'. 문서 이름은 넓은 화면에서만 보이고, 긴 문장은 title 로.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { createDoc, saveDoc } from "@/entities/pb-client";
import { docOf } from "./canvasDoc";
import { forgetClientDoc, type ClientDocCtx } from "./clientMode";
import { usePortfolioGraph } from "./store";

const hhmm = (d = new Date()) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

export function ClientDocChip({ ctx }: { ctx: ClientDocCtx }) {
  const nodes = usePortfolioGraph((s) => s.nodes);
  const edges = usePortfolioGraph((s) => s.edges);
  const name = usePortfolioGraph((s) => s.name);
  const goal = usePortfolioGraph((s) => s.goal);
  const groups = usePortfolioGraph((s) => s.groups);
  const branches = usePortfolioGraph((s) => s.branches);
  const pinned = usePortfolioGraph((s) => s.pinned);
  const folded = usePortfolioGraph((s) => s.folded);
  const loadSeq = usePortfolioGraph((s) => s.loadSeq);
  const json = useMemo(() => JSON.stringify(docOf({ nodes, edges, name, goal, groups, branches, pinned, folded })),
    [nodes, edges, name, goal, groups, branches, pinned, folded]);

  const seq0 = useRef<number | null>(null);
  const [docId, setDocId] = useState(ctx.docId);
  const [base, setBase] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  // 칩이 뜬 때의 횟수 — 그 뒤 처음 불러온 문서가 이 고객 문서다(그 전 캔버스는 기준이 아니다).
  useEffect(() => { seq0.current = usePortfolioGraph.getState().loadSeq; }, []);
  useEffect(() => {
    if (base === null && docId && seq0.current !== null && loadSeq > seq0.current) setBase(json);
  }, [base, docId, loadSeq, json]);
  // 고객 모드를 떠나면 캔버스를 비운다 — 일반 캔버스가 이 탭의 작업 중 문서를 다시 싣는다.
  useEffect(() => () => forgetClientDoc(), []);

  const dirty = !docId || (base !== null && json !== base);
  useEffect(() => {
    if (!dirty || ctx.archived) return;
    const ask = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [dirty, ctx.archived]);

  async function save() {
    setSaving(true);
    setErr(null);
    const graph = JSON.parse(json);
    const r = docId ? await saveDoc(ctx.clientId, docId, graph) : await createDoc(ctx.clientId, ctx.name, graph);
    setSaving(false);
    if (!r.ok) {
      setErr(r.error);
      usePortfolioGraph.getState().setNote(`고객 문서를 저장하지 못했어요 — ${r.error}`);
      return;
    }
    if (!docId) {
      setDocId(r.value.doc_id);
      window.history.replaceState(null, "",
        `/allocation?client=${encodeURIComponent(ctx.clientId)}&doc=${encodeURIComponent(r.value.doc_id)}`);
    }
    setBase(json);
    setSavedAt(hhmm());
  }

  // [상태, 칩에 보이는 짧은 말, 긴 문장(title)]
  const state = ctx.archived ? ["archived", "보관 · 읽기만", "보관한 고객이라 읽기만 해요 — 고객 화면에서 다시 꺼내면 저장할 수 있어요."]
    : err ? ["error", "저장 못 함", `저장하지 못했어요 — ${err}`]
    : saving ? ["saving", "저장 중", "저장하는 중이에요."]
    : !docId ? ["new", "저장 전", "아직 고객 문서로 저장하지 않았어요 — 이 탭의 작업 중 문서에도 남지 않아요."]
    : dirty ? ["dirty", "고친 것 있음", "저장한 뒤 고친 것이 있어요."]
    : ["saved", savedAt ? `저장함 · ${savedAt}` : "저장함", "고객 문서에 저장한 그대로예요."];

  return (
    <div className="pg-client-chip" role="group" aria-label={`고객 문서 — ${ctx.alias} · ${ctx.name}`} data-state={state[0]}>
      <a className="pg-client-who" href={`/clients?client=${encodeURIComponent(ctx.clientId)}`} title={`${ctx.alias} · ${ctx.name} — 고객 화면으로`}>
        <b>{ctx.alias}</b><span className="pg-client-doc">{ctx.name}</span>
      </a>
      <span className="pg-client-state" role="status" title={state[2]}>{state[1]}</span>
      <button type="button" className="pg-btn pg-client-save" onClick={() => void save()} aria-label="고객 문서에 저장" title="고객 문서에 저장"
              disabled={ctx.archived || saving || (!!docId && !dirty)}>
        저장
      </button>
    </div>
  );
}
