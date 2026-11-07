"use client";
/**
 * AI 넷 — 노드 추천(AI1) · 풀어 쓴 글(AI2) · 묻기(AI3) · 말로 설계(AI4)
 * (CF 3부 E2b — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변 · 본체의 같은 자리에서 부른다 — 사이에 있던 `order`·`path`·`staleSet` 은
 * effect 가 없는 계산이라 이 훅 앞으로 올렸다).
 */
import { useCallback, useEffect, useMemo, useRef, type RefObject } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import { NODE_W, nodeHeight, draftTouched, placeDraft, placeNodes, type AskTarget, type DraftBody, type GraphDoc } from "@/entities/portfolio-graph";
import { useSession } from "@/entities/session";
import { useAiAssist } from "./AiAsk";
import { useAiQuestion } from "./AiQuestion";
import { useAiStory } from "./AiStory";
import { useDraft } from "./DraftPanel";
import type { LeftTab } from "./NodePalette";
import { floatInsets, toggle, type Panels } from "./panels";
import { usePortfolioGraph, type PgState } from "./store";

export function useCanvasAi(s: PgState, doc: GraphDoc, order: string[], staleSet: Set<string>,
                            rf: RefObject<ReactFlowInstance | null>, canvasEl: RefObject<HTMLDivElement>,
                            updatePanels: (f: (p: Panels) => Panels) => void, setLeftTab: (t: LeftTab) => void,
                            fitIds: (ids: string[]) => void) {
  // AI1 — 누를 때만 묻는 AI 노드 추천. 로그인 판정은 서버가 하고, 화면은 로그아웃이면 묻지 않는다(요청 0).
  const { session } = useSession();
  const aiNoteSink = useCallback((n: string) => usePortfolioGraph.getState().setNote(n), []);
  const ai = useAiAssist(doc, session, aiNoteSink);
  // AI2 — 이야기 탭 맨 위 'AI 가 풀어 쓴 글'(누를 때만 · 낡지 않은 결과의 설명·봉인만 보낸다).
  const aiStory = useAiStory(doc, order, s.report?.nodes ?? null, staleSet, session);
  // AI3 — 고른 노드·선에게 묻기(오른쪽 창 아래 칸). 문답은 대상마다 이번 방문 동안 남는다.
  const askTarget = useMemo<AskTarget | null>(() => (s.selectedId ? { kind: "node", id: s.selectedId }
    : s.selectedEdge ? { kind: "edge", id: s.selectedEdge } : null), [s.selectedId, s.selectedEdge]);
  const aiQ = useAiQuestion(doc, order, s.report, staleSet, session, askTarget);
  const askFocus = useRef<() => void>(() => {});
  // AI4 — 말로 설계(왼쪽 창 '말로' 탭). 초안은 미리보기일 뿐 — [받아들이기] 때만 문서가 바뀐다(되돌리기 한 번).
  const draftQ = useDraft(doc, session);
  const sayInput = useRef<HTMLTextAreaElement | null>(null);
  const draftAt = useMemo(() => (draftQ.draft
    ? placeDraft(draftQ.draft, placeNodes(s.nodes), s.catalog) : {}),
  [draftQ.draft, s.nodes, s.catalog]);
  const draftAtRef = useRef(draftAt);
  draftAtRef.current = draftAt;
  // 새 초안이 판 밑이나 화면 밖이면 그쪽을 보인다(AI1 유령과 같은 까닭 — 미리 볼 수 없으면 받아들일지 정할 수 없다. PNG 검토에서 찾음:
  // 더할 노드가 오른쪽 창 밑에 깔렸다). 지금 확대로 다 들어오지 않으면 줄인다. 초안이 올 때 한 번만 — 노드를 옮길 때마다 따라가지 않는다.
  useEffect(() => {
    const dr = draftQ.draft;
    const el = canvasEl.current;
    if (!dr || !rf.current || !el) return;
    const st = usePortfolioGraph.getState();
    const box = (x: number, y: number, kind: string, slotH?: number) => ({ x, y, w: NODE_W, h: nodeHeight(kind, st.catalog, slotH) });
    const boxes = [...dr.add.flatMap((a) => (draftAtRef.current[a.id] ? [box(draftAtRef.current[a.id].x, draftAtRef.current[a.id].y, a.kind)] : [])),
                   ...draftTouched(dr, new Set(st.nodes.map((n) => n.id))).flatMap((id) => {
                     const n = st.nodes.find((x) => x.id === id);
                     return n ? [box(n.position.x, n.position.y, n.data.kind, n.data.slotH)] : [];
                   })];
    if (!boxes.length) return;
    const { x: tx, y: ty, zoom } = rf.current.getViewport();
    const ins = floatInsets(el);
    const l = Math.min(...boxes.map((b) => b.x)), r = Math.max(...boxes.map((b) => b.x + b.w));
    const t = Math.min(...boxes.map((b) => b.y)), bt = Math.max(...boxes.map((b) => b.y + b.h));
    const seen = l * zoom + tx >= ins.left && r * zoom + tx <= el.clientWidth - ins.right && t * zoom + ty >= 0 && bt * zoom + ty <= el.clientHeight - ins.bottom;
    if (seen) return;
    const fitZoom = 0.9 * Math.min((el.clientWidth - ins.left - ins.right) / (r - l), (el.clientHeight - ins.bottom) / (bt - t));
    const z = Math.max(0.2, Math.min(zoom, fitZoom));
    rf.current.setCenter((l + r) / 2 + (ins.right - ins.left) / 2 / z, (t + bt) / 2 + ins.bottom / 2 / z, { zoom: z, duration: 250 });
  }, [draftQ.draft, rf, canvasEl]);
  /** '말로' 탭을 열고 입력에 초점(명령 찾기 · 좁은 화면은 왼쪽 시트를 연다). */
  const openSay = () => {
    updatePanels((p) => (p.left ? p : toggle(p, "left")));
    setLeftTab("say");
    window.setTimeout(() => sayInput.current?.focus(), 80);
  };
  /** [받아들이기] — 미리 본 자리 그대로, 되돌리기 한 번(`applyDraft`). 새 노드와 값이 바뀐 노드로 맞춰 본다. 계산은 하지 않는다(길잡이가 권한다). */
  const acceptDraft = (dr: DraftBody) => {
    const st = usePortfolioGraph.getState();
    const touched = draftTouched(dr, new Set(st.nodes.map((n) => n.id)));
    let ok = false;
    st.act(() => {
      const r = st.applyDraft(dr, draftAt);
      if (!r) return "캔버스가 바뀌어 초안을 받아들이지 못했어요 — 다시 말해 주세요.";
      ok = true;
      return `말씀대로 바꿨어요 — 노드 ${r.added}개 더함 · 선 ${r.connected}개 이음 · 값 ${r.set}개 넣음. 계산하면 결과가 나와요.`;
    });
    if (ok) fitIds([...dr.add.map((a) => a.id), ...touched]);
  };
  return { session, ai, aiStory, askTarget, aiQ, askFocus, draftQ, sayInput, draftAt, openSay, acceptDraft };
}
