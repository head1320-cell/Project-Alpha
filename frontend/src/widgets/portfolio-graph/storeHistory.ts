/**
 * 캔버스 상태 조각 — 되돌리기·복사 (CF 3부 E3 — `store.ts` 에서 옮김 · 동작 불변)
 */
import type { PgState } from "./store";
import { newId, HISTORY, clean, bare, type SliceCtx } from "./storeShared";

type HistorySlice = Pick<PgState, "undo" | "redo" | "copy" | "paste">;

export const historySlice = ({ set, get, push }: SliceCtx): HistorySlice => ({
  undo: () => set((s) => {
    const prev = s.past[s.past.length - 1];
    if (!prev) return {};
    return {
      past: s.past.slice(0, -1),
      future: [{ nodes: clean(s.nodes), edges: s.edges, groups: s.groups, branches: s.branches }, ...s.future].slice(0, HISTORY),
      nodes: prev.nodes, edges: prev.edges, groups: prev.groups, branches: prev.branches ?? [], picked: [],
      selectedId: prev.nodes.some((n) => n.id === s.selectedId) ? s.selectedId : null,
      };
  }),

  redo: () => set((s) => {
    const next = s.future[0];
    if (!next) return {};
    return {
      future: s.future.slice(1),
      past: [...s.past, { nodes: clean(s.nodes), edges: s.edges, groups: s.groups, branches: s.branches }].slice(-HISTORY),
      nodes: next.nodes, edges: next.edges, groups: next.groups, branches: next.branches ?? [], picked: [],
      selectedId: next.nodes.some((n) => n.id === s.selectedId) ? s.selectedId : null,
      };
  }),

  copy: () => {
    const s = get();
    const ids = new Set(s.picked.length ? s.picked : s.selectedId ? [s.selectedId] : []);
    if (!ids.size) return 0;
    const nodes = s.nodes.filter((n) => ids.has(n.id));
    // ★링크는 고른 것끼리만★ — 고르지 않은 노드로 들어오던 링크를 따라 붙이면 붙인 자리에서 뜻이 바뀐다.
    const edges = s.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    set({ clip: { nodes: structuredClone(clean(nodes)), edges: structuredClone(edges) } });
    return nodes.length;
  },

  paste: () => {
    const s = get();
    if (!s.clip?.nodes.length) return 0;
    push();
    const taken = new Set(s.nodes.map((n) => n.id));
    const remap = new Map<string, string>();
    const nodes = s.clip.nodes.map((n) => {
      const id = newId(n.data.kind, taken);
      taken.add(id);
      remap.set(n.id, id);
      return { ...n, id, selected: true, position: { x: n.position.x + 48, y: n.position.y + 48 },
               data: { ...n.data, params: structuredClone(n.data.params ?? {}) } };
    });
    const edges = s.clip.edges.map((e) => {
      const source = remap.get(e.source)!;
      const target = remap.get(e.target)!;
      return { ...bare(e), source, target, id: `${source}.${e.sourceHandle}->${target}.${e.targetHandle}`, selected: false };
    });
    set({
      nodes: [...s.nodes.map((n) => ({ ...n, selected: false })), ...nodes], edges: [...s.edges, ...edges],
      picked: nodes.map((n) => n.id), selectedId: nodes.length === 1 ? nodes[0].id : s.selectedId,
      // 다음 붙여넣기는 또 한 칸 비껴 놓는다.
      clip: { nodes: s.clip.nodes.map((n) => ({ ...n, position: { x: n.position.x + 48, y: n.position.y + 48 } })),
              edges: s.clip.edges },
    });
    return nodes.length;
  },
});
