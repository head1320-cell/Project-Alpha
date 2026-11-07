/**
 * 유령 노드(CF6) — 서버 규칙 추천(`procedure.next` · `by_gate`)을 캔버스에 보일 모양과 자리.
 * ★추천을 새로 만들지 않는다★ — 서버가 낸 것을 합치고(같은 추천은 하나로) 놓일 자리만 정한다. 설정값은 다루지 않는다.
 * AI1 — 서버가 검사를 통과시킨 AI 추천도 같은 그릇에 담는다(`withAiGhosts`): 규칙과 같은 추천이면 그 유령에 AI 이유를 붙이고(두 칩), 아니면 따로.
 */
import { NEW_NODE } from "./procedure";
import { cardHeight, COL, NODE_W, nodeHeight, PORT_TOP, ROW_GAP } from "./size";
import type { AiSuggestion, NodeCatalogEntry, Procedure, ProcedureSuggestion } from "./types";

/** 한 번에 보일 유령 수 — 2부 AI1(노드 추천 1~3)과 같은 그릇. */
export const MAX_GHOSTS = 3;

export interface Ghost extends ProcedureSuggestion {
  /** 같은 추천을 가리는 서명(종류 · 잇는 선). 숨김·붙이기 자리를 이 키로 찾는다. */
  key: string;
  /** 누가 낸 추천인가 — 서버 규칙(`rule`) 또는 AI(`claude`, AI1). 글(`text`)은 이 출처의 것이다. */
  source: "rule" | "claude";
  /** AI 가 같은 추천을 냈으면 그 이유(서버 검사를 통과한 한 줄) — 규칙 유령이면 두 칩, AI 유령이면 `text` 와 같다. 없으면 null. */
  aiReason: string | null;
  /** 이 추천으로 잴 수 있게 되는 관문(관문별 추천 키 + `unlocks`, 서버 관문 순서). */
  gates: string[];
  /** 아래 '다음 한 걸음' 바와 같은 추천인가. */
  isNext: boolean;
}

/** 같은 추천인지 — 종류와 잇는 선(순서 무관)이 같으면 같다. */
export function suggestionKey(s: ProcedureSuggestion): string {
  return JSON.stringify([s.action, s.kind, s.attach.map((a) => `${a.source}.${a.source_port}>${a.target}.${a.target_port}`).sort()]);
}

/** 보일 유령 — next 먼저, 그다음 관문 순서. 같은 추천은 하나로(관문을 모은다). 문서에 없는 노드를 가리키는 추천은 뺀다(편집 직후의 낡은 검증). */
export function ghostSuggestions(proc: Procedure | null | undefined, nodeIds: Iterable<string>): Ghost[] {
  if (!proc) return [];
  const have = new Set(nodeIds);
  const real = (id: string) => id === NEW_NODE || have.has(id);
  const order = Object.keys(proc.by_gate ?? {});
  const rank = (g: string) => (order.indexOf(g) < 0 ? order.length : order.indexOf(g));
  const out: Ghost[] = [];
  const take = (s: ProcedureSuggestion | null, gate: string | null, isNext: boolean) => {
    if (!s || !s.attach.every((a) => real(a.source) && real(a.target))) return;
    const key = suggestionKey(s);
    let g = out.find((x) => x.key === key);
    if (!g) { g = { ...s, key, source: "rule", aiReason: null, gates: [], isNext }; out.push(g); }
    for (const k of [...(gate ? [gate] : []), ...s.unlocks]) if (!g.gates.includes(k)) g.gates.push(k);
  };
  take(proc.next, null, true);
  for (const k of order) take(proc.by_gate[k], k, false);
  for (const g of out) g.gates.sort((a, b) => rank(a) - rank(b));
  return out.slice(0, MAX_GHOSTS);
}

/**
 * AI 추천을 유령에 합친다(AI1) — 같은 추천(종류·잇는 선, 순서 무관)이 규칙 유령에 있으면 그 유령에 AI 이유만 붙인다(유령 하나에 두 칩).
 * 아니면 AI 유령을 규칙 유령 뒤에 더한다(AI 만 최대 `MAX_GHOSTS`). 문서에 없는 노드를 가리키는 추천은 뺀다(규칙 유령과 같은 규칙).
 */
export function withAiGhosts(rule: Ghost[], ai: AiSuggestion[], nodeIds: Iterable<string>): Ghost[] {
  const have = new Set(nodeIds);
  const real = (id: string) => id === NEW_NODE || have.has(id);
  const out = rule.map((g) => ({ ...g }));
  let added = 0;
  for (const s of ai) {
    if (!s.attach.every((a) => real(a.source) && real(a.target))) continue;
    const sug: ProcedureSuggestion = { action: "add", kind: s.kind, label: s.label, text: s.reason, attach: s.attach, unlocks: [] };
    const key = suggestionKey(sug);
    const same = out.find((g) => g.key === key);
    if (same) { same.aiReason = s.reason; continue; }
    if (added >= MAX_GHOSTS) continue;
    out.push({ ...sug, key, source: "claude", aiReason: s.reason, gates: [], isNext: false });
    added++;
  }
  return out;
}

/** 자리를 잴 노드 — 문서 노드의 id · 종류 · 왼쪽 위. */
export interface PlaceNode { id: string; kind: string; position: { x: number; y: number }; slotH?: number }
/** 캔버스 노드 → 자리 계산용(R3 — 늘린 결과 칸을 함께 넘긴다). 유령·초안·추천 붙이기가 같은 것을 쓴다. */
export const placeNodes = (nodes: { id: string; position: { x: number; y: number }; data: { kind: string; slotH?: number } }[]): PlaceNode[] =>
  nodes.map((n) => ({ id: n.id, kind: n.data.kind, position: n.position, ...(n.data.slotH ? { slotH: n.data.slotH } : {}) }));
/** 차지한 상자(캔버스 좌표). */
export interface Box { x: number; y: number; w: number; h: number }

/**
 * 붙일 노드가 놓일 자리 — 붙을 노드 옆 열·같은 높이(받아 오면 다음 열, 내보내면 앞 열 · 붙을 곳이 없으면 맨 아래 밑 · 빈 캔버스는 0,0).
 * 그 자리에 카드나 앞선 유령(`taken`)이 있으면 ★그 아래 빈 자리★로 내린다 — 예전엔 같은 높이에 겹쳐 놓았다(CF6 이 찾음).
 */
export function placeSuggestion(sug: ProcedureSuggestion, nodes: PlaceNode[], catalog: NodeCatalogEntry[] | null | undefined,
                                taken: Box[] = []): { x: number; y: number } {
  const pos = (id: string) => nodes.find((n) => n.id === id)?.position;
  const from = sug.attach.find((a) => a.target === NEW_NODE && a.source !== NEW_NODE);
  const to = sug.attach.find((a) => a.source === NEW_NODE && a.target !== NEW_NODE);
  const anchor = (from && pos(from.source)) ?? (to && pos(to.target));
  const dx = from ? COL : to ? -COL : 0;
  const bottom = nodes.reduce((m, n) => Math.max(m, n.position.y), 0);
  const p = anchor ? { x: anchor.x + dx, y: anchor.y } : { x: 0, y: nodes.length ? bottom + 200 : 0 };
  return freeSpot(p, sug.kind ? cardHeight(sug.kind, catalog) : 0, boxesOf(nodes, catalog, taken));
}

/** 잇기 추천의 칩 높이(캔버스 좌표) — 칩은 카드 폭에 글 두세 줄 + 단추. 자리를 찾을 때만 쓴다. */
export const CHIP_H = 150;

/**
 * 잇기 추천의 칩 자리 — ① 두 노드 사이 선 가운데(첫 포트 줄 높이)가 비면 거기 ② 아니면 두 카드 바로 위 ③ 그것도 막히면 ①에서 아래로 빈 자리.
 * 이웃한 열은 틈이 80 이라 ①은 카드에 걸린다 — 카드 밑에 깔리면 단추를 누를 수 없었고(CF6 E2E), 카드 아래로만 내리면 선과 멀었다(PNG). 이을 노드가 없으면 null.
 */
export function placeConnectChip(sug: ProcedureSuggestion, nodes: PlaceNode[], catalog: NodeCatalogEntry[] | null | undefined,
                                 taken: Box[] = []): { x: number; y: number } | null {
  const a = sug.attach[0];
  const s = a && nodes.find((n) => n.id === a.source)?.position;
  const t = a && nodes.find((n) => n.id === a.target)?.position;
  if (!s || !t) return null;
  const mid = { x: (s.x + NODE_W + t.x) / 2, y: (s.y + t.y) / 2 + PORT_TOP };
  const boxes = boxesOf(nodes, catalog, taken);
  const onWire = { x: mid.x - NODE_W / 2, y: mid.y };
  const above = { x: onWire.x, y: Math.min(s.y, t.y) - CHIP_H - ROW_GAP };
  for (const p of [onWire, above]) if (!blocking(p, CHIP_H, boxes).length) return p;
  return freeSpot(onWire, CHIP_H, boxes);
}

function boxesOf(nodes: PlaceNode[], catalog: NodeCatalogEntry[] | null | undefined, taken: Box[]): Box[] {
  return [...nodes.map((n) => ({ x: n.position.x, y: n.position.y, w: NODE_W, h: nodeHeight(n.kind, catalog, n.slotH) })), ...taken];
}

/** 폭 `NODE_W` · 높이 `h` 상자를 `p` 에서 시작해 겹치는 상자 아래로 내려 빈 자리(틈 `ROW_GAP`). */
function freeSpot(start: { x: number; y: number }, h: number, boxes: Box[]): { x: number; y: number } {
  const p = { ...start };
  for (let i = 0; i < boxes.length + 1; i++) {
    const hit = blocking(p, h, boxes);
    if (!hit.length) break;
    p.y = Math.max(...hit.map((b) => b.y + b.h)) + ROW_GAP;
  }
  return p;
}

/** `p` 에 놓은 폭 `NODE_W` · 높이 `h` 상자와 겹치는(틈 `ROW_GAP` 안) 상자들. */
function blocking(p: { x: number; y: number }, h: number, boxes: Box[]): Box[] {
  return boxes.filter((b) => p.x < b.x + b.w && p.x + NODE_W > b.x && p.y < b.y + b.h + ROW_GAP && p.y + h + ROW_GAP > b.y);
}
