import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, freezeCharts, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// M2 — 기대수익 엔진 근거 · 분포 무가정 예측 구간
// ─────────────────────────────────────────────────────────────────────────────
// 백엔드는 pytest 가 지킨다(entropy_views 25 · mes_capability 16 · conformal 10 ·
// case_binding 13). 이 스펙이 지키는 것은 **화면 계약** 넷이다:
//
//   1. 미가용 엔진이 숫자를 내지 않는다 — 사유만 낸다
//   2. ★엔진 라벨은 서버의 `mu_engine` 이지 화면의 `model` 추측이 아니다★
//      뷰가 없으면 BL 도 시장균형이고, 그때 μ 엔진은 BL 이 아니다. 화면이 `model` 로
//      추측하면 서버가 실제로 탄 경로와 갈라지고, 그 갈라짐은 타입 에러를 내지 않는다.
//   3. EP 가 신뢰도를 쓰지 않는다는 사실이 화면에 있다 (매핑을 지어내지 않았음을 밝힌다)
//   4. conformal 적중률은 **실측**이지 이론 `1-α` 가 아니다
//
// ★서버 상태를 남기지 않는다★ `/analyze` 와 `/backtest` 를 전부 스텁한다 — A4 의 알파
// 스펙이 실제로 ResearchRun 을 기록해 `research-run-roundtrip` 을 타임아웃시킨 전례가 있다.
// ═══════════════════════════════════════════════════════════════════════════════

test.beforeEach(async ({ page }) => { await freezeCharts(page); });

/** 최소 형태의 `/analyze` 응답 — 화면이 그리는 데 필요한 키만. */
function analyzeBody(over: Record<string, unknown> = {}) {
  const names = ["005930", "000660"];
  return {
    error: false,
    names,
    labels: { "005930": "삼성전자", "000660": "SK하이닉스" },
    excluded: [],
    coverage: { start: "2023-01-02", end: "2026-08-14", n_obs: 900,
                benchmark_available: true, source: "db" },
    model: "bl",
    params: { delta: 2.5, tau: 0.05, lookback_days: 756 },
    views_applied: false,
    skipped_views: [],
    cap_missing: [],
    weights: { current: { "005930": 60, "000660": 40 },
               optimized: { "005930": 55, "000660": 45 } },
    flow: { market: { "005930": 50, "000660": 50 },
            view_applied: { "005930": 50, "000660": 50 },
            optimized: { "005930": 55, "000660": 45 } },
    frontier: { curve: [], cloud: { returns: [], volatilities: [], sharpes: [] } },
    points: { current: { r: 8, v: 15 }, market: { r: 7, v: 14 }, optimal: { r: 9, v: 15 } },
    risk_contributions: { "005930": 55, "000660": 45 },
    correlation: { "005930": { "005930": 1, "000660": 0.4 },
                   "000660": { "005930": 0.4, "000660": 1 } },
    summary: { portfolio: {}, benchmark: null, active: null, benchmark_label: null,
               extra: {} },
    mc: null,
    constraints_report: null,
    mu_engine: "mvo",
    ep: null,
    mes: null,
    ...over,
  };
}

const EP_OK = {
  available: true, feasible: true, n_views: 1, kl: 0.12,
  ens: 640, ens_prior: 756, confidence_used: false,
  violations: [], skipped: [], note: null,
};

async function stubAnalyze(page: Page, over: Record<string, unknown> = {}) {
  await page.route("**/api/v1/allocation/analyze", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(analyzeBody(over)) });
  });
}

/** 게이트 → 05 OPTIMIZE. 재계산을 눌러 스텁 응답이 화면 상태가 되게 한다. */
async function enterOptimize(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  // ★엔진 버튼은 닫힌 <details class="aas-adv"> 안에 있다★ (실측 — 첫 작성에서
  // `.as-engine-seg button` 으로 잡으려다 두 테스트가 1.5분씩 타임아웃했다.)
  // 먼저 고급 설정을 열고, 모델 버튼을 눌러 runAnalyze 를 태운다 — 스텁이 응답한다.
  await page.locator("details.aas-adv summary").first().click();
  await page.locator(".as-models button").first().click();
  await expect(page.locator(".as-eng")).toBeVisible({ timeout: 20_000 });
}

// ── 1. ★미가용 엔진은 숫자를 내지 않는다★ ──────────────────────────────────

test("★EP 가 실현 불가면 비중 숫자가 아니라 사유가 온다★", async ({ page }) => {
  await stubAnalyze(page, {
    mu_engine: "ep",
    ep: { ...EP_OK, feasible: false, note: null,
          violations: [{ view_index: 0, assets: "005930", direction: 1,
                         requested_pct: 20, achieved_pct: 3.41, gap_pct: 16.59 }] },
  });
  await enterOptimize(page);

  const panel = page.locator(".as-eng");
  await expect(panel.locator(".as-eng-badge.bad")).toHaveText(/실현 불가/);

  // 위반은 **사용자 용어**로 온다 — 변환 공간의 부호 뒤집힌 값이 아니다.
  const viol = panel.locator(".as-eng-viol li");
  await expect(viol).toHaveCount(1);
  await expect(viol.first()).toContainText("005930");
  await expect(viol.first()).toContainText("20.00%");
  await expect(viol.first()).toContainText("3.41%");
});

test("★미가용 사유는 접히지 않는다★ (A5 경계 — 설명은 접고 사유는 접지 않는다)",
  async ({ page }) => {
    await stubAnalyze(page, {
      mu_engine: "ep",
      ep: { ...EP_OK, feasible: false,
            violations: [{ view_index: 0, assets: "000660", direction: -1,
                           requested_pct: -15, achieved_pct: -2.0, gap_pct: 13 }] },
    });
    await enterOptimize(page);
    // 닫힌 <details> 안이면 innerText 가 빈 문자열이라 textContent 로 본다(A6 기록).
    const inClosed = await page.locator(".as-eng .as-eng-viol").evaluate(
      (el) => !!el.closest("details:not([open])"));
    expect(inClosed, "위반 내역이 닫힌 details 안에 있다").toBe(false);
  });

// ── 2. ★라벨은 서버가 준 것이다★ (짝 단언) ─────────────────────────────────

test("엔진 라벨이 서버의 mu_engine 을 그대로 쓴다 (ep)", async ({ page }) => {
  await stubAnalyze(page, { mu_engine: "ep", ep: EP_OK });
  await enterOptimize(page);
  await expect(page.locator(".as-eng .as-eng-v")).toHaveText("Entropy Pooling");
});

test("★model 이 bl 이어도 mu_engine 이 mvo 면 화면은 MVO 라고 말한다★", async ({ page }) => {
  // 이것이 짝 단언이다. 앞 테스트만 있으면 화면이 `model` 로 추측해도 통과할 수 있다.
  // 뷰 없는 BL 은 시장균형이고 그때 μ 엔진은 BL 이 아니다 — 서버가 그 사실을 안다.
  await stubAnalyze(page, { model: "bl", views_applied: false, mu_engine: "mvo", ep: null });
  await enterOptimize(page);
  await expect(page.locator(".as-eng .as-eng-v")).toHaveText(/MVO/);
  await expect(page.locator(".as-eng .as-eng-v")).not.toHaveText(/Black-Litterman/);
});

// ── 3. ★신뢰도를 쓰지 않는다는 사실이 화면에 있다★ ─────────────────────────

test("★EP 가 신뢰도를 쓰지 않는다고 화면이 말한다★", async ({ page }) => {
  await stubAnalyze(page, { mu_engine: "ep", ep: EP_OK });
  await enterOptimize(page);
  // 이 문구가 없으면 사용자는 BL 처럼 신뢰도가 반영됐다고 읽는다. 매핑을 지어내지
  // 않았다는 사실 자체가 화면에 있어야 그 오해가 막힌다.
  await expect(page.locator(".as-eng")).toContainText("신뢰도를 사용하지 않습니다");
});

test("유효 시나리오 수가 사전 → 사후로 함께 온다", async ({ page }) => {
  await stubAnalyze(page, { mu_engine: "ep", ep: { ...EP_OK, ens_prior: 756, ens: 640 } });
  await enterOptimize(page);
  const txt = await page.locator(".as-eng").textContent();
  expect(txt).toContain("756");
  expect(txt).toContain("640");
});

test("MES 가 없으면 증거 줄을 그리지 않는다 (지어내지 않는다)", async ({ page }) => {
  await stubAnalyze(page, { mu_engine: "mvo", ep: null, mes: null });
  await enterOptimize(page);
  await expect(page.locator(".as-eng")).not.toContainText("고정된 매크로 증거");
});

test("MES 레벨 불일치는 경고로 보인다", async ({ page }) => {
  await stubAnalyze(page, {
    mu_engine: "ep", ep: EP_OK,
    mes: { mes_id: "rgs_e2e_0001", as_of: "2026-08-14", capability_level: "L3",
           capability_reason: null, live_capability_level: "L1",
           capability_diverged: "이 증거가 고정될 때는 L3 였고 지금은 L1 입니다 — 같은 증거라도 지금 쓸 수 있는 도구가 달라졌습니다." },
  });
  await enterOptimize(page);
  await expect(page.locator(".as-eng .as-eng-warn")).toContainText("달라졌습니다");
  await expect(page.locator(".as-eng")).toContainText("rgs_e2e_0001");
});

// ── 4. ★적중률은 실측이지 이론값이 아니다★ ─────────────────────────────────

function backtestBody(conformal: unknown) {
  return {
    error: false,
    dates: ["2025-01-02", "2025-01-03"],
    equity_curve: [1.0, 1.01],
    bench_curve: null,
    drawdown_curve: [0, 0],
    rebalances: [{ date: "2025-01-02", weights: { "005930": 100 }, turnover_pct: 0 }],
    n_rebalances: 57,
    turnover_avg_pct: 3.2,
    metrics: {},
    summary: {
      total_return_pct: 12.3, cagr_pct: 6.1, volatility_pct: 11.0, sharpe_ratio: 0.55,
      sortino_ratio: 0.7, calmar_ratio: 0.4, max_drawdown_pct: -15.0,
      active_return_pct: null, information_ratio: null,
    },
    config: { model: "mvo", rebalance: "M", window: "expanding", cost_bps: 10, n_obs: 1300 },
    conformal,
    labels: { "005930": "삼성전자" },
    coverage: { source: "db", start: "2019-01-02", end: "2026-08-14", n_obs: 1300 },
    benchmark_label: null,
    excluded: [],
  };
}

async function enterJournalBacktest(page: Page, conformal: unknown) {
  await page.route("**/api/v1/allocation/backtest", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(backtestBody(conformal)) });
  });
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "정책 백테스트", exact: true }).first().click();
  await expect(page.locator(".as-bt-cf")).toBeVisible({ timeout: 25_000 });
}

test("★적중률이 홀드아웃 실측값으로 온다 (1-α 가 아니다)★", async ({ page }) => {
  await enterJournalBacktest(page, {
    available: true, alpha: 0.1, unit: "daily_mean_return", n_pairs: 56, n_required: 9,
    next_period: { point: 0.00058, lower: -0.0033, upper: 0.00445, half_width: 0.00387 },
    measured_coverage: { available: true, coverage: 0.9411764705882353, n: 17, hits: 16,
                         mean_width: 0.0077, n_calibration: 39 },
    note: "다음 리밸런스 구간의 **일평균** 포트폴리오 수익률 구간입니다.",
  });
  const cf = page.locator(".as-bt-cf");
  // ★분수까지 보여야 한다★ 94.1% 만 있으면 이론값인지 실측인지 구분할 수 없다.
  await expect(cf).toContainText("94.1%");
  await expect(cf).toContainText("16/17");
  await expect(cf).not.toContainText("90.0%");
});

test("★보정 표본이 모자라면 숫자 자리에 사유가 온다★", async ({ page }) => {
  await enterJournalBacktest(page, {
    available: false, alpha: 0.1, n_pairs: 8, n_required: 9,
    reason: "완료된 리밸런스 구간이 8개로 보정 최소치 9개에 미치지 못합니다 (α=0.1) — 구간을 만들 수 없습니다.",
  });
  const cf = page.locator(".as-bt-cf");
  await expect(cf.locator(".as-bt-cf-na")).toContainText("보정 최소치");
  // 구간을 못 만들었으면 구간 숫자가 없어야 한다.
  await expect(cf).not.toContainText("~");
});

test("적중률을 잴 수 없으면 그 사실만 적고 숫자를 만들지 않는다", async ({ page }) => {
  await enterJournalBacktest(page, {
    available: true, alpha: 0.1, unit: "daily_mean_return", n_pairs: 12, n_required: 9,
    next_period: { point: 0.0004, lower: -0.002, upper: 0.0028, half_width: 0.0024 },
    measured_coverage: { available: false, reason: "적중률을 잴 홀드아웃 표본이 없습니다." },
    note: null,
  });
  await expect(page.locator(".as-bt-cf")).toContainText("홀드아웃 표본이 없습니다");
});

// ── 5. §56 하한 + 라이트/다크 AA ────────────────────────────────────────────

test("§56 하한 + 대비: 엔진 근거 패널", async ({ page }) => {
  await stubAnalyze(page, { mu_engine: "ep", ep: EP_OK });
  await enterOptimize(page);

  const sizes = await page.locator(".as-eng *").evaluateAll((els) =>
    els.filter((e) => (e.textContent || "").trim().length > 0)
       .map((e) => parseFloat(getComputedStyle(e).fontSize)));
  expect(sizes.length, "잴 노드가 없으면 이 단언은 공허하다").toBeGreaterThan(4);
  expect(Math.min(...sizes)).toBeGreaterThanOrEqual(11);

  // `contrastAudit` 은 evaluate 문자열을 돌려준다 (A2 에서 helpers 로 추출한 형태).
  const AUDIT = contrastAudit(".aas-root");

  const light = await page.evaluate<AuditResult>(AUDIT);
  expect(light.checked, "라이트에서 검사한 텍스트 노드 수").toBeGreaterThan(10);
  expect(light.low, `라이트 AA 미달: ${JSON.stringify(light.low.slice(0, 6))}`).toHaveLength(0);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  // ★전이 중간값이 잡히는 것을 피한다★ Badge·Button 의 `transition-colors` 때문에
  // 클래스를 붙인 직후 읽으면 라이트·다크의 중간색이 나와 없는 결함이 보고된다(A9 실측).
  await page.waitForTimeout(200);
  const dark = await page.evaluate<AuditResult>(AUDIT);
  expect(dark.checked, "다크에서 검사한 텍스트 노드 수").toBeGreaterThan(10);
  expect(dark.low, `다크 AA 미달: ${JSON.stringify(dark.low.slice(0, 6))}`).toHaveLength(0);
  expect(dark.bright, `밝은 배경 누출: ${JSON.stringify(dark.bright.slice(0, 6))}`).toHaveLength(0);
});
