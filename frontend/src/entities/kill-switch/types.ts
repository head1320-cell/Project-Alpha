/**
 * Kill Switch — 발동 기록 응답 타입 (AP5)
 * ==========================================================================
 * `GET /api/v1/live/kill-switch/status` · `/kill-switch/events`
 * (`src/api/stage13_routes.py` · 어휘 `src/domain/kill_action.py`)
 *
 * ★이번에 화면은 만들지 않는다★ — AO5 와 같은 선택이다. 타입만 먼저 두고,
 * 안 만든 것을 안 만들었다고 적는다.
 *
 * ★두 축을 섞지 않는다★ — **발동했는가**(이벤트)와 **무엇을 했는가**(조치)는
 * 다른 사실이다. 화면이 `is_active` 만 보고 "정리됐다" 로 그리면, 그것이 바로
 * 이 타입이 막으려는 오독이다.
 */

/** 조치 넷. 서버의 `KILL_ACTIONS` 와 **같은 어휘**. */
export type KillAction =
  | "block_new_orders"
  | "cancel_open_orders"
  | "liquidate_positions"
  | "notify";

/**
 * 조치 상태 넷.
 * ★`skipped` 는 `done` 에 건수 0 인 것과 **다른 사실**★ — 전자는 시도하지
 * 않았다는 뜻이고, 후자는 할 일이 없었다는 뜻이다.
 */
export type ActionState = "done" | "skipped" | "failed" | "unknown";

/** 관측 축의 상태. ★잰 `0` 은 `observed` 다★ — 문제는 **안 실은** `0` 이다. */
export type ObservationState = "observed" | "unknown";

export interface ActionRecord {
  action: KillAction;
  label: string;
  state: ActionState;
  /** ★`done` 이외 상태에는 반드시 사유가 있다★ (서버가 생성 단계에서 강제). */
  reason: string | null;
  detail: Record<string, unknown> | null;
}

export interface ActionRollup {
  done: KillAction[];
  skipped: KillAction[];
  failed: KillAction[];
  unknown: KillAction[];
  records: ActionRecord[];
  /** ★넷이 전부 `done` 일 때만 참★ — 그래도 "포지션이 정리됐다" 는 뜻이 아니다. */
  cleared: boolean;
  summary: string;
  /** 화면이 지우면 안 되는 경고문. */
  note: string;
}

export interface Observation<T> {
  value: T | null;
  state: ObservationState;
}

export interface TriggerObservations {
  equity_krw: Observation<number>;
  dd_pct: Observation<number>;
  regime: Observation<string>;
  any_unobserved: boolean;
}

/**
 * 저장된 발동 행.
 * ★숫자는 전부 `| null`★ — 안 실었으면 `0` 이 아니라 NULL 이다. 화면이 `?? 0`
 * 으로 채우면 미상이 관측으로 둔갑한다(`CLAUDE.md` §4).
 */
export interface KillEvent {
  event_id: string;
  triggered_at: string | null;
  trigger_source: string;
  trigger_reason: string;
  equity_at_trigger: number | null;
  /** ★발동을 일으킨 드로다운★ — 원인이 아닌 트리거에서는 `null` 이다. */
  dd_at_trigger: number | null;
  regime_at_trigger: string | null;
  liquidation_mode: string | null;
  /** 시도하지 않았으면 `null`(0 이 아니다). */
  n_orders_cancelled: number | null;
  n_positions_closed: number | null;
  krw_recovered: number | null;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_notes: string | null;
  /** ★조치 기록이 없는 과거 행은 넷이 `unknown` + 사유★ — 소급하지 않는다. */
  actions: ActionRollup;
}

/**
 * KIS 연속 실패 관측 (AQ) — `GET /kill-switch/readiness` 의 `api_failure_observation`.
 *
 * ★`count` 가 `null` 이면 "0 회 실패" 가 아니라 "재지 못했다" 다★ — 화면이
 * `?? 0` 으로 채우면 `auto_api` 가 무장된 것처럼 보인다.
 */
export type ApiFailureSource = "broker" | "mock" | "no_client" | "unknown";
export type BreakerState = "closed" | "open" | "half_open" | "unknown";

export interface ApiFailureObservation {
  /** 연속 실패 횟수. ★broker 출처에서 읽었을 때만 숫자★ */
  count: number | null;
  state: ObservationState;
  source: ApiFailureSource;
  breaker_state: BreakerState;
  /** ★차단 중 ≠ 실패 중★ — `open` 이면 호출 자체가 막혀 있다. */
  blocking: boolean | null;
  /** ★방금 열렸다 풀린 직후의 `0` 을 '건강' 으로 읽지 않게★ */
  recently_tripped: boolean | null;
  reason: string | null;
  /** 화면이 지우면 안 되는 경고문(0 이 정상을 뜻하지 않는다). */
  note: string;
}

/** `GET /kill-switch/readiness` (AF4 + AQ) */
export interface KillSwitchReadiness {
  armed: { trigger: string; basis: string }[];
  inoperable: { trigger: string; reason: string }[];
  summary: string;
  is_active: boolean;
  api_failure_observation: ApiFailureObservation | null;
  account_state_reason: string | null;
  note: string;
}

/** `GET /kill-switch/status` — ★최상위 키 둘은 골든이다★ (AF4 가 못 박았다). */
export interface KillSwitchStatus {
  is_active: boolean;
  active_event: KillEvent | null;
}

/** `GET /kill-switch/events` */
export interface KillEventsResponse {
  count: number;
  events: KillEvent[];
}

/** `POST /kill-switch/trigger` 응답 — 발동 결과 + 조치 + 관측. */
export interface KillTriggerResult {
  event_id: string;
  triggered_at: string;
  trigger_source: string;
  trigger_reason: string;
  equity_at_trigger: number | null;
  dd_at_trigger: number | null;
  liquidation_mode: string;
  n_orders_cancelled: number | null;
  n_positions_closed: number | null;
  krw_recovered: number | null;
  liquidation: {
    mode: string;
    closed: number | null;
    partial: unknown[];
    failed: unknown[];
    krw_recovered: number | null;
    complete: boolean | null;
    note: string | null;
  };
  /** ★시도하지 않았으면 `false` 가 아니라 `null`★ (미상 ≠ 거짓). */
  liquidation_complete: boolean | null;
  liquidation_note: string | null;
  actions: ActionRollup;
  observations: TriggerObservations;
}
