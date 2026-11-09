import { test, expect, type Page } from "./fixtures";
import { cardsOverflow, completedRun, contrastAudit, STUB_RUN_ID, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 두 실행 비교 화면 — 둘 겹쳐 보기 (2026-11-09 · 설계 `docs/superpowers/specs/2026-11-09-perf-grammar-other-screens-design.md`)
//  실행 A·B 는 스텁 · ★`POST /api/v1/perf/compare` 는 스텁하지 않는다★ — 진짜 서버가 맞추고 뺀 값이 화면에 온다.
//  (a) 두 선 + 차이 선 · 읽는 줄 마지막 날 · ArrowLeft · 차이 %p
//  (b) 같은 날짜 → 정렬 글 0 · B 끝 2점을 빼면 합집합 5 + "없는 날" 글 · B 날짜를 통째로 바꾸면 "시작부터"(짝)
//  (c) 해마다 차이 행 = 해 합집합 · 한쪽만 있는 해는 "주지 않았어요"
//  (d) 지표 표 차이 = 서버 rows · B 값을 지우면 "비교할 수 없어요"(0 아님)
//  (e) recharts 0 · title= 0
//  (f) 대비 라이트·다크   (g) 390 가로 넘침 0
// ═══════════════════════════════════════════════════════════════════════════════

type Full = ReturnType<typeof completedRun>["full"] & Record<string, unknown>;
type Bt = { equity_curve: number[]; equity_dates: string[]; statistics: Record<string, number | undefined> };
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const B_ID = "bt_stub_e2e_2";
const bt = (f: Full) => (f.result as { backtest: Bt }).backtest;

async function stub(page: Page, editB: (f: Full) => void = () => {}) {
  const a = completedRun();
  const aFull = clone(a.full) as Full;
  const bFull = clone(a.full) as Full;
  Object.assign(bFull, { run_id: B_ID, correlation_id: B_ID, strategy_name: "모멘텀 (E2E)" });
  bt(bFull).statistics.total_return_pct = 24.9;
  bt(bFull).statistics.max_drawdown_pct = -18.0;
  bt(bFull).equity_curve = [100, 106, 110, 115, 121];
  editB(bFull);
  const bLite = { ...a.lite, run_id: B_ID, strategy_name: "모멘텀 (E2E)" };
  await page.route("**/api/v1/backtest/runs", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [a.lite, bLite] }) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(aFull) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${B_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(bFull) }));
  return { aFull, bFull };
}
async function openCompare(page: Page, editB?: (f: Full) => void) {
  const fx = await stub(page, editB);
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/compare`, { waitUntil: "networkidle" });
  await page.locator(".brun-select").selectOption(B_ID);
  return fx;
}
const card = (p: Page) => p.locator(".brun-card").filter({ has: p.getByRole("heading", { name: /^자산곡선/ }) });

test("(a) 두 선 + 차이 선 · 읽는 줄은 마지막 날 · ArrowLeft 로 옮김 · 차이는 %p", async ({ page }) => {
  const { aFull } = await openCompare(page);
  const dates = bt(aFull).equity_dates;
  const fig = card(page).locator(".pf-cmp");
  await expect(fig).toBeVisible();
  await expect(fig.locator(".pf-line-a")).toHaveCount(1);
  await expect(fig.locator(".pf-line-b")).toHaveCount(1);
  await expect(fig.locator(".pf-diff-line")).toHaveCount(1);
  const read = fig.locator(".pf-read");
  await expect(read.locator(".pf-read-date")).toHaveText(dates[dates.length - 1]);
  await expect(read.locator(".pf-read-diff")).toContainText("%p");
  // 서버가 뺀 값: A 112/100 → 112.0 · B 121/100 → 121.0 · 차이 +9.0%p (base 100 이라 값은 그대로 · 차이는 %p)
  await expect(read.locator(".pf-read-diff")).toContainText("+9.0%p");
  await fig.locator("svg").focus();
  await page.keyboard.press("ArrowLeft");
  await expect(read.locator(".pf-read-date")).toHaveText(dates[dates.length - 2]);
  await page.keyboard.press("End");
  await expect(read.locator(".pf-read-date")).toHaveText(dates[dates.length - 1]);
  await expect(fig.locator(".pf-legend")).toContainText("차이 = B − A");
});

test("(b) 같은 날짜면 정렬 글 0 · B 끝 2점을 빼면 합집합 5 + 없는 날 글 · 날짜가 통째로 다르면 '시작부터'(짝)", async ({ page }) => {
  await openCompare(page);
  const fig = card(page).locator(".pf-cmp");
  await expect(fig).toHaveAttribute("data-alignment", "date");
  await expect(fig.locator(".pf-strip-legend-align")).toHaveCount(0);
  await expect(fig.locator(".pf-strip-legend-missing")).toHaveCount(0);
  await page.unrouteAll();
  await openCompare(page, (b) => { bt(b).equity_dates = bt(b).equity_dates.slice(0, 3); bt(b).equity_curve = bt(b).equity_curve.slice(0, 3); });
  const fig2 = card(page).locator(".pf-cmp");
  await expect(fig2).toHaveAttribute("data-alignment", "date");
  await fig2.locator("details.pf-cmp-table summary").click();
  await expect(fig2.locator(".pf-cmp-table tbody tr")).toHaveCount(5);                       // 합집합 — 순번이면 3
  await expect(fig2.locator(".pf-strip-legend-missing")).toContainText("B에 없는 날 2일");
  await page.unrouteAll();
  await openCompare(page, (b) => { bt(b).equity_dates = ["2020-01", "2020-02", "2020-03", "2020-04", "2020-05"]; });
  const fig3 = card(page).locator(".pf-cmp");
  await expect(fig3).toHaveAttribute("data-alignment", "index");
  await expect(fig3.locator(".pf-strip-legend-align")).toContainText("시작부터 5일째");
  await expect(fig3.locator(".pf-read-date")).toHaveText("5일째");
});

test("(c) 해마다 차이 행 = 해 합집합 · 한쪽만 있는 해는 '주지 않았어요' · 차이는 '비교할 수 없어요'", async ({ page }) => {
  await openCompare(page);
  const tbl = card(page).locator(".pf-year-diff");
  await expect(tbl.locator("tbody tr")).toHaveCount(1);
  await expect(tbl.locator("tbody tr").first()).toContainText("2023");
  await page.unrouteAll();
  await openCompare(page, (b) => { (b.perf as { periods: { yearly: { year: number }[] } }).periods.yearly[0].year = 2024; });
  const tbl2 = card(page).locator(".pf-year-diff");
  await expect(tbl2.locator("tbody tr")).toHaveCount(2);
  await expect(tbl2.locator("tbody tr").first()).toContainText("주지 않았어요");
  await expect(tbl2.locator("tbody tr").first()).toContainText("비교할 수 없어요");
});

test("(d) 지표 표의 차이는 서버 rows — 총수익률 +12.6%p · B 값을 지우면 '비교할 수 없어요'(0 아님)", async ({ page }) => {
  await openCompare(page);
  const delta = (label: string) => page.locator(".brun-cmp tr", { hasText: label }).first().locator("td").nth(3);
  await expect(delta("총수익률")).toHaveText("+12.6%p");
  await expect(delta("최대낙폭")).toHaveText("-3.8%p");
  await page.unrouteAll();
  await openCompare(page, (b) => { delete bt(b).statistics.sharpe_ratio; });
  await expect(delta("샤프 지수")).toHaveText("비교할 수 없어요");
  await expect(page.locator(".tx-answer")).toContainText("샤프 지수는 비교할 수 없어요 — B 에 값이 없어요");
});

test("(e) recharts 0 · 새 부품에 title= 0", async ({ page }) => {
  await openCompare(page);
  await expect(card(page).locator(".pf-cmp")).toBeVisible();
  await expect(page.locator(".recharts-wrapper, .recharts-tooltip-wrapper")).toHaveCount(0);
  await expect(page.locator(".terminal-main [title]:not(.perf-label)")).toHaveCount(0);
});

for (const t of ["light", "dark"] as const) {
  test(`(f) 대비 — ${t}: 비교 화면 AA 미달 0`, async ({ page }) => {
    await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, t);
    await openCompare(page);
    await expect(card(page).locator(".pf-cmp")).toBeVisible();
    await card(page).locator("details.pf-cmp-table summary").click();
    await page.waitForTimeout(400);
    const r = await page.evaluate<AuditResult>(contrastAudit(".terminal-main"));
    expect(r.checked).toBeGreaterThan(40);
    expect(r.low, `${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
    if (t === "dark") expect(r.bright).toEqual([]);
  });
}

test("(g) 390 — 카드 밖으로 넘치는 것 0", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openCompare(page);
  await expect(card(page).locator(".pf-cmp")).toBeVisible();
  await page.waitForTimeout(300);
  expect(await page.evaluate<string[]>(cardsOverflow(".rs .brun-card")), "390px 카드 밖").toEqual([]);
});
