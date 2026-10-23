/**
 * 캔버스 상태의 도우미 (CF 3부 E3 — `store.ts` 에서 옮김 · 동작 불변)
 * 조각(slice) 파일들이 함께 쓰는 셈·상수·순수 함수. 일련번호(`seq`)는 여기 하나뿐이다.
 */
import type { Edge } from "@xyflow/react";
import { cardHeight, type GraphGroup, type NodeCatalogEntry, type NodeStatus, type PgNode, type RunReport } from "@/entities/portfolio-graph";
import { stableJson } from "@/entities/portfolio-graph/staleness";
import type { StoreApi } from "zustand";
import type { PgState, RunRecord, RunProgress } from "./store";

/** 전략 이름 — 이미 있는 이름이면 숫자를 붙인다(포트폴리오 노드는 이름이 겹치면 사유와 함께 멈춘다). */
export function uniqueLabel(want: string, groups: GraphGroup[]): string {
  const taken = new Set(groups.map((g) => g.label));
  if (!taken.has(want)) return want;
  for (let k = 2; ; k++) if (!taken.has(`${want} ${k}`)) return `${want} ${k}`;
}

let seq = 0;
/** id 끝의 일련번호 — 노드·묶음·갈래가 한 셈을 쓴다(E3: 조각 파일들이 같은 수를 잇도록 한 곳에). */
export const nextSeq = () => ++seq;
export const newId = (kind: string, taken: Set<string>) => {
  let id = "";
  do { id = `${kind}_${Date.now().toString(36)}${(++seq).toString(36)}`; } while (taken.has(id));
  return id;
};

export const STRUCTURAL = new Set(["add", "remove", "reset"]);
export const HISTORY = 50;
/** 전략·블록을 아래에 넣을 때 위 카드 바닥에서 띄우는 틈 — 예전 "맨 위 y + 300" 이 폭 150 · 높이 ≤124 카드에서 남기던 틈(≥176)과 같다. */
export const INSERT_GAP = 176;
export const RUNS = 10;
/** 같은 노드의 설정을 잇달아 고치면 한 단계로 묶는다(글자 하나마다 되돌리기 한 번이면 못 쓴다). */
export const COALESCE_MS = 800;

/** 하류(BT4·BT5) — 이 노드들에서 선을 따라 닿는 모든 노드(자기 자신은 뺀다). */
export function descendantsOf(ids: string[], edges: { source: string; target: string }[]): string[] {
  const out = new Map<string, string[]>();
  for (const e of edges) out.set(e.source, [...(out.get(e.source) ?? []), e.target]);
  const seen = new Set<string>();
  const stack = [...ids.flatMap((i) => out.get(i) ?? [])];
  while (stack.length) {
    const n = stack.pop()!;
    if (seen.has(n)) continue;
    seen.add(n);
    stack.push(...(out.get(n) ?? []));
  }
  for (const i of ids) seen.delete(i);
  return [...seen];
}

/** 조상(자신 포함) — 서버 `portfolio_graph._ancestors` 와 같은 규칙. "여기까지 계산" 이 돌 노드들. */
export function ancestorsOf(ids: string[], edges: { source: string; target: string }[]): string[] {
  const into = new Map<string, string[]>();
  for (const e of edges) into.set(e.target, [...(into.get(e.target) ?? []), e.source]);
  const seen = new Set<string>();
  const stack = [...ids];
  while (stack.length) {
    const n = stack.pop()!;
    if (seen.has(n)) continue;
    seen.add(n);
    stack.push(...(into.get(n) ?? []));
  }
  return [...seen];
}

/**
 * 원인 경로 — `id` 에서 상류로, **완료가 아닌** 노드만 따라 올라간다(완료된 상류는 원인이 아니다).
 * 뿌리 = 계산 못 한 상류가 더 없는 노드(스스로 실패했거나 자기 설정 때문에 막힌 노드). 결과가 없는 노드는 따라가지 않는다.
 */
export function causePath(id: string, edges: { source: string; target: string }[],
                          results: Record<string, { status: NodeStatus }> | null | undefined): { path: string[]; roots: string[] } {
  const bad = (n: string) => !!results?.[n] && results[n].status !== "ok";
  if (!bad(id)) return { path: [], roots: [] };
  const seen = new Set<string>();
  const roots: string[] = [];
  const stack = [id];
  while (stack.length) {
    const n = stack.pop()!;
    if (seen.has(n)) continue;
    seen.add(n);
    const up = edges.filter((e) => e.target === n && bad(e.source)).map((e) => e.source);
    if (!up.length) roots.push(n);
    stack.push(...up);
  }
  return { path: [...seen], roots };
}

export const clean = (nodes: PgNode[]) => nodes.map((n) => ({ ...n, selected: false, dragging: false }));
/** 계산을 시작할 때 — 서버가 순서(`plan`)를 알리기 전까지는 계산할 노드를 그대로 대기로 둔다. */
export const waitingFor = (ids: string[]): RunProgress =>
  ({ order: ids, lost: false, final: false, cells: Object.fromEntries(ids.map((id) => [id, { phase: "waiting" as const }])) });
/** 선 복사본(복제·갈래·붙여넣기)은 경유점을 가져가지 않는다(CF4c) — 노드가 다른 자리로 가니 옛 길은 틀린 길이다. 화면 선의 `data` 는 경유점만 담는다. */
export const bare = (e: Edge): Edge => { const { data: _via, ...rest } = e; void _via; return rest; };
/** 쌓기·맞추기에 쓰는 카드 높이(CF4a) — 화면에서 잰 높이와 카드 높이 중 큰 값(막힘 사유로 자란 카드 · 아직 안 잰 카드). */
export const boxH = (n: PgNode, catalog: NodeCatalogEntry[] | null) => Math.max(n.measured?.height ?? 0, cardHeight(n.data.kind, catalog));

export function record(report: RunReport, partial: string[] | null): RunRecord {
  const nodes: RunRecord["nodes"] = {};
  const counts = { ok: 0, blocked: 0, failed: 0 };
  for (const [id, r] of Object.entries(report.nodes)) {
    if (r.previous) continue;
    counts[r.status] += 1;
    const h = r.explain?.headline;
    nodes[id] = { status: r.status, headline: h ? (h.text ?? (h.value != null ? `${h.value}${h.unit ?? ""}` : null)) : null,
                  value: typeof h?.value === "number" ? h.value : null };
  }
  return { at: Date.now(), partial, counts, nodes };
}

/** 말로 설계 출처 중 값이 그대로인 칸만 남긴다(AI4). 남는 것이 없으면 없음. */
export function keepSaid(said: Record<string, string> | undefined, before: Record<string, unknown>, after: Record<string, unknown>) {
  if (!said) return undefined;
  const kept = Object.entries(said).filter(([f]) => f in after && stableJson(before[f]) === stableJson(after[f]));
  return kept.length ? Object.fromEntries(kept) : undefined;
}

/** 조각이 받는 것 — `set` 은 낡음을 다시 세는 것을 감싼 그대로, `push` 는 되돌리기 칸에 넣기. */
export interface SliceCtx {
  set: StoreApi<PgState>["setState"];
  get: () => PgState;
  push: () => void;
}
