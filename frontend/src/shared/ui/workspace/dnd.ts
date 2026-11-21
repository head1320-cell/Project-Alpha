/**
 * 끌어 놓기의 자리 — 그린 사각형과 포인터 점에서 옮기기 자리(`Target`)와 놓일 자리 표시 사각형을 고른다 (G6 2a-1 · 계획 §9.1)
 * ==========================================================================
 * ★순수 · 결정적★ — 같은 사각형 · 같은 점이면 같은 답(시험 `e2e/ws-layout.spec.ts`). 고른 자리는 판 메뉴와 같은 `move` 로 미리 검사해
 * 놓을 수 없는 자리면 null(표시 없음)이다. 차례: ① 칸 머리의 탭 사이 ② 열의 왼 · 오른 가장자리 15%(새 열) ③ 칸 몸의 위 · 아래 25%(새 칸 —
 * 칸이 하나인 열만) ④ 칸 몸의 나머지(그 칸 끝 탭). 가장자리에서 새 열을 놓을 수 없으면 null — 겨눈 것이 새 열이라 다른 자리로 돌리지 않는다.
 */
import { move, type Layout, type ScreenSpec, type Target } from "./layout";

export type Rect = { x: number; y: number; width: number; height: number };
export type AreaGeo = { col: number; row: number; head: Rect; body: Rect; tabs: { id: string; rect: Rect }[] };
export type Geometry = { cols: Rect[]; areas: AreaGeo[] };
export type Drop = { target: Target; box: Rect };

export const EDGE = 0.15;
export const ZONE = 0.25;

const inside = (r: Rect, p: { x: number; y: number }): boolean => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height;

export function dropAt(geo: Geometry, point: { x: number; y: number }, layout: Layout, id: string, spec: ScreenSpec): Drop | null {
  const ok = (t: Target): boolean => move(layout, id, t, spec).ok;
  for (const a of geo.areas) {
    if (!inside(a.head, point)) continue;
    const others = a.tabs.filter((t) => t.id !== id);
    const index = others.filter((t) => t.rect.x + t.rect.width / 2 < point.x).length;
    const target: Target = { kind: "tab", col: a.col, row: a.row, index };
    if (!ok(target)) return null;
    const last = others[others.length - 1];
    const x = index < others.length ? others[index].rect.x : last ? last.rect.x + last.rect.width : a.head.x + 8;
    return { target, box: { x: x - 1, y: a.head.y + 4, width: 2, height: a.head.height - 8 } };
  }
  for (let c = 0; c < geo.cols.length; c++) {
    const r = geo.cols[c];
    if (!inside(r, point)) continue;
    const left = point.x < r.x + r.width * EDGE;
    const right = point.x > r.x + r.width * (1 - EDGE);
    if (!left && !right) break;
    const target: Target = { kind: "col", index: left ? c : c + 1 };
    if (!ok(target)) return null;
    return { target, box: { x: left ? r.x : r.x + (r.width * 2) / 3, y: r.y, width: r.width / 3, height: r.height } };
  }
  for (const a of geo.areas) {
    if (!inside(a.body, point)) continue;
    if (layout.cols[a.col]?.rows.length === 1) {
      const top = point.y < a.body.y + a.body.height * ZONE;
      const bottom = point.y > a.body.y + a.body.height * (1 - ZONE);
      if (top || bottom) {
        const target: Target = { kind: "row", col: a.col, pos: top ? "top" : "bottom" };
        const half = a.body.height / 2;
        if (ok(target)) return { target, box: { x: a.body.x, y: top ? a.body.y : a.body.y + half, width: a.body.width, height: half } };
      }
    }
    const target: Target = { kind: "tab", col: a.col, row: a.row, index: a.tabs.filter((t) => t.id !== id).length };
    if (!ok(target)) return null;
    return { target, box: { ...a.body } };
  }
  return null;
}
