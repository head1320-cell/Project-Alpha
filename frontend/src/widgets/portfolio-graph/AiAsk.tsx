"use client";
/**
 * AI 노드 추천(AI1) — ★누를 때만 묻는다★(사용자 결정 2026-10-22). 답은 서버가 검사를 통과시킨 것만 오고, 화면은 CF6 유령 자리에 둔다.
 *  · 로그아웃이면 묻지 않는다(요청 0) — 단추 대신 로그인 안내.
 *  · 못 보이면 서버 사유를 그대로 말한다(조용히 숨기지 않는다) · 검사에서 빠진 것은 수와 사유를 말한다 — ★바 안의 상태 줄★로:
 *    토스트는 아래 바를 가리고(닫을 때까지) 다시 묻기 단추까지 숨긴다(AI1 E2E 가 찾음).
 *  · ★답은 물을 때의 그래프에 대한 것이다★ — 구조(노드 종류·선)가 바뀌면 AI 유령을 지우고 그렇게 말한다. 옮기기만 하면 그대로.
 *  · 목표(AI1 목표, 문서 `meta.goal`)도 근거다 — 목표가 바뀌면 지우고 "목표가 바뀌어…"라고 말한다(구조가 바뀐 것과 가른다).
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { portfolioGraphApi, type AiRejected, type AiSuggestion, type GraphDoc } from "@/entities/portfolio-graph";
import type { Session } from "@/entities/session";

export type AiState =
  | { state: "idle"; note: string | null }
  | { state: "loading"; sig: string; goal: string }
  | { state: "ready"; sig: string; goal: string; suggestions: AiSuggestion[]; note: string }
  | { state: "stale"; why: "graph" | "goal" };

/** 구조 서명 — 노드 id·종류와 선만(자리·설정값은 빼고). 서버 답이 기대는 것과 같은 범위다. */
export function structureSig(doc: Pick<GraphDoc, "nodes" | "edges">): string {
  return JSON.stringify([doc.nodes.map((n) => `${n.id}:${n.type}`).sort(),
                         doc.edges.map((e) => `${e.source}.${e.source_port}>${e.target}.${e.target_port}`).sort()]);
}

/** 받은 답을 한 줄로 — 보인 수 · 검사에서 빠진 수와 첫 사유. */
export function aiNote(shown: number, rejected: AiRejected[]): string {
  const why = rejected.length ? `${rejected.length}개는 검사에서 빠졌어요: ${rejected[0].reason}` : "";
  if (shown > 0) return why ? `AI 추천 ${shown}개를 보였어요 · ${why}` : `AI 추천 ${shown}개를 보였어요.`;
  return why ? `AI 추천 ${why}` : "AI 가 낸 추천이 없어요.";
}

export function useAiAssist(doc: GraphDoc, session: Session, setNote: (n: string) => void) {
  const sig = useMemo(() => structureSig(doc), [doc]);
  const goal = doc.meta?.goal ?? "";
  const [ai, setAi] = useState<AiState>({ state: "idle", note: null });
  const live = useRef({ sig, goal, doc, session, ai });
  live.current = { sig, goal, doc, session, ai };
  useEffect(() => {
    if ((ai.state === "ready" || ai.state === "loading") && (ai.sig !== sig || ai.goal !== goal)) {
      setAi({ state: "stale", why: ai.sig !== sig ? "graph" : "goal" });
    }
  }, [sig, goal, ai]);
  const ask = useCallback(async () => {
    const now = live.current;
    if (now.session.kind === "signed_out") { setNote("로그인하면 AI 추천을 받을 수 있어요."); return; }
    if (now.ai.state === "loading") return;
    const asked = now.sig, askedGoal = now.goal;
    setAi({ state: "loading", sig: asked, goal: askedGoal });
    const res = await portfolioGraphApi.assistSuggest(now.doc);
    if (live.current.sig !== asked || live.current.goal !== askedGoal) {
      setAi({ state: "stale", why: live.current.sig !== asked ? "graph" : "goal" });
      return;
    }
    if (!res.available) { setAi({ state: "idle", note: `AI 답을 보여 줄 수 없어요: ${res.reason}` }); return; }
    setAi({ state: "ready", sig: asked, goal: askedGoal, suggestions: res.suggestions, note: aiNote(res.suggestions.length, res.rejected) });
  }, [setNote]);
  return { ai, ask, suggestions: ai.state === "ready" ? ai.suggestions : [] };
}

/** 아래 바 끝의 묻기 칸 — 로그아웃이면 로그인 안내, 확인 중이면 아무것도(모름 ≠ 로그아웃). */
export function AiAsk({ session, ai, onAsk }: { session: Session; ai: AiState; onAsk: () => void }) {
  if (session.kind === "loading") return null;
  // 짧게 — 두 창을 연 1024 폭에선 바가 280px 남짓이라 긴 문장이면 바가 세 줄이 됐다(K4 바 높이 120 미만, E2E 가 찾음).
  if (session.kind === "signed_out") return <Link href="/login" className="pg-ai-login">로그인하면 AI 추천</Link>;
  const busy = ai.state === "loading";
  const note = ai.state === "idle" || ai.state === "ready" ? ai.note : null;
  return (
    <span className="pg-ai">
      {note && <span className="pg-ai-note" role="status">{note}</span>}
      {ai.state === "stale" && (
        <span className="pg-ai-stale" role="status">{ai.why === "goal" ? "목표가 바뀌어" : "그래프가 바뀌어"} AI 추천을 지웠어요</span>
      )}
      <button type="button" className="pg-ai-ask" onClick={onAsk} disabled={busy} aria-busy={busy || undefined}>
        {busy ? "AI 추천을 묻는 중이에요" : ai.state === "stale" ? "다시 묻기" : "AI 추천 받기"}
      </button>
    </span>
  );
}
