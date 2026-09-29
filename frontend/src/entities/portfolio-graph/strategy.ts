/**
 * 전략 지도 (BM C2) — 순수 함수. 여러 전략(상자)이 한 포트폴리오로 모이는 캔버스의 배치·삽입·블록 파일.
 * ==========================================================================
 * ★화면 정보만 다룬다★ — 전략 상자(`groups[].kind === "strategy"`)는 계산에 끼지 않는다. 계산은 `portfolio_combine` 노드가 한다.
 * - `mapLayout`: ★그냥 노드와 선이다★(BN N1 — 레인·배경 칸을 그리지 않는다). 전략마다 한 줄, 줄 안은 흐름 깊이 순서로 왼쪽 → 오른쪽.
 *   전략에 속하지 않은 노드 중 `portfolio_combine` 과 그 하류는 모든 줄의 오른쪽에 세로로 쌓고, 나머지는 맨 아래 "공용" 줄로.
 * - `insertDoc`: 문서(템플릿·블록)를 id 를 새로 받아 끼워 넣는다 — 링크는 문서 안의 것만 따라온다.
 * - 블록 파일 `project-alpha.pgblock` v1 — 그래프 파일과 같은 규칙(다른 포맷은 거부, 모르는 노드는 버리지 않음).
 */
import type { GraphDoc, GraphDocEdge, GraphDocNode, GraphGroup, NodeCatalogEntry } from "./types";
import { topoOrder } from "./order";
import { CARD_BODY_H, COL, COMBINE_W, NODE_W, ROW_GAP, cardHeight } from "./size";

export const STRATEGY_COLORS = 6;
export const PORTFOLIO_NODE = "portfolio_combine";
export const PORTFOLIO_PORTS = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"] as const;

/** 지도 치수 — 열은 카드 폭 + 라벨 틈(`size.ts`), 줄은 ★카드 높이 + 틈으로 쌓는다★(BS2 — 예전 고정 170).
 *  `row` 는 카드 하나짜리 줄의 높이(빈 지도·최소 높이)다. 전략 사이·포트폴리오 앞은 상자 머리가 들어갈 만큼 띄운다. */
export const MAP = { col: COL, row: CARD_BODY_H + ROW_GAP, bandGap: 120, portfolioGap: 90 } as const;

type Pos = { x: number; y: number };
type N = { id: string; position: Pos; data: { kind: string } };
type E = { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null };

/** 전략의 출력 — 구성원 중 Weights 를 내는 마지막 노드(흐름 순서). 없으면 null. */
export function strategyOutput(members: string[], nodes: N[], edges: E[], catalog: NodeCatalogEntry[]): string | null {
  const inside = new Set(members);
  const order = topoOrder(nodes.map((n) => n.id), edges).filter((id) => inside.has(id));
  const weightsOut = (id: string) => {
    const kind = nodes.find((n) => n.id === id)?.data.kind;
    return !!catalog.find((c) => c.type === kind)?.outputs.some((o) => o.type === "Weights");
  };
  return [...order].reverse().find(weightsOut) ?? null;
}

/** 포트폴리오 레인 — 전략 밖의 `portfolio_combine` 노드와 그 하류. */
export function portfolioLane(nodes: N[], edges: E[], groups: GraphGroup[]): Set<string> {
  const inGroup = new Set(groups.filter((g) => g.kind === "strategy").flatMap((g) => g.members));
  const out = new Set<string>();
  const stack = nodes.filter((n) => n.data.kind === PORTFOLIO_NODE && !inGroup.has(n.id)).map((n) => n.id);
  while (stack.length) {
    const id = stack.pop()!;
    if (out.has(id) || inGroup.has(id)) continue;
    out.add(id);
    edges.filter((e) => e.source === id).forEach((e) => stack.push(e.target));
  }
  return out;
}

export function mapLayout(nodes: N[], edges: E[], groups: GraphGroup[], catalog?: NodeCatalogEntry[] | null): Map<string, Pos> {
  const kindOf = new Map(nodes.map((n) => [n.id, n.data.kind] as const));
  const hOf = (id: string) => cardHeight(kindOf.get(id) ?? "", catalog) + ROW_GAP;
  const order = topoOrder(nodes.map((n) => n.id), edges);
  const depth = new Map<string, number>();
  for (const id of order) {
    const ins = edges.filter((e) => e.target === id).map((e) => (depth.get(e.source) ?? 0) + 1);
    depth.set(id, ins.length ? Math.max(...ins) : 0);
  }
  const lane = portfolioLane(nodes, edges, groups);
  const strategies = groups.filter((g) => g.kind === "strategy");
  const owner = new Map<string, string>();
  for (const g of strategies) for (const m of g.members) owner.set(m, g.id);
  const bandKeys: (string | null)[] = strategies.map((g) => g.id);
  if (nodes.some((n) => !owner.has(n.id) && !lane.has(n.id))) bandKeys.push(null);

  const positions = new Map<string, Pos>();
  let y = 0;
  let maxDepth = 0;
  for (const b of bandKeys) {
    // 줄 안: 같은 깊이는 흐름 순서대로 아래로 — 사슬 하나면 한 줄로 곧게 선다. 아래 카드는 위 카드 높이 + 틈만큼.
    const cursor = new Map<number, number>();
    let bandH = MAP.row;
    for (const id of order.filter((x) => !lane.has(x) && (owner.get(x) ?? null) === b)) {
      const d = depth.get(id) ?? 0;
      const top = cursor.get(d) ?? 0;
      cursor.set(d, top + hOf(id));
      bandH = Math.max(bandH, top + hOf(id));
      maxDepth = Math.max(maxDepth, d);
      positions.set(id, { x: d * MAP.col, y: y + top });
    }
    y += bandH + MAP.bandGap;
  }
  const height = Math.max(MAP.row, y - MAP.bandGap);
  // 포트폴리오 노드(와 그 하류) — 모든 줄의 오른쪽. 첫 열은 줄 전체의 가운데에 세로로 쌓는다(여러 개면 겹치지 않게).
  const laneIds = order.filter((id) => lane.has(id));
  const laneDepth = new Map<string, number>();
  for (const id of laneIds) {
    const ins = edges.filter((e) => e.target === id && lane.has(e.source)).map((e) => (laneDepth.get(e.source) ?? 0) + 1);
    laneDepth.set(id, ins.length ? Math.max(...ins) : 0);
  }
  // 전략 상자의 최소 폭(머리 줄이 들어갈 만큼)을 넘도록 적어도 세 칸 오른쪽.
  const x0 = (bandKeys.length ? Math.max(maxDepth + 1, 3) : 0) * MAP.col + MAP.portfolioGap;
  const total = new Map<number, number>();
  for (const id of laneIds) total.set(laneDepth.get(id)!, (total.get(laneDepth.get(id)!) ?? 0) + hOf(id));
  // 첫 열(합치기 카드)이 보통 카드보다 넓다 — 그 뒤 열은 넓은 만큼 오른쪽으로(카드가 다음 열을 덮지 않게).
  const wide = laneIds.some((id) => laneDepth.get(id) === 0 && kindOf.get(id) === PORTFOLIO_NODE) ? COMBINE_W - NODE_W : 0;
  const seen = new Map<number, number>();
  for (const id of laneIds) {
    const d = laneDepth.get(id)!;
    const at = seen.get(d) ?? 0;
    seen.set(d, at + hOf(id));
    const top = Math.max(0, height / 2 - (total.get(d)! - ROW_GAP) / 2);
    positions.set(id, { x: x0 + d * MAP.col + (d > 0 ? wide : 0), y: Math.round(top + at) });
  }
  return positions;
}

/** 문서를 끼워 넣을 때의 새 id — `${prefix}${원래 id}`, 겹치면 숫자를 붙인다. */
export function insertDoc(doc: { nodes: GraphDocNode[]; edges: GraphDocEdge[] }, taken: Set<string>, prefix: string, offset: Pos) {
  const map = new Map<string, string>();
  for (const n of doc.nodes) {
    let id = `${prefix}${n.id}`;
    for (let k = 2; taken.has(id) || [...map.values()].includes(id); k++) id = `${prefix}${n.id}_${k}`;
    map.set(n.id, id);
  }
  const x0 = Math.min(...doc.nodes.map((n) => n.position.x));
  const y0 = Math.min(...doc.nodes.map((n) => n.position.y));
  const nodes = doc.nodes.map((n) => ({ ...n, id: map.get(n.id)!, params: structuredClone(n.params ?? {}),
    position: { x: n.position.x - x0 + offset.x, y: n.position.y - y0 + offset.y } }));
  const edges = doc.edges.filter((e) => map.has(e.source) && map.has(e.target)).map((e) => ({
    ...e, source: map.get(e.source)!, target: map.get(e.target)!,
    id: `${map.get(e.source)}.${e.source_port}->${map.get(e.target)}.${e.target_port}` }));
  return { nodes, edges, map };
}

// ── 내 블록 파일 ──────────────────────────────────────────────────────────────

export const BLOCK_FORMAT = "project-alpha.pgblock";
export const BLOCK_VERSION = 1;

export interface GraphBlock {
  format: typeof BLOCK_FORMAT;
  version: typeof BLOCK_VERSION;
  label: string;
  kind: "group" | "strategy";
  nodes: GraphDocNode[];
  edges: GraphDocEdge[];
  /** 전략이면 비중을 내는 노드(블록 안 id). */
  output?: string | null;
  saved_at?: string;
}

export function blockFromGroup(g: GraphGroup, doc: GraphDoc): GraphBlock {
  const m = new Set(g.members);
  return {
    format: BLOCK_FORMAT, version: BLOCK_VERSION, label: g.label, kind: g.kind === "strategy" ? "strategy" : "group",
    nodes: doc.nodes.filter((n) => m.has(n.id)), edges: doc.edges.filter((e) => m.has(e.source) && m.has(e.target)),
    output: g.kind === "strategy" ? g.output ?? null : null, saved_at: new Date().toISOString(),
  };
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** 블록 파일 읽기 — ★다른 포맷·다른 버전은 거부★(사유), 노드 타입은 검사하지 않는다(모르는 노드는 캔버스가 빨갛게 남긴다). */
export function parseBlock(text: string): { block: GraphBlock | null; problem: string | null } {
  let raw: unknown;
  try { raw = JSON.parse(text); } catch { return { block: null, problem: "JSON 이 아니에요." }; }
  if (!isObj(raw) || raw.format !== BLOCK_FORMAT) {
    return { block: null, problem: `블록 파일이 아니에요(format 이 "${BLOCK_FORMAT}" 이어야 해요).` };
  }
  if (raw.version !== BLOCK_VERSION) return { block: null, problem: `모르는 블록 버전 ${String(raw.version)} 이에요(지원: ${BLOCK_VERSION}).` };
  if (!Array.isArray(raw.nodes) || !raw.nodes.length || !Array.isArray(raw.edges)) return { block: null, problem: "노드가 없는 블록이에요." };
  const nodes: GraphDocNode[] = [];
  for (const n of raw.nodes) {
    if (!isObj(n) || typeof n.id !== "string" || typeof n.type !== "string") return { block: null, problem: "id·type 이 없는 노드가 있어요." };
    const p = isObj(n.position) ? n.position : {};
    nodes.push({ id: n.id, type: n.type, params: isObj(n.params) ? n.params : {},
                 position: { x: Number(p.x) || 0, y: Number(p.y) || 0 } });
  }
  const ids = new Set(nodes.map((n) => n.id));
  const edges: GraphDocEdge[] = (raw.edges as unknown[]).filter(isObj)
    .filter((e) => typeof e.source === "string" && typeof e.target === "string" && ids.has(e.source) && ids.has(e.target)
      && typeof e.source_port === "string" && typeof e.target_port === "string")
    .map((e) => ({ id: String(e.id ?? `${e.source}.${e.source_port}->${e.target}.${e.target_port}`), source: e.source as string,
                   source_port: e.source_port as string, target: e.target as string, target_port: e.target_port as string }));
  const label = typeof raw.label === "string" && raw.label.trim() ? raw.label.trim().slice(0, 40) : "이름 없는 블록";
  const kind = raw.kind === "strategy" ? "strategy" : "group";
  const output = typeof raw.output === "string" && ids.has(raw.output) ? raw.output : null;
  return { block: { format: BLOCK_FORMAT, version: BLOCK_VERSION, label, kind, nodes, edges, output,
                    saved_at: typeof raw.saved_at === "string" ? raw.saved_at : undefined }, problem: null };
}

// ── 이 브라우저의 블록 목록(편의 — 신뢰 저장이 아니다. 저장은 파일) ─────────────────────

export const BLOCKS_KEY = "alpha_pg_blocks";

/** 읽기 — 저장소를 못 쓰면 `available: false`(없음과 다르다). */
export function readBlocks(): { available: boolean; blocks: GraphBlock[] } {
  try {
    const raw = localStorage.getItem(BLOCKS_KEY);
    if (!raw) return { available: true, blocks: [] };
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return { available: true, blocks: [] };
    return { available: true, blocks: arr.map((x) => parseBlock(JSON.stringify(x)).block).filter((b): b is GraphBlock => !!b) };
  } catch {
    return { available: false, blocks: [] };
  }
}

export function writeBlocks(blocks: GraphBlock[]): boolean {
  try { localStorage.setItem(BLOCKS_KEY, JSON.stringify(blocks)); return true; } catch { return false; }
}
