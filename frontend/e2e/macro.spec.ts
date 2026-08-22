import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// Macro Analysis regression — locks in the healthy state so a future regression (the
// reported "Macro tab throws an error") makes CI go red. Drives all 8 sub-tabs + US toggle.
const SUBTABS = ["Indicators", "Regime", "Valuation", "Strategies", "Recommend", "Correlations", "Timing", "Overview"];

test("Macro: all sub-tabs render with zero page/console/API errors + Korean encoding", async ({ page }) => {
  const sink = trackErrors(page);

  await page.goto("/macro", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);

  // Overview loaded: a known Korean label is visible and correctly encoded (not mojibake).
  await expect(page.getByText("국면", { exact: false }).first()).toBeVisible();
  const banner = await page.locator("body").innerText();
  expect(banner).toContain("STRESS");
  expect(banner).not.toMatch(/�/); // no replacement char (encoding corruption)

  for (const t of SUBTABS) {
    const before = sink.pageErrors.length;
    await page.locator(".mc-tab", { hasText: t }).first().click();
    await page.waitForTimeout(1800);
    expect(sink.pageErrors.slice(before), `sub-tab ${t} threw`).toHaveLength(0);
    // the clicked tab became active
    await expect(page.locator(".mc-tab.on", { hasText: t }).first()).toBeVisible();
  }

  expect(uniq(sink.api404), "macro API 404s").toEqual([]);
  expect(uniq(sink.pageErrors), "macro page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "macro console errors").toEqual([]);
});

// Hardening regression: a PARTIAL /macro/recommend payload (top/regime dropped — the shape
// real BOK/FRED data can produce when a recommendation can't be fully computed) must render
// an honest unavailable state, NOT crash the tab.
test("Macro: partial recommend payload → honest unavailable state, no crash", async ({ page }) => {
  const sink = trackErrors(page);
  await page.route("**/api/v1/macro/recommend**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ error: false, confidence: 0.2, low_conviction: true, top: null, macro_allocation: null }),
    }),
  );

  await page.goto("/macro", { waitUntil: "networkidle" });
  await page.locator(".mc-tab", { hasText: "Recommend" }).first().click();
  await page.waitForTimeout(1500);

  await expect(page.getByText(/추천 데이터가 불완전|데이터 미가용|추천 데이터 없음/).first()).toBeVisible();
  expect(uniq(sink.pageErrors), "no crash on partial recommend").toEqual([]);
});
