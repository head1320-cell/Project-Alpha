/**
 * 캔버스 상태 조각 — 배치·묶음·전략·갈래·블록·경유점 (CF 3부 E3 — `store.ts` 에서 옮김 · 동작 불변)
 */
import { addEdge, type Edge } from "@xyflow/react";
import { fromDoc, GRAPH_FORMAT, GRAPH_VERSION, blockFromGroup, branchScope, MAX_BRANCHES, nextBranchLetter, insertDoc, mapLayout, paramDiff, readBlocks, toDoc, writeBlocks, PG_NODE_TYPE, PORTFOLIO_NODE, PORTFOLIO_PORTS, portfolioLane, STRATEGY_COLORS, strategyOutput, compareTargets, COL, COMBINE_W, NODE_W, ROW_GAP, nodeHeight, cardWidth, topoOrder, type GraphBranch, type PgNode } from "@/entities/portfolio-graph";
import { fitLanes } from "@/entities/portfolio-graph/lanes";
import { viaOf } from "@/entities/portfolio-graph/format";
import { alignRects } from "./guides";
import type { PgState } from "./store";
import { uniqueLabel, nextSeq, newId, INSERT_GAP, bare, boxH, COALESCE_MS, type SliceCtx } from "./storeShared";

type LayoutSlice = Pick<PgState, "autoLayout" | "alignPicked" | "addWaypoint" | "moveWaypoint" | "removeWaypoint" | "fitToLanes" | "groupPicked" | "strategyPicked" | "comparePicked" | "addStrategy" | "insertBlock" | "ungroup" | "toggleGroup" | "renameGroup" | "moveGroup" | "setDropGroups" | "applyBoxMembership" | "makeBranch" | "branchPicked" | "removeBranch" | "promoteBranch" | "loadBlocks" | "saveBlock" | "removeBlock">;

/** 같은 상자 이름을 잇달아 고친 때 — 이어 친 글자는 한 단계(R1 · `updateParams` 와 같은 규칙). */
let lastRename: { id: string; at: number } | null = null;

export const layoutSlice = ({ set, get, push }: SliceCtx): LayoutSlice => ({
  autoLayout: () => {
    const s = get();
    if (!s.nodes.length) return;
    push();
    if (s.groups.some((g) => g.kind === "strategy")) {
      // 전략이 있으면 전략마다 한 줄 · 포트폴리오 노드는 오른쪽(BN N1 — 노드와 선만, 레인 없음).
      const pos = mapLayout(s.nodes, s.edges, s.groups, s.catalog);
      set({ nodes: s.nodes.map((n) => (pos.has(n.id) ? { ...n, position: pos.get(n.id)! } : n)) });
      return;
    }
    const order = topoOrder(s.nodes.map((n) => n.id), s.edges);
    const depth = new Map<string, number>();
    for (const id of order) {
      const ins = s.edges.filter((e) => e.target === id).map((e) => (depth.get(e.source) ?? 0) + 1);
      depth.set(id, ins.length ? Math.max(...ins) : 0);
    }
    const cols = new Map<number, PgNode[]>();
    for (const n of s.nodes) cols.set(depth.get(n.id) ?? 0, [...(cols.get(depth.get(n.id) ?? 0) ?? []), n]);
    const pos = new Map<string, { x: number; y: number }>();
    for (const [d, col] of cols) {
      // 같은 깊이는 **지금의 세로 순서**를 지킨다 — 사람이 둔 위아래를 뒤섞지 않는다. 줄은 카드 높이 + 틈(BS2).
      // CF4a — 막힘 사유가 길어 자란 카드는 실제 높이로 쌓는다(카드 높이보다 낮게는 잡지 않는다 — 접은 카드를 펴도 겹치지 않게).
      let top = 0;
      for (const n of col.sort((a, b) => a.position.y - b.position.y)) {
        pos.set(n.id, { x: d * COL, y: top });
        top += boxH(n, s.catalog) + ROW_GAP;
      }
    }
    set({ nodes: s.nodes.map((n) => ({ ...n, position: pos.get(n.id) ?? n.position })) });
  },

  alignPicked: (kind) => {
    const s = get();
    const sel = s.nodes.filter((n) => s.picked.includes(n.id));
    const to = alignRects(sel.map((n) => ({ id: n.id, x: n.position.x, y: n.position.y,
                                           w: n.measured?.width ?? cardWidth(n.data.kind), h: boxH(n, s.catalog) })), kind);
    if (!to.size) return;
    push();
    set({ nodes: s.nodes.map((n) => (to.has(n.id) ? { ...n, position: to.get(n.id)! } : n)) });
  },

  addWaypoint: (edgeId, index, p) => {
    const s = get();
    const e = s.edges.find((x) => x.id === edgeId);
    if (!e) return;
    push();
    const via = [...viaOf(e)];
    via.splice(Math.max(0, Math.min(index, via.length)), 0, { x: p.x, y: p.y });
    set({ edges: s.edges.map((x) => (x.id === edgeId ? { ...x, data: { ...(x.data ?? {}), waypoints: via } } : x)) });
  },

  moveWaypoint: (edgeId, index, p, record) => {
    const s = get();
    const e = s.edges.find((x) => x.id === edgeId);
    if (!e || !viaOf(e)[index]) return;
    if (record) push();
    const via = viaOf(e).map((q, i) => (i === index ? { x: p.x, y: p.y } : q));
    set({ edges: s.edges.map((x) => (x.id === edgeId ? { ...x, data: { ...(x.data ?? {}), waypoints: via } } : x)) });
  },

  removeWaypoint: (edgeId, index) => {
    const s = get();
    const e = s.edges.find((x) => x.id === edgeId);
    if (!e || !viaOf(e)[index]) return;
    push();
    const via = viaOf(e).filter((_, i) => i !== index);
    set({ edges: s.edges.map((x) => (x.id === edgeId ? { ...x, data: { ...(x.data ?? {}), waypoints: via } } : x)) });
  },

  fitToLanes: () => {
    const s = get();
    if (!s.catalog || !s.stages.length) return;
    const byId = new Map(s.nodes.map((n) => [n.id, n]));
    const to = fitLanes(s.nodes.map((n) => ({ id: n.id, kind: n.data.kind, position: n.position })), s.edges, s.catalog, s.stages,
                        (id) => boxH(byId.get(id)!, s.catalog));
    if (!to.size) return;
    push();
    set({ nodes: s.nodes.map((n) => (to.has(n.id) ? { ...n, position: to.get(n.id)! } : n)) });
  },

  groupPicked: (label) => {
    const s = get();
    const ids = s.picked.filter((id) => s.nodes.some((n) => n.id === id));
    if (ids.length < 2) return null;
    push();
    const id = `grp_${Date.now().toString(36)}${nextSeq().toString(36)}`;
    // 한 노드는 한 묶음에만 — 다른 묶음에 있던 노드는 옮겨 온다.
    const groups = s.groups.map((g) => ({ ...g, members: g.members.filter((m) => !ids.includes(m)) }))
      .filter((g) => g.members.length >= 1);
    set({ groups: [...groups, { id, label: label ?? `묶음 ${groups.length + 1}`, members: ids, collapsed: false }] });
    return id;
  },

  strategyPicked: () => {
    const s = get();
    const ids = s.picked.filter((id) => s.nodes.some((n) => n.id === id));
    if (!ids.length) return "전략으로 묶을 노드를 먼저 골라 주세요.";
    const output = strategyOutput(ids, s.nodes, s.edges, s.catalog ?? []);
    if (!output) return "고른 노드에 비중을 내는 노드가 없어요 — 전략은 비중을 내야 포트폴리오에 합칠 수 있어요. 그냥 묶으려면 Ctrl+G 를 써요.";
    push();
    const groups = s.groups.map((g) => ({ ...g, members: g.members.filter((m) => !ids.includes(m)) })).filter((g) => g.members.length);
    const used = new Set(groups.filter((g) => g.kind === "strategy").map((g) => g.color ?? 0));
    const color = [...Array(STRATEGY_COLORS).keys()].find((c) => !used.has(c)) ?? groups.length % STRATEGY_COLORS;
    const label = uniqueLabel(`전략 ${groups.filter((g) => g.kind === "strategy").length + 1}`, groups);
    set({ groups: [...groups, { id: `grp_${Date.now().toString(36)}${nextSeq().toString(36)}`, label, members: ids,
                                collapsed: false, kind: "strategy", color, output }] });
    return `고른 노드 ${ids.length}개를 ‘${label}’로 묶었어요. 포트폴리오에 합치려면 ‘전략 추가’로 전략을 하나 더 넣거나, 비중 출력을 ‘전략 합치기’ 노드에 이어요.`;
  },

  comparePicked: () => {
    const s = get();
    const chk = compareTargets(s.picked, s.nodes, s.catalog ?? []);
    if (!chk.ok) return chk.reason;
    push();
    const id = newId(chk.kind, new Set(s.nodes.map((n) => n.id)));
    const from = s.nodes.filter((n) => chk.sources.some((x) => x.id === n.id));
    const x = Math.max(...from.map((n) => n.position.x)) + COL + (from.some((n) => n.data.kind === PORTFOLIO_NODE) ? COMBINE_W - NODE_W : 0);
    const y = from.reduce((a, n) => a + n.position.y, 0) / from.length;
    const node: PgNode = { id, type: PG_NODE_TYPE, position: { x, y }, data: { kind: chk.kind, params: {} } };
    let edges = s.edges;
    chk.sources.forEach((src) => {
      const c = { source: src.id, sourceHandle: src.handle, target: id, targetHandle: src.port };
      edges = addEdge({ ...c, id: `${c.source}.${c.sourceHandle}->${c.target}.${c.targetHandle}` }, edges);
    });
    set({ nodes: [...s.nodes.map((n) => ({ ...n, selected: false })), node], edges, selectedId: id, picked: [id] });
    return `고른 ${chk.sources.length}개를 ‘${chk.label}’에 이었어요 — 계산하면 같이 무너지는지 보여요.`;
  },

  addStrategy: (src) => {
    const s = get();
    const catalog = s.catalog ?? [];
    push();
    let groups = [...s.groups];
    let nodes = [...s.nodes];
    let edges = [...s.edges];
    let wrapped = "";
    // ① 처음 전략이면 지금 흐름(어느 묶음에도, 포트폴리오 레인에도 없는 노드)을 ‘전략 1’로 묶는다.
    if (!groups.some((g) => g.kind === "strategy")) {
      const lane = portfolioLane(nodes, edges, groups);
      const free = nodes.filter((n) => !groups.some((g) => g.members.includes(n.id)) && !lane.has(n.id)).map((n) => n.id);
      const out = strategyOutput(free, nodes, edges, catalog);
      if (out) {
        const label = uniqueLabel(s.name.trim() || "전략 1", groups);
        groups.push({ id: `grp_${Date.now().toString(36)}${nextSeq().toString(36)}`, label, members: free, collapsed: false,
                      kind: "strategy", color: 0, output: out });
        wrapped = `지금 흐름을 ‘${label}’로 묶고, `;
      }
    }
    // ② 새 전략을 가장 아래 카드의 ★바닥★ 밑에 넣는다(CF1 — 카드 높이가 카탈로그로 정해져 예전 "맨 위 y + 300" 은 겹쳤다).
    const bottom = nodes.length ? Math.max(...nodes.map((n) => n.position.y + nodeHeight(n.data.kind, catalog, n.data.slotH))) : 0;
    const minX = nodes.length ? Math.min(...nodes.map((n) => n.position.x)) : 0;
    const k = groups.filter((g) => g.kind === "strategy").length + 1;
    const ins = insertDoc(src, new Set(nodes.map((n) => n.id)), `s${k}_`, { x: minX, y: nodes.length ? bottom + INSERT_GAP : 0 });
    const added = fromDoc({ format: GRAPH_FORMAT, version: GRAPH_VERSION, nodes: ins.nodes, edges: ins.edges }, catalog);
    nodes = [...nodes, ...added.nodes];
    edges = [...edges, ...added.edges];
    const newIds = added.nodes.map((n) => n.id);
    const output = (src.output && ins.map.get(src.output)) || strategyOutput(newIds, nodes, edges, catalog);
    const used = new Set(groups.filter((g) => g.kind === "strategy").map((g) => g.color ?? 0));
    const color = [...Array(STRATEGY_COLORS).keys()].find((c) => !used.has(c)) ?? k % STRATEGY_COLORS;
    const label = uniqueLabel(src.label, groups);
    groups.push({ id: `grp_${Date.now().toString(36)}${nextSeq().toString(36)}`, label, members: newIds, collapsed: false,
                  kind: "strategy", color, output });
    // ③ 포트폴리오 노드 — 없으면 오른쪽 끝에 만들고, 아직 잇지 않은 전략 출력을 빈 포트에 잇는다.
    let pf = nodes.find((n) => n.data.kind === PORTFOLIO_NODE && !groups.some((g) => g.members.includes(n.id)));
    if (!pf && catalog.some((c) => c.type === PORTFOLIO_NODE)) {
      const maxX = Math.max(...nodes.map((n) => n.position.x));
      const ys = nodes.map((n) => n.position.y);
      pf = { id: newId(PORTFOLIO_NODE, new Set(nodes.map((n) => n.id))), type: PG_NODE_TYPE,
             position: { x: maxX + 320, y: (Math.min(...ys) + Math.max(...ys)) / 2 }, data: { kind: PORTFOLIO_NODE, params: {} } };
      nodes.push(pf);
    }
    let unwired = 0;
    if (pf) {
      const labels = { ...((pf.data.params.labels as Record<string, string>) ?? {}) };
      for (const g of groups.filter((x) => x.kind === "strategy" && x.output)) {
        if (edges.some((e) => e.source === g.output && e.target === pf!.id)) continue;
        const port = PORTFOLIO_PORTS.find((p) => !edges.some((e) => e.target === pf!.id && e.targetHandle === p));
        const outPort = catalog.find((c) => c.type === nodes.find((n) => n.id === g.output)?.data.kind)?.outputs.find((o) => o.type === "Weights")?.name;
        if (!port || !outPort) { unwired += 1; continue; }
        edges.push({ id: `${g.output}.${outPort}->${pf.id}.${port}`, source: g.output!, sourceHandle: outPort, target: pf.id, targetHandle: port });
        labels[port] = g.label;
      }
      const pid = pf.id;
      nodes = nodes.map((n) => (n.id === pid ? { ...n, data: { ...n.data, params: { ...n.data.params, labels } } } : n));
    }
    set({ nodes, edges, groups, selectedId: null, picked: [] });
    if (!output) return `‘${label}’을 넣었어요. 이 전략에는 비중을 내는 노드가 없어 포트폴리오에 잇지 않았어요.`;
    if (unwired) return `${wrapped}‘${label}’을 넣었어요. 포트폴리오 노드의 빈 자리(최대 ${PORTFOLIO_PORTS.length}개)가 없어 ${unwired}개는 잇지 못했어요.`;
    return `${wrapped}‘${label}’을 넣어 ‘전략 합치기’에 이었어요. 계산하면 전략별 몫이 보여요.`;
  },

  insertBlock: (b) => {
    if (b.kind === "strategy") return get().addStrategy({ label: b.label, nodes: b.nodes, edges: b.edges, output: b.output });
    const s = get();
    push();
    const bottom = s.nodes.length ? Math.max(...s.nodes.map((n) => n.position.y + nodeHeight(n.data.kind, s.catalog, n.data.slotH))) : 0;
    const minX = s.nodes.length ? Math.min(...s.nodes.map((n) => n.position.x)) : 0;
    const ins = insertDoc(b, new Set(s.nodes.map((n) => n.id)), "b_", { x: minX, y: s.nodes.length ? bottom + INSERT_GAP : 0 });
    const added = fromDoc({ format: GRAPH_FORMAT, version: GRAPH_VERSION, nodes: ins.nodes, edges: ins.edges }, s.catalog ?? []);
    const label = uniqueLabel(b.label, s.groups);
    set({ nodes: [...s.nodes, ...added.nodes], edges: [...s.edges, ...added.edges], groups: [...s.groups, { id: `grp_${Date.now().toString(36)}${nextSeq().toString(36)}`, label,
                                  members: added.nodes.map((n) => n.id), collapsed: false }] });
    return `‘${label}’ 블록을 넣었어요 — 노드 ${added.nodes.length}개. 필요한 입력을 이어 주세요.`;
  },

  ungroup: (id) => { push(); set((s) => ({ groups: s.groups.filter((g) => g.id !== id) })); },
  toggleGroup: (id) => set((s) => ({ groups: s.groups.map((g) => (g.id === id ? { ...g, collapsed: !g.collapsed } : g)) })),
  renameGroup: (id, label) => {
    const now = Date.now();
    if (!(lastRename && lastRename.id === id && now - lastRename.at < COALESCE_MS)) push();
    lastRename = { id, at: now };
    set((s) => {
      const groups = s.groups.map((g) => (g.id === id ? { ...g, label } : g));
      const g = groups.find((x) => x.id === id);
      // 전략 이름은 포트폴리오 노드의 전략 이름(파라미터)과 같아야 한다 — 이은 포트의 이름을 함께 바꾼다.
      const e = g?.kind === "strategy" && g.output
        ? s.edges.find((x) => x.source === g.output && s.nodes.find((n) => n.id === x.target)?.data.kind === PORTFOLIO_NODE) : undefined;
      if (!e || !e.targetHandle || !label.trim()) return { groups };
      return {
        groups, nodes: s.nodes.map((n) => (n.id === e.target
          ? { ...n, data: { ...n.data, params: { ...n.data.params,
              labels: { ...((n.data.params.labels as Record<string, string>) ?? {}), [e.targetHandle!]: label.trim().slice(0, 40) } } } }
          : n)),
      };
    });
  },
  setDropGroups: (ids) => set((s) => (s.dropGroups.length === ids.length && ids.every((x, i) => x === s.dropGroups[i]) ? {} : { dropGroups: ids })),
  applyBoxMembership: (plan) => {
    const s = get();
    const labelOf = (id: string | null) => s.groups.find((g) => g.id === id)?.label ?? "";
    if (plan.moves.length) {
      set((st) => ({ groups: st.groups.map((g) => {
        const out = new Set(plan.moves.filter((m) => m.from === g.id).map((m) => m.id));
        const add = plan.moves.filter((m) => m.to === g.id).map((m) => m.id);
        return out.size || add.length ? { ...g, members: [...g.members.filter((m) => !out.has(m)), ...add] } : g;
      }).filter((g) => g.members.length > 0) }));                                // 마지막 멤버가 다른 상자로 가면 빈 상자는 없앤다(지우기와 같은 규칙)
    }
    // 안내 — 상자마다 몇 개를 넣고 뺐는지, 그리고 막힌 까닭(지어내지 않고 규칙이 준 문장 그대로).
    const into = new Map<string, number>(), outOf = new Map<string, number>();
    for (const m of plan.moves) {
      if (m.to) into.set(m.to, (into.get(m.to) ?? 0) + 1);
      else if (m.from) outOf.set(m.from, (outOf.get(m.from) ?? 0) + 1);
    }
    const said = [...[...into].map(([g, k]) => `‘${labelOf(g)}’ 상자에 노드 ${k}개를 넣었어요`),
                  ...[...outOf].map(([g, k]) => `‘${labelOf(g)}’ 상자에서 노드 ${k}개를 뺐어요`)];
    const text = [said.length ? `${said.join(" · ")}.` : "", ...[...new Set(plan.blocked.map((b) => b.why))]].filter(Boolean).join(" ");
    return text || null;
  },
  moveGroup: (id, dx, dy, record = false) => {
    const g = get().groups.find((x) => x.id === id);
    if (!g || (!dx && !dy)) return false;
    if (record) push();
    const m = new Set(g.members);
    set((s) => ({ nodes: s.nodes.map((n) => (m.has(n.id) ? { ...n, position: { x: n.position.x + dx, y: n.position.y + dy } } : n)) }));
    return true;
  },

  makeBranch: (rootIdArg, strategyId, picked) => {
    const s = get();
    // 전략째 갈래(BN N2) — 뿌리 = 전략의 흐름 첫 노드, 범위 = 전략 구성원 전부.
    // 고른 노드째 갈래(CF5c) — 같은 규칙: 뿌리 = 고른 것 중 흐름 첫 노드(고른 순서가 아니다), 범위 = 고른 노드만.
    const strat = strategyId ? s.groups.find((g) => g.id === strategyId && g.kind === "strategy") : undefined;
    const want = strat ? strat.members : picked;
    const members = want ? topoOrder(s.nodes.map((n) => n.id), s.edges).filter((id) => want.includes(id)) : null;
    const rootId = members?.[0] ?? rootIdArg;
    const root = s.nodes.find((n) => n.id === rootId);
    if (!root) return "갈래를 만들 노드를 찾지 못했어요.";
    // 갈래의 갈래는 원본 뿌리에 붙인다 — 비교 표가 한 원본을 기준으로 선다.
    const parent = s.branches.find((b) => rootId in b.map);
    const ofRoot = parent ? parent.map[rootId] : rootId;
    // 고른 것은 모두 원본이거나 모두 뿌리와 같은 갈래 안이어야 한다 — 섞이면 어느 쪽 설정을 이을지 정할 수 없다.
    if (picked && members!.some((id) => s.branches.find((b) => id in b.map) !== parent))
      return "고른 노드가 원본과 갈래(또는 서로 다른 갈래)에 섞여 있어요 — 원본에서만, 또는 한 갈래 안에서만 골라 주세요.";
    if (parent && parent.root !== rootId) return "갈래는 뿌리 노드에서만 다시 만들 수 있어요 — 갈래 안의 뿌리(점선 틀의 맨 앞)를 골라 주세요.";
    const letter = nextBranchLetter(ofRoot, s.branches);
    if (!letter) return `한 노드에 갈래는 ${MAX_BRANCHES}개까지예요 — 여러 번 고를수록 우연히 좋아 보이는 쪽을 고를 위험이 커져요. 쓰지 않는 갈래를 지우고 만들어 주세요.`;
    // 갈래 안에서 고른 것은 원본 이름으로 — 범위는 늘 원본 노드다(복제의 설정은 아래 `from` 이 잇는다).
    const scope = branchScope(ofRoot, s.nodes, s.edges, s.groups, s.branches, members?.map((id) => parent?.map[id] ?? id));
    push();
    const taken = new Set(s.nodes.map((n) => n.id));
    const idOf = new Map<string, string>();
    for (const id of scope) {
      let nid = `${id}__${letter.toLowerCase()}`;
      for (let k = 2; taken.has(nid); k++) nid = `${id}__${letter.toLowerCase()}${k}`;
      taken.add(nid);
      idOf.set(id, nid);
    }
    const src = parent ? parent : null;
    // 갈래의 갈래면 그 갈래의 설정을 이어받는다(바꾼 값 위에서 또 바꾼다).
    const from = (orig: string) => (src ? Object.entries(src.map).find(([, o]) => o === orig)?.[0] : undefined) ?? orig;
    const scoped = scope.map((id) => s.nodes.find((n) => n.id === id)!);
    // 갈래마다 한 칸씩 아래로 — 칸 높이 = 복제 범위의 높이(카드 실제 높이까지) + 틀 머리·여백(겹치지 않게).
    const bottomOf = (n: PgNode) => n.position.y + nodeHeight(n.data.kind, s.catalog, n.data.slotH);
    const top = Math.min(...scoped.map((n) => n.position.y));
    const x0 = Math.min(...scoped.map((n) => n.position.x)), x1 = Math.max(...scoped.map((n) => n.position.x)) + NODE_W;
    let bottom = Math.max(...scoped.map(bottomOf));
    // 범위 밖인데 범위의 열·높이 안에 낀 원본 카드(고른 노드째 갈래 — 고른 둘 사이의 노드)도 센다. 안 세면 틀 머리가 그 카드 밑에 깔렸다(CF5c).
    const copiesAll = new Set(s.branches.flatMap((b) => Object.keys(b.map)));
    for (const n of s.nodes)
      if (!scope.includes(n.id) && !copiesAll.has(n.id) && n.position.x < x1 && n.position.x + NODE_W > x0
          && n.position.y >= top && n.position.y < bottom) bottom = Math.max(bottom, bottomOf(n));
    const band = bottom - top + 56 + 2 * 28 + 60;  // 카드 · 틀 머리 · 위아래 여백 · 틈
    const dy = band * (1 + s.branches.filter((b) => b.of_root === ofRoot).length);
    const copies: PgNode[] = scope.map((id) => {
      const base = s.nodes.find((n) => n.id === from(id)) ?? s.nodes.find((n) => n.id === id)!;
      const orig = s.nodes.find((n) => n.id === id)!;
      return { ...orig, id: idOf.get(id)!, selected: false, position: { x: orig.position.x, y: orig.position.y + dy },
               data: { ...orig.data, params: structuredClone(base.data.params ?? {}), said: base.data.said ? { ...base.data.said } : undefined } };
    });
    const inScope = new Set(scope);
    // 안쪽 선은 복제끼리, 밖에서 들어오는 선은 원본과 같이. 밖으로 나가는 선은 잇지 않는다.
    const newEdges: Edge[] = s.edges.filter((e) => inScope.has(e.target)).map((e) => {
      const source = inScope.has(e.source) ? idOf.get(e.source)! : e.source;
      const target = idOf.get(e.target)!;
      return { ...bare(e), id: `${source}.${e.sourceHandle}->${target}.${e.targetHandle}`, source, target, selected: false };
    });
    const branch: GraphBranch = { id: `br_${Date.now().toString(36)}${nextSeq().toString(36)}`, label: `갈래 ${letter}`,
      root: idOf.get(ofRoot)!, of_root: ofRoot, map: Object.fromEntries(scope.map((id) => [idOf.get(id)!, id])) };
    set({ nodes: [...s.nodes, ...copies], edges: [...s.edges, ...newEdges], branches: [...s.branches, branch],
          selectedId: branch.root, picked: [branch.root], tab: "settings" });
    return `‘${branch.label}’를 만들었어요 — 노드 ${scope.length}개를 복제했어요. 설정을 바꾸고 계산하면 원본과 다른 값만 나란히 보여요.`;
  },
  branchPicked: () => {
    const s = get();
    const ok = s.picked.filter((id) => s.nodes.find((n) => n.id === id)?.data.kind !== PORTFOLIO_NODE);
    if (!ok.length) return "포트폴리오 노드는 갈래로 복제하지 않아요 — 계산 노드를 골라 주세요.";
    const before = s.branches.length;
    const msg = get().makeBranch("", undefined, ok);
    return get().branches.length > before && ok.length < s.picked.length ? `${msg} 포트폴리오 노드는 넣지 않았어요.` : msg;
  },
  removeBranch: (id) => {
    const s = get();
    const b = s.branches.find((x) => x.id === id);
    if (!b) return;
    push();
    const ids = new Set(Object.keys(b.map));
    set({ nodes: s.nodes.filter((n) => !ids.has(n.id)), edges: s.edges.filter((e) => !ids.has(e.source) && !ids.has(e.target)),
          branches: s.branches.filter((x) => x.id !== id), selectedId: s.selectedId && ids.has(s.selectedId) ? null : s.selectedId, picked: [] });
  },
  promoteBranch: (id) => {
    const s = get();
    const b = s.branches.find((x) => x.id === id);
    if (!b) return "갈래를 찾지 못했어요.";
    push();
    const copies = new Set(Object.keys(b.map));
    const copyOf = new Map(Object.entries(b.map).map(([c, o]) => [o, c]));
    let moved = 0;
    const nodes = s.nodes.filter((n) => !copies.has(n.id)).map((n) => {
      const c = copyOf.has(n.id) ? s.nodes.find((x) => x.id === copyOf.get(n.id)) : undefined;
      if (!c) return n;
      moved += paramDiff(n.data.params ?? {}, c.data.params ?? {}).length;
      return { ...n, data: { ...n.data, params: structuredClone(c.data.params ?? {}), said: c.data.said ? { ...c.data.said } : undefined } };
    });
    set({ nodes, edges: s.edges.filter((e) => !copies.has(e.source) && !copies.has(e.target)),
          groups: s.groups.map((g) => ({ ...g, members: g.members.filter((m) => !copies.has(m)) })),
          branches: s.branches.filter((x) => x.id !== id), pinned: s.pinned.filter((p) => !copies.has(p)),
          selectedId: s.selectedId && copies.has(s.selectedId) ? null : s.selectedId, picked: [] });
    return moved
      ? `‘${b.label}’의 바꾼 설정 ${moved}개를 원본으로 옮겼어요 — 다시 계산해 주세요. 되돌리기(Ctrl+Z)로 돌아갈 수 있어요.`
      : `‘${b.label}’은 원본과 같아서 옮길 설정이 없었어요 — 갈래만 지웠어요. 되돌리기(Ctrl+Z)로 돌아갈 수 있어요.`;
  },
  loadBlocks: () => { const r = readBlocks(); set({ blocks: r.blocks, blocksAvailable: r.available }); },
  saveBlock: (groupId) => {
    const s = get();
    const g = s.groups.find((x) => x.id === groupId);
    if (!g) return null;
    const block = blockFromGroup(g, toDoc(s.nodes, s.edges, undefined, s.groups));
    const cur = readBlocks();
    const ok = cur.available && writeBlocks([...cur.blocks.filter((b) => b.label !== block.label), block]);
    const r = readBlocks();
    set({ blocks: r.blocks, blocksAvailable: r.available && ok,
          noteUndo: false, noteTransient: false, note: ok ? `‘${g.label}’을 내 블록에 넣었어요 — 이 브라우저에만 있어요. 다른 곳에서 쓰려면 파일로 받아 두세요.`
                   : `이 브라우저에 블록을 저장할 수 없어요 — ‘${g.label}’은 파일로 받아 두세요.` });
    return block;
  },
  removeBlock: (i) => {
    const cur = readBlocks();
    const next = cur.blocks.filter((_, k) => k !== i);
    const ok = writeBlocks(next);
    set({ blocks: ok ? next : cur.blocks, blocksAvailable: ok });
  },
});
