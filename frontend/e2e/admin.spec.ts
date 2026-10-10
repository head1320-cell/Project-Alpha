import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// Admin route smoke coverage.
//
// These three routes had NO E2E coverage at all, yet /admin/live-trading (610 lines)
// and /admin/multi-backtest (432) are among the largest files in the app. This spec
// exists so refactoring them is verified rather than hoped — it lands green BEFORE
// any of that work starts.
//
// Scope is deliberately what a smoke test can honestly guarantee: the route mounts,
// its heading renders, no uncaught page error, Korean text intact. API failures are
// REPORTED, not asserted away: these pages call live-trading / realism endpoints that
// legitimately return errors under KIS_USE_MOCK, so asserting "no 4xx" would encode a
// contract the app never promised.
//
// Selector note: unlike the rest of the app these pages are Tailwind-styled (no
// semantic .xxx-* classes), so assertions anchor on headings and text.
// ═══════════════════════════════════════════════════════════════════════════════

const ROUTES: [string, string][] = [
  ["/admin/live-trading", "Live Trading Cockpit"],
  ["/admin/multi-backtest", "Multi-Strategy 통합 백테스트"],
  ["/admin/realism", "Realism Panel"],
];

for (const [path, heading] of ROUTES) {
  test(`Admin: ${path} mounts and renders without page errors`, async ({ page }) => {
    const sink = trackErrors(page);

    await page.goto(path, { waitUntil: "domcontentloaded" });

    // The route actually mounted and rendered its own heading (not an error boundary).
    await expect(page.locator("h1").first()).toContainText(heading, { timeout: 20_000 });

    // Let client-side fetches settle so a render crash has a chance to surface.
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(1_000);

    // Still mounted after data arrived — catches "renders then throws on first payload".
    await expect(page.locator("h1").first()).toContainText(heading);

    const body = await page.locator("body").innerText();
    expect(body, "Korean text must not be mojibake").not.toMatch(/�/);
    expect(body.length, "page rendered non-trivial content").toBeGreaterThan(200);

    // Uncaught exceptions are real failures.
    expect(uniq(sink.pageErrors), `${path} uncaught page errors`).toEqual([]);

    // Backend errors are informational here — surfaced in the report, not asserted.
    const apiErrs = uniq([...sink.api404, ...sink.apiOther4xx5xx]);
    if (apiErrs.length) console.log(`[smoke] ${path} backend errors (not asserted):`, apiErrs);
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// BV7 — 실계좌 관문이 닫혀 있으면 LIVE 전환이 거절된다. ★거절을 조용히 넘기지 않는다★ — 서버 사유를 그대로 보인다.
// ═══════════════════════════════════════════════════════════════════════════════

async function pressLive(page: import("@playwright/test").Page, status: number, body: unknown) {
  await page.route("**/api/v1/live/mode", (r) =>
    r.request().method() === "POST" ? r.fulfill({ status, json: body }) : r.fulfill({ json: { mode: "SHADOW" } }));
  await page.goto("/admin/live-trading", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /Live · Real Money/ }).click();
  await page.getByRole("button", { name: "실거래 진입 (Confirmed)" }).click();
}

test("Admin: 관문이 닫혀 LIVE 가 거절되면 서버 사유를 보인다", async ({ page }) => {
  const why = "실계좌 주문은 확인된 적이 없어 꺼져 있어요.";
  await pressLive(page, 400, { detail: why });
  const alert = page.locator(".live-mode-refused");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(why);
});

test("Admin: LIVE 가 받아들여지면 거절 문구가 없다", async ({ page }) => {
  await pressLive(page, 200, { old_mode: "SHADOW", new_mode: "LIVE" });
  await page.waitForTimeout(500);
  await expect(page.locator(".live-mode-refused")).toHaveCount(0);
});
