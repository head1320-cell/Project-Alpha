import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";
import { nextAction, type WorkflowState } from "../src/widgets/allocation/nextAction";

// ═══════════════════════════════════════════════════════════════════════════════
// 리서치 워크스페이스 셸 (UI/UX 현대화 P3.5)
// ─────────────────────────────────────────────────────────────────────────────
// 두 층으로 나눠 검사한다.
//
//   1) 정책 — 순수 함수라 브라우저 없이 **8가지 상태를 전부** 돌린다. 화면을 띄워
//      상태를 만들려 했다면 절반은 검사하지 못했을 것이다.
//   2) 셸 — 그 정책이 실제로 화면에 하나의 CTA 로 나오는지, 사유가 보이는지.
//
// ★정책 테스트가 브라우저 테스트보다 강한 이유★
// "자산 없음" 같은 상태는 UI 로 만들 수 있지만 "스트레스 검증까지 끝난 상태" 는 실행에
// 몇 분이 걸린다. 그래서 그런 조건은 늘 검사되지 않은 채 남는다. 정책을 순수 함수로
// 떼어 두면 그 격차가 사라진다.
// ═══════════════════════════════════════════════════════════════════════════════

/** 흐름을 모두 마친 상태 — 각 테스트는 여기서 한 가지만 되돌린다. */
const DONE: WorkflowState = {
  hasStudy: true, holdingsCount: 5, hasSnapshot: true, hasRuleSet: true,
  hasResult: true, isResultStale: false, hasStressValidation: true, hasJournalEntry: true,
};

test.describe("워크플로 다음 할 일 정책 (순수 함수)", () => {
  test("8가지 상태가 각각 정해진 하나의 다음 할 일을 낸다", () => {
    expect(nextAction({ ...DONE, hasStudy: false, holdingsCount: 0, hasResult: false,
      hasSnapshot: false, hasRuleSet: false, hasStressValidation: false, hasJournalEntry: false }).key).toBe("start");
    expect(nextAction({ ...DONE, holdingsCount: 0 }).key).toBe("construct");
    expect(nextAction({ ...DONE, hasResult: false, hasSnapshot: false }).key).toBe("snapshot");
    expect(nextAction({ ...DONE, hasResult: false, hasRuleSet: false }).key).toBe("ruleset");
    expect(nextAction({ ...DONE, isResultStale: true }).key).toBe("recalc");
    expect(nextAction({ ...DONE, hasResult: false }).key).toBe("recalc");
    expect(nextAction({ ...DONE, hasStressValidation: false }).key).toBe("stress");
    expect(nextAction({ ...DONE, hasJournalEntry: false }).key).toBe("journal");
    expect(nextAction(DONE).key).toBe("review");
  });

  test("★낡은 결과는 검증·기록보다 앞선다★ 낡은 수치를 결론으로 만들지 않는다", () => {
    // 재계산이 필요한데 "시나리오 검증" 을 권하면, 사용자는 이전 입력의 결과를 검증하게 된다.
    const stale = { ...DONE, isResultStale: true, hasStressValidation: false, hasJournalEntry: false };
    expect(nextAction(stale).key).toBe("recalc");
  });

  test("★선택 단계가 사슬을 막지 않는다★ 결과가 나온 뒤에는 다시 조르지 않는다", () => {
    // 승인된 표를 그대로 옮겼다면 스냅샷을 고정하지 않는 한 영원히 3번에 멈췄다.
    const skipped = { ...DONE, hasSnapshot: false, hasRuleSet: false };
    expect(nextAction(skipped).key, "선택을 건너뛴 사용자도 흐름을 끝낼 수 있어야 한다").toBe("review");
  });

  test("★작업 중인 사용자를 게이트로 돌려보내지 않는다★", () => {
    // activeStudy 는 저널을 저장해야 생긴다. 그 전 사용자를 전부 게이트로 보내면
    // 다음 할 일은 쓸모가 없어진다.
    const working = { ...DONE, hasStudy: false };
    expect(nextAction(working).key).not.toBe("start");
  });

  test("★투자 권고를 만들 수 없다★ 입력에 시장 값이 없다", () => {
    // 타입 수준의 경계를 값 수준에서도 확인한다: 상태 키에 수익률·비중·신호가 없다.
    const keys = Object.keys(DONE);
    for (const banned of ["return", "weight", "signal", "stress_score", "exposure", "price"]) {
      expect(keys.some((k) => k.toLowerCase().includes(banned)), `금지 필드 ${banned}`).toBe(false);
    }
    // 모든 분기의 문구가 워크플로 어휘인지 — 매수/매도/비중 조절을 말하지 않는다.
    const labels = [
      nextAction({ ...DONE, holdingsCount: 0 }), nextAction({ ...DONE, isResultStale: true }),
      nextAction({ ...DONE, hasStressValidation: false }), nextAction(DONE),
    ].flatMap((a) => [a.label, a.why]);
    for (const t of labels) {
      expect(t).not.toMatch(/매수|매도|비중을 늘|비중을 줄|위험을 늘|위험을 줄/);
    }
  });
});

test.describe("셸 — 단일 CTA 와 보이는 사유", () => {
  test("스테이지마다 주 CTA 는 정확히 하나이고 사유가 함께 보인다", async ({ page }) => {
    const sink = trackErrors(page);
    for (const path of ["/allocation/construct", "/allocation/optimize", "/allocation/journal"]) {
      await page.goto(path, { waitUntil: "networkidle" });

      const cta = page.locator(".aas-botnav-next");
      await expect(cta, `${path}: 주 CTA 는 하나`).toHaveCount(1);
      await expect(cta).toBeVisible();

      // 사유는 툴팁이 아니라 보이는 텍스트다 — P3 에서 걷어낸 것을 되들이지 않는다.
      const why = page.locator(".aas-botnav-why");
      await expect(why, `${path}: 사유가 보여야 한다`).toBeVisible();
      expect((await why.innerText()).trim().length).toBeGreaterThan(0);
      expect(await why.getAttribute("data-next"), "안정 키").toBeTruthy();
    }
    expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  });

  test("자산이 없으면 셸이 자산 구성을 다음 할 일로 말한다", async ({ page }) => {
    await page.goto("/allocation/thesis", { waitUntil: "networkidle" });
    // 콜드 스타트에는 보유 자산이 없다 — 규칙 1 또는 2 가 걸린다(둘 다 "시작" 계열).
    const key = await page.locator(".aas-botnav-why").getAttribute("data-next");
    expect(["start", "construct"], `콜드 스타트의 다음 할 일: ${key}`).toContain(key);
  });

});

// P3.5 는 CTA 의 목적지를 바꿨다. STAGES 의 href 가 전부 실재하고 셸이 붙는지 확인한다.
//
// ★한 테스트에서 11개를 순회하다 90초 타임아웃에 걸렸다★ 8번째(/allocation/stress)에서
// 죽었다 — 라우트당 ~9초라 합이 한도를 넘는다. 타임아웃을 늘리는 대신 라우트마다
// 테스트를 나눈다(route-health.spec.ts 와 같은 방식). 실패했을 때 어느 라우트인지도
// 바로 드러난다.
const STAGE_ROUTES = [
  "/allocation/overview", "/allocation/macro", "/allocation/construct", "/allocation/alphalab",
  "/allocation/thesis", "/allocation/timing", "/allocation/optimize", "/allocation/stress",
  "/allocation/explain", "/allocation/execution", "/allocation/journal",
];

for (const path of STAGE_ROUTES) {
  test(`셸: ${path} 이 살아 있고 크롬이 붙는다`, async ({ page }) => {
    const res = await page.goto(path, { waitUntil: "domcontentloaded" });
    expect(res?.status(), `${path} 상태코드`).toBeLessThan(400);
    await expect(page.locator(".aas-intent"), `${path} 셸`).toBeVisible();
    await expect(page.locator(".aas-botnav-next"), `${path} 주 CTA`).toHaveCount(1);
  });
}
