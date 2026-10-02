import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BU1 · 홈 `/dashboard` — 답 한 문장 + 근거 칩 (계획 "BU1 상세" · ADR-003 §2.6 답 문장 = 서버 값)
 * 거는 것(짝으로 항상-통과·항상-침묵을 배제):
 *  · 답 문장은 서버 `recommended_mode` 의 번역이다 — 응답을 바꾸면 문장이 바뀐다 · 모르는 값이면 판단 없이 잰 값만
 *  · 숫자(스트레스·국면·확률)는 응답 그대로 · 확률이 없으면 "확률 몰라요"(0% 아님) · 미국 국면이 없으면 줄을 빼지 않고 "몰라요"
 *  · 연습용 칩은 `connection-status` 로만 — mock 이면 있고, 실데이터면 없다 · 확인 실패면 "몰라요" 칩
 *  · ★실패와 빈 결과를 섞지 않는다★ 국면·점수 실패는 alert + 다시 시도 · 빈 점수는 빈 문구(alert 아님)
 *  · 점수 행은 서버 순서 그대로 · 누르면 새로고침 없이 `/insights?code=`
 *  · 적재 행 수는 서버 값 · 실패면 "몰라요"(0 아님)
 *  · 번호 없는 모듈 줄 6 · 라이트/다크 AA · 390 에서 가로 스크롤 없음
 */

const MODE: Record<string, string> = { NORMAL: "보통", CAUTIOUS: "조심", DEFENSIVE: "방어" };
const KO: Record<string, string> = { Goldilocks: "골디락스", Reflation: "리플레이션", Stagflation: "스태그플레이션", Disinflation: "디스인플레이션" };
type Regime = { regime: string; recommended_mode: string; stress_score: number; regime_probs?: Record<string, number>;
  markets?: { us?: { regime: string; regime_probs?: Record<string, number> } } };
type Item = { stock_code: string; corp_name: string; current_price: number };

const pct0 = (p: number) => `${(p * 100).toLocaleString("ko-KR", { maximumFractionDigits: 0 })}%`;
const answer = (p: Page) => p.locator(".home-macro .tx-answer-s");
const fig = (p: Page, label: string) => p.locator(".home-macro .tx-fig", { has: p.locator("dt", { hasText: label }) }).locator("dd");

/** 국면 응답을 고쳐서 돌려준다 — 받은 원본을 그대로 쓰고 일부만 바꾼다(지어낸 응답이 아니라 서버 응답의 변형). */
async function patchRegime(page: Page, edit: (b: Regime) => void) {
  await page.route("**/api/v1/macro/regime", async (route: Route) => {
    const res = await route.fetch();
    const b = (await res.json()) as Regime;
    edit(b);
    await route.fulfill({ response: res, json: b });
  });
}
async function open(page: Page) {
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".home-macro")).toBeVisible({ timeout: 20_000 });
}

test("답 문장 = 서버 recommended_mode 의 번역 — 응답을 DEFENSIVE 로 바꾸면 '방어'(짝) · 모르는 값이면 잰 값만", async ({ page }) => {
  const seen = page.waitForResponse((r) => r.url().endsWith("/api/v1/macro/regime"));
  await open(page);
  const body = (await (await seen).json()) as Regime;
  await expect(answer(page)).toHaveText(`지금 경제 흐름은 ‘${MODE[body.recommended_mode]}’ 단계예요`);

  await patchRegime(page, (b) => { b.recommended_mode = "DEFENSIVE"; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(answer(page)).toHaveText("지금 경제 흐름은 ‘방어’ 단계예요");

  await page.unroute("**/api/v1/macro/regime");
  await patchRegime(page, (b) => { b.recommended_mode = "SOMETHING_NEW"; b.stress_score = 37.6; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(answer(page)).toHaveText("지금 시장 스트레스는 38/100이에요");     // 판단을 지어내지 않는다
});

test("숫자는 응답 그대로 — 확률이 없으면 '확률 몰라요'(0% 아님) · 미국 국면이 없으면 줄은 남고 '몰라요'(짝)", async ({ page }) => {
  const seen = page.waitForResponse((r) => r.url().endsWith("/api/v1/macro/regime"));
  await open(page);
  const b = (await (await seen).json()) as Regime;
  await expect(fig(page, "시장 스트레스")).toHaveText(`${Math.round(b.stress_score)}/100`);
  await expect(fig(page, "한국")).toHaveText(`${KO[b.regime]} ${pct0(b.regime_probs![b.regime])}`);
  const us = b.markets!.us!;
  await expect(fig(page, "미국")).toHaveText(`${KO[us.regime]} ${pct0(us.regime_probs![us.regime])}`);

  await patchRegime(page, (x) => { delete x.regime_probs; delete x.markets; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(fig(page, "한국")).toHaveText(`${KO[b.regime]} 확률 몰라요`);
  await expect(fig(page, "한국")).not.toContainText("0%");
  await expect(fig(page, "미국")).toContainText("몰라요");
  await expect(fig(page, "미국")).toContainText("미국 국면을 받지 못했어요");
});

test("연습용 칩은 connection-status 로만 — mock 이면 있고 · 실데이터면 없고 ok 칩(짝) · 확인 실패면 '몰라요' 칩", async ({ page }) => {
  const chip = (tone: string) => page.locator(`.home-macro .tx-chip[data-tone="${tone}"]`);
  const cs = page.waitForResponse((r) => r.url().endsWith("/api/v1/macro/connection-status"));
  await open(page);
  const st = (await (await cs).json()) as { mock_allowed: boolean; bok_configured: boolean };
  expect(st.mock_allowed && !st.bok_configured, "이 환경은 mock 이다").toBe(true);
  await expect(chip("practice")).toHaveText("연습용 데이터");

  await page.route("**/api/v1/macro/connection-status", (r) => r.fulfill({ json: { mock_allowed: false, real_mode: true, bok_configured: true, fred_configured: true } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".home-macro .tx-answer-s")).toBeVisible();
  await expect(chip("practice")).toHaveCount(0);
  await expect(chip("ok")).toHaveText("한국은행 실데이터");

  await page.unroute("**/api/v1/macro/connection-status");
  await page.route("**/api/v1/macro/connection-status", (r) => r.fulfill({ status: 500, json: { detail: "x" } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(chip("unknown")).toHaveText("데이터 출처를 확인하지 못했어요");
  await expect(chip("practice")).toHaveCount(0);
});

test("★국면 실패는 alert + 다시 시도★ — 풀고 누르면 문장이 뜬다 · 정상이면 alert 없음(짝)", async ({ page }) => {
  await open(page);
  await expect(page.locator(".home-macro [role='alert']")).toHaveCount(0);
  await page.route("**/api/v1/macro/regime", (r) => r.fulfill({ status: 500, json: { detail: "x" } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  const alert = page.locator(".home-macro [role='alert']");
  await expect(alert).toContainText("경제 흐름을 불러오지 못했어요", { timeout: 20_000 });
  await expect(answer(page)).toHaveCount(0);
  await page.unroute("**/api/v1/macro/regime");
  await page.locator(".home-macro button", { hasText: "다시 시도" }).click();
  await expect(answer(page)).toBeVisible({ timeout: 20_000 });
  await expect(alert).toHaveCount(0);
});

test("점수 높은 종목: 서버 순서 그대로 5줄 · 가격은 원 단위 그대로 · 누르면 새로고침 없이 기업 분석이 그 종목을 연다", async ({ page }) => {
  const run = page.waitForResponse((r) => r.url().includes("/api/v1/screener/run-advanced"));
  await open(page);
  const items = ((await (await run).json()) as { items: Item[] }).items.slice(0, 5);
  expect(items.length).toBeGreaterThan(0);
  const rows = page.locator(".home-picks a.tx-row");
  await expect(rows).toHaveCount(items.length);
  expect(await rows.locator(".tx-row-t").allInnerTexts()).toEqual(items.map((i) => i.corp_name));
  for (const [n, it] of items.entries()) {
    await expect(rows.nth(n).locator(".tx-row-sub")).toContainText(it.stock_code);
    await expect(rows.nth(n).locator(".tx-row-right")).toContainText(`${it.current_price.toLocaleString("ko-KR")}원`);
  }
  const target = items[items.length - 1];
  await page.evaluate(() => { (window as unknown as { __home: number }).__home = 1; });
  const core = page.waitForRequest((r) => r.url().includes("/api/v1/screener/run-advanced") && (r.postData() ?? "").includes(`"${target.stock_code}"`));
  await rows.nth(items.length - 1).click();
  await expect(page).toHaveURL(new RegExp(`/insights\\?code=${target.stock_code}$`));
  await core;
  expect(await page.evaluate(() => (window as unknown as { __home?: number }).__home), "새로고침 없이 옮겨 간다").toBe(1);
});

test("★점수 실패는 alert(빈 문구 아님)★ · 빈 결과는 빈 문구 + 데이터 상태로(alert 아님 — 짝)", async ({ page }) => {
  await page.route("**/api/v1/screener/run-advanced", (r) => r.fulfill({ status: 500, json: { detail: "x" } }));
  await open(page);
  const picks = page.locator(".home-picks");
  await expect(picks.locator("[role='alert']")).toContainText("종목 점수를 불러오지 못했어요", { timeout: 20_000 });
  await expect(picks).not.toContainText("점수를 낼 종목이 아직 없어요");
  await expect(picks.locator("button", { hasText: "다시 시도" })).toBeVisible();

  await page.unroute("**/api/v1/screener/run-advanced");
  await page.route("**/api/v1/screener/run-advanced", (r) => r.fulfill({ json: { universe: "kospi200", total_evaluated: 0, total_passed: 0,
    elapsed_seconds: 0, cache_hits: 0, cache_misses: 0, failures: 0, timestamp: "", items: [] } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(picks).toContainText("점수를 낼 종목이 아직 없어요", { timeout: 20_000 });
  await expect(picks.locator("[role='alert']")).toHaveCount(0);
  await expect(picks.locator('a[href="/admin/data"]')).toBeVisible();
});

test("적재 행 수 = 서버 db_rows · 실패면 '몰라요' + 사유(0 아님 — 짝)", async ({ page }) => {
  const st = page.waitForResponse((r) => r.url().endsWith("/api/v1/screener/snapshot-status"));
  await open(page);
  const s = (await (await st).json()) as { db_rows: number; persist_enabled: boolean };
  const row = page.locator(".home-data .dash-mod-stat");
  await expect(row.locator(".tx-row-right")).toHaveText(`${s.db_rows.toLocaleString("ko-KR")}행`);
  if (!s.persist_enabled) await expect(row.locator(".tx-row-sub")).toContainText("영속 저장이 꺼져 있어요");

  await page.route("**/api/v1/screener/snapshot-status", (r) => r.fulfill({ status: 500, json: { detail: "x" } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(row.locator(".tx-unknown-v")).toHaveText("몰라요", { timeout: 20_000 });
  await expect(row.locator(".tx-unknown-why")).toHaveText("적재 현황을 불러오지 못했어요");
  await expect(row.locator(".tx-row-right")).not.toContainText("0행");
});

test("무엇을 할까요: 모듈 줄 6개 — 이름·주소 · 번호 표식이 없다 · 포트폴리오 설계가 맨 위", async ({ page }) => {
  await open(page);
  const mods = page.locator(".home-todo a.dash-mod");
  await expect(mods).toHaveCount(6);
  const got = await mods.evaluateAll((els) => els.map((e) => [e.querySelector(".tx-row-t")?.textContent, e.getAttribute("href")]));
  expect(got).toEqual([["포트폴리오 설계", "/allocation"], ["종목 찾기", "/screener"], ["백테스트", "/backtest"],
    ["경제 흐름", "/macro"], ["기업 분석", "/insights"], ["위험 점검", "/risk-tools"]]);
  await expect(page.locator(".terminal-main .dash-mod-n")).toHaveCount(0);
  await expect(page.locator(".terminal-main")).not.toContainText(/STRESS INDEX|RISK-FREE|YIELD CURVE|CAUTIOUS/);
  await expect(page.locator(".terminal-main h1")).toHaveText("홈");
});

for (const theme of ["light", "dark"] as const) {
  test(`홈 대비 AA (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    await expect(answer(page)).toBeVisible();
    await expect(page.locator(".home-picks a.tx-row").first()).toBeVisible({ timeout: 20_000 });
    const r = await page.evaluate<AuditResult>(contrastAudit(".terminal-main"));
    expect(r.checked).toBeGreaterThan(20);
    expect(r.low, JSON.stringify(r.low)).toEqual([]);
  });
}

test("390 폭: 가로로 넘치지 않고 답 문장이 첫 화면에 보인다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await expect(answer(page)).toBeVisible();
  await expect(page.locator(".home-picks a.tx-row").first()).toBeVisible({ timeout: 20_000 });
  const over = await page.locator(".terminal-main").evaluate((m) => m.scrollWidth - m.clientWidth);
  expect(over, "본문이 가로로 넘친다").toBeLessThanOrEqual(0);
  const box = await answer(page).boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThan(844);
});
