import { test, expect } from "@playwright/test";
import { fromDoc, parseFile, toDoc } from "../src/entities/portfolio-graph/format";
import { placeSuggestion } from "../src/entities/portfolio-graph/ghost";
import { cardHeight, cardsOverlap, COL, COMBINE_SLOT_H, nodeHeight, restackColumns, ROW_GAP, SLOT_H, SLOT_MAX_K, slotBase, slotHeight } from "../src/entities/portfolio-graph/size";
import { mapLayout } from "../src/entities/portfolio-graph/strategy";
import type { ProcedureSuggestion } from "../src/entities/portfolio-graph/types";

/**
 * CF 3부 R3 · 결과 칸 높이 — 순수 규칙(브라우저 없이)
 *  · 결과 칸 = 기본(156 · 합치기 168) ~ 세 배 · 숫자가 아니면 기본 · 카드 높이 = cardHeight + (결과 칸 − 기본)
 *  · 문서 `size.slot_h` — 범위 밖이면 맞추고 · 숫자가 아니면 빼고 ★둘 다 문제 줄★ · 기본이면 쓰지 않는다 · 파일 왕복
 *  · 높이를 쓰는 배치 규칙(겹침·다시 쌓기·유령 자리·전략 지도)이 늘린 높이를 본다 — 짝: 늘리지 않으면 지금과 같다
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const fileWith = (size?: unknown, type = "optimizer") =>
  JSON.stringify({ ...F, nodes: [{ id: "o", type, params: {}, position: { x: 0, y: 0 }, ...(size === undefined ? {} : { size }) }], edges: [] });

test("R3 · 결과 칸 — 기본 156 · 합치기 168 · 세 배까지 맞춘다 · 숫자가 아니면 기본 (짝: 범위 안 값은 그대로)", () => {
  expect(slotBase("optimizer")).toBe(SLOT_H);
  expect(slotBase("portfolio_combine")).toBe(COMBINE_SLOT_H);
  expect(SLOT_MAX_K).toBe(3);
  expect(slotHeight("optimizer", undefined)).toBe(SLOT_H);
  expect(slotHeight("optimizer", Number.NaN)).toBe(SLOT_H);
  expect(slotHeight("optimizer", "300" as unknown as number)).toBe(SLOT_H);
  expect(slotHeight("optimizer", 300)).toBe(300);                                   // 짝 — 범위 안
  expect(slotHeight("optimizer", 300.4)).toBe(300);
  expect(slotHeight("optimizer", 10)).toBe(SLOT_H);
  expect(slotHeight("optimizer", 9999)).toBe(SLOT_H * 3);
  expect(slotHeight("portfolio_combine", 9999)).toBe(COMBINE_SLOT_H * 3);
  expect(nodeHeight("optimizer", null, undefined)).toBe(cardHeight("optimizer", null));
  expect(nodeHeight("optimizer", null, 300)).toBe(cardHeight("optimizer", null) + 300 - SLOT_H);
  expect(nodeHeight("portfolio_combine", null, 268)).toBe(cardHeight("portfolio_combine", null) + 100);
});

test("R3 · 문서 size.slot_h — 범위 밖은 맞추고·숫자가 아니면 빼고 둘 다 문제 줄 (짝: 범위 안·없음은 문제 0)", () => {
  const ok = parseFile(fileWith({ slot_h: 300 }));
  expect(ok.problems).toEqual([]);
  expect(ok.doc!.nodes[0].size).toEqual({ slot_h: 300 });
  const none = parseFile(fileWith());
  expect(none.problems).toEqual([]);
  expect(none.doc!.nodes[0]).not.toHaveProperty("size");
  const big = parseFile(fileWith({ slot_h: 9999 }));
  expect(big.doc!.nodes[0].size).toEqual({ slot_h: SLOT_H * 3 });
  expect(big.problems).toHaveLength(1);
  expect(big.problems[0]).toMatch(/노드 o 의 결과 칸 높이 9999 .*468/);
  const small = parseFile(fileWith({ slot_h: 40 }));
  expect(small.doc!.nodes[0]).not.toHaveProperty("size");                          // 기본으로 맞추면 쓸 것이 없다
  expect(small.problems[0]).toMatch(/노드 o 의 결과 칸 높이 40 .*156/);
  for (const bad of [{ slot_h: "big" }, "x", { slot_h: null }, { h: 300 }]) {
    const r = parseFile(fileWith(bad));
    expect(r.doc!.nodes[0], JSON.stringify(bad)).not.toHaveProperty("size");
    expect(r.problems, JSON.stringify(bad)).toHaveLength(1);
    expect(r.problems[0]).toMatch(/노드 o 의 결과 칸 높이가 숫자가 아니라 뺐어요/);
  }
});

test("R3 · fromDoc → data.slotH · toDoc 은 기본보다 클 때만 쓴다 · 파일 왕복 (짝: 기본·없음이면 size 없음)", () => {
  const doc = parseFile(fileWith({ slot_h: 300 })).doc!;
  const { nodes, edges } = fromDoc(doc, []);
  expect(nodes[0].data.slotH).toBe(300);
  expect(toDoc(nodes, edges).nodes[0].size).toEqual({ slot_h: 300 });
  expect(parseFile(JSON.stringify(toDoc(nodes, edges))).doc!.nodes[0].size).toEqual({ slot_h: 300 });
  const base = { ...nodes[0], data: { ...nodes[0].data, slotH: SLOT_H } };
  expect(toDoc([base], []).nodes[0]).not.toHaveProperty("size");
  const plain = fromDoc(parseFile(fileWith()).doc!, []).nodes;
  expect(plain[0].data).not.toHaveProperty("slotH");
  expect(toDoc(plain, []).nodes[0]).not.toHaveProperty("size");
});

const card = (id: string, y: number, slotH?: number) => ({ id, position: { x: 0, y }, data: { kind: "optimizer", ...(slotH ? { slotH } : {}) } });

test("R3 · 겹침·다시 쌓기가 늘린 높이를 본다 (짝: 늘리지 않으면 지금과 같다)", () => {
  const h = cardHeight("optimizer", null);
  expect(cardsOverlap([card("a", 0), card("b", h + ROW_GAP)], null)).toBe(false);
  expect(cardsOverlap([card("a", 0, 300), card("b", h + ROW_GAP)], null)).toBe(true);
  const plain = restackColumns([card("a", 0), card("b", 1)], null);
  const grown = restackColumns([card("a", 0, 300), card("b", 1)], null);
  const gap = (xs: typeof plain) => xs[1].position.y - xs[0].position.y;
  expect(gap(plain)).toBe(h + ROW_GAP);
  expect(gap(grown)).toBe(h + ROW_GAP + 300 - SLOT_H);
});

test("R3 · 유령 자리가 늘린 카드를 피한다 (짝: 늘리지 않으면 이음 노드 옆 같은 높이)", () => {
  const sug: ProcedureSuggestion = { action: "add", kind: "backtest", label: "과거로 돌려 보기", text: "",
    attach: [{ source: "a", source_port: "weights", target: "@new", target_port: "weights" }], unlocks: [] };
  const above = (slotH?: number) => ({ id: "b", kind: "optimizer", position: { x: COL, y: -cardHeight("optimizer", null) - ROW_GAP - 10 }, ...(slotH ? { slotH } : {}) });
  const a = { id: "a", kind: "optimizer", position: { x: 0, y: 0 } };
  expect(placeSuggestion(sug, [a, above()], null)).toEqual({ x: COL, y: 0 });
  const p = placeSuggestion(sug, [a, above(SLOT_H + 100)], null);
  expect(p.x).toBe(COL);
  expect(p.y).toBe(-ROW_GAP - 10 + 100 + ROW_GAP);                                  // 늘린 카드 아래(바닥 −38 + 100) + 틈으로 내려간다
});

test("R3 · 전략 지도가 늘린 높이로 줄을 띄운다 (짝: 늘리지 않으면 카드 높이 + 틈)", () => {
  const n = (id: string, slotH?: number) => ({ id, position: { x: 0, y: 0 }, data: { kind: "optimizer", ...(slotH ? { slotH } : {}) } });
  const gapOf = (ns: ReturnType<typeof n>[]) => { const m = mapLayout(ns, [], []); return m.get("b")!.y - m.get("a")!.y; };
  expect(gapOf([n("a"), n("b")])).toBe(cardHeight("optimizer", null) + ROW_GAP);
  expect(gapOf([n("a", SLOT_H + 100), n("b")])).toBe(cardHeight("optimizer", null) + ROW_GAP + 100);
});
