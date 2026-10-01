/**
 * 선 잇기 규칙(BT4) — ★거부를 말한다★
 * ==========================================================================
 * 끌어 잇기·"어디서 받을까요" 고르기·끄는 동안의 강조가 모두 같은 규칙을 쓴다. 규칙은 예전과 같다(타입 일치 · 입력 하나에
 * 선 하나 · 고리 금지). 달라진 것은 안 될 때 **왜 안 되는지 사람 말로** 돌려준다는 것이다(예전엔 조용히 거부했다).
 * 받는 쪽 요구값(`needs`)은 서버가 판정한다(`/validate` 의 `needs_unmet`) — 여기서는 보내는 쪽이 그 값을 **전혀 선언하지
 * 않은** 경우만 미리 표시한다(`needsGap`). 조건부로 줄 수 있으면 막지 않는다.
 */
import type { CatalogPort, NodeCatalogEntry } from "./types";

export interface ConnNode { id: string; data: { kind: string } }
export interface ConnEdge { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }
export interface ConnTry { source: string | null; sourceHandle: string | null; target: string | null; targetHandle: string | null }

function obj(word: string): string {
  const ch = [...word].reverse().find((c) => c >= "가" && c <= "힣");
  return `‘${word}’${ch && (ch.charCodeAt(0) - 0xac00) % 28 ? "은" : "는"}`;
}

/** 이을 수 없으면 사람 말 사유, 이을 수 있으면 null. */
export function connectionProblem(c: ConnTry, nodes: ConnNode[], edges: ConnEdge[], catalog: NodeCatalogEntry[],
                                  plain: Record<string, string>): string | null {
  if (!c.source || !c.target) return "잇는 두 끝을 찾지 못했어요.";
  if (c.source === c.target) return "노드를 자기 자신에게 이을 수 없어요.";
  const entry = (id: string) => catalog.find((x) => x.type === nodes.find((n) => n.id === id)?.data.kind);
  const out = entry(c.source)?.outputs.find((p) => p.name === c.sourceHandle);
  const inp = entry(c.target)?.inputs.find((p) => p.name === c.targetHandle);
  if (!out || !inp) return "없는 자리예요 — 카탈로그에 없는 포트예요.";
  const nm = (p: CatalogPort) => plain[p.type] ?? p.type;
  if (out.type !== inp.type) return `${obj(nm(out))} ‘${nm(inp)}’ 자리에 이을 수 없어요 — 같은 색 점끼리 이어요.`;
  const taken = edges.find((e) => e.target === c.target && e.targetHandle === c.targetHandle);
  if (taken) {
    const who = entry(taken.source)?.plain_label ?? taken.source;
    return `이 자리에는 이미 ‘${who}’가 이어져 있어요 — 입력 하나에는 선 하나만 이어요.`;
  }
  const seen = new Set<string>();
  const stack = [c.target];
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === c.source) return "이으면 고리가 생겨요 — 계산 순서를 정할 수 없어요.";
    if (seen.has(cur)) continue;
    seen.add(cur);
    edges.filter((e) => e.source === cur).forEach((e) => stack.push(e.target));
  }
  return null;
}

/** 받는 쪽이 요구하는 값을 보내는 쪽이 전혀 선언하지 않았으면 그 값 키들(미리 표시용 — 판정은 서버). */
export function needsGap(out: CatalogPort | undefined, inp: CatalogPort | undefined): string[] {
  if (!out || !inp?.needs?.length) return [];
  return inp.needs.filter((k) => !(out.gives ?? []).some((g) => g.key === k));
}

/** 이 입력에 이을 수 있는 (노드, 출력) — "어디서 받을까요" 고르기에 쓴다. */
export function sourcesFor(targetId: string, port: CatalogPort, nodes: ConnNode[], edges: ConnEdge[],
                           catalog: NodeCatalogEntry[], plain: Record<string, string>): { node: string; port: string; label: string }[] {
  const others = edges.filter((e) => !(e.target === targetId && e.targetHandle === port.name));
  return nodes.flatMap((n) => {
    const e = catalog.find((x) => x.type === n.data.kind);
    return (e?.outputs ?? []).filter((o) => o.type === port.type)
      .filter((o) => !connectionProblem({ source: n.id, sourceHandle: o.name, target: targetId, targetHandle: port.name },
                                        nodes, others, catalog, plain))
      .map((o) => ({ node: n.id, port: o.name, label: e?.plain_label ?? n.data.kind }));
  });
}
