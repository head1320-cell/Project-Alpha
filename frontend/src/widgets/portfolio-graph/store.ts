"use client";
/**
 * 포트폴리오 캔버스 상태 (BI3 → BL1) — reactflow 노드·엣지 + 카탈로그 + 검증·실행 보고.
 * ==========================================================================
 * ★낡은 결과를 새 그래프의 결과처럼 보이지 않는다★ — 노드·링크·파라미터가 바뀌면
 * `reportStale` 이 서고, 화면은 "현재 그래프의 결과가 아닙니다" 라고 말한다. 위치 이동은
 * 계산에 영향이 없으므로 결과를 낡게 만들지 않는다.
 *
 * BL1 (조사 → 적용):
 * - **여기까지 계산**(n8n Execute step): 부분 계산 결과를 이전 결과에 **합치되**, 이번에 계산하지 않은 노드는
 *   `previous: true` 로 표시한다 — 이전 값을 지금 값처럼 보이지 않는다.
 * - **되돌리기/다시하기**: 구조·설정·위치(끌기 한 번 = 한 단계)를 스냅숏 50개까지.
 * - **여러 개 고르기 · 복사/붙여넣기**: 붙여넣으면 id 를 새로 받고, 링크는 **고른 것끼리**만 따라온다.
 * - **자동 정리**: 위상 깊이로 열, 같은 깊이는 이전 세로 순서 — 새 의존성 없음.
 * - **묶음 상자**(KNIME 메타노드·ComfyUI 서브그래프): 문서의 `groups` — 계산에는 끼지 않는 화면 정보다.
 * - **계산 기록**: 세션 최근 10회 — 노드마다 상태·헤드라인을 남겨 두 계산을 비교한다.
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
  GRAPH_FORMAT,
  GRAPH_VERSION,
  blockFromGroup,
  branchScope,
  MAX_BRANCHES,
  nextBranchLetter,
  insertDoc,
  mapLayout,
  readBlocks,
  toDoc,
  writeBlocks,
  PG_NODE_TYPE,
  PORTFOLIO_NODE,
  PORTFOLIO_PORTS,
  portfolioLane,
  STRATEGY_COLORS,
  strategyOutput,
  topoOrder,
  type GraphBlock,
  type GraphBranch,
  type LaneBox,
  type WorkflowStage,
  type GraphDoc,
  type GraphDocEdge,
  type GraphDocNode,
  type GraphGroup,
  type NodeCatalogEntry,
  type NodeStatus,
  type PgNode,
  type RunReport,
  type ValidateReport,
} from "@/entities/portfolio-graph";

/** 계산 기록 한 줄 — 노드마다 상태와 헤드라인만(원 결과는 두지 않는다: 가볍게, 비교에 필요한 만큼). */
export interface RunRecord {
  at: number;
  partial: string[] | null;
  counts: { ok: number; blocked: number; failed: number };
  nodes: Record<string, { status: NodeStatus; headline: string | null; value: number | null }>;
}

interface Snapshot { nodes: PgNode[]; edges: Edge[]; groups: GraphGroup[]; branches?: GraphBranch[] }

export interface PgState {
  catalog: NodeCatalogEntry[] | null;
  catalogError: string | null;
  nodes: PgNode[];
  edges: Edge[];
  groups: GraphGroup[];
  name: string;
  report: RunReport | null;
  reportStale: boolean;
  validation: ValidateReport | null;
  /** 마지막 불러오기에서 건너뛴 것(깨진 링크 등) — 조용히 버리지 않고 말한다. */
  loadProblems: string[];
  selectedId: string | null;
  /** 함께 고른 노드들(상자 끌기·Shift) — 복사·묶기·삭제의 대상. `selectedId` 는 그중 패널에 보이는 하나. */
  picked: string[];
  running: boolean;
  /** 지금 계산 중인 노드들(부분 계산이면 대상의 조상) — 경로를 밝힌다. */
  runningIds: string[] | null;
  /** "여기까지 계산" 에 마우스를 올렸을 때 계산될 노드 — 누르기 전에 무엇이 돌지 보인다. */
  preview: string[] | null;
  runError: string | null;
  runs: RunRecord[];
  past: Snapshot[];
  future: Snapshot[];
  clip: { nodes: PgNode[]; edges: Edge[] } | null;
  showMinimap: boolean;
  /** 오른쪽 패널 탭 · 전문가 설정 · 펼친 관문 (BJ3). */
  tab: "story" | "settings" | "detail" | "branches";
  expert: boolean;
  openGate: string | null;
  /** 미리보기 고정(BM C1 · TouchDesigner 뷰어 플래그) — 어떤 확대에서도 작은 그림을 보인다. 화면 정보(파일에 없다). */
  pinned: string[];
  /** 원인 경로(BM C1) — 막힘·실패 노드에서 계산 못 한 상류를 따라 첫 원인까지. 켜지면 나머지는 흐려진다. */
  cause: { from: string; path: string[]; roots: string[] } | null;
  /** 단계 순서(서버 카탈로그) — 전략 지도 정리의 열 순서. */
  stages: WorkflowStage[];
  /** 전략 지도 정리가 그린 단계 레인(BM C2) — 다른 정리를 하거나 불러오면 지운다. */
  lanes: { lanes: LaneBox[]; height: number; portfolioX: number } | null;
  /** 들어간 전략 상자(ComfyUI 서브그래프 들어가기) — 나머지는 흐리게, 상단에 빵부스러기. */
  focusGroup: string | null;
  /** 캔버스 필터(Dataiku) — 맞지 않는 노드·선을 흐린다. 여러 개면 하나라도 맞으면 남긴다. */
  filters: FilterKey[];
  /** 내 블록(이 브라우저) — 저장소를 못 쓰면 `blocksAvailable: false`(없음과 다르다). 신뢰 저장은 파일. */
  blocks: GraphBlock[];
  blocksAvailable: boolean;
  /** 갈래(BM C3) — 화면 정보. 복제 노드 자체는 보통 노드다. */
  branches: GraphBranch[];
  /** 캔버스 한 줄 안내(전략 추가·블록 저장 결과). */
  note: string | null;

  setCatalog: (c: NodeCatalogEntry[] | null, err?: string | null) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  connect: (c: Connection) => void;
  addNode: (kind: string, position: { x: number; y: number }) => string;
  updateParams: (id: string, params: Record<string, unknown>) => void;
  removeNode: (id: string) => void;
  removePicked: () => void;
  /** 같은 입력(들어오는 링크)·같은 설정으로 옆에 하나 더 — 설정만 바꿔 나란히 비교할 때. 나가는 링크는 잇지 않는다. */
  duplicateNode: (id: string) => string | null;
  loadDoc: (doc: GraphDoc, problems?: string[]) => void;
  setName: (n: string) => void;
  select: (id: string | null) => void;
  setValidation: (v: ValidateReport | null) => void;
  startRun: (ids?: string[] | null) => void;
  finishRun: (r: RunReport | null, err?: string | null) => void;
  setPreview: (ids: string[] | null) => void;
  undo: () => void;
  redo: () => void;
  copy: () => number;
  paste: () => number;
  autoLayout: () => void;
  groupPicked: (label?: string) => string | null;
  ungroup: (id: string) => void;
  toggleGroup: (id: string) => void;
  renameGroup: (id: string, label: string) => void;
  moveGroup: (id: string, dx: number, dy: number) => void;
  setMinimap: (v: boolean) => void;
  setTab: (t: PgState["tab"]) => void;
  setExpert: (v: boolean) => void;
  setOpenGate: (k: string | null) => void;
  togglePin: (id: string) => void;
  showCause: (id: string | null) => void;
  setStages: (st: WorkflowStage[]) => void;
  /** 전략 하나를 새 띠로 넣고 포트폴리오 노드에 잇는다. 전략이 처음이면 지금 흐름을 ‘전략 1’로 묶는다. 돌려주는 값은 한 줄 안내. */
  addStrategy: (src: { label: string; nodes: GraphDocNode[]; edges: GraphDocEdge[]; output?: string | null }) => string;
  /** 고른 노드를 전략 상자로 묶는다 — 비중을 내는 노드가 없으면 묶지 않고 사유. */
  strategyPicked: () => string;
  insertBlock: (b: GraphBlock) => string;
  setFocusGroup: (id: string | null) => void;
  toggleFilter: (k: FilterKey) => void;
  clearLanes: () => void;
  loadBlocks: () => void;
  /** 상자를 내 블록으로 — 이 브라우저에 넣고, 파일로 받을 수 있게 블록을 돌려준다(저장소가 막혀도 파일은 된다). */
  saveBlock: (groupId: string) => GraphBlock | null;
  removeBlock: (index: number) => void;
  setNote: (n: string | null) => void;
  /** 이 노드와 같은 전략 안의 하류를 복제해 갈래를 만든다 — 한 뿌리에 최대 4개. 돌려주는 값은 한 줄 안내. */
  makeBranch: (rootId: string) => string;
  /** 갈래를 지운다 — 복제 노드도 함께. */
  removeBranch: (id: string) => void;
}

export type FilterKey = "failed" | "blocked" | "practice" | "forward" | "assumed";

/** 전략 이름 — 이미 있는 이름이면 숫자를 붙인다(포트폴리오 노드는 이름이 겹치면 사유와 함께 멈춘다). */
function uniqueLabel(want: string, groups: GraphGroup[]): string {
  const taken = new Set(groups.map((g) => g.label));
  if (!taken.has(want)) return want;
  for (let k = 2; ; k++) if (!taken.has(`${want} ${k}`)) return `${want} ${k}`;
}

let seq = 0;
const newId = (kind: string, taken: Set<string>) => {
  let id = "";
  do { id = `${kind}_${Date.now().toString(36)}${(++seq).toString(36)}`; } while (taken.has(id));
  return id;
};

const STRUCTURAL = new Set(["add", "remove", "reset"]);
const HISTORY = 50;
const RUNS = 10;
/** 같은 노드의 설정을 잇달아 고치면 한 단계로 묶는다(글자 하나마다 되돌리기 한 번이면 못 쓴다). */
const COALESCE_MS = 800;
let lastParamEdit: { id: string; at: number } | null = null;
let dragging = false;

/** 조상(자신 포함) — 서버 `portfolio_graph._ancestors` 와 같은 규칙. "여기까지 계산" 이 돌 노드들. */
export function ancestorsOf(ids: string[], edges: { source: string; target: string }[]): string[] {
  const into = new Map<string, string[]>();
  for (const e of edges) into.set(e.target, [...(into.get(e.target) ?? []), e.source]);
  const seen = new Set<string>();
  const stack = [...ids];
  while (stack.length) {
    const n = stack.pop()!;
    if (seen.has(n)) continue;
    seen.add(n);
    stack.push(...(into.get(n) ?? []));
  }
  return [...seen];
}

/**
 * 원인 경로 — `id` 에서 상류로, **완료가 아닌** 노드만 따라 올라간다(완료된 상류는 원인이 아니다).
 * 뿌리 = 계산 못 한 상류가 더 없는 노드(스스로 실패했거나 자기 설정 때문에 막힌 노드). 결과가 없는 노드는 따라가지 않는다.
 */
export function causePath(id: string, edges: { source: string; target: string }[],
                          results: Record<string, { status: NodeStatus }> | null | undefined): { path: string[]; roots: string[] } {
  const bad = (n: string) => !!results?.[n] && results[n].status !== "ok";
  if (!bad(id)) return { path: [], roots: [] };
  const seen = new Set<string>();
  const roots: string[] = [];
  const stack = [id];
  while (stack.length) {
    const n = stack.pop()!;
    if (seen.has(n)) continue;
    seen.add(n);
    const up = edges.filter((e) => e.target === n && bad(e.source)).map((e) => e.source);
    if (!up.length) roots.push(n);
    stack.push(...up);
  }
  return { path: [...seen], roots };
}

const clean = (nodes: PgNode[]) => nodes.map((n) => ({ ...n, selected: false, dragging: false }));

function record(report: RunReport, partial: string[] | null): RunRecord {
  const nodes: RunRecord["nodes"] = {};
  const counts = { ok: 0, blocked: 0, failed: 0 };
  for (const [id, r] of Object.entries(report.nodes)) {
    if (r.previous) continue;
    counts[r.status] += 1;
    const h = r.explain?.headline;
    nodes[id] = { status: r.status, headline: h ? (h.text ?? (h.value != null ? `${h.value}${h.unit ?? ""}` : null)) : null,
                  value: typeof h?.value === "number" ? h.value : null };
  }
  return { at: Date.now(), partial, counts, nodes };
}

export const usePortfolioGraph = create<PgState>((set, get) => {
  /** 지금 상태를 되돌리기 칸에 넣는다 — 바꾸기 **직전**에 부른다. */
  const push = () => set((s) => ({
    past: [...s.past, { nodes: clean(s.nodes), edges: s.edges, groups: s.groups, branches: s.branches }].slice(-HISTORY),
    future: [],
  }));

  return {
    catalog: null,
    catalogError: null,
    nodes: [],
    edges: [],
    groups: [],
    name: "",
    report: null,
    reportStale: false,
    validation: null,
    loadProblems: [],
    selectedId: null,
    picked: [],
    running: false,
    runningIds: null,
    preview: null,
    runError: null,
    runs: [],
    past: [],
    future: [],
    clip: null,
    showMinimap: false,
    tab: "story",
    expert: false,
    openGate: null,
    pinned: [],
    cause: null,
    stages: [],
    lanes: null,
    focusGroup: null,
    filters: [],
    blocks: [],
    blocksAvailable: true,
    note: null,
    branches: [],

    setCatalog: (catalog, err = null) => set({ catalog, catalogError: err }),

    onNodesChange: (changes) => {
      const structural = changes.some((c) => STRUCTURAL.has(c.type));
      const drag = changes.find((c) => c.type === "position") as { dragging?: boolean } | undefined;
      if (structural) push();
      else if (drag?.dragging && !dragging) { dragging = true; push(); }          // 끌기 한 번 = 한 단계
      if (drag && drag.dragging === false) dragging = false;
      set((s) => {
        const removed = new Set(changes.filter((c) => c.type === "remove").map((c) => (c as { id: string }).id));
        const nodes = applyNodeChanges(changes, s.nodes) as PgNode[];
        const selChanged = changes.some((c) => c.type === "select");
        const picked = selChanged ? nodes.filter((n) => n.selected).map((n) => n.id)
          : s.picked.filter((id) => !removed.has(id));
        return {
          nodes,
          edges: removed.size ? s.edges.filter((e) => !removed.has(e.source) && !removed.has(e.target)) : s.edges,
          groups: removed.size ? s.groups.map((g) => ({ ...g, members: g.members.filter((m) => !removed.has(m)) }))
            .filter((g) => g.members.length > 0) : s.groups,
          picked,
          selectedId: s.selectedId && removed.has(s.selectedId) ? null
            : (selChanged && picked.length === 1 ? picked[0] : s.selectedId),
          reportStale: s.reportStale || (structural && s.report !== null),
        };
      });
    },

    onEdgesChange: (changes) => {
      if (changes.some((c) => STRUCTURAL.has(c.type))) push();
      set((s) => ({
        edges: applyEdgeChanges(changes, s.edges),
        reportStale: s.reportStale || (changes.some((c) => STRUCTURAL.has(c.type)) && s.report !== null),
      }));
    },

    connect: (c) => {
      push();
      set((s) => ({
        edges: addEdge({ ...c, id: `${c.source}.${c.sourceHandle}->${c.target}.${c.targetHandle}` }, s.edges),
        reportStale: s.report !== null,
      }));
    },

    addNode: (kind, position) => {
      push();
      const id = newId(kind, new Set(get().nodes.map((n) => n.id)));
      const node: PgNode = { id, type: PG_NODE_TYPE, position, data: { kind, params: {} } };
      set((s) => ({ nodes: [...s.nodes, node], selectedId: id, picked: [id], reportStale: s.report !== null }));
      return id;
    },

    updateParams: (id, params) => {
      const now = Date.now();
      if (!(lastParamEdit && lastParamEdit.id === id && now - lastParamEdit.at < COALESCE_MS)) push();
      lastParamEdit = { id, at: now };
      set((s) => ({
        nodes: s.nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, params } } : n)),
        reportStale: s.report !== null,
      }));
    },

    removeNode: (id) => {
      push();
      set((s) => ({
        nodes: s.nodes.filter((n) => n.id !== id),
        edges: s.edges.filter((e) => e.source !== id && e.target !== id),
        groups: s.groups.map((g) => ({ ...g, members: g.members.filter((m) => m !== id) })).filter((g) => g.members.length),
        selectedId: s.selectedId === id ? null : s.selectedId,
        picked: s.picked.filter((p) => p !== id),
        reportStale: s.report !== null,
      }));
    },

    removePicked: () => {
      const ids = new Set(get().picked.length ? get().picked : get().selectedId ? [get().selectedId!] : []);
      if (!ids.size) return;
      push();
      set((s) => ({
        nodes: s.nodes.filter((n) => !ids.has(n.id)),
        edges: s.edges.filter((e) => !ids.has(e.source) && !ids.has(e.target)),
        groups: s.groups.map((g) => ({ ...g, members: g.members.filter((m) => !ids.has(m)) })).filter((g) => g.members.length),
        selectedId: s.selectedId && ids.has(s.selectedId) ? null : s.selectedId,
        picked: [],
        reportStale: s.report !== null,
      }));
    },

    duplicateNode: (id) => {
      const src = get().nodes.find((n) => n.id === id);
      if (!src) return null;
      push();
      const nid = newId(src.data.kind, new Set(get().nodes.map((n) => n.id)));
      const node: PgNode = {
        ...src, id: nid, selected: false, position: { x: src.position.x + 36, y: src.position.y + 150 },
        data: { ...src.data, params: structuredClone(src.data.params ?? {}) },
      };
      const incoming = get().edges.filter((e) => e.target === id).map((e) => ({
        ...e, id: `${e.source}.${e.sourceHandle}->${nid}.${e.targetHandle}`, target: nid, selected: false,
      }));
      set((s) => ({ nodes: [...s.nodes, node], edges: [...s.edges, ...incoming], selectedId: nid, picked: [nid],
                    reportStale: s.report !== null }));
      return nid;
    },

    loadDoc: (doc, problems = []) => {
      const cur = get();
      if (cur.nodes.length) push();
      const { nodes, edges } = fromDoc(doc, cur.catalog ?? []);
      const ids = new Set(nodes.map((n) => n.id));
      const groups = (doc.groups ?? []).map((g) => ({ ...g, members: g.members.filter((m) => ids.has(m)) }))
        .filter((g) => g.members.length);
      set({
        nodes, edges, groups, name: doc.meta?.name ?? "", loadProblems: problems,
        report: null, reportStale: false, validation: null, selectedId: null, picked: [], runError: null,
        pinned: [], cause: null, lanes: null, focusGroup: null, filters: [],
        branches: (doc.branches ?? []).filter((b) => b.root in b.map),
      });
    },

    setName: (name) => set({ name }),
    select: (selectedId) => set({ selectedId, picked: selectedId ? [selectedId] : [] }),
    setValidation: (validation) => set({ validation }),
    startRun: (ids = null) => set({ running: true, runError: null, runningIds: ids, preview: null, cause: null }),
    finishRun: (report, err = null) => set((s) => {
      if (!report) return { running: false, runningIds: null, runError: err };
      const partial = report.partial?.targets ?? null;
      let merged = report;
      if (partial && s.report) {
        // ★이번에 계산하지 않은 노드는 이전 결과를 "이전 계산" 으로 남긴다 — 지금 값처럼 보이지 않는다.
        const prev = Object.fromEntries(Object.entries(s.report.nodes)
          .filter(([id]) => !(id in report.nodes) && s.nodes.some((n) => n.id === id))
          .map(([id, r]) => [id, { ...r, previous: true }]));
        merged = { ...report, nodes: { ...prev, ...report.nodes } };
      }
      return {
        running: false, runningIds: null, runError: err,
        report: merged,
        reportStale: false,
        runs: [record(report, partial), ...s.runs].slice(0, RUNS),
      };
    }),
    setPreview: (preview) => set({ preview }),
    setStages: (stages) => set({ stages }),
    setFocusGroup: (focusGroup) => set((s) => ({
      focusGroup,
      groups: focusGroup ? s.groups.map((g) => (g.id === focusGroup ? { ...g, collapsed: false } : g)) : s.groups,
    })),
    toggleFilter: (k) => set((s) => ({ filters: s.filters.includes(k) ? s.filters.filter((x) => x !== k) : [...s.filters, k] })),
    clearLanes: () => set({ lanes: null }),
    setNote: (note) => set({ note }),
    makeBranch: (rootId) => {
      const s = get();
      const root = s.nodes.find((n) => n.id === rootId);
      if (!root) return "갈래를 만들 노드를 찾지 못했어요.";
      // 갈래의 갈래는 원본 뿌리에 붙인다 — 비교 표가 한 원본을 기준으로 선다.
      const parent = s.branches.find((b) => rootId in b.map);
      const ofRoot = parent ? parent.map[rootId] : rootId;
      if (parent && parent.root !== rootId) return "갈래는 뿌리 노드에서만 다시 만들 수 있어요 — 갈래 안의 뿌리(점선 틀의 맨 앞)를 골라 주세요.";
      const letter = nextBranchLetter(ofRoot, s.branches);
      if (!letter) return `한 노드에 갈래는 ${MAX_BRANCHES}개까지예요 — 여러 번 고를수록 우연히 좋아 보이는 쪽을 고를 위험이 커져요. 쓰지 않는 갈래를 지우고 만들어 주세요.`;
      const scope = branchScope(ofRoot, s.nodes, s.edges, s.groups, s.branches);
      push();
      const taken = new Set(s.nodes.map((n) => n.id));
      const idOf = new Map<string, string>();
      for (const id of scope) {
        let nid = `${id}__${letter.toLowerCase()}`;
        for (let k = 2; taken.has(nid); k++) nid = `${id}__${letter.toLowerCase()}${k}`;
        taken.add(nid);
        idOf.set(id, nid);
      }
      const src = parent ? parent : null;
      // 갈래의 갈래면 그 갈래의 설정을 이어받는다(바꾼 값 위에서 또 바꾼다).
      const from = (orig: string) => (src ? Object.entries(src.map).find(([, o]) => o === orig)?.[0] : undefined) ?? orig;
      const ys = scope.map((id) => s.nodes.find((n) => n.id === id)!.position.y);
      // 갈래마다 한 칸씩 아래로 — 칸 높이 = 복제 범위의 높이 + 틀 머리·여백(겹치지 않게).
      const band = Math.max(...ys) - Math.min(...ys) + 150 + 56 + 2 * 28 + 60;          // 카드 · 틀 머리 · 위아래 여백 · 틈
      const dy = band * (1 + s.branches.filter((b) => b.of_root === ofRoot).length);
      const copies: PgNode[] = scope.map((id) => {
        const base = s.nodes.find((n) => n.id === from(id)) ?? s.nodes.find((n) => n.id === id)!;
        const orig = s.nodes.find((n) => n.id === id)!;
        return { ...orig, id: idOf.get(id)!, selected: false, position: { x: orig.position.x, y: orig.position.y + dy },
                 data: { ...orig.data, params: structuredClone(base.data.params ?? {}) } };
      });
      const inScope = new Set(scope);
      // 안쪽 선은 복제끼리, 밖에서 들어오는 선은 원본과 같이. 밖으로 나가는 선은 잇지 않는다.
      const newEdges: Edge[] = s.edges.filter((e) => inScope.has(e.target)).map((e) => {
        const source = inScope.has(e.source) ? idOf.get(e.source)! : e.source;
        const target = idOf.get(e.target)!;
        return { ...e, id: `${source}.${e.sourceHandle}->${target}.${e.targetHandle}`, source, target, selected: false };
      });
      const branch: GraphBranch = { id: `br_${Date.now().toString(36)}${(++seq).toString(36)}`, label: `갈래 ${letter}`,
        root: idOf.get(ofRoot)!, of_root: ofRoot, map: Object.fromEntries(scope.map((id) => [idOf.get(id)!, id])) };
      set({ nodes: [...s.nodes, ...copies], edges: [...s.edges, ...newEdges], branches: [...s.branches, branch],
            selectedId: branch.root, picked: [branch.root], reportStale: s.report !== null, tab: "settings" });
      return `‘${branch.label}’를 만들었어요 — 노드 ${scope.length}개를 복제했어요. 설정을 바꾸고 계산하면 원본과 다른 값만 나란히 보여요.`;
    },
    removeBranch: (id) => {
      const s = get();
      const b = s.branches.find((x) => x.id === id);
      if (!b) return;
      push();
      const ids = new Set(Object.keys(b.map));
      set({ nodes: s.nodes.filter((n) => !ids.has(n.id)), edges: s.edges.filter((e) => !ids.has(e.source) && !ids.has(e.target)),
            branches: s.branches.filter((x) => x.id !== id), reportStale: s.report !== null,
            selectedId: s.selectedId && ids.has(s.selectedId) ? null : s.selectedId, picked: [] });
    },
    loadBlocks: () => { const r = readBlocks(); set({ blocks: r.blocks, blocksAvailable: r.available }); },
    saveBlock: (groupId) => {
      const s = get();
      const g = s.groups.find((x) => x.id === groupId);
      if (!g) return null;
      const block = blockFromGroup(g, toDoc(s.nodes, s.edges, undefined, s.groups));
      const cur = readBlocks();
      const ok = cur.available && writeBlocks([...cur.blocks.filter((b) => b.label !== block.label), block]);
      const r = readBlocks();
      set({ blocks: r.blocks, blocksAvailable: r.available && ok,
            note: ok ? `‘${g.label}’을 내 블록에 넣었어요 — 이 브라우저에만 있어요. 다른 곳에서 쓰려면 파일로 받아 두세요.`
                     : `이 브라우저에 블록을 저장할 수 없어요 — ‘${g.label}’은 파일로 받아 두세요.` });
      return block;
    },
    removeBlock: (i) => {
      const cur = readBlocks();
      const next = cur.blocks.filter((_, k) => k !== i);
      const ok = writeBlocks(next);
      set({ blocks: ok ? next : cur.blocks, blocksAvailable: ok });
    },
    togglePin: (id) => set((s) => ({ pinned: s.pinned.includes(id) ? s.pinned.filter((x) => x !== id) : [...s.pinned, id] })),
    showCause: (id) => set((s) => {
      if (!id || s.reportStale) return { cause: null };
      const { path, roots } = causePath(id, s.edges, s.report?.nodes);
      return { cause: path.length ? { from: id, path, roots } : null };
    }),

    undo: () => set((s) => {
      const prev = s.past[s.past.length - 1];
      if (!prev) return {};
      return {
        past: s.past.slice(0, -1),
        future: [{ nodes: clean(s.nodes), edges: s.edges, groups: s.groups, branches: s.branches }, ...s.future].slice(0, HISTORY),
        nodes: prev.nodes, edges: prev.edges, groups: prev.groups, branches: prev.branches ?? [], picked: [],
        selectedId: prev.nodes.some((n) => n.id === s.selectedId) ? s.selectedId : null,
        reportStale: s.report !== null,
      };
    }),

    redo: () => set((s) => {
      const next = s.future[0];
      if (!next) return {};
      return {
        future: s.future.slice(1),
        past: [...s.past, { nodes: clean(s.nodes), edges: s.edges, groups: s.groups, branches: s.branches }].slice(-HISTORY),
        nodes: next.nodes, edges: next.edges, groups: next.groups, branches: next.branches ?? [], picked: [],
        selectedId: next.nodes.some((n) => n.id === s.selectedId) ? s.selectedId : null,
        reportStale: s.report !== null,
      };
    }),

    copy: () => {
      const s = get();
      const ids = new Set(s.picked.length ? s.picked : s.selectedId ? [s.selectedId] : []);
      if (!ids.size) return 0;
      const nodes = s.nodes.filter((n) => ids.has(n.id));
      // ★링크는 고른 것끼리만★ — 고르지 않은 노드로 들어오던 링크를 따라 붙이면 붙인 자리에서 뜻이 바뀐다.
      const edges = s.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
      set({ clip: { nodes: structuredClone(clean(nodes)), edges: structuredClone(edges) } });
      return nodes.length;
    },

    paste: () => {
      const s = get();
      if (!s.clip?.nodes.length) return 0;
      push();
      const taken = new Set(s.nodes.map((n) => n.id));
      const remap = new Map<string, string>();
      const nodes = s.clip.nodes.map((n) => {
        const id = newId(n.data.kind, taken);
        taken.add(id);
        remap.set(n.id, id);
        return { ...n, id, selected: true, position: { x: n.position.x + 48, y: n.position.y + 48 },
                 data: { ...n.data, params: structuredClone(n.data.params ?? {}) } };
      });
      const edges = s.clip.edges.map((e) => {
        const source = remap.get(e.source)!;
        const target = remap.get(e.target)!;
        return { ...e, source, target, id: `${source}.${e.sourceHandle}->${target}.${e.targetHandle}`, selected: false };
      });
      set({
        nodes: [...s.nodes.map((n) => ({ ...n, selected: false })), ...nodes], edges: [...s.edges, ...edges],
        picked: nodes.map((n) => n.id), selectedId: nodes.length === 1 ? nodes[0].id : s.selectedId,
        reportStale: s.report !== null,
        // 다음 붙여넣기는 또 한 칸 비껴 놓는다.
        clip: { nodes: s.clip.nodes.map((n) => ({ ...n, position: { x: n.position.x + 48, y: n.position.y + 48 } })),
                edges: s.clip.edges },
      });
      return nodes.length;
    },

    autoLayout: () => {
      const s = get();
      if (!s.nodes.length) return;
      push();
      if (s.groups.some((g) => g.kind === "strategy") && s.stages.length) {
        // 전략이 있으면 전략 지도로 — (전략 띠 × 단계 열) 칸, 오른쪽 끝은 포트폴리오 레인.
        const stageOf = (kind: string) => s.catalog?.find((c) => c.type === kind)?.stage;
        const m = mapLayout(s.nodes, s.edges, s.groups, s.stages, stageOf);
        set({ nodes: s.nodes.map((n) => (m.positions.has(n.id) ? { ...n, position: m.positions.get(n.id)! } : n)),
              lanes: { lanes: m.lanes, height: m.height, portfolioX: m.portfolioX } });
        return;
      }
      const order = topoOrder(s.nodes.map((n) => n.id), s.edges);
      const depth = new Map<string, number>();
      for (const id of order) {
        const ins = s.edges.filter((e) => e.target === id).map((e) => (depth.get(e.source) ?? 0) + 1);
        depth.set(id, ins.length ? Math.max(...ins) : 0);
      }
      const cols = new Map<number, PgNode[]>();
      for (const n of s.nodes) cols.set(depth.get(n.id) ?? 0, [...(cols.get(depth.get(n.id) ?? 0) ?? []), n]);
      const pos = new Map<string, { x: number; y: number }>();
      for (const [d, col] of cols) {
        // 같은 깊이는 **지금의 세로 순서**를 지킨다 — 사람이 둔 위아래를 뒤섞지 않는다.
        col.sort((a, b) => a.position.y - b.position.y).forEach((n, i) => pos.set(n.id, { x: d * 230, y: i * 170 }));
      }
      set({ nodes: s.nodes.map((n) => ({ ...n, position: pos.get(n.id) ?? n.position })), lanes: null });
    },

    groupPicked: (label) => {
      const s = get();
      const ids = s.picked.filter((id) => s.nodes.some((n) => n.id === id));
      if (ids.length < 2) return null;
      push();
      const id = `grp_${Date.now().toString(36)}${(++seq).toString(36)}`;
      // 한 노드는 한 묶음에만 — 다른 묶음에 있던 노드는 옮겨 온다.
      const groups = s.groups.map((g) => ({ ...g, members: g.members.filter((m) => !ids.includes(m)) }))
        .filter((g) => g.members.length >= 1);
      set({ groups: [...groups, { id, label: label ?? `묶음 ${groups.length + 1}`, members: ids, collapsed: false }] });
      return id;
    },

    strategyPicked: () => {
      const s = get();
      const ids = s.picked.filter((id) => s.nodes.some((n) => n.id === id));
      if (!ids.length) return "전략으로 묶을 노드를 먼저 골라 주세요.";
      const output = strategyOutput(ids, s.nodes, s.edges, s.catalog ?? []);
      if (!output) return "고른 노드에 비중을 내는 노드가 없어요 — 전략은 비중을 내야 포트폴리오에 합칠 수 있어요. 그냥 묶으려면 Ctrl+G 를 써요.";
      push();
      const groups = s.groups.map((g) => ({ ...g, members: g.members.filter((m) => !ids.includes(m)) })).filter((g) => g.members.length);
      const used = new Set(groups.filter((g) => g.kind === "strategy").map((g) => g.color ?? 0));
      const color = [...Array(STRATEGY_COLORS).keys()].find((c) => !used.has(c)) ?? groups.length % STRATEGY_COLORS;
      const label = uniqueLabel(`전략 ${groups.filter((g) => g.kind === "strategy").length + 1}`, groups);
      set({ groups: [...groups, { id: `grp_${Date.now().toString(36)}${(++seq).toString(36)}`, label, members: ids,
                                  collapsed: false, kind: "strategy", color, output }] });
      return `고른 노드 ${ids.length}개를 ‘${label}’로 묶었어요. 포트폴리오에 합치려면 ‘전략 추가’로 전략을 하나 더 넣거나, 비중 출력을 ‘전략 합치기’ 노드에 이어요.`;
    },

    addStrategy: (src) => {
      const s = get();
      const catalog = s.catalog ?? [];
      push();
      let groups = [...s.groups];
      let nodes = [...s.nodes];
      let edges = [...s.edges];
      let wrapped = "";
      // ① 처음 전략이면 지금 흐름(어느 묶음에도, 포트폴리오 레인에도 없는 노드)을 ‘전략 1’로 묶는다.
      if (!groups.some((g) => g.kind === "strategy")) {
        const lane = portfolioLane(nodes, edges, groups);
        const free = nodes.filter((n) => !groups.some((g) => g.members.includes(n.id)) && !lane.has(n.id)).map((n) => n.id);
        const out = strategyOutput(free, nodes, edges, catalog);
        if (out) {
          const label = uniqueLabel(s.name.trim() || "전략 1", groups);
          groups.push({ id: `grp_${Date.now().toString(36)}${(++seq).toString(36)}`, label, members: free, collapsed: false,
                        kind: "strategy", color: 0, output: out });
          wrapped = `지금 흐름을 ‘${label}’로 묶고, `;
        }
      }
      // ② 새 전략을 가장 아래 노드 밑에 넣는다.
      const maxY = nodes.length ? Math.max(...nodes.map((n) => n.position.y)) : 0;
      const minX = nodes.length ? Math.min(...nodes.map((n) => n.position.x)) : 0;
      const k = groups.filter((g) => g.kind === "strategy").length + 1;
      const ins = insertDoc(src, new Set(nodes.map((n) => n.id)), `s${k}_`, { x: minX, y: nodes.length ? maxY + 300 : 0 });
      const added = fromDoc({ format: GRAPH_FORMAT, version: GRAPH_VERSION, nodes: ins.nodes, edges: ins.edges }, catalog);
      nodes = [...nodes, ...added.nodes];
      edges = [...edges, ...added.edges];
      const newIds = added.nodes.map((n) => n.id);
      const output = (src.output && ins.map.get(src.output)) || strategyOutput(newIds, nodes, edges, catalog);
      const used = new Set(groups.filter((g) => g.kind === "strategy").map((g) => g.color ?? 0));
      const color = [...Array(STRATEGY_COLORS).keys()].find((c) => !used.has(c)) ?? k % STRATEGY_COLORS;
      const label = uniqueLabel(src.label, groups);
      groups.push({ id: `grp_${Date.now().toString(36)}${(++seq).toString(36)}`, label, members: newIds, collapsed: false,
                    kind: "strategy", color, output });
      // ③ 포트폴리오 노드 — 없으면 오른쪽 끝에 만들고, 아직 잇지 않은 전략 출력을 빈 포트에 잇는다.
      let pf = nodes.find((n) => n.data.kind === PORTFOLIO_NODE && !groups.some((g) => g.members.includes(n.id)));
      if (!pf && catalog.some((c) => c.type === PORTFOLIO_NODE)) {
        const maxX = Math.max(...nodes.map((n) => n.position.x));
        const ys = nodes.map((n) => n.position.y);
        pf = { id: newId(PORTFOLIO_NODE, new Set(nodes.map((n) => n.id))), type: PG_NODE_TYPE,
               position: { x: maxX + 320, y: (Math.min(...ys) + Math.max(...ys)) / 2 }, data: { kind: PORTFOLIO_NODE, params: {} } };
        nodes.push(pf);
      }
      let unwired = 0;
      if (pf) {
        const labels = { ...((pf.data.params.labels as Record<string, string>) ?? {}) };
        for (const g of groups.filter((x) => x.kind === "strategy" && x.output)) {
          if (edges.some((e) => e.source === g.output && e.target === pf!.id)) continue;
          const port = PORTFOLIO_PORTS.find((p) => !edges.some((e) => e.target === pf!.id && e.targetHandle === p));
          const outPort = catalog.find((c) => c.type === nodes.find((n) => n.id === g.output)?.data.kind)?.outputs.find((o) => o.type === "Weights")?.name;
          if (!port || !outPort) { unwired += 1; continue; }
          edges.push({ id: `${g.output}.${outPort}->${pf.id}.${port}`, source: g.output!, sourceHandle: outPort, target: pf.id, targetHandle: port });
          labels[port] = g.label;
        }
        const pid = pf.id;
        nodes = nodes.map((n) => (n.id === pid ? { ...n, data: { ...n.data, params: { ...n.data.params, labels } } } : n));
      }
      set({ nodes, edges, groups, reportStale: s.report !== null, selectedId: null, picked: [] });
      if (!output) return `‘${label}’을 넣었어요. 이 전략에는 비중을 내는 노드가 없어 포트폴리오에 잇지 않았어요.`;
      if (unwired) return `${wrapped}‘${label}’을 넣었어요. 포트폴리오 노드의 빈 자리(최대 ${PORTFOLIO_PORTS.length}개)가 없어 ${unwired}개는 잇지 못했어요.`;
      return `${wrapped}‘${label}’을 넣어 ‘전략 합치기’에 이었어요. 계산하면 전략별 몫이 보여요.`;
    },

    insertBlock: (b) => {
      if (b.kind === "strategy") return get().addStrategy({ label: b.label, nodes: b.nodes, edges: b.edges, output: b.output });
      const s = get();
      push();
      const maxY = s.nodes.length ? Math.max(...s.nodes.map((n) => n.position.y)) : 0;
      const minX = s.nodes.length ? Math.min(...s.nodes.map((n) => n.position.x)) : 0;
      const ins = insertDoc(b, new Set(s.nodes.map((n) => n.id)), "b_", { x: minX, y: s.nodes.length ? maxY + 300 : 0 });
      const added = fromDoc({ format: GRAPH_FORMAT, version: GRAPH_VERSION, nodes: ins.nodes, edges: ins.edges }, s.catalog ?? []);
      const label = uniqueLabel(b.label, s.groups);
      set({ nodes: [...s.nodes, ...added.nodes], edges: [...s.edges, ...added.edges], reportStale: s.report !== null,
            groups: [...s.groups, { id: `grp_${Date.now().toString(36)}${(++seq).toString(36)}`, label,
                                    members: added.nodes.map((n) => n.id), collapsed: false }] });
      return `‘${label}’ 블록을 넣었어요 — 노드 ${added.nodes.length}개. 필요한 입력을 이어 주세요.`;
    },

    ungroup: (id) => { push(); set((s) => ({ groups: s.groups.filter((g) => g.id !== id) })); },
    toggleGroup: (id) => set((s) => ({ groups: s.groups.map((g) => (g.id === id ? { ...g, collapsed: !g.collapsed } : g)) })),
    renameGroup: (id, label) => set((s) => {
      const groups = s.groups.map((g) => (g.id === id ? { ...g, label } : g));
      const g = groups.find((x) => x.id === id);
      // 전략 이름은 포트폴리오 노드의 전략 이름(파라미터)과 같아야 한다 — 이은 포트의 이름을 함께 바꾼다.
      const e = g?.kind === "strategy" && g.output
        ? s.edges.find((x) => x.source === g.output && s.nodes.find((n) => n.id === x.target)?.data.kind === PORTFOLIO_NODE) : undefined;
      if (!e || !e.targetHandle || !label.trim()) return { groups };
      return {
        groups, reportStale: s.report !== null,
        nodes: s.nodes.map((n) => (n.id === e.target
          ? { ...n, data: { ...n.data, params: { ...n.data.params,
              labels: { ...((n.data.params.labels as Record<string, string>) ?? {}), [e.targetHandle!]: label.trim().slice(0, 40) } } } }
          : n)),
      };
    }),
    moveGroup: (id, dx, dy) => set((s) => {
      const g = s.groups.find((x) => x.id === id);
      if (!g || (!dx && !dy)) return {};
      const m = new Set(g.members);
      return { nodes: s.nodes.map((n) => (m.has(n.id) ? { ...n, position: { x: n.position.x + dx, y: n.position.y + dy } } : n)) };
    }),

    setMinimap: (showMinimap) => set({ showMinimap }),
    setTab: (tab) => set({ tab }),
    setExpert: (expert) => set({ expert }),
    setOpenGate: (openGate) => set({ openGate }),
  };
});
