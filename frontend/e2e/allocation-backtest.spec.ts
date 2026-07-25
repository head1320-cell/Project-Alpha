import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// Walk-forward policy backtest (roadmap 07) — drives the real backend: pick a goal (seeds a
// portfolio) → Journal → run the policy backtest → OOS equity + KPIs + honesty badges render.
test("Allocation: policy walk-forward backtest renders OOS equity + metrics + honesty badges", async ({ page }) => {
  const sink = trackErrors(page);

  // goal gate seeds holdings
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await expect(page.locator(".aas-goal").first()).toBeVisible();
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });

  // Journal hosts the Policy Backtest
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });
  const runBtn = page.locator(".as-fb-apply", { hasText: "정책 백테스트" }).first();
  await expect(runBtn).toBeVisible();
  await runBtn.click();

  // OOS results: KPI cards + equity/benchmark chart + honesty badges
  await expect(page.locator(".as-bt-kpi").first()).toBeVisible({ timeout: 30_000 });
  expect(await page.locator(".as-bt-kpi").count(), "OOS metric KPIs").toBeGreaterThan(6);
  await expect(page.locator(".as-bt-card", { hasText: "OOS 자산곡선" })).toBeVisible();
  await expect(page.getByText("OOS · look-ahead 없음")).toBeVisible();
  // per-rebalance weight table
  await expect(page.locator(".as-bt-wtbl tbody tr").first()).toBeVisible();

  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/�/); // Korean encoding intact
  expect(uniq(sink.pageErrors), "policy backtest page errors").toEqual([]);
  expect(uniq(sink.api404), "policy backtest API 404s").toEqual([]);
});
