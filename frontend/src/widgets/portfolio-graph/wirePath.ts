/**
 * 선 경로 (CF4c, 순수) — 선 모양(곡선 · 직각 · 직선)과 경유점. `EvidenceEdge` 와 끄는 중 선(`WireDragLine`)이 같은 함수를 쓴다.
 *  · 경유점이 없으면 xyflow 의 경로 함수 그대로다(곡선 = 지금 모습 · 직각 = 둥근 모서리 8 · 직선).
 *  · 경유점이 있으면 보내는 손잡이 → 점들 → 받는 손잡이를 구간마다 같은 모양으로 잇는다:
 *    곡선 = 구간마다 가로로 나가 가로로 들어오는 베지어(xyflow 와 같은 휘는 정도) · 직각 = 구간마다 가로→세로→가로 · 직선 = 꺾은선.
 *  · `mid` 는 가운데 구간의 가운데 — 타입 알약이 선 위에 남는다.
 *  · 손잡이 방향(`pos`)은 경유점이 없을 때만 쓴다 — 끄는 중 선은 받는 쪽(왼쪽)에서 끌어 올 수도 있다.
 */
import { Position, getBezierPath, getSmoothStepPath, getStraightPath } from "@xyflow/react";

export type WireShape = "curve" | "step" | "straight";
export const WIRE_SHAPES: { shape: WireShape; label: string }[] = [
  { shape: "curve", label: "곡선" },
  { shape: "step", label: "직각" },
  { shape: "straight", label: "직선" },
];
export const isWireShape = (v: unknown): v is WireShape => WIRE_SHAPES.some((s) => s.shape === v);

export type Pt = { x: number; y: number };
/** 경유점 자리 — 노드 끌기와 같은 11 칸 격자에 놓는다. */
export const snapPt = (p: Pt, g = 11): Pt => ({ x: Math.round(p.x / g) * g, y: Math.round(p.y / g) * g });

/** xyflow `getBezierPath` 의 휘는 정도(curvature 0.25)와 같은 계산 — 경유점 구간도 같은 모양으로 보인다. */
const offset = (d: number) => (d >= 0 ? 0.5 * d : 0.25 * 25 * Math.sqrt(-d));

function segment(shape: WireShape, a: Pt, b: Pt): string {
  if (shape === "straight") return `L${b.x},${b.y}`;
  if (shape === "step") {
    const mx = (a.x + b.x) / 2;
    return `L${mx},${a.y} L${mx},${b.y} L${b.x},${b.y}`;
  }
  const o = offset(b.x - a.x);
  return `C${a.x + o},${a.y} ${b.x - o},${b.y} ${b.x},${b.y}`;
}

export function wirePath(shape: WireShape, s: Pt, t: Pt, via: Pt[] = [],
                         pos: { s: Position; t: Position } = { s: Position.Right, t: Position.Left }): { d: string; mid: Pt } {
  if (!via.length) {
    const p = { sourceX: s.x, sourceY: s.y, targetX: t.x, targetY: t.y, sourcePosition: pos.s, targetPosition: pos.t };
    const [d, x, y] = shape === "step" ? getSmoothStepPath({ ...p, borderRadius: 8 })
      : shape === "straight" ? getStraightPath(p) : getBezierPath(p);
    return { d, mid: { x, y } };
  }
  const pts = [s, ...via, t];
  const d = `M${s.x},${s.y} ` + pts.slice(1).map((b, i) => segment(shape, pts[i], b)).join(" ");
  const k = Math.floor((pts.length - 1) / 2);
  return { d, mid: { x: (pts[k].x + pts[k + 1].x) / 2, y: (pts[k].y + pts[k + 1].y) / 2 } };
}

/** 선 위 한 점을 끼울 자리 — 경유점 목록에서 그 점과 가장 가까운 구간(보내는 쪽 → 점들 → 받는 쪽) 뒤. */
export function insertAt(s: Pt, t: Pt, via: Pt[], p: Pt): number {
  const pts = [s, ...via, t];
  let best = 0, bestD = Infinity;
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    const dx = b.x - a.x, dy = b.y - a.y;
    const len2 = dx * dx + dy * dy || 1;
    const u = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
    const d = Math.hypot(p.x - (a.x + u * dx), p.y - (a.y + u * dy));
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}
