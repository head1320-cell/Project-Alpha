"use client";
/**
 * AAS 포트폴리오 설계 캔버스 (BI3 → BJ2·BJ3 토스식 재단장 · 목업 승인본)
 * ==========================================================================
 * ★캔버스는 편집기다. 계산은 백엔드가 한다★(`POST /api/v1/allocation/graph/run`) — 노드는
 * `/analyze`·`/backtest` 와 같은 함수를 부른다(BI2 골든). 설명 문장·관문 판정도 서버가 만든다(BJ1).
 *
 * 배치: 상단 바 → 증거 관문 레일(단 하나의 강한 요소) → 팔레트 | 캔버스 | 이야기·설정·자세히.
 * - 팔레트·포트·파라미터 폼은 서버 카탈로그 하나에서 온다.
 * - 연결은 출력 타입 == 입력 타입일 때만, 입력 하나에 링크 하나, 순환 금지.
 * - 그래프가 바뀌면 곧바로 서버 검증을 불러 노드 위에 오류를 빨갛게 그린다.
 * - 불러오기(파일 선택·드래그앤드롭)는 **즉시** 캔버스를 교체한다. 다른 포맷이면 캔버스를
 *   건드리지 않고 사유를 말한다. 모르는 노드는 버리지 않고 빨갛게 남긴다.
 * - BL4 — 마법사를 지웠다. 옛 주소로 온 사람에게는 그 화면이 하던 일을 여기서 어떻게 하는지 한 줄로 안내한다(`legacy`).
 *
 * BL1 — 조사(n8n·KNIME·ComfyUI·React Flow)에서 가져온 편집 도구: 여기까지 계산(Shift+Enter) · 되돌리기(Ctrl+Z)/
 * 다시하기(Ctrl+Shift+Z) · 복사(Ctrl+C)/붙여넣기(Ctrl+V) · 여러 개 지우기 · 자동 정리 · 미니맵 · 묶음 상자(Ctrl+G) ·
 * 명령 팔레트(Ctrl+K) · 계산 기록. ★이번 대담함은 한 곳★ — "여기까지 계산" 에 올리면 돌 경로가 먼저 밝아진다.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  MiniMap,
  Panel,
  SelectionMode,
  ViewportPortal,
  type Edge,
  type Node,
  type NodeChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Boxes, GitBranch, Filter, Maximize, Minus, MoreHorizontal, PanelRightOpen, Plus, Scale, Sparkles, X } from "lucide-react";
import {
  BRIEF_MAX_W,
  boxDropPlan,
  cardHeight,
  nodeHeight,
  placeNodes,
  cardsOverlap,
  cardWidth,
  NODE_W,
  TEMPLATES,
  PG_NODE_TYPE,
  nodeSummary,
  topoOrder,
  stepOfNode,
  CHIP_H,
  ghostSuggestions,
  withAiGhosts,
  placeConnectChip,
  placeSuggestion,
  suggestionKey,
  restackDoc,
  COMPARE_KIND,
  RECORD_KIND,
  toolOf,
  viaOf,
  type GuideId,
  type GuideState,
  type Box,
  type PgNode,
  type ProcedureSuggestion,
  type WorkflowStage,
  ARIA_KO,
} from "@/entities/portfolio-graph";
import { CommandPalette } from "./CommandPalette";
import { GateRail } from "./GateRail";
import { GhostLayer, type PlacedGhost } from "./GhostLayer";
import { AiAsk } from "./AiAsk";
import { DraftPanel } from "./DraftPanel";
import { DraftLayer } from "./DraftLayer";
import { GuideBar, useGuide } from "./Guide";
import { BranchFrame, PG_BRANCH_TYPE } from "./Branches";
import { EvidenceEdge, PG_WIRE_TYPE, WIRE_LEGEND } from "./EvidenceEdge";
import { GoalStart } from "./GoalStart";
import { GraphNode, PORT_PLAIN, STAGE_VAR } from "./GraphNode";
import { GroupFrame, PG_GROUP_TYPE } from "./GroupFrame";
import { measuredH, measuredW } from "./toolbarPlace";
import { snapToGuides, type Guide } from "./guides";
import { ContextMenu, FindBar, NoteLine, QuickAdd, ShortcutSheet, type QuickAddState } from "./CanvasAssist";
import { NodePalette, type LeftTab } from "./NodePalette";
import { ProcedurePanel } from "./ProcedurePanel";
import { floatInsets, toggle } from "./panels";
import { drawnWire, type WireToolFn } from "./WireToolbar";
import type { LegacyScreen } from "@/entities/portfolio-graph/legacyScreens";
import { Sheet } from "@/shared/ui/tx";
import { SimpleView } from "./SimpleView";
import { usePortfolioGraph, type PgState } from "./store";
import { AlignMenu, SelBar, StageLanes, ZoomPct, ZoomWatch } from "./CanvasChrome";
import { DRAWERS, FILTERS, LEFT_TAB_KEY, markWelcomed, matchFilter, welcomeSeen, type DrawerKey } from "./canvasConfig";
import { MIN_ZOOM, SNAP, fitClear } from "./canvasGeometry";
import { deleteNote, overlapping, useWireHandlers } from "./canvasRules";
import { WireDragLine } from "./WireDragLine";
import { useCanvasView, useViewFollow } from "./useCanvasView";
import { CanvasToolbar } from "./CanvasToolbar";
import { RightPanel } from "./RightPanel";
import { useCanvasCommands } from "./useCanvasCommands";
import { useLatestHandlers } from "./useLatestHandlers";
import { useRunActions } from "./useRunActions";

// R8 — React Flow 에 넘기는 설정은 모듈 상수로. 그릴 때마다 새 배열·객체를 넘기면 React Flow 가 그것을 바뀐 것으로 받아
// 선 감싸개를 모두 다시 그렸다(`defaultEdgeOptions` — 200노드 끌기 한 걸음 = 선 200개, 재서 찾음). 값은 예전 그대로.
const DEFAULT_EDGE_OPTIONS = { type: PG_WIRE_TYPE };
const SNAP_GRID: [number, number] = [SNAP, SNAP];
const DELETE_KEYS = ["Backspace", "Delete"];
const MULTI_SELECT_KEYS = ["Meta", "Control"];
const FIT_VIEW_OPTIONS = { padding: 0.08, maxZoom: 1 };
const PRO_OPTIONS = { hideAttribution: true };
import { useCanvasDrop } from "./useCanvasDrop";
import { useQuickAdd, type CtxAt } from "./useQuickAdd";
import { insertAt, snapPt } from "./wirePath";
import { useDocSync } from "./useDocSync";
import { useCanvasGraph } from "./useCanvasGraph";
import { useCanvasAi } from "./useCanvasAi";
import { useCanvasBoot, type BootDoc } from "./useCanvasBoot";
import { docOf } from "./canvasDoc";

const NODE_TYPES = { [PG_NODE_TYPE]: GraphNode, [PG_GROUP_TYPE]: GroupFrame, [PG_BRANCH_TYPE]: BranchFrame };
const EDGE_TYPES = { [PG_WIRE_TYPE]: EvidenceEdge };
export { ZOOM_FAR, ZOOM_NEAR, zoomLevel, type ZoomLevel } from "./canvasGeometry";

export interface PortfolioCanvasProps {
  /** 상단 바 오른쪽 — 케이스 상자 등. app 계층이 채운다. */
  topExtra?: ReactNode;
  /** 다른 화면이 넘긴 흐름(BL2b — 매크로 스냅샷 등). 있으면 세션 복원 대신 이것을 연다.
   *  `restack: false` 면 위치를 그대로(PB3 — 사용자가 놓은 고객 문서) · `isolate` 면 연 뒤 되돌리기 기록을 비운다(다른 문서로 되돌아가지 않게). */
  initialDoc?: BootDoc | null;
  /** 작업 중 문서를 이 탭에 남길까(기본 예). PB3 고객 문서를 여는 동안은 아니오 — 고객 문서가 작업 중 문서와 섞이지 않는다. */
  persistWip?: boolean;
  /** 넘겨받은 흐름을 싣지 못했을 때의 말(BU2 — 예: 종목 이름 확인 실패). 문서는 바꾸지 않고 안내만 띄운다. */
  bootNote?: string | null;
  /** 옛 주소(`/allocation/<화면>` → `?from=`)로 왔을 때 그 예전 화면(BL4). 배너·팔레트 검색·템플릿·서랍을 안내한다. */
  legacy?: LegacyScreen | null;
}

export function PortfolioCanvas({ topExtra, initialDoc, bootNote, legacy, persistWip = true }: PortfolioCanvasProps) {
  const s = usePortfolioGraph();
  const rf = useRef<ReactFlowInstance | null>(null);
  const canvasEl = useRef<HTMLDivElement>(null);
  const addCount = useRef(0);
  const [stages, setStages] = useState<WorkflowStage[]>([]);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [goalOpen, setGoalOpen] = useState(false);
  /** 올린 선(BT4) — 가운데에 타입 이름 알약을 보인다(툴팁이 아니라 보이는 요소). */
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  /** 팔레트에서 끄는 노드를 끼울 수 있는 선(BT4) — 놓으면 그 선 사이에 들어간다. */
  const [dropWire, setDropWire] = useState<string | null>(null);
  /** 끄는 동안의 정렬 안내선(CF4a) — 놓으면 비운다. */
  const [guides, setGuides] = useState<Guide[]>([]);
  // BT2 — 왼쪽 판 탭. 고른 적이 없으면 노드 추가(예전 그대로)이고, 캔버스가 비어 있으면 절차를 먼저 보인다.
  const [leftTab, setLeftTabState] = useState<LeftTab | null>(() => {
    try { const v = localStorage.getItem(LEFT_TAB_KEY); return v === "proc" || v === "add" || v === "say" ? v : null; } catch { return null; }
  });
  const setLeftTab = useCallback((t: LeftTab) => {
    setLeftTabState(t);
    try { localStorage.setItem(LEFT_TAB_KEY, t); } catch { /* 편의 기능 */ }
  }, []);
  const [welcome, setWelcome] = useState(false);
  // 캔버스 손길(BN N3) — 선 끌어 놓기 빠른 추가 · 우클릭 메뉴 · 찾기 · 단축키 한 장.
  const [quick, setQuick] = useState<QuickAddState | null>(null);
  const [ctx, setCtx] = useState<CtxAt | null>(null);
  const [findOpen, setFindOpen] = useState(false);
  const [keysOpen, setKeysOpen] = useState(false);
  const connectFrom = useRef<QuickAddState["from"]>(null);
  useEffect(() => { setWelcome(!welcomeSeen()); }, []);
  const closeWelcome = () => { markWelcomed(); setWelcome(false); };
  // 서랍(BL2) — 계산하지 않는 기록 화면. 노드가 아니라 캔버스 옆에서 연다.
  const [drawer, setDrawer] = useState<DrawerKey | null>(null);
  // 노드 카드의 "여기까지 계산" 버튼이 부를 함수 — 아래에서 정의되고, 카드는 이 참조로 부른다.
  const runToRef = useRef<(id: string) => void>(() => {});
  const previewRef = useRef<(id: string | null) => void>(() => {});
  /** BT3 — 카드의 "‘X’을 이어 주세요" 단추: 그 입력에서 선을 끈 것과 같은 빠른 추가를 연다. */
  const needRef = useRef<(id: string, port: string, type: string) => void>(() => {});
  const onNeed = useCallback((id: string, port: string, type: string) => needRef.current(id, port, type), []);
  /** CF2 — 소켓 두 번 누르기: 받는 소켓은 "이어 주세요"와 같은 빠른 추가(왼쪽에 놓음), 내는 소켓은 그 값을 받는 노드(오른쪽에 놓음). */
  const socketRef = useRef<(id: string, port: string, type: string, side: "in" | "out") => void>(() => {});
  const onSocket = useCallback((id: string, port: string, type: string, side: "in" | "out") => socketRef.current(id, port, type, side), []);
  /** 카드의 고치는 법 단추(BT7) — 절차 제안과 같은 길(되돌리기 한 번). 정의가 아래에 있어 ref 로 잇는다. */
  const fixRef = useRef<(sug: ProcedureSuggestion) => void>(() => undefined);
  /** 지금 보이는 유령(CF6) — 붙이기가 그 자리를 찾는다(콜백을 다시 만들지 않게 ref). */
  const ghostsRef = useRef<PlacedGhost[]>([]);
  const onFix = useCallback((sug: ProcedureSuggestion) => fixRef.current(sug), []);
  const focusRef = useRef<(id: string) => void>(() => {});
  const runStrategyRef = useRef<(groupId: string) => void>(() => {});
  const branchStrategyRef = useRef<(groupId: string) => void>(() => {});
  /** 선 도구줄·선 우클릭(R5)의 동작 — 아래에서 지금 가진 것으로 채운다. */
  const wireToolRef = useRef<WireToolFn>(() => {});
  const [announce, setAnnounce] = useState("");
  const { panels, setPanels, updatePanels, tight, leftShown, rightShown, fit, fitIds, zoomBy } = useCanvasView(rf, canvasEl, !!s.catalog);

  const booted = useCanvasBoot(initialDoc, bootNote, setStages, setFileNote, setLeftTabState, fit);

  const doc = useMemo(() => docOf(s),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 문서 칸만(s 전체가 아니라)
    [s.nodes, s.edges, s.name, s.goal, s.groups, s.branches, s.pinned, s.folded]);
  const order = useMemo(() => topoOrder(s.nodes.map((n) => n.id), s.edges), [s.nodes, s.edges]);
  /** 밝힐 경로 — 계산 중이면 계산하는 노드들, 아니면 "여기까지 계산" 에 올린 노드의 조상. */
  const path = useMemo(() => new Set(s.runningIds ?? s.preview ?? []), [s.runningIds, s.preview]);
  /** 결과가 지금 그래프의 것이 아닌 노드(BT5) — 바뀐 노드와 그 하류만. 나머지는 결과·선 모양·한눈 요약을 그대로 둔다. */
  const staleSet = useMemo(() => new Set(s.staleIds), [s.staleIds]);
  const { session, ai, aiStory, askTarget, aiQ, askFocus, draftQ, sayInput, draftAt, openSay, acceptDraft } =
    useCanvasAi(s, doc, order, staleSet, rf, canvasEl, updatePanels, setLeftTab, fitIds);
  const { cause, live, stageOfNode, mmMark, bandOf, numbered, onFlag, edgesStyled } =
    useCanvasGraph(s, order, path, staleSet, { runToRef, previewRef, runStrategyRef, branchStrategyRef, wireToolRef }, onNeed, onFix, onSocket,
                   updatePanels, hoverEdge, dropWire);
  /** 전략 추가 메뉴의 재료 — 비중을 내는 템플릿과 내 블록 중 전략. */
  const strategySources = useMemo(() => {
    const cat = s.catalog ?? [];
    const producesWeights = (d: { nodes: { type: string }[] }) =>
      d.nodes.some((n) => cat.find((c) => c.type === n.type)?.outputs.some((o) => o.type === "Weights"));
    return [
      // 템플릿은 코드가 만든 흐름이라 새 카드 높이로 다시 쌓아 넣는다(CF1). 내 블록은 사용자의 배치 그대로.
      ...TEMPLATES.filter((t) => producesWeights(t.doc)).map((t) => ({ key: `tpl:${t.key}`, label: t.name, sub: t.description,
        src: { label: t.name, ...(({ nodes, edges }) => ({ nodes, edges }))(restackDoc(t.doc, cat)) } })),
      ...s.blocks.filter((b) => b.kind === "strategy").map((b, i) => ({ key: `blk:${i}`, label: b.label, sub: `내 블록 · 노드 ${b.nodes.length}개`,
        src: { label: b.label, nodes: b.nodes, edges: b.edges, output: b.output } })),
    ];
  }, [s.catalog, s.blocks]);
  const [stratOpen, setStratOpen] = useState(false);
  // 필터 칩은 접어 둔다 — 캔버스 위에 떠 있는 칩이 노드를 가리지 않게(열 때만 펼친다).
  const [filtersOpen, setFiltersOpen] = useState(false);
  const addStrategy = useCallback((src: Parameters<PgState["addStrategy"]>[0]) => {
    const st = usePortfolioGraph.getState();
    st.act(() => st.addStrategy(src));
    setStratOpen(false);
    fit();
  }, [fit]);

  useViewFollow(s, rf, canvasEl, ctx, leftShown, rightShown, setPanels);
  const focused = s.groups.find((g) => g.id === s.focusGroup);

  /** 상자 끌기 한 번(R1) — 처음 움직인 때 한 번만 되돌리기 칸에 넣는다. */
  const frameDrag = useRef<{ id: string; recorded: boolean } | null>(null);
  /** 노드 끌기 시작 자리(R4) — 상자 그림은 끄는 동안 멤버를 따라 커지므로 넣기·빼기는 시작 자리의 상자로 판단한다. */
  const dragStart = useRef<PgNode[] | null>(null);
  /** 마우스 끌기 중(R6) — 앞서 dragging true 를 보았다. 화살표 이동(dragging false 만)과 구별한다. */
  const pointerDrag = useRef(false);
  /** 선 누르기(R6) — 마우스와 초점 둔 선의 Enter·Space 가 같은 길: 선 고름 + 오른쪽 창. */
  const pickEdge = useCallback((id: string) => {
    usePortfolioGraph.getState().selectEdge(id);
    updatePanels((p) => (p.right ? p : toggle(p, "right")));
  }, [updatePanels]);
  /** 묶음 상자를 끌면 안의 노드가 함께 움직인다 — 상자 자리는 노드에서 계산하므로 차이만 옮긴다. */
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const st = usePortfolioGraph.getState();
    const rest: NodeChange[] = [];
    // CF4a — 카드 하나를 끄는 중이면 다른 카드의 가장자리·가운데에 붙인다(여럿·묶음 상자는 붙이지 않는다). 위치는 격자(11)에 맞춘 뒤 오므로
    // 문턱은 화면 6px 에 격자 반 칸을 더한다 — 손이 6px 안으로 가져간 자리는 격자로 밀려도 붙는다.
    // 놓을 때(dragging false) React Flow 는 끌기 자리를 다시 보낸다 — 그 자리도 같은 규칙으로 붙여야 놓은 뒤 격자로 되밀리지 않는다.
    // 정렬선 붙이기는 ★마우스 끌기만★(R6) — 화살표 이동도 dragging false 로 와서, 줄 맞은 노드가 한 칸을 못 가고 다른 카드 선에 붙었다(관측 y 0 → 8).
    if (changes.some((c) => c.type === "position" && c.dragging === true)) pointerDrag.current = true;
    const drags = pointerDrag.current
      ? changes.filter((c) => c.type === "position" && typeof c.dragging === "boolean" && c.position && !c.id.includes(":")) : [];
    const c = drags.length === 1 ? drags[0] : null;
    if (c && c.type === "position" && c.position) {
      const at = c.position;
      const me = st.nodes.find((x) => x.id === c.id);
      if (me) {
        const box = (x: typeof me) => ({ w: measuredW(x) || cardWidth(x.data.kind), h: measuredH(x) || nodeHeight(x.data.kind, st.catalog, x.data.slotH) });
        const others = st.nodes.filter((x) => x.id !== c.id).map((x) => ({ x: x.position.x, y: x.position.y, ...box(x) }));
        const r = snapToGuides({ x: at.x, y: at.y, ...box(me) }, others, 6 / (rf.current?.getZoom() ?? 1) + SNAP / 2);
        c.position = { x: r.x, y: r.y };
        setGuides(c.dragging ? r.guides : []);
      }
    } else if (changes.some((c) => c.type === "position" && c.dragging === false)) {
      setGuides([]);
    }
    if (changes.some((c) => c.type === "position" && c.dragging === false)) pointerDrag.current = false;
    for (const c of changes) {
      if ("id" in c && c.id.startsWith("branch:")) continue;
      if ("id" in c && c.id.startsWith("frame:")) {
        if (c.type === "position" && c.position) {
          const frame = numbered.find((n) => n.id === c.id);
          if (frame) {
            // 상자 자리(멤버 − 여백 28)는 격자(11)에 맞지 않는다 — 움직인 양을 격자 배수로 맞춰 멤버가 격자를 지킨다(R1).
            const dx = Math.round((c.position.x - frame.position.x) / SNAP) * SNAP;
            const dy = Math.round((c.position.y - frame.position.y) / SNAP) * SNAP;
            const fd = frameDrag.current?.id === c.id ? frameDrag.current : (frameDrag.current = { id: c.id, recorded: false });
            if (st.moveGroup(c.id.slice(6), dx, dy, !fd.recorded)) fd.recorded = true;
          }
          if (c.dragging === false) frameDrag.current = null;
        }
        continue;
      }
      rest.push(c);
    }
    if (rest.length) st.onNodesChange(rest);
    // 상자에 끌어 넣기·빼기(R4) — 끄는 동안 넣을 상자를 빛내고, 놓으면 멤버를 옮긴다(끌기 한 단계에 함께 — 따로 기록하지 않는다).
    const moving = rest.filter((c) => c.type === "position" && typeof c.dragging === "boolean");
    if (moving.length) {
      dragStart.current ??= st.nodes;                                            // 이 바꾸기를 넣기 전 — 끌기 시작 자리
      const now = usePortfolioGraph.getState();
      const plan = boxDropPlan(moving.map((c) => (c as { id: string }).id), now.nodes, dragStart.current, now.groups, now.catalog, now.focusGroup);
      if (moving.some((c) => c.type === "position" && c.dragging)) {
        now.setDropGroups([...new Set(plan.moves.flatMap((m) => (m.to ? [m.to] : [])))]);
      } else {
        now.setDropGroups([]);
        dragStart.current = null;
        const note = now.applyBoxMembership(plan);
        if (note) now.setNote(note, plan.moves.length > 0);
      }
    }
  }, [numbered]);

  const { setValidateTick } = useDocSync(doc, s.catalog, persistWip && booted);

  const { isValidConnection, onReconnectStart, onReconnect, onReconnectEnd } = useWireHandlers();

  const { addAt, onConnectStart, onConnectEnd, quickPick, compareCheck, pickedIsOneGroup, ctxItems } =
    useQuickAdd(s, rf, canvasEl, addCount, connectFrom, quick, setQuick, ctx, setCtx, fit, setFindOpen, runToRef, wireToolRef);
  // 선 도구줄·선 우클릭(R5) — 끊기는 Delete 키와 같은 길·같은 문장(R2) · 넣기는 선 탭과 같은 후보 · 꺾는 점은 그린 선 가운데 · 묻기는 명령 `ask-here` 와 같은 길.
  wireToolRef.current = (edgeId, action, arg) => {
    const st = usePortfolioGraph.getState();
    if (action === "cut") st.act(() => deleteNote(st.deleteElements([], [edgeId])));
    else if (action === "insert" && arg) st.act(() => (st.insertOnEdge(edgeId, arg.kind, arg.inPort, arg.outPort) ? "선 사이에 노드를 넣었어요." : null));
    else if (action === "waypoint") {
      const w = drawnWire(edgeId);
      const e = st.edges.find((x) => x.id === edgeId);
      if (!w || !e) return;
      const p = snapPt(w.mid);
      st.addWaypoint(edgeId, insertAt(w.src, w.tgt, viaOf(e), p), p);
    } else if (action === "ask") {
      st.selectEdge(edgeId);
      updatePanels((p) => (p.right ? p : toggle(p, "right")));
      window.setTimeout(() => askFocus.current(), 60);
    }
  };


  const { applyLoad, loadTemplate, onDragOverCanvas, onDrop } = useCanvasDrop(rf, setFileNote, fit, setDragOver, setDropWire, addAt);

  const { run, paletteNext, runTo, swapTo, runStale, startGoal } = useRunActions(s, stages, rf, canvasEl, setQuick, setGoalOpen, fit,
    { needRef, socketRef, runToRef, runStrategyRef, branchStrategyRef, previewRef });

  const { toggleLanes, fitToLanes, toggleMinimap, setWire, toggleGhosts, commands } = useCanvasCommands(s, {
    run, runTo, updatePanels, fit, setCmdOpen, setFindOpen, setKeysOpen, setGoalOpen, setDrawer, focusRef, askFocus,
    leftShown, rightShown, panels, cmdOpen, openSay, ai, strategySources, addStrategy, loadTemplate, pickEdge });

  const focusNode = useCallback((id: string) => {
    usePortfolioGraph.getState().select(id);
    const n = usePortfolioGraph.getState().nodes.find((x) => x.id === id);
    if (n && rf.current) {
      // 떠 있는 판 사이의 가운데로(BQ Q1) — 캔버스 가운데는 창 밑일 수 있다.
      const z = rf.current.getZoom();
      const ins = floatInsets(canvasEl.current);
      // 카드 가운데(CF1 — 자리 고정 상자: 폭·높이는 카탈로그로 정한 값. 예전 +90/+60 은 폭 150 카드의 가운데였다).
      const cx = n.position.x + cardWidth(n.data.kind) / 2, cy = n.position.y + nodeHeight(n.data.kind, usePortfolioGraph.getState().catalog, n.data.slotH) / 2;
      rf.current.setCenter(cx + (ins.right - ins.left) / 2 / z, cy + ins.bottom / 2 / z, { zoom: z, duration: 250 });
    }
    const entry = usePortfolioGraph.getState().catalog?.find((c) => c.type === n?.data.kind);
    setAnnounce(n ? `${entry?.plain_label ?? n.data.kind} 노드를 골랐어요` : "");
  }, []);

  // ── BT2 절차 탭 ─────────────────────────────────────────────────────────
  const stageOf = useCallback((kind: string) => s.catalog?.find((c) => c.type === kind)?.stage, [s.catalog]);
  const gateLabel = useCallback((key: string) => s.catalogMeta?.gates.find((g) => g.key === key)?.label ?? key, [s.catalogMeta]);
  const gateStateOf = useCallback((key: string) =>
    (s.report ? s.report.gates?.gates.find((g) => g.key === key)?.state ?? null : null), [s.report]);
  const focusNodes = useCallback((ids: string[]) => {
    if (!ids.length || !rf.current) return;
    if (ids.length === 1) { focusNode(ids[0]); return; }
    rf.current.fitView({ nodes: ids.map((id) => ({ id })), padding: 0.35, duration: 250, maxZoom: 1.1 });
  }, [focusNode]);
  const applySuggestion = useCallback((sug: ProcedureSuggestion) => {
    const st = usePortfolioGraph.getState();
    // 유령이 보인 자리에 놓는다(CF6) — 바·절차 판·유령 어느 쪽에서 붙여도 같은 자리.
    const at = ghostsRef.current.find((g) => g.key === suggestionKey(sug))?.at ?? undefined;
    st.act(() => {
      const id = st.applySuggestion(sug, at);
      return id ? `‘${sug.label}’를 붙이고 이었어요.` : "선을 이었어요.";
    });
  }, []);
  fixRef.current = applySuggestion;
  /** 노드 번호(캔버스 흐름 순서 — 카드 머리 번호와 같다)와 쉬운 이름. */
  const nodeBadge = useCallback((id: string) => {
    const n = s.nodes.find((x) => x.id === id);
    const e = s.catalog?.find((c) => c.type === n?.data.kind);
    const num = order.indexOf(id);
    return { num: num >= 0 ? num + 1 : null, name: e?.plain_label ?? n?.data.kind ?? id };
  }, [s.nodes, s.catalog, order]);
  const nodeLabel = useCallback((id: string) => {
    const b = nodeBadge(id);
    return `${b.num ? `${b.num}. ` : ""}${b.name}`;
  }, [nodeBadge]);
  // BT3 — 다음 한 걸음(서버). [다음에] 는 이 그래프 모양(노드 종류 모음)에 대해 이번 방문 동안만 숨긴다.
  // CF6 — 유령과 하나: 숨김 키 = 모양 + 추천(같은 추천이면 바 [다음에]와 유령 [닫기]가 같다).
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const shapeKey = useMemo(() => [...new Set(s.nodes.map((n) => n.data.kind))].sort().join(","), [s.nodes]);
  const dismiss = useCallback((sug: ProcedureSuggestion) => setDismissed((d) => new Set(d).add(`${shapeKey}|${suggestionKey(sug)}`)), [shapeKey]);
  const procNext = s.validation?.procedure?.next ?? null;
  const nextStep = procNext && !dismissed.has(`${shapeKey}|${suggestionKey(procNext)}`) ? procNext : null;
  // CF6 — 유령: next 먼저 + 막힌 관문, 서로 다른 것만 최대 3 · 자리는 앞선 유령도 피한다.
  const ghosts = useMemo<PlacedGhost[]>(() => {
    // AI4 — 초안을 미리 보는 동안은 초안만(규칙·AI 유령이 같은 자리를 다투지 않게). 버리거나 받아들이면 돌아온다.
    if (!s.showGhosts || s.simple || !s.validation?.procedure || draftQ.draft) return [];
    const place = placeNodes(s.nodes);
    const taken: Box[] = [];
    const ids = s.nodes.map((n) => n.id);
    // AI1 — 서버가 검사를 통과시킨 AI 추천을 같은 그릇에(규칙과 같은 추천이면 두 칩 하나) — 숨김·자리·붙이기는 그대로.
    return withAiGhosts(ghostSuggestions(s.validation.procedure, ids), ai.suggestions, ids)
      .filter((g) => !dismissed.has(`${shapeKey}|${g.key}`))
      .map((g) => {
        if (g.action !== "add" || !g.kind) {
          const chip = placeConnectChip(g, place, s.catalog, taken);
          if (chip) taken.push({ x: chip.x, y: chip.y, w: NODE_W, h: CHIP_H });
          return { ...g, at: null, chip };
        }
        const at = placeSuggestion(g, place, s.catalog, taken);
        taken.push({ x: at.x, y: at.y, w: NODE_W, h: cardHeight(g.kind, s.catalog) });
        return { ...g, at, chip: null };
      });
  }, [s.showGhosts, s.simple, s.validation, s.nodes, s.catalog, dismissed, shapeKey, ai.suggestions, draftQ.draft]);
  ghostsRef.current = ghosts;
  const [ghostHot, setGhostHot] = useState<string | null>(null);
  /** AI 묻기 칸 — 추천 유령을 보이는 동안만(끄면 물을 곳도 없다). */
  const aiShown = s.showGhosts && !s.simple;
  // AI1 — 새 답의 AI 유령이 떠 있는 판 밑이나 화면 밖이면 그쪽을 판 사이 가운데로 옮겨 보인다(확대는 그대로 · focusNode 와 같은 식).
  // 물은 사람은 답을 봐야 한다 — 오른쪽 창 밑에 깔린 유령은 [붙이기]를 누를 수도 없었다(AI1 E2E 가 찾음).
  useEffect(() => {
    if (ai.ai.state !== "ready" || !rf.current || !canvasEl.current) return;
    const boxes = ghostsRef.current.filter((g) => g.aiReason !== null && g.at)
      .map((g) => ({ x: g.at!.x, y: g.at!.y, w: NODE_W, h: cardHeight(g.kind!, usePortfolioGraph.getState().catalog) }));
    if (!boxes.length) return;
    const { x: tx, y: ty, zoom } = rf.current.getViewport();
    const el = canvasEl.current;
    const ins = floatInsets(el);
    const l = Math.min(...boxes.map((b) => b.x)), r = Math.max(...boxes.map((b) => b.x + b.w));
    const t = Math.min(...boxes.map((b) => b.y)), bt = Math.max(...boxes.map((b) => b.y + b.h));
    const seen = l * zoom + tx >= ins.left && r * zoom + tx <= el.clientWidth - ins.right && t * zoom + ty >= 0 && bt * zoom + ty <= el.clientHeight - ins.bottom;
    if (!seen) rf.current.setCenter((l + r) / 2 + (ins.right - ins.left) / 2 / zoom, (t + bt) / 2 + ins.bottom / 2 / zoom, { zoom, duration: 250 });
  }, [ai.ai]);
  // AI5 — 길잡이(아래 바 세 번째 자리). 상태는 화면이 센 수·참거짓 — 서버로도 간다(설정값·종목 없음).
  const kindOf = useCallback((id: string) => s.nodes.find((n) => n.id === id)?.data.kind, [s.nodes]);
  const isWeight = useCallback((id: string) => !!s.catalog?.find((c) => c.type === kindOf(id))?.outputs.some((o) => o.type === "Weights"),
    [s.catalog, kindOf]);
  const guideState = useMemo<GuideState>(() => {
    const res = Object.values(s.report?.nodes ?? {});
    return {
      computed: !!s.report, fresh: !!s.report && !s.reportStale,
      ready_to_run: s.nodes.length > 0 && !!s.validation?.procedure && s.validation.procedure.next === null && !(s.validation.errors ?? []).length,
      nodes: s.nodes.length,
      failed: res.filter((r) => r.status === "failed" || r.status === "blocked").length,
      wire_issues: Object.values(s.report?.edges ?? {}).filter((r) => (r.issues ?? []).length > 0).length,
      weight_nodes: s.nodes.filter((n) => isWeight(n.id)).length,
      branches: s.branches.length,
      robustness: s.nodes.some((n) => n.data.kind === COMPARE_KIND || n.data.kind === RECORD_KIND),
      overlapping: cardsOverlap(s.nodes, s.catalog),
      lanes: s.showLanes, minimap: s.showMinimap,
      backtest: Object.entries(s.report?.nodes ?? {}).some(([id, r]) => r.status === "ok" && kindOf(id) === "backtest"),
      gates_blocked: (s.report?.gates?.gates ?? []).filter((g) => ["failed", "unknown", "skipped", "partial"].includes(g.state)).map((g) => g.key),
    };
  }, [s.report, s.reportStale, s.nodes, s.validation, s.branches, s.catalog, s.showLanes, s.showMinimap, isWeight, kindOf]);
  const guideDismissed = useMemo(() => new Set([...dismissed].filter((k) => k.startsWith("guide|")).map((k) => k.slice(6))), [dismissed]);
  const guide = useGuide(doc, guideState, guideDismissed, session);
  /** [해 보기] — 그 도구를 실제로 쓰고, 안내 줄에 ★다음엔 어디서 하나★를 붙인다(길잡이는 도구가 어디 있는지 가르친다). 바꾸는 것은 되돌리기 한 번. */
  const tryTool = (id: GuideId) => {
    const st = usePortfolioGraph.getState();
    const where = toolOf(id)?.where ?? "";
    const say = (msg: string) => st.setNote(`${msg} · ${where}`, false, true);
    const openRight = () => updatePanels((p) => (p.right ? p : toggle(p, "right")));
    switch (id) {
      case "cause": {
        const f = order.find((nid) => ["failed", "blocked"].includes(st.report?.nodes[nid]?.status ?? ""));
        if (f) { focusNode(f); st.showCause(f); say("처음 막힌 곳부터 거슬러 보여 드려요"); }
        return;
      }
      case "wire_check": {
        const eid = Object.entries(st.report?.edges ?? {}).find(([, r]) => (r.issues ?? []).length > 0)?.[0];
        if (eid) { onFlag(eid); say("빠지거나 바뀐 것이 있는 선을 열었어요"); }
        return;
      }
      case "run": void run(); say("계산하고 있어요"); return;
      case "layout": st.autoLayout(); fit(); say("흐름 순서대로 다시 놓았어요"); return;
      case "branch": {
        const root = order.find(isWeight);
        if (root) st.act(() => `${st.makeBranch(root)} · ${where}`);
        return;
      }
      case "strategy_add": setStratOpen(true); say("무엇을 더할지 골라 주세요"); return;
      case "compare": {
        usePortfolioGraph.setState({ picked: order.filter(isWeight).slice(0, 4), pickedByUser: true });
        st.act(() => `${usePortfolioGraph.getState().comparePicked()} · ${where}`);
        return;
      }
      case "story_ai":
        openRight(); st.select(null); st.selectEdge(null); st.setTab("story");
        requestAnimationFrame(() => (document.querySelector(".pg-ai-story-ask, .pg-ai-story-login") as HTMLElement | null)?.focus());
        say("이야기 탭 맨 위에서 AI 로 풀어 쓸 수 있어요");
        return;
      case "ask_ai": {
        const t = [...order].reverse().find(isWeight) ?? order[order.length - 1];
        if (t) { focusNode(t); openRight(); window.setTimeout(() => askFocus.current(), 60); say("고른 노드에게 물어보세요"); }
        return;
      }
      case "records": setDrawer("records"); say("기록함을 열었어요"); return;
      case "lanes": if (!st.showLanes) toggleLanes(); say("단계 레인을 켰어요"); return;
      case "minimap": if (!st.showMinimap) toggleMinimap(); say("미니맵을 켰어요"); return;
    }
  };
  const hereStep = stepOfNode(s.validation?.procedure, s.selectedId)?.key ?? null;
  const procedureView = (
    <ProcedurePanel procedure={s.validation?.procedure ?? null} error={s.validationError}
                    gateLabel={gateLabel} gateState={gateStateOf} hereStep={hereStep} stageOf={stageOf}
                    onHover={(ids) => usePortfolioGraph.getState().setProcHover(ids)} onFocusNodes={focusNodes}
                    onApply={applySuggestion} onRetry={() => setValidateTick((t) => t + 1)} />
  );

  focusRef.current = focusNode;

  // R8 — React Flow 에 넘기는 손잡이는 늘 같은 함수(몸은 그대로 · ref 로 마지막 것을 부른다). 그릴 때마다 새 함수를 넘기면 카드·선
  // 감싸개가 모두 다시 그려졌다(200노드 끌기 한 걸음 = 감싸개 400개 — 재서 찾음).
  const rfOn = useLatestHandlers({
    onNodeContextMenu: (e: ReactMouseEvent, n: Node) => {
      e.preventDefault();
      if (n.id.startsWith("frame:") || n.id.startsWith("branch:")) return;
      const box = canvasEl.current?.getBoundingClientRect();
      // 여럿 고른 것 안의 노드면 고르기를 지킨다(R1) — 메뉴의 '고른 노드' 동작이 그 여럿을 대상으로 한다.
      if (!(s.picked.length > 1 && s.picked.includes(n.id))) s.select(n.id);
      setCtx({ x: e.clientX - (box?.left ?? 0), y: e.clientY - (box?.top ?? 0), clientX: e.clientX, clientY: e.clientY, nodeId: n.id });
    },
    onSelectionContextMenu: (e: ReactMouseEvent, sel: Node[]) => {
      // Shift 상자로 고르면 고른 노드 위에 고르기 상자가 덮인다 — 그 아래 노드의 메뉴를 연다(R1). 고르기는 그대로.
      e.preventDefault();
      const hit = document.elementsFromPoint(e.clientX, e.clientY)
        .map((el) => el.closest(".pg-node")?.getAttribute("data-node-id")).find((id): id is string => !!id);
      const id = hit ?? sel.find((x) => !x.id.includes(":"))?.id;
      if (!id) return;
      const box = canvasEl.current?.getBoundingClientRect();
      setCtx({ x: e.clientX - (box?.left ?? 0), y: e.clientY - (box?.top ?? 0), clientX: e.clientX, clientY: e.clientY, nodeId: id });
    },
    onBeforeDelete: async ({ nodes, edges }: { nodes: Node[]; edges: Edge[] }) => {
      // React Flow 는 선을 먼저, 노드를 나중에 바꾼다(되돌리기 두 단계) — 여기서 한 번에 지우고 React Flow 의 지우기는 막는다(R1).
      const st = usePortfolioGraph.getState();
      st.act(() => deleteNote(st.deleteElements(nodes.map((x) => x.id).filter((id) => !id.includes(":")), edges.map((x) => x.id))));
      return false;
    },
    onEdgeContextMenu: (e: ReactMouseEvent, edge: Edge) => {
      // 선 우클릭(R5) — 그 선을 고르고 선 메뉴(도구줄과 같은 넷 · 접힌 상자의 대리 선이면 까닭 + 펼치기).
      e.preventDefault();
      usePortfolioGraph.getState().selectEdge(edge.id);
      const box = canvasEl.current?.getBoundingClientRect();
      setCtx({ x: e.clientX - (box?.left ?? 0), y: e.clientY - (box?.top ?? 0), clientX: e.clientX, clientY: e.clientY, nodeId: null, edgeId: edge.id, mode: "edge" });
    },
    onPaneContextMenu: (e: ReactMouseEvent | MouseEvent) => {
      e.preventDefault();
      const box = canvasEl.current?.getBoundingClientRect();
      setCtx({ x: e.clientX - (box?.left ?? 0), y: e.clientY - (box?.top ?? 0), clientX: e.clientX, clientY: e.clientY, nodeId: null });
    },
    onNodeClick: (e: ReactMouseEvent, n: Node) => { if (!n.id.startsWith("frame:") && !(e.shiftKey || e.metaKey || e.ctrlKey)) s.select(n.id); },
    onPaneClick: () => { s.select(null); s.selectEdge(null); if (s.cause) s.showCause(null); },
    onEdgeMouseEnter: (_: ReactMouseEvent, e: Edge) => setHoverEdge(e.id),
    onEdgeMouseLeave: () => setHoverEdge(null),
    onEdgeClick: (_: ReactMouseEvent, e: Edge) => pickEdge(e.id),
    onNodeDoubleClick: (_: ReactMouseEvent, n: Node) => { if (n.id.startsWith("frame:")) s.setFocusGroup(n.id.slice(6)); },
  });

  const selected = s.nodes.find((n) => n.id === s.selectedId);
  const selEdge = s.selectedEdge ? s.edges.find((e) => e.id === s.selectedEdge) ?? null : null;
  const selEntry = s.catalog?.find((c) => c.type === selected?.data.kind);
  const selResult = selected ? s.report?.nodes[selected.id] : undefined;
  const nErrors = s.validation?.errors.length ?? 0;

  return (
    <div className="pg-root pg-theme" data-left={leftShown ? "open" : "closed"} data-right={rightShown ? "open" : "closed"}
         data-simple={s.simple || undefined} data-tight={tight || undefined} style={{ "--pg-right-w": `${panels.rightW}px` } as CSSProperties}>
      <CanvasToolbar s={s} fit={fit} setGoalOpen={setGoalOpen} stratOpen={stratOpen} setStratOpen={setStratOpen}
                     strategySources={strategySources} addStrategy={addStrategy} toggleMinimap={toggleMinimap} toggleLanes={toggleLanes}
                     fitToLanes={fitToLanes} setWire={setWire} toggleGhosts={toggleGhosts} setCmdOpen={setCmdOpen} nErrors={nErrors}
                     runStale={runStale} applyLoad={applyLoad} drawer={drawer} setDrawer={setDrawer} topExtra={topExtra} run={run} />


      {s.catalogError && (
        <p className="pg-banner pg-banner--err">노드 목록을 불러오지 못했어요 — {s.catalogError}. 서버가 켜져 있는지 확인해 주세요.</p>
      )}
      {s.runError && <p className="pg-banner pg-banner--err">계산 요청이 실패했어요 — {s.runError}</p>}
      {legacy && (
        <div className="pg-banner pg-legacy" role="note">
          <span>예전 ‘{legacy.title}’ 화면은 이제 이 캔버스에서 해요. {legacy.nodes.length
            ? "그 일을 하는 노드를 왼쪽 목록에 찾아 두었어요."
            : "요약은 캔버스 전체와 이야기 탭이 그 자리를 대신해요."}</span>
          {legacy.template && (
            <button type="button" className="pg-btn pg-legacy-template" onClick={() => loadTemplate(legacy.template!)}>
              ‘{TEMPLATES.find((t) => t.key === legacy.template)?.name ?? legacy.template}’ 흐름 열기
            </button>
          )}
          {legacy.drawer && (
            <button type="button" className="pg-btn pg-legacy-drawer" onClick={() => setDrawer(legacy.drawer!)}>
              {DRAWERS.find((d) => d.key === legacy.drawer)?.label ?? legacy.drawer} 서랍 열기
            </button>
          )}
        </div>
      )}
      {s.loadProblems.length > 0 && (
        <div className="pg-banner pg-banner--warn pg-load-problems">
          불러오면서 건너뛴 항목이 {s.loadProblems.length}개 있어요:
          <ul>{s.loadProblems.map((p, i) => <li key={i}>{p}</li>)}</ul>
        </div>
      )}
      {(s.validation?.errors ?? []).filter((e) => !e.node_id).map((e, i) => (
        <p key={i} className="pg-banner pg-banner--err">{e.message}</p>
      ))}

      <ShortcutSheet open={keysOpen} onClose={() => setKeysOpen(false)} />
      <GoalStart open={goalOpen} onClose={() => setGoalOpen(false)} catalog={s.catalog ?? []} onStart={startGoal} />
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} catalog={s.catalog ?? []} commands={commands}
                      onAddNode={(k) => addAt(k)} />
      {DRAWERS.map((d) => (
        <Sheet key={d.key} testId={d.key} className="pg-sheet" open={drawer === d.key} onClose={() => setDrawer(null)} title={d.label} sub={d.sub}>
          <d.Body />
        </Sheet>
      ))}

      {/* 진행상황 알약(BQ Q2) — 캔버스 위 가운데. 간단히 보기에서는 그 위에 한 줄로. */}
      {s.simple && <GateRail report={s.report?.gates ?? null} stale={s.reportStale}
                  note={s.report?.partial ? s.report.gates_reason ?? null : null}
                  byGate={s.validation?.procedure?.by_gate ?? null} nodeLabel={nodeLabel} nodeBadge={nodeBadge}
                  onFocusNode={focusNode} onApply={applySuggestion} />}
      {s.simple && (
        <SimpleView nodes={s.nodes} edges={s.edges} groups={s.groups} catalog={s.catalog ?? []}
                    results={s.report?.nodes ?? null} staleIds={staleSet} running={s.running} onRun={() => void run()}
                    onChange={(id, p) => s.updateParams(id, p)}
                    onCause={(id) => { s.setSimple(false); s.select(id); setTimeout(() => usePortfolioGraph.getState().showCause(id), 60); }} />
      )}
      <div className="pg-body" hidden={s.simple}>
        {s.catalog && <NodePalette catalog={s.catalog} stages={stages} initialQuery={legacy?.aliases[1] ?? ""} onAdd={(k) => addAt(k)} onTemplate={loadTemplate}
                                  onGoal={() => setGoalOpen(true)} hidden={!leftShown} onClose={() => updatePanels((p) => toggle(p, "left"))}
                                  tab={leftTab ?? "add"} onTab={setLeftTab} procedure={procedureView} next={paletteNext}
                                  say={<DraftPanel d={draftQ} session={session} catalog={s.catalog} plain={s.catalogMeta?.portPlain ?? PORT_PLAIN}
                                                   nameOf={nodeLabel} kindOf={kindOf} onAccept={acceptDraft} inputRef={sayInput} />} />}
        {!leftShown && (
          <button type="button" className="pg-palette-fab" aria-label="노드 목록 열기 ([)" title="노드 추가 — 목록 열기 ([)"
                  onClick={() => updatePanels((p) => toggle(p, "left"))}><Plus size={20} aria-hidden="true" /></button>
        )}
        <div ref={canvasEl} className={`pg-canvas${dragOver ? " pg-canvas--drop" : ""}${s.growing ? " pg-growing" : ""}`}
             style={{ "--pg-node-w": NODE_W, "--pg-brief-w": `${BRIEF_MAX_W}px` } as React.CSSProperties}
             onDragOver={onDragOverCanvas}
             onDragLeave={() => { setDragOver(false); setDropWire(null); }}
             onDrop={onDrop}>
          <ReactFlow
            nodes={numbered}
            edges={edgesStyled}
            nodeTypes={NODE_TYPES}
            edgeTypes={EDGE_TYPES}
            minZoom={MIN_ZOOM}
            onNodesChange={onNodesChange}
            onEdgesChange={s.onEdgesChange}
            onConnect={s.connect}
            onConnectStart={onConnectStart}
            onConnectEnd={onConnectEnd}
            isValidConnection={isValidConnection}
            connectionLineComponent={WireDragLine}
            onReconnectStart={onReconnectStart}
            onReconnect={onReconnect}
            onReconnectEnd={onReconnectEnd}
            onNodeContextMenu={rfOn.onNodeContextMenu}
            onSelectionContextMenu={rfOn.onSelectionContextMenu}
            onBeforeDelete={rfOn.onBeforeDelete}
            onEdgeContextMenu={rfOn.onEdgeContextMenu}
            onPaneContextMenu={rfOn.onPaneContextMenu}
            snapToGrid
            snapGrid={SNAP_GRID}
            // v12 의 인스턴스는 노드·선 타입을 제네릭으로 싣는다 — 이 파일은 일반 Node/Edge 로만 부른다.
            onInit={(inst) => { rf.current = inst as unknown as ReactFlowInstance; }}
            onNodeClick={rfOn.onNodeClick}
            onPaneClick={rfOn.onPaneClick}
            onEdgeMouseEnter={rfOn.onEdgeMouseEnter} onEdgeMouseLeave={rfOn.onEdgeMouseLeave}
            onEdgeClick={rfOn.onEdgeClick}
            onNodeDoubleClick={rfOn.onNodeDoubleClick}
            deleteKeyCode={drawer || cmdOpen ? null : DELETE_KEYS}
            multiSelectionKeyCode={MULTI_SELECT_KEYS}
            selectionMode={SelectionMode.Partial}
            ariaLabelConfig={ARIA_KO}
            defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
            fitView
            fitViewOptions={FIT_VIEW_OPTIONS}
            proOptions={PRO_OPTIONS}
          >
            {/* CF0 — v12 는 점을 칸 가운데로 옮긴다(offset 0 = 칸 절반). v11 처럼 칸 모서리에 두려면 (점 크기 − 칸) / 2. */}
            {/* CF4a — 격자 두 겹: 점(22)을 ★먼저★(바탕 대비 테스트가 첫 무늬를 잰다) · 큰 칸 선(110 = 점 다섯 칸, 점 자리를 지난다). */}
            <Background id="pg-grid-dots" variant={BackgroundVariant.Dots} gap={22} size={1.5} offset={(1.5 - 22) / 2} color="var(--pg-dot)" />
            <Background id="pg-grid-lines" variant={BackgroundVariant.Lines} gap={110} lineWidth={1} color="var(--pg-grid-line)"
                        bgColor="transparent" className="pg-grid-lines" />
            {guides.length > 0 && (
              <ViewportPortal>
                <svg className="pg-guides" aria-hidden="true">
                  {guides.map((g, i) => (g.axis === "x"
                    ? <line key={i} className="pg-guide" data-axis="x" x1={g.at} x2={g.at} y1={g.from - 12} y2={g.to + 12} />
                    : <line key={i} className="pg-guide" data-axis="y" x1={g.from - 12} x2={g.to + 12} y1={g.at} y2={g.at} />))}
                </svg>
              </ViewportPortal>
            )}
            {s.showLanes && <StageLanes stages={stages} />}
            {ghosts.length > 0 && (
              <GhostLayer ghosts={ghosts} catalog={s.catalog} shape={s.wireShape} hot={ghostHot} gateLabel={gateLabel}
                          onApply={applySuggestion} onDismiss={dismiss} />
            )}
            {draftQ.draft && <DraftLayer draft={draftQ.draft} at={draftAt} catalog={s.catalog} shape={s.wireShape} />}
            <ZoomWatch el={canvasEl} />
            {focused && (
              <Panel position="top-center" className="pg-crumb" aria-label="지금 보는 곳">
                <button type="button" className="pg-crumb-root" onClick={() => { s.setFocusGroup(null); fit(); }}>포트폴리오</button>
                <span aria-hidden="true">›</span>
                <b>{focused.label}</b>
                <button type="button" className="pg-cause-clear" onClick={() => { s.setFocusGroup(null); fit(); }}>나가기 <kbd>Esc</kbd></button>
              </Panel>
            )}
            {live && (
              <Panel position="top-right" className="pg-filters" aria-label="상태로 걸러 보기">
                <button type="button" className="pg-filters-toggle" aria-expanded={filtersOpen}
                        onClick={() => setFiltersOpen((o) => !o)}>
                  <Filter size={13} aria-hidden="true" />걸러 보기{s.filters.length ? ` · ${s.filters.length}` : ""}
                </button>
                {filtersOpen && FILTERS.map(([k, label]) => {
                  const n = Object.values(live).filter((r) => matchFilter(k, r)).length;
                  return (
                    <button key={k} type="button" className="pg-filter" data-filter={k} aria-pressed={s.filters.includes(k)}
                            disabled={n === 0 && !s.filters.includes(k)} onClick={() => s.toggleFilter(k)}>
                      {label} <span className="pg-filter-n">{n}</span>
                    </button>
                  );
                })}
              </Panel>
            )}
            {live && (
              <Panel position="top-left" className="pg-wire-legend" aria-label="선 모양 읽는 법">
                {WIRE_LEGEND.map((w) => (
                  <span key={w.key} className={`pg-wire-key pg-wire-key--${w.key}`} title={w.help}>
                    <svg width="26" height="8" aria-hidden="true"><line x1="1" y1="4" x2="25" y2="4" /></svg>{w.label}
                  </span>
                ))}
              </Panel>
            )}
            {cause && (
              <Panel position="top-center" className="pg-cause-banner" role="status">
                <span>
                  {cause.roots.length === 1 && cause.roots[0] === cause.from ? "이 노드가 첫 원인이에요" : "첫 원인"}
                  {" — "}
                  {cause.roots.map((r) => {
                    const n = s.nodes.find((x) => x.id === r);
                    const name = s.catalog?.find((c) => c.type === n?.data.kind)?.plain_label ?? n?.data.kind ?? r;
                    return (
                      <button key={r} type="button" className="pg-cause-root-btn" onClick={() => focusNode(r)}
                              title={live?.[r]?.reason ?? undefined}>
                        {name}: {live?.[r]?.explain?.facts?.[0] ?? live?.[r]?.reason ?? "사유 없음"}
                      </button>
                    );
                  })}
                </span>
                <button type="button" className="pg-cause-clear" onClick={() => s.showCause(null)}>다 보기 <kbd>Esc</kbd></button>
              </Panel>
            )}
            {/* 고른 노드 위 작은 막대(BR R1b) — 둘 이상 고르면 묶기 · 견고성 비교. 조건이 안 되면 단추는 흐리고, 누르면 사유를 안내 줄로. */}
            {/* 고른 노드 **아래**에 — 전략·묶음 상자의 머리는 위에 있어, 위에 띄우면 상자 머리 단추를 가렸다(E2E 가 찾음).
                고른 것이 한 상자의 구성원 전부면(방금 묶었을 때) 상자 머리가 그 역할을 하므로 띄우지 않는다. */}
            {!s.simple && s.picked.length > 1 && !pickedIsOneGroup && (
              <SelBar ids={s.picked}>
                <span className="pg-selbar-n">{s.picked.length}개 골랐어요</span>
                <AlignMenu n={s.picked.length} onPick={(k) => usePortfolioGraph.getState().alignPicked(k)} />
                <button type="button" className="pg-selbar-b" onClick={() => usePortfolioGraph.getState().groupPicked()}
                        title="고른 노드를 상자로 묶어요 (Ctrl+G)">
                  <Boxes size={14} aria-hidden="true" /> 묶기
                </button>
                <button type="button" className="pg-selbar-b pg-selbar-compare" aria-disabled={!compareCheck.ok || undefined}
                        title={compareCheck.ok ? "고른 노드를 ‘견고성 비교’에 이어요 — 같이 무너지는지 봐요" : compareCheck.reason}
                        onClick={() => { const st = usePortfolioGraph.getState(); st.act(() => st.comparePicked()); }}>
                  <Scale size={14} aria-hidden="true" /> 견고성 비교
                </button>
                <button type="button" className="pg-selbar-b pg-selbar-branch"
                        title="고른 노드만 복제해 갈래를 만들어요 — 뿌리는 흐름 맨 앞, 밖으로 나가는 선은 잇지 않아요"
                        onClick={() => { const st = usePortfolioGraph.getState(); st.act(() => st.branchPicked()); }}>
                  <GitBranch size={14} aria-hidden="true" /> 갈래
                </button>
              </SelBar>
            )}
            {/* 확대·축소는 떠 있는 판 사이 가운데를 기준으로(BQ Q1) — 기본 단추는 판 뒤 캔버스 가운데를 기준으로 해 노드를 창 밑으로 민다. */}
            <Controls showZoom={false} showFitView={false} showInteractive={false}>
              <ControlButton className="react-flow__controls-zoomin" title="확대" aria-label="확대" onClick={() => zoomBy(1.2)}><Plus size={14} aria-hidden="true" /></ControlButton>
              <ControlButton className="react-flow__controls-zoomout" title="축소" aria-label="축소" onClick={() => zoomBy(1 / 1.2)}><Minus size={14} aria-hidden="true" /></ControlButton>
              <ZoomPct onReset={(z) => zoomBy(1 / z)} />
              <ControlButton className="react-flow__controls-fitview" title="맞춰 보기" aria-label="맞춰 보기"
                             onClick={() => fitClear(rf.current, canvasEl.current)}><Maximize size={13} aria-hidden="true" /></ControlButton>
            </Controls>
            {s.showMinimap && (
              <>
                {/* CF5b — 칸 = 단계색(전략 띠 구성원은 띠 색) · 테두리 = 고름 파랑 > 실패 빨강 > 막힘 주황(지금 결과만 — 낡은 결과는 칠하지 않는다). */}
                <MiniMap pannable zoomable ariaLabel="미니맵" className="pg-minimap" nodeStrokeWidth={24}
                         nodeColor={(n) => (n.type === PG_GROUP_TYPE ? "transparent"
                           : bandOf.has(n.id) ? `var(--pg-band-${bandOf.get(n.id)})` : STAGE_VAR[stageOfNode(n.id) ?? ""] ?? "var(--pg-line)")}
                         nodeStrokeColor={(n) => { const k = mmMark(n.id); return k === "picked" ? "var(--pg-blue)" : k === "failed" ? "var(--pg-fail)"
                           : k === "blocked" ? "var(--pg-assume)" : "transparent"; }}
                         nodeClassName={(n) => { const st = stageOfNode(n.id), k = mmMark(n.id);
                           return ["pg-mm", st && `pg-mm--stage-${st}`, k && `pg-mm--${k}`].filter(Boolean).join(" "); }} />
                <button type="button" className="pg-minimap-fold nodrag nopan" aria-label="미니맵 접기" title="미니맵 접기" onClick={toggleMinimap}>
                  <X size={13} aria-hidden="true" />
                </button>
              </>
            )}
          </ReactFlow>
          <p className="pg-sr-live" aria-live="polite">{announce}</p>
          {!s.simple && <GateRail report={s.report?.gates ?? null} stale={s.reportStale}
                  note={s.report?.partial ? s.report.gates_reason ?? null : null}
                  byGate={s.validation?.procedure?.by_gate ?? null} nodeLabel={nodeLabel} nodeBadge={nodeBadge}
                  onFocusNode={focusNode} onApply={applySuggestion} />}
          {s.catalog && s.nodes.length === 0 && (
            <div className="pg-empty-start">
              <p>비어 있어요. 무엇을 하려는지 고르면 흐름을 만들어 드려요.</p>
              <button type="button" className="pg-btn pg-btn--primary" onClick={() => setGoalOpen(true)}>
                <Sparkles size={14} aria-hidden="true" /> 목표로 시작
              </button>
            </div>
          )}
          {welcome && !dragOver ? (
            <div className="pg-welcome" role="region" aria-label="처음 오셨을 때">
              <p>처음이세요? 하려는 일을 고르면 흐름을 만들어 드려요.</p>
              <button type="button" className="pg-welcome-go" onClick={() => { closeWelcome(); setGoalOpen(true); }}>
                <Sparkles size={14} aria-hidden="true" /> 목표로 시작
              </button>
              <button type="button" className="pg-welcome-x" aria-label="환영 안내 닫기" onClick={closeWelcome}>
                <X size={14} aria-hidden="true" />
              </button>
            </div>
          ) : nextStep && !dragOver && s.picked.length <= 1 && !s.selectedId ? (
            <div className="pg-hint pg-next" role="region" aria-label="다음 한 걸음"
                 onMouseEnter={() => setGhostHot(suggestionKey(nextStep))} onMouseLeave={() => setGhostHot(null)}
                 onFocus={() => setGhostHot(suggestionKey(nextStep))} onBlur={() => setGhostHot(null)}>
              <p className="pg-next-text">{nextStep.text}</p>
              <button type="button" className="pg-next-go" onClick={() => applySuggestion(nextStep)}>
                {nextStep.action === "connect" ? "잇기" : "붙이기"}
              </button>
              <button type="button" className="pg-next-later" onClick={() => dismiss(nextStep)}>다음에</button>
              {aiShown && <AiAsk session={session} ai={ai.ai} onAsk={() => { void ai.ask(); }} />}
            </div>
          ) : guide.tip && !dragOver && s.picked.length <= 1 && !s.selectedId && !s.selectedEdge && s.nodes.length > 0 ? (
            <GuideBar g={guide} session={session} onTry={tryTool}
                      onLater={(id) => setDismissed((d) => new Set(d).add(`guide|${id}`))}
                      extra={aiShown ? <AiAsk session={session} ai={ai.ai} onAsk={() => { void ai.ask(); }} /> : null} />
          ) : <div className="pg-hint">{dragOver ? "그래프 파일을 놓으면 바로 불러와요"
            : s.picked.length > 1 ? `${s.picked.length}개 골랐어요 · Ctrl+G 묶기 · Ctrl+C 복사 · Delete 지우기`
            : s.selectedId ? "Alt+←→ 앞·뒤 단계로 · Alt+↑↓ 번호 순서로 · Shift+Enter 여기까지 계산"
            : "노드를 끌어 놓고, 같은 색 점끼리 이어 보세요. 선을 빈 곳에 놓으면 이을 노드를 찾아요 · 단축키 ?"}
            {aiShown && !dragOver && <AiAsk session={session} ai={ai.ai} onAsk={() => { void ai.ask(); }} />}</div>}
          {quick && s.catalog && (
            <QuickAdd at={quick} catalog={s.catalog} stageKeys={stages.map((x) => x.key)}
                      fromKind={quick.from ? s.nodes.find((n) => n.id === quick.from!.node)?.data.kind ?? null : null}
                      box={canvasEl.current?.getBoundingClientRect()} inset={floatInsets(canvasEl.current)} onPick={quickPick} onClose={() => setQuick(null)} />
          )}
          {ctx && (
            <ContextMenu x={ctx.x} y={ctx.y} box={canvasEl.current?.getBoundingClientRect()} inset={floatInsets(canvasEl.current)} items={ctxItems}
                         label={ctx.edgeId ? "선 메뉴" : ctx.nodeId ? "노드 메뉴" : "캔버스 메뉴"} onClose={() => setCtx(null)} />
          )}
          {findOpen && (
            <FindBar onPick={(id) => focusRef.current(id)} onClose={() => setFindOpen(false)}
                     nodes={s.nodes.map((n) => {
                       const entry = s.catalog?.find((c) => c.type === n.data.kind);
                       return { id: n.id, label: entry?.plain_label ?? n.data.kind, sub: nodeSummary(entry, n.data.params ?? {}) ?? n.id };
                     })} />
          )}
        </div>
        <RightPanel s={s} rightShown={rightShown} panels={panels} updatePanels={updatePanels} setPanels={setPanels} selected={selected}
                    selEdge={selEdge} selEntry={selEntry} selResult={selResult} order={order} staleSet={staleSet} stages={stages}
                    focusNode={focusNode} nodeBadge={nodeBadge} session={session} aiStory={aiStory} askTarget={askTarget} aiQ={aiQ}
                    askFocus={askFocus} swapTo={swapTo} runTo={runTo} />
        {!rightShown && (
          <button type="button" className="pg-side-fab" aria-label="오른쪽 창 열기 (])" title="이야기·설정 창 열기 (])"
                  onClick={() => updatePanels((p) => toggle(p, "right"))}><PanelRightOpen size={18} aria-hidden="true" /></button>
        )}
      </div>
      {/* 안내·파일 안내 — 캔버스 아래 가운데 떠 있는 토스트(BQ Q1). 되돌리기·8초 닫힘은 NoteLine 그대로, 파일 안내는 사람이 닫을 때까지. */}
      <div className="pg-toasts">
        {s.note && <NoteLine key={s.note} />}
        {fileNote && (
          <p className="pg-banner pg-file-note" role="status">
            {fileNote}
            <button type="button" className="pg-toast-x" aria-label="파일 안내 닫기" onClick={() => setFileNote(null)}><X size={13} aria-hidden="true" /></button>
          </p>
        )}
      </div>
    </div>
  );
}


export default PortfolioCanvas;
