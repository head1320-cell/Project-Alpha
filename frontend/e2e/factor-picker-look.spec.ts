import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BU3c · 팩터 고르기 창 · 관심그룹 창 — 모습(토스식)과 정직성 (계획 "BU3c 상세 (재감사)")
 * 거는 것(짝으로 항상-통과를 배제):
 *  · 창 색은 연 자리를 따른다 — 매수 = --tx-up-ink · 매도 = --tx-down-ink · 종목 찾기 = --tx-cta(주 단추),
 *    고른 줄 바탕 = 같은 톤의 연한 색. 짝: 매수 색은 다른 두 자리와 다르다(매도·중립은 라이트에서 같은 파랑).
 *  · 창 안 주 단추는 [입력] 하나 · 라이트/다크 AA · 다크에서 밝은 판 0 · 390 에서 창이 화면 안
 *  · 관심그룹 창: ★분류·종목을 불러오지 못하면 alert★(짝: 정상이면 alert 0, 분류 목록이 보인다) ·
 *    [저장하기]는 종목을 고르기 전엔 막혀 있고 고르면 열린다 · AA · 390
 * 동작·문구 계약은 `factor-picker.spec`(12 단언)이, 요청은 두 요청 골든이 바이트로 건다.
 */

const SEARCH = "조건을 단어로 입력하세요";
const dialog = (p: Page) => p.locator(".tfm");
const apply = (p: Page) => p.getByRole("button", { name: "입력", exact: true });

const tokenRgb = (p: Page, name: string) => p.evaluate((n) => {
  const el = document.createElement("span");
  el.style.color = `var(${n})`;
  document.body.appendChild(el);
  const c = getComputedStyle(el).color;
  el.remove();
  return c;
}, name);
const bg = (l: ReturnType<Page["locator"]>) => l.evaluate((e) => getComputedStyle(e).backgroundColor);

async function pickMcap(p: Page) {
  await p.getByPlaceholder(SEARCH).fill("시가총액");
  const row = p.locator(".tfm-row").filter({ has: p.locator('.tfm-row-d:text-is("{시가총액}")') }).first();
  await row.click();
  await expect(apply(p)).toBeVisible();
}

async function openFrom(p: Page, where: "buy" | "sell" | "screener") {
  if (where === "screener") {
    await p.goto("/screener", { waitUntil: "networkidle" });
    await p.locator(".bsc-add-btn").first().click();
  } else {
    await p.goto("/backtest", { waitUntil: "networkidle" });
    if (where === "sell") await p.locator('[data-act="step-sell"]').click();
    await p.locator(`.bte-step[data-step="${where}"]`).getByRole("button", { name: /^팩터$/ }).first().click();
  }
  await expect(p.getByPlaceholder(SEARCH)).toBeVisible();
}

const theme = (p: Page, t: "light" | "dark") =>
  p.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, t);

test("창 색은 연 자리를 따른다 — 매수 빨강 · 매도 파랑 · 종목 찾기 중립(짝: 매수는 다른 둘과 다르다)", async ({ page }) => {
  const want = { buy: ["--tx-up-ink", "--tx-up-soft"], sell: ["--tx-down-ink", "--tx-down-soft"], screener: ["--tx-cta", "--tx-blue-soft"] } as const;
  const seen: string[] = [];
  for (const where of ["buy", "sell", "screener"] as const) {
    await openFrom(page, where);
    await pickMcap(page);
    const [btnTok, softTok] = want[where];
    const btnWant = await tokenRgb(page, btnTok);
    await expect.poll(() => bg(apply(page)), `${where}: [입력] 색`).toBe(btnWant);
    await expect.poll(() => bg(page.locator(".tfm-row.on").first()), `${where}: 고른 줄 바탕`).toBe(await tokenRgb(page, softTok));
    seen.push(await bg(apply(page)));
  }
  // 짝: 매수는 매도·중립과 다르다. ★매도와 중립은 라이트에서 같은 파랑이다★(--tx-down-ink = --tx-cta = #1b64da —
  // 한국식 "내림 = 파랑" 이 제품의 중립 파랑과 같은 색이라서. BU3 kit 도 같다) — 그래서 셋이 모두 다르다고 걸지 않는다.
  expect(seen[0], `매수 vs 매도: ${seen.join(" / ")}`).not.toBe(seen[1]);
  expect(seen[0], `매수 vs 종목 찾기: ${seen.join(" / ")}`).not.toBe(seen[2]);
});

test("창 안 주 단추는 [입력] 하나 — 같은 톤으로 칠한 다른 단추가 없다", async ({ page }) => {
  await openFrom(page, "buy");
  await pickMcap(page);
  const btn = await bg(apply(page));
  const same = await dialog(page).locator("button").evaluateAll(
    (els, c) => els.filter((e) => getComputedStyle(e).backgroundColor === c).map((e) => (e.textContent || "").trim()), btn);
  expect(same).toEqual(["입력"]);
});

for (const t of ["light", "dark"] as const) {
  test(`팩터 창 AA — ${t} (빈 상태 · 고른 상태)`, async ({ page }) => {
    await theme(page, t);
    await openFrom(page, "buy");
    for (const stage of ["empty", "picked"]) {
      if (stage === "picked") await pickMcap(page);
      await page.waitForTimeout(400);
      const r = await page.evaluate<AuditResult>(contrastAudit(".tfm"));
      expect(r.checked, stage).toBeGreaterThan(5);
      expect(r.low, `${t}/${stage}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
      if (t === "dark") expect(r.bright, `${t}/${stage} 밝은 판`).toEqual([]);
    }
  });
}

test("390 — 팩터 창이 화면 안에 있고 [입력]까지 닿는다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openFrom(page, "screener");
  await pickMcap(page);
  const box = await dialog(page).boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390.5);
  await apply(page).scrollIntoViewIfNeeded();
  await expect(apply(page)).toBeInViewport();
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over).toBeLessThanOrEqual(0);
});

// ── 관심그룹 창 ────────────────────────────────────────────────────────────────
const wg = (p: Page) => p.locator(".wg-modal");
async function openWatch(p: Page) {
  await p.goto("/backtest", { waitUntil: "networkidle" });
  await p.locator('[data-act="step-universe"]').click();
  await p.getByRole("button", { name: /그룹 추가/ }).first().click();
  await expect(wg(p)).toBeVisible();
}

test("관심그룹 창: 분류 목록을 불러오지 못하면 alert(짝: 정상이면 alert 0 · 분류가 보인다)", async ({ page }) => {
  await openWatch(page);
  await expect(wg(page).getByRole("button", { name: /코스피 대형/ })).toBeVisible({ timeout: 15_000 });
  await expect(wg(page).getByRole("alert")).toHaveCount(0);
  await page.keyboard.press("Escape");

  await page.route(/\/api\/v1\/screener\/stock-browse$/, (r) => r.fulfill({ status: 500, body: "boom" }));
  await page.getByRole("button", { name: /그룹 추가/ }).first().click();
  await expect(wg(page).getByRole("alert")).toContainText("분류 목록을 불러오지 못했어요");
});

test("관심그룹 창: 종목 목록을 불러오지 못하면 alert — '분류를 고르세요'로 덮지 않는다", async ({ page }) => {
  await page.route(/\/api\/v1\/screener\/stock-browse\?cls=/, (r) => r.fulfill({ status: 500, body: "boom" }));
  await openWatch(page);
  await wg(page).getByRole("button", { name: /코스피 대형/ }).click();
  await expect(wg(page).getByRole("alert")).toContainText("종목 목록을 불러오지 못했어요");
  await expect(wg(page).locator(".wg-items").getByText(/분류를 (선택|골라)/)).toHaveCount(0);
});

test("관심그룹 창: [저장하기]는 종목을 고르기 전엔 막혀 있고, 고르면 열린다", async ({ page }) => {
  await openWatch(page);
  const save = wg(page).getByRole("button", { name: "저장하기" });
  await expect(save).toBeDisabled();
  await wg(page).getByRole("button", { name: /코스피 대형/ }).click();
  await wg(page).locator('.wg-items input[type="checkbox"]').first().check();
  await expect(save).toBeEnabled();
});

for (const t of ["light", "dark"] as const) {
  test(`관심그룹 창 AA — ${t}`, async ({ page }) => {
    await theme(page, t);
    await openWatch(page);
    await wg(page).getByRole("button", { name: /코스피 대형/ }).click();
    await wg(page).locator('.wg-items input[type="checkbox"]').first().check();
    await page.waitForTimeout(400);
    const r = await page.evaluate<AuditResult>(contrastAudit(".wg-modal"));
    expect(r.checked).toBeGreaterThan(5);
    expect(r.low, `${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
    if (t === "dark") expect(r.bright, `${t} 밝은 판`).toEqual([]);
  });
}

test("390 — 관심그룹 창이 화면 안에 있다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openWatch(page);
  const box = await wg(page).boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390.5);
});
