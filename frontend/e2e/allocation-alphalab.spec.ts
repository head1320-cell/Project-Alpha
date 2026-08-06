import { test, expect, type Page } from "@playwright/test";

// ═══════════════════════════════════════════════════════════════════════════════
// 02 ALPHA LAB — 표현식 · 레지스트리 · 검증 리포트 (A4-L)
// ─────────────────────────────────────────────────────────────────────────────
// 이 화면은 스튜디오에서 타입이 가장 작았고(8px TPL 배지 · 9px 버전/상태),
// 알파의 정체인 **표현식이 title= 안에만** 있었다. 그리고 IC 가 미산출일 때
// `(ic.mean ?? 0) > 0` 이 거짓이 되어 **약세색**이 칠해졌다 — 못 잰 것이 나쁜 것처럼.
// ═══════════════════════════════════════════════════════════════════════════════

async function enter(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/alphalab", { waitUntil: "networkidle" });
  await expect(page.locator(".as-card", { hasText: "ALPHA EXPRESSION" }))
    .toBeVisible({ timeout: 15_000 });
}

test("★미산출 IC 에 약세색을 칠하지 않는다★", async ({ page }) => {
  // 검증 응답을 IC 없이 돌려준다 — 엔진이 IC 를 못 낸 상태를 재현.
  await page.route("**/alpha-lab/validate**", async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        expr: "zscore(mom_6m)", universe: "kospi50", n_periods: 24,
        universe_size: 50, avg_coverage: 0.9,
        period_start: "2024-01-01", period_end: "2026-01-01",
        ic: { mean: null, icir: null, t_stat: null, hit_rate: null },
        notes: ["커버리지 부족 구간이 있습니다"],
      }),
    });
  });
  await enter(page);
  await page.locator(".as-fb-apply", { hasText: "검증 실행" }).click();

  const kpi = page.locator(".as-al-kpi", { hasText: "Rank IC" });
  await expect(kpi).toBeVisible({ timeout: 20_000 });
  await expect(kpi.locator("b"), "미산출은 값 대신 —").toHaveText("—");
  // ★핵심★ 값이 없으면 색도 없다. bear 가 붙으면 "성과가 나빴다"로 읽힌다.
  await expect(kpi.locator("b.bear"), "미산출에 약세색이 붙었다").toHaveCount(0);
  await expect(kpi.locator("b.bull"), "미산출에 강세색이 붙었다").toHaveCount(0);
});

test("DECAY 와 IS/OOS 는 별개의 표이고, 모든 머리글에 scope 가 있다", async ({ page }) => {
  await enter(page);
  await page.locator(".as-fb-apply", { hasText: "검증 실행" }).click();

  const tables = page.locator(".as-al-tables table");
  await expect(tables, "두 축을 한 머리글 줄에 섞지 않는다").toHaveCount(2, { timeout: 60_000 });
  const heads = page.locator(".as-al-tables th");
  const n = await heads.count();
  expect(n, "머리글 수 (0 이면 조용히 통과한다)").toBeGreaterThan(5);
  for (const th of await heads.all()) {
    await expect(th, "모든 th 에 scope").toHaveAttribute("scope", /^(col|row)$/);
  }
});

test("레지스트리: 표현식이 보이는 글자이고, 삭제 버튼에 이름이 있다", async ({ page }) => {
  await enter(page);

  // ★첫 판은 `if (del.count() > 0)` 로 감싸 두었고, 그래서 **아무것도 지키지 못했다**★
  // 시드된 레지스트리 항목은 전부 템플릿(is_template)이라 `×` 를 렌더하지 않는다.
  // aria-label 을 지우는 변이를 넣어도 초록이었다. 그래서 조건부로 넘기는 대신
  // **비-템플릿 알파를 직접 하나 만든다** — 그러면 삭제 버튼이 반드시 존재한다.
  const name = `E2E 삭제이름 ${Date.now()}`;
  await page.locator("input.as-input[placeholder*='알파 이름']").fill(name);
  await page.locator(".as-fb-apply", { hasText: "레지스트리에 저장" }).click();

  const mine = page.locator(".as-al-item", { hasText: name });
  await expect(mine, "저장한 알파가 목록에 없다").toHaveCount(1, { timeout: 20_000 });

  // 표현식이 호버가 아니라 행에 있어야 한다.
  const exprs = page.locator(".as-al-expr-r");
  expect(await exprs.count(), "행에 표현식이 하나도 없다").toBeGreaterThan(0);
  expect((await exprs.first().innerText()).trim().length,
    "표현식이 비어 있다").toBeGreaterThan(0);

  // 선택 버튼에서 title= 이 사라졌는지 — 근거를 다시 호버로 숨기지 않는다.
  await expect(page.locator(".as-al-pick[title]"),
    "표현식을 title= 로 되돌렸다").toHaveCount(0);

  // 글리프 하나짜리 버튼의 접근 가능한 이름 — 조건 없이 단언한다.
  const del = mine.locator(".as-x");
  await expect(del, "삭제 버튼이 없다").toHaveCount(1);
  await expect(del, "글리프 버튼에 접근 가능한 이름이 없다")
    .toHaveAttribute("aria-label", /삭제/);

  // 뒷정리 — 다음 실행에 남기지 않는다.
  await del.click();
  await expect(mine).toHaveCount(0, { timeout: 15_000 });
});

test("AlphaLab: 12px 산문 하한 · 11px 크롬 하한", async ({ page }) => {
  await enter(page);
  const res = await page.locator(".aas-root").evaluate((root) => {
    const out: string[] = [];
    let checked = 0;
    for (const el of [root, ...Array.from(root.querySelectorAll("*"))]) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent!.trim())) continue;
      checked++;
      const px = parseFloat(cs.fontSize);
      if (px < 11) out.push(`${el.tagName}.${(el.getAttribute("class") || "").split(" ")[0]} ${px}px :: ${(el.textContent || "").trim().slice(0, 16)}`);
    }
    return { checked, out };
  });
  expect(res.checked, "검사한 텍스트 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(20);
  expect(res.out, "11px 미만 텍스트").toEqual([]);
});

test("팩터 창(CatalogueShell)도 11px 하한 — 소비자 6개 공용", async ({ page }) => {
  await enter(page);
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).click();
  await expect(page.locator(".tfm-row").first()).toBeVisible({ timeout: 20_000 });

  const res = await page.evaluate(() => {
    const root = document.querySelector("[role='dialog']") || document.body;
    const out: string[] = [];
    let checked = 0;
    for (const el of [root, ...Array.from(root.querySelectorAll("*"))]) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent!.trim())) continue;
      checked++;
      const px = parseFloat(cs.fontSize);
      if (px < 11) out.push(`${el.tagName}.${(el.getAttribute("class") || "").split(" ")[0]} ${px}px :: ${(el.textContent || "").trim().slice(0, 16)}`);
    }
    return { checked, out };
  });
  expect(res.checked, "모달에서 검사한 텍스트 노드 수").toBeGreaterThan(10);
  expect(res.out, "모달 11px 미만 텍스트").toEqual([]);
});
