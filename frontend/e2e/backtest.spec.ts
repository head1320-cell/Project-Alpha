import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BacktestRun workflow regression (스펙 §5) — locks in the durable run flow so a
// regression (results rendered under the config form, navigation before a valid
// run_id, dead loading/results URLs, mojibake) makes CI go red.
//
//  Test A drives the REAL backend: clicking "백테스트 실행" must create a run and
//  navigate to a dedicated /loading URL (never render results under the form), the
//  monitor must show a REAL stage + config, and cancel must reach an honest state.
//  It cancels instead of waiting out the full multi-minute simulation.
//
//  Test B stubs the run API with a real-schema completed payload so the
//  loading→results transition, the results workspace, honesty badges, Korean
//  encoding, and refresh recovery are verified deterministically and fast.
// ═══════════════════════════════════════════════════════════════════════════════

// Resilience regression (stubbed, deterministic): a transient status-poll error (proxy 504 / DB
// blip) must NOT flip the loading page to the terminal "만료된 링크" state — it keeps polling and
// shows live progress. Stubs the run API so it's fast and independent of the real engine.
const RESIL_ID = "bt_resil_e2e_1";
function simStatus() {
  return {
    run_id: RESIL_ID, status: "simulating", progress_percent: 55, current_stage: "simulating",
    status_message: "시뮬레이션 400/785일", strategy_name: "Condition",
    created_at: 1_700_000_000, started_at: 1_700_000_001, completed_at: null,
    error_code: null, error_message: null, correlation_id: RESIL_ID,
    is_mock_data: true, is_pit_verified: false, engine_version: "dev",
  };
}

test("Backtest: loading survives transient status errors (keeps polling, no dead-end)", async ({ page }) => {
  let n = 0;
  await page.route(new RegExp(`/runs/${RESIL_ID}/status`), (route) => {
    n += 1;
    // first 4 polls fail transiently (503), then recover to a live 'simulating' status
    if (n <= 4) return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(simStatus()) });
  });
  await page.route(new RegExp(`/runs/${RESIL_ID}$`), (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...simStatus(), input_snapshot: { universe: "kospi200" }, parameter_snapshot: {}, result: null }) }));

  await page.goto(`/backtest/runs/${RESIL_ID}/loading`, { waitUntil: "domcontentloaded" });
  // through the transient window the terminal not-found must never appear
  for (let i = 0; i < 8; i++) {
    await page.waitForTimeout(1000);
    expect(await page.locator("body").innerText(), "no terminal not-found during transient errors")
      .not.toContain("만료되었거나 잘못된 링크");
  }
  // it recovered to live progress
  await expect(page.locator(".brun-progress")).toBeVisible();
  await expect(page.locator(".brun-stage")).toContainText("시뮬레이션");
});

// ★실제 인시던트 회귀★ — 숨겨진 탭에서 폴링이 영구 정지하던 문제.
// react-query의 retryer는 재시도 대기 후 canContinue()에서 focusManager.isFocused()를 보고,
// 탭이 숨겨져 있으면 timeout 없이 pause()한다. 그 뒤 1초 interval은 전부 dedupe되어 멈춘
// promise를 돌려주므로 브라우저에서 요청이 한 건도 나가지 않는다 — 사용자가 터미널을 보는
// 동안 UI가 마지막 스냅샷("시뮬레이션 63/728일")에 얼어붙은 채 "재시도 중"만 띄웠던 원인.
// 수정(retry:false + networkMode:"always")은 retryer를 폴링 루프에서 제거한다.
const HIDDEN_ID = "bt_hidden_e2e_1";

test("Backtest: polling survives a hidden tab (no permanent retryer pause)", async ({ page }) => {
  let polls = 0;
  let failing = true;
  await page.route(new RegExp(`/runs/${HIDDEN_ID}/status`), (route) => {
    polls += 1;
    if (failing) {
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary" }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...simStatus(), run_id: HIDDEN_ID }) });
  });
  await page.route(new RegExp(`/runs/${HIDDEN_ID}$`), (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...simStatus(), run_id: HIDDEN_ID, input_snapshot: { universe: "kospi200" }, parameter_snapshot: {}, result: null }) }));

  await page.goto(`/backtest/runs/${HIDDEN_ID}/loading`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  // 탭을 숨긴다 — 사용자가 터미널로 전환한 순간을 재현
  await page.emulateMedia({ reducedMotion: null });
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { get: () => "hidden", configurable: true });
    Object.defineProperty(document, "hidden", { get: () => true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });

  const atHide = polls;
  await page.waitForTimeout(6000);
  // 수정 전: 여기서 polls가 전혀 늘지 않았다(retryer pause). 수정 후: 계속 나간다.
  expect(polls - atHide, "polling must continue while the tab is hidden").toBeGreaterThan(2);

  // 숨겨진 채로 서버가 회복되면 UI도 따라와야 한다
  failing = false;
  await page.waitForTimeout(3000);
  await expect(page.locator(".brun-stage")).toContainText("시뮬레이션");
});

test("Backtest: a genuinely missing run shows the honest not-found (real 404)", async ({ page }) => {
  await page.goto("/backtest/runs/bt_missing_e2e_xyz/loading", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("만료되었거나 잘못된 링크")).toBeVisible({ timeout: 15_000 });
});

test("Backtest: run button creates a run + navigates to loading (never in-form) + honest cancel", async ({ page }) => {
  const sink = trackErrors(page);

  await page.goto("/backtest", { waitUntil: "networkidle" });
  const runBtn = page.locator(".tbt-run").first();
  await expect(runBtn).toBeVisible();
  await expect(runBtn).toContainText("백테스트 실행");

  await runBtn.click();
  // Never render final results under the form — must navigate to a dedicated run URL.
  await page.waitForURL(/\/backtest\/runs\/.+\/loading/, { timeout: 20_000 });
  const runId = page.url().match(/runs\/([^/]+)\/loading/)?.[1];
  expect(runId, "a real run_id in the URL").toBeTruthy();
  expect(page.url()).not.toMatch(/\/backtest$/); // left the config page

  // The loading monitor shows a REAL current stage (one of the lifecycle labels) + config rows.
  await expect(page.locator(".brun-stage").first()).toBeVisible();
  const stage = (await page.locator(".brun-stage").first().innerText()).trim();
  expect(stage.length, "a real stage label is shown").toBeGreaterThan(0);
  expect(await page.locator(".brun-cfg tr").count(), "config snapshot rows").toBeGreaterThan(0);
  expect(await page.locator("body").innerText()).not.toMatch(/�/); // encoding intact

  // Safe cancel → honest terminal state (not a silent hang).
  await page.locator(".brun-btn", { hasText: "실행 취소" }).first().click();
  await expect(page.locator(".brun-err-title")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".brun-err-title")).toContainText("취소");

  expect(uniq(sink.api404), "backtest run API 404s").toEqual([]);
  expect(uniq(sink.pageErrors), "backtest page errors").toEqual([]);
});

// A real-schema completed payload (ScreenToBacktestResult) — small but shape-accurate.
const STUB_RUN_ID = "bt_stub_e2e_1";
function completedRun() {
  const base = {
    run_id: STUB_RUN_ID,
    status: "completed",
    progress_percent: 100,
    current_stage: "completed",
    status_message: "완료",
    strategy_name: "골든크로스 (E2E)",
    created_at: 1_700_000_000,
    started_at: 1_700_000_001,
    completed_at: 1_700_000_050,
    error_code: null,
    error_message: null,
    correlation_id: STUB_RUN_ID,
    is_mock_data: true,
    is_pit_verified: false,
    engine_version: "dev",
  };
  const stats = {
    total_return_pct: 12.3, cagr: 5.8, max_drawdown_pct: -14.2, volatility_pct: 18.1,
    sharpe_ratio: 0.72, sortino_ratio: 0.95, calmar_ratio: 0.41, win_rate: 54.0,
    profit_factor: 1.35, num_trades: 3, var_pct: -2.1, cvar_pct: -2.6,
    total_commission: 41000, total_slippage: 12000, eod_liquidated: 1,
  };
  const result = {
    error: false,
    screened_tickers: ["005930", "000660"],
    screened_count: 2,
    data_source: { fundamentals: "mock", market_data: "mock", fully_real: false },
    backtest: {
      id: 1, ran_at: 1_700_000_050, duration_seconds: 1.2, statistics: stats,
      equity_curve: [100, 103, 101, 108, 112], equity_dates: ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05"],
      drawdown_curve: [0, 0, -1.9, 0, 0], monthly_returns: [3.0, -1.9, 6.9, 3.7],
      benchmark: { label: "KOSPI", curve: [100, 101, 100, 104, 106], total_return_pct: 6.0, excess_return_pct: 6.3, beta: 0.9, alpha_pct: 4.1 },
      trade_mode: "backtest",
      round_trips: [
        { stock_code: "005930", corp_name: "삼성전자", entry_date: "2023-01-05", exit_date: "2023-03-10", entry_price: 60000, exit_price: 66000, return_pct: 10.0, reason: "기간종료 청산", quantity: 10, pnl: 60000 },
        { stock_code: "000660", corp_name: "SK하이닉스", entry_date: "2023-02-01", exit_date: "2023-04-20", entry_price: 90000, exit_price: 85000, return_pct: -5.6, reason: "데드크로스", quantity: 5, pnl: -25000 },
      ],
      trades: [],
      symbol_results: [
        { symbol: "005930", corp_name: "삼성전자", total_return_pct: 10.0, realized_pnl: 60000, round_trips: 1, win_rate: 100, avg_hold_days: 64, contribution_pct: 7.1 },
        { symbol: "000660", corp_name: "SK하이닉스", total_return_pct: -5.6, realized_pnl: -25000, round_trips: 1, win_rate: 0, avg_hold_days: 78, contribution_pct: -2.0 },
      ],
      charts: {},
    },
    intraday: null, asset_alloc: null, backtest_config: {},
  };
  const input_snapshot = { universe: "kospi200", start_date: "2023-01-01", end_date: "2023-05-31", strategy_name: "Condition", benchmark: "KOSPI" };
  return { lite: { ...base }, full: { ...base, input_snapshot, parameter_snapshot: {}, result } };
}

test("Backtest: completed run → results workspace renders + refresh recovery (stubbed, deterministic)", async ({ page }) => {
  const sink = trackErrors(page);
  const { lite, full } = completedRun();

  await page.route("**/api/v1/backtest/runs/**/status", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(lite) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(full) }));

  // Loading page must auto-navigate to results once status is completed.
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/loading`, { waitUntil: "networkidle" });
  await page.waitForURL(new RegExp(`/backtest/runs/${STUB_RUN_ID}/results`), { timeout: 15_000 });

  // Results workspace: header, grouped diagnostics, attribution, honesty badges, Korean intact.
  await expect(page.locator("h1")).toContainText("골든크로스");
  await expect(page.locator(".brun-kpi").first()).toBeVisible();
  expect(await page.locator(".brun-kpi").count(), "KPI cards for available metrics").toBeGreaterThan(6);
  // metrics are grouped into honest diagnostic sections (only groups with data render)
  const groups = await page.locator(".brun-mgroup-t").allInnerTexts();
  expect(groups.length, "grouped metric sections").toBeGreaterThan(2);
  // attribution chart (from engine contribution_pct) + honest omission note
  await expect(page.locator(".brun-card-t", { hasText: "Attribution" })).toBeVisible();
  await expect(page.locator(".brun-diag-omit")).toContainText("MFE/MAE");
  await expect(page.getByText("MOCK 데이터").first()).toBeVisible();
  await expect(page.getByText("PIT 미검증").first()).toBeVisible();
  await expect(page.locator("table").first()).toBeVisible(); // symbols / trades
  const body = await page.locator("body").innerText();
  expect(body).toContain("삼성전자");
  expect(body).not.toMatch(/�/);

  // Refresh recovery: the results URL is durable (bookmarkable / reloadable).
  await page.reload({ waitUntil: "networkidle" });
  expect(page.url()).toMatch(new RegExp(`/backtest/runs/${STUB_RUN_ID}/results`));
  await expect(page.locator(".brun-kpi").first()).toBeVisible();

  expect(uniq(sink.api404), "results API 404s").toEqual([]);
  expect(uniq(sink.pageErrors), "results page errors").toEqual([]);
});

test("Backtest: compare two completed runs → overlay + metric delta + config diff (stubbed)", async ({ page }) => {
  const sink = trackErrors(page);
  const a = completedRun();
  // run B: a distinct completed run (different id, config, stronger stats).
  const B_ID = "bt_stub_e2e_2";
  const bFull = JSON.parse(JSON.stringify(a.full));
  bFull.run_id = B_ID; bFull.correlation_id = B_ID; bFull.strategy_name = "모멘텀 (E2E)";
  bFull.result.backtest.statistics.total_return_pct = 24.9;
  bFull.result.backtest.statistics.sharpe_ratio = 1.15;
  bFull.result.backtest.equity_curve = [100, 106, 110, 115, 121];
  bFull.input_snapshot = { ...a.full.input_snapshot, strategy_name: "모멘텀", start_date: "2022-06-01" };
  const bLite = { ...a.lite, run_id: B_ID, strategy_name: "모멘텀 (E2E)" };

  await page.route("**/api/v1/backtest/runs", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [a.lite, bLite] }) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(a.full) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${B_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(bFull) }));

  await page.goto(`/backtest/runs/${STUB_RUN_ID}/compare`, { waitUntil: "networkidle" });
  await expect(page.locator("h1")).toContainText("실행 비교");
  // pick run B from the candidate list (completed, not A)
  const select = page.locator(".brun-select");
  await expect(select).toBeVisible();
  await select.selectOption(B_ID);

  // overlay + metric delta + config diff all render
  await expect(page.locator(".brun-card-t", { hasText: "정규화 자산곡선" })).toBeVisible();
  await expect(page.locator(".brun-card-t", { hasText: "지표 델타" })).toBeVisible();
  await expect(page.locator(".brun-card-t", { hasText: "설정 차이" })).toBeVisible();
  expect(await page.locator(".brun-cmp tbody tr").count(), "delta+diff rows").toBeGreaterThan(4);
  // config diff highlights the differing strategy/date rows
  await expect(page.locator(".brun-cmp-diff").first()).toBeVisible();
  const body = await page.locator("body").innerText();
  expect(body).toContain("모멘텀");
  expect(body).not.toMatch(/�/);

  expect(uniq(sink.api404), "compare API 404s").toEqual([]);
  expect(uniq(sink.pageErrors), "compare page errors").toEqual([]);
});
