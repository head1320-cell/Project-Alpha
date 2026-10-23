import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, minimapOn, type AuditResult } from "./helpers";

/**
 * CF5b · 미니맵 · 확대율 — 보조 컨트롤러
 *  · 미니맵은 ★기본으로 꺼져 있다★(사용자 결정 2026-10-22 — 켜 두면 구석의 카드를 덮어 누를 수 없었다) · 켬/끔은 이 브라우저에 남는다 · 모서리 [접기]
 *  · 미니맵 칸 = 노드 단계색 · 계산 뒤 실패는 빨강 테두리 · 막힘은 주황 · 고른 노드는 파랑(짝: 정상 노드는 테두리 없음)
 *  · 확대율 = 지금 배율(%) · 누르면 100% · 라이트/다크 AA
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const chain = (tickers: string[]) => ({
  ...F,
  nodes: [n("universe", "universe", 0, 140, { tickers }), n("returns", "returns", 320, 140),
          n("optimizer", "optimizer", 640, 140, { model: "risk_parity" }), n("corr", "corr_stress", 960, 140)],
  edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns"),
          e("returns", "returns", "corr", "returns"), e("optimizer", "weights", "corr", "weights")],
});

async function openWith(page: Page, doc: object, keepView = false) {
  await page.addInitScript(([d, keep]) => {
    try {
      if (sessionStorage.getItem("cf5b_seeded")) return;
      sessionStorage.setItem("cf5b_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      if (!keep) localStorage.removeItem("alpha_pg_view");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, [doc, keepView] as const);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
}
const mmButton = (page: Page) => page.locator('button[aria-label="미니맵"]');
/** 칸의 색 — 토큰을 실제 색으로 풀어 견준다. */
const tokenColor = (page: Page, token: string) => page.evaluate((t) => {
  const i = document.createElement("i");
  i.style.color = t;
  document.querySelector(".pg-canvas")!.appendChild(i);
  const c = getComputedStyle(i).color;
  i.remove();
  return c;
}, token);
const rectFill = (page: Page, sel: string) => page.locator(sel).first().evaluate((el) => getComputedStyle(el).fill);
const rectStroke = (page: Page, sel: string) => page.locator(sel).first().evaluate((el) => getComputedStyle(el).stroke);

test("미니맵: 넓은 화면도 기본은 꺼짐(켜 두면 구석의 카드를 덮었다) · 짝: 켜면 보이고 도구줄 단추가 눌린 상태", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openWith(page, chain(["005930", "000660"]));
  await expect(page.locator(".pg-minimap")).toHaveCount(0);
  await expect(mmButton(page)).toHaveAttribute("aria-pressed", "false");
  await mmButton(page).click();
  await expect(page.locator(".pg-minimap")).toBeVisible();
  await expect(mmButton(page)).toHaveAttribute("aria-pressed", "true");
});

test("미니맵 켬/끔은 이 브라우저에 남는다 · 모서리 [접기]도 같은 상태", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openWith(page, chain(["005930", "000660"]));
  await mmButton(page).click();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-minimap")).toBeVisible({ timeout: 30_000 });     // 켠 것이 남았다
  await page.locator(".pg-minimap-fold").click();
  await expect(page.locator(".pg-minimap")).toHaveCount(0);
  await expect(mmButton(page)).toHaveAttribute("aria-pressed", "false");
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await expect(page.locator(".pg-minimap")).toHaveCount(0);                     // [×]로 끈 것도 남았다
  await expect(mmButton(page)).toHaveAttribute("aria-pressed", "false");
});

test("미니맵 칸 = 단계색 · 계산 뒤 실패는 빨강·막힘은 주황 테두리 · 고른 노드는 파랑 (짝: 정상은 테두리 없음)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openWith(page, chain(["005930"]));
  await minimapOn(page, true);
  for (const [stage, token] of [["data", "var(--pg-st-data)"], ["build", "var(--pg-st-build)"], ["check", "var(--pg-st-check)"]] as const) {
    await expect(page.locator(`.pg-mm--stage-${stage}`).first()).toBeAttached();
    expect(await rectFill(page, `.pg-mm--stage-${stage}`), stage).toBe(await tokenColor(page, token));
  }
  await expect(page.locator(".pg-mm--failed, .pg-mm--blocked")).toHaveCount(0);   // 계산 전엔 없다
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-mm--failed")).toHaveCount(1, { timeout: 60_000 });
  await expect(page.locator(".pg-mm--blocked")).toHaveCount(2);
  expect(await rectStroke(page, ".pg-mm--failed")).toBe(await tokenColor(page, "var(--pg-fail)"));
  expect(await rectStroke(page, ".pg-mm--blocked")).toBe(await tokenColor(page, "var(--pg-assume)"));
  const okStroke = await page.locator(".react-flow__minimap-node:not(.pg-mm--failed):not(.pg-mm--blocked)").first()
    .evaluate((el) => getComputedStyle(el).stroke);
  expect(["none", "rgba(0, 0, 0, 0)", "transparent"]).toContain(okStroke);
  await page.locator('.pg-node[data-node-id="optimizer"]').click({ position: { x: 30, y: 14 } });
  await expect(page.locator(".pg-mm--picked")).toHaveCount(1);
  expect(await rectStroke(page, ".pg-mm--picked")).toBe(await tokenColor(page, "var(--pg-blue)"));
});

test("확대율: 글 = 지금 배율 · 확대하면 바뀐다(짝) · 누르면 100%", async ({ page }) => {
  await openWith(page, chain(["005930", "000660"]));
  const scale = () => page.locator(".react-flow__viewport").evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).a);
  const pct = page.locator(".pg-zoom-pct");
  await expect(pct).toHaveText(`${Math.round((await scale()) * 100)}%`);
  const before = await pct.textContent();
  await page.locator(".react-flow__controls-zoomout").click();
  await page.waitForTimeout(250);
  await expect(pct).not.toHaveText(before!);
  await expect(pct).toHaveText(`${Math.round((await scale()) * 100)}%`);
  await pct.click();
  await page.waitForTimeout(300);
  expect(Math.abs((await scale()) - 1)).toBeLessThan(0.01);
  await expect(pct).toHaveText("100%");
});

for (const scheme of ["light", "dark"] as const) {
  test(`확대율·미니맵 대비(${scheme}) AA`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openWith(page, chain(["005930", "000660"]));
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    const a = await page.evaluate<AuditResult>(contrastAudit(".react-flow__controls"));
    expect(a.checked).toBeGreaterThanOrEqual(1);
    expect(a.low, scheme).toEqual([]);
  });
}
