/**
 * 보기 설정(CF4b·CF4c·CF5b) — 단계 레인 켬/끔 · 선 모양 · 미니맵 켬/끔. ★이 브라우저에만★ 남는 편의 상태(localStorage) — 문서·서버에는 가지 않는다.
 * 못 읽거나 망가졌으면 기본값(레인 끔 · 곡선 = 지금 모습 · 미니맵 끔 — 켜 두면 구석의 카드를 덮어 누를 수 없었다).
 */
import { isWireShape, type WireShape } from "./wirePath";

export const VIEW_KEY = "alpha_pg_view";

export interface View {
  lanes: boolean;
  wire: WireShape;
  minimap: boolean;
}
export const DEFAULT_VIEW: View = { lanes: false, wire: "curve", minimap: false };

export function readView(): View {
  try {
    const raw = typeof window === "undefined" ? null : localStorage.getItem(VIEW_KEY);
    if (!raw) return DEFAULT_VIEW;
    const v = JSON.parse(raw) as Partial<View>;
    return {
      lanes: typeof v.lanes === "boolean" ? v.lanes : DEFAULT_VIEW.lanes,
      wire: isWireShape(v.wire) ? v.wire : DEFAULT_VIEW.wire,
      minimap: typeof v.minimap === "boolean" ? v.minimap : DEFAULT_VIEW.minimap,
    };
  } catch {
    return DEFAULT_VIEW;
  }
}

export function saveView(v: View) {
  try { localStorage.setItem(VIEW_KEY, JSON.stringify(v)); }
  catch { /* 적을 수 없으면 이번 방문에만 */ }
}
