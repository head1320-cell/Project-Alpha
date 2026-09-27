import { test, expect } from "@playwright/test";
import { trackErrors, uniq, STUB_RUN_ID, stubCompletedRun } from "./helpers";
import { LEGACY_SCREENS } from "../src/entities/portfolio-graph/legacyScreens";

// ═══════════════════════════════════════════════════════════════════════════════
// 라우트 건강도 스윕 — UI/UX 현대화 P0
// ─────────────────────────────────────────────────────────────────────────────
// ★왜 "초록 110개" 로는 부족한가★
// 기존 스위트가 방문하는 라우트는 전부 오류 가드가 걸려 있다(pageErrors·api404 둘 다
// 단정). 그래서 초록은 **그 라우트들에 대해서만** 진짜다. 아무 테스트도 열지 않는
// 라우트가 12개 있고, 그중 다섯이 이번 재설계 대상이다. 재설계 diff 밑에 이미 있던
// 결함이 깔리면 원인을 가릴 수 없으므로, **손대기 전에** 기준선을 잰다.
//
// ★이 스펙이 재는 것★
// 콜드 스타트(최적화 결과 없음·런 없음) 에서 각 라우트가
//   1) 껍데기가 아니라 실제로 렌더되는가,
//   2) 미처리 예외를 던지지 않는가,
//   3) 백엔드 404 를 내지 않는가,
//   4) 한글 인코딩이 깨지지 않는가.
// 빈 상태 자체는 결함이 아니다 — 빈 상태를 **정직하게** 보여주는 것이 이 앱의 설계다.
// 재는 것은 "데이터가 있는가" 가 아니라 "데이터가 없을 때 무너지는가" 다.
//
// ★results 라우트만 픽스처가 필요한 이유★
// /backtest/runs/<임의>/results 는 백엔드가 정직하게 404 를 준다. 그건 올바른 동작이다.
// 그러므로 임의 runId 로 재면 앱이 아니라 테스트가 틀린다 — backtest.spec.ts 와 같은
// 완료 런 픽스처(helpers.ts::stubCompletedRun)를 공유해서 연다.
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * ★옛 마법사 주소 12 개 — 지운 화면이 404 가 아니라 캔버스로 온다★ (BL4)
 * `next.config.js` redirects 가 `/allocation/<화면>` → `/allocation?from=<화면>` 으로 보낸다(쿼리 보존). 캔버스는 그 화면의 이름을
 * 한 줄로 말하고, 그 일을 하는 노드로 팔레트 검색을 채운다. 표는 `entities/portfolio-graph/legacyScreens.ts` 하나.
 */
const LEGACY = Object.entries(LEGACY_SCREENS) as [string, (typeof LEGACY_SCREENS)[keyof typeof LEGACY_SCREENS]][];

for (const [key, screen] of LEGACY) {
  test(`Route health: 옛 주소 /allocation/${key} → 캔버스 · ‘${screen.title}’ 안내 · 오류 0`, async ({ page }) => {
    const sink = trackErrors(page);
    await page.goto(`/allocation/${key}`, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(new RegExp(`/allocation\\?from=${key}$`));
    await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
    const banner = page.locator(".pg-legacy");
    await expect(banner).toContainText(screen.title);
    // 그 일을 하는 노드가 팔레트에 보인다(검색이 예전 이름으로 채워진다) · 템플릿·서랍이 있으면 그 버튼도.
    for (const kind of screen.nodes) await expect(page.locator(`.pg-palette-item[data-kind="${kind}"]`), kind).toBeVisible();
    await expect(page.locator(".pg-legacy-template")).toHaveCount(screen.template ? 1 : 0);
    await expect(page.locator(".pg-legacy-drawer")).toHaveCount(screen.drawer ? 1 : 0);

    const body = await page.locator("body").innerText();
    expect(body, "인코딩").not.toMatch(/�/);
    expect(uniq(sink.pageErrors), "page errors").toEqual([]);
    expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
    expect(uniq(sink.api404), "API 404s").toEqual([]);
  });
}

test("Route health: 옛 주소의 쿼리는 따라온다 — /allocation/macro?snapshot= 은 캔버스가 그 스냅샷으로 연다", async ({ page }) => {
  await page.goto("/allocation/macro?snapshot=rgs_0_e2e_missing", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/allocation\?(?=.*from=macro)(?=.*snapshot=rgs_0_e2e_missing)/);
  await expect(page.locator(".pg-file-note")).toContainText("rgs_0_e2e_missing", { timeout: 30_000 });
});

test("Route health: 짝 — 모르는 옛 화면은 404, 모르는 from 은 안내를 지어내지 않는다", async ({ page }) => {
  const res = await page.goto("/allocation/not-a-stage", { waitUntil: "domcontentloaded" });
  expect(res?.status(), "모르는 화면을 캔버스로 보내면 안 된다(오타가 조용히 성공한다)").toBe(404);
  await page.goto("/allocation?from=bogus", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".pg-legacy")).toHaveCount(0);
});

test("Route health: /backtest/runs/[runId]/results renders from the shared completed-run fixture", async ({ page }) => {
  const sink = trackErrors(page);
  await stubCompletedRun(page);

  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });

  await expect(page.locator("h1")).toBeVisible();
  await expect(page.locator(".brun-kpi").first()).toBeVisible();

  const body = await page.locator("body").innerText();
  expect(body, "results 인코딩").not.toMatch(/�/);

  expect(uniq(sink.pageErrors), "results page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "results console errors").toEqual([]);
  expect(uniq(sink.api404), "results API 404s").toEqual([]);
});
