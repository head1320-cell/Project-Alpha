/**
 * 운영 계좌(서버 `.env` 계좌) 실거래 경로 — `/api/v1/live/*` (Stage13 · BV7 관문 뒤 LIVE).
 * ==========================================================================
 * 관리 화면 `/admin/live-trading`(BU9b)이 쓴다. ★요청(메서드·경로·본문)은 옛 화면과 바이트 그대로★ — BU9a 골든
 * (`e2e/golden/live-trading-requests.json`)이 건다. 고정 본문은 아래 상수에만 있고, 화면은 이것을 고치지 않는다.
 * 실패는 `Result` 로(서버 사유 그대로, 닿지 못하면 status 0) — 던지지 않는다.
 */
import { getWithAuth, postJson } from "@/shared/api/apiBase";
import { call, type Result } from "@/shared/api/result";

/** 실행 모드 — 서버 열거값 그대로. 모르는 값이 와도 문자열로 들고 다닌다(번역표에 없으면 원문). */
export type OpModeName = "SHADOW" | "PAPER" | "LIVE" | (string & {});

export type OpMode = {
  mode: OpModeName; started_at: string | null; last_mode_change: string | null; changed_by: string | null;
};
export type OpKillEvent = {
  event_id?: string; trigger_reason?: string | null; triggered_at?: string | null; trigger_source?: string | null;
  liquidation_mode?: string | null;
};
/** `is_active` 는 운영 계좌 정지만(`account_id IS NULL`) — ★조회가 실패해도 서버는 '켜짐'으로 본다★(보수 쪽). */
export type OpKill = { is_active: boolean; active_event: OpKillEvent | null };
export type OpPosition = {
  ticker: string; name?: string | null; quantity?: number | null; avg_price?: number | null; current_price?: number | null;
  eval_amount?: number | null; pnl_pct?: number | null; pnl_krw?: number | null;
};
/** 증권사 잔고 그대로(KIS `get_balance`). 빠진 칸은 몰라요 — 0 으로 메우지 않는다. */
export type OpBalance = {
  cash_krw?: number | null; evaluated_total?: number | null; stock_value?: number | null; n_positions?: number | null;
  positions?: OpPosition[] | null;
};
export type OpOrder = {
  client_order_id: string; ticker: string; side: string; quantity: number | null; filled_quantity?: number | null;
  price?: number | null; status: string; execution_mode?: string | null; strategy_id?: number | null;
  reason_code?: string | null; error_message?: string | null; created_at?: string | null;
};
export type OpOrders = { count: number; orders: OpOrder[] };

/** ★바이트 그대로★ — 실계좌 전환 확인 코드(서버 `set_mode`). 관문이 닫혀 있으면 서버가 사유와 함께 400. */
export const LIVE_CONFIRM_TOKEN = "EXPLICIT_LIVE_CONFIRMED";
/** ★바이트 그대로★ — 비상 정지 걸기 본문. 사유 칸은 없다(본문이 바뀐다 — 서버 기록에 이 글이 남는다). 청산은 그대로 두기만. */
export const KILL_BODY = { reason: "Manual emergency stop from cockpit", liquidation_mode: "hold" } as const;
/** ★바이트 그대로★ — 비상 정지 풀기 본문. */
export const RESOLVE_BODY = { notes: "Manual resolution from cockpit" } as const;
/** 최근 주문 몇 건 — 옛 화면과 같은 20. */
export const ORDER_LIMIT = 20;

export type OpSnapshot = {
  mode: Result<OpMode>; balance: Result<OpBalance>; orders: Result<OpOrders>; kill: Result<OpKill>;
};

/** 읽기 넷을 한꺼번에(옛 `Promise.all` 그대로) — 하나가 실패해도 나머지는 그린다. */
export async function readOperator(): Promise<OpSnapshot> {
  const [mode, balance, orders, kill] = await Promise.all([
    call<OpMode>(getWithAuth("/api/v1/live/mode")),
    call<OpBalance>(getWithAuth("/api/v1/live/balance")),
    call<OpOrders>(getWithAuth(`/api/v1/live/orders?limit=${ORDER_LIMIT}`)),
    call<OpKill>(getWithAuth("/api/v1/live/kill-switch/status")),
  ]);
  return { mode, balance, orders, kill };
}

export type ModeReply = { old_mode?: string; new_mode?: string; actor?: string };
export const setOperatorMode = (mode: "SHADOW" | "PAPER") =>
  call<ModeReply>(postJson("/api/v1/live/mode", { mode }));
export const setOperatorLive = () =>
  call<ModeReply>(postJson("/api/v1/live/mode", { mode: "LIVE", confirm_token: LIVE_CONFIRM_TOKEN }));

export type KillReply = { event_id?: string; n_orders_cancelled?: number | null; liquidation_mode?: string };
export const triggerOperatorKill = () => call<KillReply>(postJson("/api/v1/live/kill-switch/trigger", KILL_BODY));
export type ResolveReply = { status?: string; resolved_by?: string };
export const resolveOperatorKill = () => call<ResolveReply>(postJson("/api/v1/live/kill-switch/resolve", RESOLVE_BODY));
