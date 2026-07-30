import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// ResearchRun 왕복 — Phase 4 의 게이트. "아키텍처를 증명하는" 지점.
//
// ★이 스펙이 피하는 함정★
// "런을 저장했다" 나 "스냅샷이 하나 붙어 있다" 를 확인하는 테스트는 링크가 끊어져도 통과한다.
// 그래서 여기서는 **명시적인 ID** 를 대조한다 — 같은 run_id, 같은 snapshot_id, 같은 보유 구성.
// 그리고 중간에 **브라우저를 새로고침**한다. 그게 없으면 휘발성 메모리로도 통과한다.
//
// 흐름: 스냅샷 부착 → 자산 구성 → 런 기록 → 새로고침 → 되돌리기 → 동일성 단언
// ═══════════════════════════════════════════════════════════════════════════════

const RUN_NAME = "왕복 검증 런";

/** Macro → AAS 로 스냅샷을 만들어 붙이고 그 ID 를 돌려준다. */
async function attachSnapshot(page: import("@playwright/test").Page): Promise<string> {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await page.locator(".mc-open-aas").click();
  await page.waitForURL(/\/allocation\/macro\?snapshot=rgs_/, { timeout: 30_000 });
  const sid = new URL(page.url()).searchParams.get("snapshot")!;
  await page.locator(".as-macro-apply").click();
  await expect(page.locator(".as-macro-attached")).toBeVisible({ timeout: 15_000 });
  return sid;
}

/** 게이트에서 목표를 골라 자산을 시드한다(런 기록에는 자산 2개 이상이 필요). */
async function seedHoldings(page: import("@playwright/test").Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".aas-gate")).toBeVisible({ timeout: 20_000 });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/(construct|overview)/, { timeout: 20_000 });
  await expect(page.locator(".as-ctx")).toBeVisible({ timeout: 20_000 });
}

test("런 왕복: 새로고침 후 되돌리면 같은 런·같은 스냅샷·같은 구성이 돌아온다", async ({ page }) => {
  const sink = trackErrors(page);

  const sid = await attachSnapshot(page);
  await seedHoldings(page);

  // 스냅샷이 살아 있어야 런에 링크가 실린다
  await expect(page.locator(".as-ctx-snap")).toBeVisible({ timeout: 20_000 });

  // ── 런 기록 (저널 스테이지의 ResearchRunsPanel) ──
  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });
  const rec = page.locator(".as-rr-record");
  await expect(rec).toBeVisible({ timeout: 20_000 });
  await rec.locator("input.as-input").fill(RUN_NAME);

  const saveBtn = rec.locator("button.as-fb-apply");
  await expect(saveBtn).toBeEnabled({ timeout: 30_000 });
  await saveBtn.click();

  // 기록된 런이 목록에 나타난다
  const item = page.locator(".as-rr-item", { hasText: RUN_NAME });
  await expect(item).toBeVisible({ timeout: 40_000 });

  // ── ★브라우저 새로고침★ — 여기부터는 휘발성 메모리로 통과할 수 없다 ──
  await page.reload({ waitUntil: "domcontentloaded" });
  const itemAfter = page.locator(".as-rr-item", { hasText: RUN_NAME });
  await expect(itemAfter, "새로고침 후에도 런이 목록에 있어야 한다").toBeVisible({ timeout: 30_000 });

  // 구성을 흐트러뜨린 뒤 되돌려야 복원이 실제로 일어났는지 알 수 있다
  await page.goto("/allocation/construct", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".as-ctx")).toBeVisible({ timeout: 20_000 });

  // ── 되돌리기 ──
  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });
  const target = page.locator(".as-rr-item", { hasText: RUN_NAME });
  await expect(target).toBeVisible({ timeout: 30_000 });
  page.once("dialog", (d) => d.accept());          // 덮어쓰기 확인
  await target.locator(".as-rr-reopen").click();

  // ── 동일성 단언: 명시적 ID 대조 ──
  // ① 활성 런 배지가 이 런을 가리킨다
  await expect(target, "되돌린 런이 활성 런이 되어야 한다").toHaveClass(/active/, { timeout: 20_000 });

  // ② 같은 **스냅샷 ID** 가 다시 붙어 있다 (단순히 "뭔가 붙었다"가 아니다)
  const strip = page.locator(".as-ctx-snap");
  await expect(strip, "런의 국면 스냅샷이 다시 붙어야 한다").toBeVisible({ timeout: 20_000 });
  await expect(strip).toContainText(sid.replace(/^rgs_/, "").slice(0, 12));

  // ③ 구성이 복원됐다 — 컨텍스트 스트립의 유니버스 표기가 0종목이 아니다
  await expect(page.locator(".as-ctx-univ")).not.toContainText("0종목");

  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
});

test("런 왕복: 되돌리기는 저장 안 한 구성을 덮어쓰기 전에 확인을 받는다", async ({ page }) => {
  await attachSnapshot(page);
  await seedHoldings(page);

  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });
  const rec = page.locator(".as-rr-record");
  await expect(rec).toBeVisible({ timeout: 20_000 });
  await rec.locator("input.as-input").fill("확인 테스트 런");
  const saveBtn = rec.locator("button.as-fb-apply");
  await expect(saveBtn).toBeEnabled({ timeout: 30_000 });
  await saveBtn.click();

  const item = page.locator(".as-rr-item", { hasText: "확인 테스트 런" });
  await expect(item).toBeVisible({ timeout: 40_000 });

  // 활성 런이 아닌 상태로 만든 뒤 되돌리기 → 확인 대화상자가 떠야 한다
  await page.goto("/allocation/construct", { waitUntil: "domcontentloaded" });
  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });

  let asked = false;
  page.once("dialog", (d) => { asked = true; d.dismiss(); });
  const target = page.locator(".as-rr-item", { hasText: "확인 테스트 런" });
  await expect(target).toBeVisible({ timeout: 30_000 });
  await target.locator(".as-rr-reopen").click();
  await page.waitForTimeout(1_000);

  expect(asked, "저장 안 한 구성을 조용히 덮어쓰면 안 된다").toBe(true);
});

test("런 왕복: 되돌리기 버튼이 삭제와 혼동되지 않는다", async ({ page }) => {
  // 같은 행에 파괴적 액션(×)과 나란히 있으므로 별개 컨트롤이어야 한다
  await attachSnapshot(page);
  await seedHoldings(page);
  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });
  const rec = page.locator(".as-rr-record");
  await expect(rec).toBeVisible({ timeout: 20_000 });
  await rec.locator("input.as-input").fill("구분 테스트 런");
  const saveBtn = rec.locator("button.as-fb-apply");
  await expect(saveBtn).toBeEnabled({ timeout: 30_000 });
  await saveBtn.click();

  const item = page.locator(".as-rr-item", { hasText: "구분 테스트 런" });
  await expect(item).toBeVisible({ timeout: 40_000 });
  await expect(item.locator(".as-rr-reopen")).toHaveCount(1);
  await expect(item.locator(".as-x")).toHaveCount(1);
});
