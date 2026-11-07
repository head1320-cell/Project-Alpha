"use client";
/**
 * 노드 더하기의 손길 — 보이는 가운데에 더하기 · 선 끌어 놓기 빠른 추가 · 우클릭 메뉴
 * (CF 3부 E2b — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변 · 본체의 같은 자리에서 부른다).
 */
import { useCallback, useMemo, type Dispatch, type MutableRefObject, type RefObject, type SetStateAction } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import { ArrowLeft, ChevronsUpDown, ClipboardPaste, Copy, GitBranch, Info, LayoutGrid, ListPlus, MessageCircleQuestion, Pin, PinOff, Play, Plus, Replace, Route, Scale, Scissors, Search as SearchIcon, Spline, Trash2 } from "lucide-react";
import { COL, compareTargets, insertCandidates, swapCandidates, type InsertCandidate } from "@/entities/portfolio-graph";
import type { MenuItem, QuickAddState } from "./CanvasAssist";
import { deleteNote, SAME_SIDE, wireProblem } from "./canvasRules";
import { usePortfolioGraph, type PgState } from "./store";
import { collapsedMembers } from "./storeShared";
import { insertNone, wireType, type WireAction, type WireToolFn } from "./WireToolbar";

/** 우클릭한 자리 — 캔버스 안 좌표와 화면 좌표, 누른 노드(빈 곳이면 null). */
export type CtxAt = { x: number; y: number; clientX: number; clientY: number; nodeId: string | null;
                      /** 선 우클릭(R5) — 그 선과 메뉴 단계(선 동작 넷 · 사이에 넣을 후보). */
                      edgeId?: string | null; mode?: "edge" | "insert" };

export function useQuickAdd(s: PgState, rf: RefObject<ReactFlowInstance | null>, canvasEl: RefObject<HTMLDivElement>,
                            addCount: MutableRefObject<number>, connectFrom: MutableRefObject<QuickAddState["from"]>,
                            quick: QuickAddState | null, setQuick: Dispatch<SetStateAction<QuickAddState | null>>, ctx: CtxAt | null,
                            setCtx: Dispatch<SetStateAction<CtxAt | null>>,
                            fit: () => void, setFindOpen: (v: boolean) => void, runToRef: MutableRefObject<(id: string) => void>,
                            wireToolRef: MutableRefObject<WireToolFn>) {
  // 클릭으로 추가하면 **보이는 캔버스의 가운데**에, 겹치지 않게 조금씩 비껴 놓는다.
  const addAt = useCallback((kind: string, pos?: { x: number; y: number }) => {
    let at = pos;
    if (!at) {
      const r = canvasEl.current?.getBoundingClientRect();
      const k = addCount.current++ % 6;
      at = r && rf.current
        ? rf.current.screenToFlowPosition({ x: r.left + r.width / 2 + k * 28, y: r.top + r.height / 2 + k * 28 })
        : { x: 200 + k * 28, y: 200 + k * 28 };
    }
    const st = usePortfolioGraph.getState();
    // BT3 — 사람이 노드를 골라 둔 채 팔레트·명령으로 추가하면(끌어 놓은 자리가 없을 때) 그 노드 오른쪽에 놓고 잇는다.
    if (!pos && st.pickedByUser && st.selectedId) {
      const src = st.nodes.find((n) => n.id === st.selectedId);
      const srcEntry = st.catalog?.find((c) => c.type === src?.data.kind);
      const entry = st.catalog?.find((c) => c.type === kind);
      const pair = srcEntry?.outputs.flatMap((o) => (entry?.inputs ?? []).filter((i) => i.type === o.type).map((i) => [o, i] as const))[0];
      if (src && srcEntry && entry && pair) {
        let id = "";
        st.act(() => {
          id = st.addLinked(kind, { x: src.position.x + COL, y: src.position.y }, { node: src.id, handle: pair[0].name, side: "source", port: pair[1].name });
          return `‘${srcEntry.plain_label}’ 뒤에 이었어요.`;
        });
        st.setTab("settings");
        return id;
      }
    }
    const id = st.addNode(kind, at);
    st.setTab("settings");
    return id;
  }, [rf, canvasEl, addCount]);

  // ── 선 끌어 놓기 빠른 추가(BN N3) — 포트에서 끌어 빈 곳에 놓으면 그 값을 이을 노드만 보인다 ──────────
  const onConnectStart = useCallback((_: unknown, p: { nodeId: string | null; handleId: string | null; handleType: "source" | "target" | null }) => {
    const st = usePortfolioGraph.getState();
    const kind = st.nodes.find((n) => n.id === p.nodeId)?.data.kind;
    const entry = st.catalog?.find((c) => c.type === kind);
    const side = p.handleType ?? "source";
    const port = (side === "source" ? entry?.outputs : entry?.inputs)?.find((x) => x.name === p.handleId);
    connectFrom.current = p.nodeId && p.handleId && port ? { node: p.nodeId, handle: p.handleId, side, type: port.type } : null;
  }, [connectFrom]);
  const onConnectEnd = useCallback((e: MouseEvent | TouchEvent) => {
    const from = connectFrom.current;
    connectFrom.current = null;
    if (usePortfolioGraph.getState().reconnecting) return;              // 다시 꽂기는 onReconnectEnd 가 말한다(빠른 추가도 열지 않음)
    const target = e.target as Element | null;
    // BT4 — 포트에 놓았는데 이을 수 없으면 왜 안 되는지 말한다(예전엔 조용히 거부했다).
    const handle = target?.closest?.(".react-flow__handle") as HTMLElement | null;
    if (from && handle) {
      const st = usePortfolioGraph.getState();
      const other = { node: handle.dataset.nodeid ?? null, handle: handle.dataset.handleid ?? null };
      const c = from.side === "source"
        ? { source: from.node, sourceHandle: from.handle, target: other.node, targetHandle: other.handle }
        : { source: other.node, sourceHandle: other.handle, target: from.node, targetHandle: from.handle };
      const onSameSide = handle.classList.contains(from.side);
      const why = onSameSide ? SAME_SIDE[from.side] : wireProblem(c);
      if (why) st.setNote(why);
      return;
    }
    if (!from || !target?.classList.contains("react-flow__pane")) return;     // 포트에 놓았으면 평소의 연결
    const pt = "changedTouches" in e ? e.changedTouches[0] : e;
    const box = canvasEl.current?.getBoundingClientRect();
    setQuick({ from, x: pt.clientX - (box?.left ?? 0), y: pt.clientY - (box?.top ?? 0), clientX: pt.clientX, clientY: pt.clientY });
  }, [canvasEl, connectFrom, setQuick]);
  const quickPick = useCallback((kind: string, port: string | null) => {
    const q = quick;
    setQuick(null);
    if (!q || !rf.current) return;
    const at = rf.current.screenToFlowPosition({ x: q.clientX, y: q.clientY });
    const st = usePortfolioGraph.getState();
    if (q.from && port) {
      // 입력에 이미 선이 있으면(입력 하나에 선 하나) 잇지 않고 놓기만 하고 말한다.
      const taken = q.from.side === "target" && st.edges.some((e) => e.target === q.from!.node && e.targetHandle === q.from!.handle);
      if (!taken) {
        st.act(() => { st.addLinked(kind, at, { ...q.from!, port }); return "노드를 놓고 이었어요."; });
        st.setTab("settings");
        return;
      }
      st.addNode(kind, at);
      st.setNote("노드를 놓았어요 — 그 입력에는 이미 선이 있어 잇지 않았어요.");
      return;
    }
    addAt(kind, at);
  }, [quick, addAt, rf, setQuick]);

  /** 우클릭 메뉴의 항목 — 노드면 노드 동작, 빈 곳이면 추가·붙여넣기·정리. 같은 동작이 명령 찾기에도 있다. */
  const compareCheck = useMemo(() => compareTargets(s.picked, s.nodes, s.catalog ?? []), [s.picked, s.nodes, s.catalog]);
  const pickedIsOneGroup = useMemo(() => s.groups.some((g) => g.members.length === s.picked.length
    && s.picked.every((id) => g.members.includes(id))), [s.groups, s.picked]);

  const ctxItems = useMemo((): MenuItem[] => {
    if (!ctx) return [];
    const st = usePortfolioGraph.getState();
    if (ctx.edgeId) {
      // 선 메뉴(R5) — 도구줄과 같은 넷 · 같은 길(`wireToolRef`). 접힌 상자의 대리 선은 실제 끝이 숨어 있어 고치지 않고 까닭 + 펼치기.
      const id = ctx.edgeId;
      const e = st.edges.find((x) => x.id === id);
      if (!e) return [];
      const folded = collapsedMembers(st.groups, st.focusGroup);
      const gid = folded.get(e.source) ?? folded.get(e.target);
      if (gid) {
        return [
          { key: "proxy-why", label: "접힌 상자에 걸린 선이에요 — 상자를 펼치면 고칠 수 있어요", icon: <Info size={14} aria-hidden="true" />, disabled: true, run: () => {} },
          { key: "unfold", label: "상자 펼치기", icon: <ChevronsUpDown size={14} aria-hidden="true" />, run: () => usePortfolioGraph.getState().toggleGroup(gid) },
        ];
      }
      const { type, plain } = wireType(st, id);
      const cands = insertCandidates(type, st.catalog ?? []);
      const tool = (a: WireAction, arg?: InsertCandidate) => wireToolRef.current(id, a, arg);
      if (ctx.mode === "insert") {
        return [
          ...cands.map((c) => ({ key: `insert:${c.kind}`, label: c.label, icon: <ListPlus size={14} aria-hidden="true" />, run: () => tool("insert", c) })),
          { key: "back", label: "뒤로", icon: <ArrowLeft size={14} aria-hidden="true" />, run: () => setCtx({ ...ctx, mode: "edge" }) },
        ];
      }
      return [
        { key: "cut", label: "선 끊기", icon: <Scissors size={14} aria-hidden="true" />, danger: true, run: () => tool("cut") },
        { key: "insert", label: cands.length ? "사이에 넣기…" : `사이에 넣기 — ${insertNone(plain)}`, icon: <ListPlus size={14} aria-hidden="true" />,
          disabled: !cands.length, run: () => setCtx({ ...ctx, mode: "insert" }) },
        { key: "waypoint", label: "꺾는 점 넣기", icon: <Spline size={14} aria-hidden="true" />, run: () => tool("waypoint") },
        { key: "ask", label: "이 선에게 묻기", icon: <MessageCircleQuestion size={14} aria-hidden="true" />, run: () => tool("ask") },
      ];
    }
    if (!ctx.nodeId) {
      return [
        { key: "add-here", label: "여기에 노드 추가", icon: <Plus size={14} aria-hidden="true" />,
          run: () => setQuick({ from: null, x: ctx.x, y: ctx.y, clientX: ctx.clientX, clientY: ctx.clientY }) },
        { key: "paste", label: "붙여넣기", icon: <ClipboardPaste size={14} aria-hidden="true" />, disabled: !st.clip?.nodes.length,
          run: () => { usePortfolioGraph.getState().paste(); } },
        { key: "layout", label: "자동 정리", icon: <LayoutGrid size={14} aria-hidden="true" />, disabled: st.nodes.length === 0,
          run: () => { usePortfolioGraph.getState().autoLayout(); fit(); } },
        { key: "find", label: "노드 찾기 (Ctrl+F)", icon: <SearchIcon size={14} aria-hidden="true" />, run: () => setFindOpen(true) },
      ];
    }
    const id = ctx.nodeId;
    const r = st.staleIds.includes(id) ? undefined : st.report?.nodes[id];
    const pinned = st.pinned.includes(id);
    return [
      { key: "run-to", label: "여기까지 계산", icon: <Play size={14} aria-hidden="true" />, disabled: st.running, run: () => runToRef.current(id) },
      { key: "branch", label: "갈래 만들기", icon: <GitBranch size={14} aria-hidden="true" />,
        run: () => { const x = usePortfolioGraph.getState(); x.act(() => x.makeBranch(id)); } },
      { key: "duplicate", label: "복제 (Ctrl+D)", icon: <Copy size={14} aria-hidden="true" />,
        run: () => { usePortfolioGraph.getState().duplicateNode(id); } },
      // BT6 — 바꿀 종류는 설정 판에서 고른다(메뉴는 그 칸으로 데려간다). 후보가 없으면 흐리게, 이유를 이름에.
      ...(() => {
        const none = swapCandidates(id, st.nodes, st.edges, st.catalog ?? []).length === 0;
        return [{ key: "swap", label: none ? "다른 노드로 바꾸기 — 같은 선을 받는 다른 노드가 없어요" : "다른 노드로 바꾸기…",
                  icon: <Replace size={14} aria-hidden="true" />, disabled: none,
                  run: () => {
                    const x = usePortfolioGraph.getState();
                    x.select(id);
                    x.setTab("settings");
                    setTimeout(() => (document.querySelector(".pg-swap select") as HTMLSelectElement | null)?.focus(), 60);
                  } }];
      })(),
      ...(st.picked.length > 1 && st.picked.includes(id)
        ? [{ key: "compare", label: "고른 노드 견고성 비교", icon: <Scale size={14} aria-hidden="true" />,
             run: () => { const x = usePortfolioGraph.getState(); x.act(() => x.comparePicked()); } }] : []),
      { key: "pin", label: pinned ? "그림 고정 풀기" : "그림 고정", icon: pinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />,
        run: () => usePortfolioGraph.getState().togglePin(id) },
      ...(r && r.status !== "ok" ? [{ key: "cause", label: "원인 따라가기", icon: <Route size={14} aria-hidden="true" />,
                                      run: () => usePortfolioGraph.getState().showCause(id) }] : []),
      // 여럿 고른 것 안의 노드면 그 여럿을 한 번에(R2) — 되돌리기 한 번.
      ...(st.picked.length > 1 && st.picked.includes(id)
        ? [{ key: "remove-picked", label: `고른 노드 ${st.picked.length}개 지우기`, icon: <Trash2 size={14} aria-hidden="true" />, danger: true,
             run: () => { const x = usePortfolioGraph.getState(); x.act(() => deleteNote(x.deleteElements(x.picked, []))); } }] : []),
      { key: "remove", label: st.picked.length > 1 && st.picked.includes(id) ? "이 노드만 지우기" : "지우기", icon: <Trash2 size={14} aria-hidden="true" />, danger: true,
        run: () => { const x = usePortfolioGraph.getState(); x.act(() => deleteNote(x.deleteElements([id], []))); } },
    ];
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 메뉴를 열 때마다 새로 만든다
  }, [ctx]);
  return { addAt, onConnectStart, onConnectEnd, quickPick, compareCheck, pickedIsOneGroup, ctxItems };
}
