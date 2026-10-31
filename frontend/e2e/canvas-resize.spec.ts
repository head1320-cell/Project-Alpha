import { test, expect, type Page } from "@playwright/test";
import { cardHeight, nodeHeight, SLOT_H } from "../src/entities/portfolio-graph/size";
import type { NodeCatalogEntry } from "../src/entities/portfolio-graph/types";

/**
 * CF 3부 R3 · 결과 칸 높이 (스펙 §8.3 결정 1 — ★결과 칸 높이만★ · ★늘린 만큼 더 보여 줌★)
 *  ① 하나만 고른 펼친 카드의 아래 손잡이로 결과 칸을 늘린다 — 세 확대에서 카드 높이 = nodeHeight · 다른 카드 그대로 · 되돌리기 한 단계
 *  ② 기본 ~ 세 배에서 멈춘다 · 여럿·접힘·멀리에서는 손잡이가 없다
 *  ③ 문서에 남는다(`size.slot_h`) — 다시 열면 그대로 · 범위 밖은 맞추고 말한다
 *  ④ 높이는 그림일 뿐 — 계산 뒤 늘려도 예전 결과가 되지 않는다 · 상자 테두리·복제가 늘린 높이를 본다
 *  ⑤ 늘린 만큼 막대가 더 보인다(서버가 보낸 개수까지 — 새 숫자는 없다)
 */

const CAT = "http://localhost:8000/api/v1/allocation/graph/node-types";
const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}, extra: object = {}) =>
  ({ id, type, position: { x, y }, params, ...extra });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const T8 = ["005930", "000660", "035420", "051910", "006400", "035720", "005380", "068270"];
const nodesOf = (tickers: string[], optExtra: object = {}, optParams: Record<string, unknown> = {}) => [
  n("universe", "universe", 0, 0, { tickers }), n("returns", "returns", 330, 0),
  n("estimate", "estimate", 660, 0), n("optimizer", "optimizer", 990, 0, optParams, optExtra)];
const EDGES = [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
               e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")];
const CORE = { ...F, nodes: nodesOf(T8.slice(0, 3)), edges: EDGES };
const HEAD = { x: 30, y: 14 };

type Doc = { nodes: { id: string; position: { x: number; y: number }; size?: { slot_h: number } }[] };

async function open(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("r3_seeded")) return;
      sessionStorage.setItem("r3_seeded", "1");
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
const catalog = async (page: Page): Promise<NodeCatalogEntry[]> => (await (await page.request.get(CAT)).json()).nodes;
const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const grip = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"] .pg-node-resize`);
const canvas = (page: Page) => page.locator(".pg-canvas");
const undoBtn = (page: Page) => page.getByRole("button", { name: "되돌리기 (Ctrl+Z)" });
const zoomOf = (page: Page) => canvas(page).evaluate((el) => Number(getComputedStyle(el).getPropertyValue("--pg-z")));
const wip = async (page: Page): Promise<Doc> => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}"));
const slotOf = async (page: Page, id: string) => (await wip(page)).nodes.find((x) => x.id === id)?.size?.slot_h;
/** 화면 카드 높이 ÷ 확대율 = 캔버스 좌표 높이. */
const hOf = async (page: Page, id: string) => { const b = (await node(page, id).boundingBox())!; return b.height / (await zoomOf(page)); };

async function zoomTo(page: Page, level: "far" | "mid" | "near") {
  for (let i = 0; i < 16; i++) {
    const z = await canvas(page).getAttribute("data-zoom");
    if (z === level) return;
    const wantIn = level === "near" || (level === "mid" && z === "far");
    await page.locator(wantIn ? ".react-flow__controls-zoomin" : ".react-flow__controls-zoomout").click();
    await page.waitForTimeout(120);
  }
  await expect(canvas(page)).toHaveAttribute("data-zoom", level);
}
/** 손잡이를 캔버스 좌표로 dy 만큼 끈다. */
async function drag(page: Page, id: string, dy: number) {
  const b = (await grip(page, id).boundingBox())!;
  const z = await zoomOf(page);
  const at = { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  await page.mouse.move(at.x, at.y + (dy * z) / 2, { steps: 5 });
  await page.mouse.move(at.x, at.y + dy * z, { steps: 5 });
  await page.mouse.up();
  await page.waitForTimeout(150);
}
async function compute(page: Page) {
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 90_000 });
}

test.use({ viewport: { width: 1440, height: 900 } });

test("R3 · 손잡이로 결과 칸을 +110 — 세 확대에서 높이 = nodeHeight · 다른 카드 그대로 · 되돌리기 한 단계 (짝: 두 번 끌면 둘)", async ({ page }) => {
  await open(page, CORE);
  const cat = await catalog(page);
  await node(page, "optimizer").click({ position: HEAD });
  await expect(grip(page, "optimizer")).toBeVisible();
  await drag(page, "optimizer", 110);
  await expect.poll(() => slotOf(page, "optimizer")).toBeGreaterThanOrEqual(SLOT_H + 108);
  const slot = (await slotOf(page, "optimizer"))!;
  expect(slot).toBeLessThanOrEqual(SLOT_H + 112);
  for (const lv of ["far", "mid", "near"] as const) {
    await zoomTo(page, lv);
    expect(Math.abs((await hOf(page, "optimizer")) - nodeHeight("optimizer", cat, slot)), lv).toBeLessThanOrEqual(1.5);
    expect(Math.abs((await hOf(page, "estimate")) - cardHeight("estimate", cat)), `${lv} 다른 카드`).toBeLessThanOrEqual(1.5);
  }
  await zoomTo(page, "mid");
  await page.keyboard.press("Control+z");
  await expect.poll(() => slotOf(page, "optimizer")).toBeUndefined();
  await expect(undoBtn(page)).toBeDisabled();                                    // 끌기 한 번 = 한 단계
  await expect.poll(() => hOf(page, "optimizer")).toBeLessThan(cardHeight("optimizer", cat) + 1.5);
  await page.locator(".react-flow__controls-fitview").click();                   // 가까이에서 돌아오면 카드가 화면 밖일 수 있다
  await page.waitForTimeout(350);
  await node(page, "optimizer").click({ position: HEAD });
  await drag(page, "optimizer", 60);
  await drag(page, "optimizer", 60);
  await page.keyboard.press("Control+z");
  await expect(undoBtn(page)).toBeEnabled();                                     // 짝 — 두 번 끌면 두 단계
});

test("R3 · 세 배에서 멈추고 기본보다 작아지지 않는다 — 기본으로 돌아오면 문서에 쓰지 않는다", async ({ page }) => {
  await open(page, CORE);
  const cat = await catalog(page);
  await node(page, "optimizer").click({ position: HEAD });
  await drag(page, "optimizer", 900);
  await expect.poll(() => slotOf(page, "optimizer")).toBe(SLOT_H * 3);
  expect(Math.abs((await hOf(page, "optimizer")) - nodeHeight("optimizer", cat, SLOT_H * 3))).toBeLessThanOrEqual(1.5);
  await drag(page, "optimizer", -2000);
  await expect.poll(() => slotOf(page, "optimizer")).toBeUndefined();
  expect(Math.abs((await hOf(page, "optimizer")) - cardHeight("optimizer", cat))).toBeLessThanOrEqual(1.5);
});

test("R3 · 손잡이는 하나만 고른 펼친 카드에만 (짝: 여럿 · 접힘 · 멀리면 없다)", async ({ page }) => {
  await open(page, CORE);
  await expect(page.locator(".pg-node-resize")).toHaveCount(0);                 // 고르지 않으면 없다
  await node(page, "optimizer").click({ position: HEAD });
  await expect(grip(page, "optimizer")).toBeVisible();
  await node(page, "estimate").click({ position: HEAD, modifiers: ["Control"] });
  await expect(page.locator(".pg-node-resize")).toHaveCount(0);
  await node(page, "optimizer").click({ position: HEAD });
  await expect(grip(page, "optimizer")).toBeVisible();
  await zoomTo(page, "far");
  await expect(grip(page, "optimizer")).toBeHidden();
  await zoomTo(page, "mid");
  await node(page, "optimizer").locator(".pg-node-fold").click();
  await expect(page.locator(".pg-node-resize")).toHaveCount(0);
});

test("R3 · 문서에 남는다 — 다시 열면 같은 높이 · 범위 밖 값은 맞추고 불러오기 안내에 적는다", async ({ page }) => {
  const doc = { ...F, nodes: nodesOf(T8.slice(0, 3), { size: { slot_h: 9999 } }), edges: EDGES };
  doc.nodes[2] = { ...doc.nodes[2], size: { slot_h: 300 } } as typeof doc.nodes[number];
  await open(page, doc);
  const cat = await catalog(page);
  await expect(page.locator(".pg-load-problems")).toContainText("결과 칸 높이 9999");
  expect(Math.abs((await hOf(page, "estimate")) - nodeHeight("estimate", cat, 300))).toBeLessThanOrEqual(1.5);
  expect(Math.abs((await hOf(page, "optimizer")) - nodeHeight("optimizer", cat, SLOT_H * 3))).toBeLessThanOrEqual(1.5);
  await expect.poll(() => slotOf(page, "estimate")).toBe(300);
  await expect.poll(() => slotOf(page, "optimizer")).toBe(SLOT_H * 3);
  await page.reload();
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".pg-load-problems")).toHaveCount(0);                // 맞춘 값이 남아 다시 열 때는 문제 없다
  await expect.poll(() => slotOf(page, "estimate")).toBe(300);
});

test("R3 · 계산 뒤 늘려도 예전 결과가 되지 않는다 (짝: 선을 끊으면 예전 결과)", async ({ page }) => {
  test.setTimeout(150_000);
  await open(page, CORE);
  await compute(page);
  await node(page, "optimizer").click({ position: HEAD });
  await drag(page, "optimizer", 120);
  await expect.poll(() => slotOf(page, "optimizer")).toBeGreaterThan(SLOT_H);
  await page.waitForTimeout(600);                                                 // 검증 디바운스(350ms)를 넘겨 본다
  await expect(page.locator(".pg-node--stale")).toHaveCount(0);
  await expect(page.locator(".pg-summary--stale")).toHaveCount(0);
  await page.locator('.react-flow__edge[data-id="estimate.belief->optimizer.belief"]').click({ force: true });
  await page.keyboard.press("Delete");
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--stale/);
});

test("R3 · 상자 테두리 · 복제가 늘린 높이를 본다", async ({ page }) => {
  const doc = { ...CORE, groups: [{ id: "g1", label: "묶음", members: ["estimate", "optimizer"] }] };
  await open(page, doc);
  await zoomTo(page, "mid");                                                      // 상자 틀까지 맞추면 멀리(55% 미만) — 손잡이는 멀리에서 숨는다
  const frameH = async () => { const b = (await page.locator('.react-flow__node[data-id="frame:g1"]').boundingBox())!; return b.height / (await zoomOf(page)); };
  const before = await frameH();
  await node(page, "optimizer").click({ position: HEAD });
  await drag(page, "optimizer", 110);
  const slot = (await slotOf(page, "optimizer"))!;
  await expect.poll(frameH).toBeGreaterThan(before + slot - SLOT_H - 2);
  const cat = await catalog(page);
  await page.keyboard.press("Control+d");
  await expect(page.locator(".pg-node")).toHaveCount(5);
  const d = await wip(page);
  const src = d.nodes.find((x) => x.id === "optimizer")!;
  const copy = d.nodes.find((x) => !["universe", "returns", "estimate", "optimizer"].includes(x.id))!;
  expect(copy.position.y).toBeGreaterThanOrEqual(src.position.y + nodeHeight("optimizer", cat, slot));   // 복제가 늘린 카드 아래
  expect(copy.size).toEqual({ slot_h: slot });                                                          // 복제는 크기도 함께
});

test("R3 · 늘린 만큼 막대가 더 보인다 — 서버가 보낸 개수까지 (짝: 기본은 5줄 + '그림 밖')", async ({ page }) => {
  test.setTimeout(150_000);
  // 위험 균형은 여덟 종목 모두에 비중을 준다 — 서버가 막대 여덟을 보낸다(평균-분산은 양수 비중 다섯만)
  await open(page, { ...F, nodes: nodesOf(T8, {}, { model: "risk_parity" }), edges: EDGES });
  const cat = await catalog(page);
  await compute(page);
  // 그림 고정 — 가운데 확대에서도 작은 그림이 보인다(가까이에서는 이 카드가 화면 밖이다). 우클릭이 이 카드를 고른다.
  await node(page, "optimizer").click({ button: "right", position: HEAD });
  await page.locator('.pg-ctx-item[data-action="pin"]').click();
  const bars = node(page, "optimizer").locator(".pg-gl-bars li:not(.pg-gl-more)");
  await expect(node(page, "optimizer").locator(".pg-node-glance")).toBeVisible();
  await expect(bars).toHaveCount(5);
  await expect(node(page, "optimizer").locator(".pg-gl-more")).toContainText("그림 밖 3개");
  await expect(grip(page, "optimizer")).toBeVisible();
  await drag(page, "optimizer", 2000);
  await expect.poll(() => slotOf(page, "optimizer")).toBe(SLOT_H * 3);
  await expect(bars).toHaveCount(8);
  await expect(node(page, "optimizer").locator(".pg-gl-more")).toHaveCount(0);
  expect(Math.abs((await hOf(page, "optimizer")) - nodeHeight("optimizer", cat, SLOT_H * 3))).toBeLessThanOrEqual(1.5);   // 늘린 칸 안에 들어간다
});

test("R3 · 늘린 뒤 접으면 머리 줄만 — 노드에 고정 높이를 박지 않는다 (짝: 펴면 늘린 높이 그대로 · 접어도 문서의 크기는 남음)", async ({ page }) => {
  await open(page, CORE);
  const cat = await catalog(page);
  const box = async () => { const b = (await page.locator('.react-flow__node[data-id="optimizer"]').boundingBox())!; return b.height / (await zoomOf(page)); };
  await node(page, "optimizer").click({ position: HEAD });
  await drag(page, "optimizer", 110);
  const slot = (await slotOf(page, "optimizer"))!;
  expect(slot).toBeGreaterThan(SLOT_H);
  await node(page, "optimizer").locator(".pg-node-fold").click();
  await expect.poll(box).toBeLessThan(80);                                        // React Flow 노드 틀도 머리 줄만큼 — 고정 높이가 남지 않는다
  expect(await slotOf(page, "optimizer")).toBe(slot);
  await node(page, "optimizer").locator(".pg-node-fold").click();
  await expect.poll(box).toBeGreaterThan(nodeHeight("optimizer", cat, slot) - 1.5);
  expect(await box()).toBeLessThan(nodeHeight("optimizer", cat, slot) + 1.5);
});
