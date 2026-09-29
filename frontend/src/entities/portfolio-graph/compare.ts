/**
 * 고른 노드 견고성 비교 (BR R1b) — 비중을 내는 노드 2~4개를 '견고성 비교' 노드의 a·b·c·d 에 잇는다.
 * ==========================================================================
 * 순수 함수 — 무엇을 이을 수 있는지와 왜 안 되는지만 정한다. 노드를 만들고 잇는 것은 store 가 한다.
 * 이어지는 순서는 캔버스 위에서 아래로(같으면 왼쪽부터) — 결과의 '묶음 1·2…' 가 그 순서다.
 */
import type { NodeCatalogEntry } from "./types";

type N = { id: string; position: { x: number; y: number }; data: { kind: string } };

export const COMPARE_KIND = "sleeve_analytics";
export const COMPARE_PORTS = ["a", "b", "c", "d"] as const;

export type CompareCheck =
  | { ok: true; sources: { id: string; handle: string }[] }
  | { ok: false; reason: string };

export function compareTargets(picked: string[], nodes: N[], catalog: NodeCatalogEntry[]): CompareCheck {
  const chosen = picked.map((id) => nodes.find((n) => n.id === id)).filter((n): n is N => !!n);
  if (chosen.length < 2) return { ok: false, reason: "비중을 내는 노드를 둘 이상 골라 주세요." };
  if (chosen.length > COMPARE_PORTS.length) {
    return { ok: false, reason: `넷까지 비교할 수 있어요 — 지금 ${chosen.length}개를 골랐어요.` };
  }
  const out: { id: string; handle: string; x: number; y: number }[] = [];
  const bad: string[] = [];
  for (const n of chosen) {
    const entry = catalog.find((c) => c.type === n.data.kind);
    const port = entry?.outputs.find((o) => o.type === "Weights");
    if (!port) bad.push(entry?.plain_label || entry?.label || n.data.kind);
    else out.push({ id: n.id, handle: port.name, x: n.position.x, y: n.position.y });
  }
  if (bad.length) {
    return { ok: false, reason: `비중을 내는 노드끼리만 비교할 수 있어요 — ${bad.join(", ")}은(는) 비중을 내지 않아요.` };
  }
  out.sort((a, b) => a.y - b.y || a.x - b.x);
  return { ok: true, sources: out.map(({ id, handle }) => ({ id, handle })) };
}
