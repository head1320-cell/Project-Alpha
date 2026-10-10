/**
 * 노드 위 도구줄 자리 고르기 (BS2) — 다른 카드를 덮지 않고 떠 있는 판 밑으로 들어가지 않는 자리.
 * ==========================================================================
 * 카드 격자를 촘촘하게 맞춘 뒤(BS2) 한 노드 도구줄('여기까지 계산 · 갈래 만들기 · 그림 고정', 약 400px)이 위 가운데에
 * 뜨면 앞 열 카드를 덮었다 — Ctrl+클릭으로 그 카드를 함께 고를 수 없었다(E2E 가 찾음). 후보 자리를 차례로 보고
 * 덮는 넓이(다른 카드와 겹침 + 캔버스·떠 있는 판 밖으로 나간 넓이)가 가장 작은 자리를 고른다. 같으면 앞 후보(= 예전 자리).
 */
import { Position, type ReactFlowState } from "reactflow";
import { floatInsets } from "./panels";

export type ToolbarAlign = "start" | "center" | "end";
export interface ToolbarPlace { position: Position; align: ToolbarAlign }

type Rect = { l: number; t: number; r: number; b: number };
const area = (a: Rect, b: Rect) =>
  Math.max(0, Math.min(a.r, b.r) - Math.max(a.l, b.l)) * Math.max(0, Math.min(a.b, b.b) - Math.max(a.t, b.t));

/** 후보 순서 — 앞이 예전 자리. `prefer` 쪽(위/아래)을 먼저 본다. */
function candidates(prefer: Position): ToolbarPlace[] {
  const other = prefer === Position.Top ? Position.Bottom : Position.Top;
  const aligns: ToolbarAlign[] = ["center", "start", "end"];
  return [...aligns.map((a) => ({ position: prefer, align: a })), ...aligns.map((a) => ({ position: other, align: a }))];
}

/**
 * `useStore` 선택자로 쓴다 — 결과는 `"top|center"` 같은 글이라 같으면 다시 그리지 않는다.
 * `w`·`h` 는 도구줄의 화면 크기(확대와 무관), `offset` 은 NodeToolbar 의 offset 과 같게.
 */
export function placeToolbar(st: ReactFlowState, ids: string[], w: number, h: number, offset: number,
                             prefer: Position = Position.Top): string {
  const [tx, ty, zoom] = st.transform;
  const box = (id: string): Rect | null => {
    const n = st.nodeInternals.get(id);
    if (!n || n.hidden) return null;
    const p = n.positionAbsolute ?? n.position;
    return { l: p.x * zoom + tx, t: p.y * zoom + ty, r: (p.x + (n.width ?? 0)) * zoom + tx, b: (p.y + (n.height ?? 0)) * zoom + ty };
  };
  const mine = ids.map(box).filter((x): x is Rect => !!x);
  if (!mine.length) return `${prefer}|center`;
  const sel: Rect = { l: Math.min(...mine.map((x) => x.l)), t: Math.min(...mine.map((x) => x.t)),
                      r: Math.max(...mine.map((x) => x.r)), b: Math.max(...mine.map((x) => x.b)) };
  const others: Rect[] = [];
  for (const [id] of st.nodeInternals) {
    if (ids.includes(id)) continue;
    const b = box(id);
    // 틀(그룹·갈래 띠)은 카드가 아니다 — 폭이 아주 넓은 것은 덮어도 누를 것을 가리지 않는다.
    if (b && b.r - b.l < 400 * Math.max(zoom, 0.3)) others.push(b);
  }
  const ins = floatInsets(st.domNode ?? null);
  const view: Rect = { l: ins.left, t: 0, r: st.width - ins.right, b: st.height - ins.bottom };
  let best = `${prefer}|center`, bestCost = Infinity;
  for (const c of candidates(prefer)) {
    const top = c.position === Position.Top ? sel.t - offset - h : sel.b + offset;
    const left = c.align === "center" ? (sel.l + sel.r) / 2 - w / 2 : c.align === "start" ? sel.l : sel.r - w;
    const r: Rect = { l: left, t: top, r: left + w, b: top + h };
    const outside = w * h - area(r, view);
    const cost = others.reduce((s, o) => s + area(r, o), 0) + outside * 4;
    if (cost < bestCost - 0.5) { best = `${c.position}|${c.align}`; bestCost = cost; }
    if (cost <= 0.5) break;
  }
  return best;
}

export function parsePlace(s: string): ToolbarPlace {
  const [p, a] = s.split("|");
  return { position: p as Position, align: a as ToolbarAlign };
}
