import { expect, test, type Page } from "@playwright/test";

// ═══════════════════════════════════════════════════════════════════════════════
// R0-B — 06 STRESS 는 무엇을 스트레스하는지 밝힌다
// ─────────────────────────────────────────────────────────────────────────────
// 실측된 결함: 이 화면의 비중 소비자 셋이 전부 **현재 보유**였다
// (`ScenarioContext.tsx:62` · `stress/page.tsx:61` · `:166`). 목표를 스트레스하는 곳이
// 하나도 없어서, 타이밍 오버레이로 노출을 줄여도 스트레스 숫자는 꿈쩍하지 않았다.
//
// ★2번이 이 파일의 핵심이다★ 목표가 없을 때 현재 값을 복사해 목표인 척하는 것은
// 이 저장소가 반복해 금지해 온 형태다(`?? 0`, 지어낸 커버리지 문자열…). 그 재발을 막는다.
// ═══════════════════════════════════════════════════════════════════════════════

async function seedPortfolio(page: Page) {
  await page.addInitScript(() => {
    const KEY = "alpha_alloc_wip";
    if (sessionStorage.getItem(KEY)) return;
    sessionStorage.setItem(KEY, JSON.stringify({
      holdings: [{ code: "005930", name: "삼성전자", weight: 60 },
                 { code: "000660", name: "SK하이닉스", weight: 40 }],
      views: [], model: "bl",
    }));
  });
}

/** 최적화를 돌린 뒤 **앱 안에서** 06 STRESS 로 이동한다 (결과는 전체 리로드에서 사라진다).
 *  스파인 클릭은 `dispatchEvent` 를 쓴다 — `.aas-wiz-sep` 이 스텝 중심을 덮는 결함이 있다
 *  (allocation-tpv.spec.ts 에 근거 기록). */
async function optimizeThenStress(page: Page) {
  await page.goto("/allocation/optimize", { waitUntil: "domcontentloaded" });
  const run = page.locator(".as-run").first();
  await expect(run).toBeVisible({ timeout: 20_000 });
  await run.click();
  await page.waitForTimeout(6_000);
  await page.locator(".aas-wiz-step", { hasText: "STRESS" }).first().dispatchEvent("click");
  await expect(page).toHaveURL(/\/allocation\/stress/, { timeout: 20_000 });
  await expect(page.locator(".as-rob-basis")).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(3_000);
}

function cells(page: Page) {
  return page.locator(".as-rob-basis-table tbody tr");
}

// ── 1. 두 기준이 나란히 렌더되고 라벨이 서로 다르다 ──────────────────────────
test("★스트레스 기준이 현재 보유와 목표를 나란히 보여 준다★", async ({ page }) => {
  test.setTimeout(180_000);
  await seedPortfolio(page);
  await optimizeThenStress(page);

  const band = page.locator(".as-rob-basis");
  const heads = band.locator("thead th");
  await expect(heads, "기준 표의 열 머리글이 없다").toHaveCount(4);
  await expect(heads.nth(1)).toHaveText("현재 보유");
  await expect(heads.nth(2)).toHaveText("목표");

  // 노드 수를 먼저 단언한다 — 빈 표는 아무것도 지키지 않는다.
  expect(await cells(page).count(), "기준 표에 자산 행이 없다").toBeGreaterThan(0);
});

// ── 2. ★목표가 없으면 미계산 + 사유이고, 현재 값을 복사하지 않는다★ ─────────
test("★목표가 없으면 목표 열은 미계산이고 현재 값을 복사하지 않는다★", async ({ page }) => {
  test.setTimeout(120_000);
  await seedPortfolio(page);
  // 최적화를 **돌리지 않고** 바로 들어온다 → 목표가 존재하지 않는 상태.
  await page.goto("/allocation/stress", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".as-rob-basis")).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(2_000);

  const na = page.locator(".as-rob-basis-na");
  await expect(na, "목표가 없는데 사유를 적지 않았다").toBeVisible();
  await expect(na).toContainText("미계산");
  await expect(na, "왜 없는지 말하지 않는다").toContainText("OPTIMIZE");

  const rows = cells(page);
  const n = await rows.count();
  expect(n, "기준 표에 자산 행이 없다").toBeGreaterThan(0);
  for (let i = 0; i < n; i++) {
    const cur = (await rows.nth(i).locator("td").nth(1).innerText()).trim();
    const tgt = (await rows.nth(i).locator("td").nth(2).innerText()).trim();
    expect(tgt, "목표 열에 숫자가 찍혔다 — 목표가 없는데 무언가를 목표라고 말하고 있다")
      .toContain("미계산");
    expect(tgt, "목표 열이 현재 값을 복사했다").not.toBe(cur);
  }
});

// ── 3. 두 기준이 같으면 그 사실을 말한다 ────────────────────────────────────
test("두 기준이 같으면 같다고 적는다 (같은 숫자 두 번을 오류로 읽지 않게)", async ({ page }) => {
  test.setTimeout(180_000);
  await seedPortfolio(page);
  await optimizeThenStress(page);

  const same = page.locator(".as-rob-basis-same");
  const meta = page.locator(".as-rob-basis-meta");
  // 둘 중 정확히 하나가 보여야 한다 — 아무것도 없으면 기준을 설명하지 않은 것이다.
  const shown = (await same.count()) + (await meta.count());
  expect(shown, "기준 상태를 한 줄도 설명하지 않았다").toBe(1);
  if (await same.count()) await expect(same).toContainText("같습니다");
});

// ── 4. 3자 비교가 어느 기준인지 밝힌다 ──────────────────────────────────────
test("3자 비교 패널이 어느 기준인지 라벨로 밝힌다", async ({ page }) => {
  test.setTimeout(120_000);
  await seedPortfolio(page);
  await page.goto("/allocation/stress", { waitUntil: "domcontentloaded" });
  const label = page.locator(".as-3w-basis");
  await expect(label, "3자 비교의 기준이 화면에 없다").toBeVisible({ timeout: 20_000 });
  await expect(label).toContainText("현재 보유");
});

// ── 5. 타입 하한 (§56) ──────────────────────────────────────────────────────
test("§56 하한: 기준 밴드의 텍스트가 11px 이상이다", async ({ page }) => {
  test.setTimeout(120_000);
  await seedPortfolio(page);
  await page.goto("/allocation/stress", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".as-rob-basis")).toBeVisible({ timeout: 20_000 });
  const r = await page.evaluate(() => {
    const out: string[] = [];
    let n = 0;
    for (const el of document.querySelectorAll(".as-rob-basis, .as-rob-basis *")) {
      if (!(el.textContent ?? "").trim()) continue;
      n++;
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (fs < 10.99) out.push(`${el.className || el.tagName} ${fs}px`);
    }
    return { n, out: [...new Set(out)] };
  });
  expect(r.n, "검사한 노드가 없다 — 빈 선택자는 조용히 통과한다").toBeGreaterThan(5);
  expect(r.out, `11px 미만: ${JSON.stringify(r.out)}`).toEqual([]);
});

// ── 6. SCENARIO DETAIL 이 두 기준을 나란히 낸다 (R0-B2) ─────────────────────
test("★시나리오 충격을 현재 보유와 목표 두 기준으로 낸다★", async ({ page }) => {
  test.setTimeout(120_000);
  await seedPortfolio(page);
  await page.goto("/allocation/stress", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".as-rob-basis")).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(4_000);

  // 전제: 충격 한 줄이 렌더돼야 대조가 성립한다.
  const head = page.locator(".as-shock-head");
  await expect(head, "시나리오 충격 줄이 없다 — 아래 단언은 뜻이 없다")
    .toBeVisible({ timeout: 20_000 });

  const kpi = page.locator(".as-rob-kpi2").first();
  await expect(kpi, "두 기준 대조 줄이 없다").toBeVisible();
  await expect(kpi).toContainText("현재 보유");
  await expect(kpi).toContainText("목표");
  // 최적화를 돌리지 않았으므로 목표는 미계산이어야 한다 — 0 이나 현재 값 복사가 아니라.
  await expect(kpi, "목표 기준이 없는데 숫자를 만들었다").toContainText("미계산");
});
