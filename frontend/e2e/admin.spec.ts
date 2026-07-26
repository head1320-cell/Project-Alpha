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
