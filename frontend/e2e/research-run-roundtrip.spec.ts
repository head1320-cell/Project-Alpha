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

// ★런 이름은 실행마다 유일해야 한다★
// runs 테이블은 Playwright 실행 사이에 살아남는 **실제 영속 DB** 다. 이름을 상수로 두면
// 이 스펙을 두 번 돌린 순간 같은 이름의 행이 2개가 되고, Playwright strict mode 가
// 모호한 로케이터를 거부한다("resolved to 2 elements").
// 실제로 그렇게 깨졌다: 단독 실행 3/3 → 전수 실행에서 2건 실패. 단독 실행과 뮤테이션 프로브가
// 각각 '왕복 검증 런' 을 하나씩 남긴 것이 원인이었다(제품은 정상, 테스트가 공족적이었다).
//
// .first() 로 때우지 않는다 — 그러면 **이전 실행이 남긴 런**을 집을 수 있고, 그건
// 지속성 테스트가 절대 해선 안 되는 일이다. 유일한 이름으로 정확히 이번 런만 지목한다.
const uniqueRunName = (base: string) =>
  `${base} ${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;

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
  const RUN_NAME = uniqueRunName("왕복 검증 런");

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
  const NAME = uniqueRunName("확인 테스트 런");
  await attachSnapshot(page);
  await seedHoldings(page);

  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });
  const rec = page.locator(".as-rr-record");
  await expect(rec).toBeVisible({ timeout: 20_000 });
  await rec.locator("input.as-input").fill(NAME);
  const saveBtn = rec.locator("button.as-fb-apply");
  await expect(saveBtn).toBeEnabled({ timeout: 30_000 });
  await saveBtn.click();

  const item = page.locator(".as-rr-item", { hasText: NAME });
  await expect(item).toBeVisible({ timeout: 40_000 });

  // 활성 런이 아닌 상태로 만든 뒤 되돌리기 → 확인 대화상자가 떠야 한다
  await page.goto("/allocation/construct", { waitUntil: "domcontentloaded" });
  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });

  let asked = false;
  page.once("dialog", (d) => { asked = true; d.dismiss(); });
  const target = page.locator(".as-rr-item", { hasText: NAME });
  await expect(target).toBeVisible({ timeout: 30_000 });
  await target.locator(".as-rr-reopen").click();
  await page.waitForTimeout(1_000);

  expect(asked, "저장 안 한 구성을 조용히 덮어쓰면 안 된다").toBe(true);
});

test("런 왕복: 되돌리기 버튼이 삭제와 혼동되지 않는다", async ({ page }) => {
  // 같은 행에 파괴적 액션(×)과 나란히 있으므로 별개 컨트롤이어야 한다
  const NAME = uniqueRunName("구분 테스트 런");   // 지금은 통과하지만 같은 함정이라 함께 고친다
  await attachSnapshot(page);
  await seedHoldings(page);
  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });
  const rec = page.locator(".as-rr-record");
  await expect(rec).toBeVisible({ timeout: 20_000 });
  await rec.locator("input.as-input").fill(NAME);
  const saveBtn = rec.locator("button.as-fb-apply");
  await expect(saveBtn).toBeEnabled({ timeout: 30_000 });
  await saveBtn.click();

  const item = page.locator(".as-rr-item", { hasText: NAME });
  await expect(item).toBeVisible({ timeout: 40_000 });
  await expect(item.locator(".as-rr-reopen")).toHaveCount(1);
  await expect(item.locator(".as-x")).toHaveCount(1);
});

// ═══════════════════════════════════════════════════════════════════════════════
// 룰셋 버전 왕복 (Phase 7c) — 스냅샷과 **같은 성질**을 룰셋에도 요구한다.
//
// 스냅샷만 돌아오고 룰셋이 안 돌아오면, 되돌린 런은 "같은 국면에서 다른 규칙으로" 계산된
// 것이 되고 그건 재현이 아니다. 그래서 여기서도 "뭔가 붙었다" 가 아니라 **같은 id·같은 버전**을
// 대조한다.
// ═══════════════════════════════════════════════════════════════════════════════

/** 타이밍 데스크에서 카탈로그 팩터를 담고 룰셋으로 저장한다. 저장된 신원 텍스트를 돌려준다. */
async function saveRuleSet(page: import("@playwright/test").Page): Promise<string> {
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).first().click();
  await expect(page.locator(".tfm-row").first()).toBeVisible({ timeout: 20_000 });
  await page.locator(".tfm-row").first().click();
  await page.locator(".as-fb-apply", { hasText: "이 팩터 추가" }).click();

  const save = page.locator(".as-3w-save");
  await expect(save).toBeEnabled({ timeout: 30_000 });
  await save.click();

  // 저장되면 컨텍스트 스트립이 설정 요약이 아니라 **룰셋 신원**을 보여준다.
  const rules = page.locator(".as-ctx-rules");
  await expect(rules).toContainText("RULES", { timeout: 30_000 });
  return (await rules.innerText()).trim();
}

test("룰셋 왕복: 되돌린 런이 같은 룰셋 id·버전을 복원한다", async ({ page }) => {
  const sink = trackErrors(page);
  const RUN_NAME = uniqueRunName("룰셋 왕복 런");

  await attachSnapshot(page);
  await seedHoldings(page);
  const identity = await saveRuleSet(page);
  // 버전이 없으면 재현 좌표가 아니다 — 화면이 그 사실을 감추지 않는지도 함께 본다.
  expect(identity, "룰셋 신원에 버전이 없다").toMatch(/v\d+|버전 미기록|확인 불가/);

  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });
  const rec = page.locator(".as-rr-record");
  await expect(rec).toBeVisible({ timeout: 20_000 });
  await rec.locator("input.as-input").fill(RUN_NAME);
  const saveBtn = rec.locator("button.as-fb-apply");
  await expect(saveBtn).toBeEnabled({ timeout: 30_000 });
  await saveBtn.click();
  await expect(page.locator(".as-rr-item", { hasText: RUN_NAME })).toBeVisible({ timeout: 40_000 });

  // ★새로고침★ — 여기부터 휘발성 메모리로는 통과할 수 없다
  await page.reload({ waitUntil: "domcontentloaded" });

  const target = page.locator(".as-rr-item", { hasText: RUN_NAME });
  await expect(target).toBeVisible({ timeout: 30_000 });
  page.once("dialog", (d) => d.accept());
  await target.locator(".as-rr-reopen").click();
  await expect(target).toHaveClass(/active/, { timeout: 20_000 });

  // 되돌린 뒤에도 **같은** 신원이어야 한다 — 현재 룰셋으로 대체되면 재현이 아니다.
  await expect(page.locator(".as-ctx-rules")).toHaveText(identity, { timeout: 20_000 });

  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
});

test("룰셋 왕복: 사라진 버전은 현재 버전으로 대체되지 않고 '확인 불가'로 표시된다", async ({ page, request }) => {
  // ★재현성 표시의 정직성 게이트★
  // 런에 박힌 버전이 서버에서 사라졌을 때 화면이 현재 버전을 대신 보여주면, 사용자는 그 런이
  // 재현됐다고 믿는다 — 실제로는 다른 규칙으로 계산된 결과를 보고 있다.
  await saveRuleSet(page);

  // 전체 id 는 **증거 서랍** 안에 있다(칩 표기는 앞 10자로 잘린다).
  // P3 이전에는 .as-ctx-rules 의 title= 에서 읽었다. 그 title 은 근거를 호버 뒤에
  // 숨기고 있었기 때문에 걷어냈고, 같은 정보가 이제 서랍의 "룰셋" 행에 있다.
  await page.locator(".as-ctx .tev-drawer-t").click();
  const drawerText = await page.locator(".tev-drawer").innerText();
  const setId = drawerText.match(/tr_[0-9a-z_]+/)?.[0];
  expect(setId, `룰셋 id 를 증거 서랍에서 찾지 못했다: ${drawerText}`).toBeTruthy();
  await page.keyboard.press("Escape");

  // 서버에서 룰셋을 지운다 → 박힌 버전은 더 이상 해석되지 않는다.
  const del = await request.delete(`/api/backend/api/v1/allocation/timing-rules/${setId}`);
  expect(del.ok(), "룰셋 삭제가 실패하면 이 테스트는 아무것도 검증하지 못한다").toBeTruthy();

  await page.reload({ waitUntil: "networkidle" });
  const rules = page.locator(".as-ctx-rules");
  await expect(rules).toContainText("RULES", { timeout: 20_000 });
  await expect(rules, "사라진 버전을 그대로/현재 버전으로 보여주고 있다")
    .toContainText("확인 불가", { timeout: 20_000 });
});
