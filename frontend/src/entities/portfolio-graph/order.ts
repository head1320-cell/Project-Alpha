/**
 * 그래프 순서 — 노드 번호와 이야기 순서의 단일 출처 (BJ2·BJ3).
 * 칸 알고리즘, 동률은 목록 순서(서버 `portfolio_graph._topo` 와 같은 규칙). 순환이 있으면
 * 순서를 정할 수 없는 노드는 뒤에 목록 순서대로 붙인다(화면이 사라지지 않게) — 순환 자체는
 * 서버 검증이 오류로 말한다.
 */
export function topoOrder(ids: string[], edges: { source: string; target: string }[]): string[] {
  const rank = new Map(ids.map((id, i) => [id, i]));
  const indeg = new Map(ids.map((id) => [id, 0]));
  const adj = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const e of edges) {
    if (!rank.has(e.source) || !rank.has(e.target)) continue;
    adj.get(e.source)!.push(e.target);
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
  }
  const byRank = (a: string, b: string) => rank.get(a)! - rank.get(b)!;
  const ready = ids.filter((id) => indeg.get(id) === 0).sort(byRank);
  const out: string[] = [];
  while (ready.length) {
    const n = ready.shift()!;
    out.push(n);
    for (const t of [...adj.get(n)!].sort(byRank)) {
      indeg.set(t, indeg.get(t)! - 1);
      if (indeg.get(t) === 0) { ready.push(t); ready.sort(byRank); }
    }
  }
  return [...out, ...ids.filter((id) => !out.includes(id))];
}
