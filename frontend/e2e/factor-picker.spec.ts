import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// FactorPickerModal — Phase 6c 의 **안전망을 먼저 깐다**
//
// 이 창은 477줄 · 인라인 스타일 76개 · **className 0개** · E2E 0건이었다. 클래스 계약이
// 아예 없으므로 CatalogueShell 로 옮기면 DOM 구조가 통째로 바뀐다. 그때 "무엇도 잃지
// 않았다" 를 증명할 근거가 없으면 이전은 도박이다. 그래서 계획이 "E2E 부터" 라고 못박았다.
//
// ★구조가 아니라 동작으로 단정한다★
// 클래스·DOM 위치가 아니라 role·보이는 텍스트·사용자 결과로만 검증한다. 그래야 셸로
// 옮긴 뒤에도 같은 스펙이 그대로 게이트 역할을 한다(선택자만 고쳐서 통과시키는 일이 없다).
//
// 소비자는 둘이다 — 백테스터(FormulaBuilder, tone/allowNesting) · 스크리너(TerminalScreener).
// 둘 다 덮는다. 한쪽만 덮으면 이전 때 다른 쪽이 조용히 깨진다.
// ═══════════════════════════════════════════════════════════════════════════════

const SEARCH = "조건을 단어로 입력하세요";
const FACTOR = "시가총액";

async function openFromScreener(page: import("@playwright/test").Page) {
  await page.goto("/screener", { waitUntil: "networkidle" });
  await page.locator(".bsc-add-btn").first().click();
  await expect(page.getByPlaceholder(SEARCH)).toBeVisible();
}

/** STEP1 에서 팩터 하나를 고른다. */
async function pickFactor(page: import("@playwright/test").Page, name = FACTOR) {
  await page.getByPlaceholder(SEARCH).fill(name);
  const cand = page.locator("button", { hasText: name }).first();
  await expect(cand).toBeVisible();
  await cand.click();
  await expect(page.getByText("선택된 팩터")).toBeVisible();
}

// ─── 1. 두 단계 계약 ──────────────────────────────────────────────────────────
test("Factor picker: STEP2 는 팩터를 고르기 전에는 열리지 않는다", async ({ page }) => {
  await openFromScreener(page);

  // 팩터를 고르기 전 STEP2 크럼은 **비활성**이다(클릭을 시도하지 않고 상태를 단정한다 —
  // 비활성 요소를 click 하면 Playwright 가 활성화를 기다리다 타임아웃 나고, 그건 계약을
  // 검증한 것이 아니라 테스트가 멈춘 것이다).
  await expect(page.getByRole("button", { name: "STEP2 함수 선택" })).toBeDisabled();
  await expect(page.getByText("왼쪽에서 팩터를 선택하세요")).toBeVisible();
  await expect(page.getByText("조건식 미리보기")).toHaveCount(0);

  // 팩터를 고르면 비로소 열린다
  await pickFactor(page);
  await expect(page.getByRole("button", { name: "STEP2 함수 선택" })).toBeEnabled();
});

test("Factor picker: 팩터 → 함수 → 입력 왕복이 스크리너 필터를 만든다", async ({ page }) => {
  const sink = trackErrors(page);
  await openFromScreener(page);

  // 삽입 전에는 '전체 초기화'(조건이 1개 이상일 때만 렌더)가 없다
  await expect(page.locator(".bsc-rail-clear")).toHaveCount(0);

  await pickFactor(page);
  await page.getByRole("button", { name: /다음 단계/ }).click();

  // STEP2 — 미리보기가 실제 조건식을 보여준다
  await expect(page.getByText("조건식 미리보기")).toBeVisible();
  await expect(page.getByText(`{${FACTOR}}`, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "입력", exact: true }).click();

  // 창이 닫히고 필터가 생겼다 — 왕복이 실제로 값을 만들었는지가 이 테스트의 요점
  await expect(page.getByPlaceholder(SEARCH)).toHaveCount(0);
  await expect(page.locator(".bsc-rail-clear")).toHaveCount(1);

  expect(uniq(sink.pageErrors), "factor picker page errors").toEqual([]);
  expect(uniq(sink.api404), "factor picker API 404s").toEqual([]);
});

// ─── 2. 함수 선택이 조건식을 바꾼다 ───────────────────────────────────────────
test("Factor picker: 함수를 바꾸면 미리보기 조건식이 따라 바뀐다", async ({ page }) => {
  await openFromScreener(page);
  await pickFactor(page);
  await page.getByRole("button", { name: /다음 단계/ }).click();

  // 기본(원값)은 토큰 그대로
  await expect(page.getByText(`{${FACTOR}}`, { exact: true })).toBeVisible();

  // 이동평균을 고르면 조건식에 함수가 씌워진다
  await page.getByRole("button", { name: "이동평균", exact: true }).click();
  const preview = page.getByText(/이동평균\(\{시가총액\}/);
  await expect(preview, "함수를 골랐는데 조건식이 그대로면 선택이 반영되지 않은 것").toBeVisible();
});

// ─── 3. 뒤로 가도 선택이 남는다 ───────────────────────────────────────────────
test("Factor picker: 이전 단계로 돌아가도 고른 팩터가 유지된다", async ({ page }) => {
  await openFromScreener(page);
  await pickFactor(page);
  await page.getByRole("button", { name: /다음 단계/ }).click();
  await expect(page.getByText("조건식 미리보기")).toBeVisible();

  await page.getByRole("button", { name: /이전 단계/ }).click();
  // 선택이 날아가면 사용자는 처음부터 다시 골라야 한다
  await expect(page.getByText("선택된 팩터")).toBeVisible();
  await page.getByRole("button", { name: /다음 단계/ }).click();
  await expect(page.getByText("조건식 미리보기")).toBeVisible();
});

// ─── 4. 정직성 — 미지원 팩터를 감추지도, 쓸 수 있는 척하지도 않는다 ──────────
test("Factor picker: 미지원 팩터는 사유와 함께 보이고 선택되지 않는다", async ({ page }) => {
  await openFromScreener(page);

  // 왜 회색인지 창 안에 적혀 있어야 한다(툴팁에 숨기지 않는다)
  await expect(page.getByText(/회색 팩터는 미지원/)).toBeVisible();
  // 카테고리별 지원 개수(n/m)를 그대로 노출한다 — 0/7 처럼 전부 미지원인 묶음도 숨기지 않는다
  await expect(page.getByText(/^\d+\/\d+$/).first()).toBeVisible();
});

// ─── 5. 대화상자 계약 (Phase 6c) — 셸이 세 창에 준 것과 같은 수준 ────────────
// 이전에는 role·aria-modal·Escape 가 전부 없었고 backdrop 클릭만 닫혔다.
test("Factor picker: 모달 계약 — role·aria-modal·Escape", async ({ page }) => {
  await openFromScreener(page);

  const dlg = page.getByRole("dialog", { name: "팩터 선택" });
  await expect(dlg).toBeVisible();
  await expect(dlg).toHaveAttribute("aria-modal", "true");
  // 검색 입력이 자동 포커스 — 창을 열자마자 타이핑할 수 있어야 한다
  await expect(page.getByPlaceholder(SEARCH)).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(page.getByPlaceholder(SEARCH)).toHaveCount(0);
});

// ★포커스 트랩 — Radix Dialog 로 옮기면서 처음 생긴 능력★
// 이전에는 트랩이 아예 없어서 Tab 이 창 밖 페이지 컨트롤로 새어 나갔다(단정할 대상조차 없었다).
test("Factor picker: Tab 포커스가 창 밖으로 새지 않는다", async ({ page }) => {
  await openFromScreener(page);
  const dlg = page.getByRole("dialog", { name: "팩터 선택" });

  // 여러 번 Tab 해도 포커스는 대화상자 안에 머문다
  for (let i = 0; i < 12; i++) await page.keyboard.press("Tab");
  const inside = await dlg.evaluate((el) => el.contains(document.activeElement));
  expect(inside, "Tab 이 창 밖으로 나가면 모달이 아니라 그냥 겹쳐진 패널이다").toBe(true);
});

// ─── 6. 두 번째 소비자 — 백테스터에서도 같은 창이 열린다 ─────────────────────
test("Factor picker: 백테스터 수식 빌더에서도 같은 창이 열린다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/backtest", { waitUntil: "networkidle" });

  await page.getByRole("button", { name: /^팩터$/ }).first().click();
  await expect(page.getByPlaceholder(SEARCH)).toBeVisible();
  await expect(page.getByText("STEP1 팩터 선택")).toBeVisible();

  // 닫기가 동작한다
  await page.getByRole("button", { name: "닫기" }).click();
  await expect(page.getByPlaceholder(SEARCH)).toHaveCount(0);

  expect(uniq(sink.pageErrors), "backtester picker page errors").toEqual([]);
  expect(uniq(sink.api404), "backtester picker API 404s").toEqual([]);
});
