import { readFileSync } from "node:fs";
import { test, expect, type Page } from "@playwright/test";

/**
 * CF4c · 경유점 · 선 모양 — ★선은 노드와 노드의 관계를 보여 준다 — 길을 사람이 고를 수 있게★
 *  · 선을 두 번 누르면 그 자리에 경유점 하나(가장 가까운 구간에 끼움) · 선이 그 점을 지난다 · 두 번 눌러도 확대되지 않는다
 *  · 점을 끌면 점과 선이 따라간다 · 점을 두 번 누르거나 Delete 로 지운다(선은 지워지지 않는다) · 추가·이동·지우기 모두 되돌리기 한 번
 *  · 경유점은 문서(edges[].waypoints)에 남고 파일 왕복에 그대로 · 서버는 읽지 않는다 → 끌어도 검증 요청 0(짝: 설정을 바꾸면 검증 요청)
 *  · 선 모양(보기 메뉴 · Ctrl+K): 곡선 = C · 직각 = C 없이 꺾음 · 직선 = C 없음 · 끄는 중 선도 같은 모양 · 이 브라우저에 남는다
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string, waypoints?: { x: number; y: number }[]) =>
  ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp, ...(waypoints ? { waypoints } : {}) });
type Pt = { x: number; y: number };
type Doc = { nodes: { id: string; position: Pt; params: Record<string, unknown> }[]; edges: { id: string; waypoints?: Pt[] }[] };
// 두 카드 사이 긴 선 하나(가운데가 빈 자리) + 둘째 선.
const PAIR = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 660, 220), n("optimizer", "optimizer", 1100, 220)],
  edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns")] };
const W = "universe.universe->returns.universe";

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("cf4c_seeded")) return;
      sessionStorage.setItem("cf4c_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();          // 세 카드가 떠 있는 판 사이에 다 보이게
  await page.waitForTimeout(300);
}
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const via = async (page: Page, id = W) => (await wip(page)).edges.find((x) => x.id === id)?.waypoints ?? [];
const path = (page: Page, id = W) => page.locator(`.react-flow__edge[data-id="${id}"] path.react-flow__edge-path`);
const zoom = (page: Page) => page.locator(".react-flow__viewport").evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).a);
/** 선이 캔버스 좌표 p 를 지나는가 — 선 굵기를 넉넉히(6) 잡고 잰다. */
const passes = (page: Page, p: Pt, id = W) => path(page, id).evaluate((el, q) => {
  const g = el as SVGPathElement;
  const w = g.style.strokeWidth;
  g.style.strokeWidth = "6";
  const hit = g.isPointInStroke(new DOMPoint(q.x, q.y));
  g.style.strokeWidth = w;
  return hit;
}, p);
/** 선을 고른다 — 선 위 한 점(길이의 0.3)을 눌러서(상자 가운데는 휜 선 밖일 수 있다). */
async function pickWire(page: Page, id = W) {
  const at = await onWire(page, 0.3, id);
  await page.mouse.click(at.x, at.y);
  await expect(page.locator(`.react-flow__edge[data-id="${id}"]`)).toHaveClass(/selected/);
}
/** 선 위 한 점(길이의 t)을 화면 좌표로. */
const onWire = (page: Page, t: number, id = W) => path(page, id).evaluate((el, k) => {
  const g = el as SVGPathElement;
  const q = g.getPointAtLength(g.getTotalLength() * k);
  const m = g.getScreenCTM()!;
  return { x: q.x * m.a + m.e, y: q.y * m.d + m.f };
}, t);

test("두 번 누르기: 그 자리에 경유점 하나 · 선이 그 점을 지난다 · 확대는 그대로 · 되돌리기 한 번에 없어짐", async ({ page }) => {
  await openWith(page, PAIR);
  const z0 = await zoom(page);
  const at = await onWire(page, 0.5);
  await page.mouse.dblclick(at.x, at.y);
  await expect.poll(async () => (await via(page)).length).toBe(1);
  expect(await zoom(page), "두 번 눌러도 확대되지 않는다").toBeCloseTo(z0, 5);
  const p = (await via(page))[0];
  expect(await passes(page, p)).toBe(true);
  await expect(page.locator(`.pg-waypoint[data-edge-id="${W}"]`)).toHaveCount(1);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await via(page)).length).toBe(0);
});

test("경유점 끌기: 점과 선이 따라간다 · 놓은 자리가 문서에 · 되돌리기 한 번에 원래 자리 · 끄는 동안 검증 요청 0", async ({ page }) => {
  await openWith(page, { ...PAIR, edges: [e("universe", "universe", "returns", "universe", [{ x: 440, y: 110 }]), PAIR.edges[1]] });
  await pickWire(page);
  const dot = page.locator(`.pg-waypoint[data-edge-id="${W}"][data-i="0"]`);
  await expect(dot).toBeVisible();
  let validates = 0;
  page.on("request", (r) => { if (r.url().includes("/allocation/graph/validate")) validates++; });
  const b = (await dot.boundingBox())!;
  const z = await zoom(page);
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2 + 60, b.y + b.height / 2 + 120, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(600);
  const p = (await via(page))[0];
  expect(Math.abs(p.x - (440 + 60 / z))).toBeLessThanOrEqual(11);
  expect(Math.abs(p.y - (110 + 120 / z))).toBeLessThanOrEqual(11);
  expect(await passes(page, p)).toBe(true);
  expect(validates, "경유점은 서버가 읽지 않는다 — 끌어도 다시 검증하지 않는다").toBe(0);
  await page.keyboard.press("Control+z");
  expect(await via(page)).toEqual([{ x: 440, y: 110 }]);
  // 짝 — 구조가 바뀌면(설정) 검증 요청이 간다(세는 장치가 살아 있다).
  await page.locator('.pg-node[data-node-id="optimizer"]').click({ position: { x: 30, y: 14 } });
  await page.locator('.pg-tab[data-tab="settings"]').click();
  const before = validates;
  await page.locator(".pg-side select").first().selectOption({ index: 1 });
  await expect.poll(() => validates).toBeGreaterThan(before);
});

test("경유점 지우기: 점을 두 번 누르면 · 점에서 Delete 도 — 선은 그대로 · 되돌리기 한 번", async ({ page }) => {
  await openWith(page, { ...PAIR, edges: [e("universe", "universe", "returns", "universe", [{ x: 330, y: 0 }, { x: 330, y: 220 }]), PAIR.edges[1]] });
  const dot = (i: number) => page.locator(`.pg-waypoint[data-edge-id="${W}"][data-i="${i}"]`);
  await pickWire(page);
  await expect(dot(1)).toBeVisible();
  await dot(1).dblclick();
  await expect.poll(async () => (await via(page)).length).toBe(1);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await via(page)).length).toBe(2);
  await pickWire(page);
  await dot(0).focus();
  await page.keyboard.press("Delete");
  await expect.poll(async () => (await via(page)).map((p) => p.y)).toEqual([220]);
  expect((await wip(page)).edges.map((x) => x.id), "선은 지워지지 않는다").toContain(W);
});

test("가장 가까운 구간에 끼운다 — 점 둘 사이를 두 번 누르면 가운데 자리(끝에 붙이지 않는다)", async ({ page }) => {
  await openWith(page, { ...PAIR, edges: [e("universe", "universe", "returns", "universe", [{ x: 330, y: -150 }, { x: 550, y: 330 }]), PAIR.edges[1]] });
  // 두 점 사이 구간의 가운데 — 곡선 구간(가로로 나가 가로로 들어오는 베지어)도 현의 가운데를 지난다.
  const p0 = { x: 330, y: -150 }, p1 = { x: 550, y: 330 };
  const target = { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 };
  expect(await passes(page, target), "누를 자리가 선 위").toBe(true);
  const scr = await path(page).evaluate((el, q) => { const m = (el as SVGPathElement).getScreenCTM()!; return { x: q.x * m.a + m.e, y: q.y * m.d + m.f }; }, target);
  await page.mouse.dblclick(scr.x, scr.y);
  await expect.poll(async () => (await via(page)).length).toBe(3);
  const v = await via(page);
  expect(v[0]).toEqual(p0);
  expect(v[2]).toEqual(p1);
});

test("파일 왕복: 경유점이 내보내기 → 불러오기에 그대로", async ({ page, context }) => {
  const wp = [{ x: 330, y: -110 }, { x: 440, y: 330 }];
  await openWith(page, { ...PAIR, edges: [e("universe", "universe", "returns", "universe", wp), PAIR.edges[1]] });
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  const exported = JSON.parse(readFileSync((await (await dl).path())!, "utf-8"));
  expect(exported.edges.find((x: { id: string }) => x.id === W).waypoints).toEqual(wp);
  expect(exported.edges.find((x: { id: string }) => x.id !== W).waypoints, "경유점 없는 선은 키가 없다").toBeUndefined();
  const page2 = await context.newPage();
  await openWith(page2, PAIR);                                             // 경유점 없는 문서를 불러온 파일이 바꾼다
  await page2.locator(".pg-import-input").setInputFiles({ name: "wp.portfolio-graph.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(exported)) });
  await expect(page2.locator(".pg-file-note")).toContainText("불러왔어요");
  expect(await via(page2)).toEqual(wp);
  // 망가진 점은 버린다(지어내지 않는다) — 숫자가 아닌 점이 있으면 그 선의 경유점은 없다.
  const bad = { ...exported, edges: exported.edges.map((x: { id: string }) => (x.id === W ? { ...x, waypoints: [{ x: "a", y: 1 }] } : x)) };
  await page2.locator(".pg-import-input").setInputFiles({ name: "bad.portfolio-graph.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(bad)) });
  await expect(page2.locator(".pg-file-note")).toContainText("불러왔어요");
  expect(await via(page2)).toEqual([]);
  await page2.close();
});

async function wireShape(page: Page, shape: "curve" | "step" | "straight") {
  await page.locator(".pg-view-open").click();
  await page.locator(`.pg-view-menu [role=menuitemradio][data-wire="${shape}"]`).click();
}
const d = (page: Page, id = W) => path(page, id).getAttribute("d") as Promise<string>;

test("선 모양: 곡선 = C · 직각 = C 없이 꺾음(가로·세로만) · 직선 = C 없음 · 경유점이 있어도 같은 모양 · 새로고침 뒤에도", async ({ page }) => {
  await openWith(page, { ...PAIR, edges: [PAIR.edges[0], e("returns", "returns", "optimizer", "returns", [{ x: 990, y: 120 }])] });
  const W2 = "returns.returns->optimizer.returns";
  expect(await d(page)).toContain("C");                                     // 기본 = 곡선(지금 모습)
  await page.locator(".pg-view-open").click();
  await expect(page.locator('.pg-view-menu [data-wire="curve"]')).toHaveAttribute("aria-checked", "true");
  await page.keyboard.press("Escape");
  await wireShape(page, "straight");
  expect(await d(page)).not.toMatch(/[CQ]/);
  expect(await d(page, W2)).not.toMatch(/[CQ]/);
  expect(await passes(page, { x: 990, y: 120 }, W2)).toBe(true);
  await wireShape(page, "step");
  expect(await d(page)).not.toContain("C");
  // 직각 — 경유점이 있는 선의 꺾는 점들은 이어서 x 나 y 가 같다(가로·세로 구간만).
  const pts = ((await d(page, W2)).match(/-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?|-?\d+(?:\.\d+)? -?\d+(?:\.\d+)?/g) ?? [])
    .map((t) => t.split(/[ ,]/).map(Number));
  expect(pts.length).toBeGreaterThan(4);
  for (let i = 1; i < pts.length; i++) {
    const [a, b] = [pts[i - 1], pts[i]];
    expect(Math.abs(a[0] - b[0]) < 0.5 || Math.abs(a[1] - b[1]) < 0.5, `구간 ${i} 가로·세로`).toBe(true);
  }
  expect(await passes(page, { x: 990, y: 120 }, W2)).toBe(true);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  expect(await d(page)).not.toContain("C");                                 // 이 브라우저에 남는다
  await wireShape(page, "curve");
  expect(await d(page)).toContain("C");
});

test("끄는 중 선도 같은 모양 — 직선이면 끄는 선에 C 가 없다(짝: 곡선이면 있다)", async ({ page }) => {
  await openWith(page, PAIR);
  const dragD = async () => {
    const h = page.locator('.react-flow__node[data-id="optimizer"] .react-flow__handle.source').first();
    const b = (await h.boundingBox())!;
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x + 160, b.y + 140, { steps: 8 });
    const v = await page.locator(".pg-drag-wire path").getAttribute("d");
    await page.mouse.up();
    return v ?? "";
  };
  expect(await dragD()).toContain("C");
  await wireShape(page, "straight");
  expect(await dragD()).not.toContain("C");
});

test("명령 찾기(Ctrl+K)에 선 모양 셋", async ({ page }) => {
  await openWith(page, PAIR);
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("선 모양");
  await expect(page.locator('.pg-cmd-item[data-cmd^="wire:"]')).toHaveCount(3);
  await page.getByLabel("명령 찾기").last().fill("선 모양: 직선");
  await page.keyboard.press("Enter");
  expect(await d(page)).not.toContain("C");
});
