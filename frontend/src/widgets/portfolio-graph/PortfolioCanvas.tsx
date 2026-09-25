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
 * - ★마법사 세션에 직접 손대지 않는다★ — 넘기기는 `onHandoff` 로 알릴 뿐이다(FSD).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  type Connection,
  type ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import { Loader2 } from "lucide-react";
import {
  buildHandoff,
  CORE_CHAIN_TEMPLATE,
  parseFile,
  PG_NODE_TYPE,
  portfolioGraphApi,
  toDoc,
  topoOrder,
  type HandoffPayload,
  type ParseResult,
  type WorkflowStage,
} from "@/entities/portfolio-graph";
import { ExportButton, ImportControl, readGraphFile } from "@/features/portfolio-graph-io";
import { GateRail } from "./GateRail";
import { GraphNode, PORT_COLORS } from "./GraphNode";
import { NodePalette, PALETTE_MIME } from "./NodePalette";
import { NodeResultPanel } from "./NodeResultPanel";
import { SettingsPanel } from "./SettingsPanel";
import { StoryPanel } from "./StoryPanel";
import { usePortfolioGraph } from "./store";

const NODE_TYPES = { [PG_NODE_TYPE]: GraphNode };
const WIP_KEY = "alpha_pg_wip";

export interface HandoffTarget { href: string; label: string }

export interface PortfolioCanvasProps {
  /** 옵티마이저 결과를 마법사 도구로 넘길 때. 없으면 넘기기 버튼을 그리지 않는다. */
  onHandoff?: (payload: HandoffPayload, target: HandoffTarget) => void;
  handoffTargets?: HandoffTarget[];
  /** 상단 바 오른쪽 — 예전 화면(마법사) 링크 등. app 계층이 채운다. */
  topExtra?: ReactNode;
}

function readWip(): string | null {
  try { return typeof window === "undefined" ? null : sessionStorage.getItem(WIP_KEY); }
  catch { return null; }
}

const TABS = [["story", "이야기"], ["settings", "설정"], ["detail", "자세히"]] as const;

export function PortfolioCanvas({ onHandoff, handoffTargets = [], topExtra }: PortfolioCanvasProps) {
  const s = usePortfolioGraph();
  const rf = useRef<ReactFlowInstance | null>(null);
  const canvasEl = useRef<HTMLDivElement>(null);
  const addCount = useRef(0);
  const [stages, setStages] = useState<WorkflowStage[]>([]);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const fit = () => setTimeout(() => rf.current?.fitView({ padding: 0.08, maxZoom: 1 }), 60);

  // ── 카탈로그 → 복원(세션) 또는 기본 사슬 ──────────────────────────────
  useEffect(() => {
    let alive = true;
    portfolioGraphApi.nodeTypes()
      .then((cat) => {
        if (!alive) return;
        setStages(cat.stages ?? []);
        usePortfolioGraph.getState().setCatalog(cat.nodes);
        const saved = readWip();
        const parsed = saved ? parseFile(saved) : null;
        const st = usePortfolioGraph.getState();
        if (st.nodes.length === 0) st.loadDoc(parsed?.doc ?? CORE_CHAIN_TEMPLATE, parsed?.problems ?? []);
        fit();
      })
      .catch((e: Error) => { if (alive) usePortfolioGraph.getState().setCatalog(null, e.message); });
    return () => { alive = false; };
  }, []);

  const doc = useMemo(() => toDoc(s.nodes, s.edges, s.name ? { name: s.name } : undefined),
    [s.nodes, s.edges, s.name]);
  const order = useMemo(() => topoOrder(s.nodes.map((n) => n.id), s.edges), [s.nodes, s.edges]);
  const numbered = useMemo(() => {
    const num = new Map(order.map((id, i) => [id, i + 1]));
    // 선택은 스토어의 selectedId 하나가 진실 — 이야기 카드에서 고른 노드도 캔버스에서 선택돼 보인다.
    return s.nodes.map((n) => ({ ...n, selected: n.id === s.selectedId, data: { ...n.data, num: num.get(n.id) } }));
  }, [s.nodes, order, s.selectedId]);
  const edgesStyled = useMemo(() => s.edges.map((e) => {
    const kind = s.nodes.find((n) => n.id === e.source)?.data.kind;
    const out = s.catalog?.find((c) => c.type === kind)?.outputs.find((p) => p.name === e.sourceHandle);
    return { ...e, style: { stroke: out ? PORT_COLORS[out.type] ?? "#94a3b8" : "#94a3b8", strokeWidth: 2.5 } };
  }), [s.edges, s.nodes, s.catalog]);

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

  const loadTemplate = useCallback(() => {
    usePortfolioGraph.getState().loadDoc(CORE_CHAIN_TEMPLATE);
    setFileNote("기본 흐름을 불러왔어요. 종목은 예시예요 — ‘종목 고르기’에서 바꿔 보세요.");
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

  const run = useCallback(async () => {
    const st = usePortfolioGraph.getState();
    st.startRun();
    st.setOpenGate(null);
    try {
      st.finishRun(await portfolioGraphApi.run(toDoc(st.nodes, st.edges)));
    } catch (e) {
      st.finishRun(null, (e as Error).message);
    }
  }, []);

  // 단축키 — 입력 칸에 있을 때는 가로채지 않는다. Ctrl/⌘+Enter 계산 · Ctrl/⌘+D 복제 · Esc 관문 닫기.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      const st = usePortfolioGraph.getState();
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key === "Enter" && !st.running) { e.preventDefault(); void run(); }
      else if (mod && (e.key === "d" || e.key === "D") && st.selectedId) { e.preventDefault(); st.duplicateNode(st.selectedId); }
      else if (e.key === "Escape" && st.openGate) st.setOpenGate(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run]);

  const focusNode = useCallback((id: string) => {
    usePortfolioGraph.getState().select(id);
    const n = usePortfolioGraph.getState().nodes.find((x) => x.id === id);
    if (n && rf.current) rf.current.setCenter(n.position.x + 90, n.position.y + 60, { zoom: rf.current.getZoom(), duration: 250 });
  }, []);

  const selected = s.nodes.find((n) => n.id === s.selectedId);
  const selEntry = s.catalog?.find((c) => c.type === selected?.data.kind);
  const selResult = selected ? s.report?.nodes[selected.id] : undefined;
  const nErrors = s.validation?.errors.length ?? 0;
  const handoff = selected?.data.kind === "optimizer" && onHandoff && !s.reportStale
    ? buildHandoff(doc, selected.id, s.report?.nodes ?? null) : null;

  return (
    <div className="pg-root pg-theme">
      <header className="pg-toolbar">
        <h1 className="pg-title">포트폴리오 설계</h1>
        <input className="pg-name" value={s.name} placeholder="이름 없는 설계" aria-label="설계 이름"
               onChange={(e) => s.setName(e.target.value)} />
        <span className="pg-toolbar-spacer" />
        {nErrors > 0 && <span className="pg-summary pg-summary--err">설정을 확인할 곳이 {nErrors}군데 있어요</span>}
        {s.reportStale && <span className="pg-summary pg-summary--stale">바뀐 설정으로 다시 계산해 주세요</span>}
        {s.report && !s.reportStale && (
          <span className="pg-summary">
            완료 {Object.values(s.report.nodes).filter((r) => r.status === "ok").length} · 막힘{" "}
            {Object.values(s.report.nodes).filter((r) => r.status === "blocked").length} · 실패{" "}
            {Object.values(s.report.nodes).filter((r) => r.status === "failed").length}
          </span>
        )}
        {topExtra}
        <ImportControl onLoad={applyLoad} />
        <ExportButton getDoc={() => toDoc(s.nodes, s.edges, { name: s.name || undefined, exported_at: new Date().toISOString() })}
                      disabled={s.nodes.length === 0} />
        <button type="button" className="pg-run pg-btn pg-btn--primary" onClick={run} title="Ctrl+Enter"
                disabled={s.running || !s.catalog || s.nodes.length === 0}>
          {s.running ? <><Loader2 size={14} className="spin" /> 계산하는 중</> : "계산하기"}
        </button>
      </header>

      <GateRail report={s.report && !s.reportStale ? s.report.gates ?? null : null} />

      {s.catalogError && (
        <p className="pg-banner pg-banner--err">노드 목록을 불러오지 못했어요 — {s.catalogError}. 서버가 켜져 있는지 확인해 주세요.</p>
      )}
      {s.runError && <p className="pg-banner pg-banner--err">계산 요청이 실패했어요 — {s.runError}</p>}
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

      <div className="pg-body">
        {s.catalog && <NodePalette catalog={s.catalog} stages={stages} onAdd={(k) => addAt(k)} onTemplate={loadTemplate} />}
        <div ref={canvasEl} className={`pg-canvas${dragOver ? " pg-canvas--drop" : ""}`}
             onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDragOver(e.dataTransfer.types.includes("Files")); }}
             onDragLeave={() => setDragOver(false)}
             onDrop={onDrop}>
          <ReactFlow
            nodes={numbered}
            edges={edgesStyled}
            nodeTypes={NODE_TYPES}
            onNodesChange={s.onNodesChange}
            onEdgesChange={s.onEdgesChange}
            onConnect={s.connect}
            isValidConnection={isValidConnection}
            onInit={(inst) => { rf.current = inst; }}
            onNodeClick={(_, n) => s.select(n.id)}
            onPaneClick={() => s.select(null)}
            deleteKeyCode={["Backspace", "Delete"]}
            defaultEdgeOptions={{ type: "default" }}
            fitView
            fitViewOptions={{ padding: 0.08, maxZoom: 1 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="var(--pg-line)" />
            <Controls showInteractive={false} />
          </ReactFlow>
          <div className="pg-hint">{dragOver ? "그래프 파일을 놓으면 바로 불러와요" : "노드를 끌어 놓고, 같은 색 점끼리 이어 보세요."}</div>
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
                             onDuplicate={() => s.duplicateNode(selected.id)} />
            )}
            {s.tab === "detail" && selected && (
              <NodeResultPanel
                kind={selected.data.kind}
                result={selResult}
                stale={s.reportStale}
                extra={handoff && (
                  <div className="pg-handoff-box">
                    <h4 className="pg-h4">단계별 마법사로 이어서 보기</h4>
                    {handoff.payload ? (
                      <>
                        <p className="pg-note">계산된 숫자가 아니라 <b>입력</b>(종목·지금 비중·생각·방식·제약)을 넘겨요. 마법사가 같은 계산으로 다시 구해요.</p>
                        {handoff.payload.notCarried.length > 0 && (
                          <ul className="pg-list pg-handoff-notcarried">
                            {handoff.payload.notCarried.map((m, i) => <li key={i}>{m}</li>)}
                          </ul>
                        )}
                        <div className="pg-handoff-targets">
                          {handoffTargets.map((t) => (
                            <button key={t.href} type="button" className="pg-handoff pg-btn" data-href={t.href}
                                    onClick={() => onHandoff?.(handoff.payload!, t)}>
                              {t.label}
                            </button>
                          ))}
                        </div>
                      </>
                    ) : <p className="pg-warn">{handoff.reason}</p>}
                  </div>
                )}
              />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

export default PortfolioCanvas;
