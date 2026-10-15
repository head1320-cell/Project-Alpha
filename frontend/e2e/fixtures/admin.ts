import type { Page, Route } from "@playwright/test";
import REALISM from "./realism.json";

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
  fail: Partial<Record<"mode" | "balance" | "orders" | "kill" | SafetyKey, number>>;
  /** ST3b [안전] 탭 읽기 다섯(+요약) — 모양은 서버 `stage13_routes` 그대로(TestClient 로 찍어 베낌). */
  safety: Record<SafetyKey, unknown>;
  /** 쓰기 응답을 정한다(없으면 상태 기계대로). */
  modeReply: { status: number; json: unknown } | null;
  triggerReply: { status: number; json: unknown } | null;
  resolveReply: { status: number; json: unknown } | null;
};

export type SafetyKey = "events" | "readiness" | "kisCodes" | "audit" | "auditSummary" | "pnl";
const SAFETY_PATH: Record<string, SafetyKey> = {
  "/kill-switch/events": "events", "/kill-switch/readiness": "readiness", "/kill-switch/kis-codes": "kisCodes",
  "/audit": "audit", "/audit/summary": "auditSummary", "/daily-pnl": "pnl",
};
const KILL_REC = (state: string, action: string, label: string, reason: string | null = null) => ({ action, label, state, reason, detail: null });
export const SAFETY: Record<SafetyKey, unknown> = {
  events: { count: 2, events: [
    { event_id: "KILL-2", triggered_at: "2026-10-09T12:05:00", trigger_source: "manual_admin", trigger_reason: "Manual emergency stop from cockpit",
      liquidation_mode: "hold", n_orders_cancelled: 1, resolved_at: "2026-10-09T12:30:00", resolved_by: "admin", resolution_notes: "Manual resolution from cockpit",
      actions: { records: [KILL_REC("done", "block_new_orders", "신규 주문 차단"), KILL_REC("done", "cancel_open_orders", "미체결 주문 취소"),
        KILL_REC("skipped", "liquidate_positions", "보유 청산", "청산 모드가 `hold` 라 포지션을 ★팔지 않았습니다★"), KILL_REC("done", "notify", "통지")],
        summary: "건너뜀 보유 청산" } },
    { event_id: "KILL-1", triggered_at: "2026-10-01T09:00:00", trigger_source: "auto_dd", trigger_reason: "누적 drawdown 한도 초과 (10.4% >= 10%)",
      liquidation_mode: "hold", n_orders_cancelled: null, resolved_at: "2026-10-01T10:00:00", resolved_by: "admin", resolution_notes: "확인함",
      actions: { records: [KILL_REC("unknown", "block_new_orders", "신규 주문 차단", "이 발동은 조치 기록이 생기기 전에 저장됐습니다")] } },
  ] },
  readiness: { armed: [], inoperable: [
    { trigger: "auto_dd", reason: "누적 drawdown 미상 (no_equity_history)" }, { trigger: "auto_cb", reason: "일중 손실 미상 (no_equity_history)" },
    { trigger: "auto_risk", reason: "국면 systemic_risk_score 미상" }, { trigger: "auto_api", reason: "KIS API 실패 횟수 미상 (mock 클라이언트에는 실패 카운터가 없습니다)" }],
    summary: "자동 트리거 4개 중 0개 무장 · 4개 불능", is_active: false, account_state_reason: null,
    note: "불능 트리거는 임계값 문제가 아니라 재료가 없어서 발동하지 않습니다 — 임계를 낮춰도 달라지지 않습니다." },
  kisCodes: { observed: [], gaps: [], table: { size: 0, why_empty: "이 환경은 KIS 자격증명이 없어 공식 문서도 실계좌 응답도 얻을 수 없다." },
    gate: { state: "blocked", reason: "업무 응답을 breaker 카운트에서 빼는 변경은 막혀 있습니다." } },
  audit: { count: 2, events: [
    { audit_id: "A-2", event_type: "KILL_SWITCH_TRIGGERED", event_category: "safety", severity: "CRITICAL", actor: "admin", message: "Manual emergency stop from cockpit", timestamp: "2026-10-09T12:05:00" },
    { audit_id: "A-1", event_type: "SIGNAL_RECEIVED", event_category: "order", severity: "INFO", actor: "system", ticker: "005930", message: null, timestamp: "2026-10-09T12:01:00" }] },
  auditSummary: { date: "2026-10-09", total_events: 2, by_severity: { INFO: 1, WARN: 0, ERROR: 0, CRITICAL: 1 }, by_category: {}, by_event_type: {} },
  pnl: { count: 2, pnl_history: [
    { trade_date: "2026-10-09", execution_mode: "SHADOW", ending_equity_krw: 100_046_983, daily_return_pct: 0.12, n_orders: 3 },
    { trade_date: "2026-10-08", execution_mode: "PAPER", ending_equity_krw: 99_926_000, daily_return_pct: -0.4, n_orders: 1 }] },
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
    fail: {}, modeReply: null, triggerReply: null, resolveReply: null, safety: { ...SAFETY }, ...o,
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
    const sk = m === "GET" ? SAFETY_PATH[p] : undefined;
    if (sk) {
      if (st.fail[sk]) return r.fulfill({ status: st.fail[sk], json: { detail: `${sk} 를 읽지 못했어요` } });
      return r.fulfill({ json: st.safety[sk] });
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

// ── 등록 전략 (현실성 점검이 읽는다) ───────────────────────────────────────

export const MB_STRATEGIES = [
  { id: 1, name: "가치 상위 20", source_run_id: "bt_a", is_active: true, is_mock_data: true, is_pit_verified: false,
    symbols: ["005930", "000660", "035420"], registered_at: 1_760_000_000, repro: { equal: true, compared_points: 487, first_mismatch: null } },
  { id: 2, name: "모멘텀 10", source_run_id: "bt_z", is_active: true, is_mock_data: true, is_pit_verified: null,
    symbols: ["005380", "051910"], registered_at: 1_760_000_100, repro: { equal: true, compared_points: 487, first_mismatch: null } },
];


// ── 현실성 점검 ────────────────────────────────────────────────────────────



export type RealismState = {
  strategies: Record<string, unknown>[];
  fail: Partial<Record<"strategies" | "ideal" | "reality", number>>;
  idealReply: unknown | null;
  realityReply: unknown | null;
};
export function realismState(o: Partial<RealismState> = {}): RealismState {
  return { strategies: MB_STRATEGIES, fail: {}, idealReply: null, realityReply: null, ...o };
}

/**
 * 현실성 점검(ST3c) — 등록 전략 목록 + `/realism/backtest` 둘(이상 = 현실 조건 전부 끔 · 현실 = 넷 켬).
 * 계산 응답은 실제 서버를 찍은 `fixtures/realism.json`(결정적 합성 전략 둘). `/multibacktest/run` 은 지웠다 — 부르면 404.
 */
export async function routeRealism(page: Page, st: RealismState) {
  await page.route("**/api/v1/multibacktest/**", async (r) => {
    const req = r.request();
    const p = new URL(req.url()).pathname.replace(/^.*\/api\/v1\/multibacktest/, "");
    if (p === "/strategies" && req.method() === "GET") {
      if (st.fail.strategies) return r.fulfill({ status: st.fail.strategies, json: { detail: "전략 목록을 읽지 못했어요" } });
      return r.fulfill({ json: { count: st.strategies.length, strategies: st.strategies } });
    }
    return r.fulfill({ status: 404, json: { detail: "Not Found" } });
  });
  await page.route("**/api/v1/realism/**", async (r) => {
    const body = r.request().postDataJSON() as Record<string, unknown>;
    const ideal = body.enable_market_impact === false;
    const side = ideal ? "ideal" : "reality";
    if (st.fail[side]) return r.fulfill({ status: st.fail[side], json: { detail: ideal ? "이상 쪽 계산이 실패했어요" : "현실 조건 계산이 실패했어요" } });
    const reply = ideal ? st.idealReply : st.realityReply;
    if (reply) return r.fulfill({ json: reply });
    return r.fulfill({ json: { ...(ideal ? REALISM.ideal : REALISM.real), config: body } });
  });
}
