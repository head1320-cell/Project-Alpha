import { test, expect, type Page } from "@playwright/test";
import { freezeCharts, contrastAudit, type AuditResult } from "./helpers";

// A12: Recharts 애니메이션만 끈다 — CSS 모션(§62/§63)은 그대로 둔다.
// `reducedMotion:'reduce'` 를 쓰면 CSS 까지 꺼져 모션 가드가 공허해진다.
test.beforeEach(async ({ page }) => { await freezeCharts(page); });


// ═══════════════════════════════════════════════════════════════════════════════
// AAS 다크 스윕 — 11개 스테이지 전부 (A4-X2)
// ─────────────────────────────────────────────────────────────────────────────
// ★이 스펙이 존재하는 이유★
// A3 까지 다크 처리는 `.dark .as-ws2 …` 로 스코프돼 있었다. `.as-ws2` 는 11개 스테이지
// 중 9개만 쓴다 — overview 와 execution 은 안 쓴다. 그래서 그 둘은 다크에서 `.as-card`
// 의 `background:#fff`(:3254)가 그대로 남아, 글자만 #fafafa 로 뒤집힌 상태였다.
//
// A4-X2 가 스코프를 `.aas-root` 로 넓히면서 9개 스테이지가 **처음으로** 다크로 렌더된다.
// 스테이지마다 사람이 눈으로 확인하는 대신, 여기서 기계적으로 잰다. 스코프를 넓힌
// 변경이 안전한지는 이 스윕이 초록인지로만 판단한다 — 넓힌 사람의 자신감이 아니라.
//
// ★checked 를 먼저 단언한다★ 렌더가 실패해 텍스트 노드가 0개면 low 도 [] 라서 조용히
// 통과한다. 이 저장소에서 세 번 물린 패턴이라 라우트마다 하한을 건다.
// ═══════════════════════════════════════════════════════════════════════════════

/** 11개 스테이지 — AllocationProvider 의 STAGES + 북엔드와 같은 집합. */
const STAGES: [path: string, label: string][] = [
  ["/allocation/overview", "00 OVERVIEW"],
  ["/allocation/construct", "01 CONSTRUCT"],
  ["/allocation/macro", "0M MACRO"],
  ["/allocation/alphalab", "02 ALPHA LAB"],
  ["/allocation/thesis", "03 THESIS"],
  ["/allocation/timing", "04 TIMING"],
  ["/allocation/optimize", "05 OPTIMIZE"],
  ["/allocation/stress", "06 STRESS"],
  ["/allocation/explain", "07 EXPLAIN"],
  ["/allocation/execution", "08 EXECUTION"],
  ["/allocation/journal", "09 JOURNAL"],
];

/** 게이트를 통과해 세션을 시드한다 — 빈 세션은 대부분의 패널이 빈 상태라 잴 것이 적다. */
async function seed(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
}

for (const [path, label] of STAGES) {
  test(`다크: ${label} — AA 미달 0 · 밝은 배경 0`, async ({ page }) => {
    await seed(page);
    await page.goto(path, { waitUntil: "networkidle" });
    await expect(page.locator(".aas-root")).toBeVisible({ timeout: 15_000 });

    await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.waitForTimeout(200);

    const dark = await page.evaluate<AuditResult>(contrastAudit(".aas-root"));
    expect(dark.checked, `${label}: 검사한 텍스트 노드 수 (0 이면 조용히 통과한다)`)
      .toBeGreaterThan(10);
    expect(dark.low, `${label}: 다크 AA 미달`).toEqual([]);
    // ★"반만 다크" 검사★ 글자만 뒤집히고 배경이 흰 채로 남는 것이 이 저장소가
    // 네 번 반복한 결함이다(.aas-wiz-lab · .as-seg button · .as-al-kpi · TIP_STYLE).
    expect(dark.bright, `${label}: 다크인데 밝은 배경이 남아 있다`).toEqual([]);
  });
}

test("★계산 중에도 결과를 흐리지 않는다 (A4-X1)★", async ({ page }) => {
  // ★이 테스트가 지키는 것★
  // `.as-loading` 은 `opacity: .55` 로 5개 스테이지의 결과 패널 9곳을 흐리게 만들었다.
  // 흐린 숫자는 AA 아래로 떨어지면서도 여전히 읽히므로, 사용자는 **낡은 값을 읽고
  // 판단한다**. 어떤 테스트도 이 값을 본 적이 없었다 — 그래서 조용히 살아남았다.
  await seed(page);
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });

  // 실제 pending 을 잡기는 타이밍에 의존하므로, 클래스를 직접 붙여 규칙 자체를 잰다.
  const card = page.locator(".as-card").first();
  await expect(card).toBeVisible({ timeout: 15_000 });
  const op = await card.evaluate((el) => {
    el.classList.add("as-loading");
    return getComputedStyle(el).opacity;
  });
  expect(Number(op), ".as-loading 이 결과를 흐리면 안 된다").toBe(1);
});
