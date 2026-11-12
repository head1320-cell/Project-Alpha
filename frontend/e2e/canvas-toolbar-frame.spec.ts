import { test, expect, type Page } from "./fixtures";

/**
 * 도구줄 × 틀 머리 (U 이어서 — U6 이 관측으로 남긴 것) — 고른 카드의 도구줄('여기까지 계산 · 갈래 · 고정')은 넓은 틀(갈래 틀·상자 틀)의
 * ★머리 단추★를 덮지 않는다. 넓은 틀의 몸통은 예전처럼 덮어도 된다(누를 것이 없다 — BS2).
 *  · 재현: 1280×720 · 고른 노드째 갈래 → 맞춰 보기(35%) — 갈래 뿌리 복제의 도구줄이 '이 갈래를 원본으로' 를 193px² 덮었다(고치기 전 빌드에서 잼).
 */
const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const CORE = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
                             n("estimate", "estimate", 660, 0), n("optimizer", "optimizer", 990, 0)],
               edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
                       e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")] };
type R = { x: number; y: number; width: number; height: number };
const overlap = (a: R, b: R) => Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));

async function branchAndFit(page: Page, w: number, h: number) {
  await page.setViewportSize({ width: w, height: h });
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("tb_seeded")) return;
      sessionStorage.setItem("tb_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, CORE);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(300);
  await page.locator('.react-flow__node[data-id="estimate"] .pg-node').click({ position: { x: 30, y: 14 } });
  await page.locator('.react-flow__node[data-id="optimizer"] .pg-node').click({ position: { x: 30, y: 14 }, modifiers: ["Control"] });
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("선택한 노드로 대안");
  await page.keyboard.press("Enter");
  await expect(page.locator(".pg-branch")).toHaveCount(1);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(500);
}
const visibleToolbars = (page: Page) => page.locator(".react-flow__node-toolbar").evaluateAll((els) => els
  .filter((t) => getComputedStyle(t).visibility !== "hidden" && t.getBoundingClientRect().width > 0)
  .map((t) => { const r = t.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; }));

for (const [w, h] of [[1280, 720], [1440, 900]] as const) {
  test(`도구줄 × 틀 머리 · ${w}×${h} — 고른 대안 뿌리 복제의 도구줄은 대안 틀 머리 단추를 덮지 않는다 (짝: 도구줄은 보인다 · 제 카드도 덮지 않는다)`, async ({ page }) => {
    await branchAndFit(page, w, h);
    const tbs = await visibleToolbars(page);
    expect(tbs, "고른 카드의 도구줄 하나가 보인다").toHaveLength(1);
    const btns = await page.locator(".pg-branch-head button").evaluateAll((els) => els.map((b) => {
      const r = b.getBoundingClientRect(); return { cls: b.className.split(" ")[0], x: r.x, y: r.y, width: r.width, height: r.height };
    }));
    expect(btns.length, "대안 머리 단추를 잰다").toBeGreaterThanOrEqual(2);
    for (const b of btns) expect(overlap(tbs[0], b), `도구줄 × ${b.cls}`).toBe(0);
    const root = (await page.locator(".react-flow__node.selected .pg-node").first().boundingBox())!;
    expect(overlap(tbs[0], root), "도구줄 × 제 카드").toBe(0);
  });
}

test("도구줄 × 틀 머리 · 짝 — 넓은 상자의 ★몸통★만 덮는 자리는 예전 자리(카드 위) 그대로 — 틀 전체를 피하지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // 상자 하나(두 열 — 넓은 틀) · 고를 카드는 아래 줄: 카드 위 자리는 상자 몸통(빈 곳)이다.
  const BOX = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930"] }), n("returns", "returns", 330, 0), n("estimate", "estimate", 0, 770)], edges: [],
                groups: [{ id: "g1", label: "그룹 하나", members: ["universe", "returns", "estimate"] }] };
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("tb_seeded")) return;
      sessionStorage.setItem("tb_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, BOX);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node")).toHaveCount(3, { timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(400);
  await page.locator('.react-flow__node[data-id="estimate"] .pg-node').click({ position: { x: 30, y: 14 } });
  await page.waitForTimeout(300);
  const [tb] = await visibleToolbars(page);
  const card = (await page.locator('.pg-node[data-node-id="estimate"]').boundingBox())!;
  const frame = (await page.locator('.pg-group[data-group-id="g1"]').boundingBox())!;
  expect(tb, "도구줄이 보인다").toBeTruthy();
  expect(tb.y + tb.height, "도구줄은 카드 위(예전 자리)").toBeLessThanOrEqual(card.y + 1);
  expect(overlap(tb, frame), "그 자리는 상자 몸통 위다(짝이 실제로 몸통을 덮는 경우를 잰다)").toBeGreaterThan(0);
});
