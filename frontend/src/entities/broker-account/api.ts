/**
 * 내 증권 계좌 라우트 — `/api/v1/broker-accounts*` (서버 BV3·BV4·BV6·BV7·BV9a).
 * ==========================================================================
 * 설정 화면(계좌 연결·목록·확인·지우기 — BV8)과 "내 계좌" 화면(주문·모드·비상 정지·준비 목록·잔고 — BV9)이 함께 쓴다.
 * ★서버가 가린 값만 돌아온다★(앱 키·시크릿·전체 계좌번호 0). 남의 계좌는 서버가 404 — 화면이 거르지 않는다.
 * 실패는 `Result` 로 — 서버 사유 그대로, 닿지 못하면 status 0.
 */
import { getWithAuth, postJson } from "@/shared/api/apiBase";
import { call } from "@/shared/api/result";

export type BrokerAccount = {
  account_id: string; label: string; is_paper: boolean; account_prdt: string;
  app_key_last4: string; account_no_masked: string; created_at: string | null;
};

export type BrokerCheck = {
  account_id: string; state: "practice" | "ok" | "failed"; reason: string; detail?: string; checked_at: string;
};

export type BrokerConnect = {
  label: string; app_key: string; app_secret: string; account_no: string; is_paper: boolean; account_prdt: string;
};

/** 실행 모드 — 서버 열거값 그대로. 모르는 값이 와도 문자열로 들고 다닌다(번역표에 없으면 원문). */
export type ExecMode = "SHADOW" | "PAPER" | "LIVE" | (string & {});

export type AccountMode = { mode: ExecMode; changed_by: string | null; last_mode_change: string | null };

/** `active` 는 운영자 전역 정지도 센다(서버는 조회 실패도 '켜짐'으로 본다). `event` 는 이 계좌가 직접 건 정지만. */
export type KillEvent = {
  event_id: string; trigger_reason?: string | null; triggered_at?: string | null; trigger_source?: string | null;
};
export type AccountKill = { active: boolean; event: KillEvent | null };

export type ReadinessItem = { key: string; ok: boolean; reason: string };
export type Readiness = { account_id: string; ready: boolean; items: ReadinessItem[] };

export type Position = {
  ticker: string; quantity: number | null; avg_price: number | null; current_price: number | null;
  eval_amount: number | null; pnl_pct: number | null;
};
/** `practice` 는 서버 mock 게이트 — 이 숫자가 연습용 클라이언트에서 왔는지. 실패면 숫자 칸이 없다. */
export type Balance = { account_id: string; practice: boolean; as_of: string } & (
  | { state: "ok"; cash_krw: number | null; evaluated_total: number | null; positions: Position[] }
  | { state: "failed"; reason: string; detail?: string }
);

/** 서버 `live_orders` 행 그대로(쓰는 칸만 적었다). */
export type OrderRow = {
  client_order_id: string; ticker: string; side: string; quantity: number | null; price: number | null;
  status: string; execution_mode: string | null; reason_code: string | null; error_message: string | null;
  created_at: string | null;
};

/** `POST /{id}/orders` 본문 — 서버 `SignalRequest` 그대로. 직접 낸 주문은 전략이 없어 `strategy_id` 0(전략 표 id 는 1부터). */
export type OrderRequest = {
  strategy_id: 0; ticker: string; side: "BUY" | "SELL"; quantity: number; price: number;
  order_type: "LIMIT" | "MARKET"; source: "manual";
};
/** 실행기 응답 — 상태 + (거절이면) 사유 코드·문장 / (실패면) error / (보냈으면) 증권사 주문번호. */
export type OrderReply = {
  client_order_id: string; status: string; mode?: string; reason?: string; message?: string; error?: string;
  kis_order_id?: string | null;
};

export type CancelReply = { status: "cancelled" | "not_cancellable" | "cancel_failed" | (string & {}); current?: string; error?: string };
export type KillReply = { event_id: string; n_orders_cancelled: number | null };
export type ResolveReply = { status: "resolved" | "no_active_event" | "db_error" | (string & {}) };

const BROKER = "/api/v1/broker-accounts";
const at = (id: string, tail = "") => `${BROKER}/${encodeURIComponent(id)}${tail}`;

// ── 연결 (BV8 설정 화면) ─────────────────────────────────────────────────────
export const listBrokerAccounts = () => call<{ accounts: BrokerAccount[] }>(getWithAuth(BROKER));
export const connectBrokerAccount = (body: BrokerConnect) => call<BrokerAccount>(postJson(BROKER, body));
export const checkBrokerAccount = (id: string) => call<BrokerCheck>(postJson(at(id, "/check"), {}));
export const deleteBrokerAccount = (id: string) =>
  call<{ deleted: string }>(getWithAuth(at(id), { method: "DELETE" }));

// ── 내 계좌 (BV9 화면) ───────────────────────────────────────────────────────
export const getAccountMode = (id: string) => call<AccountMode>(getWithAuth(at(id, "/mode")));
export const setAccountMode = (id: string, mode: "SHADOW" | "PAPER") =>
  call<{ new_mode: string }>(postJson(at(id, "/mode"), { mode }));
export const getAccountKill = (id: string) => call<AccountKill>(getWithAuth(at(id, "/kill-switch")));
/** ★청산은 '그대로 두기'(hold)만★ — 사용자 결정(BV9). 분할 매도는 1/5 만 파는 간이 구현이라 화면에서 내지 않는다. */
export const triggerAccountKill = (id: string, reason: string) =>
  call<KillReply>(postJson(at(id, "/kill-switch/trigger"), { reason, liquidation_mode: "hold" }));
export const resolveAccountKill = (id: string, notes: string) =>
  call<ResolveReply>(postJson(at(id, "/kill-switch/resolve"), { notes }));
export const getReadiness = (id: string) => call<Readiness>(getWithAuth(at(id, "/live-readiness")));
export const getBalance = (id: string) => call<Balance>(getWithAuth(at(id, "/balance")));
export const listAccountOrders = (id: string, limit = 50) =>
  call<{ count: number; orders: OrderRow[] }>(getWithAuth(at(id, `/orders?limit=${limit}`)));
export const submitAccountOrder = (id: string, body: OrderRequest) => call<OrderReply>(postJson(at(id, "/orders"), body));
export const cancelAccountOrder = (id: string, coid: string) =>
  call<CancelReply>(getWithAuth(at(id, `/orders/${encodeURIComponent(coid)}`), { method: "DELETE" }));
