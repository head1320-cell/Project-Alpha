/**
 * 운영 계좌 문장 (BU9b) — 서버 값(모드·비상 정지·연습용 게이트)만 틀에 끼운다. 새 판단 없음(ADR-003 §2.6).
 * ==========================================================================
 * /내 계좌(`entities/broker-account/orderPath`)의 문장을 그대로 쓰면 셋이 틀린다:
 *  ⓐ 운영 계좌 정지는 이벤트가 있어야 '어떤 정지'인지 안다 — `is_active` 만 참이고 이벤트가 없으면 조회 실패일 수도 있다
 *     (서버는 조회가 실패해도 '켜짐'으로 본다). 그래서 둘을 가를 수 없다고 그대로 말한다.
 *  ⓑ 모의 체결 + 실데이터 연결이면 서버 연결이 모의투자가 아닐 때 `paper_mode_real_client` 로 거절한다 — 화면은
 *     `KIS_IS_PAPER` 를 모르므로 '증권사 모의 서버로 간다'고 단정하지 않는다.
 *  ⓒ ★운영자 비상 정지는 모든 사용자 계좌의 새 주문도 막는다★(BV6a `KillSwitch.is_active`).
 */
import type { OpKill, OpModeName } from "@/entities/trading/operator";

/** 모드 표 이름 — /내 계좌와 같은 말(서버 열거값 번역). */
export const MODE_NAME: Record<string, string> = { SHADOW: "기록만", PAPER: "모의 체결", LIVE: "실계좌" };
/** 조사가 받침에 따라 바뀌어서 붙이지 않고 통째로 적는다. */
export const MODE_TO: Record<string, string> = { SHADOW: "기록만으로", PAPER: "모의 체결로", LIVE: "실계좌로" };
export const MODE_IS: Record<string, string> = { SHADOW: "기록만이에요", PAPER: "모의 체결이에요", LIVE: "실계좌예요" };

type Read<T> = { pending: boolean; failed: boolean; value: T | null };

/** 맨 위 답 한 문장. 앞 규칙이 이긴다(정지 → 정지 모름 → 모드). */
export function opSentence(mode: Read<OpModeName>, kill: Read<OpKill>, practice: boolean | null): string {
  if (mode.pending || kill.pending) return "운영 계좌 상태를 확인하는 중이에요.";
  const k = kill.value;
  if (k?.is_active && k.active_event) return "운영 계좌는 지금 비상 정지 중이에요. 운영 계좌와 모든 사용자 계좌의 새 주문이 나가지 않아요.";
  if (k?.is_active) return "비상 정지가 켜져 있다고 서버가 답했지만 어떤 정지인지 읽지 못했어요. 새 주문은 막혀 있어요.";
  if (kill.failed) return "운영 계좌의 비상 정지 상태를 확인하지 못했어요. 주문이 나가는지 단정할 수 없어요.";
  const m = mode.value;
  if (mode.failed || m === null) return "운영 계좌의 실행 모드를 확인하지 못했어요.";
  const at = "운영 계좌에서 내는 주문은 지금";
  if (m === "SHADOW") return `${at} 기록만 돼요. 증권사로 보내지 않아요.`;
  if (m === "PAPER") {
    if (practice === true) return `${at} 연습용 체결기로 가요. 증권사에는 닿지 않아요.`;
    if (practice === false) return `${at} 모의 체결로 가요. 서버의 증권사 연결이 모의투자가 아니면 서버가 거절해요.`;
    return `${at} 모의 체결로 가요.`;
  }
  if (m === "LIVE") return `${at} 실제 돈으로 나가요.`;
  return `운영 계좌의 실행 모드는 서버 값 '${m}'예요.`;
}

/** 보내는 곳 역 — 모드 + 연습용 여부. 모르면 단정하지 않는다. */
export function opDestination(mode: OpModeName, practice: boolean | null): string {
  if (mode === "SHADOW") return "보내지 않아요";
  if (mode === "PAPER") return practice === true ? "연습용 체결기로 가요" : practice === false ? "증권사 모의 서버로 가요" : "모의 체결로 가요";
  if (mode === "LIVE") return "실제 돈으로 주문해요";
  return `서버가 '${mode}' 모드라고 답했어요`;
}

/** 비상 정지 역의 상태 글. */
export function killState(kill: Read<OpKill>): string {
  if (kill.pending) return "확인하는 중이에요";
  if (kill.failed) return "확인하지 못했어요";
  const k = kill.value;
  if (k?.is_active && k.active_event) return "켜져 있어요";
  if (k?.is_active) return "켜져 있지만 어떤 정지인지 몰라요";
  return "꺼져 있어요";
}

/** 모의 체결로 바꿀 때 확인 줄 — 어디로 가는지(연습용 여부)를 서버 게이트로만. */
export function paperConfirm(practice: boolean | null): string {
  if (practice === true) return "모의 체결로 바꾸면 운영 계좌 주문을 연습용 체결기로 보내요. 실제 돈은 쓰지 않아요.";
  if (practice === false) return "모의 체결로 바꾸면 운영 계좌 주문을 증권사 모의 서버로 보내요. 서버의 증권사 연결이 모의투자가 아니면 서버가 거절해요.";
  return "모의 체결로 바꾸면 운영 계좌 주문을 모의 체결로 보내요. 실제 돈은 쓰지 않아요.";
}
