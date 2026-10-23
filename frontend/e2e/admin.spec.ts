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
  ["/admin/live-trading", "실거래"],
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

// ST3c — 옛 주소 /admin/realism 은 실거래 [현실성 점검] 탭으로 보낸다(북마크가 깨지지 않게).
test("Admin: /admin/realism 은 실거래의 현실성 점검 탭으로 옮겨 간다", async ({ page }) => {
  await page.goto("/admin/realism", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/admin\/live-trading\?tab=realism$/, { timeout: 20_000 });
  await expect(page.locator('.tx-tab[data-tab="realism"]')).toHaveAttribute("aria-selected", "true");
});

// BV7 의 두 테스트(관문이 닫혀 LIVE 가 거절되면 사유 · 받아들이면 문구 없음)는 BU9b 에서 관리자 로그인과 함께
// `e2e/live-trading.spec.ts` "실계좌 시트" 테스트로 옮겼다 — 새 화면은 관리자에게만 모드 단추를 그린다.
