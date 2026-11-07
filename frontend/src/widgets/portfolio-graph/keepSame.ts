/**
 * 값이 같으면 앞의 객체를 그대로 (CF 3부 R8 — 재서 찾음).
 * 캔버스는 스토어가 바뀔 때마다 React Flow 에 줄 노드·선 객체를 모두 새로 만든다. 그러면 끌기 한 걸음(카드 하나의 자리)에도
 * React Flow 가 카드·선을 모두 다시 그린다(200노드에서 한 걸음 ≈ 0.1초 — 이 환경 기준). 새로 만든 객체가 앞의 것과 ★값이 같으면★
 * 앞의 객체를 돌려줘 다시 그리지 않게 한다. 값이 다르면 늘 새 객체 — 보이는 것은 바뀌지 않는다(같은 값이니까).
 * 순수 — React·스토어를 부르지 않는다(시험이 직접 부른다).
 */

const plain = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && (Object.getPrototypeOf(v) === Object.prototype || Object.getPrototypeOf(v) === null);

/** 깊이 `depth` 까지 같은 값인지 — 배열·평범한 객체만 들어가 보고, 함수·그 밖의 객체는 같은 것(===)일 때만 같다. */
export function sameValue(a: unknown, b: unknown, depth = 4): boolean {
  if (Object.is(a, b)) return true;
  if (depth <= 0) return false;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => sameValue(x, b[i], depth - 1));
  if (plain(a) && plain(b)) {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && sameValue(a[k], b[k], depth - 1));
  }
  return false;
}

/** `next` 의 각 항목을, 같은 id 의 앞 항목과 값이 같으면 앞 항목으로 바꾼 배열. `prev` 는 이번 결과로 바꿔 둔다(사라진 id 는 빠진다). */
export function keepSame<T extends { id: string }>(prev: Map<string, unknown>, next: T[]): T[] {
  const out = next.map((x) => {
    const p = prev.get(x.id);
    return p !== undefined && sameValue(p, x) ? (p as T) : x;              // 값이 같으니 모양도 같다
  });
  prev.clear();
  for (const x of out) prev.set(x.id, x);
  return out;
}
