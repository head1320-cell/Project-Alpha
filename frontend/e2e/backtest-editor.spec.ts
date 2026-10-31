import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BU3 · 백테스트 편집기 — 설계 순서 넷 · 지금 설정 되읽기 · 거짓 약속 없음 · 실패는 실패로 (계획 "BU3 상세")
 * 거는 것(짝으로 항상-통과·항상-침묵을 배제):
 *  · 머리 "백테스트" · 단계 넷(무엇을 살까 → 언제 팔까 → 어디서 고를까 → 돈·기간·비용)이 그 순서 · 고른 단계만 펼친다
 *  · 단계의 "지금" 줄은 사용자가 넣은 설정을 되읽는다 — 투자 금액을 바꾸면 그 줄이 바뀐다(짝: 바꾸기 전 값)
 *  · ★결과가 뜨지 않는 결과 자리·"AWAITING" 약속이 없다★ · 실행 실패는 alert + 주소 그대로(짝: 정상이면 진행 화면으로, alert 0)
 *  · 주 단추는 하나(실행) · 매수 톤 = 빨강(--tx-up) · 매도 톤 = 파랑(--tx-down) — 라벨과 함께
 *  · 라이트/다크 AA(단계 넷) · 390 가로 넘침 없음
 * 요청은 `backtest-requests.spec` 골든이 바이트로 건다(이 스펙은 모습·문구·동작).
 */

const act = (p: Page, a: string) => p.locator(`[data-act="${a}"]`);
const steps = (p: Page) => p.locator(".bte .tbt-mode");
const nowLine = (p: Page, i: number) => steps(p).nth(i).locator(".bte-step-now");
const STEP_NAMES = ["무엇을 살까", "언제 팔까", "어디서 고를까", "돈·기간·비용"];

async function open(page: Page) {
  await page.goto("/backtest", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".bte")).toBeVisible({ timeout: 20_000 });
}

/** CSS 변수 값을 계산된 rgb 로 — 토큰이 실제로 칠해졌는지 견준다. */
const tokenRgb = (p: Page, name: string) => p.evaluate((n) => {
  const el = document.createElement("span");
  el.style.color = `var(${n})`;
  document.body.appendChild(el);
  const c = getComputedStyle(el).color;
  el.remove();
  return c;
}, name);

test("머리 · 단계 넷이 설계 순서대로 · 고른 단계만 펼친다(짝)", async ({ page }) => {
  await open(page);
  await expect(page.locator(".bte h1")).toHaveText("백테스트");
  await expect(steps(page)).toHaveCount(4);
  expect(await steps(page).locator(".bte-step-t").allInnerTexts()).toEqual(STEP_NAMES);
  expect(await steps(page).locator(".bte-step-n").allInnerTexts()).toEqual(["1", "2", "3", "4"]);
  await expect(page.locator(".bte-step-body")).toHaveCount(1);
  await expect(steps(page).nth(0)).toHaveAttribute("aria-expanded", "true");
  await expect(act(page, "capital")).toHaveCount(0);              // 돈 칸은 매수 단계에 없다(④ 로 옮겼다)
  await steps(page).nth(3).click();
  await expect(act(page, "capital")).toBeVisible();
  await expect(steps(page).nth(0)).toHaveAttribute("aria-expanded", "false");
  await expect(act(page, "buy-fundamentals")).toHaveCount(0);     // 짝: 다른 단계 칸은 닫힌다
});

test("'지금' 줄은 설정을 되읽는다 — 투자 금액을 바꾸면 ④ 줄이 바뀐다(짝: 바꾸기 전 값)", async ({ page }) => {
  await open(page);
  await expect(nowLine(page, 3)).toContainText("5,000만원");
  await steps(page).nth(3).click();
  await act(page, "capital").fill("12000");
  await expect(nowLine(page, 3)).toContainText("12,000만원");
  await expect(nowLine(page, 3)).not.toContainText("5,000만원");
});

test("★아직 세지 않은 대상 수는 0이 아니라 '세어요'★ — ③을 열면 서버가 센 수로 바뀐다(짝)", async ({ page }) => {
  await open(page);
  await expect(nowLine(page, 2)).toContainText("③을 열면 세어요");
  await expect(nowLine(page, 2)).not.toContainText("0 종목");
  await steps(page).nth(2).click();
  await expect(nowLine(page, 2)).toContainText(/[1-9][\d,]* 종목/, { timeout: 15_000 });
  await expect(nowLine(page, 2)).not.toContainText("③을 열면 세어요");
});

test("★업종 목록 실패는 alert★(예전에는 빈 칸) · 정상이면 alert 없음(짝)", async ({ page }) => {
  await page.route("**/api/v1/screener/theme-tree", (r) => r.fulfill({ status: 500, json: { detail: "x" } }));
  await open(page);
  await steps(page).nth(2).click();
  await expect(page.locator(".bte-step-body [role='alert']")).toContainText("업종 목록을 불러오지 못했어요");
  await page.unroute("**/api/v1/screener/theme-tree");
  await page.reload({ waitUntil: "domcontentloaded" });
  await steps(page).nth(2).click();
  await expect(page.locator(".bte-tree-g").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".bte-step-body [role='alert']")).toHaveCount(0);
});

test("늘 켜진 절에는 스위치가 없다(눌러도 아무 일 없는 스위치를 걷었다) · 켜고 끄는 절에는 있다(짝)", async ({ page }) => {
  await open(page);
  await steps(page).nth(3).click();
  const money = page.locator(".kit-sec", { has: page.locator(".kit-sec-t", { hasText: /^돈과 기간$/ }) });
  await expect(money).toHaveCount(1);
  await expect(money.locator(".kit-sec-head [role='switch']")).toHaveCount(0);
  await steps(page).nth(0).click();
  const buy = page.locator(".kit-sec", { has: page.locator(".kit-sec-t", { hasText: /^살 조건$/ }) });
  await expect(buy.locator(".kit-sec-head [role='switch']")).toHaveCount(1);
});

test("★거짓 약속 없음★ — 결과가 뜨지 않는 결과 자리 문구가 없다 · 실행하면 진행 화면으로 간다고 말한다", async ({ page }) => {
  await open(page);
  const body = page.locator(".terminal-main");
  await expect(body).not.toContainText("AWAITING");
  await expect(body).not.toContainText("결과가 여기에 표시돼요");
  await expect(body).not.toContainText("자산곡선·성과지표·거래내역이 여기에");
  await expect(page.locator(".bte-run-note")).toContainText("진행 화면");
});

test("★실행 실패는 alert, 주소 그대로★ · 정상이면 진행 화면으로 가고 alert 없음(짝)", async ({ page }) => {
  await page.route("**/api/v1/backtest/runs", (r) => r.request().method() === "POST"
    ? r.fulfill({ status: 500, json: { detail: "boom" } }) : r.fallback());
  await open(page);
  await act(page, "run").click();
  const alert = page.locator(".bte [role='alert']");
  await expect(alert).toContainText("실행을 시작하지 못했어요", { timeout: 15_000 });
  await expect(page).toHaveURL(/\/backtest$/);

  await page.unroute("**/api/v1/backtest/runs");
  await page.route("**/api/v1/backtest/runs", (r) => r.request().method() === "POST"
    ? r.fulfill({ json: { run_id: "bu3-editor", status: "queued" } }) : r.fallback());
  await page.route("**/api/v1/backtest/runs/bu3-editor**", (r) => r.fulfill({ status: 404, json: { detail: "x" } }));
  await act(page, "run").click();
  await page.waitForURL(/\/backtest\/runs\/bu3-editor\/loading/);
});

test("주 단추는 하나(실행) · 매수 톤 빨강 · 매도 톤 파랑 — 라벨과 함께", async ({ page }) => {
  await open(page);
  await expect(page.locator(".bte .tx-btn--main")).toHaveCount(1);
  await expect(page.locator(".bte .tx-btn--main")).toHaveText("백테스트 실행");
  const up = await tokenRgb(page, "--tx-up"), down = await tokenRgb(page, "--tx-down");
  expect(up).not.toEqual(down);

  const buy = act(page, "buy-fundamentals");
  await buy.click();
  await expect(buy).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => buy.evaluate((b) => getComputedStyle(b).backgroundColor)).toEqual(up);   // 전이(.12s) 뒤 값
  await expect(buy.locator("xpath=ancestor::*[contains(@class,'kit-sub')][1]")).toContainText("재무 조건도 평가");

  await steps(page).nth(1).click();
  const sell = act(page, "sell-exits");
  await sell.click();
  await expect(sell).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => sell.evaluate((b) => getComputedStyle(b).backgroundColor)).toEqual(down);
});

for (const theme of ["light", "dark"] as const) {
  test(`백테스트 편집기 대비 AA — 단계 넷 (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    for (let i = 0; i < 4; i++) {
      await steps(page).nth(i).click();
      await expect(steps(page).nth(i)).toHaveAttribute("aria-expanded", "true");
      const r = await page.evaluate<AuditResult>(contrastAudit(".terminal-main"));
      expect(r.checked, `단계 ${i + 1}`).toBeGreaterThan(20);
      expect(r.low, `단계 ${i + 1}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
    }
  });
}

test("390 폭: 가로로 넘치지 않고 실행 단추가 보인다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  for (let i = 0; i < 4; i++) {
    await steps(page).nth(i).click();
    const over = await page.locator(".terminal-main").evaluate((m) => m.scrollWidth - m.clientWidth);
    expect(over, `단계 ${i + 1}`).toBeLessThanOrEqual(0);
  }
  await act(page, "run").scrollIntoViewIfNeeded();
  await expect(act(page, "run")).toBeVisible();
});
