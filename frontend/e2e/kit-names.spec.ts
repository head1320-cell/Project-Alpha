import { test, expect, type Page } from "./fixtures";

/**
 * 이름 없는 조작 요소 — 접근성 P0-4 (ADR 007 결정 D4 · 계획 `docs/superpowers/plans/2026-11-20-uiux-u0-foundation.md`)
 * ─────────────────────────────────────────────────────────────────
 * kit 의 스위치 · 숫자 칸 · 고르기 칸은 곁에 글자가 보이는데도 접근성 트리에는 이름이 없었다 — 낭독기는 "스위치, 꺼짐" · "숫자 입력, 10"만 읽는다.
 * 보이는 글자와 `aria-labelledby` 로 잇는다(화면의 글자 · 모습 · 요청은 그대로 — 그쪽은 `backtest-editor` · `backtest-requests` · 라이트 골든이 건다).
 * 거는 것(짝으로 항상-통과를 배제):
 *  · `/backtest` 의 네 단계를 하나씩 펴면 이름 없는 조작 요소가 0 이다(짝: 스위치 · 숫자 칸 · 고르기 칸이 실제로 있다)
 *  · 스위치의 이름 = 그 줄에 보이는 제목 그대로 · 한 단계 안에서 서로 다르다(이름 하나를 모두에 붙인 구현을 배제)
 *  · 숫자 칸의 이름 = 줄의 글자 + 단위 — 켜야 나오는 칸(손절가 %)도 같다
 *  · 한 줄에 칸이 둘인 곳(ETF · 주식 배분 비율)은 서로 다른 이름 · 줄 밖의 고르기 칸(돌파 매수의 기준가)도 이름이 있다
 * 이름은 브라우저의 접근성 이름 계산으로 본다(`toHaveAccessibleName` · `ariaSnapshot`) — 속성만 달고 가리키는 곳이 틀린 구현은 통과하지 못한다.
 * 한계: 접근성 트리의 이름까지다 — 실제 낭독기로 듣지는 못했다.
 */

const STEP = ".bte .tbt-mode";
/** 접근성 트리의 한 줄이 이름 없는 조작 요소인가 — `- switch` · `- switch [checked]` · `- spinbutton: "10"` · `- combobox:` 처럼 역할 뒤에 따옴표 이름이 없다. */
const UNNAMED = /^\s*- (switch|spinbutton|combobox|textbox|checkbox|radio|slider|button)(?! ")(\s|$|\[|:)/;
const KIT = /^\s*- (switch|spinbutton|combobox)\b/;

async function open(page: Page) {
  await page.goto("/backtest", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".bte").first()).toBeVisible({ timeout: 20_000 });
  // React 가 붙은 뒤에 누른다 — 붙기 전의 누르기는 사라진다.
  await page.waitForFunction(() => { const el = document.querySelector(".bte"); return !!el && Object.keys(el).some((k) => k.startsWith("__reactFiber")); }, undefined, { timeout: 20_000 });
}

/** i 번째 단계를 편다(펴져 있으면 그대로). 단계는 ★하나만★ 펴진다 — 다른 단계를 펴면 앞의 것은 접힌다(그래서 아래의 세기는 그 단계의 것이다). */
async function expand(page: Page, i: number) {
  const step = page.locator(STEP).nth(i);
  if ((await step.getAttribute("aria-expanded")) !== "true") await step.click();
  await expect(step).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(`${STEP}[aria-expanded="true"]`), "펴진 단계는 하나").toHaveCount(1);
}
/** 스위치를 켠다(켜져 있으면 그대로). */
async function turnOn(sw: ReturnType<Page["locator"]>) {
  if ((await sw.getAttribute("aria-checked")) !== "true") await sw.click();
  await expect(sw).toHaveAttribute("aria-checked", "true");
}

test("네 단계를 하나씩 펴도 이름 없는 조작 요소가 없다(짝: 스위치 · 숫자 칸 · 고르기 칸이 실제로 있다)", async ({ page }) => {
  await open(page);
  const n = await page.locator(STEP).count();
  expect(n, "단계의 수").toBeGreaterThanOrEqual(4);
  let kit = 0;
  for (let i = 0; i < n; i++) {
    await expand(page, i);
    const lines = (await page.locator(".bte").ariaSnapshot()).split("\n");
    kit += lines.filter((l) => KIT.test(l)).length;
    expect(lines.filter((l) => UNNAMED.test(l)).map((l) => l.trim()), `${i + 1}단계의 이름 없는 조작 요소`).toEqual([]);
  }
  expect(kit, "짝 — 본 조작 요소가 있다(빈 화면을 통과시키지 않는다)").toBeGreaterThan(20);
});

test("스위치의 이름은 그 줄에 보이는 제목이다 · 한 단계 안에서 서로 다르다", async ({ page }) => {
  await open(page);
  const n = await page.locator(STEP).count();
  let seen = 0;
  for (let i = 0; i < n; i++) {
    await expand(page, i);
    const switches = page.locator(".bte [role='switch']");
    const titles = await switches.evaluateAll((els) => els.map((el) =>
      el.closest(".kit-sec-head, .kit-sub-head")?.querySelector(".kit-sec-t, .kit-sub-l")?.textContent?.trim() ?? ""));
    for (let k = 0; k < titles.length; k++) {
      expect(titles[k], `${i + 1}단계 ${k + 1}번째 스위치 곁에 보이는 제목`).not.toBe("");
      await expect(switches.nth(k), `'${titles[k]}' 스위치의 이름`).toHaveAccessibleName(titles[k]);
    }
    expect(new Set(titles).size, `${i + 1}단계 스위치의 이름이 서로 다르다: ${titles.join(" · ")}`).toBe(titles.length);
    seen += titles.length;
  }
  expect(seen, "짝 — 스위치가 실제로 있다").toBeGreaterThanOrEqual(10);
});

test("숫자 칸의 이름은 줄의 글자와 단위다 — 켜야 나오는 칸도 같다(짝: 한 묶음의 칸이 서로 다른 이름)", async ({ page }) => {
  await open(page);
  await expand(page, 3);                                                     // 투자금 · 기간 · 비용
  await expect(page.locator('.bte [data-act="capital"]')).toHaveAccessibleName("투자 금액 만원");
  await expect(page.locator('.bte [data-act="fee"]')).toHaveAccessibleName("수수료율 %");
  await expect(page.locator(".bte").getByRole("spinbutton", { name: "슬리피지 %", exact: true }), "act 가 없는 칸도 줄의 글자를 따른다").toHaveCount(1);
  await expect(page.locator(".bte").getByRole("spinbutton", { name: "수수료율 %", exact: true }), "짝 — 같은 이름이 둘이 아니다").toHaveCount(1);

  await expand(page, 1);                                                     // 매도 설정 — 손절가는 절을 켜야 나온다
  await turnOn(page.locator('.bte [data-act="sell-exits"]'));
  const stop = page.locator('.bte [data-act="stop-loss"]');
  await expect(stop).toHaveAccessibleName("손절가");
  await turnOn(stop);
  await expect(page.locator('.bte [data-act="stop-loss-pct"]'), "켜야 나오는 칸 — 그 줄의 스위치 글자 + 단위").toHaveAccessibleName("손절가 %");
});

test("한 줄에 칸이 둘이면 서로 다른 이름이다 — ETF · 주식 배분 비율 · 줄 밖의 고르기 칸(돌파 매수의 기준가)", async ({ page }) => {
  await open(page);
  await expand(page, 0);                                                     // 매수 설정
  const etf = page.locator('.bte .kit-sec:has(> .kit-sec-head .kit-sec-t:text-is("ETF 자산배분"))');
  await expect(etf).toHaveCount(1);
  await turnOn(etf.locator("> .kit-sec-head [role='switch']"));
  const boxes = etf.locator('.kit-field:has(> .kit-field-l:text-is("배분 비율")) input[type="number"]');
  await expect(boxes, "배분 비율 줄의 숫자 칸").toHaveCount(2);
  await expect(boxes.nth(0)).toHaveAccessibleName("ETF 배분 비율 %");
  await expect(boxes.nth(1)).toHaveAccessibleName("주식 배분 비율 %");

  const breakout = page.locator('.bte .kit-sub:has(> .kit-sub-head .kit-sub-l:text-is("돌파 매수"))');
  await expect(breakout).toHaveCount(1);
  await turnOn(breakout.locator("> .kit-sub-head [role='switch']"));
  await expect(page.locator(".bte").getByRole("combobox", { name: "돌파 매수 기준가", exact: true }), "줄(Field) 밖의 고르기 칸").toHaveCount(1);
});
