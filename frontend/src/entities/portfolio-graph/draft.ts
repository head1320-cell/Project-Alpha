/**
 * 말로 설계(AI4) — 초안의 미리보기 자리 · 낡음 판정 · 값이 바뀔 노드. ★초안은 문서가 아니다★ — [받아들이기] 전에는
 * 노드 목록·저장·계산에 들어가지 않는다(서버 `src/services/canvas_assist/draft.py` 가 검사한 것만 온다 — 값은 서버가 말씀에서 읽었다).
 */
import { placeSuggestion, type Box, type PlaceNode } from "./ghost";
import { NEW_NODE } from "./procedure";
import { cardHeight, NODE_W } from "./size";
import { stableJson } from "./staleness";
import type { DraftBody, GraphDoc, NodeCatalogEntry } from "./types";

/** 초안이 기댄 문서 — 노드(id·종류·설정)와 선. ★위치는 넣지 않는다★(옮기기만 하면 초안은 그대로, 설정을 바꾸면 지운다). */
export function draftSig(doc: GraphDoc): string {
  return stableJson([doc.nodes.map((n) => [n.id, n.type, n.params]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
                     doc.edges.map((e) => [e.source, e.source_port, e.target, e.target_port].join("|")).sort()]);
}

/** 값이 바뀔 ★지금★ 노드 — 새 노드는 유령 카드가 말한다. */
export function draftTouched(d: DraftBody, existing: ReadonlySet<string>): string[] {
  return [...new Set(d.set.map((s) => s.node).filter((id) => existing.has(id)))];
}

/**
 * 더할 노드의 자리 — 유령(CF6)과 같은 규칙(`placeSuggestion`: 앞 노드의 옆 열 · 겹치면 그 아래 빈 자리)을 ★위상 순서로 되풀이★한다.
 * 놓은 유령은 다음 자리 찾기의 노드·빈 자리에 들어간다(서로 겹치지 않게). 앞이 없으면 가장 아래 카드 밑(빈 캔버스면 원점).
 */
export function placeDraft(d: DraftBody, nodes: PlaceNode[], catalog: NodeCatalogEntry[] | null | undefined): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {};
  const placed: PlaceNode[] = [...nodes];
  const taken: Box[] = [];
  const fresh = new Set(d.add.map((a) => a.id));
  const ready = (id: string) => !fresh.has(id) || id in out;
  const left = [...d.add];
  while (left.length) {
    const i = Math.max(0, left.findIndex((a) => d.connect.every((c) => c.target !== a.id || ready(c.source))));
    const a = left.splice(i, 1)[0];
    const attach = d.connect
      .filter((c) => (c.target === a.id && ready(c.source)) || (c.source === a.id && !fresh.has(c.target)))
      .map((c) => ({ source: c.source === a.id ? NEW_NODE : c.source, source_port: c.source_port,
                     target: c.target === a.id ? NEW_NODE : c.target, target_port: c.target_port }));
    const at = placeSuggestion({ action: "add", kind: a.kind, label: a.label, text: "", attach, unlocks: [] }, placed, catalog, taken);
    out[a.id] = at;
    placed.push({ id: a.id, kind: a.kind, position: at });
    taken.push({ x: at.x, y: at.y, w: NODE_W, h: cardHeight(a.kind, catalog) });
  }
  return out;
}
