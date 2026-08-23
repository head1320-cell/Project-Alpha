import { expect, test } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// Radix Dialog 로 옮긴 창 3개의 대화상자 계약 (Phase A)
//
// ★이 세 창에는 E2E 가 하나도 없었다★ 그리고 role·aria-modal·Escape·포커스 트랩도
// **하나도 없었다**. 키보드·스크린리더 사용자는 열 수는 있어도 빠져나올 수 없었다.
//
// `WatchGroupModal`·`StrategyModal` 은 파일명으로 찾았지만, `DrillDownModal` 은
// `cockpitParts.tsx` 안에 있어 파일명 기반 목록에서 빠져 있었다 — 같은 결함이 세 번째로
// 있었던 셈이고, 그래서 여기서 셋을 함께 고정한다.
//
// ★Radix 는 document.body 로 포털한다★ (ADR 001 이 명시한 위험)
// 그래서 단언을 컨테이너로 좁히지 않고 **페이지 루트**에서 건다. 컨테이너로 스코프하면
// 포털된 내용을 놓쳐 "없다" 고 잘못 보고한다.
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * 대화상자 공통 계약 — 어느 창이든 이만큼은 해야 한다.
 *
 * ★`aria-modal` 을 단정하지 않는다★ 처음엔 단정했다가 틀렸다.
 * 손으로 만든 창(CatalogueShell)은 `aria-modal="true"` 를 직접 붙이지만, Radix 는 그 대신
 * **바깥 트리를 `aria-hidden` 으로 덮는다** — 보조기술 입장에서 더 튼튼한 방식이고,
 * `aria-modal` 이 없다고 접근성이 없는 것이 아니다. 그래서 구현 관례가 아니라 **효과**를
 * 단정한다: 이름이 있고, 바깥이 감춰지고, 포커스가 갇히고, Escape 로 닫힌다.
 */
async function assertDialogContract(page: import("@playwright/test").Page) {
  const dlg = page.getByRole("dialog");
  await expect(dlg).toBeVisible({ timeout: 20_000 });

  // 접근 가능한 이름 — 없으면 스크린리더가 "대화상자" 라고만 읽는다.
  const name = await dlg.getAttribute("aria-labelledby");
  expect(name, "대화상자에 접근 가능한 이름이 없습니다").toBeTruthy();

  // ★바깥 트리가 실제로 감춰졌는가★ 이것이 aria-modal 이 하려던 일이다.
  const hidden = await page.locator("body > [aria-hidden='true']").count();
  expect(hidden, "창 밖 콘텐츠가 보조기술에 그대로 노출돼 있습니다").toBeGreaterThan(0);

  // ★포커스 트랩★ Tab 을 계속 눌러도 포커스가 창을 벗어나지 않는다.
  for (let i = 0; i < 25; i++) await page.keyboard.press("Tab");
  await expect(dlg.locator(":focus"), "Tab 이 창 밖으로 걸어 나갔습니다").toHaveCount(1);

  // Escape 로 닫힌다 — 이전에는 backdrop 클릭만 가능했다.
  await page.keyboard.press("Escape");
  await expect(dlg).toHaveCount(0);
}

test("Radix Dialog: 관심그룹 창이 대화상자 계약을 지킨다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/backtest", { waitUntil: "networkidle" });
  // UniversePanel 은 03 탭 뒤에 있다 — 초기 화면에는 트리거가 없다.
  await page.locator(".tbt-mode", { hasText: "매매 대상" }).click();
  await page.getByRole("button", { name: /그룹 추가/ }).first().click();
  await assertDialogContract(page);

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.api404), "API 404s").toEqual([]);
});

test("Radix Dialog: 지표 드릴다운 창이 대화상자 계약을 지킨다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/macro", { waitUntil: "networkidle" });
  // ★히트맵은 기본 탭(overview)이 아니라 `indicators` 탭에 있다★ 기본 탭에서 찾으면
  // "트리거가 사라졌다" 가 아니라 "탭을 안 옮겼다" 인데 화면은 똑같이 비어 보인다.
  await page.locator(".mc-tab", { hasText: "Indicators" }).click();

  // 히트맵 셀 하나 = 지표 드릴다운 트리거(ZHeatmap, core 탭). 매크로 데이터가 도착해야
  // 셀이 그려지므로 넉넉히 기다린다 — 못 찾으면 그것 자체가 보고할 사실이다.
  const cell = page.locator(".mc-heat-cell").first();
  await expect(cell, "지표 셀을 찾지 못했습니다 — 트리거가 바뀌었을 수 있습니다")
    .toBeVisible({ timeout: 60_000 });
  await cell.click();
  await assertDialogContract(page);

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.api404), "API 404s").toEqual([]);
});

test("Radix Dialog: 닫으면 포커스가 창을 연 요소로 돌아온다", async ({ page }) => {
  // ★포커스 복귀는 트랩과 별개의 계약이다★ 닫은 뒤 포커스가 body 로 떨어지면
  // 키보드 사용자는 목록의 어디에 있었는지 잃는다.
  await page.goto("/backtest", { waitUntil: "networkidle" });
  await page.locator(".tbt-mode", { hasText: "매매 대상" }).click();
  const trigger = page.getByRole("button", { name: /그룹 추가/ }).first();
  await trigger.click();
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 20_000 });

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger, "닫은 뒤 포커스가 트리거로 돌아오지 않았습니다").toBeFocused();
});

test("Radix Dialog: 창이 닫혀 있을 때는 페이지에 대화상자가 없다", async ({ page }) => {
  // 동적 import 로 바뀌었으므로 "닫혀 있으면 아예 마운트되지 않는다" 가 계약이다.
  await page.goto("/backtest", { waitUntil: "networkidle" });
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
