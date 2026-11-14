/**
 * 카드마다 이은 선의 열쇠 (CF 3부 R8b — 재서 찾음)
 * ==========================================================================
 * 카드(`GraphNode`)는 '나가는 선의 소켓들'·'들어오는 선의 소켓들'을 글자 열쇠로 골라 같은 내용이면 다시 그리지 않는다.
 * 예전에는 카드마다 셀렉터가 선 목록을 통째로 걸렀다 — 스토어가 알릴 때마다 카드 200장 × 선 200개(끌기 한 걸음에 여러 번).
 * 이제 선 목록(배열 그 자체)마다 한 번 색인을 만들고 카드는 제 열쇠만 꺼낸다. 열쇠는 예전 식과 같다:
 * 나가는 = 원천이 이 카드인 선의 `sourceHandle ?? ""` 를 목록 순서대로 "|" 로 · 들어오는 = 받는 쪽이 이 카드인 선의 `targetHandle`
 * (없으면 빈칸 — `join` 과 같다) · 선이 없으면 "". 순수 — 시험이 예전 식과 견준다.
 */
type EdgeLike = { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null };
export interface EdgeKeys { out: Map<string, string>; inn: Map<string, string> }

const memo = new WeakMap<readonly EdgeLike[], EdgeKeys>();

export function edgeKeys(edges: readonly EdgeLike[]): EdgeKeys {
  const hit = memo.get(edges);
  if (hit) return hit;
  const out = new Map<string, (string | null | undefined)[]>();
  const inn = new Map<string, (string | null | undefined)[]>();
  for (const e of edges) {
    let a = out.get(e.source);
    if (!a) out.set(e.source, (a = []));
    a.push(e.sourceHandle ?? "");
    let b = inn.get(e.target);
    if (!b) inn.set(e.target, (b = []));
    b.push(e.targetHandle);
  }
  const v: EdgeKeys = {
    out: new Map([...out].map(([k, xs]) => [k, xs.join("|")])),
    inn: new Map([...inn].map(([k, xs]) => [k, xs.join("|")])),
  };
  memo.set(edges, v);
  return v;
}

export const outKeyOf = (edges: readonly EdgeLike[], id: string) => edgeKeys(edges).out.get(id) ?? "";
export const inKeyOf = (edges: readonly EdgeLike[], id: string) => edgeKeys(edges).inn.get(id) ?? "";
