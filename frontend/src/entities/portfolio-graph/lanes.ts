/**
 * 단계 레인 (CF4b, 순수) — 서버 단계 순서대로 왼→오 세로 띠 여섯. 노드의 단계는 카탈로그 `stage`.
 * ==========================================================================
 * 띠 폭은 그 단계 안 노드끼리의 깊이(같은 단계 노드 사이의 선으로 잰 가장 긴 길)로 정한 하위 열 수 × 열 폭(COL).
 * 빈 단계도 한 열을 차지해 여섯 띠가 늘 같은 순서로 보인다. ★현재 위치와 무관하게 문서·카탈로그로만 정한다★ —
 * 자유 이동은 막지 않는다(띠 밖에 둔 노드는 밖에 그대로 보인다). '레인에 맞추기'(`fitLanes`)만 노드를 옮긴다.
 */
import { COL, COL_GAP, ROW_GAP } from "./size";
import type { NodeCatalogEntry, WorkflowStage } from "./types";

export type Lane = { key: string; label: string; x: number; w: number; cols: number; count: number };
type N = { id: string; kind: string; position: { x: number; y: number } };
type E = { source: string; target: string };

const stageOf = (kind: string, catalog: NodeCatalogEntry[]) => catalog.find((c) => c.type === kind)?.stage ?? null;

/** 단계 안 깊이 — 같은 단계 노드 사이의 선만 본다(순환은 엔진이 막는다 — 여기서는 방문한 노드를 다시 세지 않는다). */
function depthsWithin(ids: string[], edges: E[]): Map<string, number> {
  const inside = new Set(ids);
  const preds = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const e of edges) if (inside.has(e.source) && inside.has(e.target)) preds.get(e.target)!.push(e.source);
  const d = new Map<string, number>();
  const visit = (id: string, seen: Set<string>): number => {
    if (d.has(id)) return d.get(id)!;
    if (seen.has(id)) return 0;
    seen.add(id);
    const v = Math.max(0, ...preds.get(id)!.map((p) => visit(p, seen) + 1));
    d.set(id, v);
    return v;
  };
  for (const id of ids) visit(id, new Set());
  return d;
}

export function laneLayout(nodes: N[], edges: E[], catalog: NodeCatalogEntry[], stages: WorkflowStage[]):
  { lanes: Lane[]; slot: Map<string, { lane: string; col: number }> } {
  const slot = new Map<string, { lane: string; col: number }>();
  const lanes: Lane[] = [];
  let x = 0;
  for (const st of stages) {
    const ids = nodes.filter((n) => stageOf(n.kind, catalog) === st.key).map((n) => n.id);
    const depth = depthsWithin(ids, edges);
    for (const id of ids) slot.set(id, { lane: st.key, col: depth.get(id) ?? 0 });
    const cols = Math.max(1, ...ids.map((id) => (depth.get(id) ?? 0) + 1));
    lanes.push({ key: st.key, label: st.label, x, w: cols * COL, cols, count: ids.length });
    x += cols * COL;
  }
  return { lanes, slot };
}

/**
 * 레인에 맞추기 — 노드마다 자기 띠의 하위 열(x = 띠 시작 + 열 × COL + 틈 반)로, 같은 열 안 위아래는 ★지금 순서★대로
 * 실제 높이 + 틈으로 쌓는다. 단계를 모르는 노드(카탈로그에 없음)는 그대로 둔다(지어내지 않는다).
 */
export function fitLanes(nodes: N[], edges: E[], catalog: NodeCatalogEntry[], stages: WorkflowStage[],
                         heightOf: (id: string) => number): Map<string, { x: number; y: number }> {
  const { lanes, slot } = laneLayout(nodes, edges, catalog, stages);
  const laneX = new Map(lanes.map((l) => [l.key, l.x]));
  const cells = new Map<string, N[]>();
  for (const n of nodes) {
    const s = slot.get(n.id);
    if (!s) continue;
    const k = `${s.lane}|${s.col}`;
    cells.set(k, [...(cells.get(k) ?? []), n]);
  }
  const out = new Map<string, { x: number; y: number }>();
  for (const [k, col] of cells) {
    const [lane, c] = k.split("|");
    let top = 0;
    for (const n of [...col].sort((a, b) => a.position.y - b.position.y)) {
      out.set(n.id, { x: laneX.get(lane)! + Number(c) * COL + COL_GAP / 2, y: top });
      top += heightOf(n.id) + ROW_GAP;
    }
  }
  return out;
}
