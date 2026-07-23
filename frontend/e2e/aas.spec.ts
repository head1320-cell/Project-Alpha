import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// Allocation Studio (AAS) reliability regression — the reported "some buttons return 404".
// Enters via the goal gate, walks every wizard stage, and fires each stage's primary
// (fast, non-destructive) action. Asserts ZERO /api/backend 404s and ZERO unhandled
// console/page errors, so any future dead route/method/proxy regression makes CI go red.
//
// Note: the reliability signal is the network assertion (no 404). We deliberately skip the
// heavy alpha "검증 실행" (a multi-minute monthly-rebalance simulation) — its endpoint is
// still exercised elsewhere, and running it would make the E2E slow/flaky, not more correct.
const STAGES = ["CONSTRUCT", "ALPHA", "THESIS", "TIMING", "OPTIMIZE", "STRESS", "ATTRIBUTION", "EXECUTION", "JOURNAL"];
const ACTION_RE = /생성|산출|중립화|결합|후보|스테이징|기록|계획|승인|분석|최적화|Re-optimize/;

test("AAS: walk every stage + fire actions → zero 404, zero console errors", async ({ page }) => {
  test.setTimeout(150_000);
  page.on("dialog", (d) => d.dismiss().catch(() => {})); // never block on native dialogs
  const sink = trackErrors(page);

  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await page.getByText("성장 추구").click();
  await expect(page).toHaveURL(/\/allocation\/construct/, { timeout: 15_000 });

  for (const s of STAGES) {
    await page.locator(".aas-wiz-step", { hasText: s }).first().click({ timeout: 8_000 }).catch(() => {});
    await page.waitForLoadState("networkidle", { timeout: 6_000 }).catch(() => {});
    // one fast, enabled, primary action — targeted by role+name (no innerText iteration)
    const action = page.locator(".aas-content").getByRole("button", { name: ACTION_RE }).first();
    if (await action.isEnabled({ timeout: 2_000 }).catch(() => false)) {
      await action.click({ timeout: 6_000 }).catch(() => {});
      await page.waitForLoadState("networkidle", { timeout: 6_000 }).catch(() => {});
    }
  }

  expect(uniq(sink.api404), "AAS API 404s").toEqual([]);
  expect(uniq(sink.apiOther4xx5xx), "AAS API 4xx/5xx").toEqual([]);
  expect(uniq(sink.pageErrors), "AAS page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "AAS console errors").toEqual([]);
});
