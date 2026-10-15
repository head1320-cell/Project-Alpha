import type { Page, Route } from "@playwright/test";

/**
 * BU9 · 관리 화면 셋(실거래·여러 전략 백테스트·현실성 점검) 스펙이 함께 쓰는 서버 응답.
 * ★모양은 서버 코드에서 베꼈다★ — `src/api/stage13_routes.py`(실거래) · `src/api/live_gate_routes.py`(관문) ·
 * `src/engine/multi_strategy_backtest.py`·`attribution_decomposer.py`·`counterfactual_analyzer.py`(여러 전략) ·
 * `src/engine/realism_engine.py`(현실성). 개발 서버에는 등록된 전략·실키가 없어서 이 스펙들이 응답을 정한다.
 * 숫자는 화면이 그리는 데 쓰는 결정적인 예시다(연습용) — 투자 결과가 아니다.
 */

// ── 세션 ───────────────────────────────────────────────────────────────────

export type Role = "admin" | "analyst";

/** 토큰 + `/auth/me`. `role: null` 이면 로그아웃(토큰 없음). */
export async function signIn(page: Page, role: Role | null, o: { mustChange?: boolean; username?: string } = {}) {
  if (role === null) return;
  await page.addInitScript(() => localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"));
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
    principal: { username: o.username ?? (role === "admin" ? "admin" : "minji"), role },
    must_change_password: !!o.mustChange, password_changed_at: "2026-10-01T00:00:00",
  } }));
}

export async function routeConnection(page: Page, mock: boolean | "fail" = true) {
  await page.route("**/api/v1/macro/connection-status", (r) => mock === "fail"
    ? r.fulfill({ status: 500, json: { detail: "연결 상태를 읽지 못했어요" } })
    : r.fulfill({ json: { mock_allowed: mock, real_mode: !mock, bok_configured: false, fred_configured: false } }));
}

// ── 실거래 (운영 계좌) ─────────────────────────────────────────────────────

export type LiveMode = "SHADOW" | "PAPER" | "LIVE";
export type LiveState = {
  mode: LiveMode;
  kill: { is_active: boolean; active_event: Record<string, unknown> | null };
  balance: Record<string, unknown> | null;
  orders: Record<string, unknown>[];
  /** 읽기 실패(상태 코드). */
  fail: Partial<Record<"mode" | "balance" | "orders" | "kill", number>>;
  /** 쓰기 응답을 정한다(없으면 상태 기계대로). */
  modeReply: { status: number; json: unknown } | null;
  triggerReply: { status: number; json: unknown } | null;
  resolveReply: { status: number; json: unknown } | null;
};

/** BV7 — 관문이 닫혀 있으면 서버가 이 사유로 400 을 준다(`order_executor.set_mode`). */
export const LIVE_REFUSED = "실계좌 관문이 닫혀 있어요. 빠진 항목: basis, authority, reference_no, verified_at, scope, allowed_users";

export const LIVE_BALANCE = {
  cash_krw: 99_786_983, evaluated_total: 100_046_983, stock_value: 473_000, n_positions: 2,
  positions: [
    { ticker: "005930", name: "삼성전자", quantity: 3, avg_price: 70_100, current_price: 71_000, eval_amount: 213_000, pnl_pct: 1.28, pnl_krw: 2_700 },
    { ticker: "000660", name: "SK하이닉스", quantity: 2, avg_price: 132_000, current_price: 130_000, eval_amount: 260_000, pnl_pct: -1.52, pnl_krw: -4_000 },
  ],
};

const liveOrder = (coid: string, status: string, extra: Record<string, unknown> = {}) => ({
  client_order_id: coid, ticker: "005930", side: "BUY", quantity: 10, filled_quantity: 0, price: 71_000, status,
  execution_mode: "SHADOW", strategy_id: 3, reason_code: null, created_at: "2026-10-09T12:01:00", ...extra,
});

export const LIVE_ORDERS = [
  liveOrder("CO-3", "SUBMITTED", { execution_mode: "PAPER", created_at: "2026-10-09T12:03:00" }),
  liveOrder("CO-2", "REJECTED", { ticker: "000660", side: "SELL", quantity: 5, price: 130_000, reason_code: "risk_check_failed", created_at: "2026-10-09T12:02:00" }),
  liveOrder("CO-1", "SHADOW_LOGGED"),
];

export function liveState(o: Partial<LiveState> = {}): LiveState {
  return {
    mode: "SHADOW", kill: { is_active: false, active_event: null }, balance: LIVE_BALANCE, orders: LIVE_ORDERS,
    fail: {}, modeReply: null, triggerReply: null, resolveReply: null, ...o,
  };
}

/** `/api/v1/live/*` 상태 기계 — 모드 POST 는 상태를 바꾸고(LIVE 는 400 사유), 걸기는 정지를 켜고, 풀기는 끈다. */
export async function routeLive(page: Page, st: LiveState) {
  const reply = (r: Route, x: { status: number; json: unknown }) => r.fulfill({ status: x.status, json: x.json });
  await page.route("**/api/v1/live/**", async (r) => {
    const req = r.request();
    const p = new URL(req.url()).pathname.replace(/^.*\/api\/v1\/live/, "");
    const m = req.method();
    if (p === "/mode" && m === "GET") {
      if (st.fail.mode) return r.fulfill({ status: st.fail.mode, json: { detail: "모드를 읽지 못했어요" } });
      return r.fulfill({ json: { mode: st.mode, started_at: "2026-10-09T08:00:00", last_mode_change: "2026-10-09T12:00:00",
        changed_by: "admin", enabled_strategies: [] } });
    }
    if (p === "/balance") {
      if (st.fail.balance) return r.fulfill({ status: st.fail.balance, json: { detail: "잔고를 읽지 못했어요" } });
      return r.fulfill({ json: st.balance });
    }
    if (p === "/orders" && m === "GET") {
      if (st.fail.orders) return r.fulfill({ status: st.fail.orders, json: { detail: "주문을 읽지 못했어요" } });
      return r.fulfill({ json: { count: st.orders.length, orders: st.orders } });
    }
    if (p === "/kill-switch/status") {
      if (st.fail.kill) return r.fulfill({ status: st.fail.kill, json: { detail: "정지 상태를 읽지 못했어요" } });
      return r.fulfill({ json: st.kill });
    }
    if (p === "/mode" && m === "POST") {
      if (st.modeReply) return reply(r, st.modeReply);
      const body = req.postDataJSON() as { mode: LiveMode };
      if (body.mode === "LIVE") return r.fulfill({ status: 400, json: { detail: LIVE_REFUSED } });
      const old = st.mode;
      st.mode = body.mode;
      return r.fulfill({ json: { old_mode: old, new_mode: body.mode, actor: "admin", actor_source: "token" } });
    }
    if (p === "/kill-switch/trigger") {
      if (st.triggerReply) return reply(r, st.triggerReply);
      st.kill = { is_active: true, active_event: { event_id: "K-9", trigger_reason: "Manual emergency stop from cockpit",
        triggered_at: "2026-10-09T12:05:00", trigger_source: "manual_admin", liquidation_mode: "hold" } };
      return r.fulfill({ json: { event_id: "K-9", n_orders_cancelled: 1, liquidation_mode: "hold", actor: "admin" } });
    }
    if (p === "/kill-switch/resolve") {
      if (st.resolveReply) return reply(r, st.resolveReply);
      const was = st.kill.is_active;
      st.kill = { is_active: false, active_event: null };
      return r.fulfill({ json: was ? { status: "resolved", resolved_by: "admin" } : { status: "no_active_event" } });
    }
    return r.fulfill({ status: 404, json: { detail: "이 스펙이 정하지 않은 경로" } });
  });
}

// ── 실계좌 관문 (BV7) ───────────────────────────────────────────────────────

export type GateRecord = {
  basis: string; authority: string; reference_no: string; verified_at: string; scope: string; allowed_users: string[];
  declared_by: string; declared_at: string; revoked_by: string | null; revoked_at: string | null;
};
export const GATE_OPEN: GateRecord = {
  basis: "본인 계좌로만 주문하는 개인 운영", authority: "한국투자증권 오픈API 약관", reference_no: "KIS-OPENAPI-2026-117",
  verified_at: "2026-10-09", scope: "운영 계좌 하나, 국내 주식", allowed_users: ["admin"],
  declared_by: "admin", declared_at: "2026-10-09T12:00:00+00:00", revoked_by: null, revoked_at: null,
};
export type GateState = { current: GateRecord | null; history: GateRecord[]; fail?: number; declareReply?: { status: number; json: unknown } };

export async function routeGate(page: Page, st: GateState) {
  await page.route("**/api/v1/admin/live-gate", async (r) => {
    const m = r.request().method();
    if (m === "GET") {
      if (st.fail) return r.fulfill({ status: st.fail, json: { detail: "관문 기록을 읽지 못했어요" } });
      return r.fulfill({ json: { current: st.current, history: st.history } });
    }
    if (m === "POST") {
      if (st.declareReply) return r.fulfill({ status: st.declareReply.status, json: st.declareReply.json });
      const body = r.request().postDataJSON() as Omit<GateRecord, "declared_by" | "declared_at" | "revoked_by" | "revoked_at">;
      const now = "2026-10-10T03:00:00+00:00";
      if (st.current) st.current = { ...st.current, revoked_by: "admin", revoked_at: now };
      const rec: GateRecord = { ...body, declared_by: "admin", declared_at: now, revoked_by: null, revoked_at: null };
      st.history = [rec, ...st.history.map((h) => (h.revoked_at ? h : { ...h, revoked_by: "admin", revoked_at: now }))];
      st.current = rec;
      return r.fulfill({ status: 201, json: { current: rec, live_dropped_to_shadow: false } });
    }
    if (m === "DELETE") {
      if (!st.current) return r.fulfill({ status: 404, json: { detail: "지금 열려 있는 실계좌 관문이 없어요." } });
      const now = "2026-10-10T03:05:00+00:00";
      st.history = st.history.map((h) => (h.revoked_at ? h : { ...h, revoked_by: "admin", revoked_at: now }));
      st.current = null;
      return r.fulfill({ json: { revoked: true, revoked_by: "admin", live_dropped_to_shadow: false } });
    }
    return r.fulfill({ status: 405, json: { detail: "x" } });
  });
}

// ── 전략 계산 응답 모양 (현실성 점검이 쓴다) ─────────────────────────────────

const QUADS = ["Goldilocks", "Goldilocks", "Reflation", "Reflation", null, "Stagflation", "Disinflation", "Goldilocks"];

export type DailyRec = Record<string, unknown> & {
  date: string; portfolio_equity: number; portfolio_return: number; cumulative_return: number; drawdown_pct: number;
  regime: string | null; rebalanced: boolean; weights: Record<string, number>;
};

/** 결정적인 일별 기록 — `_record_to_dict` 모양. 전략 둘(1·2), 21 거래일마다 리밸런싱. */
export function dailyRecords(days = 60, start = "2024-01-02", ids: number[] = [1, 2], capital = 10_000_000): DailyRec[] {
  const out: DailyRec[] = [];
  let eq = capital;
  let peak = eq;
  const d0 = new Date(`${start}T00:00:00Z`);
  for (let i = 0; i < days; i++) {
    const d = new Date(d0.getTime() + i * 86_400_000);
    const ret = Math.sin(i / 5) * 0.004 + 0.0006;
    eq = eq * (1 + ret);
    peak = Math.max(peak, eq);
    const w1 = 0.5 + Math.sin(i / 17) * 0.1;
    const weights = ids.length === 1 ? { [ids[0]]: 1 } : Object.fromEntries(ids.map((id, k) => [String(id), k === 0 ? +w1.toFixed(4) : +(1 - w1).toFixed(4)]));
    out.push({
      date: d.toISOString().slice(0, 10), portfolio_equity: +eq.toFixed(2), portfolio_return: ret,
      cumulative_return: +(((eq / capital) - 1) * 100).toFixed(4), drawdown_pct: +(((eq / peak) - 1) * 100).toFixed(4),
      regime: QUADS[Math.floor(i / 8) % QUADS.length], regimes: { kr: QUADS[Math.floor(i / 8) % QUADS.length], us: "Goldilocks" },
      systemic_risk: null, baseline_effect: ret * 0.9, allocation_effect: ret * 0.12, selection_effect: null, macro_effect: 0,
      netting_effect: null, cost_effect: -0.00002, cash_effect: null, num_trades: i % 21 === 0 ? 2 : 0, turnover_pct: i % 21 === 0 ? 8.5 : 0,
      netting_savings: i === 0 ? null : 1200, rebalanced: i % 21 === 0, weights,
      strategy_returns: Object.fromEntries(ids.map((id) => [String(id), ret])), weights_exact: weights,
      base_weights: weights, macro_adj: Object.fromEntries(ids.map((id) => [String(id), 0])),
    });
  }
  return out;
}

export const MB_STRATEGIES = [
  { id: 1, name: "가치 상위 20", source_run_id: "bt_a", is_active: true, is_mock_data: true, is_pit_verified: false,
    symbols: ["005930", "000660", "035420"], registered_at: 1_760_000_000, repro: { equal: true, compared_points: 487, first_mismatch: null } },
  { id: 2, name: "모멘텀 10", source_run_id: "bt_z", is_active: true, is_mock_data: true, is_pit_verified: null,
    symbols: ["005380", "051910"], registered_at: 1_760_000_100, repro: { equal: true, compared_points: 487, first_mismatch: null } },
];

const PERF = { kind: "backtest", data_source: "mock", label: "백테스트 · 연습용" };
const SOURCES = { available: true, reason: null, strategies: MB_STRATEGIES.map((s) => ({
  strategy_id: s.id, registered: true, name: s.name, source_run_id: s.source_run_id, is_active: true,
  is_mock_data: s.is_mock_data, is_pit_verified: s.is_pit_verified, repro_equal: true, repro_compared_points: 487 })) };

export function mbSummary(daily: DailyRec[]) {
  const last = daily[daily.length - 1];
  return {
    total_return_pct: +last.cumulative_return.toFixed(2), annualized_return_pct: 14.83, sharpe_ratio: 1.214, max_drawdown_pct: -4.37,
    calmar_ratio: 3.39, convention: { rf: 0, ddof: 1, periods: 252 }, sharpe_ratio_full: 1.21437, final_equity: last.portfolio_equity,
    total_trades: 12, total_turnover_pct: 25.5, n_rebalances: daily.filter((d) => d.rebalanced).length,
    n_trading_days: daily.length, netting_total_savings: 70_800,
    netting: { enabled: true, basis: "보유 상쇄", assumptions: ["같은 날 같은 종목 매수·매도 상쇄"], n_measured_days: daily.length - 1,
      n_unmeasured_days: 0, first_unmeasured_reason: null },
    regime_labels: { kr: { n_known_days: daily.length - 8, n_unknown_days: 8, first_unknown_reason: "그 시점에 공표된 빈티지가 없어요" },
      us: { n_known_days: daily.length, n_unknown_days: 0, first_unknown_reason: null } },
    regime_rebalance: null,
    attribution: { allocation_effect_pct: 0.42, macro_effect_pct: 0, netting_effect_pct: null, cost_effect_pct: -0.08, cash_effect_pct: null },
    regime_alpha: {},
  };
}

export function mbRunResult(run_id: number | null, config: Record<string, unknown>, daily = dailyRecords()) {
  return {
    success: true, config, summary: mbSummary(daily), daily_records: daily, strategy_names: { 1: "가치 상위 20", 2: "모멘텀 10" },
    n_trading_days: daily.length, duration_seconds: 1.42, warnings: [], ...(run_id === null ? {} : { run_id }),
    cost_model: { commission_rate: 0.00015, slippage_rate: 0.0005, basis: "명시" }, sources: SOURCES, perf_label: PERF,
  };
}

// ── 현실성 점검 ────────────────────────────────────────────────────────────

export const REALISM_STATS = {
  total_market_impact_cost: 18_420_000, total_cash_yield: 9_870_000, total_buying_power_truncations: 2, total_capacity_reallocations: 0,
  regime_mode_days: { normal: 40, cautious: 15, defensive: 5 }, ewma_active_days: 12, hard_cap_active_days: 0, breakdown_detected_days: 1,
  avg_market_impact_bps_per_rebalance: 6.14, cash_yield_annualized_pct: 0.412, mode_distribution_pct: { normal: 66.7, cautious: 25, defensive: 8.3 },
};

export type RealismState = {
  strategies: Record<string, unknown>[];
  fail: Partial<Record<"strategies" | "ideal" | "reality", number>>;
  idealReply: unknown | null;
  realityReply: unknown | null;
};
export function realismState(o: Partial<RealismState> = {}): RealismState {
  return { strategies: MB_STRATEGIES, fail: {}, idealReply: null, realityReply: null, ...o };
}

export async function routeRealism(page: Page, st: RealismState) {
  await page.route("**/api/v1/multibacktest/**", async (r) => {
    const req = r.request();
    const p = new URL(req.url()).pathname.replace(/^.*\/api\/v1\/multibacktest/, "");
    if (p === "/strategies" && req.method() === "GET") {
      if (st.fail.strategies) return r.fulfill({ status: st.fail.strategies, json: { detail: "전략 목록을 읽지 못했어요" } });
      return r.fulfill({ json: { count: st.strategies.length, strategies: st.strategies } });
    }
    if (p === "/run" && req.method() === "POST") {
      if (st.fail.ideal) return r.fulfill({ status: st.fail.ideal, json: { detail: "이상적 조건 계산이 실패했어요" } });
      if (st.idealReply) return r.fulfill({ json: st.idealReply });
      const { save: _s, ...config } = req.postDataJSON() as Record<string, unknown>;
      return r.fulfill({ json: mbRunResult(null, config, dailyRecords(60, "2023-01-02", [1, 2], 10_000_000_000)) });
    }
    return r.fulfill({ status: 404, json: { detail: "이 스펙이 정하지 않은 경로" } });
  });
  await page.route("**/api/v1/realism/**", async (r) => {
    const req = r.request();
    if (st.fail.reality) return r.fulfill({ status: st.fail.reality, json: { detail: "현실 조건 계산이 실패했어요" } });
    if (st.realityReply) return r.fulfill({ json: st.realityReply });
    const config = req.postDataJSON() as Record<string, unknown>;
    const daily = dailyRecords(60, "2023-01-02", [1, 2], 10_000_000_000).map((d) => ({ ...d,
      cumulative_return: d.cumulative_return * 0.86, portfolio_equity: d.portfolio_equity * 0.999 }));
    const summary = { ...mbSummary(daily), annualized_return_pct: 12.1, realism_adjustments: REALISM_STATS };
    return r.fulfill({ json: { success: true, config: { ...config, avg_adv_krw: 50_000_000_000, enable_capacity_constraint: false },
      summary, realism_stats: REALISM_STATS, daily_records: daily, strategy_names: { 1: "가치 상위 20", 2: "모멘텀 10" },
      n_trading_days: daily.length, duration_seconds: 2.4, cost_model: { basis: "명시" },
      regime_adaptive: { basis: "국면 판정", reason: null }, sources: SOURCES, perf_label: PERF } });
  });
}
