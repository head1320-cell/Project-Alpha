"use client";
/**
 * 'AI 가 풀어 쓴 글'(AI2) — 이야기 탭 맨 위. ★서버 설명을 대신하지 않는다★(아래 단계별 설명은 그대로).
 *  · 누를 때만 묻는다 · 계산 전이면 안내만 · 로그아웃이면 로그인 링크(요청 0).
 *  · 보내는 것 = 결과의 설명과 봉인(`explain_sig`) 그대로, 흐름 순서 — ★낡은 결과는 보내지 않는다★(서버도 지금 그래프로 다시 확인한다).
 *  · 문단마다 근거 칩(화면 번호 + 이름) — 누르면 그 노드. 연습용 경고는 ★서버가 붙인 것★(`notice`)만 보인다.
 *  · 못 보이면 서버 사유 그대로 · 검사에서 빠진 문단 · 확인 못 한 결과는 수와 첫 사유.
 *  · 물을 때의 (노드, 봉인) 묶음이 지금과 다르면 글을 지우고 그렇게 말한다(옮기기만 하면 그대로).
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { portfolioGraphApi, type AssistNarrate, type GraphDoc, type NarrateFact, type NodeRunResult } from "@/entities/portfolio-graph";
import type { Session } from "@/entities/session";

type Para = { text: string; node_ids: string[] };
export type AiStoryState =
  | { state: "idle"; note: string | null }
  | { state: "loading"; key: string }
  | { state: "ready"; key: string; paragraphs: Para[]; notice: string | null; note: string | null }
  | { state: "stale" };

/** 받은 답을 한 줄로 — 문단이 없음 · 검사에서 빠진 문단 · 확인 못 한 결과. 말할 것이 없으면 null. */
export function storyNote(res: Extract<AssistNarrate, { available: true }>): string | null {
  const parts: string[] = [];
  if (!res.paragraphs.length) parts.push("AI 가 쓴 문단이 없어요");
  if (res.rejected.length) parts.push(`${res.rejected.length}문단은 검사에서 빠졌어요: ${res.rejected[0].reason}`);
  if (res.dropped.length) parts.push(`${res.dropped.length}개 단계의 결과는 확인하지 못해 뺐어요: ${res.dropped[0].reason}`);
  return parts.length ? parts.join(" · ") : null;
}

export function useAiStory(doc: GraphDoc, order: string[], results: Record<string, NodeRunResult> | null,
                           staleIds: ReadonlySet<string>, session: Session) {
  const facts = useMemo<NarrateFact[]>(() => order.flatMap((id) => {
    const r = results?.[id];
    return r?.explain && r.explain_sig && !staleIds.has(id) ? [{ node_id: id, explain: r.explain, sig: r.explain_sig }] : [];
  }), [order, results, staleIds]);
  const key = useMemo(() => JSON.stringify(facts.map((f) => [f.node_id, f.sig])), [facts]);
  const [ai, setAi] = useState<AiStoryState>({ state: "idle", note: null });
  const live = useRef({ key, doc, facts, session, ai });
  live.current = { key, doc, facts, session, ai };
  useEffect(() => {
    if ((ai.state === "ready" || ai.state === "loading") && ai.key !== key) setAi({ state: "stale" });
  }, [key, ai]);
  const ask = useCallback(async () => {
    const now = live.current;
    if (now.session.kind === "signed_out" || !now.facts.length || now.ai.state === "loading") return;
    const asked = now.key;
    setAi({ state: "loading", key: asked });
    const res = await portfolioGraphApi.assistNarrate(now.doc, now.facts);
    if (live.current.key !== asked) { setAi({ state: "stale" }); return; }
    if (!res.available) { setAi({ state: "idle", note: `AI 글을 보여 줄 수 없어요: ${res.reason}` }); return; }
    setAi({ state: "ready", key: asked, paragraphs: res.paragraphs, notice: res.notice, note: storyNote(res) });
  }, []);
  return { ai, ask, hasFacts: facts.length > 0 };
}

export function AiStory({ session, story, badge, onSelect }: {
  session: Session;
  story: ReturnType<typeof useAiStory>;
  /** 화면 번호와 쉬운 이름 — 칩이 캔버스·이야기 번호와 같은 말을 한다. */
  badge: (id: string) => { num: number | null; name: string };
  onSelect: (id: string) => void;
}) {
  const { ai, ask, hasFacts } = story;
  const busy = ai.state === "loading";
  const again = ai.state === "ready" || ai.state === "stale";
  const note = ai.state === "idle" || ai.state === "ready" ? ai.note : null;
  const control = !hasFacts || session.kind === "loading" ? null
    : session.kind === "signed_out" ? <Link href="/login" className="pg-ai-story-login">로그인하면 AI 로 풀어 쓸 수 있어요</Link>
    : (
      <button type="button" className="pg-ai-story-ask" onClick={() => { void ask(); }} disabled={busy} aria-busy={busy || undefined}>
        {busy ? "AI 가 풀어 쓰는 중이에요" : again ? "AI 로 다시 풀어 쓰기" : "AI 로 풀어 쓰기"}
      </button>
    );
  return (
    <section className="pg-ai-story" aria-labelledby="pg-ai-story-h">
      <div className="pg-ai-story-head">
        <h3 id="pg-ai-story-h" className="pg-ai-story-h">AI 가 풀어 쓴 글</h3>
        {control}
      </div>
      <p className="pg-ai-story-cap">서버 설명을 근거로 Claude 가 써요. 숫자는 근거 단계에 있는 것만 통과해요.</p>
      {!hasFacts && ai.state !== "ready" && <p className="pg-ai-story-wait">계산한 뒤에 풀어 쓸 수 있어요</p>}
      {ai.state === "stale" && <p className="pg-ai-story-stale" role="status">계산 결과가 바뀌어 AI 글을 지웠어요</p>}
      {ai.state === "ready" && (
        <>
          {ai.notice && <p className="pg-ai-story-notice" role="note">{ai.notice}</p>}
          {ai.paragraphs.length > 0 && (
            <ol className="pg-ai-paras">
              {ai.paragraphs.map((p, i) => (
                <li key={i} className="pg-ai-para">
                  <p className="pg-ai-para-text">{p.text}</p>
                  <div className="pg-ai-chips" aria-label="이 문단의 근거 단계">
                    {p.node_ids.map((id) => {
                      const b = badge(id);
                      return (
                        <button key={id} type="button" className="pg-ai-chip" onClick={() => onSelect(id)}>
                          {b.num !== null && <span className="pg-ai-chip-n">{b.num}</span>} {b.name}
                        </button>
                      );
                    })}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
      {note && <p className="pg-ai-story-note" role="status">{note}</p>}
    </section>
  );
}
