import { test, expect, type Page } from "@playwright/test";
import { boxDropPlan, frameRect } from "../src/entities/portfolio-graph/boxdrop";
import { GROUP_PAD, NODE_W, nodeHeight } from "../src/entities/portfolio-graph/size";
import type { GraphGroup } from "../src/entities/portfolio-graph/types";

/**
 * CF 3부 R4 · 상자에 끌어 넣기·빼기 (스펙 §8.3 결정 4 — "넣기·빼기 모두 끌어서")
 *  ① 카드 넓이의 절반 이상이 펼친 상자 안이면 넣는다(여럿이면 가장 많이 겹친 상자) — 짝: 30% 면 그대로
 *  ② 끌기 전 상자 테두리 밖으로 ★완전히★ 나가면 뺀다 — 짝: 조금 옮겨 걸치면 그대로(가장자리 멤버가 조금 밀렸다고 빠지지 않는다)
 *  ③ 한 노드는 한 상자 · 전략의 비중을 내는 노드는 뺄 수 없다 · 전략을 합치는 노드는 전략 상자에 넣을 수 없다 · 접힌 상자는 대상이 아니다 ·
 *     들어간 상자 안이면 그 상자만
 *  ④ 끄는 동안 넣을 상자가 빛나고 · 놓으면 자리와 멤버가 함께 ★되돌리기 한 단계★ · 무엇을 했는지 토스트로
 */

type N = { id: string; position: { x: number; y: number }; data: { kind: string } };
const nd = (id: string, x: number, y = 0, kind = "optimizer"): N => ({ id, position: { x, y }, data: { kind } });
const H = nodeHeight("optimizer", null);
const BASE = [nd("u", 0), nd("r", 330), nd("e", 660), nd("o", 990)];
const at = (ns: N[], id: string, x: number, y = 0) => ns.map((n) => (n.id === id ? { ...n, position: { x, y } } : n));
const G1: GraphGroup = { id: "g1", label: "묶음", members: ["u", "r"] };
const plan = (ids: string[], now: N[], groups: GraphGroup[], focus: string | null = null, start: N[] = BASE) =>
  boxDropPlan(ids, now, start, groups, null, focus);

test.describe("규칙 (브라우저 없이)", () => {
  test("R4 · 상자 테두리 = 멤버 카드 + 여백 28 · 머리 30", () => {
    expect(frameRect([BASE[0], BASE[1]], null)).toEqual({ x0: -GROUP_PAD, y0: -GROUP_PAD - 30, x1: 330 + NODE_W + GROUP_PAD, y1: H + GROUP_PAD });
    expect(frameRect([], null)).toBeNull();
  });

  test("R4 · 절반 넘게 겹치면 넣는다 (짝: 30% 면 그대로)", () => {
    const x1 = 330 + NODE_W + GROUP_PAD;                                         // 598
    expect(plan(["e"], at(BASE, "e", x1 - 0.6 * NODE_W), [G1])).toEqual({ moves: [{ id: "e", from: null, to: "g1" }], blocked: [] });
    expect(plan(["e"], at(BASE, "e", x1 - 0.3 * NODE_W), [G1])).toEqual({ moves: [], blocked: [] });
  });

  test("R4 · 끌기 전 테두리 밖으로 완전히 나가면 뺀다 (짝: 조금 옮겨 걸치면 그대로 — 가장자리 멤버)", () => {
    expect(plan(["r"], at(BASE, "r", 1400), [G1])).toEqual({ moves: [{ id: "r", from: "g1", to: null }], blocked: [] });
    expect(plan(["r"], at(BASE, "r", 330 + 66), [G1])).toEqual({ moves: [], blocked: [] });
    expect(plan(["u", "r"], at(at(BASE, "u", 1400), "r", 1730), [G1])).toEqual({ moves: [], blocked: [] });   // 멤버를 다 끌면 상자째 옮긴 것
  });

  test("R4 · 여럿이 겹치면 가장 많이 겹친 상자 · A 에서 B 로 옮기면 한 상자에만", () => {
    const g2: GraphGroup = { id: "g2", label: "둘째", members: ["o"] };
    // e 를 g1(오른쪽 끝 598)과 g2(왼쪽 끝 962) 사이에 — g2 쪽이 더 많이 겹친다
    const p = plan(["e"], at(BASE, "e", 962 - 0.3 * NODE_W), [G1, g2]);
    expect(p.moves).toEqual([{ id: "e", from: null, to: "g2" }]);
    expect(plan(["r"], at(BASE, "r", 990 - 0.2 * NODE_W), [G1, g2]).moves).toEqual([{ id: "r", from: "g1", to: "g2" }]);
    // 위아래로 붙은 두 상자의 테두리가 겹치는 띠 — 카드가 둘 다에 절반 넘게 들면 더 많이 겹친 쪽(짝: 위로 옮기면 위 상자)
    const ns = [nd("a", 0), nd("b", 0, H + 40), nd("d", 660)];
    const top: GraphGroup = { id: "top", label: "위", members: ["a"] }, low: GraphGroup = { id: "low", label: "아래", members: ["b"] };
    const drop = (y: number) => boxDropPlan(["d"], at(ns, "d", 0, y), ns, [top, low], null, null).moves;
    expect(drop(H / 2 + 20)).toEqual([{ id: "d", from: null, to: "low" }]);     // 위 상자에도 절반 넘게 들지만 아래가 더 많다
    expect(drop(H / 2 - 20)).toEqual([{ id: "d", from: null, to: "top" }]);
  });

  test("R4 · 전략의 비중을 내는 노드는 뺄 수 없다 (짝: 다른 멤버는 빠진다)", () => {
    const s: GraphGroup = { id: "s1", label: "전략 1", kind: "strategy", members: ["r", "e", "o"], output: "o" };
    const p = plan(["o"], at(BASE, "o", 1800), [s]);
    expect(p.moves).toEqual([]);
    expect(p.blocked).toEqual([{ id: "o", why: "‘전략 1’의 비중을 내는 노드라 상자 밖으로 뺄 수 없어요." }]);
    expect(plan(["r"], at(BASE, "r", 330, 900), [s]).moves).toEqual([{ id: "r", from: "s1", to: null }]);
  });

  test("R4 · 전략을 합치는 노드는 전략 상자에 넣을 수 없다 (짝: 그냥 묶음에는 넣는다)", () => {
    const ns = [...BASE, nd("pf", 330, 900, "portfolio_combine")];
    const s: GraphGroup = { id: "s1", label: "전략 1", kind: "strategy", members: ["u", "r"], output: "r" };
    const p = boxDropPlan(["pf"], at(ns, "pf", 200), ns, [s], null, null);
    expect(p.moves).toEqual([]);
    expect(p.blocked[0].why).toMatch(/전략 상자에 넣을 수 없어요/);
    expect(boxDropPlan(["pf"], at(ns, "pf", 200), ns, [G1], null, null).moves).toEqual([{ id: "pf", from: null, to: "g1" }]);
  });

  test("R4 · 접힌 상자는 대상이 아니다 · 들어간 상자 안이면 그 상자만 (짝)", () => {
    const folded = { ...G1, collapsed: true };
    expect(plan(["e"], at(BASE, "e", 450), [folded]).moves).toEqual([]);
    const g2: GraphGroup = { id: "g2", label: "둘째", members: ["o"] };
    expect(plan(["e"], at(BASE, "e", 450), [G1, g2], "g2").moves).toEqual([]);                  // 들어간 상자(g2)가 아니면 넣지 않는다
    expect(plan(["e"], at(BASE, "e", 450), [G1, g2], "g1").moves).toEqual([{ id: "e", from: null, to: "g1" }]);
  });
});

// ── 화면 ─────────────────────────────────────────────────────────────────────

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const NODES = [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
               n("estimate", "estimate", 660, 0), n("optimizer", "optimizer", 990, 0)];
const EDGES = [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
               e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")];
const DOC = { ...F, nodes: NODES, edges: EDGES, groups: [{ id: "g1", label: "묶음", members: ["universe", "returns"] }] };
const HEAD = { x: 30, y: 14 };
type Doc = { nodes: { id: string; position: { x: number; y: number } }[]; groups?: { id: string; members: string[] }[] };

async function open(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("r4_seeded")) return;
      sessionStorage.setItem("r4_seeded", "1");
      for (const k of ["alpha_pg_panels", "alpha_pg_view", "alpha_pg_left_tab"]) localStorage.removeItem(k);
      localStorage.setItem("alpha_pg_welcomed", "1");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(350);
}
const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const box = (page: Page, id: string) => page.locator(`.pg-group[data-group-id="${id}"]`);
const undoBtn = (page: Page) => page.getByRole("button", { name: "되돌리기 (Ctrl+Z)" });
const zoomOf = (page: Page) => page.locator(".pg-canvas").evaluate((el) => Number(getComputedStyle(el).getPropertyValue("--pg-z")));
const wip = async (page: Page): Promise<Doc> => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}"));
const membersOf = async (page: Page, g: string) => ((await wip(page)).groups ?? []).find((x) => x.id === g)?.members ?? [];
const xOf = async (page: Page, id: string) => (await wip(page)).nodes.find((x) => x.id === id)!.position.x;

/** 카드 머리를 잡고 캔버스 좌표로 (dx, dy) 끈다 — `hold` 면 놓지 않는다. */
async function dragBy(page: Page, id: string, dx: number, dy = 0, hold = false) {
  const b = (await node(page, id).boundingBox())!;
  const z = await zoomOf(page);
  const p = { x: b.x + HEAD.x, y: b.y + HEAD.y };
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x + (dx * z) / 2, p.y + (dy * z) / 2, { steps: 6 });
  await page.mouse.move(p.x + dx * z, p.y + dy * z, { steps: 6 });
  if (!hold) { await page.mouse.up(); await page.waitForTimeout(200); }
}

test.use({ viewport: { width: 1440, height: 900 } });

test("R4 · 끌어 넣기 — 끄는 동안 상자가 빛나고 · 놓으면 멤버 · 되돌리기 한 번에 자리와 멤버 (짝: 놓으면 빛이 꺼진다)", async ({ page }) => {
  await open(page, DOC);
  const before = await wip(page);
  await expect(undoBtn(page)).toBeDisabled();
  await dragBy(page, "estimate", 450 - 660, 0, true);                             // 상자 오른쪽 끝(598) 안으로 카드의 약 60%
  await expect(box(page, "g1")).toHaveClass(/pg-group--drop/);
  await page.mouse.up();
  await expect(box(page, "g1")).not.toHaveClass(/pg-group--drop/);
  await expect.poll(() => membersOf(page, "g1")).toEqual(["universe", "returns", "estimate"]);
  await expect(page.locator(".pg-note")).toContainText("넣었어요");
  await page.keyboard.press("Control+z");
  await expect.poll(async () => ({ g: (await wip(page)).groups, x: await xOf(page, "estimate") }))
    .toEqual({ g: before.groups, x: before.nodes.find((x) => x.id === "estimate")!.position.x });
  await expect(undoBtn(page)).toBeDisabled();                                     // 자리와 멤버가 한 단계
});

test("R4 · (짝) 30% 만 겹치면 넣지 않고 빛나지도 않는다", async ({ page }) => {
  await open(page, DOC);
  await dragBy(page, "estimate", 598 - 0.3 * 240 - 660, 0, true);
  await expect(box(page, "g1")).not.toHaveClass(/pg-group--drop/);
  await page.mouse.up();
  await page.waitForTimeout(250);
  expect(await membersOf(page, "g1")).toEqual(["universe", "returns"]);
});

test("R4 · 끌기 전 테두리 밖으로 완전히 빼면 뺀다 (짝: 조금 옮겨 걸치면 그대로)", async ({ page }) => {
  await open(page, DOC);
  await dragBy(page, "returns", 66, 0);
  await page.waitForTimeout(250);
  expect(await membersOf(page, "g1")).toEqual(["universe", "returns"]);           // 가장자리 멤버를 조금 밀어도 빠지지 않는다
  await dragBy(page, "returns", 0, 700);
  await expect.poll(() => membersOf(page, "g1")).toEqual(["universe"]);
  await expect(page.locator(".pg-note")).toContainText("뺐어요");
});

test("R4 · 전략의 비중을 내는 노드는 빼지 않고 까닭을 말한다 (짝: 다른 멤버는 빠진다)", async ({ page }) => {
  const strat = { ...F, nodes: NODES, edges: EDGES,
                  groups: [{ id: "s1", label: "전략 1", kind: "strategy", color: 0, members: ["returns", "estimate", "optimizer"], output: "optimizer" }] };
  await open(page, strat);
  await dragBy(page, "optimizer", 0, 800);
  await expect(page.locator(".pg-note")).toContainText("비중을 내는 노드라 상자 밖으로 뺄 수 없어요");
  expect(await membersOf(page, "s1")).toEqual(["returns", "estimate", "optimizer"]);
  // 막혀도 자리는 옮겨졌다 — 상자가 그만큼 아래로 커졌으니 되돌리고 다른 멤버를 뺀다
  await page.locator(".pg-note-x").click();
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).nodes.find((x) => x.id === "optimizer")!.position.y).toBe(0);
  await dragBy(page, "estimate", 0, 800);
  await expect.poll(() => membersOf(page, "s1")).toEqual(["returns", "optimizer"]);
});

test("R4 · 둘을 함께 끌어 넣으면 둘 다 · 다른 상자는 빛나지 않는다", async ({ page }) => {
  const two = { ...DOC, nodes: [...NODES, n("risk", "risk", 990, 600)],
                groups: [...DOC.groups, { id: "g2", label: "둘째", members: ["risk"] }] };
  await open(page, two);
  await node(page, "estimate").click({ position: HEAD });
  await node(page, "optimizer").click({ position: HEAD, modifiers: ["Control"] });
  await dragBy(page, "estimate", -700, 0, true);                                  // 둘이 함께 왼쪽으로 — optimizer 가 상자 오른쪽 끝(598) 안에 가로로 다 든다
  await expect(box(page, "g1")).toHaveClass(/pg-group--drop/);
  await expect(box(page, "g2")).not.toHaveClass(/pg-group--drop/);
  await page.mouse.up();
  await expect.poll(() => membersOf(page, "g1")).toEqual(["universe", "returns", "estimate", "optimizer"]);
  expect(await membersOf(page, "g2")).toEqual(["risk"]);
  await page.keyboard.press("Control+z");
  await expect.poll(() => membersOf(page, "g1")).toEqual(["universe", "returns"]);     // 둘을 한 번에 되돌린다
});
