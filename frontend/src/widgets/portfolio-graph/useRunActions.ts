"use client";
/**
 * 계산하기와 그 둘레 — 실행 줄(진행 곁줄) · 여기까지·바뀐 곳만·이 전략만 계산 · 바꿔 끼우기 · 목표로 시작 · 카드 단추가 부르는 ref
 * (CF 3부 E2b — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변 · 본체의 같은 자리에서 부른다 — ref 는 그릴 때마다 그 자리에서 다시 건다).
 */
import { useCallback, useMemo, useRef, type Dispatch, type MutableRefObject, type RefObject, type SetStateAction } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import { COL, euro, goalDoc, josa, nextKinds, portfolioGraphApi, restackDoc, toDoc, type WorkflowStage } from "@/entities/portfolio-graph";
import type { QuickAddState } from "./CanvasAssist";
import { ancestorsOf, usePortfolioGraph, type PgState } from "./store";

export interface CardRefs {
  needRef: MutableRefObject<(id: string, port: string, type: string) => void>;
  socketRef: MutableRefObject<(id: string, port: string, type: string, side: "in" | "out") => void>;
  runToRef: MutableRefObject<(id: string) => void>;
  runStrategyRef: MutableRefObject<(groupId: string) => void>;
  branchStrategyRef: MutableRefObject<(groupId: string) => void>;
  previewRef: MutableRefObject<(id: string | null) => void>;
}

export function useRunActions(s: PgState, stages: WorkflowStage[], rf: RefObject<ReactFlowInstance | null>, canvasEl: RefObject<HTMLDivElement>,
                              setQuick: Dispatch<SetStateAction<QuickAddState | null>>, setGoalOpen: (v: boolean) => void, fit: () => void,
                              refs: CardRefs) {
  const { needRef, socketRef, runToRef, runStrategyRef, branchStrategyRef, previewRef } = refs;
  // 실행 줄(CF5a) — 진행은 곁줄로 받는다. 곁줄을 먼저 열고 계산한다(늦게 붙어도 서버가 쌓인 것부터 준다). 곁줄이 끊기면 그렇다고 말하고,
  // 계산과 결과는 `/run` 이 그대로 낸다. 다음 계산을 시작하면 앞 곁줄은 닫는다.
  const follower = useRef<AbortController | null>(null);
  const run = useCallback(async (targets?: string[]) => {
    const st = usePortfolioGraph.getState();
    const ids = targets?.length ? ancestorsOf(targets, st.edges) : st.nodes.map((n) => n.id);
    st.startRun(ids);
    st.setOpenGate(null);
    follower.current?.abort();
    const ctl = new AbortController();
    follower.current = ctl;
    const rid = `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    portfolioGraphApi.followProgress(rid, (ev) => usePortfolioGraph.getState().applyRunEvent(ev), ctl.signal)
      .catch(() => { if (!ctl.signal.aborted) usePortfolioGraph.getState().progressLost(); });
    try {
      st.finishRun(await portfolioGraphApi.run(toDoc(st.nodes, st.edges), targets?.length ? targets : undefined, rid));
    } catch (e) {
      st.finishRun(null, (e as Error).message);
    }
  }, []);
  /** 지금 이을 수 있어요(BT6) — 사람이 고른 노드가 있을 때만(추가로 자동 선택된 노드에는 잇지 않으므로 보이지 않는다). */
  const paletteNext = useMemo(() => {
    const sel = s.pickedByUser ? s.nodes.find((n) => n.id === s.selectedId) : undefined;
    const entry = sel && s.catalog?.find((c) => c.type === sel.data.kind);
    return entry && s.catalog ? { from: entry.plain_label, items: nextKinds(entry.type, s.catalog, stages.map((x) => x.key)) } : null;
  }, [s.pickedByUser, s.selectedId, s.nodes, s.catalog, stages]);
  const runTo = useCallback((id: string) => run([id]), [run]);
  /** 바꿔 끼우기(BT6) — 되돌리기 한 번. 설정이 기본값이 된다는 것을 토스트가 말한다. */
  const swapTo = useCallback((id: string, kind: string) => {
    const st = usePortfolioGraph.getState();
    const name = (k?: string) => st.catalog?.find((c) => c.type === k)?.plain_label ?? k ?? "";
    const from = name(st.nodes.find((n) => n.id === id)?.data.kind);
    st.act(() => (st.swapNode(id, kind)
      ? `${josa(`‘${from}’`, ["을", "를"])} ${euro(`‘${name(kind)}’`)} 바꿨어요 — 선과 자리는 그대로, 설정은 기본값이에요.`
      : "바꿀 수 없어요 — 지금 선을 그대로 받을 수 없는 노드예요."));
  }, []);
  /** 바뀐 곳만 계산(BT5) — 낡은 노드들을 목표로 하는 부분 계산("여기까지 계산" 과 같은 길). 관문은 부분 계산이라 내지 않는다(기존 사유 문구). */
  const runStale = useCallback(() => {
    const ids = usePortfolioGraph.getState().staleIds;
    return ids.length ? run(ids) : Promise.resolve();
  }, [run]);
  /** 목표로 시작 — 답으로 조립한 흐름을 싣고(되돌리기 가능), 흐름 순서대로 한 번 자라나게 한 뒤 곧바로 계산한다. */
  const startGoal = useCallback((goal: Parameters<typeof goalDoc>[0], tickers: string[], lookback: number | null,
                                 riskAversion: number | null) => {
    const st = usePortfolioGraph.getState();
    st.act(() => {
      st.loadDoc(restackDoc(goalDoc(goal, tickers, lookback, riskAversion), st.catalog));
      return "답으로 흐름을 만들었어요 — 계산하고 있어요. 노드를 눌러 설정을 바꿀 수 있어요.";
    });
    setGoalOpen(false);
    st.setGrowing(true);
    setTimeout(() => usePortfolioGraph.getState().setGrowing(false), 1800);
    fit();
    void run();
  }, [run, fit, setGoalOpen]);
  needRef.current = (id, port, type) => {
    const el = canvasEl.current?.querySelector(`.react-flow__node[data-id="${CSS.escape(id)}"]`);
    const box = canvasEl.current?.getBoundingClientRect();
    if (!el || !box) return;
    const r = el.getBoundingClientRect();
    const cx = Math.max(box.left + 8, r.left - COL * (rf.current?.getZoom() ?? 1));
    setQuick({ from: { node: id, handle: port, side: "target", type }, x: r.left - box.left, y: r.bottom - box.top + 6,
               clientX: cx, clientY: r.top });
  };
  socketRef.current = (id, port, type, side) => {
    if (side === "in") { needRef.current(id, port, type); return; }
    const el = canvasEl.current?.querySelector(`.react-flow__node[data-id="${CSS.escape(id)}"]`);
    const box = canvasEl.current?.getBoundingClientRect();
    if (!el || !box) return;
    const r = el.getBoundingClientRect();
    setQuick({ from: { node: id, handle: port, side: "source", type }, x: r.right - box.left + 6, y: r.top - box.top,
               clientX: r.left + COL * (rf.current?.getZoom() ?? 1), clientY: r.top });
  };
  runToRef.current = (id) => { if (!usePortfolioGraph.getState().running) void runTo(id); };
  // 이 전략만 계산(BN N1) — 전략 구성원 중 하류가 전략 안에 없는 노드(출력·잎)를 대상으로 부분 계산.
  runStrategyRef.current = (groupId) => {
    const st = usePortfolioGraph.getState();
    const g = st.groups.find((x) => x.id === groupId);
    if (!g || st.running) return;
    const inside = new Set(g.members);
    const targets = g.members.filter((m) => !st.edges.some((e) => e.source === m && inside.has(e.target)));
    if (targets.length) void run(targets);
  };
  branchStrategyRef.current = (groupId) => {
    const st = usePortfolioGraph.getState();
    st.act(() => st.makeBranch("", groupId));
  };
  previewRef.current = (id) => {
    const st = usePortfolioGraph.getState();
    st.setPreview(id ? ancestorsOf([id], st.edges) : null);
  };
  return { run, paletteNext, runTo, swapTo, runStale, startGoal };
}
