/**
 * 캔버스 상태 조각 — 보기 (CF 3부 E3 — `store.ts` 에서 옮김 · 동작 불변)
 */
import type { PgState } from "./store";
import type { SliceCtx } from "./storeShared";

type ViewSlice = Pick<PgState, "setFocusGroup" | "toggleFilter" | "setSimple" | "setGrowing" | "setMinimap" | "setLanes" | "setWireShape" | "setShowGhosts" | "setTab" | "setExpert" | "setOpenGate">;

export const viewSlice = ({ set }: SliceCtx): ViewSlice => ({
  setFocusGroup: (focusGroup) => set((s) => ({
    focusGroup,
    groups: focusGroup ? s.groups.map((g) => (g.id === focusGroup ? { ...g, collapsed: false } : g)) : s.groups,
  })),
  toggleFilter: (k) => set((s) => ({ filters: s.filters.includes(k) ? s.filters.filter((x) => x !== k) : [...s.filters, k] })),
  setSimple: (simple) => set({ simple }),
  setGrowing: (growing) => set({ growing }),
  setMinimap: (showMinimap) => set({ showMinimap }),
  setLanes: (showLanes) => set({ showLanes }),
  setWireShape: (wireShape) => set({ wireShape }),
  setShowGhosts: (showGhosts) => set({ showGhosts }),
  setTab: (tab) => set({ tab }),
  setExpert: (expert) => set({ expert }),
  setOpenGate: (openGate) => set({ openGate }),
});
