import { test, expect, type Page } from "./fixtures";
import { completedRun, contrastAudit, STUB_RUN_ID, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 백테스트 결과 화면 — 성과 그림 문법 (2026-11-09 · 설계 `docs/superpowers/specs/2026-11-09-backtest-results-perf-grammar-design.md`)
//  (a) 그림 하나 — 포트폴리오 선 · 벤치마크 회색 선 · 낙폭 물속 · 읽는 줄(마지막 날 · ArrowLeft) · 띠 범례는 라벨이 말한 만큼만
//  (b) 낙폭 단위 = 서버 perf.drawdown_pct(통계와 같은 %) — 축 글자도 그 값(화면이 ×100 하지 않는다)
//  (c) 달마다 격자 칸 수 = perf.periods.monthly · 칸 글자 = 서버 값
//  (d) 낙폭 사건 행 수 = perf.drawdowns · 회복 null 은 "아직"
//  (e) 기여도 HTML 막대 — 행 수 = contribution 있는 종목 수 · 부호 · 등락색
//  (f) 짝: perf 가 없으면 낙폭·기간별·낙폭 사건은 "주지 않았어요" 이고 곡선은 그대로
//  (g) 질문 띠 — 관문 없는 화면의 문장
//  (h) recharts 요소 0 · 새 부품에 title= 0
//  (i) 다크 AA(.terminal-main)
// ═══════════════════════════════════════════════════════════════════════════════

type Full = ReturnType<typeof completedRun>["full"] & Record<string, unknown>;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
type Perf = { drawdown_pct: number[] | null; periods: { monthly: { year: number; month: number; return_pct: number }[] };
  drawdowns: { recovery_date: string | null; days_to_recover: number | null; peak_date: string; depth_pct: number }[] };

async function openResults(page: Page, edit: (f: Full) => void = () => {}) {
  const f = clone(completedRun().full) as Full;
  edit(f);
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(f) }));
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  return f;
}
const curveCard = (p: Page) => p.locator(".brun-card").filter({ has: p.getByRole("heading", { name: /^자산곡선/ }) });
const signed = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;

test("(a) 그림 하나 — 선·벤치마크·낙폭 물속 · 읽는 줄 마지막 날 · ArrowLeft · 띠 범례는 라벨이 말한 만큼만", async ({ page }) => {
  // 기본 픽스처에는 perf_label 이 없다(기존 '미상' 짝 시험이 그걸 쓴다) — 연습용 띠는 라벨을 넣어서 본다.
  const f = await openResults(page, (x) => { x.perf_label = { kind: "backtest", data_real: false, data_reason: "mock 시세" }; });
  const bt = (f.result as { backtest: { equity_dates: string[] } }).backtest;
  const fig = curveCard(page).locator(".pf-curve");
  await expect(fig).toBeVisible();
  await expect(fig.locator(".pf-line-port")).toHaveCount(1);
  await expect(fig.locator(".pf-line-bench")).toHaveCount(1);
  await expect(fig.locator(".pf-dd-area")).toHaveCount(1);
  const read = curveCard(page).locator(".pf-read");
  await expect(read).toContainText(bt.equity_dates[bt.equity_dates.length - 1]);
  await fig.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(read).toContainText(bt.equity_dates[bt.equity_dates.length - 2]);
  await expect(curveCard(page).locator(".pf-legend")).toContainText("벤치마크 KOSPI");
  // 리밸런싱 날짜를 모르는 엔진 — 띠는 리밸런싱을 말하지 않는다(모름 ≠ 0).
  await expect(curveCard(page).locator(".pf-strip-legend")).not.toContainText("리밸런싱");
  await expect(curveCard(page).locator(".pf-strip-legend")).toContainText("합성 데이터");
  // 짝: 라벨이 없으면 "실제인지 몰라요" — 연습용이라고 단정하지 않는다.
  await page.unrouteAll();
  await openResults(page);
  await expect(curveCard(page).locator(".pf-strip-legend")).toContainText("데이터 출처 미상");
  await expect(curveCard(page).locator(".pf-strip-legend")).not.toContainText("합성 데이터");
});

test("(b) 낙폭 단위 = perf.drawdown_pct(통계와 같은 %) — 축 글자도 그 값 · 짝: 비율을 넣으면 작은 수로 보인다", async ({ page }) => {
  await openResults(page, (f) => { (f.perf as Perf).drawdown_pct = [0, -5, -14.2, -3, 0]; });
  await expect(curveCard(page).locator(".pf-dd .pf-ytick")).toHaveText("-14%");
  await page.unrouteAll();
  await openResults(page, (f) => { (f.perf as Perf).drawdown_pct = [0, -0.05, -0.142, -0.03, 0]; });
  await expect(curveCard(page).locator(".pf-dd .pf-ytick")).toHaveText("-0%");           // 화면은 받은 값을 그대로 — ×100 하지 않는다
});

test("(c) 달마다 격자 — 칸 수 = perf.periods.monthly · 칸 글자 = 서버 값 · 짝: 값을 바꾸면 칸이 바뀐다", async ({ page }) => {
  const f = await openResults(page);
  const monthly = (f.perf as Perf).periods.monthly;
  const cells = page.locator("td.pf-month[data-month]");
  await expect(cells).toHaveCount(monthly.length);
  await expect(page.locator('td.pf-month[data-month="2023-03"]')).toHaveText(signed(-1.9));
  await expect(page.locator(".rs-periods table.pf-table-years tbody tr")).toHaveCount(1);   // 표로 보기 안의 쌍둥이 표는 빼고(기간별 카드만)
  await page.unrouteAll();
  await openResults(page, (f2) => { (f2.perf as Perf).periods.monthly[2].return_pct = 7.77; });
  await expect(page.locator('td.pf-month[data-month="2023-03"]')).toHaveText("+7.8%");
});

test("(d) 주요 낙폭 구간 — 행 수 = perf.drawdowns · 날짜·깊이 · 짝: 회복 null 은 '아직'", async ({ page }) => {
  const f = await openResults(page);
  const eps = (f.perf as Perf).drawdowns;
  const rows = page.locator(".pf-dd-ep");
  await expect(rows).toHaveCount(eps.length);
  await expect(rows.first()).toContainText(eps[0].peak_date);
  await expect(rows.first()).toContainText(`${Math.abs(eps[0].depth_pct).toFixed(1)}%`);
  await expect(rows.first()).toHaveAttribute("data-recovered", "true");
  await page.unrouteAll();
  await openResults(page, (f2) => { const e = (f2.perf as Perf).drawdowns[0]; e.recovery_date = null; e.days_to_recover = null; });
  await expect(page.locator(".pf-dd-ep").first()).toHaveAttribute("data-recovered", "false");
  await expect(page.locator(".pf-dd-ep").first()).toContainText("고점 미회복");
});

test("(e) 기여도 — HTML 막대 · 행 수 = contribution 있는 종목 · 부호와 등락색 · recharts 아님", async ({ page }) => {
  const f = await openResults(page);
  const rows = (f.result as { backtest: { symbol_results: { contribution_pct?: number }[] } }).backtest.symbol_results.filter((r) => r.contribution_pct != null);
  const tr = page.locator("table.brun-attr-table tbody tr");
  await expect(tr).toHaveCount(rows.length);
  await expect(tr.first()).toHaveAttribute("data-sign", "up");
  await expect(tr.first().locator(".brun-attr-bar")).toBeVisible();
  await expect(tr.last()).toHaveAttribute("data-sign", "down");
  await expect(page.locator(".recharts-wrapper")).toHaveCount(0);
});

test("(f) 짝: perf 가 없으면 낙폭·기간별·낙폭 구간은 '미제공' 이고 곡선은 그대로(화면이 세지 않는다)", async ({ page }) => {
  await openResults(page, (f) => { (f as { perf: unknown }).perf = null; });
  await expect(curveCard(page).locator(".pf-line-port")).toHaveCount(1);
  await expect(curveCard(page).locator(".pf-dd-area")).toHaveCount(0);
  await expect(curveCard(page).locator(".pf-legend")).toContainText("낙폭 곡선 없음");
  await expect(page.locator("td.pf-month[data-month]")).toHaveCount(0);
  await expect(page.locator(".pf-dd-ep")).toHaveCount(0);
  await expect(page.locator(".terminal-main")).toContainText("미제공");
});

test("(g) 질문 띠 — 답하는 것(전달) · 답하지 않는 것은 이 화면이 재지 않는다고 말한다(관문 칩 0)", async ({ page }) => {
  await openResults(page);
  const q = page.locator(".pf-q");
  await expect(q).toContainText("답하는 것");
  await expect(q).toContainText("답하지 않는 것");
  await expect(q).toContainText("측정하지 않습니다");
  await expect(q.locator(".pf-q-gate")).toHaveCount(0);
});

test("(h) recharts 요소 0 · 새 부품에 title= 0", async ({ page }) => {
  await openResults(page);
  await expect(page.locator(".recharts-wrapper, .recharts-surface, .recharts-tooltip-wrapper")).toHaveCount(0);
  await expect(page.locator(".terminal-main [title]:not(.perf-label)")).toHaveCount(0);
});

for (const t of ["light", "dark"] as const) {
  test(`(i) 대비 — ${t}: 결과 화면 AA 미달 0`, async ({ page }) => {
    await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, t);
    await openResults(page);
    await page.locator("details.pf-table summary").click();
    await page.waitForTimeout(400);
    const r = await page.evaluate<AuditResult>(contrastAudit(".terminal-main"));
    expect(r.checked).toBeGreaterThan(60);
    expect(r.low, `${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
    if (t === "dark") expect(r.bright).toEqual([]);
  });
}
