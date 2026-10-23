"use client";
/**
 * 노드·선에게 묻기(AI3) — ★오른쪽 창 아래에 붙은 칸★(사용자가 UI/UX 판단을 맡김 2026-10-23: 새 탭이 아니다 — 묻고 답을 읽는 동안
 * 그 결과가 그대로 보이고, 탭이 여섯이 되지 않는다). 노드나 선을 고르면 한 줄로 보이고, 답이 있으면 창 높이의 절반까지 자란다.
 *  · 계산한 뒤에만(사용자 결정) — 계산 전·낡음이면 안내 + [여기까지 계산] · 로그아웃이면 로그인 링크(요청 0) · 누를 때만 묻는다.
 *  · 보내는 것 = 대상 · 질문 · ★직전 문답 하나★(사용자 결정) · 낡지 않은 결과의 설명·봉인 + 전달 점검 기록·봉인(`/run` 그대로 — 범위는 서버가 고른다).
 *  · 답: 문장마다 사실 칩(번호 + 이름 · 부분) — ★누르면 그 자리에서 원문을 펼친다★(근거 확인에 화면을 옮기지 않는다) + [그 노드로]/[그 선으로].
 *  · 답할 수 없으면 서버 고정 문장(`cannot`) · 연습용 경고는 서버가 붙인 것만(`notice`) · 못 보임 사유 · 빠진 문장·확인 못 한 결과는 수와 첫 사유.
 *  · 문답은 대상마다 이번 방문 동안 남는다(최근 5) · 물을 때의 범위 안 (id, 봉인) 묶음이 바뀌면 그 대상의 문답을 지우고 그렇게 말한다.
 *  · 머리 줄과 입력은 칸 안에 고정되고 문답만 스크롤한다(PNG 검토에서 찾음 — 칸 전체가 스크롤되면 입력이 밀려 사라졌다).
 *    자주 묻는 질문 칩은 첫 질문 전에만 · 같은 연습용 경고는 바뀔 때만 다시 보인다.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { askScope, portfolioGraphApi, type AskAnswer, type AskFactRef, type AskRecord, type AskTarget, type AssistAsk,
         type GraphDoc, type NarrateFact, type NodeRunResult, type RunReport } from "@/entities/portfolio-graph";
import type { Session } from "@/entities/session";

const KEEP = 5;
const MAX_PREV = 1200;
const PRESETS: Record<AskTarget["kind"], string[]> = {
  node: ["이 결과는 어디서 왔나요?", "무엇을 재지 않았나요?", "이 결과를 믿어도 되나요?"],
  edge: ["무엇이 건너가나요?", "빠지거나 바뀐 것이 있나요?"],
};
/** 여러 줄이 있는 부분 — 칩에 몇 번째인지 붙인다. */
const LISTY = new Set(["사실", "믿음", "재지 않은 것", "건너간 것", "빠지거나 바뀐 것"]);

type Turn =
  | { q: string; state: "loading" }
  | { q: string; state: "ready"; answer: AskAnswer; facts: Record<string, AskFactRef>; notice: string | null; note: string | null }
  | { q: string; state: "failed"; note: string };
interface Thread { basis: string; turns: Turn[]; stale: boolean }

const keyOf = (t: AskTarget) => `${t.kind}:${t.id}`;

/** 받은 답을 한 줄로 — 문장 없음 · 검사에서 빠진 문장 · 확인 못 한 결과. 말할 것이 없으면 null. */
export function askNote(res: Extract<AssistAsk, { available: true }>): string | null {
  const parts: string[] = [];
  if (res.answer.answerable && !res.answer.sentences.length) parts.push("AI 가 쓴 문장이 없어요");
  if (res.rejected.length) parts.push(`${res.rejected.length}문장은 검사에서 빠졌어요: ${res.rejected[0].reason}`);
  if (res.dropped.length) parts.push(`${res.dropped.length}개 결과는 확인하지 못해 뺐어요: ${res.dropped[0].reason}`);
  return parts.length ? parts.join(" · ") : null;
}

/** 직전 문답 — 다음 질문에 하나만 함께 보낸다(답 = 통과한 문장들, 답할 수 없었으면 고정 문장부터). */
function previousOf(turns: Turn[]): { question: string; answer: string } | null {
  const last = [...turns].reverse().find((t): t is Extract<Turn, { state: "ready" }> => t.state === "ready");
  if (!last) return null;
  const said = [...(last.answer.cannot ? [last.answer.cannot] : []), ...last.answer.sentences.map((s) => s.text)].join(" ");
  return { question: last.q, answer: said.slice(0, MAX_PREV) };
}

export function useAiQuestion(doc: GraphDoc, order: string[], report: RunReport | null, staleIds: ReadonlySet<string>,
                              session: Session, target: AskTarget | null) {
  const facts = useMemo<NarrateFact[]>(() => order.flatMap((id) => {
    const r: NodeRunResult | undefined = report?.nodes[id];
    return r?.explain && r.explain_sig && !staleIds.has(id) ? [{ node_id: id, explain: r.explain, sig: r.explain_sig }] : [];
  }), [order, report, staleIds]);
  const records = useMemo<AskRecord[]>(() => Object.entries(report?.edges ?? {}).flatMap(([eid, rec]) => {
    if (!rec.sig || staleIds.has(rec.target)) return [];
    const { sig, ...rest } = rec;
    return [{ edge_id: eid, record: rest, sig }];
  }), [report, staleIds]);
  const graphEdges = useMemo(() => doc.edges.map((e) => ({ id: e.id, source: e.source, target: e.target })), [doc.edges]);
  const nodeIds = useMemo(() => doc.nodes.map((x) => x.id), [doc.nodes]);
  const scope = useMemo(() => (target ? askScope(target, nodeIds, graphEdges) : null), [target, nodeIds, graphEdges]);
  /** 범위 안 (id, 봉인) 묶음 — 문답이 기댄 결과. 이것이 바뀌면 그 대상의 문답은 낡았다. */
  const basisOf = useCallback((sc: ReturnType<typeof askScope>) => !sc ? "" : JSON.stringify([
    facts.filter((f) => sc.nodes.has(f.node_id)).map((f) => [f.node_id, f.sig]),
    records.filter((r) => sc.edges.has(r.edge_id)).map((r) => [r.edge_id, r.sig]).sort()]), [facts, records]);
  const basis = basisOf(scope);
  const ready = !!target && (target.kind === "node" ? facts.some((f) => f.node_id === target.id) : records.some((r) => r.edge_id === target.id));
  const [threads, setThreads] = useState<Record<string, Thread>>({});
  const key = target ? keyOf(target) : "";
  const live = useRef({ doc, facts, records, session, basis, key, target, threads, ready });
  live.current = { doc, facts, records, session, basis, key, target, threads, ready };

  useEffect(() => {
    if (!key) return;
    setThreads((all) => {
      const th = all[key];
      if (!th || th.basis === basis) return all;
      return { ...all, [key]: { basis, turns: [], stale: th.turns.length > 0 || th.stale } };
    });
  }, [key, basis]);

  const ask = useCallback(async (question: string) => {
    const now = live.current;
    const q = question.trim();
    if (!q || !now.target || !now.ready || now.session.kind !== "signed_in") return;
    const th = now.threads[now.key];
    if (th?.turns.some((t) => t.state === "loading")) return;
    const k = now.key, asked = now.basis, tgt = now.target;
    const prev = th && th.basis === asked ? previousOf(th.turns) : null;
    setThreads((all) => {
      const old = all[k] && all[k].basis === asked ? all[k].turns : [];
      return { ...all, [k]: { basis: asked, turns: [...old, { q, state: "loading" as const }].slice(-KEEP), stale: false } };
    });
    const res = await portfolioGraphApi.assistAsk(now.doc, tgt, q, prev, now.facts, now.records);
    setThreads((all) => {
      const cur = all[k];
      if (!cur || cur.basis !== asked) return all;                                   // 묻는 사이에 결과가 바뀌었다 — 버린다(지움은 위 효과가 말한다)
      const turn: Turn = res.available
        ? { q, state: "ready", answer: res.answer, facts: res.facts, notice: res.notice, note: askNote(res) }
        : { q, state: "failed", note: `AI 답을 보여 줄 수 없어요: ${res.reason}` };
      const turns = cur.turns.map((t) => (t.state === "loading" && t.q === q ? turn : t));
      return { ...all, [k]: { ...cur, turns } };
    });
  }, []);

  const thread = key ? threads[key] : undefined;
  const busy = !!thread?.turns.some((t) => t.state === "loading");
  const ends = useCallback((id: string) => graphEdges.find((e) => e.id === id) ?? null, [graphEdges]);
  return { ask, thread: thread && thread.basis === basis ? thread : thread ? { ...thread, turns: [] } : undefined, ready, busy, scope, ends };
}

export function AiQuestion({ q, session, target, badge, onRunTo, onGotoNode, onGotoEdge, focusRef }: {
  q: ReturnType<typeof useAiQuestion>;
  session: Session;
  target: AskTarget & { source?: string; targetNode?: string };
  /** 화면 번호와 쉬운 이름 — 칩·머리 줄이 캔버스·이야기 번호와 같은 말을 한다. */
  badge: (id: string) => { num: number | null; name: string };
  onRunTo: (nodeId: string) => void;
  onGotoNode: (id: string) => void;
  onGotoEdge: (id: string) => void;
  focusRef: MutableRefObject<() => void>;
}) {
  const { ask, thread, ready, busy, scope, ends } = q;
  const [text, setText] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const turnsEl = useRef<HTMLOListElement>(null);
  focusRef.current = () => area.current?.focus();
  const tkey = keyOf(target);
  useEffect(() => { setOpen(null); }, [tkey]);
  const nTurns = thread?.turns.length ?? 0;
  const lastState = thread?.turns[nTurns - 1]?.state;
  useEffect(() => { turnsEl.current?.lastElementChild?.scrollIntoView?.({ block: "nearest" }); }, [nTurns, lastState]);

  const num = (id: string) => badge(id).num;
  const Num = ({ id }: { id: string }) => <b className="pg-ask-num">{num(id) ?? "?"}</b>;
  const head = target.kind === "node"
    ? <><Num id={target.id} /> {badge(target.id).name}에게 묻기</>
    : <><Num id={target.source!} /> {badge(target.source!).name} → <Num id={target.targetNode!} /> {badge(target.targetNode!).name} 선에게 묻기</>;
  const reach = scope ? [scope.up ? `위쪽 ${scope.up}` : "", scope.down ? `아래 ${scope.down}` : ""].filter(Boolean).join(" · ") : "";
  const scopeText = !scope ? null : target.kind === "node"
    ? `이 노드${reach ? `와 ${reach}` : ""}의 계산 설명으로 답해요`
    : `이 선과 양끝${reach ? ` · ${reach}` : ""}의 계산 설명으로 답해요`;
  const chipText = (f: AskFactRef) => {
    const part = `${f.part}${LISTY.has(f.part) ? ` ${f.index + 1}` : ""}`;
    if (f.target_kind === "node") return { n: `${num(f.target_id) ?? "?"}`, rest: `${badge(f.target_id).name} · ${part}` };
    const e = ends(f.target_id);
    return { n: `${(e && num(e.source)) ?? "?"}→${(e && num(e.target)) ?? "?"}`, rest: `선 · ${part}` };
  };
  /** 바로 앞 답의 연습용 경고 — 같은 경고를 답마다 되풀이하지 않는다(달라지면 다시 보인다). */
  const noticeBefore = (ti: number) => {
    const prev = thread?.turns.slice(0, ti).reverse().find((t) => t.state === "ready");
    return prev && prev.state === "ready" ? prev.notice : null;
  };
  const submit = (question: string) => {
    if (!question.trim() || busy) return;
    void ask(question);
    setText("");
  };

  let composer;
  if (session.kind === "loading") composer = null;
  else if (session.kind === "signed_out") {
    composer = <Link href="/login" className="pg-ask-login">로그인하면 AI 에게 물을 수 있어요</Link>;
  } else if (!ready) {
    composer = (
      <div className="pg-ask-waitrow">
        <p className="pg-ask-wait">계산한 뒤에 물을 수 있어요</p>
        <button type="button" className="pg-btn pg-ask-run"
                onClick={() => onRunTo(target.kind === "node" ? target.id : target.targetNode!)}>여기까지 계산</button>
      </div>
    );
  } else {
    composer = (
      <>
        {!text && !busy && !nTurns && (
          <div className="pg-ask-presets" aria-label="자주 묻는 질문">
            {PRESETS[target.kind].map((p) => (
              <button key={p} type="button" className="pg-ask-preset" onClick={() => submit(p)}>{p}</button>
            ))}
          </div>
        )}
        <div className="pg-ask-input">
          <textarea ref={area} className="pg-ask-text" rows={1} maxLength={300} value={text} disabled={busy}
                    aria-label={target.kind === "node" ? `${badge(target.id).name}에게 물을 말` : "이 선에게 물을 말"}
                    placeholder="계산 결과에 대해 물어보세요"
                    onChange={(ev) => setText(ev.target.value)}
                    onKeyDown={(ev) => {
                      if (ev.key === "Escape") { ev.stopPropagation(); ev.currentTarget.blur(); return; }
                      if (ev.key === "Enter" && !ev.shiftKey && !ev.nativeEvent.isComposing) { ev.preventDefault(); submit(text); }
                    }} />
          <button type="button" className="pg-ask-send" disabled={busy || !text.trim()} aria-busy={busy || undefined}
                  onClick={() => submit(text)}>{busy ? "묻는 중이에요" : "묻기"}</button>
        </div>
      </>
    );
  }

  return (
    <section className="pg-ask" aria-label="AI 에게 묻기">
      <h3 className="pg-ask-to">{head}</h3>
      {scopeText && <p className="pg-ask-scope">{scopeText}</p>}
      {thread?.stale && !nTurns && <p className="pg-ask-stale" role="status">계산 결과가 바뀌어 답을 지웠어요</p>}
      {nTurns > 0 && (
        <ol className="pg-ask-turns" ref={turnsEl}>
          {thread!.turns.map((t, ti) => (
            <li key={ti} className="pg-ask-turn">
              <p className="pg-ask-q">{t.q}</p>
              {t.state === "loading" && <p className="pg-ask-wait" role="status">AI 가 답을 쓰는 중이에요</p>}
              {t.state === "ready" && (
                <>
                  {t.answer.cannot && <p className="pg-ask-cannot">{t.answer.cannot}</p>}
                  {t.answer.sentences.length > 0 && (
                    <ol className="pg-ask-sents">
                      {t.answer.sentences.map((s, si) => (
                        <li key={si} className="pg-ask-sent">
                          <span className="pg-ask-sent-text">{s.text}</span>
                          <span className="pg-ask-chips" aria-label="이 문장의 근거">
                            {s.fact_ids.map((fid) => {
                              const f = t.facts[fid];
                              if (!f) return null;
                              const c = chipText(f);
                              const k = `${ti}:${si}:${fid}`;
                              return (
                                <button key={fid} type="button" className="pg-ai-chip pg-ask-chip" aria-expanded={open === k}
                                        onClick={() => setOpen(open === k ? null : k)}>
                                  <span className="pg-ai-chip-n">{c.n}</span> {c.rest}
                                </button>
                              );
                            })}
                          </span>
                          {s.fact_ids.map((fid) => {
                            const f = t.facts[fid];
                            if (!f || open !== `${ti}:${si}:${fid}`) return null;
                            return (
                              <div key={fid} className="pg-ask-fact">
                                <p className="pg-ask-fact-text">{f.text}</p>
                                <button type="button" className="pg-ask-goto"
                                        onClick={() => (f.target_kind === "node" ? onGotoNode(f.target_id) : onGotoEdge(f.target_id))}>
                                  {f.target_kind === "node" ? "그 노드로" : "그 선으로"}
                                </button>
                              </div>
                            );
                          })}
                        </li>
                      ))}
                    </ol>
                  )}
                  {t.notice && t.notice !== noticeBefore(ti) && <p className="pg-ask-notice" role="note">{t.notice}</p>}
                  {t.note && <p className="pg-ask-note" role="status">{t.note}</p>}
                </>
              )}
              {t.state === "failed" && <p className="pg-ask-note" role="status">{t.note}</p>}
            </li>
          ))}
        </ol>
      )}
      {composer}
    </section>
  );
}
