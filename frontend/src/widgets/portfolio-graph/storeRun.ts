/**
 * 캔버스 상태 조각 — 검증·계산·안내 (CF 3부 E3 — `store.ts` 에서 옮김 · 동작 불변)
 */
import { deepSigs } from "@/entities/portfolio-graph/staleness";
import type { PgState } from "./store";
import { RUNS, causePath, waitingFor, record, type SliceCtx } from "./storeShared";

type RunSlice = Pick<PgState, "setValidation" | "setValidationError" | "setProcHover" | "setCatalogMeta" | "startRun" | "finishRun" | "applyRunEvent" | "progressLost" | "setPreview" | "setStages" | "showCause" | "setNote" | "act">;

export const runSlice = ({ set, get }: SliceCtx): RunSlice => ({
  setValidation: (validation) => set({ validation, validationError: false }),
  setValidationError: (validationError) => set({ validationError }),
  setProcHover: (procHover) => set({ procHover }),
  setCatalogMeta: (catalogMeta) => set({ catalogMeta }),
  startRun: (ids = null) => set((s) => ({ running: true, runError: null, runningIds: ids, preview: null, cause: null,
                                          progress: waitingFor(ids ?? s.nodes.map((n) => n.id)),
                                          runSigs: deepSigs(s.nodes, s.edges) })),
  finishRun: (report, err = null) => set((s) => {
    if (!report) return { running: false, runningIds: null, runError: err, runSigs: null,
                          progress: s.progress && { ...s.progress, final: true } };
    const partial = report.partial?.targets ?? null;
    let merged = report;
    if (partial && s.report) {
      // ★이번에 계산하지 않은 노드는 이전 결과를 "이전 계산" 으로 남긴다 — 지금 값처럼 보이지 않는다.
      const prev = Object.fromEntries(Object.entries(s.report.nodes)
        .filter(([id]) => !(id in report.nodes) && s.nodes.some((n) => n.id === id))
        .map(([id, r]) => [id, { ...r, previous: true }]));
      // 선 기록(CF3b2)도 같다 — 이번에 다시 계산하지 않은 받는 쪽의 전달 점검·관계 문장은 예전 계산의 것을 남긴다.
      const kept = new Set(s.edges.map((e) => e.id));
      const prevEdges = Object.fromEntries(Object.entries(s.report.edges ?? {})
        .filter(([id, r]) => kept.has(id) && !(r.target in report.nodes)));
      const prevRel = Object.fromEntries(Object.entries(s.report.relations ?? {})
        .filter(([id]) => kept.has(id) && !((s.edges.find((e) => e.id === id)?.source ?? "") in report.nodes)));
      merged = { ...report, nodes: { ...prev, ...report.nodes }, edges: { ...prevEdges, ...(report.edges ?? {}) },
                 relations: { ...(report.relations ?? {}), ...prevRel } };
    }
    // 서명: 이번에 계산한 노드는 계산을 시작할 때의 서명으로, 계산하지 않은 노드는 예전 서명 그대로(BT5 — 부분 계산 뒤에도
    // 계산하지 않은 낡은 노드는 계속 낡은 것으로 남는다).
    const sigs = s.runSigs ?? deepSigs(s.nodes, s.edges);
    const fresh = Object.fromEntries(Object.keys(report.nodes).map((id) => [id, sigs[id]]));
    const order = report.partial?.computed ?? report.order ?? Object.keys(report.nodes);
    return {
      running: false, runningIds: null, runError: err, runSigs: null,
      progress: { order, lost: s.progress?.lost ?? false, final: true,
                  cells: Object.fromEntries(order.filter((id) => report.nodes[id]).map((id) =>
                    [id, { phase: "done" as const, status: report.nodes[id].status, elapsed_ms: report.nodes[id].elapsed_ms ?? null }])) },
      report: merged,
      snap: partial && s.report ? { ...(s.snap ?? {}), ...fresh } : fresh,
      runs: [record(report, partial), ...s.runs].slice(0, RUNS),
    };
  }),
  applyRunEvent: (ev) => set((s) => {
    const p = s.progress;
    if (!p || p.final) return {};
    if (ev.type === "plan") return { progress: { ...p, order: ev.order, cells: Object.fromEntries(ev.order.map((id) => [id, p.cells[id] ?? { phase: "waiting" as const }])) } };
    if (ev.type === "node_start") return { progress: { ...p, cells: { ...p.cells, [ev.id]: { phase: "running" } } } };
    if (ev.type === "node_done") return { progress: { ...p, cells: { ...p.cells, [ev.id]: { phase: "done", status: ev.status, elapsed_ms: ev.elapsed_ms } } } };
    return {};
  }),
  progressLost: () => set((s) => (s.progress && !s.progress.final ? { progress: { ...s.progress, lost: true } } : {})),
  setPreview: (preview) => set({ preview }),
  setStages: (stages) => set({ stages }),
  showCause: (id) => set((s) => {
    if (!id || s.staleIds.includes(id)) return { cause: null };       // 위가 낡았으면 이 노드도 낡았다(서명 사슬)
    const { path, roots } = causePath(id, s.edges, s.report?.nodes);
    return { cause: path.length ? { from: id, path, roots } : null };
  }),

  setNote: (note, undoable = false, transient = false) => set({ note, noteUndo: !!note && undoable, noteTransient: !!note && transient }),
  act: (fn) => {
    const before = get().undoSeq;
    const note = fn();
    set({ note, noteUndo: get().undoSeq > before, noteTransient: false });
  },
});
