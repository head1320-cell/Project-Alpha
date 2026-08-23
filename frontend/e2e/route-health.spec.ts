import { test, expect } from "@playwright/test";
import { trackErrors, uniq, STUB_RUN_ID, stubCompletedRun } from "./helpers";

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

/** AAS 스테이지 4종 — layout.tsx 의 공통 크롬 + 라우트 고유 마커. */
const AAS_STAGES: { path: string; marker: string; label: string }[] = [
  { path: "/allocation/overview", marker: ".aas-xlink", label: "00 OVERVIEW" },
  { path: "/allocation/thesis", marker: ".as-card-title", label: "02 THESIS" },
  { path: "/allocation/explain", marker: ".as-card-title", label: "08 EXPLAIN" },
  { path: "/allocation/execution", marker: ".as-card, .as-exec", label: "07 EXECUTION" },
];

for (const { path, marker, label } of AAS_STAGES) {
  test(`Route health: ${path} (${label}) renders honestly on a cold start`, async ({ page }) => {
    const sink = trackErrors(page);
    await page.goto(path, { waitUntil: "networkidle" });

    // 공통 크롬(인텐트·컨텍스트 스트립·트래커·하단 nav)이 붙었는가 — layout 자체의 회귀 가드
    await expect(page.locator(".aas-intent")).toBeVisible();
    await expect(page.locator(".aas-content")).toBeVisible();
    // 라우트 고유 콘텐츠가 실제로 있는가 (빈 div 가 아님)
    await expect(page.locator(marker).first()).toBeVisible();

    const body = await page.locator("body").innerText();
    expect(body.trim().length, `${path} 본문이 비어 있으면 안 된다`).toBeGreaterThan(200);
    expect(body, `${path} 인코딩`).not.toMatch(/�/);

    expect(uniq(sink.pageErrors), `${path} page errors`).toEqual([]);
    expect(uniq(sink.consoleErrors), `${path} console errors`).toEqual([]);
    expect(uniq(sink.api404), `${path} API 404s`).toEqual([]);
  });
}

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
