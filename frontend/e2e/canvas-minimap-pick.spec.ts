import { test, expect, type Page } from "@playwright/test";

/**
 * CF 3부 U3 · 미니맵 눌러 고르기 (스펙 §8.4 — 관례로 정해 승인: 누른 카드를 고르고 확대 그대로 떠 있는 판 사이 가운데로)
 *  · 미니맵 칸(rect)의 x·y 는 노드의 캔버스 자리 — 그것으로 칸을 찾는다.
 *  · 짝: 미니맵을 끌면 화면만 옮겨지고 고름은 그대로 · 빈 곳을 누르면 고름이 바뀌지 않는다 · 찾기로 먼 노드에 가도 확대 그대로(같은 원인).
 */
const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
// a·b 는 묶음 상자 하나(상자 틀은 미니맵에 칸이 없다) · z 는 멀리(1배에서는 화면 밖).
const DOC = { ...F, nodes: [n("a", "universe", 0, 0, { tickers: ["005930"] }), n("b", "returns", 330, 0), n("z", "estimate", 3300, 1320)], edges: [],
              groups: [{ id: "g1", label: "묶음 하나", members: ["a", "b"] }] };

async function openWith(page: Page, doc: object) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("u3_seeded")) return;
      sessionStorage.setItem("u3_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      localStorage.setItem("alpha_pg_view", JSON.stringify({ minimap: true }));
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node")).toHaveCount(3, { timeout: 30_000 });
  await expect(page.locator(".pg-minimap")).toBeVisible();
  await page.waitForTimeout(500);
}
const cell = (page: Page, x: number, y: number) => page.locator(`.pg-minimap rect.react-flow__minimap-node[x="${x}"][y="${y}"]`);
const vp = (page: Page) => page.locator(".react-flow__viewport").evaluate((el) => {
  const m = new DOMMatrixReadOnly(getComputedStyle(el).transform);
  return { x: m.e, y: m.f, z: m.a };
});
const picked = (page: Page) => page.locator(".react-flow__node.selected").evaluateAll((els) => els.map((e) => e.getAttribute("data-id")));

test("U3 · 미니맵 칸을 누르면 그 카드를 고르고 판 사이 가운데로 — 확대 그대로 (짝: 미니맵을 끌면 화면만 옮겨지고 고름 그대로 · 빈 곳 누름은 고름을 바꾸지 않음)", async ({ page }) => {
  await openWith(page, DOC);
  await page.locator(".pg-zoom-pct").click();                                 // 100% — z 는 화면 밖
  await page.waitForTimeout(500);
  const before = await vp(page);
  expect(before.z).toBeCloseTo(1, 2);
  await cell(page, 3300, 1320).click();
  await expect(page.locator('.react-flow__node[data-id="z"]')).toHaveClass(/selected/);
  await page.waitForTimeout(500);                                             // 옮기기 250ms
  const after = await vp(page);
  expect(after.z, "확대 그대로").toBeCloseTo(before.z, 3);
  const box = (await page.locator('.pg-node[data-node-id="z"]').boundingBox())!;
  const r = await page.evaluate(() => {
    const c = document.querySelector(".react-flow")!.getBoundingClientRect();
    const pal = document.querySelector(".pg-palette")!.getBoundingClientRect(), side = document.querySelector(".pg-side")!.getBoundingClientRect();
    return { mid: (pal.right + side.left) / 2, cy: c.top + c.height / 2, left: pal.right, right: side.left };
  });
  // focusNode 와 같은 자리 — 판 사이 가운데(판 바깥 여백까지 같은 식이라 ±16 안)
  expect(Math.abs(box.x + box.width / 2 - r.mid), `카드 가운데 x ${box.x + box.width / 2} · 판 사이 가운데 ${r.mid}`).toBeLessThanOrEqual(16);
  expect(Math.abs(box.y + box.height / 2 - r.cy), `카드 가운데 y ${box.y + box.height / 2} · 캔버스 가운데 ${r.cy}`).toBeLessThanOrEqual(16);
  await expect(page.locator(".pg-sr-live")).toHaveText(/노드를 골랐어요/);

  // 짝 — 미니맵을 끌면 화면만 옮겨진다(고름 그대로)
  const mm = (await page.locator(".pg-minimap svg").boundingBox())!;
  const p = { x: mm.x + 12, y: mm.y + mm.height - 10 };
  const v0 = await vp(page);
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x + 30, p.y - 20, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  const v1 = await vp(page);
  expect(Math.abs(v1.x - v0.x) + Math.abs(v1.y - v0.y), "미니맵 끌기는 화면을 옮긴다").toBeGreaterThan(20);
  expect(await picked(page)).toEqual(["z"]);

  // 짝 — 미니맵 빈 곳(칸이 없는 곳)을 누르면 고름이 바뀌지 않는다. 상자 틀은 미니맵에 칸이 없다(그려지는 칸은 카드 셋뿐).
  await expect(page.locator(".pg-minimap rect.react-flow__minimap-node")).toHaveCount(3);
  const free = await page.evaluate(() => {
    const r = document.querySelector(".pg-minimap svg")!.getBoundingClientRect();
    for (let y = r.top + 6; y < r.bottom - 6; y += 4) for (let x = r.left + 6; x < r.right - 6; x += 4) {
      const el = document.elementFromPoint(x, y);
      if (el?.closest(".pg-minimap") && !el.classList.contains("react-flow__minimap-node")) return { x, y };
    }
    return null;
  });
  expect(free).not.toBeNull();
  await page.mouse.click(free!.x, free!.y);
  await page.waitForTimeout(300);
  expect(await picked(page), "빈 곳 누름은 고름을 바꾸지 않는다").toEqual(["z"]);
});

test("U3 · 짝 — 찾기(Ctrl+F)로 먼 노드에 가도 확대 그대로 (같은 원인: 고르기 효과가 옮기는 도중의 화면을 재고 또 옮겨 확대가 중간에서 멈췄다)", async ({ page }) => {
  await openWith(page, DOC);
  await page.locator(".pg-zoom-pct").click();
  await page.waitForTimeout(500);
  const before = await vp(page);
  const label = ((await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json()).nodes as { type: string; plain_label: string }[])
    .find((c) => c.type === "estimate")!.plain_label;
  await page.locator(".react-flow__pane").click({ position: { x: 360, y: 20 } });
  await page.keyboard.press("Control+f");
  await page.locator(".pg-find input").fill(label);
  await expect(page.locator('.pg-find-item[data-node-id="z"]')).toBeVisible();
  await page.locator(".pg-find input").press("Enter");
  await expect(page.locator('.react-flow__node[data-id="z"]')).toHaveClass(/selected/);
  await page.waitForTimeout(600);
  expect((await vp(page)).z, "확대 그대로").toBeCloseTo(before.z, 3);
  await expect(page.locator('.pg-node[data-node-id="z"]')).toBeInViewport();
});
