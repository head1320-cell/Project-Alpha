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

/**
 * KIS 호출 실패의 종류 (AR) — `src/domain/kis_failure.py` 와 같은 어휘.
 *
 * ★`fault` 가 `"unknown"` 인 것은 실수가 아니다★ — `business`(rt_cd ≠ 0)는
 * 주문 거절 같은 정상 업무 응답일 수도, KIS 장애일 수도 있는데 이 저장소에는
 * `rt_cd` 를 뜻으로 옮기는 표가 없다. 화면이 "장애" 로 단정하면 안 된다.
 */
export type KisFailureKind =
  | "blocked"
  | "transport"
  | "http_status"
  | "malformed"
  | "business"
  | "token"
  | "unknown";

export type KisFault = "provider" | "self" | "unknown";

export interface KisFailureLabel {
  kind: KisFailureKind;
  label: string;
  fault: KisFault;
  /** 책임 소재를 단정하지 않은 이유. 단정할 수 있으면 `null`. */
  fault_reason: string | null;
  /** ★지금 circuit breaker 가 이 종류를 세는가★ — 기술이지 정책이 아니다. */
  counted_by_breaker: boolean;
  rt_cd: string | null;
  /**
   * ★표의 열쇠★ — `rt_cd` 는 `!== "0"` 이분법으로 쓰이는 거친 값이라 혼자서는
   * 뜻을 가리지 못한다. `null` 은 **미상**이지 "KIS 가 주지 않는다" 가 아니다.
   */
  msg_cd: string | null;
  status: number | null;
  kis_msg: string | null;
  note: string;
  /**
   * ★표가 무엇을 말하는가★ — 비어 있으면 `meaning` 이 `null` 이고 `reason` 이
   * 왜 미상인지 적는다. 이 저장소는 KIS 에 닿지 못해 표가 비어 있다.
   */
  table?: KisFailureTable;
}

/** `rt_cd`/`msg_cd` 표가 이 코드에 대해 말하는 것. ★관측은 뜻이 아니다.★ */
export interface KisFailureTable {
  meaning: string | null;
  fault: KisFault | null;
  grade: string | null;
  evidence_source: string | null;
  /** 왜 미상인지. 표가 말해 주면 `null`. */
  reason: string | null;
  key: string | null;
  note: string;
}

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
  /**
   * ★그 숫자가 무엇이었나★(AT) — `broker` 출처가 아니면 `null` 이다(합성을
   * 관측으로 팔지 않는다). `describes_count` 가 `true` 가 아니면 이 구성은
   * 그 횟수를 설명하지 않는다 — 비율로 읽으면 안 된다.
   */
  streak: FailureStreak | null;
  reason: string | null;
  /** 화면이 지우면 안 되는 경고문(0 이 정상을 뜻하지 않는다). */
  note: string;
  /** ★마지막 실패의 종류★ (AR). 아직 실패가 없으면 `null` — 0 이 아니다. */
  last_failure: KisFailureLabel | null;
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

/**
 * ★우리가 본 KIS 업무 코드★ — `GET /api/v1/live/kill-switch/kis-codes` (AS4)
 *
 * `(rt_cd, msg_cd, 실행 모드)` 별 관측 하나. ★모드가 열쇠에 들어 있다★ —
 * 모의와 실계좌 관측을 합치면 그 수치는 아무것도 뜻하지 않는다.
 */
export interface KisCodeObservation {
  rt_cd: string | null;
  /** `null` 은 미상 — KIS 가 주지 않는다는 뜻이 아니다. */
  msg_cd: string | null;
  execution_mode: string;
  count: number;
  first_seen: string | null;
  last_seen: string | null;
  /** ★해석하지 않은 원문★ — 문구로 뜻을 단정하지 않는다. */
  sample_msg1: string | null;
  key: string;
}

/** 본 적은 있으나 뜻을 모르는 코드. 많이 본 것이 먼저 온다. */
export interface KisCodeGap extends KisCodeObservation {
  /** 왜 미상인지. ★사유 없는 미상은 없다.★ */
  reason: string | null;
}

/** 표의 현재 상태. ★관측만 있는 항목은 표의 크기가 아니다.★ */
export interface KisCodeTable {
  size: number;
  observed_only: number;
  min_grade: string;
  grades: string[];
  /** 표가 비어 있다면 왜 비었는지. 비어 있는 것이 정직한 상태다. */
  why_empty: string | null;
  path: string;
  note: string;
}

export interface KisCodesResponse {
  observed: KisCodeObservation[];
  /** ★표가 비어 있으면 이것이 곧 `observed` 다★ — 그것이 지금의 진실이다. */
  gaps: KisCodeGap[];
  table: KisCodeTable;
  /** 이 코드들을 breaker 카운트에서 뺄 수 있는가. 오늘은 전부 막혀 있다. */
  gate: BreakerChangeGate;
  note: string;
}

/** 조건 하나의 충족 여부. 미충족이면 `reason` 이 무엇을 해야 하는지 말한다. */
export interface GateCondition {
  met: boolean;
  reason: string | null;
}

/** 코드 하나에 대한 판정. */
export interface GateVerdict {
  state: "allowed" | "blocked";
  reason: string | null;
  /** 못 채운 조건 이름들. */
  unmet: string[];
  conditions: Record<string, GateCondition>;
  key: string;
  note: string;
}

/**
 * ★일부만 통과한 것은 통과가 아니다★ — 코드 하나라도 막혀 있으면 전체는
 * `blocked` 다. 빈 목록도 `blocked` 이다(공허한 전칭을 주장하지 않는다).
 */
export interface BreakerChangeGate {
  state: "allowed" | "blocked";
  reason: string | null;
  n_allowed: number;
  n_blocked: number;
  allowed_codes: GateVerdict[];
  blocked_codes: GateVerdict[];
  conditions: string[];
  min_observations: number;
  note: string;
}

/** 연속 실패의 구성. ★무엇이 몇 번이지 누구 탓이 아니다.★ */
export interface FailureStreak {
  n_recorded: number;
  count: number | null;
  by_kind: Record<string, number>;
  labels: Record<string, string>;
  dominant: KisFailureKind | null;
  business_n: number;
  /** ★빈 연속에서는 `false`★ — 0회 중 0회를 전칭으로 읽지 않는다. */
  all_business: boolean;
  /** 지금 breaker 가 세는 종류의 개수. 기술이지 정책이 아니다. */
  counted_n: number;
  /** `null` 은 센 횟수를 모른다는 뜻 — 일치가 아니다. */
  describes_count: boolean | null;
  reason: string | null;
  note: string;
}
