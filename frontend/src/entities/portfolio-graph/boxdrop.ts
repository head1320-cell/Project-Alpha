/**
 * 상자에 끌어 넣기·빼기 (CF 3부 R4 — 사용자 결정 "넣기·빼기 모두 끌어서")
 */
import type { GraphGroup, NodeCatalogEntry } from "./types";
import { GROUP_PAD, NODE_W, nodeHeight } from "./size";
import { PORTFOLIO_NODE } from "./strategy";

type N = { id: string; position: { x: number; y: number }; data: { kind: string; slotH?: number } };
export interface FrameRect { x0: number; y0: number; x1: number; y1: number }
/** 상자 머리 높이 — 묶음·전략 상자 30 · 갈래 틀 56(설정 차이 칩 줄). */
export const FRAME_HEAD = 30;
export const BRANCH_HEAD = 56;

/** 카드 한 장의 자리(캔버스 좌표) — 폭 240 · 높이는 늘린 결과 칸까지(`nodeHeight`). */
const cardRect = (n: N, catalog: NodeCatalogEntry[] | null | undefined): FrameRect =>
  ({ x0: n.position.x, y0: n.position.y, x1: n.position.x + NODE_W, y1: n.position.y + nodeHeight(n.data.kind, catalog, n.data.slotH) });

/** 상자·갈래 테두리 — 멤버 카드 둘레 + 여백 · 위로 머리. 멤버가 없으면 null. 캔버스 상자 그림과 끌어 넣기 판단이 같은 것을 쓴다. */
export function frameRect(ms: N[], catalog: NodeCatalogEntry[] | null | undefined, head = FRAME_HEAD): FrameRect | null {
  if (!ms.length) return null;
  const rs = ms.map((n) => cardRect(n, catalog));
  return { x0: Math.min(...rs.map((r) => r.x0)) - GROUP_PAD, y0: Math.min(...rs.map((r) => r.y0)) - GROUP_PAD - head,
           x1: Math.max(...rs.map((r) => r.x1)) + GROUP_PAD, y1: Math.max(...rs.map((r) => r.y1)) + GROUP_PAD };
}

export interface BoxMove { id: string; from: string | null; to: string | null }
export interface BoxPlan { moves: BoxMove[]; blocked: { id: string; why: string }[] }

/** 넣을 상자로 보는 겹침 — 카드 넓이의 절반 이상. */
export const JOIN_SHARE = 0.5;

const area = (r: FrameRect) => Math.max(0, r.x1 - r.x0) * Math.max(0, r.y1 - r.y0);
const meet = (a: FrameRect, b: FrameRect): FrameRect =>
  ({ x0: Math.max(a.x0, b.x0), y0: Math.max(a.y0, b.y0), x1: Math.min(a.x1, b.x1), y1: Math.min(a.y1, b.y1) });

/**
 * 끈 노드를 어느 상자에 넣고 뺄지 — 상자 그림은 끄는 동안 멤버를 따라 커지므로 ★끌기 시작 자리(`start`)의 상자★로 판단한다.
 *  · 넣기: 지금 카드(`now`) 넓이의 절반 이상이 다른 상자(끈 노드를 뺀 나머지 멤버 테두리) 안 — 여럿이면 가장 많이 겹친 상자.
 *    대상은 펼친 상자만, 들어간 상자가 있으면 그 상자만. 한 노드는 한 상자 — 넣으면 옛 상자에서 빠진다.
 *  · 빼기: 끌기 전 제 상자 테두리(자신 포함) 밖으로 ★완전히★ 나갔을 때만 — 가장자리 멤버를 조금 밀어도 빠지지 않는다.
 *    상자 멤버를 다 끌었으면 상자째 옮긴 것이다.
 *  · 막힘: 전략의 비중을 내는 노드는 상자를 떠날 수 없고, 전략을 합치는 노드는 전략 상자에 들 수 없다 — 까닭을 돌려준다.
 */
export function boxDropPlan(dragIds: string[], now: N[], start: N[], groups: GraphGroup[],
                            catalog: NodeCatalogEntry[] | null | undefined, focusGroup: string | null): BoxPlan {
  const drag = new Set(dragIds);
  const startOf = (g: GraphGroup, exclude: Set<string>) =>
    frameRect(start.filter((n) => g.members.includes(n.id) && !exclude.has(n.id)), catalog);
  const targets = groups.filter((g) => (focusGroup ? g.id === focusGroup : !g.collapsed));
  const moves: BoxMove[] = [];
  const blocked: { id: string; why: string }[] = [];
  for (const d of now.filter((n) => drag.has(n.id))) {
    const own = groups.find((g) => g.members.includes(d.id)) ?? null;
    const r = cardRect(d, catalog);
    let best: { g: GraphGroup; share: number } | null = null;
    for (const g of targets) {
      if (g === own) continue;
      const f = startOf(g, drag);
      const share = f ? area(meet(r, f)) / area(r) : 0;
      if (share >= JOIN_SHARE && (!best || share > best.share)) best = { g, share };
    }
    const output = !!own && own.kind === "strategy" && own.output === d.id;
    const keep = `‘${own?.label ?? ""}’의 비중을 내는 노드라 상자 밖으로 뺄 수 없어요.`;
    if (best) {
      if (d.data.kind === PORTFOLIO_NODE && best.g.kind === "strategy") {
        blocked.push({ id: d.id, why: `전략을 합치는 노드라 ‘${best.g.label}’ 같은 전략 상자에 넣을 수 없어요.` });
      } else if (output) blocked.push({ id: d.id, why: keep });
      else moves.push({ id: d.id, from: own?.id ?? null, to: best.g.id });
      continue;
    }
    if (!own || own.members.every((m) => drag.has(m))) continue;
    const f = startOf(own, new Set());
    if (!f || area(meet(r, f)) > 0) continue;
    if (output) blocked.push({ id: d.id, why: keep });
    else moves.push({ id: d.id, from: own.id, to: null });
  }
  return { moves, blocked };
}
