/**
 * 말로 설계(AI4) — 초안의 미리보기 자리 · 낡음 판정 · 값이 바뀔 노드. ★초안은 문서가 아니다★ — [받아들이기] 전에는
 * 노드 목록·저장·계산에 들어가지 않는다(서버 `src/services/canvas_assist/draft.py` 가 검사한 것만 온다 — 값은 서버가 말씀에서 읽었다).
 */
import { placeSuggestion, type Box, type PlaceNode } from "./ghost";
import { NEW_NODE } from "./procedure";
import { cardHeight, NODE_W } from "./size";
import { stableJson } from "./staleness";
import type { DraftAdd, DraftBody, DraftConnect, DraftSet, GraphDoc, NodeCatalogEntry } from "./types";

/** 초안이 기댄 문서 — 노드(id·종류·설정)와 선. ★위치는 넣지 않는다★(옮기기만 하면 초안은 그대로, 설정을 바꾸면 지운다). */
export function draftSig(doc: GraphDoc): string {
  return stableJson([doc.nodes.map((n) => [n.id, n.type, n.params]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
                     doc.edges.map((e) => [e.source, e.source_port, e.target, e.target_port].join("|")).sort()]);
}

/** 초안 줄의 열쇠(U5) — 더하기 `add:<id>` · 잇기 `connect:<id>` · 값 `set:<노드>.<칸>`. */
export const draftKey = {
  add: (a: DraftAdd) => `add:${a.id}`,
  connect: (c: DraftConnect) => `connect:${c.id}`,
  set: (x: DraftSet) => `set:${x.node}.${x.field}`,
};

/**
 * 초안 일부만 받기(U5 — 사용자 결정 2026-11-01 "줄마다 고르기") — 뺀 줄(`off`)을 뺀 본문. 잇기는 두 끝이 모두 있어야 하고(지금 노드이거나
 * 고른 새 노드) 값은 그 노드가 있어야 한다 — 기대는 새 노드를 빼면 그 줄은 ★막힘★(까닭 한 줄)이 되어 본문에 들지 않는다(조용히 빼지 않는다).
 * `summary`·`empty` 는 안내라 그대로. `n` = 받을 줄 수. 순수 — 시험이 직접 부른다.
 */
export function pickDraft(d: DraftBody, off: ReadonlySet<string>, existing: ReadonlySet<string>):
  { body: DraftBody; blocked: Map<string, string>; n: number } {
  const add = d.add.filter((a) => !off.has(draftKey.add(a)));
  const label = new Map(d.add.map((a) => [a.id, a.label]));
  const kept = new Set(add.map((a) => a.id));
  const has = (id: string) => existing.has(id) || kept.has(id);
  const gone = (id: string) => `‘${label.get(id) ?? id}(새)’를 빼서`;
  const blocked = new Map<string, string>();
  const connect = d.connect.filter((c) => {
    const k = draftKey.connect(c), miss = [c.source, c.target].find((id) => !has(id));
    if (miss !== undefined) { blocked.set(k, `${gone(miss)} 이 선을 연결할 수 없습니다`); return false; }
    return !off.has(k);
  });
  const set = d.set.filter((x) => {
    const k = draftKey.set(x);
    if (!has(x.node)) { blocked.set(k, `${gone(x.node)} 이 값을 넣을 곳이 없습니다`); return false; }
    return !off.has(k);
  });
  return { body: { ...d, add, connect, set }, blocked, n: add.length + connect.length + set.length };
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
