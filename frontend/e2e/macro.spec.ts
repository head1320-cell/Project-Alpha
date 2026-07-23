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
