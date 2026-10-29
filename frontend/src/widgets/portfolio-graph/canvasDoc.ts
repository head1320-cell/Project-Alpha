/**
 * 지금 캔버스의 문서 (CF 3부 PB3 — `PortfolioCanvas` 에서 옮김 · 동작 불변) — 캔버스 본체와 고객 칩이 같은 문서를 본다.
 */
import { toDoc, type GraphDoc } from "@/entities/portfolio-graph";
import type { PgState } from "./store";

export type DocState = Pick<PgState, "nodes" | "edges" | "name" | "goal" | "groups" | "branches" | "pinned" | "folded">;

export function docOf(s: DocState): GraphDoc {
  return toDoc(s.nodes, s.edges, s.name || s.goal ? { ...(s.name ? { name: s.name } : {}), ...(s.goal ? { goal: s.goal } : {}) } : undefined,
               s.groups, s.branches, s.pinned, s.folded);
}
