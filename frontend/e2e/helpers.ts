import type { Page } from "@playwright/test";

// External hosts blocked by the sandbox/CSP (fonts, analytics) are not app failures.
const IGNORE_URL = /fonts\.googleapis\.com|fonts\.gstatic\.com|google-analytics|gtag/;
const IGNORE_CONSOLE = /ERR_CONNECTION_RESET|Failed to load resource.*font|net::ERR_/;

export interface ErrorSink {
  pageErrors: string[];
  consoleErrors: string[];
  api404: string[];
  apiOther4xx5xx: string[];
}

/** Attach listeners that record page errors, console errors, and any /api/backend 4xx/5xx. */
export function trackErrors(page: Page): ErrorSink {
  const sink: ErrorSink = { pageErrors: [], consoleErrors: [], api404: [], apiOther4xx5xx: [] };
  page.on("pageerror", (e) => sink.pageErrors.push(e.stack || e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !IGNORE_CONSOLE.test(m.text())) sink.consoleErrors.push(m.text());
  });
  page.on("response", (r) => {
    const u = r.url();
    if (!u.includes("/api/backend/")) return;
    const tag = `${r.request().method()} ${u.split("/api/backend")[1]}`;
    if (r.status() === 404) sink.api404.push(tag);
    else if (r.status() >= 400) sink.apiOther4xx5xx.push(`[${r.status()}] ${tag}`);
  });
  page.on("requestfailed", (r) => {
    const u = r.url();
    if (u.includes("/api/backend/") && !IGNORE_URL.test(u))
      sink.apiOther4xx5xx.push(`FAILED ${r.method()} ${u.split("/api/backend")[1]} :: ${r.failure()?.errorText}`);
  });
  return sink;
}

export const uniq = (a: string[]) => [...new Set(a)];

// ═══════════════════════════════════════════════════════════════════════════════
// 완료된 백테스트 런 픽스처
// ─────────────────────────────────────────────────────────────────────────────
// backtest.spec.ts 안에 있던 것을 여기로 옮겼다. results 라우트를 여는 스펙이 둘
// 이상이 되었기 때문이다.
//
// ★왜 임의의 runId 로는 안 되는가★
// /backtest/runs/<아무거나>/results 를 그냥 열면 백엔드는 **정직하게 404** 를 준다.
// 그건 결함이 아니라 설계다. 그러므로 이 픽스처 없이 라우트 건강도를 재면 테스트가
// 거짓으로 빨개진다 — 측정 대상은 "없는 런의 404" 가 아니라 "있는 런의 렌더" 다.
// ═══════════════════════════════════════════════════════════════════════════════
export const STUB_RUN_ID = "bt_stub_e2e_1";

/** 실제 스키마(ScreenToBacktestResult) 를 따르는 완료 런 — 작지만 형태는 정확하다. */
export function completedRun(runId: string = STUB_RUN_ID) {
  const base = {
    run_id: runId,
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
    correlation_id: runId,
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

/** 완료 런의 status·상세 두 엔드포인트를 스텁하고 페이로드를 돌려준다. */
export async function stubCompletedRun(page: Page, runId: string = STUB_RUN_ID) {
  const { lite, full } = completedRun(runId);
  await page.route("**/api/v1/backtest/runs/**/status", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(lite) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${runId}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(full) }));
  return { lite, full };
}
