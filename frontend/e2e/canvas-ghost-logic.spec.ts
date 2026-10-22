import { test, expect } from "@playwright/test";
import { CHIP_H, ghostSuggestions, placeConnectChip, placeSuggestion, MAX_GHOSTS, type PlaceNode } from "../src/entities/portfolio-graph/ghost";
import { cardHeight, COL, NODE_W, PORT_TOP, ROW_GAP } from "../src/entities/portfolio-graph/size";
import type { Procedure, ProcedureSuggestion } from "../src/entities/portfolio-graph/types";

/**
 * CF6 · 유령 노드 — 순수 규칙(브라우저 없이)
 *  · 유령 = next 먼저, 그다음 관문 순서의 by_gate · ★같은 추천(종류·잇는 선)은 하나로★ 합치고 그 관문을 모은다 · 최대 3
 *  · 문서에 없는 노드를 가리키는 추천은 뺀다(편집 직후의 낡은 검증) — 짝: 있는 노드면 남는다
 *  · 자리 = 붙을 노드 옆 열·같은 높이(지금 규칙) — ★카드·앞선 유령과 겹치면 그 아래 빈 자리★ · 짝: 비어 있으면 지금 자리 그대로
 */

const EST: ProcedureSuggestion = {
  action: "add", kind: "estimate", label: "기대 수익 추정", text: "‘기대 수익 추정’을 붙여 이을까요?",
  attach: [{ source: "@new", source_port: "belief", target: "optimizer", target_port: "belief" }], unlocks: [],
};
const BT: ProcedureSuggestion = {
  action: "add", kind: "backtest", label: "과거로 돌려 보기", text: "거래비용과 처음 보는 기간을 아직 재지 않았어요.",
  attach: [{ source: "optimizer", source_port: "weights", target: "@new", target_port: "weights" },
           { source: "returns", source_port: "returns", target: "@new", target_port: "returns" }],
  unlocks: ["cost", "oos"],
};
const proc = (next: ProcedureSuggestion | null, by_gate: Record<string, ProcedureSuggestion | null>): Procedure =>
  ({ steps: [], next, by_gate, done_text: null });
const IDS = ["universe", "returns", "optimizer"];

test("같은 추천은 하나로(잇는 선 순서가 달라도) · 관문을 모은다 · next 먼저", () => {
  const g = ghostSuggestions(proc(EST, { data: null, cost: BT, oos: { ...BT, attach: [...BT.attach].reverse() }, live: null }), IDS);
  expect(g.map((x) => x.kind)).toEqual(["estimate", "backtest"]);
  expect(g[0].isNext).toBe(true);
  expect(g[0].gates).toEqual([]);
  expect(g[1].isNext).toBe(false);
  expect(g[1].gates).toEqual(["cost", "oos"]);
  expect(g.every((x) => x.source === "rule")).toBe(true);
  expect(new Set(g.map((x) => x.key)).size).toBe(2);
});

test("짝: next 가 관문 추천과 같으면 유령 하나 — next 이면서 그 관문들을 연다", () => {
  const g = ghostSuggestions(proc(BT, { cost: BT, oos: BT }), IDS);
  expect(g).toHaveLength(1);
  expect(g[0].isNext).toBe(true);
  expect(g[0].gates).toEqual(["cost", "oos"]);
});

test(`많아도 ${MAX_GHOSTS}개까지`, () => {
  const k = (kind: string): ProcedureSuggestion => ({ ...BT, kind, label: kind, unlocks: [] });
  const g = ghostSuggestions(proc(EST, { data: k("a"), pit: k("b"), signal: k("c"), build: k("d") }), IDS);
  expect(MAX_GHOSTS).toBe(3);
  expect(g.map((x) => x.kind)).toEqual(["estimate", "a", "b"]);
});

test("문서에 없는 노드를 가리키는 추천은 뺀다 — 짝: 있는 노드·잇기만 하는 추천은 남는다", () => {
  const stale: ProcedureSuggestion = { ...BT, attach: [{ source: "gone", source_port: "weights", target: "@new", target_port: "weights" }] };
  const conn: ProcedureSuggestion = { action: "connect", kind: null, label: null, text: "이어 주세요",
                                      attach: [{ source: "universe", source_port: "universe", target: "returns", target_port: "universe" }], unlocks: [] };
  expect(ghostSuggestions(proc(stale, {}), IDS)).toEqual([]);
  const g = ghostSuggestions(proc(conn, { cost: BT }), IDS);
  expect(g.map((x) => x.action)).toEqual(["connect", "add"]);
  expect(ghostSuggestions(null, IDS)).toEqual([]);
});

const node = (id: string, kind: string, x: number, y: number): PlaceNode => ({ id, kind, position: { x, y } });

test("자리: 붙을 노드 앞 열 — 그 자리에 카드가 있으면 그 카드 아래 빈 자리 · 짝: 비어 있으면 지금 자리 그대로", () => {
  // 기대 수익 추정은 비중 계산으로 '내보낸다' — 비중 계산 한 열 앞(수익률 자리).
  const crowded = [node("returns", "returns", 320, 0), node("optimizer", "optimizer", 640, 0)];
  const p = placeSuggestion(EST, crowded, null);
  expect(p.x).toBe(640 - COL);
  expect(p.y).toBe(cardHeight("returns", null) + ROW_GAP);                 // 수익률 카드 아래
  const free = [node("returns", "returns", 320, 2000), node("optimizer", "optimizer", 640, 0)];
  expect(placeSuggestion(EST, free, null)).toEqual({ x: 640 - COL, y: 0 });  // 짝 — 지금 규칙 그대로
});

test("자리: 받아 오는 추천은 다음 열 · 앞선 유령 자리(taken)도 피한다", () => {
  const nodes = [node("returns", "returns", 320, 0), node("optimizer", "optimizer", 640, 0)];
  const first = placeSuggestion(BT, nodes, null);
  expect(first).toEqual({ x: 640 + COL, y: 0 });
  const taken = [{ x: first.x, y: first.y, w: NODE_W, h: cardHeight("backtest", null) }];
  const second = placeSuggestion(BT, nodes, null, taken);
  expect(second.x).toBe(640 + COL);
  expect(second.y).toBe(cardHeight("backtest", null) + ROW_GAP);
});

test("자리: 붙을 곳이 없으면 빈 캔버스는 0,0 · 아니면 맨 아래 카드 밑", () => {
  const lone: ProcedureSuggestion = { ...EST, attach: [] };
  expect(placeSuggestion(lone, [], null)).toEqual({ x: 0, y: 0 });
  const p = placeSuggestion(lone, [node("universe", "universe", 0, 0)], null);
  expect(p.x).toBe(0);
  expect(p.y).toBeGreaterThanOrEqual(cardHeight("universe", null) + ROW_GAP);   // 카드와 겹치지 않는다
});

test("잇기 칩 자리: 선 가운데가 비면 거기 · 아니면 두 카드 위 · 위도 막히면 아래 빈 자리", () => {
  const conn: ProcedureSuggestion = { action: "connect", kind: null, label: null, text: "이어 주세요",
                                      attach: [{ source: "universe", source_port: "universe", target: "returns", target_port: "universe" }], unlocks: [] };
  // 이웃한 열(틈 80) — 칩(카드 폭)은 선 가운데에선 카드에 걸린다 → 두 카드 바로 위(선과 가깝다).
  const near = [node("universe", "universe", 0, 0), node("returns", "returns", 320, 0)];
  const p = placeConnectChip(conn, near, null)!;
  expect(p.x).toBe((NODE_W + 320) / 2 - NODE_W / 2);
  expect(p.y).toBe(-CHIP_H - ROW_GAP);
  // 위에 다른 카드가 있으면 아래 빈 자리(두 카드 밑).
  const roofed = [...near, node("roof", "universe", 120, -CHIP_H)];                    // 칩이 놓일 위 자리에 걸치는 카드
  expect(placeConnectChip(conn, roofed, null)!.y).toBe(Math.max(cardHeight("universe", null), cardHeight("returns", null)) + ROW_GAP);
  // 짝 — 사이가 넓으면 선 가운데(첫 포트 줄 높이)에 그대로.
  const far = [node("universe", "universe", 0, 0), node("returns", "returns", 1000, 0)];
  expect(placeConnectChip(conn, far, null)).toEqual({ x: (NODE_W + 1000) / 2 - NODE_W / 2, y: PORT_TOP });
  // 앞선 유령 자리(taken)도 피한다 — 선 가운데가 차 있으면 위로.
  const taken = [{ x: (NODE_W + 1000) / 2 - NODE_W / 2, y: PORT_TOP, w: NODE_W, h: CHIP_H }];
  expect(placeConnectChip(conn, far, null, taken)!.y).toBe(-CHIP_H - ROW_GAP);
  expect(placeConnectChip({ ...conn, attach: [] }, far, null)).toBeNull();
});
