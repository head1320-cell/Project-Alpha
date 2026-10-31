/**
 * 캔버스 상태 조각 — 노드·선 편집 (CF 3부 E3 — `store.ts` 에서 옮김 · 동작 불변)
 */
import { addEdge, applyEdgeChanges, applyNodeChanges } from "@xyflow/react";
import { fromDoc, PG_NODE_TYPE, ROW_GAP, nodeHeight, NEW_NODE, placeNodes, placeSuggestion, slotBase, slotHeight, type DraftSet, type PgNodeData, type PgNode } from "@/entities/portfolio-graph";
import { swapPlan } from "@/entities/portfolio-graph/swap";
import type { PgState } from "./store";
import { newId, STRUCTURAL, COALESCE_MS, bare, keepSaid, pruneRemoved, type SliceCtx } from "./storeShared";

/** 같은 노드의 설정을 잇달아 고친 때 · 끌기 한 번 = 한 단계(이 조각만 쓴다). */
let lastParamEdit: { id: string; at: number } | null = null;
let dragging = false;

type GraphSlice = Pick<PgState, "setCatalog" | "onNodesChange" | "onEdgesChange" | "connect" | "swapNode" | "rewire" | "addLinked" | "applySuggestion" | "applyDraft" | "selectEdge" | "insertOnEdge" | "addNode" | "updateParams" | "deleteElements" | "duplicateNode" | "loadDoc" | "setName" | "setGoal" | "select" | "pickIds" | "resizeSlot" | "togglePin" | "toggleFold" | "setReconnecting" | "reconnect">;

export const graphSlice = ({ set, get, push }: SliceCtx): GraphSlice => ({
  setCatalog: (catalog, err = null) => set({ catalog, catalogError: err }),

  onNodesChange: (all) => {
    // 크기 손잡이(R3)가 내는 크기 바꾸기는 버린다 — 높이는 결과 칸(`resizeSlot`)으로만 정하고, 노드에 고정 높이를 박지 않는다.
    const changes = all.filter((c) => !(c.type === "dimensions" && (c.resizing !== undefined || c.setAttributes)));
    if (!changes.length) return;
    const structural = changes.some((c) => STRUCTURAL.has(c.type));
    const drag = changes.find((c) => c.type === "position") as { dragging?: boolean } | undefined;
    if (structural) push();
    else if (drag?.dragging && !dragging) { dragging = true; push(); }          // 끌기 한 번 = 한 단계
    if (drag && drag.dragging === false) dragging = false;
    set((s) => {
      const removed = new Set(changes.filter((c) => c.type === "remove").map((c) => (c as { id: string }).id));
      const nodes = applyNodeChanges(changes, s.nodes) as PgNode[];
      const selChanged = changes.some((c) => c.type === "select");
      const picked = selChanged ? nodes.filter((n) => n.selected).map((n) => n.id)
        : s.picked.filter((id) => !removed.has(id));
      return {
        nodes,
        edges: removed.size ? s.edges.filter((e) => !removed.has(e.source) && !removed.has(e.target)) : s.edges,
        groups: removed.size ? s.groups.map((g) => ({ ...g, members: g.members.filter((m) => !removed.has(m)) }))
          .filter((g) => g.members.length > 0) : s.groups,
        picked,
        selectedId: s.selectedId && removed.has(s.selectedId) ? null
          : (selChanged && picked.length === 1 ? picked[0] : s.selectedId),
      };
    });
  },

  onEdgesChange: (changes) => {
    if (changes.some((c) => STRUCTURAL.has(c.type))) push();
    set((s) => ({
      edges: applyEdgeChanges(changes, s.edges),
    }));
  },

  connect: (c) => {
    push();
    set((s) => ({
      edges: addEdge({ ...c, id: `${c.source}.${c.sourceHandle}->${c.target}.${c.targetHandle}` }, s.edges),
    }));
  },

  swapNode: (id, kind) => {
    const s = get();
    const plan = swapPlan(id, kind, s.nodes, s.edges, s.catalog ?? []);
    if (!plan) return null;
    push();
    const edges = s.edges.map((e) => {
      if (!(e.id in plan.inputs) && !(e.id in plan.outputs)) return e;
      const sourceHandle = plan.outputs[e.id] ?? e.sourceHandle ?? null;
      const targetHandle = plan.inputs[e.id] ?? e.targetHandle ?? null;
      return { ...e, sourceHandle, targetHandle, id: `${e.source}.${sourceHandle}->${e.target}.${targetHandle}` };
    });
    set({ nodes: s.nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, kind, params: {}, said: undefined } } : n)), edges,
          selectedEdge: null });
    return id;
  },

  rewire: (target, port, source, sourceHandle) => {
    push();
    set((s) => {
      const kept = s.edges.filter((e) => !(e.target === target && e.targetHandle === port));
      const edges = source && sourceHandle
        ? addEdge({ source, sourceHandle, target, targetHandle: port, id: `${source}.${sourceHandle}->${target}.${port}` }, kept)
        : kept;
      return { edges, selectedEdge: null };
    });
  },

  addLinked: (kind, position, link) => {
    push();
    const s = get();
    const id = newId(kind, new Set(s.nodes.map((n) => n.id)));
    const node: PgNode = { id, type: PG_NODE_TYPE, position, data: { kind, params: {} } };
    const c = link.side === "source"
      ? { source: link.node, sourceHandle: link.handle, target: id, targetHandle: link.port }
      : { source: id, sourceHandle: link.port, target: link.node, targetHandle: link.handle };
    set({ nodes: [...s.nodes.map((n) => ({ ...n, selected: false })), node], selectedId: id, picked: [id], pickedByUser: false,
          edges: addEdge({ ...c, id: `${c.source}.${c.sourceHandle}->${c.target}.${c.targetHandle}` }, s.edges) });
    return id;
  },

  applySuggestion: (sug, at) => {
    push();
    const s = get();
    const ids = new Set(s.nodes.map((n) => n.id));
    let id: string | null = null;
    let nodes = s.nodes;
    if (sug.action === "add" && sug.kind) {
      id = newId(sug.kind, ids);
      // 자리 = 유령이 보인 자리(CF6) — 주지 않으면 같은 규칙(`placeSuggestion`: 옆 열 · 겹치면 그 아래 빈 자리)으로 잰다.
      const position = at ?? placeSuggestion(sug, placeNodes(s.nodes), s.catalog);
      nodes = [...s.nodes.map((n) => ({ ...n, selected: false })),
               { id, type: PG_NODE_TYPE, position, data: { kind: sug.kind, params: {} } }];
    }
    let edges = s.edges;
    for (const a of sug.attach) {
      const c = { source: a.source === NEW_NODE ? id! : a.source, sourceHandle: a.source_port,
                  target: a.target === NEW_NODE ? id! : a.target, targetHandle: a.target_port };
      if (!c.source || !c.target) continue;
      edges = addEdge({ ...c, id: `${c.source}.${c.sourceHandle}->${c.target}.${c.targetHandle}` }, edges);
    }
    set({ nodes, edges, ...(id ? { selectedId: id, picked: [id], pickedByUser: false } : {}) });
    return id;
  },

  applyDraft: (d, at) => {
    const s = get();
    const ids = new Set(s.nodes.map((n) => n.id));
    const adding = new Set(d.add.map((a) => a.id));
    if (d.add.some((a) => ids.has(a.id)) || d.set.some((x) => !ids.has(x.node) && !adding.has(x.node))) return null;
    push();
    const sets = new Map<string, DraftSet[]>();
    for (const x of d.set) sets.set(x.node, [...(sets.get(x.node) ?? []), x]);
    const withSets = (id: string, data: PgNodeData): PgNodeData => {
      const mine = sets.get(id);
      if (!mine) return data;
      return { ...data, params: { ...data.params, ...Object.fromEntries(mine.map((x) => [x.field, structuredClone(x.value)])) },
               said: { ...(data.said ?? {}), ...Object.fromEntries(mine.map((x) => [x.field, x.quote])) } };
    };
    const nodes: PgNode[] = [...s.nodes.map((n) => ({ ...n, selected: false, data: withSets(n.id, n.data) })),
                             ...d.add.map((a) => ({ id: a.id, type: PG_NODE_TYPE, position: at[a.id] ?? { x: 0, y: 0 },
                                                    data: withSets(a.id, { kind: a.kind, params: {} }) }))];
    let edges = s.edges;
    for (const c of d.connect)
      edges = addEdge({ id: c.id, source: c.source, sourceHandle: c.source_port, target: c.target, targetHandle: c.target_port }, edges);
    set({ nodes, edges, selectedId: null, selectedEdge: null, picked: [], pickedByUser: false });
    return { added: d.add.length, connected: d.connect.length, set: d.set.length };
  },

  selectEdge: (id) => set((s) => (id ? { selectedEdge: id, tab: "wire", selectedId: null, picked: [], pickedByUser: false }
                                     : { selectedEdge: null, tab: s.tab === "wire" ? "story" : s.tab })),

  insertOnEdge: (edgeId, kind, inPort, outPort, at) => {
    const s = get();
    const e = s.edges.find((x) => x.id === edgeId);
    if (!e) return null;
    push();
    const id = newId(kind, new Set(s.nodes.map((n) => n.id)));
    const a = s.nodes.find((n) => n.id === e.source)?.position;
    const b = s.nodes.find((n) => n.id === e.target)?.position;
    const position = at ?? (a && b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 + 60 } : a ?? { x: 0, y: 0 });
    const node: PgNode = { id, type: PG_NODE_TYPE, position, data: { kind, params: {} } };
    let edges = s.edges.filter((x) => x.id !== edgeId);
    const c1 = { source: e.source, sourceHandle: e.sourceHandle ?? null, target: id, targetHandle: inPort };
    const c2 = { source: id, sourceHandle: outPort, target: e.target, targetHandle: e.targetHandle ?? null };
    edges = addEdge({ ...c1, id: `${c1.source}.${c1.sourceHandle}->${c1.target}.${c1.targetHandle}` }, edges);
    edges = addEdge({ ...c2, id: `${c2.source}.${c2.sourceHandle}->${c2.target}.${c2.targetHandle}` }, edges);
    set({ nodes: [...s.nodes.map((n) => ({ ...n, selected: false })), node], edges, selectedEdge: null, tab: "settings",
          selectedId: id, picked: [id], pickedByUser: false });
    return id;
  },

  addNode: (kind, position) => {
    push();
    const id = newId(kind, new Set(get().nodes.map((n) => n.id)));
    const node: PgNode = { id, type: PG_NODE_TYPE, position, data: { kind, params: {} } };
    set((s) => ({ nodes: [...s.nodes, node], selectedId: id, picked: [id], pickedByUser: false }));
    return id;
  },

  updateParams: (id, params) => {
    const now = Date.now();
    if (!(lastParamEdit && lastParamEdit.id === id && now - lastParamEdit.at < COALESCE_MS)) push();
    lastParamEdit = { id, at: now };
    // 말로 설계(AI4)의 출처 칩은 ★그 칸 값이 그대로일 때만★ — 사람이 고친 칸은 더는 말씀에서 온 값이 아니다(다른 칸은 남는다).
    set((s) => ({
      nodes: s.nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, params, said: keepSaid(n.data.said, n.data.params, params) } } : n)),
    }));
  },

  deleteElements: (nodeIds, edgeIds) => {
    const s = get();
    const ns = new Set(nodeIds.filter((id) => s.nodes.some((n) => n.id === id)));
    const es = new Set(edgeIds.filter((id) => s.edges.some((e) => e.id === id)));
    if (!ns.size && !es.size) return null;
    // 결과가 최신이던 노드 · 지워서 새로 낡은 하류 — 낡음은 set 뒤에 다시 센다(store `derive`). 결과가 없는 노드는 '예전 결과' 가 아니다.
    const fresh = (id: string, st: PgState) => !!st.report?.nodes[id] && !st.staleIds.includes(id);
    const results = [...ns].filter((id) => fresh(id, s)).length;
    push();
    set((st) => pruneRemoved(st, ns, es));
    const after = get();
    const downstream = after.staleIds.filter((id) => fresh(id, s)).length;
    return { nodes: ns.size, edges: es.size, results, downstream };
  },

  duplicateNode: (id) => {
    const src = get().nodes.find((n) => n.id === id);
    if (!src) return null;
    push();
    const nid = newId(src.data.kind, new Set(get().nodes.map((n) => n.id)));
    const node: PgNode = {
      ...src, id: nid, selected: false, position: { x: src.position.x + 36, y: src.position.y + nodeHeight(src.data.kind, get().catalog, src.data.slotH) + ROW_GAP },
      data: { ...src.data, params: structuredClone(src.data.params ?? {}) },
    };
    const incoming = get().edges.filter((e) => e.target === id).map((e) => ({
      ...bare(e), id: `${e.source}.${e.sourceHandle}->${nid}.${e.targetHandle}`, target: nid, selected: false,
    }));
    set((s) => ({ nodes: [...s.nodes, node], edges: [...s.edges, ...incoming], selectedId: nid, picked: [nid] }));
    return nid;
  },

  loadDoc: (doc, problems = []) => {
    const cur = get();
    if (cur.nodes.length) push();
    const { nodes, edges } = fromDoc(doc, cur.catalog ?? []);
    const ids = new Set(nodes.map((n) => n.id));
    const groups = (doc.groups ?? []).map((g) => ({ ...g, members: g.members.filter((m) => ids.has(m)) }))
      .filter((g) => g.members.length);
    set({
      nodes, edges, groups, name: doc.meta?.name ?? "", goal: doc.meta?.goal ?? null, loadProblems: problems, loadSeq: cur.loadSeq + 1,
      report: null, snap: null, validation: null, selectedId: null, picked: [], runError: null,
      pinned: (doc.pinned ?? []).filter((id) => nodes.some((n) => n.id === id)), cause: null, focusGroup: null, filters: [],
      folded: (doc.folded ?? []).filter((id) => nodes.some((n) => n.id === id)),
      branches: (doc.branches ?? []).filter((b) => b.root in b.map),
    });
  },

  setName: (name) => set({ name }),
  setGoal: (goal) => set({ goal }),
  resizeSlot: (id, slotH, record = false) => {
    const n = get().nodes.find((x) => x.id === id);
    if (!n) return false;
    const h = slotHeight(n.data.kind, slotH);
    if (h === slotHeight(n.data.kind, n.data.slotH)) return false;
    if (record) push();
    set((s) => ({ nodes: s.nodes.map((x) => {
      if (x.id !== id) return x;
      const { slotH: _old, ...data } = x.data;
      return { ...x, data: h > slotBase(x.data.kind) ? { ...data, slotH: h } : data };
    }) }));
    return true;
  },
  pickIds: (ids) => {
    if (ids.length <= 1) { get().select(ids[0] ?? null); return; }
    set((s) => ({ picked: ids, pickedByUser: true, selectedId: s.selectedId && ids.includes(s.selectedId) ? s.selectedId : null,
                  ...(s.selectedEdge ? { selectedEdge: null, tab: s.tab === "wire" ? "story" as const : s.tab } : {}) }));
  },
  select: (selectedId) => set((s) => ({ selectedId, picked: selectedId ? [selectedId] : [], pickedByUser: !!selectedId,
                                         ...(selectedId && s.selectedEdge ? { selectedEdge: null, tab: s.tab === "wire" ? "settings" : s.tab } : {}) })),
  togglePin: (id) => set((s) => ({ pinned: s.pinned.includes(id) ? s.pinned.filter((x) => x !== id) : [...s.pinned, id] })),
  toggleFold: (id) => set((s) => ({ folded: s.folded.includes(id) ? s.folded.filter((x) => x !== id) : [...s.folded, id] })),
  setReconnecting: (reconnecting) => set({ reconnecting }),
  reconnect: (oldId, c) => {
    const s = get();
    const old = s.edges.find((e) => e.id === oldId);
    const id = `${c.source}.${c.sourceHandle}->${c.target}.${c.targetHandle}`;
    if (!old || id === oldId) return false;
    push();
    set({ edges: [...s.edges.filter((e) => e.id !== oldId),
                  { ...old, id, source: c.source, target: c.target, sourceHandle: c.sourceHandle, targetHandle: c.targetHandle, selected: false }] });
    return true;
  },
});
