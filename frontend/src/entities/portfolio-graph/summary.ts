/**
 * 노드 카드의 짧은 요약 — "종목 3개" · "내 생각 반영" · "3년" (BJ2).
 * ★서버 x-ui 만 읽는다★(선택지 라벨·프리셋·쉬운 이름) — 요약 규칙을 노드마다 화면에 적지 않는다.
 * 선택지 → 목록 → 프리셋 → 그 밖의 값 순서로 첫 번째 기본 칸을 쓴다. 없으면 쉬운 이름.
 */
import { fieldsOf, type FieldSpec } from "./schema";
import type { NodeCatalogEntry } from "./types";

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function rank(f: FieldSpec): number {
  if (f.ui.options) return 0;
  if (f.kind === "string_list" || f.kind === "json") return 1;
  if (f.ui.presets) return 2;
  return 3;
}

export function nodeSummary(entry: NodeCatalogEntry | undefined, params: Record<string, unknown>): string | null {
  if (!entry) return null;
  const basic = fieldsOf(entry.params_schema).filter((f) => f.ui.tier === "basic").sort((a, b) => rank(a) - rank(b));
  for (const f of basic) {
    const v = params[f.name] !== undefined ? params[f.name] : f.defaultValue;
    const preset = f.ui.presets?.find((p) => same(p.value, v ?? null));
    if (preset) return f.ui.options ? preset.label : `${f.ui.label} ${preset.label}`;
    if (v === undefined || v === null) continue;
    if (f.ui.options && typeof v === "string") return f.ui.options[v] ?? v;
    if (Array.isArray(v)) return `${f.ui.label} ${v.length}개`;
    if (typeof v === "boolean") return `${f.ui.label} ${v ? "켬" : "끔"}`;
    if (typeof v === "number") return `${f.ui.label} ${v}`;
  }
  return null;
}
