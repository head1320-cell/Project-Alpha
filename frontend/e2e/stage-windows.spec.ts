import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// 02 ALPHA LAB — 표현식 팩터가 구분 없는 칩 벽으로 깔려 있던 것을 검색·분류되는 단일 창으로 통합.
// 회귀 방지: 창이 열리고 4개 패밀리가 노출되며, 검색→선택→삽입이 실제로 표현식을 바꾼다.
test("Alpha Lab: unified expression factor window inserts into the expression", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/allocation/alphalab", { waitUntil: "networkidle" });

  // 설명 없는 칩 벽은 더 이상 없어야 한다(팩터 창으로 대체)
  expect(await page.locator(".as-al-chips").count(), "legacy chip wall removed").toBe(0);
  const before = await page.locator(".as-al-expr").inputValue();

  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).click();
  await expect(page.locator(".tfm")).toBeVisible();
  const fams = await page.locator(".tfm .tfm-fams button").allInnerTexts();
  expect(fams.length, "4 families: 가격·펀더멘털·변환·결합").toBe(4);

  // 검색 → 펀더멘털 필드 선택 → 미리보기 → 삽입
  await page.locator(".tfm .tfm-search").fill("roe");
  await expect(page.locator(".tfm .tfm-row").first()).toBeVisible();
  await page.locator(".tfm .tfm-row").first().click();
  await expect(page.locator(".tfm-prev")).toContainText("roe");
  await page.locator(".as-fb-apply", { hasText: "표현식에 넣기" }).click();

  await expect(page.locator(".tfm")).toHaveCount(0);
  const after = await page.locator(".as-al-expr").inputValue();
  expect(after).not.toBe(before);
  expect(after).toContain("roe");

  expect(uniq(sink.pageErrors), "alpha window page errors").toEqual([]);
  expect(uniq(sink.api404), "alpha window API 404s").toEqual([]);
});

// ALPHA REGISTRY — 알파가 늘어도 찾을 수 있도록 검색 + 상태 필터.
test("Alpha Registry: status filter chips narrow the list", async ({ page }) => {
  await page.goto("/allocation/alphalab", { waitUntil: "networkidle" });
  const registry = page.locator(".as-card").filter({ hasText: "ALPHA REGISTRY" });
  const chips = registry.locator(".tfm-fams button");
  await expect(chips.first()).toContainText("전체");

  const total = await registry.locator(".as-al-item").count();
  if (await chips.count() > 1) {
    await chips.nth(1).click();
    const filtered = await registry.locator(".as-al-item").count();
    expect(filtered, "status filter narrows (or keeps) the list").toBeLessThanOrEqual(total);
  }
});

// 06 STRESS — 시나리오가 좌측 레일(가상4+역사4)과 KrScenarioPack(국내7) 두 곳에 흩어져
// 있던 것을 3패밀리 단일 창으로 통합. 미가용 사유가 툴팁이 아니라 목록에 보인다.
test("Stress: unified scenario window merges all three families", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/allocation/stress", { waitUntil: "networkidle" });

  await page.locator(".as-fb-apply", { hasText: "시나리오 창에서 선택" }).click();
  await expect(page.locator(".tfm")).toBeVisible();
  const fams = await page.locator(".tfm .tfm-fams button").allInnerTexts();
  expect(fams.join("|")).toContain("역사 리플레이");
  expect(fams.join("|")).toContain("국내");

  // 국내팩 시나리오를 골라 적용 → 좌측 칩이 그 패밀리로 갱신
  await page.locator(".tfm .tfm-search").fill("반도체");
  await page.locator(".tfm .tfm-row").first().click();
  await expect(page.locator(".tfm-sel-t")).toContainText("반도체");
  await page.locator(".as-fb-apply", { hasText: "이 시나리오로 검증" }).click();

  await expect(page.locator(".tfm")).toHaveCount(0);
  await expect(page.locator(".tfc-chip-tk").first()).toContainText("국내");
  // 창이 선택을 주도하므로 국내팩 카드 안의 중복 버튼 목록은 사라져야 한다
  // (hidden 속성은 display:flex에 밀렸던 이력 — 조건부 렌더를 회귀로 고정)
  expect(await page.locator(".as-krs-list").count(), "duplicate KR scenario list removed").toBe(0);

  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/�/);
  expect(uniq(sink.pageErrors), "stress window page errors").toEqual([]);
  expect(uniq(sink.api404), "stress window API 404s").toEqual([]);
});

// 정직성 회귀: 역사 리플레이는 실제 시세 재생이라 강도 배율이 적용되지 않는다고 창이 밝혀야 한다.
test("Stress: historical replay honestly states severity does not apply", async ({ page }) => {
  await page.goto("/allocation/stress", { waitUntil: "networkidle" });
  await page.locator(".as-fb-apply", { hasText: "시나리오 창에서 선택" }).click();
  await page.locator(".tfm .tfm-search").fill("코로나");
  await page.locator(".tfm .tfm-row").first().click();
  await expect(page.locator(".tfm-right")).toContainText("강도 배율이 적용되지 않습니다");
  await expect(page.locator(".tfm-note")).toContainText("합성하지 않고");
});
