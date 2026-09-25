"use client";
/**
 * 포트폴리오 캔버스 상태 (BI3) — reactflow 노드·엣지 + 카탈로그 + 검증·실행 보고.
 * ==========================================================================
 * ★낡은 결과를 새 그래프의 결과처럼 보이지 않는다★ — 노드·링크·파라미터가 바뀌면
 * `reportStale` 이 서고, 화면은 "현재 그래프의 결과가 아닙니다" 라고 말한다. 위치 이동은
 * 계산에 영향이 없으므로 결과를 낡게 만들지 않는다.
 */
import { create } from "zustand";
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "reactflow";
import {
  fromDoc,
  PG_NODE_TYPE,
  type GraphDoc,
  type NodeCatalogEntry,
  type PgNode,
  type RunReport,
  type ValidateReport,
} from "@/entities/portfolio-graph";

export interface PgState {
  catalog: NodeCatalogEntry[] | null;
  catalogError: string | null;
  nodes: PgNode[];
  edges: Edge[];
  name: string;
  report: RunReport | null;
  reportStale: boolean;
  validation: ValidateReport | null;
  /** 마지막 불러오기에서 건너뛴 것(깨진 링크 등) — 조용히 버리지 않고 말한다. */
  loadProblems: string[];
  selectedId: string | null;
  running: boolean;
  runError: string | null;

  setCatalog: (c: NodeCatalogEntry[] | null, err?: string | null) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  connect: (c: Connection) => void;
  addNode: (kind: string, position: { x: number; y: number }) => string;
  updateParams: (id: string, params: Record<string, unknown>) => void;
  removeNode: (id: string) => void;
  loadDoc: (doc: GraphDoc, problems?: string[]) => void;
  setName: (n: string) => void;
  select: (id: string | null) => void;
  setValidation: (v: ValidateReport | null) => void;
  startRun: () => void;
  finishRun: (r: RunReport | null, err?: string | null) => void;
}

let seq = 0;
const newId = (kind: string, taken: Set<string>) => {
  let id = "";
  do { id = `${kind}_${Date.now().toString(36)}${(++seq).toString(36)}`; } while (taken.has(id));
  return id;
};

const STRUCTURAL = new Set(["add", "remove", "reset"]);

export const usePortfolioGraph = create<PgState>((set, get) => ({
  catalog: null,
  catalogError: null,
  nodes: [],
  edges: [],
  name: "",
  report: null,
  reportStale: false,
  validation: null,
  loadProblems: [],
  selectedId: null,
  running: false,
  runError: null,

  setCatalog: (catalog, err = null) => set({ catalog, catalogError: err }),

  onNodesChange: (changes) => set((s) => {
    const structural = changes.some((c) => STRUCTURAL.has(c.type));
    const removed = new Set(changes.filter((c) => c.type === "remove").map((c) => (c as { id: string }).id));
    return {
      nodes: applyNodeChanges(changes, s.nodes) as PgNode[],
      edges: removed.size ? s.edges.filter((e) => !removed.has(e.source) && !removed.has(e.target)) : s.edges,
      selectedId: s.selectedId && removed.has(s.selectedId) ? null : s.selectedId,
      reportStale: s.reportStale || (structural && s.report !== null),
    };
  }),

  onEdgesChange: (changes) => set((s) => ({
    edges: applyEdgeChanges(changes, s.edges),
    reportStale: s.reportStale || (changes.some((c) => STRUCTURAL.has(c.type)) && s.report !== null),
  })),

  connect: (c) => set((s) => ({
    edges: addEdge({ ...c, id: `${c.source}.${c.sourceHandle}->${c.target}.${c.targetHandle}` }, s.edges),
    reportStale: s.report !== null,
  })),

  addNode: (kind, position) => {
    const id = newId(kind, new Set(get().nodes.map((n) => n.id)));
    const node: PgNode = { id, type: PG_NODE_TYPE, position, data: { kind, params: {} } };
    set((s) => ({ nodes: [...s.nodes, node], selectedId: id, reportStale: s.report !== null }));
    return id;
  },

  updateParams: (id, params) => set((s) => ({
    nodes: s.nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, params } } : n)),
    reportStale: s.report !== null,
  })),

  removeNode: (id) => set((s) => ({
    nodes: s.nodes.filter((n) => n.id !== id),
    edges: s.edges.filter((e) => e.source !== id && e.target !== id),
    selectedId: s.selectedId === id ? null : s.selectedId,
    reportStale: s.report !== null,
  })),

  loadDoc: (doc, problems = []) => {
    const { nodes, edges } = fromDoc(doc, get().catalog ?? []);
    set({
      nodes, edges, name: doc.meta?.name ?? "", loadProblems: problems,
      report: null, reportStale: false, validation: null, selectedId: null, runError: null,
    });
  },

  setName: (name) => set({ name }),
  select: (selectedId) => set({ selectedId }),
  setValidation: (validation) => set({ validation }),
  startRun: () => set({ running: true, runError: null }),
  finishRun: (report, err = null) => set((s) => ({
    running: false,
    runError: err,
    report: report ?? s.report,
    reportStale: report ? false : s.reportStale,
  })),
}));
