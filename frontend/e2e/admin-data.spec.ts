import { expect, test } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// /admin/data — DB 상태 패널 + **출처별 연구 등급** (Phase 8b 요구 4).
//
// 두 가지 구멍을 함께 메운다:
//  1. 이 라우트에는 E2E 가 **하나도 없었다** — admin.spec.ts 가 다른 세 라우트에 대해
//     메운 것과 같은 구멍이다(마운트 실패·API 404 를 아무도 못 본다).
//  2. Phase 8b 의 정직성 라벨은 백엔드만 테스트돼 있었다. 렌더된다는 보장이 없었고,
//     보장이 없으면 조용히 사라져도 알 수 없다.
//
// ★이 화면의 요점은 "두 축이 따로 보인다" 는 것이다★ (스펙 §3.5)
// "가져올 수 있다"(data_status)와 "과거 검증에 쓸 수 있다"(research_usage)는 다른 축이다.
// 하나로 합쳐 보여주면 사용자는 조회되는 모든 것을 백테스트에 써도 된다고 읽는다.
//
// 선택자 주의: 이 패널은 h1 이 없다(SectionHead 로 구성). admin.spec.ts 의 h1 기반
// 스모크 루프를 그대로 쓸 수 없어 전용 스펙으로 둔다.
// ═══════════════════════════════════════════════════════════════════════════════

test("/admin/data: 마운트되고 페이지 에러·API 404 가 없다", async ({ page }) => {
  const sink = trackErrors(page);

  await page.goto("/admin/data", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("DATA SOURCES").first()).toBeVisible({ timeout: 20_000 });

  // 클라이언트 페치가 끝난 뒤에도 살아 있는지 — "렌더되고 첫 응답에서 죽는" 경우를 잡는다.
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  await page.waitForTimeout(1_000);
  await expect(page.getByText("DATA SOURCES").first()).toBeVisible();

  const body = await page.locator("body").innerText();
  expect(body, "한글이 깨지면 안 된다").not.toMatch(/�/);
  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
  expect(uniq(sink.api404), "API 404s").toEqual([]);
});

test("정직성 라벨: 출처마다 두 축이 **따로** 보인다", async ({ page }) => {
  await page.goto("/admin/data", { waitUntil: "networkidle" });
  const rows = page.locator(".t-honesty-row");
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  expect(await rows.count(), "출처가 하나도 없다").toBeGreaterThanOrEqual(4);

  for (const row of await rows.all()) {
    // ★두 배지가 모두 있어야 한다★ 하나로 합치면 §3.5 의 구별이 화면에서 사라진다.
    await expect(row.locator(".t-honesty-st")).toHaveCount(1);
    await expect(row.locator(".t-honesty-use")).toHaveCount(1);
    // 왜 그 등급인지도 함께 — 등급만 있으면 사용자가 무엇을 확인해야 할지 모른다.
    expect((await row.locator(".t-honesty-why").innerText()).trim().length).toBeGreaterThan(5);
  }
});

test("정직성 라벨: mock 모드와 키 부재가 화면까지 정직하게 내려온다", async ({ page }) => {
  // 이 환경은 KIS_USE_MOCK=1 이고 FRED_API_KEY 가 없다. 그 사실이 등급으로 드러나야 한다 —
  // 드러나지 않으면 사용자는 합성 데이터를 실데이터로 오해한다.
  await page.goto("/admin/data", { waitUntil: "networkidle" });
  await expect(page.locator(".t-honesty-row").first()).toBeVisible({ timeout: 20_000 });

  const prices = page.locator(".t-honesty-row", { hasText: "ETF" }).first();
  await expect(prices.locator(".t-honesty-use")).toHaveClass(/u-forward_only/);

  const fred = page.locator(".t-honesty-row", { hasText: "FRED" }).first();
  await expect(fred.locator(".t-honesty-use")).toHaveClass(/u-unavailable/);
});

test("정직성 라벨: 등급마다 다른 클래스를 쓴다 (눈으로 구별 가능해야 한다)", async ({ page }) => {
  // ★같은 스타일이면 구별이 없는 것과 같다★ 이 화면의 존재 이유가 구별이다.
  await page.goto("/admin/data", { waitUntil: "networkidle" });
  await expect(page.locator(".t-honesty-row").first()).toBeVisible({ timeout: 20_000 });

  const classes = await page.locator(".t-honesty-use").evaluateAll(
    (els) => els.map((e) => (e.className || "").split(/\s+/).find((c) => c.startsWith("u-"))));
  const distinct = new Set(classes.filter(Boolean));
  expect(distinct.size, `등급 클래스가 ${distinct.size}종 — 서로 다른 등급이 같게 보인다`)
    .toBeGreaterThanOrEqual(2);
});
