import { test, expect, type Page } from "@playwright/test";
import { ALIGN_ITEMS, alignRects, snapGroup, snapToGuides, type Rect } from "../src/widgets/portfolio-graph/guides";

/**
 * CF 3부 U2 · 정렬 더하기 (스펙 §8.4 — 관례로 정해 승인: 오른쪽·세로 가운데·아래 맞춤 + 여럿 끌 때 묶음 테두리 정렬선)
 *  · 규칙(브라우저 없이): `alignRects` 셋 · `snapGroup`(묶음 테두리 → `snapToGuides`).
 *  · 화면: 막대 정렬 메뉴 여덟(둘이면 간격 없이 여섯) · 맞춘 뒤 되돌리기 한 번 · 둘을 끌어 셋째에 붙음 + 선 · 놓으면 선 없음 · 서로 간격 그대로.
 */
type Doc = { nodes: { id: string; position: { x: number; y: number } }[] };
const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const mod = process.platform === "darwin" ? "Meta" : "Control";
// 서로 맞지 않는 자리 셋(x 는 11 의 배수가 아니다). 셋 다 처음 화면(오른쪽 창 왼쪽)에 보인다 — canvas-layout 의 LOOSE 와 같다.
const LOOSE = { ...F, nodes: [n("a", "universe", 320, 0, { tickers: ["005930"] }), n("b", "returns", 880, 440), n("c", "estimate", 1160, 160)], edges: [] };

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("u2_seeded")) return;
      sessionStorage.setItem("u2_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
}
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const pos = async (page: Page, id: string) => (await wip(page)).nodes.find((x) => x.id === id)!.position;
const card = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"]`);
const HEAD = { x: 30, y: 14 };
async function pick(page: Page, ids: string[]) {
  await page.locator(".react-flow__pane").click({ position: { x: 350, y: 20 } });
  await card(page, ids[0]).locator(".pg-node").click({ position: HEAD });
  for (const id of ids.slice(1)) await card(page, id).locator(".pg-node").click({ position: HEAD, modifiers: [mod] });
  await expect(page.locator(".pg-selbar-n")).toHaveText(`${ids.length}개 골랐어요`);
}
async function align(page: Page, label: string) {
  await page.locator(".pg-align-open").click();
  await page.getByRole("menuitem", { name: label, exact: true }).click();
  await page.waitForTimeout(200);
}
const boxes = async (page: Page, ids: string[]) => Promise.all(ids.map(async (id) => (await card(page, id).boundingBox())!));
const zoomOf = (page: Page) => page.locator(".react-flow__viewport").evaluate((el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a);

// ── 규칙 ──────────────────────────────────────────────────────────────────────
const R = (id: string, x: number, y: number, w: number, h: number) => ({ id, x, y, w, h });
const THREE = [R("a", 0, 0, 240, 100), R("b", 300, 50, 240, 300), R("c", 700, 400, 240, 200)];

test("U2 규칙 · 오른쪽·세로 가운데·아래 — 다른 축은 그대로 (짝: 하나면 빈 결과 · 메뉴 순서 · 왼쪽·위는 예전 값)", () => {
  expect(ALIGN_ITEMS.map((i) => i.kind)).toEqual(["left", "center", "right", "top", "middle", "bottom", "hspace", "vspace"]);
  expect(ALIGN_ITEMS.find((i) => i.kind === "middle")!.label).toBe("세로 가운데 맞추기");
  const at = (kind: Parameters<typeof alignRects>[1]) => Object.fromEntries(alignRects(THREE, kind));
  expect(at("right")).toEqual({ a: { x: 700, y: 0 }, b: { x: 700, y: 50 }, c: { x: 700, y: 400 } });       // 오른쪽 끝 940
  expect(at("bottom")).toEqual({ a: { x: 0, y: 500 }, b: { x: 300, y: 300 }, c: { x: 700, y: 400 } });    // 아래 끝 600
  expect(at("middle")).toEqual({ a: { x: 0, y: 250 }, b: { x: 300, y: 150 }, c: { x: 700, y: 200 } });   // 가운데 300
  expect(at("left")).toEqual({ a: { x: 0, y: 0 }, b: { x: 0, y: 50 }, c: { x: 0, y: 400 } });
  expect(at("top")).toEqual({ a: { x: 0, y: 0 }, b: { x: 300, y: 0 }, c: { x: 700, y: 0 } });
  for (const k of ["right", "middle", "bottom"] as const) expect(alignRects([THREE[0]], k).size, `${k} — 하나면 아무것도 옮기지 않는다`).toBe(0);
});

test("U2 규칙 · snapGroup — 묶음 테두리로 붙는다(둘째 카드의 가장자리로도) · 하나면 snapToGuides 와 같다 (짝: 문턱 밖이면 0 · 빈 묶음 0)", () => {
  const m: Rect[] = [{ x: 100, y: 100, w: 240, h: 100 }, { x: 400, y: 250, w: 240, h: 100 }];   // 묶음 x 100..640 · y 100..350
  // 아래 끝(둘째 카드 몫 350)이 다른 카드 위(353)에 3 차이 → dy +3 · 가로는 맞는 곳이 없다
  expect(snapGroup(m, [{ x: 0, y: 353, w: 240, h: 100 }], 6)).toMatchObject({ dx: 0, dy: 3 });
  // 오른쪽 끝(둘째 카드 몫 640)이 다른 카드 왼쪽(643)에 → dx +3
  expect(snapGroup(m, [{ x: 643, y: 900, w: 240, h: 100 }], 6)).toMatchObject({ dx: 3, dy: 0 });
  const g = snapGroup(m, [{ x: 0, y: 353, w: 240, h: 100 }], 6);
  expect(g.guides.some((x) => x.axis === "y" && x.at === 353)).toBe(true);
  // 하나면 snapToGuides 와 같은 자리
  const one: Rect = { x: 98, y: 10, w: 240, h: 100 }, others: Rect[] = [{ x: 100, y: 400, w: 240, h: 80 }];
  const s = snapToGuides(one, others, 6), sg = snapGroup([one], others, 6);
  expect({ x: one.x + sg.dx, y: one.y + sg.dy }).toEqual({ x: s.x, y: s.y });
  expect(sg.dx).toBe(2);
  // 짝 — 문턱 밖이면 그대로 · 빈 묶음
  expect(snapGroup(m, [{ x: 0, y: 380, w: 240, h: 100 }], 6)).toMatchObject({ dx: 0, dy: 0, guides: [] });
  expect(snapGroup([], [{ x: 0, y: 0, w: 1, h: 1 }], 6)).toEqual({ dx: 0, dy: 0, guides: [] });
});

// ── 화면 ──────────────────────────────────────────────────────────────────────
test("U2 · 오른쪽·아래·세로 가운데 맞추기 — 메뉴 여덟 · 맞춘 뒤 되돌리기 한 번에 원래 자리 (짝: 둘이면 간격 없이 여섯)", async ({ page }) => {
  await openWith(page, LOOSE);
  const ids = ["a", "b", "c"];
  const before = await Promise.all(ids.map((id) => pos(page, id)));
  await pick(page, ids);
  await page.locator(".pg-align-open").click();
  await expect(page.locator(".pg-align-menu [role=menuitem]")).toHaveText(ALIGN_ITEMS.map((i) => i.label));
  await page.keyboard.press("Escape");

  await align(page, "오른쪽 맞추기");
  let r = await boxes(page, ids);
  expect(Math.max(...r.map((b) => b.x + b.width)) - Math.min(...r.map((b) => b.x + b.width)), "오른쪽 끝이 같다").toBeLessThanOrEqual(2);
  expect((await Promise.all(ids.map((id) => pos(page, id)))).map((p) => p.y), "세로는 그대로").toEqual(before.map((p) => p.y));
  await page.keyboard.press("Control+z");
  expect(await Promise.all(ids.map((id) => pos(page, id)))).toEqual(before);

  await pick(page, ids);
  await align(page, "아래 맞추기");
  r = await boxes(page, ids);
  expect(Math.max(...r.map((b) => b.y + b.height)) - Math.min(...r.map((b) => b.y + b.height)), "아래 끝이 같다").toBeLessThanOrEqual(2);
  expect((await Promise.all(ids.map((id) => pos(page, id)))).map((p) => p.x), "가로는 그대로").toEqual(before.map((p) => p.x));
  await page.keyboard.press("Control+z");
  expect(await Promise.all(ids.map((id) => pos(page, id)))).toEqual(before);

  await pick(page, ids);
  await align(page, "세로 가운데 맞추기");
  r = await boxes(page, ids);
  const mids = r.map((b) => b.y + b.height / 2);
  expect(Math.max(...mids) - Math.min(...mids), "세로 가운데가 같다").toBeLessThanOrEqual(2);
  await page.keyboard.press("Control+z");
  expect(await Promise.all(ids.map((id) => pos(page, id)))).toEqual(before);

  await pick(page, ["a", "b"]);
  await page.locator(".pg-align-open").click();
  await expect(page.locator(".pg-align-menu [role=menuitem]")).toHaveCount(6);
  await expect(page.locator(".pg-align-menu")).not.toContainText("간격");
});

/** 고른 둘(a·b) 중 a 의 머리를 잡고 화면 (0, dyScreen) 만큼 끈다. `during` 은 놓기 전에 부른다. */
async function dragPicked(page: Page, dyScreen: number, during?: () => Promise<void>) {
  const b = (await card(page, "a").boundingBox())!;
  const p = { x: b.x + HEAD.x, y: b.y + HEAD.y };
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x, p.y + 4, { steps: 2 });
  await page.mouse.move(p.x, p.y + dyScreen / 2, { steps: 6 });
  await page.mouse.move(p.x, p.y + dyScreen, { steps: 6 });
  await page.waitForTimeout(120);
  if (during) await during();
  await page.mouse.up();
  await page.waitForTimeout(200);
}

test("U2 · 여럿 끌기 정렬선 — 둘을 끌어 묶음 위가 셋째 위 3px 안이면 붙고 선이 보인다 · 놓으면 선이 사라진다 (짝: 둘 사이 간격 그대로 · 멀면 붙지 않고 선 없음)", async ({ page }) => {
  await openWith(page, LOOSE);
  await pick(page, ["a", "b"]);
  const z = await zoomOf(page);
  const c = await pos(page, "c");                                             // c 위 = 160
  // 묶음 위(a 의 y 0)를 c 위보다 3 아래로 — 끄는 동안 격자(11)로 165 근처가 되고 문턱(6/z + 5.5) 안이라 160 에 붙어야 한다
  await dragPicked(page, (c.y + 3) * z, async () => {
    const ys = await page.locator('.pg-guide[data-axis="y"]').evaluateAll((els) => els.map((el) => Number(el.getAttribute("y1"))));
    expect(ys, "끄는 동안 c 위(160)에 가로 선").toContain(160);
  });
  await expect(page.locator(".pg-guide")).toHaveCount(0);
  const a1 = await pos(page, "a"), b1 = await pos(page, "b");
  expect(a1.y, "묶음 위가 c 위에 붙었다").toBe(160);
  expect(b1.y - a1.y, "둘 사이 간격 그대로").toBe(440);
  expect(b1.x - a1.x, "가로 간격도 그대로").toBe(560);
  // 짝 — 되돌리고, 어떤 가장자리·가운데와도 30 넘게 떨어지는 곳으로 끌면 붙지 않고 선도 없다(격자 이동만)
  await page.keyboard.press("Control+z");
  expect((await pos(page, "a")).y).toBe(0);
  await pick(page, ["a", "b"]);
  const anchorsOf = (b: { y: number; height: number }) => [b.y, b.y + b.height / 2, b.y + b.height];
  const [ba, bb, bc] = await boxes(page, ["a", "b", "c"]);
  const theirs = anchorsOf(bc);
  let dy = 0;
  for (let t = 40; t < 600; t += 11) {                                        // 화면 px 이 아닌 캔버스 단위로 찾는다
    const top = ba.y + t * z, bottom = bb.y + bb.height + t * z, mid = (top + bottom) / 2;
    if ([top, mid, bottom].every((m) => theirs.every((o) => Math.abs(o - m) > 30 * z))) { dy = t; break; }
  }
  expect(dy, "붙지 않을 거리를 찾았다").toBeGreaterThan(0);
  await dragPicked(page, dy * z, async () => { await expect(page.locator('.pg-guide[data-axis="y"]')).toHaveCount(0); });
  const a2 = await pos(page, "a"), b2 = await pos(page, "b");
  expect(a2.y % 11, "격자 이동만").toBe(0);
  expect(b2.y - a2.y, "둘 사이 간격 그대로").toBe(440);
});
