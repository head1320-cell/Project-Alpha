/**
 * 노드별 "예전 결과" (BT5) — ★바뀐 곳과 그 하류만 낡는다★
 * ==========================================================================
 * 계산이 끝날 때 노드마다 **깊은 서명**을 남긴다: 종류 + 설정 + 들어오는 선(받는 자리 ← 보내는 자리 @ 보낸 노드의 깊은 서명).
 * 지금 그래프의 깊은 서명이 계산 때와 다르면 그 노드의 결과는 지금 그래프의 결과가 아니다.
 *
 * - 하류는 따로 계산하지 않는다 — 위에서 무엇이 바뀌면 아래 노드의 서명이 함께 바뀐다(머클 사슬). 그래서 부분 계산으로 위만
 *   다시 계산해도, 그 전 값으로 계산한 아래 노드는 계속 낡은 것으로 남는다(단순 "바뀐 것 + 하류" 규칙은 이것을 놓친다).
 * - 위치·묶음 상자·이름은 계산에 끼지 않으므로 서명에 넣지 않는다(예전처럼 옮기기는 결과를 낡게 하지 않는다).
 * - 되돌리기로 계산 때 그래프로 돌아가면 서명이 같아져 낡음이 풀린다 — 결과가 정확히 그 그래프의 것이기 때문이다.
 * - 결과가 없는 노드(새로 붙인 노드)는 "낡음"이 아니라 "아직 계산 안 함"이다 — 여기서 세지 않는다.
 */

export interface SigNode { id: string; data: { kind: string; params?: Record<string, unknown> | null } }
export interface SigEdge { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }

/** 키 순서와 무관한 JSON — 같은 설정이면 같은 글자. */
export function stableJson(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stableJson).join(",")}]`;
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o).filter((k) => o[k] !== undefined).sort().map((k) => `${JSON.stringify(k)}:${stableJson(o[k])}`).join(",")}}`;
  }
  return JSON.stringify(v ?? null);
}

/** 짧은 해시(FNV-1a 32비트 두 번) — 서명 글자가 사슬 길이만큼 자라지 않게. 충돌은 화면 표시에만 영향이 있다. */
function hash(s: string): string {
  let a = 0x811c9dc5, b = 0x01000193 ^ s.length;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    a = Math.imul(a ^ c, 0x01000193);
    b = Math.imul(b ^ c, 0x5bd1e995);
  }
  return (a >>> 0).toString(36) + (b >>> 0).toString(36);
}

/** 노드마다 깊은 서명. 고리는 그래프가 막지만, 만나면 "cycle" 로 끊는다(무한 재귀 없음). */
export function deepSigs(nodes: SigNode[], edges: SigEdge[]): Record<string, string> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const inc = new Map<string, SigEdge[]>();
  for (const e of edges) {
    const list = inc.get(e.target);
    if (list) list.push(e); else inc.set(e.target, [e]);
  }
  const memo: Record<string, string> = {};
  const visiting = new Set<string>();
  const sig = (id: string): string => {
    if (memo[id]) return memo[id];
    if (visiting.has(id)) return "cycle";
    visiting.add(id);
    const n = byId.get(id);
    const ins = (inc.get(id) ?? [])
      .map((e) => `${e.targetHandle ?? ""}<${e.sourceHandle ?? ""}@${byId.has(e.source) ? sig(e.source) : "missing"}`)
      .sort();
    visiting.delete(id);
    return (memo[id] = hash(`${n?.data.kind ?? "?"}|${stableJson(n?.data.params ?? {})}|${ins.join(",")}`));
  };
  for (const n of nodes) sig(n.id);
  return memo;
}

/** 결과가 있는데 계산 때 서명과 지금 서명이 다른 노드 — 그래프 순서대로. */
export function staleNodes(nodes: SigNode[], edges: SigEdge[], results: Record<string, unknown> | null | undefined,
                           snap: Record<string, string> | null | undefined): string[] {
  if (!results || !snap) return [];
  const now = deepSigs(nodes, edges);
  return nodes.map((n) => n.id).filter((id) => id in results && snap[id] !== now[id]);
}
