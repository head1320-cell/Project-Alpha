import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// AAS TIMING 통합 팩터 창 — 기존 카나리(cramped inline rows)를 팩터 칩 + 단일 모달로 통합.
// 회귀 방지: 창이 열리고 5개 패밀리가 모두 노출되며, 신규 팩터를 검색→설정→추가하면 칩이 늘어난다.
test("AAS Timing: unified factor window lists all families and adds a new factor", async ({ page }) => {
  const sink = trackErrors(page);

  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });

  // 기존의 비좁은 인라인 카나리 편집 행은 더 이상 없어야 한다(팩터 칩으로 대체)
  expect(await page.locator(".as-tm-canary").count(), "legacy cramped canary rows removed").toBe(0);
  const before = await page.locator(".tfc-chip").count();
  expect(before, "existing canaries render as factor chips").toBeGreaterThan(0);

  // 통합 팩터 창 열기
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).first().click();
  await expect(page.locator(".tfm")).toBeVisible();
  const fams = await page.locator(".tfm-fams button").allInnerTexts();
  expect(fams.length, "5 signal families in one window").toBe(5);

  // 검색 → 신규 팩터(이격도) 선택 → 파라미터 노출 → 추가
  await page.locator(".tfm-search").fill("이격");
  await expect(page.locator(".tfm-row").first()).toBeVisible();
  await page.locator(".tfm-row").first().click();
  await expect(page.locator(".tfm-sel-t")).toContainText("이격도");
  await page.locator(".as-fb-apply", { hasText: "이 팩터 추가" }).click();

  await expect(page.locator(".tfm")).toHaveCount(0);           // 모달 닫힘
  await expect(page.locator(".tfc-chip")).toHaveCount(before + 1);
  await expect(page.locator(".tfc-chip-t").last()).toContainText("이격도");

  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/�/);
  expect(uniq(sink.pageErrors), "timing factor window page errors").toEqual([]);
  expect(uniq(sink.api404), "timing factor window API 404s").toEqual([]);
});

// 정직성 회귀: 유료 컨텐츠 조건식을 재현했다고 주장하지 않는다는 노트가 창에 항상 보여야 한다.
test("AAS Timing: factor window shows the provenance/honesty note", async ({ page }) => {
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).first().click();
  await expect(page.locator(".tfm-note")).toContainText("유료");
  await expect(page.locator(".tfm-note")).toContainText("재현한 것이 아닙니다");
});
