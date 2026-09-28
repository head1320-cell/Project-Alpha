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
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  getRectOfNodes,
  MiniMap,
  Panel,
  useStore,
  type Connection,
  type Node,
  type NodeChange,
  type ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import { Archive, Boxes, ClipboardList, ClipboardPaste, Command, Copy, GitBranch, LayoutGrid, Loader2, Filter, LayoutList, Map as MapIcon, Maximize, Minus, MoreHorizontal, PanelRightClose, PanelRightOpen, Pin, PinOff, Play, Plus, Redo2, Route, Search as SearchIcon, Sparkles, Sigma, Trash2, Undo2, X } from "lucide-react";
import {
  CORE_CHAIN_TEMPLATE,
  fieldsOf,
  goalDoc,
  PORTFOLIO_NODE,
  TEMPLATES,
  parseFile,
  PG_NODE_TYPE,
  portfolioGraphApi,
  toDoc,
  nodeSummary,
  topoOrder,
  type GraphDoc,
  type NodeRunResult,
  type ParseResult,
  type WorkflowStage,
} from "@/entities/portfolio-graph";
import { ExportButton, ImportControl, readGraphFile } from "@/features/portfolio-graph-io";
import { AlphaSheetBody } from "./AlphaSheet";
import { CommandPalette, type PaletteCommand } from "./CommandPalette";
import { ExecutionSheetBody } from "./ExecutionSheet";
import { GateRail } from "./GateRail";
import { BranchCompare, BranchFrame, branchDiffs, PG_BRANCH_TYPE, type BranchFrameData } from "./Branches";
import { EvidenceEdge, PG_WIRE_TYPE, WIRE_LEGEND, wireOf } from "./EvidenceEdge";
import { GoalStart } from "./GoalStart";
import { GraphNode, PORT_PLAIN, STAGE_VAR } from "./GraphNode";
import { portColor as portTypeColor } from "@/entities/portfolio-graph/ports";
import { GroupFrame, PG_GROUP_TYPE, type GroupFrameData } from "./GroupFrame";
import { ContextMenu, FindBar, MoreMenu, NoteLine, QuickAdd, ShortcutSheet, type MenuItem, type QuickAddState } from "./CanvasAssist";
import { NodePalette, PALETTE_MIME } from "./NodePalette";
import { DEFAULT_PANELS, NARROW_Q, RIGHT_W, clampW, floatInsets, readPanels, savePanels, toggle, type Panels } from "./panels";
import type { LegacyScreen } from "@/entities/portfolio-graph/legacyScreens";
import { NodeResultPanel } from "./NodeResultPanel";
import { RecordsSheetBody } from "./RecordsSheet";
import { SettingsPanel } from "./SettingsPanel";
import { Sheet } from "./Sheet";
import { StoryPanel } from "./StoryPanel";
import { RunHistory } from "./RunHistory";
import { SimpleView } from "./SimpleView";
import { ancestorsOf, usePortfolioGraph, type FilterKey, type PgState } from "./store";

const NODE_TYPES = { [PG_NODE_TYPE]: GraphNode, [PG_GROUP_TYPE]: GroupFrame, [PG_BRANCH_TYPE]: BranchFrame };
const EDGE_TYPES = { [PG_WIRE_TYPE]: EvidenceEdge };
/** 확대 3단계(BM C1 · 의미 확대) — 멀리: 이름과 숫자 하나 · 보통: 카드 · 가까이: 작은 그림·계산 시간까지. */
export const ZOOM_FAR = 0.55;
export const ZOOM_NEAR = 1.05;
export type ZoomLevel = "far" | "mid" | "near";
export const zoomLevel = (z: number): ZoomLevel => (z < ZOOM_FAR ? "far" : z > ZOOM_NEAR ? "near" : "mid");

/** 확대 값을 캔버스 요소의 `data-zoom`·`--pg-z` 로 옮긴다 — 노드를 다시 그리지 않고 CSS 가 단계별로 보이고 숨긴다. */
function ZoomWatch({ el }: { el: RefObject<HTMLDivElement> }) {
  const z = useStore((st) => st.transform[2]);
  useEffect(() => {
    const node = el.current;
    if (!node) return;
    node.dataset.zoom = zoomLevel(z);
    node.style.setProperty("--pg-z", String(z));
  }, [z, el]);
  return null;
}
/** 묶음 상자 여백·노드 카드 크기(대략) — 상자는 안의 노드를 감싸는 사각형이다. */
const GROUP_PAD = 28;
/** 맞춰 보기의 안쪽 여백(px) — 위 64 = 선 범례·걸러 보기 판(10 + 36 + 여유), 아래 64 = 안내 줄. */
const FIT_INSET = { top: 64, bottom: 64, left: 24, right: 24 } as const;
/** 판 사이 가운데가 이보다 좁으면 선 범례·걸러 보기가 알약 아래 둘째 줄로 내려간다(BQ Q2) — 맞춰 보기 위 여백도 그만큼. */
const TIGHT_MIDDLE = 760;
const TIGHT_ROW = 44;
/** 위 여백 — 둘째 줄이 있으면 그만큼 더. */
const fitTop = (el: HTMLElement | null) => FIT_INSET.top + (el?.closest("[data-tight]") ? TIGHT_ROW : 0);
/** 노드 도구줄 높이 + 간격(px) — 고른 노드 위에 이만큼 비어 있어야 도구줄이 떠 있는 판 밑에 깔리지 않는다. */
const TOOLBAR_H = 48;

/** 맞춰 보기 — 떠 있는 판(위: 선 범례·걸러 보기 · 아래: 안내 줄)이 노드·상자 머리를 가리지 않게 위아래를 비워 둔다.
 *  (BN N1 에서 찾은 결함: 균일 여백 맞춤은 맨 위 전략 상자의 머리 줄을 선 범례 밑에 두어 누를 수 없었다.) */
function fitClear(inst: ReactFlowInstance | null, el: HTMLDivElement | null,
                  opts: { ids?: string[]; minZoom?: number; maxZoom?: number; duration?: number } = {}) {
  if (!inst || !el) return;
  // 일부만 맞출 때(갈래·들어가기 — BO O5)도 같은 여백 — 예전 fitView 는 맨 위 노드의 도구줄을 캔버스 위 끝 밖으로 밀었다.
  const want = opts.ids ? new Set(opts.ids) : null;
  const ns = inst.getNodes().filter((n) => !n.hidden && n.width && n.height && (!want || want.has(n.id)));
  if (!ns.length) return;
  const b = getRectOfNodes(ns);
  // 떠 있는 왼쪽 목록·오른쪽 창(BQ Q1)이 가리는 폭만큼 더 비운다 — 캔버스는 판 뒤까지 이어져 있다.
  const ins = floatInsets(el);
  const L = FIT_INSET.left + ins.left;
  const w = Math.max(1, el.clientWidth - L - FIT_INSET.right - ins.right);
  const top = fitTop(el);
  const h = Math.max(1, el.clientHeight - top - FIT_INSET.bottom - ins.bottom);
  const zoom = Math.min(opts.maxZoom ?? 1, Math.max(opts.minZoom ?? 0.2, Math.min(w / b.width, h / b.height)));
  // 가장 작게 줄여도 넘치면 가운데 두지 않고 흐름의 시작(왼쪽 위)에 붙인다 — 넘친 쪽은 오른쪽·아래로 간다.
  const dx = w - b.width * zoom;
  const dy = h - b.height * zoom;
  inst.setViewport({ x: L + (dx > 0 ? dx / 2 : 0) - b.x * zoom,
                     y: top + (dy > 0 ? dy / 2 : 0) - b.y * zoom, zoom },
                   opts.duration ? { duration: opts.duration } : undefined);
}
const NODE_W = 176;
/** React Flow 확대 한계 — `minZoom` 속성과 기본 최대(2). */
const MIN_ZOOM = 0.2;
const MAX_ZOOM = 2;
const NODE_H = 150;
const WIP_KEY = "alpha_pg_wip";
/** 첫 방문 환영 줄(BN N2)을 본 적 있나 — 이 브라우저 localStorage. 못 읽거나 못 쓰면 "본 적 없음"(올 때마다 뜨되 닫을 수 있다). */
const WELCOME_KEY = "alpha_pg_welcomed";
function welcomeSeen(): boolean {
  try { return localStorage.getItem(WELCOME_KEY) === "1"; } catch { return false; }
}
function markWelcomed() {
  try { localStorage.setItem(WELCOME_KEY, "1"); } catch { /* 적을 수 없으면 이번만 닫는다 */ }
}

export interface PortfolioCanvasProps {
  /** 상단 바 오른쪽 — 케이스 상자 등. app 계층이 채운다. */
  topExtra?: ReactNode;
  /** 다른 화면이 넘긴 흐름(BL2b — 매크로 스냅샷 등). 있으면 세션 복원 대신 이것을 연다. */
  initialDoc?: { doc: GraphDoc; note: string } | null;
  /** 옛 주소(`/allocation/<화면>` → `?from=`)로 왔을 때 그 예전 화면(BL4). 배너·팔레트 검색·템플릿·서랍을 안내한다. */
  legacy?: LegacyScreen | null;
}

/** 이웃 노드 — ←→ 는 선을 따라(같은 줄에 가까운 것 먼저), ↑↓ 는 흐름 번호 순서. 없으면 null. */
function neighbour(id: string, key: string, nodes: { id: string; position: { x: number; y: number } }[],
                   edges: { source: string; target: string }[]): string | null {
  const me = nodes.find((n) => n.id === id);
  if (!me) return null;
  const near = (ids: string[]) => ids.map((x) => nodes.find((n) => n.id === x)).filter((n): n is typeof me => !!n)
    .sort((a, b) => Math.abs(a.position.y - me.position.y) - Math.abs(b.position.y - me.position.y))[0]?.id ?? null;
  if (key === "ArrowRight") return near(edges.filter((e) => e.source === id).map((e) => e.target));
  if (key === "ArrowLeft") return near(edges.filter((e) => e.target === id).map((e) => e.source));
  const order = topoOrder(nodes.map((n) => n.id), edges);
  const i = order.indexOf(id);
  if (key === "ArrowDown") return order[i + 1] ?? null;
  if (key === "ArrowUp") return i > 0 ? order[i - 1] : null;
  return null;
}

const FILTERS: [FilterKey, string][] = [
  ["failed", "실패"], ["blocked", "막힘"], ["practice", "연습용"], ["forward", "지금 시점 전용"], ["assumed", "가정 있음"],
];
function matchFilter(k: FilterKey, r: NodeRunResult): boolean {
  return (k === "failed" && r.status === "failed") || (k === "blocked" && r.status === "blocked")
    || (k === "practice" && !!r.lineage?.practice) || (k === "forward" && r.lineage?.pit === "forward_only")
    || (k === "assumed" && !!r.explain?.trust?.some((t) => t.state === "assumed"));
}

function readWip(): string | null {
  try { return typeof window === "undefined" ? null : sessionStorage.getItem(WIP_KEY); }
  catch { return null; }
}

const TABS = [["story", "이야기"], ["settings", "설정"], ["detail", "자세히"], ["branches", "갈래"]] as const;


type DrawerKey = "execution" | "records" | "alphas";
/** 서랍 셋 — 예전 EXECUTION·JOURNAL·ALPHA LAB 화면의 기록 관리를 옮겼다(BL2). 계산은 노드, 기록 관리는 서랍. */
const DRAWERS: { key: DrawerKey; label: string; sub: string; Icon: typeof Archive; Body: () => ReactNode }[] = [
  { key: "execution", label: "실행실", Icon: ClipboardList, Body: ExecutionSheetBody,
    sub: "저장한 실행 목표로 주문 계획을 만들고 검토·승인해요. 주문은 나가지 않아요." },
  { key: "records", label: "기록함", Icon: Archive, Body: RecordsSheetBody,
    sub: "판단 기록·연구 기록·실행 목표·국면 스냅샷을 다시 보고 고쳐요." },
  { key: "alphas", label: "알파", Icon: Sigma, Body: AlphaSheetBody,
    sub: "알파 식을 등록하고 단계를 올리거나 내려요." },
];

export function PortfolioCanvas({ topExtra, initialDoc, legacy }: PortfolioCanvasProps) {
  const s = usePortfolioGraph();
  const rf = useRef<ReactFlowInstance | null>(null);
  const canvasEl = useRef<HTMLDivElement>(null);
  const addCount = useRef(0);
  const [stages, setStages] = useState<WorkflowStage[]>([]);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [goalOpen, setGoalOpen] = useState(false);
  const [welcome, setWelcome] = useState(false);
  // 캔버스 손길(BN N3) — 선 끌어 놓기 빠른 추가 · 우클릭 메뉴 · 찾기 · 단축키 한 장.
  const [quick, setQuick] = useState<QuickAddState | null>(null);
  const [ctx, setCtx] = useState<{ x: number; y: number; clientX: number; clientY: number; nodeId: string | null } | null>(null);
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
  const focusRef = useRef<(id: string) => void>(() => {});
  const runStrategyRef = useRef<(groupId: string) => void>(() => {});
  const branchStrategyRef = useRef<(groupId: string) => void>(() => {});
  const [announce, setAnnounce] = useState("");
  // 떠 있는 판(BQ Q1) — 여닫기·폭. 넓은 화면에서 바꾼 것만 이 브라우저에 남긴다(좁은 화면은 늘 닫힌 채 시작).
  const [panels, setPanels] = useState<Panels>(DEFAULT_PANELS);
  const narrowNow = () => typeof window !== "undefined" && !!window.matchMedia?.(NARROW_Q).matches;
  useEffect(() => { setPanels(readPanels(narrowNow(), window.innerWidth >= 1440)); }, []);
  const updatePanels = useCallback((f: (p: Panels) => Panels) => {
    setPanels((p) => { const n = f(p); if (!narrowNow()) savePanels(n); return n; });
  }, []);
  // 판 사이 가운데가 좁으면(알약 + 선 범례 + 걸러 보기가 한 줄에 안 듦) 범례·걸러 보기를 한 줄 아래로(BQ Q2).
  const [tight, setTight] = useState(false);
  const leftShown = panels.left && !panels.focus;
  const rightShown = panels.right && !panels.focus;
  useEffect(() => {
    const el = canvasEl.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => { const ins = floatInsets(el); setTight(el.clientWidth - ins.left - ins.right < TIGHT_MIDDLE); };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    // 판 자체의 크기도 본다 — 왼쪽 목록은 카탈로그가 온 뒤에야 그려진다.
    el.closest(".pg-root")?.querySelectorAll(".pg-palette, .pg-side").forEach((x) => ro.observe(x));
    const t = setTimeout(measure, 0);                                   // 판이 열리고 닫힌 뒤의 폭
    return () => { ro.disconnect(); clearTimeout(t); };
  }, [leftShown, rightShown, panels.rightW, !!s.catalog]);

  const fit = () => setTimeout(() => fitClear(rf.current, canvasEl.current), 60);
  /** 판 사이 보이는 가운데를 기준으로 확대·축소(BQ Q1). */
  const zoomBy = useCallback((k: number) => {
    const inst = rf.current;
    const el = canvasEl.current;
    if (!inst || !el) return;
    const vp = inst.getViewport();
    const ins = floatInsets(el);
    const z = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, vp.zoom * k));
    const cx = ins.left + (el.clientWidth - ins.left - ins.right) / 2;
    const cy = (el.clientHeight - ins.bottom) / 2;
    const r = z / vp.zoom;
    inst.setViewport({ x: cx - (cx - vp.x) * r, y: cy - (cy - vp.y) * r, zoom: z });
  }, []);

  // ── 카탈로그 → 복원(세션) 또는 기본 사슬 ──────────────────────────────
  useEffect(() => {
    let alive = true;
    portfolioGraphApi.nodeTypes()
      .then((cat) => {
        if (!alive) return;
        setStages(cat.stages ?? []);
        usePortfolioGraph.getState().setStages(cat.stages ?? []);
        usePortfolioGraph.getState().setCatalog(cat.nodes);
        const st = usePortfolioGraph.getState();
        if (initialDoc) {
          // 다른 화면이 넘긴 흐름(예: 매크로 스냅샷) — 지금 캔버스가 있으면 되돌리기로 돌아갈 수 있다(loadDoc 이 기록한다).
          st.loadDoc(initialDoc.doc);
          setFileNote(initialDoc.note + (st.past.length ? " 이전 캔버스는 되돌리기(Ctrl+Z)로 돌아가요." : ""));
        } else {
          const saved = readWip();
          const parsed = saved ? parseFile(saved) : null;
          if (st.nodes.length === 0) st.loadDoc(parsed?.doc ?? CORE_CHAIN_TEMPLATE, parsed?.problems ?? []);
        }
        fit();
      })
      .catch((e: Error) => { if (alive) usePortfolioGraph.getState().setCatalog(null, e.message); });
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 처음 한 번만(넘겨받은 흐름은 열 때 한 번 싣는다)
  }, []);

  const doc = useMemo(() => toDoc(s.nodes, s.edges, s.name ? { name: s.name } : undefined, s.groups, s.branches, s.pinned),
    [s.nodes, s.edges, s.name, s.groups, s.branches, s.pinned]);
  const order = useMemo(() => topoOrder(s.nodes.map((n) => n.id), s.edges), [s.nodes, s.edges]);
  /** 밝힐 경로 — 계산 중이면 계산하는 노드들, 아니면 "여기까지 계산" 에 올린 노드의 조상. */
  const path = useMemo(() => new Set(s.runningIds ?? s.preview ?? []), [s.runningIds, s.preview]);
  const cause = s.reportStale ? null : s.cause;
  const causeSet = useMemo(() => new Set(cause?.path ?? []), [cause]);
  const live = s.report && !s.reportStale ? s.report.nodes : null;
  // BM C2 — 들어간 상자·필터가 켜지면 나머지를 흐린다(원인 경로가 켜져 있으면 그것이 먼저다).
  const focusSet = useMemo(() => {
    const g = s.groups.find((x) => x.id === s.focusGroup);
    return g ? new Set(g.members) : null;
  }, [s.groups, s.focusGroup]);
  const filterSet = useMemo(() => {
    if (!s.filters.length || !live) return null;
    return new Set(s.nodes.map((n) => n.id).filter((id) => {
      const r = live[id];
      if (!r) return false;
      return s.filters.some((f) => matchFilter(f, r));
    }));
  }, [s.filters, s.nodes, live]);
  const keep = cause ? causeSet : focusSet ?? filterSet;
  /** 노드 → 그 노드가 든 접힌 상자(대리 포트로 선을 다시 그린다). */
  const collapsedOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of s.groups) if (g.collapsed && g.id !== s.focusGroup) for (const id of g.members) m.set(id, g.id);
    return m;
  }, [s.groups, s.focusGroup]);
  const portColor = useCallback((nodeId: string, handle: string | null | undefined, side: "in" | "out") => {
    const kind = s.nodes.find((n) => n.id === nodeId)?.data.kind;
    const entry = s.catalog?.find((c) => c.type === kind);
    const p = (side === "out" ? entry?.outputs : entry?.inputs)?.find((x) => x.name === handle);
    return { color: portTypeColor(p?.type), plain: p ? PORT_PLAIN[p.type] ?? p.name : handle ?? "?" };
  }, [s.nodes, s.catalog]);
  const bandOf = useMemo(() => {
    const m = new Map<string, number>();
    for (const g of s.groups) if (g.kind === "strategy") for (const id of g.members) m.set(id, g.color ?? 0);
    return m;
  }, [s.groups]);

  /** 전략(출력 노드)의 몫 — 이은 포트폴리오 노드 결과의 서버 값(`view.strategies[port].share_pct`). 계산 전·모르면 null. */
  const shareByEdge = useCallback((target: string, port: string | null | undefined): number | null => {
    const r = live?.[target];
    if (!r || r.status !== "ok" || !port) return null;
    const rows = (r.view?.strategies as { port: string; share_pct: unknown }[] | undefined) ?? [];
    const v = rows.find((x) => x.port === port)?.share_pct;
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  }, [live]);
  /** 리밸런싱 주기의 쉬운 이름(BO O2) — 서버 x-ui 선택지. 카탈로그가 없으면 표시하지 않는다(지어내지 않는다). */
  const rebalUi = useMemo(() => fieldsOf(s.catalog?.find((c) => c.type === PORTFOLIO_NODE)?.params_schema ?? null)
    .find((f) => f.name === "rebalance")?.ui ?? null, [s.catalog]);
  const shareOf = useCallback((output: string | null): { share: number | null; linked: boolean; rebalance: string | null } => {
    const e = output ? s.edges.find((x) => x.source === output && s.nodes.find((n) => n.id === x.target)?.data.kind === PORTFOLIO_NODE) : undefined;
    const pf = e ? s.nodes.find((n) => n.id === e.target) : undefined;
    const set = (pf?.data.params.rebalance ?? {}) as Record<string, string>;
    const code = e?.targetHandle ? set[e.targetHandle] ?? (rebalUi?.empty_value as string | undefined) : undefined;
    return { share: e ? shareByEdge(e.target, e.targetHandle) : null, linked: !!e,
             rebalance: code ? rebalUi?.options?.[code] ?? null : null };
  }, [s.edges, s.nodes, shareByEdge, rebalUi]);

  const numbered = useMemo(() => {
    const num = new Map(order.map((id, i) => [id, i + 1]));
    const picked = new Set(s.picked);
    // 선택은 스토어가 진실 — 이야기 카드에서 고른 노드도, 상자로 여러 개 고른 노드도 캔버스에서 선택돼 보인다.
    const cards: Node[] = s.nodes.map((n) => ({
      ...n, hidden: collapsedOf.has(n.id), selected: picked.has(n.id) || n.id === s.selectedId,
      className: [path.has(n.id) && "pg-on-path",
                  keep && !keep.has(n.id) && "pg-dim",
                  cause && causeSet.has(n.id) && "pg-on-cause",
                  cause?.roots.includes(n.id) && "pg-cause-root"].filter(Boolean).join(" ") || undefined,
      data: { ...n.data, num: num.get(n.id), onRunTo: runToRef.current, onPreviewRunTo: previewRef.current },
    }));
    const frames: Node<GroupFrameData>[] = s.groups.map((g) => {
      const ms = s.nodes.filter((n) => g.members.includes(n.id));
      const strat = g.kind === "strategy";
      const x0 = Math.min(...ms.map((n) => n.position.x)) - GROUP_PAD;
      const y0 = Math.min(...ms.map((n) => n.position.y)) - GROUP_PAD - 30;
      const x1 = Math.max(...ms.map((n) => n.position.x)) + NODE_W + GROUP_PAD;
      const y1 = Math.max(...ms.map((n) => n.position.y)) + NODE_H + GROUP_PAD;
      const inside = new Set(g.members);
      const collapsed = collapsedOf.has(g.members[0] ?? "") && !!g.collapsed;
      const proxyIn = collapsed ? s.edges.filter((e) => inside.has(e.target) && !inside.has(e.source)).map((e) => {
        const pc = portColor(e.target, e.targetHandle, "in");
        return { id: `in|${e.target}|${e.targetHandle}`, label: pc.plain, color: pc.color };
      }) : [];
      const outs = new Map<string, { id: string; label: string; color: string }>();
      if (collapsed) {
        for (const e of s.edges.filter((x) => inside.has(x.source) && !inside.has(x.target))) {
          const pc = portColor(e.source, e.sourceHandle, "out");
          outs.set(`${e.source}|${e.sourceHandle}`, { id: `out|${e.source}|${e.sourceHandle}`, label: pc.plain, color: pc.color });
        }
      }
      const dimmed = keep && !g.members.some((m) => keep.has(m));
      // 접은 전략 카드는 전략의 출력 노드 자리에 선다(BO O5) — 포트폴리오로 가는 선이 전략 폭만큼 길어지지 않게.
      // 자리는 여전히 노드에서 계산하므로 카드를 끌면 구성원이 함께 움직이는 규칙(차이만 옮김)은 그대로다.
      const outNode = collapsed && strat && g.output ? ms.find((n) => n.id === g.output) : undefined;
      const at = outNode ? { x: outNode.position.x, y: outNode.position.y } : { x: x0, y: y0 };
      return { id: `frame:${g.id}`, type: PG_GROUP_TYPE, position: at, zIndex: -1, selectable: false,
               className: dimmed ? "pg-dim" : undefined,
               data: { groupId: g.id, label: g.label, collapsed, members: g.members, width: x1 - x0, height: y1 - y0,
                       kind: g.kind === "strategy" ? "strategy" : "group", color: g.color ?? 0,
                       output: g.kind === "strategy" ? g.output ?? null : null, proxyIn, proxyOut: [...outs.values()],
                       ...(strat ? shareOf(g.output ?? null) : { share: null, linked: false, rebalance: null }),
                       onRunStrategy: runStrategyRef.current, onBranchStrategy: branchStrategyRef.current } };
    });
    // 갈래 틀(BM C3) — 복제 노드를 감싼 점선 상자. 바꾼 설정만 칩으로.
    const branchFrames: Node<BranchFrameData>[] = s.branches.flatMap((b) => {
      const ms = s.nodes.filter((n) => n.id in b.map);
      if (!ms.length) return [];
      const x0 = Math.min(...ms.map((n) => n.position.x)) - GROUP_PAD;
      const y0 = Math.min(...ms.map((n) => n.position.y)) - GROUP_PAD - 56;
      const x1 = Math.max(...ms.map((n) => n.position.x)) + NODE_W + GROUP_PAD;
      const y1 = Math.max(...ms.map((n) => n.position.y)) + NODE_H + GROUP_PAD;
      const root = s.nodes.find((n) => n.id === b.of_root);
      return [{ id: `branch:${b.id}`, type: PG_BRANCH_TYPE, position: { x: x0, y: y0 }, zIndex: -1, selectable: false, draggable: false,
                className: keep && !ms.some((m) => keep.has(m.id)) ? "pg-dim" : undefined,
                data: { branchId: b.id, label: b.label, width: x1 - x0, height: y1 - y0, diffs: branchDiffs(b, s.nodes, s.catalog ?? []),
                        rootName: s.catalog?.find((c) => c.type === root?.data.kind)?.plain_label ?? b.of_root } }];
    });
    return [...frames, ...branchFrames, ...cards];
  }, [s.nodes, s.groups, s.edges, order, s.selectedId, s.picked, path, collapsedOf, keep, cause, causeSet, portColor, s.branches, s.catalog, shareOf]);
  /** 한 노드만 골랐을 때 그 노드와 닿지 않은 선은 옅게(Houdini) — 흐리기 모드(원인·들어가기·필터)가 없을 때만. */
  const faintOthers = !keep && s.picked.length <= 1 ? s.selectedId : null;
  const edgesStyled = useMemo(() => s.edges.map((e) => {
    const kind = s.nodes.find((n) => n.id === e.source)?.data.kind;
    const out = s.catalog?.find((c) => c.type === kind)?.outputs.find((p) => p.name === e.sourceHandle);
    const lit = path.has(e.source) && path.has(e.target);
    const src = live?.[e.source];
    const wire = wireOf(src, e.sourceHandle ? src?.briefs?.[e.sourceHandle] : null);
    const onCause = !!cause && causeSet.has(e.source) && causeSet.has(e.target);
    const kept = !keep || (keep.has(e.source) && keep.has(e.target));
    // 접힌 상자 — 안쪽끼리는 숨기고, 경계를 넘는 선은 상자의 대리 포트로(실제 링크는 그대로).
    const gs = collapsedOf.get(e.source);
    const gt = collapsedOf.get(e.target);
    const remap = gs && gs === gt ? { hidden: true }
      : { ...(gs ? { source: `frame:${gs}`, sourceHandle: `out|${e.source}|${e.sourceHandle}` } : {}),
          ...(gt ? { target: `frame:${gt}`, targetHandle: `in|${e.target}|${e.targetHandle}` } : {}) };
    const faint = faintOthers && e.source !== faintOthers && e.target !== faintOthers;
    const cls = ["pg-wire", wire.evidence && `pg-wire--${wire.evidence}`, wire.forward && "pg-wire--forward",
                 lit && "pg-edge--path", onCause && "pg-edge--cause", !kept && "pg-dim", faint && "pg-edge--faint",
                 (gs || gt) && "pg-wire--proxy"].filter(Boolean).join(" ");
    return { ...e, ...remap, type: PG_WIRE_TYPE, data: wire, animated: lit && s.running, className: cls,
             style: { stroke: wire.evidence === "blocked" ? "var(--pg-wire-off)" : portTypeColor(out?.type),
                      strokeWidth: lit || onCause ? 3.5 : 2.5 } };
  }), [s.edges, s.nodes, s.catalog, path, s.running, live, cause, causeSet, keep, collapsedOf, faintOthers]);
  /** 전략 추가 메뉴의 재료 — 비중을 내는 템플릿과 내 블록 중 전략. */
  const strategySources = useMemo(() => {
    const cat = s.catalog ?? [];
    const producesWeights = (d: { nodes: { type: string }[] }) =>
      d.nodes.some((n) => cat.find((c) => c.type === n.type)?.outputs.some((o) => o.type === "Weights"));
    return [
      ...TEMPLATES.filter((t) => producesWeights(t.doc)).map((t) => ({ key: `tpl:${t.key}`, label: t.name, sub: t.description,
        src: { label: t.name, nodes: t.doc.nodes, edges: t.doc.edges } })),
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
  }, []);

  // 들어가기 — 그 상자에 맞춰 확대하고, 나오면 전체로.
  useEffect(() => {
    if (!rf.current) return;
    const g = s.groups.find((x) => x.id === s.focusGroup);
    if (g) setTimeout(() => fitClear(rf.current, canvasEl.current, { ids: g.members, maxZoom: 1.2, duration: 250 }), 30);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 들어가고 나올 때만
  }, [s.focusGroup]);
  const focused = s.groups.find((g) => g.id === s.focusGroup);
  // 고른 노드가 캔버스 위쪽 띠(선 범례·걸러 보기 판)에 있으면 도구줄이 그 판 밑에 깔린다 — 도구줄이 보이도록 판만 살짝 내린다(BP P1).
  // 도구줄을 노드 아래로 뒤집으면 아래 노드를 가려 그 노드를 누르려던 손이 '갈래 만들기' 를 누른다(첫 시도에서 E2E 가 찾았다).
  // 고른 노드가 떠 있는 판(BQ Q1) 밑에 있어도 판을 옆으로 옮겨 보이게 한다 — 이미 보이면 움직이지 않는다.
  useEffect(() => {
    const inst = rf.current;
    const id = s.selectedId;
    // 우클릭으로 고른 경우엔 움직이지 않는다 — 메뉴가 그 자리에 떠 있는데 판이 밀리면 가리키던 곳이 어긋난다(도구줄도 안 보인다).
    if (!inst || !id || s.picked.length > 1 || ctx) return;
    // 창이 막 열린 뒤의 폭을 재도록 한 박자 늦게.
    const t = setTimeout(() => {
      const n = inst.getNode(id);
      const el = canvasEl.current;
      if (!n?.positionAbsolute || !el) return;
      const vp = inst.getViewport();
      const top = n.positionAbsolute.y * vp.zoom + vp.y;
      const left = n.positionAbsolute.x * vp.zoom + vp.x;
      const right = left + (n.width ?? NODE_W) * vp.zoom;
      const ins = floatInsets(el);
      const need = fitTop(el) + TOOLBAR_H;
      const dy = top < need ? need - top : 0;
      let dx = 0;
      const maxRight = el.clientWidth - ins.right - 16;
      if (right > maxRight) dx = maxRight - right;
      if (left + dx < ins.left + 16) dx = ins.left + 16 - left;
      if (dx || dy) inst.setViewport({ ...vp, x: vp.x + dx, y: vp.y + dy }, { duration: 200 });
    }, 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 고를 때·창이 열리고 닫힐 때만
  }, [s.selectedId, rightShown, leftShown]);
  // 노드를 고르면 오른쪽 창이 열린다 — × 로 닫았으면 다음에 고를 때 다시 열린다. 집중 모드(\)에서는 고르기만.
  useEffect(() => {
    if (s.selectedId) setPanels((p) => (p.focus || p.right ? p : { ...p, right: true }));
  }, [s.selectedId]);
  // 갈래를 막 만들었으면 원본 뿌리와 새 갈래가 함께 보이게 옮긴다(복제는 원본 아래에 놓인다).
  const nBranches = useRef(s.branches.length);
  useEffect(() => {
    const grew = s.branches.length > nBranches.current;
    nBranches.current = s.branches.length;
    const b = s.branches[s.branches.length - 1];
    if (!grew || !b || !rf.current) return;
    const ids = [...Object.keys(b.map), ...Object.values(b.map)];
    setTimeout(() => fitClear(rf.current, canvasEl.current, { ids, minZoom: 0.6, maxZoom: 1, duration: 250 }), 30);
  }, [s.branches]);

  /** 묶음 상자를 끌면 안의 노드가 함께 움직인다 — 상자 자리는 노드에서 계산하므로 차이만 옮긴다. */
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const st = usePortfolioGraph.getState();
    const rest: NodeChange[] = [];
    for (const c of changes) {
      if ("id" in c && c.id.startsWith("branch:")) continue;
      if ("id" in c && c.id.startsWith("frame:")) {
        if (c.type === "position" && c.position) {
          const frame = numbered.find((n) => n.id === c.id);
          if (frame) st.moveGroup(c.id.slice(6), c.position.x - frame.position.x, c.position.y - frame.position.y);
        }
        continue;
      }
      rest.push(c);
    }
    if (rest.length) st.onNodesChange(rest);
  }, [numbered]);

  // ── 작업 중 상태 보존(편의용 — 신뢰 저장이 아니다. 저장은 내보내기) ─────────
  useEffect(() => {
    if (!s.catalog) return;
    try { sessionStorage.setItem(WIP_KEY, JSON.stringify(doc)); } catch { /* 용량 초과 등 — 편의 기능 */ }
  }, [doc, s.catalog]);

  // ── 구조가 바뀌면 서버 검증(위치 이동은 제외) ─────────────────────────
  const structureKey = useMemo(() => JSON.stringify({
    n: doc.nodes.map((n) => [n.id, n.type, n.params]), e: doc.edges,
  }), [doc]);
  useEffect(() => {
    if (!s.catalog || doc.nodes.length === 0) { usePortfolioGraph.getState().setValidation(null); return; }
    const t = setTimeout(() => {
      portfolioGraphApi.validate(doc)
        .then((v) => usePortfolioGraph.getState().setValidation(v))
        .catch(() => usePortfolioGraph.getState().setValidation(null));
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 위치 변화로는 다시 검증하지 않는다
  }, [structureKey, s.catalog]);

  // ── 연결 규칙: 타입 일치 · 입력 하나에 링크 하나 · 순환 금지 ──────────────
  const isValidConnection = useCallback((c: Connection) => {
    const st = usePortfolioGraph.getState();
    if (!c.source || !c.target || c.source === c.target) return false;
    const kind = (id: string) => st.nodes.find((n) => n.id === id)?.data.kind;
    const entry = (id: string) => st.catalog?.find((x) => x.type === kind(id));
    const out = entry(c.source)?.outputs.find((p) => p.name === c.sourceHandle);
    const inp = entry(c.target)?.inputs.find((p) => p.name === c.targetHandle);
    if (!out || !inp || out.type !== inp.type) return false;
    if (st.edges.some((e) => e.target === c.target && e.targetHandle === c.targetHandle)) return false;
    const seen = new Set<string>();
    const stack = [c.target];
    while (stack.length) {
      const cur = stack.pop()!;
      if (cur === c.source) return false;
      if (seen.has(cur)) continue;
      seen.add(cur);
      st.edges.filter((e) => e.source === cur).forEach((e) => stack.push(e.target));
    }
    return true;
  }, []);

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
    const id = usePortfolioGraph.getState().addNode(kind, at);
    usePortfolioGraph.getState().setTab("settings");
    return id;
  }, []);

  // ── 선 끌어 놓기 빠른 추가(BN N3) — 포트에서 끌어 빈 곳에 놓으면 그 값을 이을 노드만 보인다 ──────────
  const onConnectStart = useCallback((_: unknown, p: { nodeId: string | null; handleId: string | null; handleType: "source" | "target" | null }) => {
    const st = usePortfolioGraph.getState();
    const kind = st.nodes.find((n) => n.id === p.nodeId)?.data.kind;
    const entry = st.catalog?.find((c) => c.type === kind);
    const side = p.handleType ?? "source";
    const port = (side === "source" ? entry?.outputs : entry?.inputs)?.find((x) => x.name === p.handleId);
    connectFrom.current = p.nodeId && p.handleId && port ? { node: p.nodeId, handle: p.handleId, side, type: port.type } : null;
  }, []);
  const onConnectEnd = useCallback((e: MouseEvent | TouchEvent) => {
    const from = connectFrom.current;
    connectFrom.current = null;
    const target = e.target as Element | null;
    if (!from || !target?.classList.contains("react-flow__pane")) return;     // 포트에 놓았으면 평소의 연결
    const pt = "changedTouches" in e ? e.changedTouches[0] : e;
    const box = canvasEl.current?.getBoundingClientRect();
    setQuick({ from, x: pt.clientX - (box?.left ?? 0), y: pt.clientY - (box?.top ?? 0), clientX: pt.clientX, clientY: pt.clientY });
  }, []);
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
  }, [quick, addAt]);

  /** 우클릭 메뉴의 항목 — 노드면 노드 동작, 빈 곳이면 추가·붙여넣기·정리. 같은 동작이 명령 찾기에도 있다. */
  const ctxItems = useMemo((): MenuItem[] => {
    if (!ctx) return [];
    const st = usePortfolioGraph.getState();
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
    const r = st.reportStale ? undefined : st.report?.nodes[id];
    const pinned = st.pinned.includes(id);
    return [
      { key: "run-to", label: "여기까지 계산", icon: <Play size={14} aria-hidden="true" />, disabled: st.running, run: () => runToRef.current(id) },
      { key: "branch", label: "갈래 만들기", icon: <GitBranch size={14} aria-hidden="true" />,
        run: () => { const x = usePortfolioGraph.getState(); x.act(() => x.makeBranch(id)); } },
      { key: "duplicate", label: "복제 (Ctrl+D)", icon: <Copy size={14} aria-hidden="true" />,
        run: () => { usePortfolioGraph.getState().duplicateNode(id); } },
      { key: "pin", label: pinned ? "그림 고정 풀기" : "그림 고정", icon: pinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />,
        run: () => usePortfolioGraph.getState().togglePin(id) },
      ...(r && r.status !== "ok" ? [{ key: "cause", label: "원인 따라가기", icon: <Route size={14} aria-hidden="true" />,
                                      run: () => usePortfolioGraph.getState().showCause(id) }] : []),
      { key: "remove", label: "지우기", icon: <Trash2 size={14} aria-hidden="true" />, danger: true,
        run: () => { const x = usePortfolioGraph.getState(); x.act(() => { x.removeNode(id); return "노드를 지웠어요."; }); } },
    ];
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 메뉴를 열 때마다 새로 만든다
  }, [ctx]);

  const applyLoad = useCallback((r: ParseResult, fileName: string) => {
    if (!r.doc) {
      setFileNote(`「${fileName}」을 불러오지 않았어요 — ${r.problems.join(" ")} 캔버스는 그대로예요.`);
      return;
    }
    usePortfolioGraph.getState().loadDoc(r.doc, r.problems);
    setFileNote(`「${fileName}」을 불러왔어요 — 노드 ${r.doc.nodes.length}개, 링크 ${r.doc.edges.length}개.`);
    fit();
  }, []);

  const loadTemplate = useCallback((key: string) => {
    const t = TEMPLATES.find((x) => x.key === key) ?? TEMPLATES[0];
    usePortfolioGraph.getState().loadDoc(t.doc);
    setFileNote(`‘${t.name}’을 불러왔어요. 종목·조건은 예시예요 — 노드를 눌러 바꿔 보세요.`);
    fit();
  }, []);

  const onDrop = useCallback(async (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) { applyLoad(await readGraphFile(file), file.name); return; }
    const kind = e.dataTransfer.getData(PALETTE_MIME);
    if (kind && rf.current) addAt(kind, rf.current.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  }, [addAt, applyLoad]);

  const run = useCallback(async (targets?: string[]) => {
    const st = usePortfolioGraph.getState();
    const ids = targets?.length ? ancestorsOf(targets, st.edges) : st.nodes.map((n) => n.id);
    st.startRun(ids);
    st.setOpenGate(null);
    try {
      st.finishRun(await portfolioGraphApi.run(toDoc(st.nodes, st.edges), targets?.length ? targets : undefined));
    } catch (e) {
      st.finishRun(null, (e as Error).message);
    }
  }, []);
  const runTo = useCallback((id: string) => run([id]), [run]);
  /** 목표로 시작 — 답으로 조립한 흐름을 싣고(되돌리기 가능), 흐름 순서대로 한 번 자라나게 한 뒤 곧바로 계산한다. */
  const startGoal = useCallback((goal: Parameters<typeof goalDoc>[0], tickers: string[], lookback: number | null,
                                 riskAversion: number | null) => {
    const st = usePortfolioGraph.getState();
    st.act(() => {
      st.loadDoc(goalDoc(goal, tickers, lookback, riskAversion));
      return "답으로 흐름을 만들었어요 — 계산하고 있어요. 노드를 눌러 설정을 바꿀 수 있어요.";
    });
    setGoalOpen(false);
    st.setGrowing(true);
    setTimeout(() => usePortfolioGraph.getState().setGrowing(false), 1800);
    fit();
    void run();
  }, [run]);
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

  // 단축키 — 입력 칸에 있을 때는 가로채지 않는다. Ctrl/⌘+Enter 계산 · Ctrl/⌘+D 복제 · Esc 관문 닫기.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      if (t?.closest("dialog")) return;                   // 서랍·명령 찾기 안의 키는 그 대화상자 몫이다
      const st = usePortfolioGraph.getState();
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (mod && k === "k") { e.preventDefault(); setCmdOpen(true); }
      else if (mod && k === "f") { e.preventDefault(); setFindOpen(true); }
      else if ((e.key === "?" || (e.key === "/" && e.shiftKey)) && !mod) { e.preventDefault(); setKeysOpen(true); }
      else if (mod && e.key === "Enter" && !st.running) { e.preventDefault(); void run(); }
      else if (e.shiftKey && e.key === "Enter" && !st.running && st.selectedId) { e.preventDefault(); void runTo(st.selectedId); }
      else if (mod && k === "z" && !e.shiftKey) { e.preventDefault(); st.undo(); }
      else if (mod && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); st.redo(); }
      else if (mod && k === "c") { if (st.copy()) e.preventDefault(); }
      else if (mod && k === "v") { if (st.paste()) e.preventDefault(); }
      else if (mod && k === "g") { e.preventDefault(); st.groupPicked(); }
      else if (mod && k === "d" && st.selectedId) { e.preventDefault(); st.duplicateNode(st.selectedId); }
      else if (!mod && !e.altKey && e.key === "[") { e.preventDefault(); updatePanels((p) => toggle(p, "left")); }
      else if (!mod && !e.altKey && e.key === "]") { e.preventDefault(); updatePanels((p) => toggle(p, "right")); }
      else if (!mod && !e.altKey && e.key === "\\") { e.preventDefault(); updatePanels((p) => toggle(p, "focus")); }
      else if (e.key === "Escape" && st.cause) st.showCause(null);
      else if (e.key === "Escape" && st.focusGroup) { st.setFocusGroup(null); fit(); }
      else if (e.key === "Escape" && st.openGate) st.setOpenGate(null);
      else if (e.altKey && e.key.startsWith("Arrow") && st.selectedId) {
        // 키보드로 노드 사이 이동(접근성) — ←→ 선을 따라 앞·뒤 단계, ↑↓ 흐름 번호 순서.
        const next = neighbour(st.selectedId, e.key, st.nodes, st.edges);
        if (next) { e.preventDefault(); focusRef.current(next); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run, runTo, updatePanels]);

  const commands = useMemo<PaletteCommand[]>(() => [
    { id: "run", group: "계산", label: "전체 계산하기", keys: "Ctrl+Enter", run: () => void run() },
    { id: "find", group: "보기", label: "캔버스에서 노드 찾기", keys: "Ctrl+F", run: () => setFindOpen(true) },
    { id: "keys", group: "도움말", label: "단축키 보기", keys: "?", run: () => setKeysOpen(true) },
    ...(s.selectedId ? [
      { id: "dup", group: "편집", label: "고른 노드 복제", keys: "Ctrl+D", run: () => { const st = usePortfolioGraph.getState(); if (st.selectedId) st.duplicateNode(st.selectedId); } },
      { id: "pin", group: "보기", label: s.pinned.includes(s.selectedId) ? "고른 노드 그림 고정 풀기" : "고른 노드 그림 고정",
        run: () => { const st = usePortfolioGraph.getState(); if (st.selectedId) st.togglePin(st.selectedId); } },
      { id: "remove", group: "편집", label: "고른 노드 지우기", keys: "Delete",
        run: () => { const st = usePortfolioGraph.getState(); const id = st.selectedId; if (id) st.act(() => { st.removeNode(id); return "노드를 지웠어요."; }); } },
    ] : []),
    { id: "goal", group: "시작", label: "목표로 새로 시작", hint: "무엇을 하려는지 · 종목 · 기간을 고르면 흐름을 만들어 계산해요",
      run: () => setGoalOpen(true) },
    { id: "simple", group: "보기", label: s.simple ? "캔버스로 돌아가기" : "간단히 보기", hint: "노드 없이 정할 것과 결과만 봐요",
      run: () => { const st = usePortfolioGraph.getState(); st.setSimple(!st.simple); } },
    ...(s.selectedId ? [{ id: "run-to", group: "계산", label: "고른 노드까지 계산", keys: "Shift+Enter",
                          run: () => void runTo(usePortfolioGraph.getState().selectedId!) }] : []),
    { id: "undo", group: "편집", label: "되돌리기", keys: "Ctrl+Z", run: () => usePortfolioGraph.getState().undo() },
    { id: "redo", group: "편집", label: "다시하기", keys: "Ctrl+Shift+Z", run: () => usePortfolioGraph.getState().redo() },
    { id: "layout", group: "보기", label: "자동 정리", hint: "흐름 순서대로 왼쪽에서 오른쪽으로 놓아요",
      run: () => { usePortfolioGraph.getState().autoLayout(); fit(); } },
    { id: "panel-left", group: "보기", label: leftShown ? "왼쪽 목록 닫기" : "왼쪽 목록 열기", keys: "[",
      run: () => updatePanels((p) => toggle(p, "left")) },
    { id: "panel-right", group: "보기", label: rightShown ? "오른쪽 창 닫기" : "오른쪽 창 열기", keys: "]",
      run: () => updatePanels((p) => toggle(p, "right")) },
    { id: "panel-focus", group: "보기", label: panels.focus ? "집중 끝내기" : "집중해서 보기", keys: "\\",
      hint: "왼쪽 목록과 오른쪽 창을 잠시 모두 닫아요", run: () => updatePanels((p) => toggle(p, "focus")) },
    { id: "minimap", group: "보기", label: s.showMinimap ? "미니맵 끄기" : "미니맵 켜기",
      run: () => usePortfolioGraph.getState().setMinimap(!usePortfolioGraph.getState().showMinimap) },
    { id: "group", group: "편집", label: "고른 노드 묶기", keys: "Ctrl+G", hint: "노드를 두 개 이상 고르면 돼요",
      run: () => usePortfolioGraph.getState().groupPicked() },
    ...(s.selectedId ? [{ id: "branch", group: "비교", label: "고른 노드에서 갈래 만들기",
                          hint: "그 노드와 하류를 복제해 설정만 바꿔 나란히 봐요(한 노드에 4개까지)",
                          run: () => { const st = usePortfolioGraph.getState(); if (st.selectedId) st.act(() => st.makeBranch(st.selectedId!)); } }] : []),
    { id: "strategy-picked", group: "전략", label: "고른 노드를 전략으로 묶기", hint: "비중을 내는 노드가 들어 있어야 해요",
      run: () => { const st = usePortfolioGraph.getState(); st.act(() => st.strategyPicked()); } },
    ...strategySources.map((x) => ({ id: `strategy:${x.key}`, group: "전략", label: `전략 추가: ${x.label}`, hint: x.sub,
                                     run: () => addStrategy(x.src) })),
    ...DRAWERS.map((d) => ({ id: `drawer:${d.key}`, group: "서랍", label: `${d.label} 열기`, hint: d.sub,
                             run: () => setDrawer(d.key) })),
    ...TEMPLATES.map((t) => ({ id: `tpl:${t.key}`, group: "템플릿", label: `${t.name} 불러오기`, hint: t.description,
                               run: () => loadTemplate(t.key) })),
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 명령은 열 때마다 새로 만든다
  ], [s.selectedId, s.showMinimap, cmdOpen, strategySources, s.simple, leftShown, rightShown, panels.focus]);

  const focusNode = useCallback((id: string) => {
    usePortfolioGraph.getState().select(id);
    const n = usePortfolioGraph.getState().nodes.find((x) => x.id === id);
    if (n && rf.current) {
      // 떠 있는 판 사이의 가운데로(BQ Q1) — 캔버스 가운데는 창 밑일 수 있다.
      const z = rf.current.getZoom();
      const ins = floatInsets(canvasEl.current);
      rf.current.setCenter(n.position.x + 90 + (ins.right - ins.left) / 2 / z, n.position.y + 60 + ins.bottom / 2 / z, { zoom: z, duration: 250 });
    }
    const entry = usePortfolioGraph.getState().catalog?.find((c) => c.type === n?.data.kind);
    setAnnounce(n ? `${entry?.plain_label ?? n.data.kind} 노드를 골랐어요` : "");
  }, []);
  focusRef.current = focusNode;

  const selected = s.nodes.find((n) => n.id === s.selectedId);
  const selEntry = s.catalog?.find((c) => c.type === selected?.data.kind);
  const selResult = selected ? s.report?.nodes[selected.id] : undefined;
  const nErrors = s.validation?.errors.length ?? 0;

  return (
    <div className="pg-root pg-theme" data-left={leftShown ? "open" : "closed"} data-right={rightShown ? "open" : "closed"}
         data-simple={s.simple || undefined} data-tight={tight || undefined} style={{ "--pg-right-w": `${panels.rightW}px` } as CSSProperties}>
      <header className="pg-toolbar">
        <h1 className="pg-title">포트폴리오 설계</h1>

        <div className="pg-edit-tools" role="toolbar" aria-label="편집">
          <button type="button" className="pg-icon-tool" aria-label="되돌리기 (Ctrl+Z)" title="되돌리기 (Ctrl+Z)"
                  disabled={s.past.length === 0} onClick={s.undo}><Undo2 size={16} /></button>
          <button type="button" className="pg-icon-tool" aria-label="다시하기 (Ctrl+Shift+Z)" title="다시하기 (Ctrl+Shift+Z)"
                  disabled={s.future.length === 0} onClick={s.redo}><Redo2 size={16} /></button>
          <button type="button" className="pg-icon-tool" aria-label="자동 정리" title="자동 정리"
                  disabled={s.nodes.length === 0} onClick={() => { s.autoLayout(); fit(); }}><LayoutGrid size={16} /></button>
          <button type="button" className="pg-icon-tool" aria-label="고른 노드 묶기 (Ctrl+G)" title="고른 노드 묶기 (Ctrl+G)"
                  disabled={s.picked.length < 2} onClick={() => s.groupPicked()}><Boxes size={16} /></button>
          <button type="button" className="pg-icon-tool pg-goal-open" aria-label="목표로 시작" title="목표로 시작 — 무엇을 하려는지 고르면 흐름을 만들어 계산해요"
                  disabled={!s.catalog} onClick={() => setGoalOpen(true)}><Sparkles size={16} /></button>
          <button type="button" className={`pg-icon-tool pg-simple-toggle${s.simple ? " on" : ""}`} aria-pressed={s.simple}
                  aria-label="간단히 보기" title="간단히 보기 — 노드 없이 정할 것과 결과만" onClick={() => s.setSimple(!s.simple)}>
            <LayoutList size={16} />
          </button>
          <span className="pg-strat-menu-wrap">
            <button type="button" className="pg-strat-add" aria-haspopup="menu" aria-expanded={stratOpen}
                    disabled={!s.catalog} onClick={() => setStratOpen((o) => !o)}>
              <Plus size={15} aria-hidden="true" />전략 추가
            </button>
            {stratOpen && (
              <div className="pg-strat-menu" role="menu" aria-label="전략 추가">
                <p className="pg-strat-menu-h">새 전략 띠로 넣고 ‘전략 합치기’에 이어요</p>
                {strategySources.map((x) => (
                  <button key={x.key} type="button" role="menuitem" className="pg-strat-item" data-source={x.key}
                          onClick={() => addStrategy(x.src)}>
                    <b>{x.label}</b><span>{x.sub}</span>
                  </button>
                ))}
              </div>
            )}
          </span>
          <button type="button" className={`pg-icon-tool${s.showMinimap ? " on" : ""}`} aria-pressed={s.showMinimap}
                  aria-label="미니맵" title="미니맵" onClick={() => s.setMinimap(!s.showMinimap)}><MapIcon size={16} /></button>
          <button type="button" className="pg-icon-tool pg-cmd-open" aria-label="명령 찾기 (Ctrl+K)" title="명령 찾기 (Ctrl+K)"
                  onClick={() => setCmdOpen(true)}><Command size={16} /></button>
        </div>
        <input className="pg-name" value={s.name} placeholder="이름 없는 설계" aria-label="설계 이름"
               onChange={(e) => s.setName(e.target.value)} />
        <span className="pg-toolbar-spacer" />
        {nErrors > 0 && <span className="pg-summary pg-summary--err">설정을 확인할 곳이 {nErrors}군데 있어요</span>}
        {s.reportStale && <span className="pg-summary pg-summary--stale">바뀐 설정으로 다시 계산해 주세요</span>}
        {s.report?.partial && !s.reportStale && (
          <span className="pg-summary pg-summary--partial">여기까지 계산 · {s.report.partial.computed.length}개</span>
        )}
        {s.report && !s.reportStale && !s.report.partial && (
          <span className="pg-summary">
            완료 {Object.values(s.report.nodes).filter((r) => r.status === "ok").length} · 막힘{" "}
            {Object.values(s.report.nodes).filter((r) => r.status === "blocked").length} · 실패{" "}
            {Object.values(s.report.nodes).filter((r) => r.status === "failed").length}
            {/* 좁은 화면에서도 누르지 않고 보이는 연습용 표시(BQ Q1) — 오른쪽 창이 닫혀 있고 노드 칩이 멀리 확대에서 숨어도 합성 수가 실데이터처럼 읽히지 않게. */}
            {Object.values(s.report.nodes).some((r) => r.lineage?.practice) && (
              <b className="pg-summary-practice" title="연습용 합성 데이터로 계산한 결과예요 — 실제 시세가 아니에요"> · 연습용</b>
            )}
          </span>
        )}
        <MoreMenu drawers={DRAWERS} onDrawer={(k) => setDrawer(k as DrawerKey)} onImport={applyLoad} canExport={s.nodes.length > 0}
                  getDoc={() => toDoc(s.nodes, s.edges, { name: s.name || undefined, exported_at: new Date().toISOString() }, s.groups, s.branches, s.pinned)} />
        <nav className="pg-drawers" aria-label="서랍">
          {DRAWERS.map((d) => (
            <button key={d.key} type="button" className="pg-drawer-open" aria-haspopup="dialog" title={d.sub}
                    aria-expanded={drawer === d.key} onClick={() => setDrawer(d.key)}>
              <d.Icon size={15} aria-hidden="true" /><span className="pg-tl">{d.label}</span>
            </button>
          ))}
        </nav>
        {topExtra}
        <ImportControl onLoad={applyLoad} />
        <ExportButton getDoc={() => toDoc(s.nodes, s.edges, { name: s.name || undefined, exported_at: new Date().toISOString() }, s.groups, s.branches, s.pinned)}
                      disabled={s.nodes.length === 0} />
        <button type="button" className="pg-run pg-btn pg-btn--primary" onClick={() => void run()} title="Ctrl+Enter"
                disabled={s.running || !s.catalog || s.nodes.length === 0}>
          {s.running ? <><Loader2 size={14} className="spin" /> 계산하는 중{s.runningIds ? ` · ${s.runningIds.length}개` : ""}</> : "계산하기"}
        </button>
      </header>


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
        <Sheet key={d.key} testId={d.key} open={drawer === d.key} onClose={() => setDrawer(null)} title={d.label} sub={d.sub}>
          <d.Body />
        </Sheet>
      ))}

      {/* 진행상황 알약(BQ Q2) — 캔버스 위 가운데. 간단히 보기에서는 그 위에 한 줄로. */}
      {s.simple && <GateRail report={s.report && !s.reportStale ? s.report.gates ?? null : null}
                  note={s.report?.partial && !s.reportStale ? s.report.gates_reason ?? null : null} />}
      {s.simple && (
        <SimpleView nodes={s.nodes} edges={s.edges} groups={s.groups} catalog={s.catalog ?? []}
                    results={s.report?.nodes ?? null} stale={s.reportStale} running={s.running} onRun={() => void run()}
                    onChange={(id, p) => s.updateParams(id, p)}
                    onCause={(id) => { s.setSimple(false); s.select(id); setTimeout(() => usePortfolioGraph.getState().showCause(id), 60); }} />
      )}
      <div className="pg-body" hidden={s.simple}>
        {s.catalog && <NodePalette catalog={s.catalog} stages={stages} initialQuery={legacy?.aliases[1] ?? ""} onAdd={(k) => addAt(k)} onTemplate={loadTemplate}
                                  onGoal={() => setGoalOpen(true)} hidden={!leftShown} onClose={() => updatePanels((p) => toggle(p, "left"))} />}
        {!leftShown && (
          <button type="button" className="pg-palette-fab" aria-label="노드 목록 열기 ([)" title="노드 추가 — 목록 열기 ([)"
                  onClick={() => updatePanels((p) => toggle(p, "left"))}><Plus size={20} aria-hidden="true" /></button>
        )}
        <div ref={canvasEl} className={`pg-canvas${dragOver ? " pg-canvas--drop" : ""}${s.growing ? " pg-growing" : ""}`}
             onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDragOver(e.dataTransfer.types.includes("Files")); }}
             onDragLeave={() => setDragOver(false)}
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
            onNodeContextMenu={(e, n) => {
              e.preventDefault();
              if (n.id.startsWith("frame:") || n.id.startsWith("branch:")) return;
              const box = canvasEl.current?.getBoundingClientRect();
              s.select(n.id);
              setCtx({ x: e.clientX - (box?.left ?? 0), y: e.clientY - (box?.top ?? 0), clientX: e.clientX, clientY: e.clientY, nodeId: n.id });
            }}
            onPaneContextMenu={(e) => {
              e.preventDefault();
              const box = canvasEl.current?.getBoundingClientRect();
              setCtx({ x: e.clientX - (box?.left ?? 0), y: e.clientY - (box?.top ?? 0), clientX: e.clientX, clientY: e.clientY, nodeId: null });
            }}
            snapToGrid
            snapGrid={[11, 11]}
            onInit={(inst) => { rf.current = inst; }}
            onNodeClick={(e, n) => { if (!n.id.startsWith("frame:") && !(e.shiftKey || e.metaKey || e.ctrlKey)) s.select(n.id); }}
            onPaneClick={() => { s.select(null); if (s.cause) s.showCause(null); }}
            onNodeDoubleClick={(_, n) => { if (n.id.startsWith("frame:")) s.setFocusGroup(n.id.slice(6)); }}
            deleteKeyCode={drawer || cmdOpen ? null : ["Backspace", "Delete"]}
            multiSelectionKeyCode={["Meta", "Control"]}
            defaultEdgeOptions={{ type: PG_WIRE_TYPE }}
            fitView
            fitViewOptions={{ padding: 0.08, maxZoom: 1 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.5} color="var(--pg-dot)" />
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
            {/* 확대·축소는 떠 있는 판 사이 가운데를 기준으로(BQ Q1) — 기본 단추는 판 뒤 캔버스 가운데를 기준으로 해 노드를 창 밑으로 민다. */}
            <Controls showZoom={false} showFitView={false} showInteractive={false}>
              <ControlButton className="react-flow__controls-zoomin" title="확대" aria-label="확대" onClick={() => zoomBy(1.2)}><Plus size={14} aria-hidden="true" /></ControlButton>
              <ControlButton className="react-flow__controls-zoomout" title="축소" aria-label="축소" onClick={() => zoomBy(1 / 1.2)}><Minus size={14} aria-hidden="true" /></ControlButton>
              <ControlButton className="react-flow__controls-fitview" title="맞춰 보기" aria-label="맞춰 보기"
                             onClick={() => fitClear(rf.current, canvasEl.current)}><Maximize size={13} aria-hidden="true" /></ControlButton>
            </Controls>
            {s.showMinimap && (
              <MiniMap pannable zoomable ariaLabel="미니맵" className="pg-minimap"
                       nodeColor={(n) => (n.type === PG_GROUP_TYPE ? "transparent"
                         : bandOf.has(n.id) ? `var(--pg-band-${bandOf.get(n.id)})` : "var(--pg-line)")} />
            )}
          </ReactFlow>
          <p className="pg-sr-live" aria-live="polite">{announce}</p>
          {!s.simple && <GateRail report={s.report && !s.reportStale ? s.report.gates ?? null : null}
                  note={s.report?.partial && !s.reportStale ? s.report.gates_reason ?? null : null} />}
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
          ) : <div className="pg-hint">{dragOver ? "그래프 파일을 놓으면 바로 불러와요"
            : s.picked.length > 1 ? `${s.picked.length}개 골랐어요 · Ctrl+G 묶기 · Ctrl+C 복사 · Delete 지우기`
            : s.selectedId ? "Alt+←→ 앞·뒤 단계로 · Alt+↑↓ 번호 순서로 · Shift+Enter 여기까지 계산"
            : "노드를 끌어 놓고, 같은 색 점끼리 이어 보세요. 선을 빈 곳에 놓으면 이을 노드를 찾아요 · 단축키 ?"}</div>}
          {quick && s.catalog && (
            <QuickAdd at={quick} catalog={s.catalog} stageKeys={stages.map((x) => x.key)}
                      fromKind={quick.from ? s.nodes.find((n) => n.id === quick.from!.node)?.data.kind ?? null : null}
                      box={canvasEl.current?.getBoundingClientRect()} inset={floatInsets(canvasEl.current)} onPick={quickPick} onClose={() => setQuick(null)} />
          )}
          {ctx && (
            <ContextMenu x={ctx.x} y={ctx.y} box={canvasEl.current?.getBoundingClientRect()} inset={floatInsets(canvasEl.current)} items={ctxItems}
                         label={ctx.nodeId ? "노드 메뉴" : "캔버스 메뉴"} onClose={() => setCtx(null)} />
          )}
          {findOpen && (
            <FindBar onPick={(id) => focusRef.current(id)} onClose={() => setFindOpen(false)}
                     nodes={s.nodes.map((n) => {
                       const entry = s.catalog?.find((c) => c.type === n.data.kind);
                       return { id: n.id, label: entry?.plain_label ?? n.data.kind, sub: nodeSummary(entry, n.data.params ?? {}) ?? n.id };
                     })} />
          )}
        </div>
        <aside className="pg-side" aria-label="설명과 설정" hidden={!rightShown}>
          <SideResize width={panels.rightW} onChange={(w, done) => (done ? updatePanels : setPanels)((p) => ({ ...p, rightW: w }))} />
          <header className="pg-side-head">
            <h2 className="pg-side-title">
              {selected ? (
                <>
                  <b className="pg-side-num" style={{ background: STAGE_VAR[selEntry?.stage ?? ""] ?? "var(--pg-st-data)" }}>{order.indexOf(selected.id) + 1}</b>
                  <span>{selEntry?.plain_label ?? selected.data.kind}</span>
                </>
              ) : <span>이 설계 한눈에</span>}
            </h2>
            <button type="button" className="pg-panel-toggle" data-panel="right" aria-label="오른쪽 창 닫기 (])" title="오른쪽 창 닫기 (])"
                    onClick={() => updatePanels((p) => toggle(p, "right"))}><PanelRightClose size={18} aria-hidden="true" /></button>
          </header>
          <nav className="pg-tabs" role="tablist">
            {TABS.filter(([k]) => k !== "branches" || s.branches.length > 0).map(([k, label]) => (
              <button key={k} type="button" role="tab" aria-selected={s.tab === k}
                      className={`pg-tab${s.tab === k ? " on" : ""}`} data-tab={k} onClick={() => s.setTab(k)}>{label}</button>
            ))}
          </nav>
          <div className="pg-panel">
            {s.tab === "story" && (
              <StoryPanel order={order} nodes={s.nodes} catalog={s.catalog ?? []} results={s.report?.nodes ?? null}
                          stale={s.reportStale} selectedId={s.selectedId} onSelect={focusNode}
                          onDetail={(id) => { focusNode(id); s.setTab("detail"); }} />
            )}
            {s.tab === "branches" && (
              <BranchCompare branches={s.branches} nodes={s.nodes} catalog={s.catalog ?? []}
                             results={s.report?.nodes ?? null} stale={s.reportStale} />
            )}
            {s.tab !== "story" && s.tab !== "branches" && !selected && (
              <p className="pg-empty">캔버스나 이야기에서 노드를 하나 골라 주세요.</p>
            )}
            {s.tab === "settings" && selected && (
              <SettingsPanel node={selected} entry={selEntry} nodes={s.nodes} edges={s.edges} catalog={s.catalog ?? []}
                             expert={s.expert} onExpert={s.setExpert}
                             onChange={(p) => s.updateParams(selected.id, p)} onRemove={() => s.removeNode(selected.id)}
                             onDuplicate={() => s.duplicateNode(selected.id)}
                             result={selResult} stale={s.reportStale}
                             onSave={() => portfolioGraphApi.save(toDoc(s.nodes, s.edges), selected.id, selResult?.view_hash ?? "")}
                             saveFollowUp={selected.data.kind === "backtest_setup" ? {
                               label: "결과 불러오기 노드 추가",
                               run: (runId) => {
                                 // 시작한 실행을 읽는 노드를 설정 노드 오른쪽에 붙이고 고른다 — 링크는 없다(읽기는 run_id 로 한다).
                                 const st = usePortfolioGraph.getState();
                                 const id = st.addNode("backtest_load", { x: selected.position.x + 240, y: selected.position.y });
                                 st.updateParams(id, { run_id: runId });
                                 st.select(id);
                               },
                             } : null} />
            )}
            {s.tab === "detail" && selected && (
              <>
              <NodeResultPanel
                kind={selected.data.kind}
                result={selResult}
                stale={s.reportStale}
                params={selected.data.params}
                onReload={() => void runTo(selected.id)}
              />
              <h4 className="pg-h4 pg-history-h">계산 기록</h4>
              <RunHistory nodeId={selected.id} runs={s.runs} />
              </>
            )}
          </div>
        </aside>
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

/** 오른쪽 창 폭 손잡이(BQ Q1) — 끌거나, 초점을 두고 ←(넓게)·→(좁게)·Home·End. 300~600px. 끝났을 때만 이 브라우저에 남긴다. */
function SideResize({ width, onChange }: { width: number; onChange: (w: number, done: boolean) => void }) {
  const drag = useRef<{ x: number; w: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const onKey = (e: ReactKeyboardEvent) => {
    const next = e.key === "ArrowLeft" ? width + RIGHT_W.step : e.key === "ArrowRight" ? width - RIGHT_W.step
      : e.key === "Home" ? RIGHT_W.min : e.key === "End" ? RIGHT_W.max : null;
    if (next === null) return;
    e.preventDefault();
    onChange(clampW(next), true);
  };
  const move = (e: ReactPointerEvent) => { if (drag.current) onChange(clampW(drag.current.w + (drag.current.x - e.clientX)), false); };
  const end = (e: ReactPointerEvent) => {
    if (!drag.current) return;
    onChange(clampW(drag.current.w + (drag.current.x - e.clientX)), true);
    drag.current = null;
    setDragging(false);
  };
  return (
    <div className="pg-side-resize" role="separator" aria-orientation="vertical" aria-label="오른쪽 창 폭"
         aria-valuemin={RIGHT_W.min} aria-valuemax={RIGHT_W.max} aria-valuenow={width} tabIndex={0}
         data-drag={dragging || undefined} onKeyDown={onKey}
         onPointerDown={(e) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x: e.clientX, w: width }; setDragging(true); }}
         onPointerMove={move} onPointerUp={end} onPointerCancel={end} />
  );
}

export default PortfolioCanvas;
