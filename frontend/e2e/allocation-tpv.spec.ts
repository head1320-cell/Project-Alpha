import { expect, test, type Page } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// R0 — 목표 포트폴리오는 하나다 (TargetPortfolioVersion)
// ─────────────────────────────────────────────────────────────────────────────
// ★이 파일에서 가장 값진 것은 1번이다★ 같은 "목표"가 세 화면에서 세 값이었다:
//   · `TimingOverlayPanel.tsx:58-61`  화면에서만 after = before × exposure
//   · `ExecutionRoom.tsx:87`          오버레이 이전 `weights.optimized` 를 주문 목표로
//   · `stress/page.tsx:61`            아예 `holdings`(현재 보유)를 스트레스
// 즉 타이밍 오버레이로 노출을 줄여도 **주문은 그 사실을 몰랐다.**
//
// 1번은 화면 텍스트가 아니라 **서버가 실제로 만든 계획**을 읽는다 — 실행이 향하는 목표가
// 무엇인지는 응답에만 있고, DOM 문구는 그것을 증명하지 못한다.
// ═══════════════════════════════════════════════════════════════════════════════

/** 전략 포트폴리오를 심는다. `addInitScript` 는 매 네비게이션마다 도므로 **없을 때만** 쓴다
 *  (덮어쓰면 /timing 에서 켠 오버레이가 다음 이동에서 사라진다 — timing-overlay.spec 의 기록). */
async function seedPortfolio(page: Page) {
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

async function runOptimize(page: Page) {
  await page.goto("/allocation/optimize", { waitUntil: "domcontentloaded" });
  const run = page.locator(".as-run").first();
  await expect(run).toBeVisible({ timeout: 20_000 });
  await run.click();
  // 결과가 들어와야 실행 준비실이 계획을 만들 수 있다.
  await expect(page.locator(".as-tov, .as-card").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(3_000);
}

/** 실행 준비실에서 계획을 만들고 **서버 응답**을 돌려준다.
 *  ★`page.goto` 로 가면 안 된다 (실측)★ 최적화 결과는 `AllocationProvider` 의 React 상태라
 *  전체 리로드에서 사라지고, 실행 준비실은 목표가 없다며 산출 버튼 자체를 그리지 않는다.
 *  그래서 스파인(위저드)으로 **앱 안에서** 이동한다 — 실제 사용자의 경로이기도 하다. */
async function buildPlan(page: Page) {
  // ★`click()` 이 아니라 `dispatchEvent` 를 쓰는 이유 (R0 실측)★
  // 스파인의 마지막 스텝(`08 EXECUTION`)은 위치가 안정적인데도(1.4초 동안 rect 불변)
  // 중심점의 `document.elementFromPoint` 가 `<span class="aas-wiz-sep">` 를 돌려준다 —
  // 마지막 페이즈의 스텝이 컨테이너를 넘쳐(A9 가 받아들인 `overflow-x` 트레이드오프)
  // 중심이 구분자 아래에 깔린다. 즉 **마우스로는 눌리지 않는다.**
  // 이 스펙의 대상은 목표-버전 관통이지 스파인 레이아웃이 아니므로 여기서는 우회하고,
  // 그 결함 자체는 별도 부채로 기록한다(고쳐지면 이 우회를 지울 것).
  await page.locator(".aas-wiz-step", { hasText: "EXECUTION" }).first().dispatchEvent("click");
  await expect(page).toHaveURL(/\/allocation\/execution/, { timeout: 20_000 });
  const run = page.locator(".as-exec-run").first();
  await expect(run).toBeVisible({ timeout: 20_000 });
  const [resp] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/execution-plan") && r.request().method() === "POST",
      { timeout: 30_000 }),
    run.click(),
  ]);
  return { resp, req: resp.request(), body: await resp.json() };
}

function targetSum(body: { plan?: { orders?: { tgt_weight_pct: number }[] } }): number {
  const orders = body.plan?.orders ?? [];
  return orders.reduce((a, o) => a + (o.tgt_weight_pct ?? 0), 0);
}

// ── 1. ★실행은 목표 버전을 거쳐 주문한다★ ──────────────────────────────────
// ★첫 판은 "오버레이를 걸면 목표 합이 100% 미만"으로 썼다가 폐기했다 (실측)★
// 이 환경의 카나리는 노출 **1.0(risk-on)** 이라 오버레이를 걸어도 줄어들 것이 없다.
// 즉 그 단언은 배선이 아니라 **그날의 시장 상태**를 재고 있었다 — 데이터가 바뀌면
// 빨강/초록이 뒤집히는 가드는 가드가 아니다. 그래서 계약 자체를 잰다:
// 실행 요청이 `tpv_id` 를 싣고, 계획의 목표가 **그 버전의 `final_weights` 와 같은가.**
test("★실행 계획의 목표가 서버가 컴파일한 목표 버전과 일치한다★", async ({ page }) => {
  test.setTimeout(180_000);
  const sink = trackErrors(page);
  await seedPortfolio(page);

  // 오버레이를 건다 — 전략 비중은 유지하고 노출만 조정하는 비파괴 경로.
  await page.goto("/allocation/timing", { waitUntil: "domcontentloaded" });
  await page.locator(".as-tm-overlay").click({ timeout: 30_000 });

  await runOptimize(page);
  const { req, body } = await buildPlan(page);

  expect(body.blocked, `실행이 막혔다: ${body.reason ?? ""}`).not.toBe(true);
  const orders = body.plan?.orders ?? [];
  expect(orders.length, "주문이 하나도 없으면 아래 단언은 뜻이 없다").toBeGreaterThan(0);

  // (a) 실행이 목표 버전을 지정했는가 — 예전에는 `weights.optimized` 를 그대로 보냈다.
  const sent = req.postDataJSON() as { tpv_id?: string };
  expect(sent.tpv_id, "실행이 목표 버전 없이 주문 목표를 정했다").toBeTruthy();

  // (b) 계획의 목표가 그 버전과 **같은가** — 화면과 주문이 다른 목표를 향하면 안 된다.
  const tvResp = await page.request.get(
    `/api/backend/api/v1/allocation/target-versions/${sent.tpv_id}`);
  expect(tvResp.ok(), await tvResp.text()).toBeTruthy();
  const tv = await tvResp.json();
  const planTargets = Object.fromEntries(
    orders.map((o: { stock_code: string; tgt_weight_pct: number }) => [o.stock_code, o.tgt_weight_pct]));
  for (const [code, w] of Object.entries(tv.final_weights as Record<string, number>)) {
    expect(planTargets[code], `${code} 의 주문 목표가 목표 버전과 다르다`).toBeCloseTo(w, 1);
  }
  // (c) 오버레이가 실제로 반영됐는가 — 노출만큼만 투자하고 나머지는 현금이다.
  //     노출이 1.0 인 날에도 이 항등식은 성립한다(현금 0).
  expect(targetSum(body) + tv.cash_weight, "목표 + 현금이 100%가 아니다")
    .toBeCloseTo(Object.values(tv.base_weights as Record<string, number>)
      .reduce((a, b) => a + b, 0), 1);
  expect(targetSum(body), "노출 배율이 목표에 반영되지 않았다")
    .toBeCloseTo(Object.values(tv.base_weights as Record<string, number>)
      .reduce((a, b) => a + b, 0) * (tv.overlay?.exposure ?? 1), 1);

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
});

// ── 2. 오버레이 산수가 실제로 주문을 줄인다 (API 로 결정적으로 잰다) ────────
// UI 경로는 카나리 상태에 의존하므로, **노출 축소가 주문에 도달하는가**는 여기서
// 결정적으로 잰다 — 노출 0.6 목표를 만들고 그 id 로 계획을 세운다.
test("★노출 60% 목표는 60%만 주문하고 40%는 현금이다★", async ({ page }) => {
  const made = await page.request.post("/api/backend/api/v1/allocation/target-versions", {
    data: { base_weights: { "005930": 60, "000660": 40 },
            overlay: { exposure: 0.6, source: "canary" } },
  });
  expect(made.ok(), await made.text()).toBeTruthy();
  const tv = await made.json();
  expect(tv.status).toBe("executable");
  expect(tv.cash_weight).toBeCloseTo(40, 1);

  const r = await page.request.post("/api/backend/api/v1/allocation/execution-plan", {
    data: { current_weights: { "005930": 60, "000660": 40 }, tpv_id: tv.tpv_id,
            portfolio_value: 1e8 },
  });
  const body = await r.json();
  expect(body.blocked).not.toBe(true);
  expect(targetSum(body), "노출 60% 인데 주문 목표가 60%가 아니다").toBeCloseTo(60, 1);
});

// ── 3. 실행은 승인된 목표만 받는다 ──────────────────────────────────────────
test("★승인되지 않은 목표는 실행이 사유와 함께 거부한다★", async ({ page }) => {
  test.setTimeout(120_000);
  await seedPortfolio(page);

  // 서버에 `research_only` 목표를 하나 만들어 두고, 그 id 로 계획을 요청한다.
  const made = await page.request.post("/api/backend/api/v1/allocation/target-versions", {
    data: {
      base_weights: { "005930": 60, "000660": 40 },
      overlay: null, neutralized: true,          // 사후 중립화 → research_only
    },
  });
  expect(made.ok(), await made.text()).toBeTruthy();
  const tv = await made.json();
  expect(tv.status, "중립화된 목표가 executable 로 나왔다").toBe("research_only");
  expect(tv.tpv_id, "저장되지 않았다면 아래 단언은 성립하지 않는다").toBeTruthy();

  const r = await page.request.post("/api/backend/api/v1/allocation/execution-plan", {
    data: { current_weights: { "005930": 50, "000660": 50 }, tpv_id: tv.tpv_id,
            portfolio_value: 1e8 },
  });
  const body = await r.json();
  expect(body.blocked, "승인되지 않은 목표로 계획이 만들어졌다").toBe(true);
  expect(body.reason).toContain("중립화");
  expect(body.plan ?? null, "차단했는데 계획을 만들어 뒀다").toBeNull();
});
