import { test, expect, type Page } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 캔버스 성과 시트 — '크게 보기' (2026-11-09 · 설계 `docs/superpowers/specs/2026-11-09-canvas-performance-viz-design.md` §4.1 시트)
// ─────────────────────────────────────────────────────────────────────────────
//  (l) 열림·닫힘 — 단추 → 넓은 시트(dialog) · 제목은 서버 explain · Esc 로 닫히고 초점이 단추로 돌아온다
//  (m) 질문 띠 — 답하는 것(전달) · 답하지 않는 것(예측 스킬·경제적 가치)은 관문 `oos`·`economic` 의 서버 판정 그대로(상태 클래스 + 글)
//  (n) 달마다 격자 — 칸 수 = 서버 periods.monthly · 칸 글자 = 서버 값(부호) · 일부 달 표시 · 짝: 값을 바꾸면 칸이 바뀐다
//  (o) 큰 낙폭 사건 — 수 = 서버 drawdowns · 회복 못 한 사건은 그렇게 말한다(짝: 회복한 사건은 날짜·며칠)
//  (p) 리밸런싱 기록 — 행 수 = 서버 rebalances · 짝: 기록이 없으면 '없어요'
//  (q) 대비 라이트·다크 AA 미달 0 · 820px 이하에서는 바닥 시트
// ═══════════════════════════════════════════════════════════════════════════════

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();

type View = Record<string, unknown>;
type Gate = { key: string; label: string; state: string };
type RunBody = { ok: boolean; gates?: { gates: Gate[] } | null;
  nodes: Record<string, { status: string; reason: string | null; view: View | null; explain?: { title: string; headline?: { text: string } | null } | null }> };

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

async function run(page: Page): Promise<RunBody> {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = (await (await resp).json()) as RunBody;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return body;
}

async function patchRun(page: Page, fn: (body: RunBody) => void) {
  await page.unroute("**/api/v1/allocation/graph/run**");
  await page.route("**/api/v1/allocation/graph/run**", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as RunBody;
    fn(body);
    await route.fulfill({ response: res, json: body });
  });
}

/** 7번을 돌리고 자세히 탭에서 시트를 연다. */
async function openSheet(page: Page): Promise<RunBody> {
  const body = await run(page);
  await node(page, "backtest").click();
  await tab(page, "detail");
  await page.locator(".pg-side .pf-open").click();
  await expect(sheet(page)).toBeVisible();
  return body;
}

const sheet = (page: Page) => page.locator('dialog.pg-sheet--wide[data-sheet="perf"]');
const STATE_TEXT: Record<string, string> = { confirmed: "확인", assumed: "가정", partial: "절반 확인", unknown: "몰라요", skipped: "건너뜀", failed: "실패" };
const signed = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;

test("(l) 열림·닫힘 — '크게 보기' → 넓은 시트 · 제목은 서버 explain · Esc 로 닫히고 초점은 단추로", async ({ page }) => {
  await openCanvas(page);
  const body = await openSheet(page);
  const s = sheet(page);
  await expect(s).toHaveAttribute("open", "");
  await expect(s.locator(".tx-sheet-title")).toHaveText(body.nodes.backtest.explain!.title);
  await expect(s.locator(".pf-curve")).toBeVisible();
  // 넓다 — 패널(≤600)보다 넓은 그림.
  const w = (await s.boundingBox())!.width;
  expect(w, "시트 폭").toBeGreaterThan(700);
  await page.keyboard.press("Escape");
  await expect(s).not.toHaveAttribute("open", "");
  await expect(page.locator(".pg-side .pf-open")).toBeFocused();
});

test("(m) 질문 띠 — 답하는 것 · 답하지 않는 것은 관문 oos·economic 의 서버 판정 그대로", async ({ page }) => {
  await openCanvas(page);
  const body = await openSheet(page);
  const gates = body.gates?.gates ?? [];
  const q = sheet(page).locator(".pf-q");
  await expect(q).toContainText("답하는 것");
  await expect(q).toContainText("답하지 않는 것");
  for (const key of ["oos", "economic"]) {
    const g = gates.find((x) => x.key === key);
    expect(g, `관문 ${key} 가 보고서에 있어야 이 시험이 공허하지 않다`).toBeTruthy();
    const dot = q.locator(`.pf-q-gate[data-gate="${key}"]`);
    await expect(dot).toHaveClass(new RegExp(`pg-stn--${g!.state}(\\s|$)`));
    await expect(dot).toContainText(STATE_TEXT[g!.state]);
    await expect(dot).toContainText(g!.label);
  }
  // 짝 — 관문 판정이 없으면(부분 계산) 띠가 그렇게 말한다.
  await page.keyboard.press("Escape");
  await patchRun(page, (b) => { b.gates = null; });
  await openSheet(page);
  await expect(sheet(page).locator(".pf-q")).toContainText("관문 판정이 없어요");
  await expect(sheet(page).locator(".pf-q-gate")).toHaveCount(0);
});

test("(n) 달마다 격자 — 칸 수 = 서버 periods.monthly · 칸 글자 = 서버 값 · 일부 달 · 짝: 값을 바꾸면 칸이 바뀐다", async ({ page }) => {
  await openCanvas(page);
  const body = await openSheet(page);
  const monthly = (body.nodes.backtest.view!.periods as { monthly: { year: number; month: number; return_pct: number; partial: boolean }[] }).monthly;
  expect(monthly.length, "서버가 달마다 수익을 줘야 이 시험이 공허하지 않다").toBeGreaterThan(3);
  const cells = sheet(page).locator("td.pf-month[data-month]");
  await expect(cells).toHaveCount(monthly.length);
  for (const m of [monthly[0], monthly[Math.floor(monthly.length / 2)], monthly[monthly.length - 1]]) {
    const cell = sheet(page).locator(`td.pf-month[data-month="${m.year}-${String(m.month).padStart(2, "0")}"]`);
    await expect(cell).toHaveText(signed(m.return_pct));
    await expect(cell).toHaveAttribute("data-partial", String(m.partial));
    await expect(cell).toHaveAttribute("data-tone", m.return_pct >= 0 ? "up" : "down");
  }
  expect(monthly[0].partial || monthly[monthly.length - 1].partial, "양 끝 달 중 하나는 일부여야 '일부' 표시가 공허하지 않다").toBe(true);
  await expect(sheet(page).locator(".pf-months-note")).toContainText("일부");
  // 짝 — 서버 값이 바뀌면 칸이 바뀐다(화면이 제 수를 쓰지 않는다).
  await page.keyboard.press("Escape");
  const key = `${monthly[1].year}-${String(monthly[1].month).padStart(2, "0")}`;
  await patchRun(page, (b) => { (b.nodes.backtest.view!.periods as { monthly: { return_pct: number }[] }).monthly[1].return_pct = -12.3456; });
  await openSheet(page);
  await expect(sheet(page).locator(`td.pf-month[data-month="${key}"]`)).toHaveText("−12.3%");
  await expect(sheet(page).locator(`td.pf-month[data-month="${key}"]`)).toHaveAttribute("data-tone", "down");
});

test("(o) 큰 낙폭 사건 — 수 = 서버 drawdowns · 날짜·깊이·며칠 · 짝: 회복 못 한 사건은 그렇게 말한다", async ({ page }) => {
  await openCanvas(page);
  const body = await openSheet(page);
  const eps = body.nodes.backtest.view!.drawdowns as { peak_date: string; trough_date: string; recovery_date: string | null; depth_pct: number; days_to_trough: number; days_to_recover: number | null }[];
  expect(eps.length, "낙폭 사건이 있어야 이 시험이 공허하지 않다").toBeGreaterThan(0);
  const rows = sheet(page).locator(".pf-dd-ep");
  await expect(rows).toHaveCount(eps.length);
  const e0 = eps[0];
  await expect(rows.first()).toContainText(e0.peak_date);
  await expect(rows.first()).toContainText(e0.trough_date);
  await expect(rows.first()).toContainText(`${Math.abs(e0.depth_pct).toFixed(1)}%`);
  await expect(rows.first()).toContainText(`${e0.days_to_trough}일`);
  if (e0.recovery_date) {
    await expect(rows.first()).toHaveAttribute("data-recovered", "true");
    await expect(rows.first()).toContainText(e0.recovery_date);
    await expect(rows.first()).toContainText(`${e0.days_to_recover}일`);
  }
  await page.keyboard.press("Escape");
  await patchRun(page, (b) => { const d = (b.nodes.backtest.view!.drawdowns as { recovery_date: string | null; days_to_recover: number | null }[])[0]; d.recovery_date = null; d.days_to_recover = null; });
  await openSheet(page);
  await expect(sheet(page).locator(".pf-dd-ep").first()).toHaveAttribute("data-recovered", "false");
  await expect(sheet(page).locator(".pf-dd-ep").first()).toContainText("아직 고점을 되찾지 못했어요");
});

test("(p) 리밸런싱 기록 — 행 수 = 서버 rebalances · 날짜·회전율 · 짝: 기록이 없으면 '없어요'", async ({ page }) => {
  await openCanvas(page);
  const body = await openSheet(page);
  const rebs = body.nodes.backtest.view!.rebalances as { date: string; turnover_pct: number }[];
  expect(rebs.length).toBeGreaterThan(0);
  const rows = sheet(page).locator("table.pf-rebal-table tbody tr");
  await expect(rows).toHaveCount(rebs.length);
  await expect(rows.first()).toContainText(rebs[0].date.slice(0, 10));
  await expect(rows.first()).toContainText(`${rebs[0].turnover_pct.toFixed(1)}%`);
  await page.keyboard.press("Escape");
  await patchRun(page, (b) => { b.nodes.backtest.view!.rebalances = []; b.nodes.backtest.view!.n_rebalances = 0; });
  await openSheet(page);
  await expect(sheet(page).locator("table.pf-rebal-table")).toHaveCount(0);
  await expect(sheet(page).locator(".pf-rebal-none")).toContainText("리밸런싱 날짜 기록이 없어요");
});

for (const scheme of ["light", "dark"] as const) {
  test(`(q) 대비: ${scheme} — 시트 AA 미달 0${scheme === "dark" ? " · 밝은 배경 0" : ""}`, async ({ page }) => {
    await openCanvas(page);
    await run(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await node(page, "backtest").click();
    await tab(page, "detail");
    await page.locator(".pg-side .pf-open").click();
    await expect(sheet(page).locator(".pf-curve")).toBeVisible();
    await page.waitForTimeout(300);
    const audit = await page.evaluate<AuditResult>(contrastAudit('dialog.pg-sheet--wide[data-sheet="perf"]'));
    expect(audit.checked, "검사한 텍스트 노드 수").toBeGreaterThan(80);
    expect(audit.low, `${scheme} AA 미달`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}

test("(q) 820px 이하 — 시트는 바닥에서 올라오고 화면 폭을 다 쓴다", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await openCanvas(page);
  await run(page);
  await node(page, "backtest").click();
  await page.locator('.pg-tab[data-tab="detail"]').click();
  await page.locator(".pg-side .pf-open").click();
  await expect(sheet(page)).toBeVisible();
  // 올라오는 모션(220ms)이 끝난 자리를 잰다 — 바닥에 붙고(소수 px 반올림 허용) 화면 폭을 다 쓴다.
  await expect.poll(async () => { const b = (await sheet(page).boundingBox())!; return Math.abs(b.y + b.height - 900); }, { timeout: 5_000 }).toBeLessThanOrEqual(1);
  const box = (await sheet(page).boundingBox())!;
  expect(Math.round(box.x)).toBe(0);
  expect(Math.round(box.width)).toBe(800);
  await expect(sheet(page).locator(".pf-curve")).toBeVisible();
});
