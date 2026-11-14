/**
 * 운영 계좌 안전 기록 읽기 — `/api/v1/live/*` (ST3b · 실거래 [안전] 탭).
 * ==========================================================================
 * 옛 화면이 부르지 않던 읽기 다섯(비상 정지 이력 · 자동 정지 준비 상태 · KIS 응답 코드 표 · 감사 기록과 오늘 요약 · 일 손익).
 * 모두 로그인만 요구하는 GET 이고, ★[안전] 탭을 열 때만★ 부른다(지금 탭의 요청·폴링은 BU9a 골든 그대로).
 * 응답 모양은 서버(`src/api/stage13_routes.py`) 그대로 — 빠진 칸은 몰라요, 0 으로 메우지 않는다.
 */
import { getWithAuth } from "@/shared/api/apiBase";
import { call } from "@/shared/api/result";

/** 발동 하나가 한 조치 — 서버 `action_rollup` 의 records 한 줄. */
export type KillAction = { action: string; label?: string | null; state: string; reason?: string | null };
export type KillEvent = {
  event_id: string; triggered_at?: string | null; trigger_source?: string | null; trigger_reason?: string | null;
  liquidation_mode?: string | null; n_orders_cancelled?: number | null;
  resolved_at?: string | null; resolved_by?: string | null; resolution_notes?: string | null;
  actions?: { records?: KillAction[] | null; summary?: string | null; note?: string | null } | null;
};
export type KillEvents = { count: number; events: KillEvent[] };

export type Readiness = {
  armed: { trigger: string; reason?: string | null }[];
  inoperable: { trigger: string; reason?: string | null }[];
  summary?: string | null; note?: string | null; account_state_reason?: string | null;
};

export type KisCodes = {
  observed: unknown[]; gaps: unknown[];
  table: { size: number; why_empty?: string | null; note?: string | null };
  gate?: { state: string; reason?: string | null } | null;
};

export type AuditEvent = {
  audit_id: string; event_type: string; event_category?: string | null; severity?: string | null;
  actor?: string | null; message?: string | null; ticker?: string | null; client_order_id?: string | null;
  timestamp?: string | null;
};
export type AuditList = { count: number; events: AuditEvent[] };
/** 오늘 요약. ★서버는 읽지 못하면 200 + `error` 로 답한다★ — 화면이 그것을 실패로 그린다. */
export type AuditSummary = {
  date: string; total_events?: number; by_severity?: Record<string, number>; error?: string;
};

export type PnlRow = {
  trade_date: string; execution_mode?: string | null; equity_source?: string | null;
  ending_equity_krw?: number | null; daily_return_pct?: number | null; n_orders?: number | null;
};
export type PnlHistory = { count: number; pnl_history: PnlRow[] };

/** 감사 기록 몇 건 — 최근 주문과 같은 20. */
export const AUDIT_LIMIT = 20;

export const readKillEvents = () => call<KillEvents>(getWithAuth("/api/v1/live/kill-switch/events?limit=20"));
export const readReadiness = () => call<Readiness>(getWithAuth("/api/v1/live/kill-switch/readiness"));
export const readKisCodes = () => call<KisCodes>(getWithAuth("/api/v1/live/kill-switch/kis-codes"));
export const readAudit = () => call<AuditList>(getWithAuth(`/api/v1/live/audit?limit=${AUDIT_LIMIT}`));
export const readAuditSummary = () => call<AuditSummary>(getWithAuth("/api/v1/live/audit/summary"));
export const readDailyPnl = () => call<PnlHistory>(getWithAuth("/api/v1/live/daily-pnl?limit=30"));
