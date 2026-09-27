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
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Connection,
  type Node,
  type NodeChange,
  type ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import { Archive, Boxes, ClipboardList, Command, LayoutGrid, Loader2, Map as MapIcon, Redo2, Sigma, Undo2 } from "lucide-react";
import {
  CORE_CHAIN_TEMPLATE,
  TEMPLATES,
  parseFile,
  PG_NODE_TYPE,
  portfolioGraphApi,
  toDoc,
  topoOrder,
  type GraphDoc,
  type ParseResult,
  type WorkflowStage,
} from "@/entities/portfolio-graph";
import { ExportButton, ImportControl, readGraphFile } from "@/features/portfolio-graph-io";
import { AlphaSheetBody } from "./AlphaSheet";
import { CommandPalette, type PaletteCommand } from "./CommandPalette";
import { ExecutionSheetBody } from "./ExecutionSheet";
import { GateRail } from "./GateRail";
import { GraphNode, PORT_COLORS } from "./GraphNode";
import { GroupFrame, PG_GROUP_TYPE, type GroupFrameData } from "./GroupFrame";
import { NodePalette, PALETTE_MIME } from "./NodePalette";
import type { LegacyScreen } from "@/entities/portfolio-graph/legacyScreens";
import { NodeResultPanel } from "./NodeResultPanel";
import { RecordsSheetBody } from "./RecordsSheet";
import { SettingsPanel } from "./SettingsPanel";
import { Sheet } from "./Sheet";
import { StoryPanel } from "./StoryPanel";
import { RunHistory } from "./RunHistory";
import { ancestorsOf, usePortfolioGraph } from "./store";

const NODE_TYPES = { [PG_NODE_TYPE]: GraphNode, [PG_GROUP_TYPE]: GroupFrame };
/** 묶음 상자 여백·노드 카드 크기(대략) — 상자는 안의 노드를 감싸는 사각형이다. */
const GROUP_PAD = 28;
const NODE_W = 176;
const NODE_H = 150;
const WIP_KEY = "alpha_pg_wip";

export interface PortfolioCanvasProps {
  /** 상단 바 오른쪽 — 케이스 상자 등. app 계층이 채운다. */
  topExtra?: ReactNode;
  /** 다른 화면이 넘긴 흐름(BL2b — 매크로 스냅샷 등). 있으면 세션 복원 대신 이것을 연다. */
  initialDoc?: { doc: GraphDoc; note: string } | null;
  /** 옛 주소(`/allocation/<화면>` → `?from=`)로 왔을 때 그 예전 화면(BL4). 배너·팔레트 검색·템플릿·서랍을 안내한다. */
  legacy?: LegacyScreen | null;
}

function readWip(): string | null {
  try { return typeof window === "undefined" ? null : sessionStorage.getItem(WIP_KEY); }
  catch { return null; }
}

const TABS = [["story", "이야기"], ["settings", "설정"], ["detail", "자세히"]] as const;


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
  // 서랍(BL2) — 계산하지 않는 기록 화면. 노드가 아니라 캔버스 옆에서 연다.
  const [drawer, setDrawer] = useState<DrawerKey | null>(null);
  // 노드 카드의 "여기까지 계산" 버튼이 부를 함수 — 아래에서 정의되고, 카드는 이 참조로 부른다.
  const runToRef = useRef<(id: string) => void>(() => {});
  const previewRef = useRef<(id: string | null) => void>(() => {});

  const fit = () => setTimeout(() => rf.current?.fitView({ padding: 0.08, maxZoom: 1 }), 60);

  // ── 카탈로그 → 복원(세션) 또는 기본 사슬 ──────────────────────────────
  useEffect(() => {
    let alive = true;
    portfolioGraphApi.nodeTypes()
      .then((cat) => {
        if (!alive) return;
        setStages(cat.stages ?? []);
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

  const doc = useMemo(() => toDoc(s.nodes, s.edges, s.name ? { name: s.name } : undefined, s.groups),
    [s.nodes, s.edges, s.name, s.groups]);
  const order = useMemo(() => topoOrder(s.nodes.map((n) => n.id), s.edges), [s.nodes, s.edges]);
  /** 밝힐 경로 — 계산 중이면 계산하는 노드들, 아니면 "여기까지 계산" 에 올린 노드의 조상. */
  const path = useMemo(() => new Set(s.runningIds ?? s.preview ?? []), [s.runningIds, s.preview]);
  const hidden = useMemo(() => new Set(s.groups.filter((g) => g.collapsed).flatMap((g) => g.members)), [s.groups]);
  const numbered = useMemo(() => {
    const num = new Map(order.map((id, i) => [id, i + 1]));
    const picked = new Set(s.picked);
    // 선택은 스토어가 진실 — 이야기 카드에서 고른 노드도, 상자로 여러 개 고른 노드도 캔버스에서 선택돼 보인다.
    const cards: Node[] = s.nodes.map((n) => ({
      ...n, hidden: hidden.has(n.id), selected: picked.has(n.id) || n.id === s.selectedId,
      className: path.has(n.id) ? "pg-on-path" : undefined,
      data: { ...n.data, num: num.get(n.id), onRunTo: runToRef.current, onPreviewRunTo: previewRef.current },
    }));
    const frames: Node<GroupFrameData>[] = s.groups.map((g) => {
      const ms = s.nodes.filter((n) => g.members.includes(n.id));
      const x0 = Math.min(...ms.map((n) => n.position.x)) - GROUP_PAD;
      const y0 = Math.min(...ms.map((n) => n.position.y)) - GROUP_PAD - 30;
      const x1 = Math.max(...ms.map((n) => n.position.x)) + NODE_W + GROUP_PAD;
      const y1 = Math.max(...ms.map((n) => n.position.y)) + NODE_H + GROUP_PAD;
      return { id: `frame:${g.id}`, type: PG_GROUP_TYPE, position: { x: x0, y: y0 }, zIndex: -1, selectable: false,
               data: { groupId: g.id, label: g.label, collapsed: !!g.collapsed, members: g.members, width: x1 - x0, height: y1 - y0 } };
    });
    return [...frames, ...cards];
  }, [s.nodes, s.groups, order, s.selectedId, s.picked, path, hidden]);
  const edgesStyled = useMemo(() => s.edges.map((e) => {
    const kind = s.nodes.find((n) => n.id === e.source)?.data.kind;
    const out = s.catalog?.find((c) => c.type === kind)?.outputs.find((p) => p.name === e.sourceHandle);
    const lit = path.has(e.source) && path.has(e.target);
    return { ...e, animated: lit && s.running, className: lit ? "pg-edge--path" : undefined,
             style: { stroke: out ? PORT_COLORS[out.type] ?? "#94a3b8" : "#94a3b8", strokeWidth: lit ? 3.5 : 2.5 } };
  }), [s.edges, s.nodes, s.catalog, path, s.running]);

  /** 묶음 상자를 끌면 안의 노드가 함께 움직인다 — 상자 자리는 노드에서 계산하므로 차이만 옮긴다. */
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const st = usePortfolioGraph.getState();
    const rest: NodeChange[] = [];
    for (const c of changes) {
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
  runToRef.current = (id) => { if (!usePortfolioGraph.getState().running) void runTo(id); };
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
      else if (mod && e.key === "Enter" && !st.running) { e.preventDefault(); void run(); }
      else if (e.shiftKey && e.key === "Enter" && !st.running && st.selectedId) { e.preventDefault(); void runTo(st.selectedId); }
      else if (mod && k === "z" && !e.shiftKey) { e.preventDefault(); st.undo(); }
      else if (mod && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); st.redo(); }
      else if (mod && k === "c") { if (st.copy()) e.preventDefault(); }
      else if (mod && k === "v") { if (st.paste()) e.preventDefault(); }
      else if (mod && k === "g") { e.preventDefault(); st.groupPicked(); }
      else if (mod && k === "d" && st.selectedId) { e.preventDefault(); st.duplicateNode(st.selectedId); }
      else if (e.key === "Escape" && st.openGate) st.setOpenGate(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run, runTo]);

  const commands = useMemo<PaletteCommand[]>(() => [
    { id: "run", group: "계산", label: "전체 계산하기", keys: "Ctrl+Enter", run: () => void run() },
    ...(s.selectedId ? [{ id: "run-to", group: "계산", label: "고른 노드까지 계산", keys: "Shift+Enter",
                          run: () => void runTo(usePortfolioGraph.getState().selectedId!) }] : []),
    { id: "undo", group: "편집", label: "되돌리기", keys: "Ctrl+Z", run: () => usePortfolioGraph.getState().undo() },
    { id: "redo", group: "편집", label: "다시하기", keys: "Ctrl+Shift+Z", run: () => usePortfolioGraph.getState().redo() },
    { id: "layout", group: "보기", label: "자동 정리", hint: "흐름 순서대로 왼쪽에서 오른쪽으로 놓아요",
      run: () => { usePortfolioGraph.getState().autoLayout(); fit(); } },
    { id: "minimap", group: "보기", label: s.showMinimap ? "미니맵 끄기" : "미니맵 켜기",
      run: () => usePortfolioGraph.getState().setMinimap(!usePortfolioGraph.getState().showMinimap) },
    { id: "group", group: "편집", label: "고른 노드 묶기", keys: "Ctrl+G", hint: "노드를 두 개 이상 고르면 돼요",
      run: () => usePortfolioGraph.getState().groupPicked() },
    ...DRAWERS.map((d) => ({ id: `drawer:${d.key}`, group: "서랍", label: `${d.label} 열기`, hint: d.sub,
                             run: () => setDrawer(d.key) })),
    ...TEMPLATES.map((t) => ({ id: `tpl:${t.key}`, group: "템플릿", label: `${t.name} 불러오기`, hint: t.description,
                               run: () => loadTemplate(t.key) })),
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 명령은 열 때마다 새로 만든다
  ], [s.selectedId, s.showMinimap, cmdOpen]);

  const focusNode = useCallback((id: string) => {
    usePortfolioGraph.getState().select(id);
    const n = usePortfolioGraph.getState().nodes.find((x) => x.id === id);
    if (n && rf.current) rf.current.setCenter(n.position.x + 90, n.position.y + 60, { zoom: rf.current.getZoom(), duration: 250 });
  }, []);

  const selected = s.nodes.find((n) => n.id === s.selectedId);
  const selEntry = s.catalog?.find((c) => c.type === selected?.data.kind);
  const selResult = selected ? s.report?.nodes[selected.id] : undefined;
  const nErrors = s.validation?.errors.length ?? 0;

  return (
    <div className="pg-root pg-theme">
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
          </span>
        )}
        <nav className="pg-drawers" aria-label="서랍">
          {DRAWERS.map((d) => (
            <button key={d.key} type="button" className="pg-drawer-open" aria-haspopup="dialog"
                    aria-expanded={drawer === d.key} onClick={() => setDrawer(d.key)}>
              <d.Icon size={15} aria-hidden="true" />{d.label}
            </button>
          ))}
        </nav>
        {topExtra}
        <ImportControl onLoad={applyLoad} />
        <ExportButton getDoc={() => toDoc(s.nodes, s.edges, { name: s.name || undefined, exported_at: new Date().toISOString() }, s.groups)}
                      disabled={s.nodes.length === 0} />
        <button type="button" className="pg-run pg-btn pg-btn--primary" onClick={() => void run()} title="Ctrl+Enter"
                disabled={s.running || !s.catalog || s.nodes.length === 0}>
          {s.running ? <><Loader2 size={14} className="spin" /> 계산하는 중</> : "계산하기"}
        </button>
      </header>

      <GateRail report={s.report && !s.reportStale ? s.report.gates ?? null : null}
                note={s.report?.partial && !s.reportStale ? s.report.gates_reason ?? null : null} />

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
      {fileNote && <p className="pg-banner pg-file-note">{fileNote}</p>}
      {s.loadProblems.length > 0 && (
        <div className="pg-banner pg-banner--warn pg-load-problems">
          불러오면서 건너뛴 항목이 {s.loadProblems.length}개 있어요:
          <ul>{s.loadProblems.map((p, i) => <li key={i}>{p}</li>)}</ul>
        </div>
      )}
      {(s.validation?.errors ?? []).filter((e) => !e.node_id).map((e, i) => (
        <p key={i} className="pg-banner pg-banner--err">{e.message}</p>
      ))}

      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} catalog={s.catalog ?? []} commands={commands}
                      onAddNode={(k) => addAt(k)} />
      {DRAWERS.map((d) => (
        <Sheet key={d.key} testId={d.key} open={drawer === d.key} onClose={() => setDrawer(null)} title={d.label} sub={d.sub}>
          <d.Body />
        </Sheet>
      ))}

      <div className="pg-body">
        {s.catalog && <NodePalette catalog={s.catalog} stages={stages} initialQuery={legacy?.aliases[1] ?? ""} onAdd={(k) => addAt(k)} onTemplate={loadTemplate} />}
        <div ref={canvasEl} className={`pg-canvas${dragOver ? " pg-canvas--drop" : ""}`}
             onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDragOver(e.dataTransfer.types.includes("Files")); }}
             onDragLeave={() => setDragOver(false)}
             onDrop={onDrop}>
          <ReactFlow
            nodes={numbered}
            edges={edgesStyled}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgesChange={s.onEdgesChange}
            onConnect={s.connect}
            isValidConnection={isValidConnection}
            onInit={(inst) => { rf.current = inst; }}
            onNodeClick={(e, n) => { if (!n.id.startsWith("frame:") && !(e.shiftKey || e.metaKey || e.ctrlKey)) s.select(n.id); }}
            onPaneClick={() => s.select(null)}
            deleteKeyCode={drawer || cmdOpen ? null : ["Backspace", "Delete"]}
            multiSelectionKeyCode={["Meta", "Control"]}
            defaultEdgeOptions={{ type: "default" }}
            fitView
            fitViewOptions={{ padding: 0.08, maxZoom: 1 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="var(--pg-line)" />
            <Controls showInteractive={false} />
            {s.showMinimap && (
              <MiniMap pannable zoomable ariaLabel="미니맵" className="pg-minimap"
                       nodeColor={(n) => (n.type === PG_GROUP_TYPE ? "transparent" : "var(--pg-line)")} />
            )}
          </ReactFlow>
          <div className="pg-hint">{dragOver ? "그래프 파일을 놓으면 바로 불러와요"
            : s.picked.length > 1 ? `${s.picked.length}개 골랐어요 · Ctrl+G 묶기 · Ctrl+C 복사 · Delete 지우기`
            : "노드를 끌어 놓고, 같은 색 점끼리 이어 보세요. Shift 를 누른 채 끌면 여러 개를 골라요."}</div>
        </div>
        <aside className="pg-side" aria-label="설명과 설정">
          <nav className="pg-tabs" role="tablist">
            {TABS.map(([k, label]) => (
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
            {s.tab !== "story" && !selected && (
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
      </div>
    </div>
  );
}

export default PortfolioCanvas;
