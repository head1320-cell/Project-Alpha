import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BU0 · 머리 줄 찾기(`/`) — 종목·화면을 한 칸에서 (스펙 2026-09-30-bu-toss-app-wide-design.md §7.2)
 * 거는 것(짝으로 항상-통과·항상-침묵을 배제):
 *  · `/` 로 찾기 칸에 초점 — 다른 입력 칸에서 친 `/` 는 가로채지 않는다(짝)
 *  · 화면 이름 → 그 화면으로 · 종목 → 서버 검색 결과 그대로(이름·코드) → `/insights?code=` 가 그 종목을 연다(다른 코드로도 — 짝)
 *  · ★빈 결과와 실패를 섞지 않는다★ 검색이 실패하면 "닿지 못했어요"(빈 결과 문구가 아니다), 빈 결과면 "맞는 … 없어요"(실패 문구가 아니다)
 *  · Esc 로 닫는다 · 라이트/다크 AA
 */

const box = (page: Page) => page.locator(".terminal-header .tx-find-input");
const opts = (page: Page) => page.locator(".tx-find-pop [role='option']");

async function open(page: Page, path = "/dashboard") {
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await expect(box(page)).toBeVisible();
}

test("`/` 로 찾기 칸에 초점이 간다 — 다른 입력 칸에서 친 `/` 는 그 칸의 글자다(짝)", async ({ page }) => {
  await open(page, "/insights");
  await page.locator("body").click({ position: { x: 600, y: 400 } });
  await page.keyboard.press("/");
  await expect(box(page)).toBeFocused();
  await expect(box(page)).toHaveValue("");                                   // `/` 글자를 넣지 않는다
  await page.keyboard.press("Escape");
  await expect(box(page)).not.toBeFocused();

  const other = page.locator(".terminal-main input[type='text'], .terminal-main input:not([type])").first();
  await other.click();
  await page.keyboard.type("a/b");
  await expect(other).toHaveValue(/a\/b/);
  await expect(box(page)).not.toBeFocused();
});

test("화면 이름으로 찾아 간다 — 고른 것은 하나 · Enter 로 이동", async ({ page }) => {
  await open(page);
  await box(page).fill("백테");
  const screen = opts(page).filter({ hasText: "백테스트" }).first();
  await expect(screen).toBeVisible();
  await expect(screen).toHaveAttribute("data-kind", "screen");
  await expect(page.locator(".tx-find-pop [aria-selected='true']")).toHaveCount(1);
  await box(page).press("Enter");
  await expect(page).toHaveURL(/\/backtest$/);
  await expect(page.locator(".tx-find-pop")).toHaveCount(0);
});

test("종목: 서버 검색 결과 그대로 — 고르면 기업 분석이 그 종목을 연다 · 다른 종목은 다른 코드로(짝)", async ({ page }) => {
  await open(page);
  const resp = page.waitForResponse((r) => r.url().includes("/api/v1/screener/stock-search") && r.url().includes("q=%EC%82%BC%EC%84%B1"));
  await box(page).fill("삼성");
  const body = (await (await resp).json()) as { items: { code: string; name: string }[] };
  expect(body.items.length).toBeGreaterThan(0);
  const stocks = page.locator(".tx-find-pop [role='option'][data-kind='stock']");
  await expect(stocks).toHaveCount(body.items.length);
  expect(await stocks.locator(".tx-find-opt-t").allInnerTexts()).toEqual(body.items.map((s) => s.name));
  for (const s of body.items) await expect(stocks.filter({ hasText: s.code })).toHaveCount(1);

  const target = body.items.find((s) => s.code === "005930") ?? body.items[0];
  const core = page.waitForRequest((r) => r.url().includes("/api/v1/screener/run-advanced")
    && (r.postData() ?? "").includes(`"${target.code}"`));
  await stocks.filter({ hasText: target.code }).click();
  await expect(page).toHaveURL(new RegExp(`/insights\\?code=${target.code}$`));
  await core;

  // ★짝★ 기본 종목(005930)이 아닌 코드로도 연다 — 늘 기본 종목을 여는 구현을 배제한다.
  const r2 = page.waitForResponse((r) => r.url().includes("/api/v1/screener/stock-search") && r.url().includes("000660"));
  await box(page).fill("000660");
  const b2 = (await (await r2).json()) as { items: { code: string; name: string }[] };
  expect(b2.items.some((s) => s.code === "000660")).toBe(true);
  const core2 = page.waitForRequest((r) => r.url().includes("/api/v1/screener/run-advanced") && (r.postData() ?? "").includes('"000660"'));
  await page.locator(".tx-find-pop [data-kind='stock']", { hasText: "000660" }).click();
  await expect(page).toHaveURL(/\/insights\?code=000660$/);
  await core2;
});

test("★실패와 빈 결과를 섞지 않는다★ 검색 실패 → '닿지 못했어요'(화면 찾기는 그대로) · 빈 결과 → '맞는 … 없어요'(짝)", async ({ page }) => {
  let mode: "fail" | "empty" = "fail";
  await page.route("**/api/v1/screener/stock-search**", (route) =>
    mode === "fail" ? route.fulfill({ status: 500, json: { detail: "테스트 실패" } }) : route.fulfill({ status: 200, json: { items: [] } }));
  await open(page);
  await box(page).fill("설정");
  const err = page.locator(".tx-find-note--err");
  await expect(err).toHaveText(/종목 검색에 닿지 못했어요/);
  await expect(err).toHaveAttribute("role", "alert");
  await expect(opts(page).filter({ hasText: "설정" })).toHaveCount(1);       // 화면 찾기는 네트워크 없이 된다
  await expect(page.locator(".tx-find-pop")).not.toContainText("맞는 종목·화면이 없어요");

  mode = "empty";
  await box(page).fill("");
  await box(page).fill("없는이름xyz");
  await expect(page.locator(".tx-find-pop .tx-find-note")).toHaveText(/맞는 종목·화면이 없어요/);
  await expect(err).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.locator(".tx-find-pop")).toHaveCount(0);
});

for (const theme of ["light", "dark"] as const) {
  test(`찾기 칸·목록 대비 AA (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    await box(page).fill("데이");
    await expect(opts(page).first()).toBeVisible();
    await expect(page.locator(".tx-find-note[role='status']")).toHaveCount(0, { timeout: 10_000 });
    const r = await page.evaluate<AuditResult>(contrastAudit(".terminal-header"));
    expect(r.checked, "브랜드·고른 줄 이름·꼬리 — 셋 이상을 쟀다").toBeGreaterThanOrEqual(3);
    expect(r.low, JSON.stringify(r.low)).toEqual([]);
  });
}
