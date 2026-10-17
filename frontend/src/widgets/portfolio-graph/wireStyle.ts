/**
 * 선 모습 (CF3b1, 순수) — 굵기 · 예전 결과 · 계산 중 흐름을 한곳에서 정한다. `PortfolioCanvas` 는 잇기만 한다.
 *  · 굵기: 받는 포트가 필수면 3, 선택이면 1.75 — 계산 중인 길·원인 경로면 +1. 받는 포트를 모르면 필수로 본다(카탈로그 기본값).
 *  · 예전 결과: 받는 노드의 결과가 지금 그래프의 것이 아니면(BT5 `staleIds`) — 결과가 없는 노드는 '예전'이 아니다.
 *  · 흐름: 계산 중일 때 — 여기까지 계산(`runningIds`)이면 그 길의 선만, 전체 계산이면 모든 선.
 */
import type { EdgeRecord, IssueLevel } from "@/entities/portfolio-graph";

export const WIRE_W_REQUIRED = 3;
export const WIRE_W_OPTIONAL = 1.75;
export const WIRE_W_LIT = 1;

export type WireLook = { required: boolean; width: number; stale: boolean; flow: boolean };

export function wireLook(a: {
  required: boolean | undefined;
  lit: boolean;
  onCause: boolean;
  targetHasResult: boolean;
  targetStale: boolean;
  running: boolean;
  runningIds: readonly string[] | null;
}): WireLook {
  const required = a.required !== false;
  const base = required ? WIRE_W_REQUIRED : WIRE_W_OPTIONAL;
  return {
    required,
    width: base + (a.lit || a.onCause ? WIRE_W_LIT : 0),
    stale: a.targetStale && a.targetHasResult,
    flow: a.running && (a.runningIds ? a.lit : true),
  };
}

/** 전달 점검 표시(CF3b2) — 문제가 있을 때만. `[]`(점검했고 찾지 못함)·`null`(점검하지 않음)·받는 쪽이 예전 결과면 없다.
 *  단계는 가장 무거운 것 하나: 빠짐 > 바뀜 > 구조 > 쓰지 않음. 이름 글은 서버의 첫 문제 글. */
export const ISSUE_RANK: Record<IssueLevel, number> = { lost: 0, changed: 1, structural: 2, unused: 3 };
export type WireFlag = { level: IssueLevel; count: number; first: string };

export function wireFlag(rec: EdgeRecord | undefined, targetStale: boolean): WireFlag | null {
  if (!rec?.issues?.length || targetStale) return null;
  const level = rec.issues.reduce((a, i) => (ISSUE_RANK[i.level] < ISSUE_RANK[a] ? i.level : a), rec.issues[0].level);
  return { level, count: rec.issues.length, first: rec.issues[0].text };
}
