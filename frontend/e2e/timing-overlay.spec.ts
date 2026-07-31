import { expect, test } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 타이밍 오버레이 — 전략 비중을 조용히 덮어쓰지 않는다 (스펙 §8, Phase 10c).
//
// §8: "Optimize 는 타이밍 산출을 제약/오버레이/목표위험 조정으로 받고 **전략 비중을 조용히
// 덮어쓰지 않는다**."
//
// ★이 동작에는 E2E 가 **하나도 없었다**★
// `applyTiming` 은 `setHoldingsReset()` 으로 보유 종목을 통째로 갈아치우면서도 테스트가 0개였다.
// 즉 §8 위반이 있었을 뿐 아니라, 그 위반을 바꾸는 것조차 아무도 지켜보지 않는 상태였다.
//
// 두 동작은 **다른 것**이고 화면에서도 달라야 한다:
//  · 오버레이로 적용 — 전략 비중 유지, 노출만 축소 (비파괴)
//  · 권고 배분으로 교체 — 위험-오프면 방어자산으로 갈아탄다 (파괴적, 배율로 재현 불가)
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * 전략 포트폴리오를 심는다 — 없으면 "비중이 살아남았다" 를 검증할 대상이 없다.
 *
 * ★덮어쓰지 않고 **없을 때만** 심는다★ `addInitScript` 는 **매 네비게이션마다** 다시 실행된다.
 * 무조건 `setItem` 하면 /timing 에서 켠 오버레이가 /optimize 로 이동하는 순간 씨앗으로
 * 되돌아가 사라지고, 테스트는 "오버레이가 전달되지 않는다" 고 잘못 보고한다.
 */
async function seedPortfolio(page: import("@playwright/test").Page) {
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

test("오버레이: 두 동작이 화면에서 구별된다 (유지 vs 교체)", async ({ page }) => {
  const sink = trackErrors(page);
  await seedPortfolio(page);
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });

  const overlay = page.locator(".as-tm-overlay");
  const replace = page.locator(".as-tm-replace");
  await expect(overlay).toBeVisible({ timeout: 20_000 });
  await expect(replace).toBeVisible();
  // ★버튼 문구가 결과를 말해야 한다★ 둘 다 "적용" 이면 사용자는 차이를 알 수 없다.
  await expect(overlay).toContainText("전략 비중 유지");
  await expect(replace).toContainText("교체");

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.api404), "API 404s").toEqual([]);
});

test("오버레이: 전략 비중이 살아남는다 (§8 — 조용한 덮어쓰기 금지)", async ({ page }) => {
  await seedPortfolio(page);
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });

  const overlay = page.locator(".as-tm-overlay");
  await expect(overlay).toBeVisible({ timeout: 20_000 });
  await overlay.click();

  // 01 CONSTRUCT 로 돌아가 보유 비중이 그대로인지 본다 — 오버레이는 여기를 건드리면 안 된다.
  await page.goto("/allocation/construct", { waitUntil: "networkidle" });
  const body = await page.locator("body").innerText();
  expect(body, "전략 종목이 사라졌습니다 — 오버레이가 보유를 덮어썼습니다").toContain("삼성전자");
  expect(body).toContain("SK하이닉스");
});

test("오버레이: Optimize 가 before/after 를 보여준다", async ({ page }) => {
  const sink = trackErrors(page);
  await seedPortfolio(page);
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await page.locator(".as-tm-overlay").click({ timeout: 20_000 });

  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  const panel = page.locator(".as-tov");
  await expect(panel).toBeVisible({ timeout: 20_000 });

  // ★전제조건을 먼저 단정한다★ 표가 없으면 아래 단언은 통과해도 뜻이 없다.
  const rows = panel.locator(".as-tov-table tbody tr");
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  await expect(panel).toContainText("위험자산 노출");
  await expect(panel).toContainText("회전율");
  // 균일 배율이 팩터 틸트를 바꾸지 않는다는 사실 — 지어낸 Δ 대신 산술적 사실을 적는다.
  await expect(panel).toContainText("팩터 틸트");

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.api404), "API 404s").toEqual([]);
});

test("오버레이: 해제하면 원래 비중이 그대로다", async ({ page }) => {
  await seedPortfolio(page);
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await page.locator(".as-tm-overlay").click({ timeout: 20_000 });

  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  const panel = page.locator(".as-tov");
  await expect(panel.locator(".as-tov-table")).toBeVisible({ timeout: 20_000 });

  await panel.locator(".as-tov-off").click();
  // 해제하면 안내 문구로 돌아가고 표는 사라진다 — 껐는데 남아 있으면 껐다고 할 수 없다.
  await expect(panel.locator(".as-tov-table")).toHaveCount(0);
  await expect(panel).toContainText("오버레이로 적용");
});

test("오버레이: 노출이 100% 를 넘지 않는다 (일방향)", async ({ page }) => {
  // ★오버레이가 노출을 키울 수 있으면 리스크 관리가 조용히 레버리지가 된다★
  await seedPortfolio(page);
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await page.locator(".as-tm-overlay").click({ timeout: 20_000 });

  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  const exp = page.locator(".as-tov-exp");
  await expect(exp).toBeVisible({ timeout: 20_000 });
  const pct = parseFloat((await exp.innerText()).replace("%", ""));
  expect(Number.isFinite(pct), "노출이 숫자가 아닙니다").toBe(true);
  expect(pct).toBeLessThanOrEqual(100);
  expect(pct).toBeGreaterThanOrEqual(0);

  // after 는 before 보다 클 수 없다 — 표의 Δ 가 전부 0 이하여야 한다.
  const deltas = await page.locator(".as-tov-table tbody tr .as-tov-d").allInnerTexts();
  expect(deltas.length).toBeGreaterThan(0);
  for (const d of deltas) {
    expect(parseFloat(d), `증가한 비중이 있습니다: ${d}`).toBeLessThanOrEqual(0.05);
  }
});
