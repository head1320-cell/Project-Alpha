/**
 * "주문이 가는 길" (BV9) — 서버 `OrderExecutor.execute_signal` 이 실제로 지나는 순서를 네 역으로.
 * ==========================================================================
 * 비상 정지 → 위험 검사 → 실행 모드 → 증권사. 순서는 서버 코드 그대로다(신호 기록 → 킬스위치 → 전략·위험 검사 → 모드 갈래 → 발주).
 * ★여기는 서버 열거값을 옮기기만 한다★ — 상태(`status`)·사유 코드(`reason_code`)를 한국어와 역 이름으로 바꿀 뿐,
 * 새 판단을 만들지 않는다. 모르는 값은 원문 그대로 둔다(`stopOf` → "unknown").
 */
import type { AccountKill, ExecMode } from "./api";

export type Stop = "kill" | "risk" | "mode" | "broker";
export const STOPS: { key: Stop; label: string }[] = [
  { key: "kill", label: "비상 정지" },
  { key: "risk", label: "위험 검사" },
  { key: "mode", label: "실행 모드" },
  // 연습용 모드면 실제로는 연습용 체결기라서 '증권사'라 부르지 않는다 — 어디인지는 역의 상태 글이 말한다.
  { key: "broker", label: "보내는 곳" },
];

/** 서버 주문 상태 → 사람 말. 없으면 undefined(부르는 쪽이 원문을 그린다). */
export const STATUS_KO: Record<string, string> = {
  PENDING: "대기", SUBMITTED: "보냈어요", PARTIAL_FILL: "일부 체결", FILLED: "체결",
  CANCELLED: "취소됨", REJECTED: "주문하지 않았어요", FAILED: "보내다 실패", SHADOW_LOGGED: "기록만",
};

/** 거절 사유 코드 → 그 사유를 낸 역(서버 `_reject_order` 를 부르는 자리). */
const REASON_STOP: Record<string, Stop> = {
  kill_switch_active: "kill", kill_switch_race: "kill",
  risk_check_failed: "risk", strategy_disabled: "risk",
  unknown_mode: "mode",
  paper_mode_real_client: "broker",
};
/** 거절이 아닌 상태 → 멈춘(닿은) 역. 기록만은 실행 모드에서 멈추고, 보냈거나 실패한 주문은 증권사까지 갔다. */
const STATUS_STOP: Record<string, Stop> = {
  SHADOW_LOGGED: "mode", PENDING: "mode",
  SUBMITTED: "broker", PARTIAL_FILL: "broker", FILLED: "broker", FAILED: "broker", CANCELLED: "broker",
};

/** 이 주문이 어느 역에서 멈췄나(또는 끝까지 갔나). 모르면 "unknown" — 짐작하지 않는다. */
export function stopOf(status: string, reason: string | null | undefined): Stop | "unknown" {
  if (status === "REJECTED") return (reason && REASON_STOP[reason]) || "unknown";
  return STATUS_STOP[status] ?? "unknown";
}

/** 실행 모드 이름 — 서버 열거값 번역. */
export const MODE_KO: Record<string, string> = { SHADOW: "기록만", PAPER: "모의 체결", LIVE: "실계좌" };

/**
 * 모드 + 연습용 여부 → 주문이 어디로 가는지. `practice` 는 서버 mock 게이트(connection-status) — 모르면 null.
 * null 이면 '어디로' 를 단정하지 않는다(연습용 체결기인지 증권사 모의 서버인지).
 */
export function destination(mode: ExecMode, practice: boolean | null): string {
  if (mode === "SHADOW") return "보내지 않아요";
  if (mode === "PAPER") return practice === true ? "연습용 체결기로 가요" : practice === false ? "증권사 모의 서버로 가요" : "모의 체결로 가요";
  if (mode === "LIVE") return "실제 돈으로 주문해요";
  return `서버가 '${mode}' 모드라고 답했어요`;
}

/** 답 문장 — 서버 값(모드·비상 정지·연습용)만 틀에 끼운다. 이름 뒤 조사가 받침에 따라 바뀌지 않게 "‘이름’에서"·"‘이름’의". */
export function answerSentence(label: string, mode: ExecMode | null, kill: AccountKill | null, practice: boolean | null): string {
  const at = `‘${label}’에서`;
  if (kill?.active && kill.event) return `${at}는 지금 비상 정지 중이라 주문이 나가지 않아요.`;
  if (kill?.active) return `${at} 내는 주문은 지금 막혀 있어요. 이 계좌가 건 정지가 아니에요(운영자 정지이거나 상태를 읽지 못했어요).`;
  if (mode === null) return `‘${label}’의 실행 모드를 확인하지 못했어요.`;
  if (mode === "SHADOW") return `${at} 내는 주문은 지금 기록만 돼요. 증권사로 보내지 않아요.`;
  if (mode === "PAPER") {
    if (practice === true) return `${at} 내는 주문은 지금 연습용 체결기로 가요. 증권사에는 닿지 않아요.`;
    if (practice === false) return `${at} 내는 주문은 지금 증권사 모의 서버로 가요. 실제 돈은 쓰지 않아요.`;
    return `${at} 내는 주문은 지금 모의 체결로 가요.`;
  }
  if (mode === "LIVE") return `${at} 내는 주문은 지금 실제 돈으로 나가요.`;
  return `‘${label}’의 실행 모드는 서버 값 '${mode}'예요.`;
}
