"use client";
/**
 * AAS 노드 캔버스 — 포트폴리오를 노드-링크 그래프로 설계·분석한다 (BI3 · ADR 002)
 * ==========================================================================
 * ★캔버스는 편집기다. 계산은 백엔드가 한다★(`POST /api/v1/allocation/graph/run`) — 노드는
 * `/analyze`·`/backtest` 와 같은 함수를 부른다(BI2 골든).
 *
 * - 팔레트·포트·파라미터 폼은 서버 카탈로그 하나에서 온다.
 * - 연결은 출력 타입 == 입력 타입일 때만, 입력 하나에 링크 하나, 순환 금지.
 * - 그래프가 바뀌면 곧바로 서버 검증을 불러 노드 위에 오류를 빨갛게 그린다.
 * - 불러오기(파일 선택·드래그앤드롭)는 **즉시** 캔버스를 교체한다. 다른 포맷이면 캔버스를
 *   건드리지 않고 사유를 말한다. 모르는 노드는 버리지 않고 빨갛게 남긴다.
 * - ★마법사 세션에 직접 손대지 않는다★ — 넘기기는 `onHandoff` 로 알릴 뿐이고 세션에 쓰는
 *   것은 app 계층이다(FSD: 위젯끼리 import 금지).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Connection,
  type ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";
import { LayoutTemplate, Loader2, Play } from "lucide-react";
import {
  buildHandoff,
  CORE_CHAIN_TEMPLATE,
  parseFile,
  PG_NODE_TYPE,
  portfolioGraphApi,
  toDoc,
  type HandoffPayload,
  type ParseResult,
} from "@/entities/portfolio-graph";
import { ExportButton, ImportControl, readGraphFile } from "@/features/portfolio-graph-io";
import { GraphNode } from "./GraphNode";
import { NodeInspector } from "./NodeInspector";
import { NodePalette, PALETTE_MIME } from "./NodePalette";
import { NodeResultPanel } from "./NodeResultPanel";
import { usePortfolioGraph } from "./store";

const NODE_TYPES = { [PG_NODE_TYPE]: GraphNode };
const WIP_KEY = "alpha_pg_wip";

export interface HandoffTarget { href: string; label: string }

export interface PortfolioCanvasProps {
  /** 옵티마이저 결과를 마법사 도구로 넘길 때. 없으면 넘기기 버튼을 그리지 않는다. */
  onHandoff?: (payload: HandoffPayload, target: HandoffTarget) => void;
  handoffTargets?: HandoffTarget[];
}

function readWip(): string | null {
  try { return typeof window === "undefined" ? null : sessionStorage.getItem(WIP_KEY); }
  catch { return null; }
}

export function PortfolioCanvas({ onHandoff, handoffTargets = [] }: PortfolioCanvasProps) {
  const s = usePortfolioGraph();
  const rf = useRef<ReactFlowInstance | null>(null);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  // ── 카탈로그 → 복원(세션) 또는 기본 사슬 ──────────────────────────────
  useEffect(() => {
    let alive = true;
    portfolioGraphApi.nodeTypes()
      .then((cat) => {
        if (!alive) return;
        usePortfolioGraph.getState().setCatalog(cat.nodes);
        const saved = readWip();
        const parsed = saved ? parseFile(saved) : null;
        const st = usePortfolioGraph.getState();
        if (st.nodes.length === 0) st.loadDoc(parsed?.doc ?? CORE_CHAIN_TEMPLATE, parsed?.problems ?? []);
        setTimeout(() => rf.current?.fitView({ padding: 0.15 }), 50);
      })
      .catch((e: Error) => { if (alive) usePortfolioGraph.getState().setCatalog(null, e.message); });
    return () => { alive = false; };
  }, []);

  const doc = useMemo(() => toDoc(s.nodes, s.edges, s.name ? { name: s.name } : undefined),
    [s.nodes, s.edges, s.name]);

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
    // 순환: target 에서 출발해 source 에 닿으면 안 된다.
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
  const canvasEl = useRef<HTMLDivElement>(null);
  const addCount = useRef(0);
  const addAt = useCallback((kind: string, pos?: { x: number; y: number }) => {
    let at = pos;
    if (!at) {
      const r = canvasEl.current?.getBoundingClientRect();
      const k = addCount.current++ % 6;
      at = r && rf.current
        ? rf.current.screenToFlowPosition({ x: r.left + r.width / 2 + k * 28, y: r.top + r.height / 2 + k * 28 })
        : { x: 200 + k * 28, y: 200 + k * 28 };
    }
    usePortfolioGraph.getState().addNode(kind, at);
  }, []);

  const applyLoad = useCallback((r: ParseResult, fileName: string) => {
    if (!r.doc) {
      setFileNote(`「${fileName}」을 불러오지 않았습니다 — ${r.problems.join(" ")} 캔버스는 그대로입니다.`);
      return;
    }
    usePortfolioGraph.getState().loadDoc(r.doc, r.problems);
    setFileNote(`「${fileName}」을 불러왔습니다 — 노드 ${r.doc.nodes.length}개 · 링크 ${r.doc.edges.length}개.`);
    setTimeout(() => rf.current?.fitView({ padding: 0.15 }), 50);
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
    try {
      st.finishRun(await portfolioGraphApi.run(toDoc(st.nodes, st.edges)));
    } catch (e) {
      st.finishRun(null, (e as Error).message);
    }
  }, []);

  const selected = s.nodes.find((n) => n.id === s.selectedId);
  const selEntry = s.catalog?.find((c) => c.type === selected?.data.kind);
  const selResult = selected ? s.report?.nodes[selected.id] : undefined;
  const counts = s.report && !s.reportStale
    ? Object.values(s.report.nodes).reduce((a, r) => ({ ...a, [r.status]: (a[r.status] ?? 0) + 1 }), {} as Record<string, number>)
    : null;
  const nErrors = s.validation?.errors.length ?? 0;

  const handoff = selected?.data.kind === "optimizer" && onHandoff && !s.reportStale
    ? buildHandoff(doc, selected.id, s.report?.nodes ?? null) : null;

  return (
    <div className="pg-root">
      <div className="pg-toolbar">
        <input className="pg-name" value={s.name} placeholder="그래프 이름"
               onChange={(e) => s.setName(e.target.value)} aria-label="그래프 이름" />
        <button type="button" className="pg-run pg-btn pg-btn--primary" onClick={run}
                disabled={s.running || !s.catalog || s.nodes.length === 0}>
          {s.running ? <Loader2 size={13} className="spin" /> : <Play size={13} />} 실행
        </button>
        <ImportControl onLoad={applyLoad} />
        <ExportButton getDoc={() => toDoc(s.nodes, s.edges, { name: s.name || undefined, exported_at: new Date().toISOString() })}
                      disabled={s.nodes.length === 0} />
        <button type="button" className="pg-template pg-btn" disabled={!s.catalog}
                onClick={() => { s.loadDoc(CORE_CHAIN_TEMPLATE); setFileNote("기본 사슬을 불러왔습니다(예시 종목 — 유니버스 노드에서 바꾸세요)."); setTimeout(() => rf.current?.fitView({ padding: 0.15 }), 50); }}>
          <LayoutTemplate size={13} /> 기본 사슬
        </button>
        <span className="pg-toolbar-spacer" />
        {counts && (
          <span className="pg-summary">
            완료 {counts.ok ?? 0} · 막힘 {counts.blocked ?? 0} · 실패 {counts.failed ?? 0}
          </span>
        )}
        {s.reportStale && <span className="pg-summary pg-summary--stale">결과가 현재 그래프와 다릅니다 — 다시 실행</span>}
        {nErrors > 0 && <span className="pg-summary pg-summary--err">검증 오류 {nErrors}</span>}
      </div>

      {s.catalogError && (
        <p className="pg-banner pg-banner--err">노드 카탈로그를 불러오지 못했습니다 — {s.catalogError}. 서버가 없으면 캔버스를 그릴 수 없습니다.</p>
      )}
      {s.runError && <p className="pg-banner pg-banner--err">실행 요청이 실패했습니다 — {s.runError}</p>}
      {fileNote && <p className="pg-banner pg-file-note">{fileNote}</p>}
      {s.loadProblems.length > 0 && (
        <div className="pg-banner pg-banner--warn pg-load-problems">
          불러오면서 건너뛴 항목 {s.loadProblems.length}개:
          <ul>{s.loadProblems.map((p, i) => <li key={i}>{p}</li>)}</ul>
        </div>
      )}
      {(s.validation?.errors ?? []).filter((e) => !e.node_id).map((e, i) => (
        <p key={i} className="pg-banner pg-banner--err">{e.code}: {e.message}</p>
      ))}

      <div className="pg-body">
        {s.catalog && <NodePalette catalog={s.catalog} onAdd={(k) => addAt(k)} />}
        <div ref={canvasEl} className={`pg-canvas${dragOver ? " pg-canvas--drop" : ""}`}
             onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDragOver(e.dataTransfer.types.includes("Files")); }}
             onDragLeave={() => setDragOver(false)}
             onDrop={onDrop}>
          <ReactFlow
            nodes={s.nodes}
            edges={s.edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={s.onNodesChange}
            onEdgesChange={s.onEdgesChange}
            onConnect={s.connect}
            isValidConnection={isValidConnection}
            onInit={(inst) => { rf.current = inst; }}
            onNodeClick={(_, n) => s.select(n.id)}
            onPaneClick={() => s.select(null)}
            deleteKeyCode={["Backspace", "Delete"]}
            defaultEdgeOptions={{ type: "smoothstep" }}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable className="pg-minimap" />
          </ReactFlow>
          {dragOver && <div className="pg-drop-hint">그래프 파일을 놓으면 바로 불러옵니다</div>}
        </div>
        <aside className="pg-side">
          {!selected && (
            <p className="pg-panel-note">
              노드를 누르면 설정과 결과가 여기 보입니다. 왼쪽 팔레트에서 노드를 끌어 오고, 포트를 끌어
              같은 색(같은 타입)끼리 잇습니다. 그래프 파일(.portfolio-graph.json)을 캔버스에 놓으면 바로 불러옵니다.
            </p>
          )}
          {selected && (
            <>
              <NodeInspector node={selected} entry={selEntry}
                             onChange={(p) => s.updateParams(selected.id, p)}
                             onRemove={() => s.removeNode(selected.id)} />
              <h3 className="pg-h3">결과</h3>
              <NodeResultPanel
                kind={selected.data.kind}
                result={selResult}
                stale={s.reportStale}
                extra={handoff && (
                  <div className="pg-handoff-box">
                    <h4 className="pg-h4">마법사 도구로 보내기</h4>
                    {handoff.payload ? (
                      <>
                        <p className="pg-note">숫자가 아니라 <b>입력</b>(종목·현재 비중·뷰·모델·제약)을 넘깁니다 — 마법사가 같은 계산(/analyze)으로 다시 구합니다.</p>
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
            </>
          )}
        </aside>
      </div>
    </div>
  );
}

export default PortfolioCanvas;
