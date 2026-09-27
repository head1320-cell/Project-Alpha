import { test, expect } from "@playwright/test";

// ═══════════════════════════════════════════════════════════════════════════════
// 반응형 — 행동 계약 (UI/UX 현대화 P10)
// ─────────────────────────────────────────────────────────────────────────────
// ★스크린샷을 찍는 것이 아니라 행동을 단언한다★
// 계획서 초안은 "390/1280/1440 에서 스크린샷" 이었다. 그런데 스크린샷은 무엇이 **사라지면
// 안 되는지** 를 말하지 못한다. 여기서 지키는 것은 하나다:
//
//   좁은 폭이라는 이유로 정직함을 줄이지 않는다.
//
// 예전 마법사 화면(문맥 줄의 PINNED/LIVE·as-of·룰셋)은 BL4 에서 지웠다. 이제 이 약속을 지키는 곳은 캔버스다 —
// 390px 에서도 계산 버튼·결과 요약·연습용(합성) 경고가 남고 가로로 넘치지 않아야 한다.
// ═══════════════════════════════════════════════════════════════════════════════

const MOBILE = { width: 390, height: 844 };
const TABLET = { width: 768, height: 1024 };

// ── 캔버스 (BL4 · 마법사 화면의 좁은 폭 계약을 옮김) ─────────────────────────────
// 마법사의 문맥 줄은 사라졌다. 캔버스에서 좁은 폭이 줄이면 안 되는 것은 ① 계산 버튼 ② 결과 요약 ③ **연습용(합성) 경고**
// ④ 노드의 상태와 사유다 — 폭이 좁다고 "연습용" 이 사라지면 합성 수가 실데이터처럼 읽힌다.
for (const [name, size] of [["mobile", MOBILE], ["tablet", TABLET]] as const) {
  test(`캔버스 ${name}(${size.width}px): 가로 스크롤 없음 · 계산·요약·연습용 경고·노드 상태가 남는다`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.goto("/allocation", { waitUntil: "domcontentloaded" });
    await expect(page.locator(".pg-node").first()).toBeAttached({ timeout: 30_000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "가로 오버플로 픽셀").toBeLessThanOrEqual(1);

    const run = page.locator(".pg-run");
    await run.scrollIntoViewIfNeeded();
    await expect(run).toBeVisible();
    const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
    await run.click();
    await resp;
    const summary = page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)");
    await expect(summary).toContainText("완료", { timeout: 30_000 });
    await summary.scrollIntoViewIfNeeded();
    await expect(summary).toBeVisible();
    // 이야기 탭 맨 위의 연습용 경고 — 개발 환경의 수익률은 합성이다.
    await page.locator('.pg-tab[data-tab="story"]').click();
    const practice = page.locator(".pg-side").getByText("연습용", { exact: false }).first();
    await practice.scrollIntoViewIfNeeded();
    await expect(practice).toBeVisible();
    const after = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(after, "계산 뒤 가로 오버플로 픽셀").toBeLessThanOrEqual(1);
  });
}
