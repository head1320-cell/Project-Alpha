"use client";
/**
 * 포트폴리오 캔버스 상태 (BI3 → BL1) — React Flow 노드·엣지 + 카탈로그 + 검증·실행 보고.
 * ==========================================================================
 * ★낡은 결과를 새 그래프의 결과처럼 보이지 않는다★ — 노드·링크·파라미터가 바뀌면 **바뀐 노드와 그 하류만**
 * `staleIds` 에 들고, 화면은 그 노드에서만 "지금 그래프의 결과가 아니에요" 라고 말한다(BT5 — 예전엔 전역 불리언 하나라
 * 설정 하나만 바꿔도 모든 카드가 낡았다). 판정은 계산 때 남긴 깊은 서명과 지금 서명의 비교다(`staleness.ts`) — 모든 동작
 * (설정·선·지우기·붙여넣기·갈래·되돌리기)이 같은 규칙을 탄다. 위치 이동은 계산에 영향이 없으므로 결과를 낡게 만들지 않는다.
 * `reportStale` 은 호환용 파생값이다: 결과가 있는 노드 중 하나라도 낡았는가.
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
import type { Connection, Edge, EdgeChange, NodeChange } from "@xyflow/react";
import type { ProcedureSuggestion, DraftBody, GraphBlock, GraphBranch, WorkflowStage, GraphDoc, GraphDocEdge, GraphDocNode, GraphGroup, NodeCatalogEntry, NodeStatus, PgNode, RunEvent, RunReport, ValidateReport } from "@/entities/portfolio-graph";
import { staleNodes } from "@/entities/portfolio-graph/staleness";
import type { GoalKey } from "@/entities/portfolio-graph/goals";
import type { WireShape } from "./wirePath";
import type { AlignKind } from "./guides";
import { clean, HISTORY } from "./storeShared";
import { graphSlice } from "./storeGraph";
import { historySlice } from "./storeHistory";
import { layoutSlice } from "./storeLayout";
import { runSlice } from "./storeRun";
import { viewSlice } from "./storeView";

/** 계산 기록 한 줄 — 노드마다 상태와 헤드라인만(원 결과는 두지 않는다: 가볍게, 비교에 필요한 만큼). */
export interface RunRecord {
  at: number;
  partial: string[] | null;
  counts: { ok: number; blocked: number; failed: number };
  nodes: Record<string, { status: NodeStatus; headline: string | null; value: number | null }>;
}

export interface Snapshot { nodes: PgNode[]; edges: Edge[]; groups: GraphGroup[]; branches?: GraphBranch[] }
/** 지운 것(R2) — 노드·선 수 · 그중 결과가 최신이던 노드 · 지워서 새로 예전 결과가 된 하류 노드. 토스트(`deleteNote`)가 이것만 말한다. */
export interface DeleteResult { nodes: number; edges: number; results: number; downstream: number }

/** 실행 줄(CF5a) — 이번 계산의 노드별 진행. 곁줄 이벤트로 바뀌고, 끝나면 ★보고서로 확정★한다(`final`). `lost` = 곁줄이 끊겼다. */
export type RunPhase = "waiting" | "running" | "done";
export interface RunCell { phase: RunPhase; status?: NodeStatus; elapsed_ms?: number | null }
export interface RunProgress { order: string[]; cells: Record<string, RunCell>; lost: boolean; final: boolean }

export interface PgState {
  catalog: NodeCatalogEntry[] | null;
  catalogError: string | null;
  nodes: PgNode[];
  edges: Edge[];
  groups: GraphGroup[];
  name: string;
  /** '목표로 시작'에서 고른 목표(AI1) — 문서 `meta.goal`. 없으면 null. */
  goal: GoalKey | null;
  report: RunReport | null;
  /** 호환용 파생값(BT5) — `staleIds` 가 하나라도 있는가. 직접 쓰지 않는다(매 변경마다 다시 센다). */
  reportStale: boolean;
  /** 결과가 지금 그래프의 것이 아닌 노드(BT5) — 바뀐 노드와 그 하류. 파생값이다. */
  staleIds: string[];
  /** 노드마다 그 결과를 계산할 때의 깊은 서명(BT5). 결과가 없으면 null. */
  snap: Record<string, string> | null;
  /** 지금 진행 중인 계산을 시작할 때의 서명 — 계산 중에 편집해도 계산한 그래프를 기준으로 남긴다. */
  runSigs: Record<string, string> | null;
  validation: ValidateReport | null;
  /** 검증 요청이 서버에 닿지 못했다(BT2) — 절차 칸이 "불러오지 못했어요"를 말한다. */
  validationError: boolean;
  /** 사람이 직접 고른 노드인가(BT3) — 추가하면 자동으로 골라지므로 그것과 가른다(연속 추가가 사슬로 이어지지 않게). */
  pickedByUser: boolean;
  /** 절차 줄에 올린 동안 또렷하게 둘 노드(BT2). */
  procHover: string[] | null;
  /** 카탈로그가 함께 준 이름표(BT1) — 관문 이름 · 포트 쉬운 이름. */
  catalogMeta: { gates: { key: string; label: string }[]; portPlain: Record<string, string> } | null;
  /** 마지막 불러오기에서 건너뛴 것(깨진 링크 등) — 조용히 버리지 않고 말한다. */
  loadProblems: string[];
  /** 문서를 통째로 불러온 횟수(PB3) — 고객 칩이 '이 문서를 연 순간' 을 알아 저장 기준을 잡는다. */
  loadSeq: number;
  selectedId: string | null;
  /** 함께 고른 노드들(상자 끌기·Shift) — 복사·묶기·삭제의 대상. `selectedId` 는 그중 패널에 보이는 하나. */
  picked: string[];
  running: boolean;
  /** 지금 계산 중인 노드들(부분 계산이면 대상의 조상) — 경로를 밝힌다. */
  runningIds: string[] | null;
  progress: RunProgress | null;
  /** "여기까지 계산" 에 마우스를 올렸을 때 계산될 노드 — 누르기 전에 무엇이 돌지 보인다. */
  preview: string[] | null;
  runError: string | null;
  runs: RunRecord[];
  past: Snapshot[];
  /** 되돌리기 칸에 넣은 횟수(R1) — 칸은 50개에서 잘리므로 길이가 아니라 이 수로 '이번 동작이 기록을 남겼나' 를 본다. */
  undoSeq: number;
  future: Snapshot[];
  clip: { nodes: PgNode[]; edges: Edge[] } | null;
  showMinimap: boolean;
  /** 단계 레인(CF4b) — 보기만 바꾼다(문서·계산과 무관). 켬/끔은 `view.ts` 가 이 브라우저에 남긴다. */
  showLanes: boolean;
  /** 선 모양(CF4c) — 곡선·직각·직선. 보기만 바꾼다. */
  wireShape: WireShape;
  /** 추천 유령(CF6) 켬/끔 — 보기 설정. */
  showGhosts: boolean;
  /** 오른쪽 패널 탭 · 전문가 설정 · 펼친 관문 (BJ3). */
  tab: "story" | "settings" | "detail" | "branches" | "wire";
  /** 오른쪽 판 "선" 탭이 보이는 선(BT4). */
  selectedEdge: string | null;
  expert: boolean;
  openGate: string | null;
  /** 미리보기 고정(BM C1 · TouchDesigner 뷰어 플래그) — 어떤 확대에서도 작은 그림을 보인다. 화면 정보(파일에 없다). */
  pinned: string[];
  /** 접은 노드(CF1) — 머리 줄만. 화면 정보라 되돌리기에 넣지 않는다(그림 고정과 같다). */
  folded: string[];
  toggleFold: (id: string) => void;
  /** 끝을 옮겨 다시 꽂는 중인 선(CF2) — 연결 검사에서 이 선 자신은 빼고 본다. */
  reconnecting: string | null;
  setReconnecting: (id: string | null) => void;
  /** 선 끝 다시 꽂기(CF2) — 옛 선을 새 연결로 바꾼다(되돌리기 한 번). 같은 자리면 아무것도 하지 않는다. */
  reconnect: (oldId: string, c: Connection) => boolean;
  /** 원인 경로(BM C1) — 막힘·실패 노드에서 계산 못 한 상류를 따라 첫 원인까지. 켜지면 나머지는 흐려진다. */
  cause: { from: string; path: string[]; roots: string[] } | null;
  /** 단계 순서(서버 카탈로그). */
  stages: WorkflowStage[];
  /** 들어간 전략 상자(ComfyUI 서브그래프 들어가기) — 나머지는 흐리게, 상단에 빵부스러기. */
  focusGroup: string | null;
  /** 캔버스 필터(Dataiku) — 맞지 않는 노드·선을 흐린다. 여러 개면 하나라도 맞으면 남긴다. */
  filters: FilterKey[];
  /** 내 블록(이 브라우저) — 저장소를 못 쓰면 `blocksAvailable: false`(없음과 다르다). 신뢰 저장은 파일. */
  blocks: GraphBlock[];
  blocksAvailable: boolean;
  /** 갈래(BM C3) — 화면 정보. 복제 노드 자체는 보통 노드다. */
  branches: GraphBranch[];
  /** 간단히 보기(BM C4) — 노드 없이 정할 것 → 결과. 같은 스토어라 바꾼 값은 노드 설정이다. */
  simple: boolean;
  /** 목표로 시작한 직후 한 번 — 노드가 흐름 순서대로 자라난다(감속 모션이면 없음). */
  growing: boolean;
  /** 캔버스 한 줄 안내(전략 추가·블록 저장 결과). */
  note: string | null;
  /** 안내가 되돌릴 수 있는 동작 뒤에 떴나(BN N3) — 그러면 안내 줄에 [되돌리기] 가 붙고 잠시 뒤 스스로 닫힌다. */
  noteUndo: boolean;
  /** 스스로 닫히는 안내(AI5 길잡이의 '다음엔 어디서') — 되돌리기는 없지만 8초 뒤 닫힌다(바를 가리지 않게). */
  noteTransient: boolean;

  setCatalog: (c: NodeCatalogEntry[] | null, err?: string | null) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  connect: (c: Connection) => void;
  /** 이 입력을 받는 곳을 바꾼다(BT4 끌지 않고 잇기) — 있던 선을 떼고 새 선을 잇는다. `source` 가 null 이면 떼기만. 되돌리기 한 번. */
  rewire: (target: string, port: string, source: string | null, sourceHandle: string | null) => void;
  /** 같은 단계의 다른 종류로 바꿔 끼운다(BT6) — 자리·선은 그대로(포트는 타입으로 다시 맞춤), 설정은 새 종류 기본값. 맞출 수 없으면 null. */
  swapNode: (id: string, kind: string) => string | null;
  addNode: (kind: string, position: { x: number; y: number }) => string;
  updateParams: (id: string, params: Record<string, unknown>) => void;
  /** 노드·선을 함께 지운다(R1) — ★되돌리기 한 번★. 지운 것이 없으면 null. Delete 키·메뉴·명령이 모두 이 길이다. */
  deleteElements: (nodeIds: string[], edgeIds: string[]) => DeleteResult | null;
  /** 같은 입력(들어오는 링크)·같은 설정으로 옆에 하나 더 — 설정만 바꿔 나란히 비교할 때. 나가는 링크는 잇지 않는다. */
  duplicateNode: (id: string) => string | null;
  loadDoc: (doc: GraphDoc, problems?: string[]) => void;
  setName: (n: string) => void;
  setGoal: (g: GoalKey | null) => void;
  select: (id: string | null) => void;
  /** 여럿을 한 번에 고른다(R2 Ctrl+A) — 고른 선은 푼다. 하나만이면 그 노드를 고른 것과 같다. */
  pickIds: (ids: string[]) => void;
  setValidation: (v: ValidateReport | null) => void;
  setValidationError: (v: boolean) => void;
  setProcHover: (ids: string[] | null) => void;
  setCatalogMeta: (m: PgState["catalogMeta"]) => void;
  startRun: (ids?: string[] | null) => void;
  finishRun: (r: RunReport | null, err?: string | null) => void;
  /** 곁줄 이벤트(CF5a) — 확정된 뒤(늦게 온 이벤트)는 무시한다. */
  applyRunEvent: (ev: RunEvent) => void;
  progressLost: () => void;
  setPreview: (ids: string[] | null) => void;
  undo: () => void;
  redo: () => void;
  copy: () => number;
  paste: () => number;
  autoLayout: () => void;
  groupPicked: (label?: string) => string | null;
  /** 고른 카드 정렬·간격 맞추기(CF4a) — 되돌리기 한 번. 간격은 셋 이상일 때만. */
  alignPicked: (kind: AlignKind) => void;
  /** 레인에 맞추기(CF4b) — 노드마다 자기 단계 띠의 하위 열로, 열 안은 지금 순서대로 실제 높이로 쌓는다. 되돌리기 한 번. */
  fitToLanes: () => void;
  /** 경유점(CF4c) — 끼우기·옮기기·지우기. 끼우기·지우기는 되돌리기 한 번, 옮기기는 `record` 일 때(끌기 시작)만 기록한다. */
  addWaypoint: (edgeId: string, index: number, p: { x: number; y: number }) => void;
  moveWaypoint: (edgeId: string, index: number, p: { x: number; y: number }, record: boolean) => void;
  removeWaypoint: (edgeId: string, index: number) => void;
  ungroup: (id: string) => void;
  toggleGroup: (id: string) => void;
  renameGroup: (id: string, label: string) => void;
  /** 상자째 옮기기 — `record` 면 이번에 되돌리기 칸에 넣는다(끌기 시작 · R1). 움직였으면 true. */
  moveGroup: (id: string, dx: number, dy: number, record?: boolean) => boolean;
  setMinimap: (v: boolean) => void;
  setLanes: (v: boolean) => void;
  setWireShape: (v: WireShape) => void;
  setShowGhosts: (v: boolean) => void;
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
  /** 고른 노드 견고성 비교(BR R1b) — 비중을 내는 노드 2~4개를 새 '견고성 비교' 노드에 잇는다(되돌리기 한 번). 돌려주는 값은 한 줄 안내. */
  comparePicked: () => string;
  insertBlock: (b: GraphBlock) => string;
  setFocusGroup: (id: string | null) => void;
  toggleFilter: (k: FilterKey) => void;
  loadBlocks: () => void;
  /** 상자를 내 블록으로 — 이 브라우저에 넣고, 파일로 받을 수 있게 블록을 돌려준다(저장소가 막혀도 파일은 된다). */
  saveBlock: (groupId: string) => GraphBlock | null;
  removeBlock: (index: number) => void;
  setNote: (n: string | null, undoable?: boolean, transient?: boolean) => void;
  /** 동작을 하고 그 안내를 띄운다 — 동작이 되돌리기 기록을 남겼으면 안내 줄에 [되돌리기] 가 붙는다(BN N3). */
  act: (fn: () => string | null) => void;
  /** 노드를 놓고 곧바로 잇는다(BN N3 선 끌어 놓기) — 되돌리기 한 번에 둘 다. */
  addLinked: (kind: string, position: { x: number; y: number },
              link: { node: string; handle: string; side: "source" | "target"; port: string }) => string;
  /**
   * 서버 절차의 한 걸음을 그대로 한다(BT2) — `add` 는 노드를 놓고 `attach` 의 선을 모두 잇는다(`@new` = 새 노드),
   * `connect` 는 선만 잇는다. 되돌리기 한 번. 새 노드는 보내는 쪽 오른쪽 열(없으면 받는 쪽 왼쪽 열)에 놓는다.
   * 돌려주는 값은 새 노드 id(없으면 null).
   */
  applySuggestion: (sug: ProcedureSuggestion, at?: { x: number; y: number }) => string | null;
  /**
   * 말로 설계(AI4)의 [받아들이기] — 노드 더하기 · 선 잇기 · 값 넣기(+ 출처 `said`)를 ★`push()` 한 번★에(되돌리기 한 번 = 전부 원래대로).
   * 이름·목표는 건드리지 않는다. 초안이 기댄 문서와 달라졌으면(더할 id 가 이미 있음 · 값 넣을 노드가 없음) 하지 않고 null.
   */
  applyDraft: (d: DraftBody, at: Record<string, { x: number; y: number }>) => { added: number; connected: number; set: number } | null;
  /** 선을 골라 "선" 탭을 연다(BT4). null 이면 닫는다. */
  selectEdge: (id: string | null) => void;
  /** 선을 끊는다(BT4) — 되돌리기 한 번. */
  cutEdge: (id: string) => void;
  /** 선 사이에 노드를 끼운다(BT4) — 원래 선을 지우고 보내는 쪽 → 새 노드 → 받는 쪽으로 잇는다. 되돌리기 한 번. */
  insertOnEdge: (edgeId: string, kind: string, inPort: string, outPort: string, at?: { x: number; y: number }) => string | null;
  /** 이 노드와 같은 전략 안의 하류를 복제해 갈래를 만든다 — 한 뿌리에 최대 4개. 돌려주는 값은 한 줄 안내.
   *  `members` 를 주면 그 노드만(뿌리 = 그중 흐름 맨 앞) — 전략째 갈래와 같은 규칙(CF5c). */
  makeBranch: (rootId: string, strategyId?: string, members?: string[]) => string;
  /** 고른 노드째 갈래(CF5c) — 고른 노드만 복제한다. 포트폴리오 노드는 넣지 않고 그렇다고 말한다. */
  branchPicked: () => string;
  /** 갈래를 지운다 — 복제 노드도 함께. */
  removeBranch: (id: string) => void;
  /** 갈래 승격(BN N2) — 복제의 설정을 원본으로 옮기고 갈래·복제를 지운다(되돌리기 한 번). 돌려주는 값은 한 줄 안내. */
  promoteBranch: (id: string) => string;
  setSimple: (v: boolean) => void;
  setGrowing: (v: boolean) => void;
}

export type FilterKey = "failed" | "blocked" | "practice" | "forward" | "assumed";

export { ancestorsOf, causePath, descendantsOf } from "./storeShared";

export const usePortfolioGraph = create<PgState>((rawSet, get) => {
  /**
   * 모든 변경 뒤에 낡음을 다시 센다(BT5) — 그래프·결과·서명이 바뀐 때만. 동작마다 손으로 표시하던 방식은 갈래·붙여넣기·되돌리기
   * 같은 경로에서 빠뜨리기 쉬웠다.
   */
  let seen: [unknown, unknown, unknown, unknown] = [null, null, null, null];
  const derive = () => {
    const s = get();
    if (seen[0] === s.nodes && seen[1] === s.edges && seen[2] === s.report && seen[3] === s.snap) return;
    seen = [s.nodes, s.edges, s.report, s.snap];
    const staleIds = staleNodes(s.nodes, s.edges, s.report?.nodes, s.snap);
    const same = staleIds.length === s.staleIds.length && staleIds.every((x, i) => x === s.staleIds[i]);
    if (!same || s.reportStale !== staleIds.length > 0) rawSet({ staleIds: same ? s.staleIds : staleIds, reportStale: staleIds.length > 0 });
  };
  const set: typeof rawSet = (...a: Parameters<typeof rawSet>) => { rawSet(...a); derive(); };
  /** 지금 상태를 되돌리기 칸에 넣는다 — 바꾸기 **직전**에 부른다. */
  const push = () => set((s) => ({
    past: [...s.past, { nodes: clean(s.nodes), edges: s.edges, groups: s.groups, branches: s.branches }].slice(-HISTORY),
    future: [],
    undoSeq: s.undoSeq + 1,
  }));

  const ctx = { set, get, push };
  return {
    catalog: null,
    catalogError: null,
    nodes: [],
    edges: [],
    groups: [],
    name: "",
    goal: null,
    report: null,
    reportStale: false,
    staleIds: [],
    snap: null,
    runSigs: null,
    validation: null,
    validationError: false,
    procHover: null,
    pickedByUser: false,
    catalogMeta: null,
    loadProblems: [],
    loadSeq: 0,
    selectedId: null,
    picked: [],
    running: false,
    runningIds: null,
    progress: null,
    preview: null,
    runError: null,
    runs: [],
    past: [],
    future: [],
    undoSeq: 0,
    clip: null,
    showMinimap: false,
    showLanes: false,
    wireShape: "curve",
    showGhosts: true,
    tab: "story",
    selectedEdge: null,
    expert: false,
    openGate: null,
    pinned: [],
    folded: [],
    reconnecting: null,
    cause: null,
    stages: [],
    focusGroup: null,
    filters: [],
    blocks: [],
    blocksAvailable: true,
    note: null,
    noteUndo: false,
    noteTransient: false,
    branches: [],
    simple: false,
    growing: false,

    ...graphSlice(ctx),
    ...runSlice(ctx),
    ...historySlice(ctx),
    ...layoutSlice(ctx),
    ...viewSlice(ctx),
  };
});
