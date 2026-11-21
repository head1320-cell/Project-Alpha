/**
 * 빠른 추가 후보 순서 (BO O5) — ★사용 기록 없이 흐름 단계 순서로★
 * ==========================================================================
 * 선을 끌어 온 노드의 단계(`stage`)를 기준으로, 내보내는 선이면 **다음 단계부터**(같은 단계 → 바로 다음 → …, 앞 단계는 뒤로),
 * 받는 선이면 **앞 단계부터**(같은 단계 → 바로 앞 → …) 보인다. 같은 거리에서는 그 포트가 꼭 필요한 입력인 노드가 먼저,
 * 그다음 서버 카탈로그 순서. 순서는 타입 일치(연결 규칙)와 이름 찾기를 거른 뒤에만 정한다 — 거르는 규칙은 바꾸지 않는다.
 */
import type { NodeCatalogEntry } from "./types";

export interface QuickFrom { side: "source" | "target"; type: string; kind?: string | null }
export interface QuickItem { c: NodeCatalogEntry; port: string | null }

export function quickAddItems(catalog: NodeCatalogEntry[], from: QuickFrom | null, stageKeys: string[], query = "",
                              limit = 30): QuickItem[] {
  const needle = query.trim().toLowerCase();
  const items = catalog.flatMap((c, i) => {
    // 타입이 맞는 첫 포트 — 선을 받는 쪽이면 입력, 선을 내는 쪽이면 출력(연결 규칙과 같은 타입 일치).
    const ports = !from ? null : from.side === "source" ? c.inputs : c.outputs;
    const hit = ports?.find((p) => p.type === from!.type);
    if (from && !hit) return [];
    if (needle && ![c.plain_label, c.plain_description, c.type].some((x) => x?.toLowerCase().includes(needle))) return [];
    return [{ c, port: hit?.name ?? null, required: hit ? hit.required !== false : false, i }];
  });
  const origin = from?.kind ? catalog.find((c) => c.type === from.kind)?.stage : undefined;
  const at = (k: string | undefined) => (k === undefined ? -1 : stageKeys.indexOf(k));
  const o = at(origin);
  if (from && o >= 0) {
    // 흐름 방향으로 가까운 것이 먼저 — 반대 방향은 뒤(거리 + 단계 수).
    const dist = (s: number) => {
      if (s < 0) return 1e6;
      const d = from.side === "source" ? s - o : o - s;
      return d >= 0 ? d : stageKeys.length + -d;
    };
    items.sort((a, b) => dist(at(a.c.stage)) - dist(at(b.c.stage))
      || Number(b.required) - Number(a.required) || a.i - b.i);
  }
  return items.slice(0, limit).map(({ c, port }) => ({ c, port }));
}
