/**
 * 고른 노드 견고성 비교 (BR R1b · BS3) — 고른 노드 2~4개를 비교 노드에 잇는다.
 * ==========================================================================
 * 순수 함수 — 무엇을 이을 수 있는지와 왜 안 되는지만 정한다. 노드를 만들고 잇는 것은 store 가 한다.
 * - 비중(Weights)을 내는 노드끼리 → '견고성 비교'(`sleeve_analytics`) a·b·c·d
 * - 기록(BacktestRun · BacktestResult)을 내는 노드끼리 → '기록끼리 견고성'(`record_robustness`) r1~r4 · t1~t2 (BS3)
 * - 둘이 섞이면 잇지 않고 사유 — 비중의 '들고 있었다면' 흐름과 기록은 같은 것이 아니다.
 * 이어지는 순서는 캔버스 위에서 아래로(같으면 왼쪽부터) — 결과의 '묶음 1·2…' 가 그 순서다.
 */
import type { NodeCatalogEntry } from "./types";

type N = { id: string; position: { x: number; y: number }; data: { kind: string } };

export const COMPARE_KIND = "sleeve_analytics";
export const COMPARE_PORTS = ["a", "b", "c", "d"] as const;
export const RECORD_KIND = "record_robustness";
export const RECORD_PORTS = { BacktestRun: ["r1", "r2", "r3", "r4"], BacktestResult: ["t1", "t2"] } as const;
const RECORD_TYPES = Object.keys(RECORD_PORTS) as (keyof typeof RECORD_PORTS)[];

export type CompareCheck =
  | { ok: true; kind: string; label: string; sources: { id: string; handle: string; port: string }[] }
  | { ok: false; reason: string };

export function compareTargets(picked: string[], nodes: N[], catalog: NodeCatalogEntry[]): CompareCheck {
  const chosen = picked.map((id) => nodes.find((n) => n.id === id)).filter((n): n is N => !!n);
  if (chosen.length < 2) return { ok: false, reason: "비중이나 기록을 내는 노드를 둘 이상 골라 주세요." };
  if (chosen.length > COMPARE_PORTS.length) {
    return { ok: false, reason: `넷까지 비교할 수 있어요 — 지금 ${chosen.length}개를 골랐어요.` };
  }
  type Row = { id: string; handle: string; type: string; x: number; y: number };
  const rows: Row[] = [];
  const bad: string[] = [];
  for (const n of chosen) {
    const entry = catalog.find((c) => c.type === n.data.kind);
    const port = entry?.outputs.find((o) => o.type === "Weights")
      ?? entry?.outputs.find((o) => (RECORD_TYPES as string[]).includes(o.type));
    if (!port) bad.push(entry?.plain_label || entry?.label || n.data.kind);
    else rows.push({ id: n.id, handle: port.name, type: port.type, x: n.position.x, y: n.position.y });
  }
  if (bad.length) {
    return { ok: false, reason: `비중이나 기록을 내는 노드끼리만 비교할 수 있어요 — ${bad.join(", ")}은(는) 둘 다 내지 않아요.` };
  }
  rows.sort((a, b) => a.y - b.y || a.x - b.x);
  const weights = rows.filter((r) => r.type === "Weights");
  if (weights.length && weights.length < rows.length) {
    return { ok: false, reason: "비중과 기록은 따로 비교해요 — 비중은 '들고 있었다면'의 흐름이고 기록은 이미 있는 곡선이라 같은 것이 아니에요." };
  }
  if (weights.length) {
    return { ok: true, kind: COMPARE_KIND, label: "견고성 비교",
             sources: rows.map((r, i) => ({ id: r.id, handle: r.handle, port: COMPARE_PORTS[i] })) };
  }
  const used: Record<string, number> = {};
  const sources: { id: string; handle: string; port: string }[] = [];
  for (const r of rows) {
    const slots = RECORD_PORTS[r.type as keyof typeof RECORD_PORTS];
    const k = used[r.type] ?? 0;
    if (k >= slots.length) {
      return { ok: false, reason: r.type === "BacktestResult"
        ? "정책 백테스트 결과는 둘까지 비교할 수 있어요." : "백테스트 실행은 넷까지 비교할 수 있어요." };
    }
    used[r.type] = k + 1;
    sources.push({ id: r.id, handle: r.handle, port: slots[k] });
  }
  return { ok: true, kind: RECORD_KIND, label: "기록끼리 견고성", sources };
}
