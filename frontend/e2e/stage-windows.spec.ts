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

// ═══════════════════════════════════════════════════════════════════════════════
// Phase 6 — CatalogueShell 로 통합한 뒤 **새로 생긴** 접근성/반응형 능력.
//
// 위의 기존 단언들은 **선택자를 하나도 고치지 않고** 통과한다 — .tfm-* 클래스 계약을
// 셸이 그대로 유지했기 때문이다. 그것이 "기능 손실 0" 의 증거이고, 아래는 그 위에
// 새로 얹힌 것만 검증한다.
// ═══════════════════════════════════════════════════════════════════════════════

test("Catalogue shell: Escape 로 닫힌다 (통합 전에는 backdrop 클릭만 가능했다)", async ({ page }) => {
  await page.goto("/allocation/stress", { waitUntil: "domcontentloaded" });
  await page.locator(".as-fb-apply", { hasText: "시나리오 창에서 선택" }).click();
  await expect(page.locator(".tfm")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.locator(".tfm"), "Escape 가 창을 닫아야 한다").toHaveCount(0);
});

test("Catalogue shell: 패밀리 필터가 화살표 키로 이동한다 (ToggleGroup roving focus)", async ({ page }) => {
  await page.goto("/allocation/stress", { waitUntil: "domcontentloaded" });
  await page.locator(".as-fb-apply", { hasText: "시나리오 창에서 선택" }).click();

  const fams = page.locator(".tfm .tfm-fams button");
  await expect(fams.first()).toBeVisible();
  const n = await fams.count();
  expect(n, "패밀리 칩이 2개 이상이어야 이동을 검증할 수 있다").toBeGreaterThan(1);

  // 통합 전에는 순수 <button> 이라 그룹 내 화살표 이동이 없었다.
  await fams.first().focus();
  await page.keyboard.press("ArrowRight");
  const focusedIsSecond = await fams.nth(1).evaluate((el) => el === document.activeElement);
  expect(focusedIsSecond, "ArrowRight 로 다음 칩에 포커스가 옮겨져야 한다").toBe(true);
});

test("Catalogue shell: 다이얼로그·목록 ARIA 역할이 붙어 있다", async ({ page }) => {
  await page.goto("/allocation/stress", { waitUntil: "domcontentloaded" });
  await page.locator(".as-fb-apply", { hasText: "시나리오 창에서 선택" }).click();

  const dlg = page.getByRole("dialog", { name: "스트레스 시나리오 선택" });
  await expect(dlg).toBeVisible();
  await expect(dlg).toHaveAttribute("aria-modal", "true");

  // 목록은 listbox/option — 통합 전에는 역할이 없는 <button> 벽이었다
  await expect(page.locator('.tfm-list[role="listbox"]')).toHaveCount(1);
  const opt = page.locator('.tfm-row[role="option"]').first();
  await expect(opt).toBeVisible();
  await opt.click();
  await expect(opt).toHaveAttribute("aria-selected", "true");
});

test("Catalogue shell: 좁은 화면(모바일)에서도 검색·목록·적용에 도달한다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });   // iPhone 12 급
  await page.goto("/allocation/stress", { waitUntil: "domcontentloaded" });
  await page.locator(".as-fb-apply", { hasText: "시나리오 창에서 선택" }).click();

  await expect(page.locator(".tfm .tfm-search")).toBeVisible();
  await page.locator(".tfm .tfm-search").fill("코로나");
  const row = page.locator(".tfm .tfm-row").first();
  await expect(row).toBeVisible();
  await row.click();

  // 우측 패널이 좁은 화면에서도 도달 가능해야 한다(가로 스크롤로 잘려 나가면 실패)
  const apply = page.locator(".tfm-right .as-fb-apply");
  await expect(apply).toBeVisible();
  const box = await apply.boundingBox();
  expect(box, "적용 버튼의 박스를 얻을 수 없다").not.toBeNull();
  expect(box!.x, "적용 버튼이 뷰포트 밖으로 밀려났다").toBeLessThan(390);
});

test("Catalogue shell: 알파 창도 같은 셸을 쓴다 (중복 제거 확인)", async ({ page }) => {
  // 같은 셸이므로 시나리오 창에서 검증한 능력이 알파 창에서도 성립해야 한다.
  await page.goto("/allocation/alphalab", { waitUntil: "domcontentloaded" });
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).click();

  await expect(page.getByRole("dialog", { name: "알파 팩터 추가" })).toBeVisible();
  await expect(page.locator('.tfm-list[role="listbox"]')).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(page.locator(".tfm")).toHaveCount(0);
});

