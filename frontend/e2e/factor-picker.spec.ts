import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// FactorPickerModal — CatalogueShell 이전 후의 안전망 (Phase 11c)
//
// ★이 파일은 다시 쓰였다. 그 사실을 숨기지 않는다★
// 6c 가 깐 원본은 "구조가 아니라 동작으로 단정하니 셸로 옮긴 뒤에도 그대로 게이트가 된다"
// 고 적었지만, 실제로는 6개 중 4개가 **2단계 모델 자체**를 단정하고 있었다 —
// `STEP2 함수 선택` 버튼의 disabled/enabled · `다음 단계` · `이전 단계` · `STEP1 팩터 선택`.
// 그건 일반적인 동작이 아니라 그 창에만 있던 단계 UI 였고, 단계를 없애는 변경 앞에서는
// 그물이 아니라 걸림돌이다. 그래서 **덮는 동작은 늘리면서** 단계 의존만 걷어냈다.
//
// 무엇이 바뀌었나: 셸은 단계가 없다. 좌측에서 고르면 우측 패널이 나타난다 — 그게 셸의
// 고유 흐름이고, "STEP2 를 우측 패널로" 라는 결정의 논리적 귀결이다.
//
// ★출력 계약은 바뀌지 않는다★ `FactorPick` 은 소비자 둘(백테스터 수식 빌더 · 스크리너)이
// 읽는다. 특히 `innerFunctionId`(중첩)는 화면에는 거의 안 보이지만 수식에는 그대로 나타난다 —
// 아래 중첩 테스트가 그 필드가 살아 있는지를 지키는 유일한 장치다.
// ═══════════════════════════════════════════════════════════════════════════════

const SEARCH = "조건을 단어로 입력하세요";
const FACTOR = "시가총액";

async function openFromScreener(page: import("@playwright/test").Page) {
  await page.goto("/screener", { waitUntil: "networkidle" });
  await page.locator(".bsc-add-btn").first().click();
  await expect(page.getByPlaceholder(SEARCH)).toBeVisible();
}

async function openFromBacktester(page: import("@playwright/test").Page) {
  await page.goto("/backtest", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /^팩터$/ }).first().click();
  await expect(page.getByPlaceholder(SEARCH)).toBeVisible();
}

/** 미리보기만 가리키는 범위 — 같은 토큰 문자열이 행·상세·미리보기 셋 다에 나온다. */
const preview = (page: import("@playwright/test").Page) => page.locator(".fp-preview");

/**
 * 좌측 목록에서 팩터 하나를 고른다 (검색으로 좁힌 뒤 행 클릭).
 *
 * ★부분일치로 고르면 **다른 팩터**를 고르게 된다★ "영업이익" 검색은 "1인당영업이익"·
 * "영업이익률"·"영업이익성장율" 도 잡고, 그중 하나가 목록에서 먼저 온다(실측: 1인당영업이익).
 * 그래서 설명 칸의 토큰을 정확일치로 지목한다.
 */
async function pickFactor(page: import("@playwright/test").Page, name = FACTOR) {
  await page.getByPlaceholder(SEARCH).fill(name);
  const row = page.locator(".tfm-row")
    .filter({ has: page.locator(`.tfm-row-d:text-is("{${name}}")`) }).first();
  await expect(row).toBeVisible();
  await row.click();
}

// ─── 1. 단일 화면 계약 — 고르기 전에는 설정이 없다 ────────────────────────────
test("Factor picker: 팩터를 고르기 전에는 함수 설정이 나타나지 않는다", async ({ page }) => {
  await openFromScreener(page);

  // 우측 패널은 셸의 빈 상태다. 미리보기도 적용 버튼도 아직 없다 —
  // 없는 것을 단정해야 "선택이 실제로 무언가를 연다"가 증명된다.
  await expect(page.getByText("왼쪽에서 항목을 선택하세요")).toBeVisible();
  await expect(page.getByText("조건식 미리보기")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "입력", exact: true })).toHaveCount(0);

  await pickFactor(page);
  await expect(page.getByText("조건식 미리보기")).toBeVisible();
  await expect(page.getByRole("button", { name: "입력", exact: true })).toBeEnabled();
});

test("Factor picker: 팩터 → 함수 → 입력 왕복이 스크리너 필터를 만든다", async ({ page }) => {
  const sink = trackErrors(page);
  await openFromScreener(page);

  // 삽입 전에는 '전체 초기화'(조건이 1개 이상일 때만 렌더)가 없다
  await expect(page.locator(".bsc-rail-clear")).toHaveCount(0);

  await pickFactor(page);
  await expect(preview(page)).toHaveText(`{${FACTOR}}`);
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

  // 기본(원값)은 토큰 그대로
  await expect(preview(page)).toHaveText(`{${FACTOR}}`);

  await page.getByRole("button", { name: "이동평균", exact: true }).click();
  await expect(
    preview(page),
    "함수를 골랐는데 조건식이 그대로면 선택이 반영되지 않은 것",
  ).toHaveText(/^이동평균\(\{시가총액\}/);
});

// ─── 3. 단계가 없어도 선택은 유지된다 (원본 "이전 단계" 테스트의 대체) ────────
// 단계를 오갈 때 선택이 날아가지 않는 것이 원본의 관심사였다. 단계가 사라졌으니
// 같은 관심사를 이 화면의 말로 옮긴다 — 팩터를 바꿔도 고른 함수는 남아야 한다.
test("Factor picker: 팩터를 바꿔도 고른 함수 설정이 남는다", async ({ page }) => {
  await openFromScreener(page);
  await pickFactor(page);
  await page.getByRole("button", { name: "이동평균", exact: true }).click();
  await expect(preview(page)).toHaveText(/^이동평균\(\{시가총액\}/);

  // 다른 팩터로 갈아탄다 — 함수를 처음부터 다시 고르게 만들면 안 된다
  await pickFactor(page, "영업이익");
  await expect(
    preview(page),
    "팩터를 바꿨더니 함수 선택이 초기화됐습니다",
  ).toHaveText(/^이동평균\(\{영업이익\}/);
});

// ─── 4. 정직성 — 미지원 팩터를 감추지도, 쓸 수 있는 척하지도 않는다 ──────────
test("Factor picker: 미지원 팩터는 사유가 목록에 적히고 적용이 막힌다", async ({ page }) => {
  await openFromScreener(page);

  // ★미지원이 있는 카테고리로 먼저 간다★ 기본 카테고리(기본정보)는 전부 지원이라
  // 곧장 `.off` 를 찾으면 "없다" 가 나온다 — 그건 정직성이 깨진 것이 아니라 잘못 본 것이다.
  const counts = await page.locator(".tfm-fam-n").allInnerTexts();
  const idx = counts.findIndex((t) => {
    const [ok, all] = t.split("/").map(Number);
    return Number.isFinite(ok) && Number.isFinite(all) && ok < all;
  });
  expect(idx, "미지원이 하나라도 있는 카테고리가 없습니다 — 지원맵을 확인하세요")
    .toBeGreaterThanOrEqual(0);
  await page.locator(".tfm-fams button").nth(idx).click();

  const off = page.locator(".tfm-row.off").first();
  await expect(off, "미지원 행이 하나도 없습니다 — 지원맵이 로드되지 않았을 수 있습니다")
    .toBeVisible({ timeout: 20_000 });
  await expect(off.locator(".tfm-off")).toHaveText("미가용");

  // 사유는 툴팁이 아니라 화면에 (셸이 세 창에 준 것과 같은 규칙)
  const reason = (await off.locator(".tfm-row-p").innerText()).trim();
  expect(reason.length, "미가용 사유가 행에 적혀 있지 않습니다").toBeGreaterThan(0);
  expect(await off.getAttribute("title"), "사유를 툴팁에 숨겼습니다").toBeNull();

  // 고를 수는 있지만 적용은 막힌다 — 고를 수조차 없으면 왜 못 쓰는지 볼 기회가 없다
  await off.click();
  await expect(page.getByRole("button", { name: "입력", exact: true })).toBeDisabled();
});

test("Factor picker: 카테고리별 지원 개수를 그대로 노출한다", async ({ page }) => {
  await openFromScreener(page);
  // 0/7 처럼 전부 미지원인 묶음도 숨기지 않는다 — 눌러 보고서야 아는 것이 더 나쁘다
  await expect(page.locator(".tfm-fam-n").first()).toHaveText(/^\d+\/\d+$/);
});

// ─── 5. 대화상자 계약 ─────────────────────────────────────────────────────────
test("Factor picker: 모달 계약 — role·aria-modal·Escape·자동 포커스", async ({ page }) => {
  await openFromScreener(page);

  const dlg = page.getByRole("dialog", { name: "팩터 선택" });
  await expect(dlg).toBeVisible();
  await expect(dlg).toHaveAttribute("aria-modal", "true");
  await expect(page.getByPlaceholder(SEARCH)).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(page.getByPlaceholder(SEARCH)).toHaveCount(0);
});

test("Factor picker: 포커스 트랩 — Tab 이 창 밖으로 걸어 나가지 않는다", async ({ page }) => {
  await openFromScreener(page);
  const dlg = page.getByRole("dialog", { name: "팩터 선택" });
  for (let i = 0; i < 25; i++) await page.keyboard.press("Tab");
  await expect(
    dlg.locator(":focus"),
    "Tab 을 계속 눌렀더니 포커스가 창 밖으로 나갔습니다",
  ).toHaveCount(1);
});

// ─── 6. 두 번째 소비자 — 백테스터에서도 같은 창이 열린다 ─────────────────────
test("Factor picker: 백테스터 수식 빌더에서도 같은 창이 열린다", async ({ page }) => {
  const sink = trackErrors(page);
  await openFromBacktester(page);
  await expect(page.getByRole("dialog", { name: "팩터 선택" })).toBeVisible();

  await page.getByRole("button", { name: "닫기" }).click();
  await expect(page.getByPlaceholder(SEARCH)).toHaveCount(0);

  expect(uniq(sink.pageErrors), "backtester picker page errors").toEqual([]);
  expect(uniq(sink.api404), "backtester picker API 404s").toEqual([]);
});

// ─── 7. 출력 계약 — 중첩이 FactorPick 에 살아남는다 ──────────────────────────
// ★이 창의 출력 중 화면에서 가장 안 보이는 부분이 중첩이다★ `innerFunctionId` 가 빠져도
// 창은 멀쩡해 보이고, 수식만 조용히 틀려진다(이동평균(과거값(종가,1),20) → 이동평균(종가,20)).
// 그래서 창이 아니라 **삽입된 수식 칩**을 읽는다 — 소비자가 실제로 받는 것이 그것이다.
test("Factor picker: 중첩(내부 지표)이 삽입된 수식에 그대로 나타난다", async ({ page }) => {
  await openFromBacktester(page);
  await pickFactor(page);

  // 바깥 함수 → 그다음 내부 지표. 순서가 바뀌면 내부 지표 셀렉트가 아직 없다.
  await page.getByRole("button", { name: "이동평균", exact: true }).click();
  const inner = page.locator(".fp-inner-fn");
  await expect(inner, "내부 지표 선택이 없습니다 — allowNesting 이 전달되지 않았을 수 있습니다")
    .toBeVisible();
  await inner.selectOption({ label: "과거값" });

  // 미리보기에 중첩이 보인다
  await expect(preview(page)).toHaveText(/^이동평균\(과거값\(\{시가총액\}/);

  await page.getByRole("button", { name: "입력", exact: true }).click();

  // ★소비자가 받은 것을 읽는다★ 칩 라벨은 renderTermExpr 의 결과다 —
  // innerFunctionId 가 빠지면 여기서 중첩이 사라진다.
  const chip = page.locator(".fb-chip").first();
  await expect(chip).toBeVisible();
  await expect(
    chip,
    "삽입된 수식에서 중첩이 사라졌습니다 — innerFunctionId 가 전달되지 않았습니다",
  ).toContainText("과거값");
  await expect(chip).toContainText("이동평균");
});
