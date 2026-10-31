"use client";
/**
 * 길잡이(AI5) — 아래 바 ★세 번째 자리★(환영 > 다음 한 걸음 > 길잡이 > 기본 안내). 캔버스의 도구를 쓰게 이끄는 코치 — 도구 안내만, 투자 판단은 말하지 않는다.
 * ==========================================================================
 * 사용자 결정(2026-10-23): 규칙 줄 + 누르면 AI.
 *  · 규칙 줄(비용 0, 로그아웃도): `ruleGuide` 가 고른 도구 — 칩 "규칙 길잡이" · 왜 한 줄 · [해 보기] · [다음에](이번 방문 동안 그 도구 숨김).
 *  · [AI 길잡이](로그인 · 누를 때만): 화면이 센 상태와 지금 적용되는 도구를 서버로 — Claude 가 고른 1~2 를 칩 "AI 길잡이"로, 둘이면 넘기기.
 *    상태(또는 적용 도구)가 바뀌면 AI 줄을 지우고 규칙 줄로 돌아가며 그렇게 말한다 · 못 보이면 사유(규칙 줄은 그대로) — ★바 안의 상태 줄★(토스트는 바를 가린다).
 *  · [해 보기]의 실행과 '다음엔 어디서' 안내는 캔버스가 한다(`onTry`) — 이 파일은 고르고 그리기만.
 *  · 바는 K4 처럼 두 창을 연 1024 에서 120px 미만 — 칩은 글 앞에 붙이고, 그 폭에선 AI 노드 추천 단추를 접는다(Ctrl+K 로 남음 · E2E 가 찾음: 4줄 149px).
 *  · 클래스는 `.pg-guidebar`·`.pg-guide-*` — `.pg-next`(다음 한 걸음의 E2E 계약)도, `.pg-guide`(CF4a 맞춤 안내선)도 쓰지 않는다. 바 꼴은 CSS 가 둘에 같이 준다.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { applicableTools, portfolioGraphApi, ruleGuide, toolOf, type GraphDoc, type GuideId, type GuideState } from "@/entities/portfolio-graph";
import type { Session } from "@/entities/session";

type Tip = { feature: string; label: string; why: string };
type AiGuide =
  | { state: "idle"; note: string | null }
  | { state: "loading"; key: string }
  | { state: "ready"; key: string; tips: Tip[]; at: number; note: string | null };

export interface GuideTip { id: GuideId; source: "rule" | "claude"; why: string; total: number; index: number }

export function useGuide(doc: GraphDoc, state: GuideState, dismissed: ReadonlySet<string>, session: Session) {
  const applicable = useMemo(() => applicableTools(state), [state]);
  const key = useMemo(() => JSON.stringify([state, applicable]), [state, applicable]);
  const [ai, setAi] = useState<AiGuide>({ state: "idle", note: null });
  const live = useRef({ key, doc, state, applicable, session, ai });
  live.current = { key, doc, state, applicable, session, ai };
  useEffect(() => {
    if ((ai.state === "ready" || ai.state === "loading") && ai.key !== key) setAi({ state: "idle", note: "캔버스가 바뀌어 AI 길잡이를 지웠어요" });
  }, [key, ai]);

  const ask = useCallback(async () => {
    const now = live.current;
    if (now.session.kind !== "signed_in" || !now.applicable.length || now.ai.state === "loading") return;
    const asked = now.key;
    setAi({ state: "loading", key: asked });
    const res = await portfolioGraphApi.assistGuide(now.doc, now.state, now.applicable);
    if (live.current.key !== asked) { setAi({ state: "idle", note: "캔버스가 바뀌어 AI 길잡이를 지웠어요" }); return; }
    if (!res.available) { setAi({ state: "idle", note: `AI 길잡이를 보여 줄 수 없어요: ${res.reason}` }); return; }
    const tips = res.tips.filter((t) => live.current.applicable.includes(t.feature as GuideId));
    const why = res.rejected.length ? `${res.rejected.length}개는 검사에서 빠졌어요: ${res.rejected[0].reason}` : null;
    setAi(tips.length ? { state: "ready", key: asked, tips, at: 0, note: why }
                      : { state: "idle", note: why ? `AI 가 고른 도구가 없어요 · ${why}` : "AI 가 고른 도구가 없어요" });
  }, []);

  const shown = ai.state === "ready" ? ai.tips.filter((t) => !dismissed.has(t.feature)) : [];
  let tip: GuideTip | null = null;
  if (ai.state === "ready" && shown.length) {
    const i = Math.min(ai.at, shown.length - 1);
    tip = { id: shown[i].feature as GuideId, source: "claude", why: shown[i].why, total: shown.length, index: i };
  } else {
    const r = ruleGuide(state, dismissed);
    if (r) tip = { id: r.id, source: "rule", why: r.why(state), total: 1, index: 0 };
  }
  const next = useCallback(() => setAi((a) => (a.state === "ready" ? { ...a, at: a.at + 1 >= a.tips.length ? 0 : a.at + 1 } : a)), []);
  const note = ai.state === "idle" || ai.state === "ready" ? ai.note : null;
  return { tip, ask, next, note, busy: ai.state === "loading", applicable };
}

export function GuideBar({ g, session, onTry, onLater, extra }: {
  g: ReturnType<typeof useGuide>;
  session: Session;
  onTry: (id: GuideId) => void;
  onLater: (id: GuideId) => void;
  /** 바 끝에 덧붙는 것(AI 노드 추천 — AI1). */
  extra?: ReactNode;
}) {
  const { tip, ask, next, note, busy } = g;
  if (!tip) return null;
  const label = toolOf(tip.id)?.label ?? tip.id;
  return (
    <div className="pg-hint pg-guidebar" role="region" aria-label="길잡이" data-tool={tip.id} data-source={tip.source}>
      <p className="pg-guide-text">
        <span className={`pg-guide-chip pg-guide-chip--${tip.source}`}>{tip.source === "claude" ? "AI 길잡이" : "규칙 길잡이"}</span>{" "}
        <span className="pg-guide-why">{tip.why}</span>
      </p>
      <button type="button" className="pg-guide-go" aria-label={`해 보기: ${label}`} onClick={() => onTry(tip.id)}>해 보기</button>
      <button type="button" className="pg-guide-later" onClick={() => onLater(tip.id)}>다음에</button>
      {tip.total > 1 && (
        <button type="button" className="pg-guide-more" onClick={next}>{`${tip.total}개 중 ${tip.index + 1} · 다음`}</button>
      )}
      {tip.source === "rule" && session.kind === "signed_out" && <Link href="/login" className="pg-guide-login">로그인하면 AI 길잡이</Link>}
      {tip.source === "rule" && session.kind === "signed_in" && (
        <button type="button" className="pg-guide-ai" onClick={() => { void ask(); }} disabled={busy} aria-busy={busy || undefined}>
          {busy ? "AI 길잡이를 묻는 중" : "AI 길잡이"}
        </button>
      )}
      {note && <span className="pg-guide-note" role="status">{note}</span>}
      {extra}
    </div>
  );
}
