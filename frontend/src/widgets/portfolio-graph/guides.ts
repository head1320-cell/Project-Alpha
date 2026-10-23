/**
 * 끌 때 정렬 안내선 (CF4a, 순수) — 한 카드를 끌 때 다른 카드의 왼·가운데·오른 x / 위·가운데·아래 y 와 문턱 안이면 그 값에 붙이고
 * 맞춘 자리마다 선 하나를 돌려준다. `PortfolioCanvas` 는 끄는 위치를 이 함수로 고치고 선을 그리기만 한다.
 *  · 문턱은 캔버스 좌표로 받는다(화면 6px ÷ 확대율) — 확대와 상관없이 손에 느껴지는 거리가 같다.
 *  · 축마다 가장 가까운 하나만 붙인다(둘이 같으면 앞의 것). 붙지 않은 축은 끄는 위치 그대로다.
 *  · 선은 맞춘 좌표마다 하나 — 끄는 카드와 그 좌표를 가진 카드들을 모두 덮는 길이.
 */
export type Rect = { x: number; y: number; w: number; h: number };
export type Guide = { axis: "x" | "y"; at: number; from: number; to: number };

const anchors = (start: number, size: number) => [start, start + size / 2, start + size];
const SAME = 0.5;

function nearest(moving: number[], others: number[][], threshold: number): number | null {
  let best: number | null = null;
  for (const m of moving) for (const os of others) for (const o of os) {
    const d = o - m;
    if (Math.abs(d) <= threshold && (best === null || Math.abs(d) < Math.abs(best))) best = d;
  }
  return best;
}

export function snapToGuides(moving: Rect, others: Rect[], threshold: number): { x: number; y: number; guides: Guide[] } {
  const dx = nearest(anchors(moving.x, moving.w), others.map((r) => anchors(r.x, r.w)), threshold) ?? 0;
  const dy = nearest(anchors(moving.y, moving.h), others.map((r) => anchors(r.y, r.h)), threshold) ?? 0;
  const m: Rect = { ...moving, x: moving.x + dx, y: moving.y + dy };
  const guides: Guide[] = [];
  const lines = (axis: "x" | "y") => {
    const mine = axis === "x" ? anchors(m.x, m.w) : anchors(m.y, m.h);
    const at = new Map<number, Rect[]>();
    for (const r of others) {
      const theirs = axis === "x" ? anchors(r.x, r.w) : anchors(r.y, r.h);
      for (const a of mine) if (theirs.some((t) => Math.abs(t - a) < SAME)) at.set(a, [...(at.get(a) ?? []), r]);
    }
    for (const [a, rs] of at) {
      const all = [m, ...rs];
      guides.push(axis === "x"
        ? { axis, at: a, from: Math.min(...all.map((r) => r.y)), to: Math.max(...all.map((r) => r.y + r.h)) }
        : { axis, at: a, from: Math.min(...all.map((r) => r.x)), to: Math.max(...all.map((r) => r.x + r.w)) });
    }
  };
  lines("x");
  lines("y");
  return { x: m.x, y: m.y, guides };
}

/** 정렬·간격(CF4a) — 고른 카드들의 새 위치. 간격 맞추기는 셋 이상일 때만(양 끝은 그대로, 사이를 똑같이). */
export type AlignKind = "left" | "center" | "top" | "hspace" | "vspace";
export const ALIGN_ITEMS: { kind: AlignKind; label: string; min: number }[] = [
  { kind: "left", label: "왼쪽 맞추기", min: 2 },
  { kind: "center", label: "가운데 맞추기", min: 2 },
  { kind: "top", label: "위 맞추기", min: 2 },
  { kind: "hspace", label: "가로 간격 똑같이", min: 3 },
  { kind: "vspace", label: "세로 간격 똑같이", min: 3 },
];

export function alignRects(rects: (Rect & { id: string })[], kind: AlignKind): Map<string, { x: number; y: number }> {
  const out = new Map<string, { x: number; y: number }>();
  if (rects.length < (ALIGN_ITEMS.find((i) => i.kind === kind)?.min ?? 2)) return out;
  const minX = Math.min(...rects.map((r) => r.x));
  const maxR = Math.max(...rects.map((r) => r.x + r.w));
  const minY = Math.min(...rects.map((r) => r.y));
  const maxB = Math.max(...rects.map((r) => r.y + r.h));
  if (kind === "left") for (const r of rects) out.set(r.id, { x: minX, y: r.y });
  if (kind === "center") for (const r of rects) out.set(r.id, { x: Math.round((minX + maxR) / 2 - r.w / 2), y: r.y });
  if (kind === "top") for (const r of rects) out.set(r.id, { x: r.x, y: minY });
  if (kind === "hspace" || kind === "vspace") {
    const h = kind === "hspace";
    const sorted = [...rects].sort((a, b) => (h ? a.x - b.x : a.y - b.y));
    const total = sorted.reduce((s, r) => s + (h ? r.w : r.h), 0);
    const gap = ((h ? maxR - minX : maxB - minY) - total) / (sorted.length - 1);
    let at = h ? minX : minY;
    for (const r of sorted) {
      out.set(r.id, h ? { x: Math.round(at), y: r.y } : { x: r.x, y: Math.round(at) });
      at += (h ? r.w : r.h) + gap;
    }
  }
  return out;
}
