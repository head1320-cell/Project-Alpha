import { test, expect } from "@playwright/test";
import { trackErrors, contrastAudit, type AuditResult } from "./helpers";

/**
 * P4 매크로 지능 패널 — 정직성 계약 (P4-V)
 * ==========================================================================
 * D1~D5·M1~M3 가 만든 것을 `/macro` 가 그린다. 이 스펙이 지키는 것은 "숫자가
 * 맞다" 가 아니라 **"거짓말을 하지 않는다"** 이다:
 *
 *   · 미가용이면 숫자를 하나도 내지 않고 사유를 낸다
 *   · 적중률 옆에 예측집합 크기가 **항상** 있다 (집합을 키우면 적중률은 오른다)
 *   · 개정 편향 사유는 접히지 않는다
 *   · 키 값은 어떤 형태로도 화면에 없다
 *
 * ★서버를 스텁한다★ 라이브 매크로 수집은 느리고(사다리 프로브가 실제로 수집한다)
 * 환경마다 값이 달라 단언이 불안정해진다. 프록시 경로(`/api/backend/**`)만 가로채고
 * 문서 내비게이션은 건드리지 않는다 — A6 에서 글롭이 문서까지 삼켜 페이지가 날 JSON
 * 으로 렌더된 전례가 있다.
 */

const CONSENSUS_SPLIT = {
  verdict: "Goldilocks", consensus: false, tie: false, n_available: 2,
  per_tool: { axis: "Goldilocks", markov: "Stagflation" },
  unavailable: ["cluster"],
  reasons: { cluster: "표본이 부족해 GMM 이 수렴하지 않았습니다" },
  disagreement: { score: 1.0, unique: 2, counts: { Goldilocks: 1, Stagflation: 1 }, n: 2 },
  note: "판정이 1:1 로 갈렸습니다",
};

const FORECAST_OK = {
  available: true, target: 0.9, coverage: 0.966, hits: 28, misses: 1, n_eval: 29,
  mean_set_size: 2.72, k: 1, walk_forward: true,
  note: "walk-forward 실측 적중률입니다 — 평균 집합 크기와 함께 읽어야 합니다.",
};

const LONGRUN_VECM = {
  available: true, model: "vecm", coint_rank: 1,
  variables: ["KR_BASE_RATE", "KR_CPI", "USD_KRW"],
  reason: "요한센 trace 검정에서 공적분 랭크 1 이 유의합니다(95%) — 오차수정항을 갖는 VECM 을 씁니다.",
  evidence: { test: "johansen_trace", trace_stat: [40.1, 12.0], crit_95: [29.8, 15.5] },
  span: { n: 240, k: 3, requested: 240 },
  requested: ["KR_BASE_RATE", "KR_CPI", "USD_KRW"],
  used: ["KR_BASE_RATE", "KR_CPI", "USD_KRW"],
};

const COVERAGE = {
  providers: [
    { provider: "ECOS", declared: 40, verified: 8, derived: 3, backtest_eligible: false,
      revision_bias_note: "한국은행 ECOS 는 빈티지(개정 이력) 엔드포인트를 제공하지 않습니다 — 개정 편향이 남습니다." },
    { provider: "FRED", declared: 21, verified: 21, derived: 0, backtest_eligible: true,
      revision_bias_note: null },
  ],
  keys: [
    { label: "한국은행 ECOS", env_vars: ["BOK_API_KEY"], configured: false, provider: "ECOS",
      series_count: 40, capability_requirements: [], unlocks_levels: [],
      unlocks: "한국 매크로 계열 — 계열 40종" },
    { label: "LLM (Anthropic)", env_vars: ["ANTHROPIC_API_KEY"], configured: false, provider: null,
      series_count: 0, capability_requirements: ["llm"], unlocks_levels: ["L0"],
      unlocks: "공시문 → 뷰 변환 — 사다리 요건 llm, 레벨 L0" },
  ],
  ladder: { level: "L1", note: "DeePM + 수익률곡선", blocked_level: "L0",
            blocked_reason: "torch 미설치 · 실측 표본 부족" },
};

/** 프록시 API 경로만 가로챈다 — 문서 내비게이션은 절대 건드리지 않는다. */
async function stubIntel(page: import("@playwright/test").Page, over: {
  consensus?: unknown; forecast?: unknown; longRun?: unknown; coverage?: unknown;
} = {}) {
  const json = (body: unknown) => ({ status: 200, contentType: "application/json",
                                     body: JSON.stringify(body) });
  await page.route("**/api/backend/api/v1/macro/regime-consensus**",
    (r) => r.fulfill(json(over.consensus ?? CONSENSUS_SPLIT)));
  await page.route("**/api/backend/api/v1/macro/regime-forecast-coverage**",
    (r) => r.fulfill(json(over.forecast ?? FORECAST_OK)));
  await page.route("**/api/backend/api/v1/macro/long-run**",
    (r) => r.fulfill(json(over.longRun ?? LONGRUN_VECM)));
  await page.route("**/api/backend/api/v1/macro/source-coverage**",
    (r) => r.fulfill(json(over.coverage ?? COVERAGE)));
}

test.describe("P4 매크로 지능 패널", () => {
  test("★미가용 블록은 숫자를 하나도 내지 않고 사유를 낸다★", async ({ page }) => {
    await stubIntel(page, {
      forecast: { available: false, reason: "평가 시점이 4개로 최소 20개에 못 미칩니다." },
      longRun: { available: false, reason: "관측이 30개로 최소 60개에 못 미칩니다." },
    });
    await page.goto("/macro");
    const panel = page.locator(".mx-panel");
    await expect(panel).toBeVisible();

    // 사유가 보인다
    await expect(panel.getByText("평가 시점이 4개로")).toBeVisible();
    await expect(panel.getByText("관측이 30개로")).toBeVisible();

    // ★그리고 그 자리에 통계 숫자가 없다★ 노드 수를 먼저 단언해 빈 선택자가
    // 통과하는 것을 막는다(A7 에서 그 실패를 겪었다).
    const reasons = panel.locator(".mx-reason");
    expect(await reasons.count()).toBeGreaterThanOrEqual(2);
    expect(await panel.locator(".mx-stat-v").count()).toBe(0);
  });

  test("★적중률 옆에 예측집합 크기가 항상 있다★", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const stats = page.locator(".mx-panel .mx-stats");
    await expect(stats).toBeVisible();
    // 집합을 키우면 적중률은 언제든 올라간다 — 둘이 떨어지면 화면이 거짓말을 한다.
    await expect(stats).toContainText("96.6%");
    await expect(stats).toContainText("2.72");
    await expect(stats).toContainText("90%");
  });

  test("갈린 판정을 만장일치로 그리지 않고, 개별 도구 판정이 남는다", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const panel = page.locator(".mx-panel");
    await expect(panel.locator(".mx-split")).toBeVisible();      // "갈림"
    await expect(panel.locator(".mx-tools")).toContainText("axis");
    await expect(panel.locator(".mx-tools")).toContainText("markov");
    // 미가용 도구는 사유와 함께 이름이 남는다
    await expect(panel.locator(".mx-tools")).toContainText("cluster");
    await expect(panel).toContainText("GMM 이 수렴하지 않았습니다");
  });

  test("짝 — 전부 일치하면 갈림 표시가 없다", async ({ page }) => {
    await stubIntel(page, {
      consensus: {
        verdict: "Goldilocks", consensus: true, tie: false, n_available: 3,
        per_tool: { axis: "Goldilocks", markov: "Goldilocks", cluster: "Goldilocks" },
        unavailable: [], reasons: {},
        disagreement: { score: 0, unique: 1, counts: { Goldilocks: 3 }, n: 3 },
        note: "가용한 도구 3개가 모두 일치합니다.",
      },
    });
    await page.goto("/macro");
    await expect(page.locator(".mx-panel .mx-split")).toHaveCount(0);
    await expect(page.locator(".mx-panel .mx-tools")).toContainText("Goldilocks");
  });

  test("모형 선택 사유와 검정 근거가 함께 보인다", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const panel = page.locator(".mx-panel");
    await expect(panel).toContainText("VECM");
    await expect(panel).toContainText("요한센 trace 검정에서 공적분 랭크 1");
    // 결론만 내지 않는다 — 통계량과 임계값이 표에 있다
    // ★표가 둘이다(장기관계·커버리지) — strict mode 위반을 피해 첫 표만 본다★
    const lrTbl = panel.locator(".mx-tbl").first();
    await expect(lrTbl).toContainText("40.10");
    await expect(lrTbl).toContainText("29.80");
  });

  test("★개정 편향 사유가 접히지 않는다★", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const bias = page.locator(".mx-panel .mx-bias");
    // ★`.count()` 는 auto-wait 하지 않는다★ 커버리지 블록은 네 번째 쿼리라 늦게
    // 오는데, 세지기 전에 기다리지 않으면 0 을 읽고 "사유가 없다" 로 오판한다.
    await expect(bias.first()).toBeVisible();
    expect(await bias.count()).toBeGreaterThanOrEqual(1);
    await expect(bias.first()).toContainText("빈티지");
    // 접힌 <details> 안에 있으면 안 된다 — 경고는 접지 않는다(A5 경계)
    expect(await page.locator(".mx-panel details:not([open]) .mx-bias").count()).toBe(0);
  });

  test("키 슬롯은 존재 여부만 그리고 값을 그리지 않는다", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const keys = page.locator(".mx-panel .mx-keys li");
    await expect(keys.first()).toBeVisible();   // `.count()` 는 기다리지 않는다
    expect(await keys.count()).toBeGreaterThanOrEqual(2);
    await expect(page.locator(".mx-panel")).toContainText("BOK_API_KEY");
    await expect(page.locator(".mx-panel")).toContainText("미설정");
    // 이 키를 넣으면 무엇이 열리는지가 적혀 있다
    await expect(page.locator(".mx-panel")).toContainText("계열 40종");
    await expect(page.locator(".mx-panel")).toContainText("레벨 L0");
  });

  test("패널이 콘솔 오류나 4xx/5xx 없이 렌더된다", async ({ page }) => {
    const sink = trackErrors(page);
    await stubIntel(page);
    await page.goto("/macro");
    await expect(page.locator(".mx-panel")).toBeVisible();
    expect(sink.pageErrors, sink.pageErrors.join("\n")).toEqual([]);
    expect(sink.api404, sink.api404.join("\n")).toEqual([]);
  });

  test("타입 하한(§56)과 라이트/다크 대비", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    await expect(page.locator(".mx-panel")).toBeVisible();
    // 네 블록이 모두 온 뒤에 잰다 — 마지막 블록의 노드가 빠지면 감사가 헐거워진다.
    await expect(page.locator(".mx-panel .mx-keys li").first()).toBeVisible();

    // 하한 — 노드 수를 먼저 단언한다
    const sizes = await page.locator(".mx-panel *").evaluateAll((els) =>
      els.filter((e) => (e.textContent || "").trim().length > 0 && e.children.length === 0)
         .map((e) => parseFloat(getComputedStyle(e).fontSize)));
    expect(sizes.length).toBeGreaterThan(10);
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(11);

    for (const dark of [false, true]) {
      await page.evaluate((d) => {
        document.documentElement.setAttribute("data-theme", d ? "dark" : "light");
        if (d) document.documentElement.classList.add("dark");
        else document.documentElement.classList.remove("dark");
      }, dark);
      // 전이 중간값이 잡히지 않게 — A9 에서 값을 치른 절차
      await page.waitForTimeout(200);
      // ★`contrastAudit` 는 평가식 문자열을 돌려주고, `page.evaluate` 가 객체를
      // 그대로 준다★ JSON.parse 를 끼우면 "[object Object]" 를 파싱하려다 죽는다.
      const res = await page.evaluate<AuditResult>(contrastAudit(".mx-panel"));
      expect(res.checked, "검사한 텍스트 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(10);
      expect(res.low, `${dark ? "dark" : "light"} AA 미달`).toEqual([]);
      // ★`bright` 는 **다크 전용** 검사다★ "글자만 뒤집히고 배경이 흰 채로 남는" 반만
      // 다크인 상태를 잡는 것이고(aas-dark.spec.ts 가 세운 용법), 라이트에서 밝은
      // 배경은 정상이다. 라이트에도 걸면 올바른 화면이 빨개진다 — 처음에 그렇게 썼다.
      if (dark) {
        expect(res.bright, `다크인데 밝은 배경이 남아 있다`).toEqual([]);
      }
    }
  });
});
