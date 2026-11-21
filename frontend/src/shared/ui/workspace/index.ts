/**
 * 판 배치(작업 공간 2단계 · G6) — 화면이 쓰는 것. 순수 규칙은 `layout.ts` · `dnd.ts`(시험 `e2e/ws-layout.spec.ts`).
 * 화면은 판 목록과 처음 배치(`ScreenSpec`)를 정하고, 판 내용을 `Workspace` 의 `render` 로 준다. 배치 관리 시트는 판 배치를 끄고 켜도 같은 자리에 두도록 화면이 그린다.
 */
export { Workspace, type WorkspaceApi } from "./Workspace";
export { LayoutMenu, openId, refocusOpen } from "./LayoutMenu";
export { LayoutSheet } from "./LayoutSheet";
export { useWorkspace, keysOf, type WorkspaceState } from "./useWorkspace";
export { useWorkWidth } from "./useWorkWidth";
export type { Layout, PanelSpec, Preset, ScreenSpec } from "./layout";
