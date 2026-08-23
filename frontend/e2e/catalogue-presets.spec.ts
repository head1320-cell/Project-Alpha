import { expect, test } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 카탈로그 셸: 프리셋 + 초안/적용본 비교 (스펙 §8.1 요구 11·12, Phase 6d).
//
// 이 둘은 네 창 어디에도 없던 **신규 기능**이다(Phase 6 의 게이트가 "기능 손실 0" 이라
// 일부러 빼 뒀다). 그래서 여기서 증명할 것은 "마이그레이션이 안 깨졌다" 가 아니라
// **기능이 실제로 동작하는가** 다:
//   · 저장한 프리셋이 목록에 남고, 불러오면 설정이 되돌아오고, 지우면 사라진다.
//   · 비교가 **바뀐 항목만** 보여주고, 비교 대상이 없을 때는 "차이 없음" 이라고 하지 않는다.
//
// ★"비교 대상 없음" 과 "차이 없음" 은 다른 사실이다★
// 둘을 같은 문구로 적으면, 처음 담는 팩터를 두고 "적용본과 같습니다" 라고 말하게 된다.
// ═══════════════════════════════════════════════════════════════════════════════

/** 프리셋은 localStorage 다 — 스펙 간 누수를 막으려면 매번 지우고 시작한다. */
test.beforeEach(async ({ page }) => {
  await page.goto("/allocation/timing", { waitUntil: "domcontentloaded" });
  await page.evaluate(() => localStorage.removeItem("alpha:catalogue-presets"));
});

async function openFactorWindow(page: import("@playwright/test").Page) {
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).first().click();
  await expect(page.locator(".tfm-row").first()).toBeVisible({ timeout: 20_000 });
}

async function pickFactor(page: import("@playwright/test").Page, search: string) {
  await page.locator(".tfm-search").fill(search);
  await expect(page.locator(".tfm-row").first()).toBeVisible({ timeout: 20_000 });
  await page.locator(".tfm-row").first().click();
}

// ═══════════════════════════════════════════════════════════════════════════════
// 1. 프리셋 (§8.1 요구 11)
// ═══════════════════════════════════════════════════════════════════════════════
test("프리셋: 저장하면 목록에 남고, 불러오면 그 설정이 돌아온다", async ({ page }) => {
  const sink = trackErrors(page);
  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");

  // 기본값과 다른 임계로 바꿔 둔다 — 되돌아왔는지 알아보려면 기본값이면 안 된다.
  const thr = page.locator(".tfm .as-tm-num").last();
  await thr.fill("0.42");

  await expect(page.locator(".tfm-preset-empty")).toBeVisible();
  await page.locator(".tfm-preset-name").fill("내 모멘텀 설정");
  await page.locator(".tfm-preset-add").click();

  const row = page.locator(".tfm-preset-row", { hasText: "내 모멘텀 설정" });
  await expect(row).toBeVisible({ timeout: 10_000 });

  // 설정을 흐트러뜨린 뒤 불러와야 복원이 실제로 일어났는지 알 수 있다.
  await thr.fill("9.99");
  await expect(thr).toHaveValue("9.99");
  await row.locator(".tfm-preset-load").click();
  await expect(thr, "프리셋을 불러왔는데 설정이 돌아오지 않았다").toHaveValue("0.42");

  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
});

test("프리셋: 새로고침해도 남아 있다 (휘발성 상태가 아니다)", async ({ page }) => {
  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");
  await page.locator(".tfm-preset-name").fill("지속성 확인");
  await page.locator(".tfm-preset-add").click();
  await expect(page.locator(".tfm-preset-row", { hasText: "지속성 확인" })).toBeVisible();

  await page.reload({ waitUntil: "networkidle" });
  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");
  await expect(page.locator(".tfm-preset-row", { hasText: "지속성 확인" }),
    "새로고침 후 프리셋이 사라졌다").toBeVisible({ timeout: 10_000 });
});

test("프리셋: 삭제하면 사라진다", async ({ page }) => {
  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");
  await page.locator(".tfm-preset-name").fill("지울 것");
  await page.locator(".tfm-preset-add").click();

  const row = page.locator(".tfm-preset-row", { hasText: "지울 것" });
  await expect(row).toBeVisible();
  await row.locator(".tfm-preset-del").click();
  await expect(row).toHaveCount(0, { timeout: 10_000 });
  await expect(page.locator(".tfm-preset-empty")).toBeVisible();
});

test("프리셋: 이 브라우저에만 있다는 사실을 숨기지 않는다", async ({ page }) => {
  // 룰셋 버전(7c)과 달리 프리셋은 재현 좌표가 아니다 — 화면이 그렇게 말해야 한다.
  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");
  await expect(page.locator(".tfm-preset-note")).toContainText("브라우저");
  await expect(page.locator(".tfm-preset-note")).toContainText("재현");
});

// ═══════════════════════════════════════════════════════════════════════════════
// 2. 초안 vs 적용본 (§8.1 요구 12)
// ═══════════════════════════════════════════════════════════════════════════════
test("비교: 아직 담지 않은 팩터는 '차이 없음'이 아니라 '비교 대상 없음'이다", async ({ page }) => {
  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");

  const cmp = page.locator(".tfm-cmp");
  await expect(cmp).toBeVisible();
  await expect(page.locator(".tfm-cmp-none"), "적용본이 없는데 비교를 지어냈다").toBeVisible();
  await expect(page.locator(".tfm-cmp-none")).toContainText("적용된 설정이 없습니다");
  await expect(page.locator(".tfm-cmp-same")).toHaveCount(0);
});

test("비교: 담은 뒤 값을 바꾸면 바뀐 항목만 이전→이후로 보인다", async ({ page }) => {
  const sink = trackErrors(page);
  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");
  const thr = page.locator(".tfm .as-tm-num").last();
  await thr.fill("0.11");
  await page.locator(".as-fb-apply", { hasText: "이 팩터 추가" }).click();

  // 같은 팩터를 다시 열면 이제 '적용본' 이 존재한다.
  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");
  await expect(page.locator(".tfm-cmp-none")).toHaveCount(0);

  // 기본 임계로 돌아왔으므로 임계가 다르다 → 그 줄이 보여야 한다.
  const rows = page.locator(".tfm-cmp-row");
  await expect(rows.first()).toBeVisible({ timeout: 10_000 });
  const cmpText = await page.locator(".tfm-cmp").innerText();
  expect(cmpText, "이전 값(0.11)이 비교에 없다").toContain("0.11");

  // 티커는 안 건드렸으니 변경 목록에 없어야 한다 — 같은 값을 나열하면 변화가 묻힌다.
  expect(cmpText, "바뀌지 않은 항목까지 나열하고 있다").not.toContain("티커");

  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
});

test("비교: 적용본과 똑같이 맞추면 '바뀌는 것이 없다'고 말한다", async ({ page }) => {
  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");
  const thr = page.locator(".tfm .as-tm-num").last();
  const applied = await thr.inputValue();          // 기본값 그대로 적용
  await page.locator(".as-fb-apply", { hasText: "이 팩터 추가" }).click();

  await openFactorWindow(page);
  await pickFactor(page, "평균 절대 모멘텀");
  await expect(thr).toHaveValue(applied);
  await expect(page.locator(".tfm-cmp-same")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".tfm-cmp-row")).toHaveCount(0);
});
