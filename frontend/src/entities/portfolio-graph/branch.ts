/**
 * 갈래 (BM C3) — "이 조건이면?" 을 나란히 보는 복제. 순수 함수.
 * ==========================================================================
 * ★사람이 정한 갈래만★ — 한 뿌리에 갈래는 최대 4개(B~E). 자동 파라미터 스윕·"가장 좋은 갈래" 추천은 하지 않는다(저장소 금지 사항).
 * - 갈래 = 뿌리 노드와 **같은 전략 안의 하류**(전략 밖이면 포트폴리오 레인을 뺀 하류)를 복제한 것. 들어오는 선은 원본과 같이 잇고,
 *   복제 묶음 밖으로 나가는 선은 잇지 않는다(한 전략이 포트폴리오에 두 번 들어가지 않게).
 * - 차이 칩 = 복제 노드의 설정 중 원본과 다른 것. Δ = 두 헤드라인이 **같은 이름·같은 단위**일 때만의 차(아니면 없음 — 지어내지 않는다).
 */
import type { GraphBranch, GraphGroup, NodeRunResult } from "./types";
import { PORTFOLIO_NODE, portfolioLane } from "./strategy";

export const MAX_BRANCHES = 4;
export const BRANCH_LETTERS = ["B", "C", "D", "E"] as const;

type N = { id: string; position: { x: number; y: number }; data: { kind: string; params: Record<string, unknown> } };
type E = { source: string; target: string };

/** 갈래로 복제할 노드 — 뿌리 + (같은 전략 안의 / 전략 밖이면 포트폴리오 레인을 뺀) 하류. 다른 갈래의 복제본은 포함하지 않는다. */
export function branchScope(root: string, nodes: N[], edges: E[], groups: GraphGroup[], branches: GraphBranch[]): string[] {
  const inStrategy = groups.find((g) => g.kind === "strategy" && g.members.includes(root));
  const lane = portfolioLane(nodes, edges, groups);
  const copies = new Set(branches.flatMap((b) => Object.keys(b.map)));
  const allowed = (id: string) => !copies.has(id) && (inStrategy ? inStrategy.members.includes(id)
    : !lane.has(id) && !groups.some((g) => g.kind === "strategy" && g.members.includes(id)))
    && nodes.find((n) => n.id === id)?.data.kind !== PORTFOLIO_NODE;
  const out = new Set<string>();
  const stack = [root];
  while (stack.length) {
    const id = stack.pop()!;
    if (out.has(id) || (id !== root && !allowed(id))) continue;
    out.add(id);
    edges.filter((e) => e.source === id).forEach((e) => stack.push(e.target));
  }
  return nodes.map((n) => n.id).filter((id) => out.has(id));            // 문서 순서를 지킨다
}

/** 원본 뿌리의 다음 갈래 글자 — 다 찼으면 null. */
export function nextBranchLetter(ofRoot: string, branches: GraphBranch[]): string | null {
  const used = new Set(branches.filter((b) => b.of_root === ofRoot).map((b) => b.label));
  return BRANCH_LETTERS.find((l) => !used.has(`갈래 ${l}`)) ?? null;
}

/** 설정 차이 — 원본과 다른 파라미터 이름·값 쌍(깊은 비교). */
export function paramDiff(orig: Record<string, unknown>, copy: Record<string, unknown>): { key: string; from: unknown; to: unknown }[] {
  const keys = [...new Set([...Object.keys(orig ?? {}), ...Object.keys(copy ?? {})])];
  return keys.filter((k) => JSON.stringify(orig?.[k] ?? null) !== JSON.stringify(copy?.[k] ?? null))
    .map((k) => ({ key: k, from: orig?.[k], to: copy?.[k] }));
}

/** 값을 짧은 글로 — 차이 칩·비교 표용. 없으면 "기본값". */
export function shortValue(v: unknown): string {
  if (v === undefined || v === null) return "기본값";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  if (typeof v === "string") return v.length > 18 ? `${v.slice(0, 17)}…` : v;
  if (typeof v === "boolean") return v ? "켬" : "끔";
  if (Array.isArray(v)) return `${v.length}개`;
  return "바뀐 값";
}

/** Δ — 두 결과가 모두 완료이고 헤드라인의 이름·단위가 같을 때만. `%` 는 %p 로. */
export function headlineDelta(orig: NodeRunResult | undefined, copy: NodeRunResult | undefined): { value: number; unit: string } | null {
  const a = orig?.status === "ok" ? orig.explain?.headline : null;
  const b = copy?.status === "ok" ? copy.explain?.headline : null;
  if (!a || !b || a.value === null || b.value === null || a.unit !== b.unit || a.label !== b.label) return null;
  const d = Number(b.value) - Number(a.value);
  if (!Number.isFinite(d)) return null;
  return { value: d, unit: a.unit === "%" ? "%p" : a.unit };
}

export function fmtDelta(d: { value: number; unit: string }): string {
  const v = Math.abs(d.value) >= 10 ? d.value.toFixed(1) : d.value.toFixed(2);
  return `${d.value > 0 ? "+" : d.value < 0 ? "" : "±"}${v}${d.unit}`;
}
