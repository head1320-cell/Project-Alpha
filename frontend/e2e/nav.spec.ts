import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// Navigation surfaces regression — locks in that Allocation Studio (AAS, module 06)
// appears on the Landing toolset + Dashboard grid, and that the shell-level breadcrumb
// renders on every tool tab. A regression (AAS dropped, breadcrumb missing) → CI red.
// ═══════════════════════════════════════════════════════════════════════════════

test("Landing: INTEGRATED TOOLSET shows 6 modules incl. Allocation Studio", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/", { waitUntil: "networkidle" });

  expect(await page.locator(".lp-module").count(), "6 toolset columns").toBe(6);
  await expect(page.locator(".lp-module", { hasText: "Allocation Studio" })).toBeVisible();
  await expect(page.locator(".lp-section-head").getByText("01 — 06")).toBeVisible();
  // the AAS column links to /allocation
  await expect(page.locator(".lp-module", { hasText: "Allocation Studio" })).toHaveAttribute("href", "/allocation");

  expect(uniq(sink.pageErrors), "landing page errors").toEqual([]);
});

test("Dashboard: module grid shows Allocation card + a breadcrumb bar", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/dashboard", { waitUntil: "networkidle" });

  // breadcrumb (shell-level) is present and names the module
  await expect(page.locator(".tcrumb")).toBeVisible();
  await expect(page.locator(".tcrumb")).toContainText("PROJECT ALPHA");
  // AAS module card present and links to /allocation
  const aas = page.locator(".dash-mod", { hasText: "Allocation" }).first();
  await expect(aas).toBeVisible();
  await expect(aas).toHaveAttribute("href", "/allocation");
  // data-ingestion strip still present
  await expect(page.locator(".dash-mod-stat")).toBeVisible();

  expect(uniq(sink.pageErrors), "dashboard page errors").toEqual([]);
});

test("Breadcrumb renders with the correct module on each tool tab", async ({ page }) => {
  const cases: [string, string][] = [
    ["/screener", "Screener"], ["/backtest", "Backtester"], ["/macro", "Macro Analysis"],
    ["/insights", "Company Analysis"], ["/risk-tools", "Risk Analysis"], ["/allocation", "Allocation Studio"],
  ];
  for (const [path, label] of cases) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    const cur = page.locator(".tcrumb-cur").first();
    await expect(cur, `crumb on ${path}`).toBeVisible();
    await expect(cur).toContainText(label);
  }
});

// The breadcrumb must not overlap a tab's own top toolbar (Company search / Screener universe).
const intersects = (a: { x: number; y: number; width: number; height: number } | null, b: typeof a) =>
  !!a && !!b && !(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y);

test("Breadcrumb does not overlap the tab top toolbar (Company + Screener)", async ({ page }) => {
  for (const path of ["/insights", "/screener"]) {
    await page.goto(path, { waitUntil: "networkidle" });
    await page.waitForTimeout(800);
    const crumb = await page.locator(".tcrumb").boundingBox();
    const toolbar = await page.locator(".t-toolbar").first().boundingBox();
    expect(intersects(crumb, toolbar), `crumb/toolbar overlap on ${path}`).toBe(false);
  }
  // the Company 분석 button (in the toolbar) is visible/clickable, not covered
  await page.goto("/insights", { waitUntil: "networkidle" });
  await expect(page.locator(".ca-pg-go")).toBeVisible();
});

test("AAS Timing gauge value does not overlap the composite label", async ({ page }) => {
  await page.goto("/allocation/timing", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  const gaugeNum = await page.locator(".as-gauge-c b").first().boundingBox().catch(() => null);
  const label = await page.locator(".as-tm-mkt-lab").first().boundingBox().catch(() => null);
  // if the composite section rendered, the big number and the label must not intersect
  if (gaugeNum && label) expect(intersects(gaugeNum, label), "gauge value overlaps label").toBe(false);
});
