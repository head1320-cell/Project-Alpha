import { test, expect } from "@playwright/test";

// ═══════════════════════════════════════════════════════════════════════════════
// 반응형 — 행동 계약 (UI/UX 현대화 P10)
// ─────────────────────────────────────────────────────────────────────────────
// ★스크린샷을 찍는 것이 아니라 행동을 단언한다★
// 계획서 초안은 "390/1280/1440 에서 스크린샷" 이었다. 그런데 스크린샷은 무엇이 **사라지면
// 안 되는지** 를 말하지 못한다. 여기서 지키는 것은 하나다:
//
//   좁은 폭이라는 이유로 정직함을 줄이지 않는다.
//
// PINNED/LIVE · as-of · mock · stale · 룰셋 · 팩 · 런 신원은 390px 에서도 화면에 남아야
// 한다. 접어도 되는 것은 보조 시각화(카나리 스파크라인)와 다열 배치뿐이다.
//
// ★실측 출발점★ globals.css 의 @media 41개 중 `.as-ctx-*` 를 겨냥한 것은 0개였다.
// 이 구간은 회귀 위험이 아니라 미개척지였다.
// ═══════════════════════════════════════════════════════════════════════════════

const MOBILE = { width: 390, height: 844 };
const TABLET = { width: 768, height: 1024 };
const DESKTOP = { width: 1440, height: 900 };

/** 어느 폭에서도 남아야 하는 신원 요소 — "폭이 좁아서 뺐다" 가 허용되지 않는 것들. */
const IDENTITY = [".as-ctx-regime", ".as-ctx-src", ".as-ctx-univ", ".as-ctx-rules"];

for (const [name, size] of [["mobile", MOBILE], ["tablet", TABLET], ["desktop", DESKTOP]] as const) {
  test(`${name}(${size.width}px): 신원 요소가 하나도 사라지지 않는다`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.goto("/allocation/optimize", { waitUntil: "networkidle" });

    for (const sel of IDENTITY) {
      await expect(page.locator(sel).first(), `${sel} @${size.width}`).toBeVisible();
    }
    // PINNED/LIVE 는 텍스트까지 확인한다 — 요소만 남고 내용이 잘리면 의미가 없다.
    await expect(page.locator(".as-ctx-src").first()).toHaveText(/PINNED|LIVE/);
  });
}

test("mobile(390px): 본문이 가로로 스크롤되지 않는다", async ({ page }) => {
  await page.setViewportSize(MOBILE);
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });

  // 가로 스크롤이 생기면 신원 줄의 오른쪽 절반이 화면 밖으로 나간다 — 숨긴 것과 같다.
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "가로 오버플로 픽셀").toBeLessThanOrEqual(1);
});

test("mobile(390px): 접는 것은 보조 시각화뿐이다 — 값과 라벨은 남는다", async ({ page }) => {
  await page.setViewportSize(MOBILE);
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });

  // 스파크라인(보조)은 접힌다.
  const sparks = page.locator(".as-ctx-spark");
  if (await sparks.count()) await expect(sparks.first()).toBeHidden();
  // 그러나 카나리의 라벨·값은 남는다 — 그것은 데이터이지 장식이 아니다.
  await expect(page.locator(".as-ctx-canary").first()).toBeVisible();
  await expect(page.locator(".as-ctx-canary b").first()).toBeVisible();
});

test("mobile(390px): 워크플로 CTA 와 그 이유가 함께 읽힌다", async ({ page }) => {
  await page.setViewportSize(MOBILE);
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });

  const cta = page.locator(".aas-botnav-next");
  const why = page.locator(".aas-botnav-why");
  await expect(cta).toBeVisible();
  await expect(why, "사유가 좁은 폭에서 사라지면 CTA 는 명령이 된다").toBeVisible();
  expect((await why.innerText()).trim().length).toBeGreaterThan(0);
});

test("desktop(1440px): 편집 워크스테이션 — 근거와 컨트롤이 함께 보인다", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });

  // 데스크톱에서는 스파크라인까지 전부 보인다(밀도가 기능이다).
  const sparks = page.locator(".as-ctx-spark");
  if (await sparks.count()) await expect(sparks.first()).toBeVisible();
  await expect(page.locator(".aas-wiz")).toBeVisible();
  await expect(page.locator(".aas-content")).toBeVisible();
});
