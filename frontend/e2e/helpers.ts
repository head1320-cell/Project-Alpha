import type { Page } from "@playwright/test";

/**
 * 차트 애니메이션을 끈다 — 스크린샷·DOM 단정을 결정적으로 만들기 위해 (A12).
 *
 * ★`page.emulateMedia({reducedMotion:'reduce'})` 를 쓰지 않는 이유★ 그건 §62/§63 의
 * CSS 모션까지 전부 끈다. 그러면 A10·A11 이 세운 전이·엘리베이션·모션 가드가 측정할
 * 대상이 사라져 **전부 0 으로 통과**한다 — 가드가 아니라 통과 도장이 된다.
 * 이 헬퍼는 Recharts 만 겨냥한다.
 *
 * `addInitScript` 는 문서 생성 전에도 돌 수 있어 `documentElement` 접근이 불안정하므로
 * window 전역에 표시한다. 읽는 쪽은 `shared/ui/chartStyle.ts` 의 `useChartAnimation`.
 *
 * 반드시 `page.goto` **전에** 부를 것.
 */
export async function freezeCharts(page: Page): Promise<void> {
  await page.addInitScript(() => {
    (window as unknown as { __MOTION_OFF__?: boolean }).__MOTION_OFF__ = true;
  });
}

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

// ═══════════════════════════════════════════════════════════════════════════════
// WCAG 대비 감사 (S1b-2 에서 만들고 A2 에서 공용화)
// ─────────────────────────────────────────────────────────────────────────────
// ★이걸 공용으로 뺀 이유★ 이 세션에서 스스로 만든 결함 두 건을 잡은 것이 전부 이 감사다
// (`.dark` 의 --chart-* 가 죽어 있던 것, `.aas-wiz-lab` 이 1.04:1 이던 것). 둘 다 육안으로는
// "좀 흐리네"로 지나가고 기존 테스트는 전부 초록이었다. 새 표면마다 40줄을 복붙하면
// 구현이 갈라지므로 루트 선택자만 받는 팩토리로 만든다.
// 반환값은 **브라우저 안에서 도는 문자열**이라 바깥 스코프에 의존할 수 없다 — 선택자만 심는다.
// ═══════════════════════════════════════════════════════════════════════════════
export interface AuditResult { checked: number; bright: string[]; low: string[] }

export function contrastAudit(rootSelector: string): string {
  return `(() => {
  const lum = (r, g, b) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const parse = (s) => { const m = s.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/); return m ? { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] } : null; };
  // 반투명 배경은 뒤가 비치므로 불투명한 조상까지 올라가서 실제 배경을 찾는다.
  const effBg = (el) => {
    let n = el;
    while (n) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0.5) return c; n = n.parentElement; }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const ratio = (a, b) => { const l1 = lum(a.r, a.g, a.b), l2 = lum(b.r, b.g, b.b); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };
  const root = document.querySelector(${JSON.stringify(rootSelector)});
  if (!root) return { checked: 0, bright: ["NO " + ${JSON.stringify(rootSelector)}], low: [] };
  const bright = [], low = [];
  let checked = 0;
  for (const el of [root, ...root.querySelectorAll("*")]) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") continue;
    const own = parse(cs.backgroundColor);
    const tag = el.tagName + "." + (el.getAttribute("class") || "").split(" ").slice(0, 2).join(".");
    if (own && own.a > 0.5 && lum(own.r, own.g, own.b) > 0.6) bright.push(tag + " bg=" + cs.backgroundColor);
    // 자기 자신이 직접 들고 있는 텍스트만 — 부모까지 세면 같은 글자를 여러 번 센다.
    const hasOwnText = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!hasOwnText) continue;
    const fg = parse(cs.color);
    if (!fg) continue;
    checked++;
    const bg = effBg(el);
    const r = ratio(fg, bg);
    const px = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700;
    const need = px >= 24 || (px >= 18.66 && bold) ? 3 : 4.5;   // WCAG 큰 글씨 예외
    if (r < need) low.push(tag + " " + r.toFixed(2) + ":1 (need " + need + ") " + px + "px " + cs.color + " :: " + (el.textContent || "").trim().slice(0, 20));
  }
  return { checked, bright: [...new Set(bright)], low: [...new Set(low)] };
})()`;
}
