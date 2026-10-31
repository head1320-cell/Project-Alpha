/**
 * 접근 이름·한국어 문장 (CF 3부 R6 — 사용자 결정 6 · 2026-10-31 "번호·이름·상태·확인할 곳")
 * ==========================================================================
 * 화면 읽기가 읽는 말을 한곳에서 만든다. ★상태 말은 카드에 보이는 말과 한 구현★(`cardState` — 카드의 점·먼 보기 글자와 노드 이름이 함께 쓴다).
 * `ARIA_KO` 는 React Flow 의 영어 기본 문장 12개를 모두 덮는다(빠진 열쇠는 영어로 돌아온다 — 시험이 열쇠 목록을 맞춰 본다).
 * 설명문은 우리 캔버스가 실제로 하는 것만 말한다: Enter·Space 고르기 · 화살표 한 칸(Shift 네 칸) · Delete 는 지우고 되돌릴 수 있음 · Esc 풀기.
 * 화살표 안내는 ★방향만★ — React Flow 가 넘기는 좌표는 옮기기 전 자리라(관측: 330 → 341 인데 'x: 330') 틀린 숫자를 말하지 않는다.
 */
import type { AriaLabelConfig } from "@xyflow/react";
import type { GraphError, NodeStatus } from "./types";

const DIRECTION: Record<string, string> = { up: "위로", down: "아래로", left: "왼쪽으로", right: "오른쪽으로" };

const NODE_DESC = "Enter 나 Space 로 노드를 고른 뒤 화살표로 한 칸씩 옮겨요(Shift 와 함께면 네 칸). "
  + "Delete 로 지우면 토스트의 되돌리기나 Ctrl+Z 로 돌려요. Esc 로 고르기를 풀어요.";

export const ARIA_KO: AriaLabelConfig = {
  // 열쇠 이름이 거꾸로다 — 키보드가 켜져 있으면 `keyboardDisabled` 문장이 쓰인다(React Flow 12.12 소스). 둘 다 같은 말로 둔다.
  "node.a11yDescription.default": NODE_DESC,
  "node.a11yDescription.keyboardDisabled": NODE_DESC,
  "node.a11yDescription.ariaLiveMessage": ({ direction }) => `고른 노드를 ${DIRECTION[direction] ?? "옆으로"} 옮겼어요.`,
  "edge.a11yDescription.default": "Enter 나 Space 로 선을 고르면 도구줄과 오른쪽 창 ‘선’ 탭이 열려요. "
    + "Delete 로 끊으면 토스트의 되돌리기나 Ctrl+Z 로 돌려요. Esc 로 고르기를 풀어요.",
  "controls.ariaLabel": "확대·축소 단추",
  "controls.zoomIn.ariaLabel": "확대",
  "controls.zoomOut.ariaLabel": "축소",
  "controls.fitView.ariaLabel": "맞춰 보기",
  "controls.interactive.ariaLabel": "고치기 잠금 켜고 끄기",
  "minimap.ariaLabel": "미니맵",
  "handle.ariaLabel": "소켓",
};

export type CardStateKey = NodeStatus | "stale" | "warn" | "idle";
const STATUS_TEXT: Record<NodeStatus, string> = { ok: "완료", blocked: "막힘", failed: "실패" };

/**
 * 카드 상태 — 카드의 점(`pg-node-dot--{key}`)·먼 보기 글자·노드 이름이 함께 쓴다.
 * `live` 는 지금 그래프의 결과일 때만(낡았으면 없음) · 낡은 결과가 있으면 '예전 결과' · 설정 문제만 있으면 점은 경고지만 글자는 '계산 전'.
 */
export function cardState(r: { live?: NodeStatus; stale: boolean; hasResult: boolean; issues: number }): { key: CardStateKey; text: string } {
  if (r.live) return { key: r.live, text: STATUS_TEXT[r.live] };
  if (r.stale && r.hasResult) return { key: "stale", text: "예전 결과" };
  return { key: r.issues ? "warn" : "idle", text: "계산 전" };
}

/** 카드가 빨갛게 적는 설정 문제 — 빠진 필수 입력(`missing_input`)은 카드가 '이어 주세요' 한 줄로 따로 말하므로 세지 않는다(같은 사실 — BN N3). */
export function nodeIssues(errors: GraphError[] | null | undefined, id: string): GraphError[] {
  return (errors ?? []).filter((e) => e.node_id === id && e.code !== "missing_input");
}

/** "노드 4. 비중 계산 · 완료" · "… · 계산 전 · 설정을 확인할 곳 2곳" — 번호는 카드 배지와 같은 흐름 순서. */
export function nodeAria(num: number | undefined, label: string, state: { text: string }, issues: number, running = false): string {
  return `노드 ${num ?? "·"}. ${label} · ${running ? "계산 중" : state.text}${issues ? ` · 설정을 확인할 곳 ${issues}곳` : ""}`;
}

/** "묶음 ‘데이터 준비’ · 노드 3개 · 접힘" — 이름 앞 말은 상자 머리의 말(묶음·전략)과 같다. */
export function boxAria(strategy: boolean, label: string, count: number, collapsed: boolean): string {
  return `${strategy ? "전략" : "묶음"} ‘${label}’ · 노드 ${count}개 · ${collapsed ? "접힘" : "펼침"}`;
}

/** 갈래 틀 — "갈래 ‘갈래 1’ · 노드 3개"(틀 머리의 이름 그대로). */
export function branchAria(label: string, count: number): string {
  return `갈래 ‘${label}’ · 노드 ${count}개`;
}

/** "선 1. 종목 고르기 → 2. 수익률 불러오기 · 종목" — 접힌 상자의 대리 선은 실제 끝이 숨었다고 덧붙인다. */
export function edgeAria(from: { num?: number; label: string }, to: { num?: number; label: string }, plain: string, proxy: boolean): string {
  return `선 ${from.num ?? "·"}. ${from.label} → ${to.num ?? "·"}. ${to.label} · ${plain}${proxy ? " · 접힌 상자에 걸린 선" : ""}`;
}
