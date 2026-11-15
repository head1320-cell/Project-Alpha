/**
 * 규칙 가동의 문 (W5b) — 내 계좌의 `rule-runs` 다섯 + 분봉의 `arm-requests` 둘.
 * ==========================================================================
 * ★요청은 가동이 아니다★: 요청은 캔버스가 남긴 한 줄이고, 가동 · 정지는 이 문들이 한다(전부 로그인 · 본인 계좌만).
 * 가동은 실행 모드 ‘기록만’에서만 열린다 — 증권사로는 아무것도 나가지 않고, 체결은 시뮬레이터가 계산한 ★가상★ 체결이다.
 * 설정은 본문으로 보내지 않는다: 시행 열쇠와 날짜뿐이다(가동되는 것은 분봉 백테스트로 실행해 시행으로 세어진 설정뿐).
 * 못 읽음은 빈 목록이 아니다 — `available: false` + 사유. 실패는 `Result` 로(서버 사유 그대로).
 */
import { getWithAuth, postJson } from "@/shared/api/apiBase";
import { call } from "@/shared/api/result";

export type GateCounts = { ok: number; degraded: number; unknown: number };

/** 요청이 가리키는 시행 — 있음(무엇을 가동하게 되는지) / 없음 / 못 읽음(`found: null`). 뒤의 둘은 사유를 싣는다. */
export type ArmTrial =
  | { found: true; rule_kind: string | null; rule_label: string | null; tickers: string[]; from: string; to: string;
      grade: string | null; synthetic: boolean; runs: number }
  | { found: false | null; reason: string };

export type ArmRequest = {
  id: number; trial_key: string; note: string | null; created_at: number | null;
  trial: ArmTrial;
  /** 남긴 판정의 관문 수. ★보여 주기만 한다★ — 미달 · 미상이 있어도 가동은 열린다. 모르면 사유. */
  gates: { known: boolean; counts: GateCounts | null; reason: string | null };
};
export type ArmRequestList = { available: boolean; reason: string | null; requests: ArmRequest[]; gate: { mock: boolean } };

/** 도는 가동에만 있다 — 봉 몇 개 가운데 몇 개를 돌았고 다음 봉이 언제인지(`HHMMSS`). */
export type RunClock = { total: number; done: number; next: string | null };

/** 가상 체결 한 줄 + 그 신호가 주문 경로에서 받은 답(기록만 · 거절 …). `kind` 는 늘 `virtual` 이다. */
export type RunFill = {
  seq: number; executed_at: string; symbol: string; side: string; quantity: number; price: number; kind: string; event: string;
  client_order_id: string | null; order_status: string | null; order_reason: string | null;
};

export type RuleRun = {
  run_id: number; account_id: string; trial_key: string; tickers: string[]; day: string; feed: string; mode: string; grade: string;
  request: { rule?: { kind?: string } } | null;
  /** `running` · `finished` · `stopped` · `interrupted` — 모르는 값이 와도 문자열로 들고 다닌다. */
  status: string; stop_reason: string | null; stop_message: string | null;
  last_bar: string | null; bars: number; signals: number; started_at: number | null; ended_at: number | null;
  active: boolean; clock: RunClock | null;
  new_fills?: RunFill[]; fills?: RunFill[];
};

/** 가동을 보는 화면이 함께 읽는 것 — 지금 모드 · 비상 정지 · 상한 · 합성 데이터 모드인지. */
export type RunContext = {
  mode: string; kill_switch: boolean; gate: { mock: boolean };
  limits: { runs: number; tickers: number; gap_minutes: number };
};
export type RunList = RunContext & { available: boolean; reason: string | null; runs: RuleRun[] };
export type RunReply = RunContext & { run: RuleRun };

const BROKER = "/api/v1/broker-accounts";
const REQUESTS = "/api/v1/intraday/arm-requests";
const runs = (id: string, tail = "") => `${BROKER}/${encodeURIComponent(id)}/rule-runs${tail}`;

export const listArmRequests = () => call<ArmRequestList>(getWithAuth(REQUESTS));
export const removeArmRequest = (requestId: number) =>
  call<{ removed: boolean; id: number }>(getWithAuth(`${REQUESTS}/${requestId}`, { method: "DELETE" }));

export const listRuleRuns = (accountId: string) => call<RunList>(getWithAuth(runs(accountId)));
export const getRuleRun = (accountId: string, runId: number) => call<RunReply>(getWithAuth(runs(accountId, `/${runId}`)));
/** 본문은 시행 열쇠와 날짜뿐 — 서버는 남는 칸을 422 로 거절한다(설정을 끼워 넣을 칸이 없다). */
export const startRuleRun = (accountId: string, body: { trial_key: string; day: string }) =>
  call<RunReply>(postJson(runs(accountId), body));
/** `bars` 를 주지 않으면 하루의 끝까지 민다. */
export const advanceRuleRun = (accountId: string, runId: number, bars?: number) =>
  call<RunReply>(postJson(runs(accountId, `/${runId}/advance`), bars === undefined ? {} : { bars }));
export const stopRuleRun = (accountId: string, runId: number) => call<RunReply>(postJson(runs(accountId, `/${runId}/stop`), {}));

// ── 화면이 쓰는 말 ───────────────────────────────────────────────────────────

/** 가동 상태 → 화면의 말. 모르는 상태는 원문 그대로(화면이 `data-server` 로 그린다). */
export const RUN_STATUS_KO: Record<string, string> = {
  running: "가동 중", finished: "하루 끝까지 완료", stopped: "정지", interrupted: "중단",
};

/** `HHMMSS` → `HH:MM`. 모양이 다르면 null(시각을 지어내지 않는다). */
export function barTime(label: string | null | undefined): string | null {
  const m = label?.match(/^(\d{2})(\d{2})\d{2}$/);
  return m ? `${m[1]}:${m[2]}` : null;
}
