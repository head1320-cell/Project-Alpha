import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 매크로 콕핏 서브탭 — 접근성 계약 (UI/UX 현대화 P7)
// ─────────────────────────────────────────────────────────────────────────────
// ★구현이 아니라 계약을 지킨다★
// 이 탭 바는 Radix Tabs 로 바꿨다가 되돌렸다 — /macro 가 243 → 254 kB(+11)가 됐고
// ADR 001 한도는 4 kB 인데, 탭 바는 늘 보이므로 dynamic 으로 뺄 수도 없다.
// 그래서 손수 만들되 **Radix 가 주던 것과 같은 행동**을 요구한다:
// roving tabindex(활성 탭만 0), 화살표·Home/End 이동, aria-selected/controls 연결.
//
// 이 스펙이 있으면 구현이 무엇이든(손수 만든 것이든 나중에 다시 Radix 든) 계약은 같다.
// ═══════════════════════════════════════════════════════════════════════════════

test("매크로 탭: 화살표·Home·End 로 이동하고 포커스가 따라간다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/macro", { waitUntil: "networkidle" });

  const tabs = page.locator(".mc-tabs .mc-tab");
  const n = await tabs.count();
  expect(n, "서브탭 개수").toBeGreaterThan(4);

  // roving tabindex — 활성 탭만 0, 나머지는 -1(그래야 Tab 한 번에 탭 바를 지나간다)
  await expect(tabs.filter({ has: page.locator(":scope") }).first()).toBeVisible();
  expect(await page.locator('.mc-tabs .mc-tab[tabindex="0"]').count(), "tabindex=0 은 하나").toBe(1);
  expect(await page.locator('.mc-tabs .mc-tab[tabindex="-1"]').count()).toBe(n - 1);

  await tabs.first().focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.nth(1), "→ 로 다음 탭이 선택된다").toHaveAttribute("aria-selected", "true");
  await expect(tabs.nth(1), "포커스도 함께 옮겨간다").toBeFocused();

  await page.keyboard.press("End");
  await expect(tabs.nth(n - 1), "End 로 마지막 탭").toHaveAttribute("aria-selected", "true");

  await page.keyboard.press("Home");
  await expect(tabs.first(), "Home 으로 첫 탭").toHaveAttribute("aria-selected", "true");

  await page.keyboard.press("ArrowLeft");
  await expect(tabs.nth(n - 1), "← 는 끝으로 감싼다").toHaveAttribute("aria-selected", "true");

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
});

test("매크로 탭: 탭과 패널이 aria 로 연결된다", async ({ page }) => {
  await page.goto("/macro", { waitUntil: "networkidle" });

  await expect(page.locator('.mc-tabs[role="tablist"]')).toBeVisible();
  const active = page.locator('.mc-tab[aria-selected="true"]');
  await expect(active).toHaveCount(1);

  // 선택된 탭이 가리키는 패널이 실제로 존재하고 그 탭을 되가리켜야 한다.
  const controls = await active.getAttribute("aria-controls");
  expect(controls, "aria-controls").toBeTruthy();
  const panel = page.locator(`#${controls}`);
  await expect(panel).toBeVisible();
  await expect(panel).toHaveAttribute("aria-labelledby", (await active.getAttribute("id")) as string);
  await expect(panel).toHaveAttribute("role", "tabpanel");
});

test("매크로 탭: 클릭 이동은 그대로 동작한다 (기존 계약)", async ({ page }) => {
  await page.goto("/macro", { waitUntil: "networkidle" });
  const tabs = page.locator(".mc-tabs .mc-tab");
  await tabs.nth(2).click();
  await expect(tabs.nth(2)).toHaveClass(/\bon\b/);
  await expect(tabs.nth(2)).toHaveAttribute("aria-selected", "true");
});
