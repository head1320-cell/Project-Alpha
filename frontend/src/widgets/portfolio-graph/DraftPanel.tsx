"use client";
/**
 * 말로 설계(AI4) — 왼쪽 창 셋째 탭 '말로'(사용자 결정 2026-10-23: 왼쪽 창 새 탭 + 캔버스 유령 · 모자라면 비워 두고 말하기).
 * ==========================================================================
 *  · 말씀 → 서버 초안(`/assist/canvas/draft`) — 지금 캔버스에 노드 더하기 · 선 잇기 · 말한 값 넣기만. ★값은 서버가 말씀 조각에서 읽었다★.
 *  · ★바뀐 점★ 묶음: 더할 노드 · 이을 선 · 넣을 값(+ '말씀에서 ‘…’' 칩) · 비어 있는 것("말씀에 없어요") · 빠진 것(사유) — 캔버스에는 같은 초안이 점선 유령(`DraftLayer`).
 *  · [받아들이기]만 반영한다(되돌리기 한 번 — `store.applyDraft`) · [버리기] · 이해 못 함·투자 판단은 서버 고정 문장(받아들일 것 없음).
 *  · 초안은 보낸 때의 문서(노드·선·설정 — 위치는 아님)에 기댄다. 바뀌면 지우고 그렇게 말한다(★바 안의 상태 줄★이 아니라 이 칸의 상태 줄).
 *  · 로그아웃이면 로그인 링크(요청 0) · 누를 때만 부른다.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import { draftSig, portfolioGraphApi, type AssistDraft, type DraftBody, type GraphDoc, type NodeCatalogEntry } from "@/entities/portfolio-graph";
import type { Session } from "@/entities/session";
import { STAGE_VAR } from "./GraphNode";

const STALE = "캔버스가 바뀌어 초안을 지웠어요 — 다시 말해 주세요";
const MAX = 300;
/** 예시(규칙 글 — AI 글이 아니다). 누르면 칸에 채우기만 한다. */
const EXAMPLES = ["삼성전자, SK하이닉스, NAVER로 3년 기준 비중을 짜 줘", "과거로 돌려 보기를 붙이고 거래비용은 0.3%로 해 줘",
                  "위험을 많이 피하게 바꿔 줘"];

type Answer = Extract<AssistDraft, { available: true }>;
type DraftState =
  | { state: "idle"; note: string | null }
  | { state: "loading"; sig: string; sentence: string }
  | { state: "ready"; sig: string; sentence: string; res: Answer };

/** 받아들일 것이 있는 초안인가. */
export const draftHasChanges = (d: DraftBody | null) => !!d && d.add.length + d.connect.length + d.set.length > 0;

export function useDraft(doc: GraphDoc, session: Session) {
  const sig = useMemo(() => draftSig(doc), [doc]);
  const [st, setSt] = useState<DraftState>({ state: "idle", note: null });
  const live = useRef({ sig, doc, session });
  live.current = { sig, doc, session };
  useEffect(() => {
    if ((st.state === "ready" || st.state === "loading") && st.sig !== sig) setSt({ state: "idle", note: STALE });
  }, [sig, st]);

  const send = useCallback(async (sentence: string) => {
    const now = live.current;
    const words = sentence.trim();
    if (now.session.kind !== "signed_in" || !words) return;
    const asked = now.sig;
    setSt({ state: "loading", sig: asked, sentence: words });
    const res = await portfolioGraphApi.assistDraft(now.doc, words);
    if (live.current.sig !== asked) { setSt({ state: "idle", note: STALE }); return; }
    if (!res.available) { setSt({ state: "idle", note: `초안을 보여 줄 수 없어요: ${res.reason}` }); return; }
    setSt({ state: "ready", sig: asked, sentence: words, res });
  }, []);
  const clear = useCallback((note: string | null = null) => setSt({ state: "idle", note }), []);
  /** 캔버스에 보일 초안 — 이해했고 받아들일 것이 있을 때만. */
  const draft = st.state === "ready" && st.res.understood && draftHasChanges(st.res.draft) ? st.res.draft : null;
  return { st, send, clear, draft, busy: st.state === "loading" };
}

function Sec({ k, title, n, children }: { k: string; title: string; n: number; children: ReactNode }) {
  return (
    <section className="pg-say-sec" data-sec={k}>
      <h4 className="pg-say-sec-h">{title} <span className="pg-say-n">{n}</span></h4>
      <ul className="pg-say-list">{children}</ul>
    </section>
  );
}

export function DraftPanel({ d, session, catalog, plain, nameOf, kindOf: kindOfNode, onAccept, inputRef }: {
  d: ReturnType<typeof useDraft>;
  session: Session;
  catalog: NodeCatalogEntry[] | null;
  /** 포트 타입 → 쉬운 이름(서버 `port_plain`). */
  plain: Record<string, string>;
  /** 지금 노드의 이름(흐름 번호 + 쉬운 이름). */
  nameOf: (id: string) => string;
  /** 지금 노드의 종류(포트 이름을 쉬운 말로). */
  kindOf: (id: string) => string | undefined;
  onAccept: (draft: DraftBody) => void;
  inputRef?: MutableRefObject<HTMLTextAreaElement | null>;
}) {
  const { st, send, clear, busy } = d;
  const [text, setText] = useState("");
  const entryOf = (kind: string) => catalog?.find((c) => c.type === kind);
  const submit = () => {
    if (!text.trim() || busy) return;
    void send(text);
    setText("");
  };

  let composer = null;
  if (session.kind === "signed_out") {
    composer = <Link href="/login" className="pg-say-login">로그인하면 말로 설계를 쓸 수 있어요</Link>;
  } else if (session.kind === "signed_in") {
    composer = (
      <>
        {!text && st.state === "idle" && (
          <div className="pg-say-examples" aria-label="이렇게 말해 보세요">
            {EXAMPLES.map((x) => <button key={x} type="button" className="pg-say-ex" onClick={() => setText(x)}>{x}</button>)}
          </div>
        )}
        <textarea ref={inputRef} className="pg-say-text" rows={3} maxLength={MAX} value={text} disabled={busy}
                  aria-label="캔버스를 어떻게 고칠지 말하기" placeholder="예: 과거로 돌려 보기를 붙이고 5년 기준으로 해 줘"
                  onChange={(ev) => setText(ev.target.value)}
                  onKeyDown={(ev) => {
                    if (ev.key === "Escape") { ev.stopPropagation(); ev.currentTarget.blur(); return; }
                    if (ev.key === "Enter" && !ev.shiftKey && !ev.nativeEvent.isComposing) { ev.preventDefault(); submit(); }
                  }} />
        <button type="button" className="pg-say-send" disabled={busy || !text.trim()} aria-busy={busy || undefined} onClick={submit}>
          {busy ? "초안을 만드는 중" : "초안 만들기"}
        </button>
      </>
    );
  }

  let result = null;
  if (st.state === "ready") {
    const { res } = st;
    const dr = res.draft;
    const added = new Map(dr.add.map((a) => [a.id, a]));
    const name = (id: string) => (added.has(id) ? `${added.get(id)!.label}(새)` : nameOf(id));
    const portName = (target: string, port: string) => {
      const kind = added.get(target)?.kind ?? kindOfNode(target);
      const t = (kind ? entryOf(kind) : undefined)?.inputs.find((p) => p.name === port)?.type;
      return t ? plain[t] ?? port : port;
    };
    const any = draftHasChanges(dr);
    result = (
      <div className="pg-say-result">
        <p className="pg-say-sent"><span className="pg-say-k">말씀</span> {st.sentence}</p>
        {!res.understood ? <p className="pg-say-cannot">{res.cannot}</p> : (
          <>
            {dr.summary && <p className="pg-say-summary">{dr.summary}</p>}
            {dr.add.length > 0 && (
              <Sec k="add" title="더할 노드" n={dr.add.length}>
                {dr.add.map((a) => (
                  <li key={a.id} className="pg-say-item">
                    <i className="pg-say-dot" style={{ background: STAGE_VAR[entryOf(a.kind)?.stage ?? ""] ?? "var(--pg-mute)" }} aria-hidden="true" />
                    {a.label}
                  </li>
                ))}
              </Sec>
            )}
            {dr.connect.length > 0 && (
              <Sec k="connect" title="이을 선" n={dr.connect.length}>
                {dr.connect.map((c) => (
                  <li key={c.id} className="pg-say-item">{name(c.source)} → {name(c.target)} · {portName(c.target, c.target_port)}</li>
                ))}
              </Sec>
            )}
            {dr.set.length > 0 && (
              <Sec k="set" title="넣을 값" n={dr.set.length}>
                {dr.set.map((x) => (
                  <li key={`${x.node}.${x.field}`} className="pg-say-item">
                    <span className="pg-say-what">{name(x.node)} · {x.label} <b>{x.display}</b></span>
                    <span className="pg-said-chip">말씀에서 ‘{x.quote}’</span>
                  </li>
                ))}
              </Sec>
            )}
            {dr.empty.length > 0 && (
              <Sec k="empty" title="비어 있는 것" n={dr.empty.length}>
                {dr.empty.map((x, i) => <li key={i} className="pg-say-item">{x.why}</li>)}
              </Sec>
            )}
          </>
        )}
        {res.rejected.length > 0 && (
          <Sec k="rejected" title="빠진 것" n={res.rejected.length}>
            {res.rejected.map((x, i) => <li key={i} className="pg-say-item">{x.reason}</li>)}
          </Sec>
        )}
        <div className="pg-say-acts">
          {res.understood && any && (
            <button type="button" className="pg-say-accept" onClick={() => { clear(); onAccept(dr); }}>받아들이기</button>
          )}
          <button type="button" className="pg-say-discard" onClick={() => clear()}>{res.understood && any ? "버리기" : "닫기"}</button>
        </div>
      </div>
    );
  }

  return (
    <section className="pg-say" aria-label="말로 설계">
      <p className="pg-say-intro">말로 지금 캔버스를 고쳐요 — 노드를 더하고, 잇고, 말한 값을 넣어요. 받아들일 때만 바뀌어요.</p>
      {composer}
      {st.state === "idle" && st.note && <p className="pg-say-note" role="status">{st.note}</p>}
      {st.state === "loading" && <p className="pg-say-wait" role="status">초안을 만드는 중이에요</p>}
      {result}
    </section>
  );
}
