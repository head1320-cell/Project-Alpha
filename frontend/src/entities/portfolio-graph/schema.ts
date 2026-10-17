/**
 * `params_schema`(서버 pydantic 이 만든 JSON Schema) → 폼 칸 목록 (BI3)
 * ==========================================================================
 * ★범위·선택지를 여기 다시 적지 않는다★ — 서버 요청 모델이 단일 출처다. 이 파일은 스키마를
 * 읽어 칸의 **종류**만 정한다. 스키마가 표현하는 것 중 폼으로 옮기기 어려운 것(객체·객체
 * 목록 — 뷰·제약)은 JSON 편집칸으로 두고, 옳은지는 서버 검증(`/validate`)이 말한다.
 */
import type { JsonSchema, ParamUi } from "./types";

export type FieldKind = "boolean" | "number" | "integer" | "enum" | "string" | "string_list" | "json";

export interface FieldSpec {
  name: string;
  title: string;
  kind: FieldKind;
  nullable: boolean;
  required: boolean;
  options?: string[];
  min?: number;
  max?: number;
  defaultValue?: unknown;
  description?: string;
  /** 서버 x-ui — 없으면 전문가 층으로 본다(쉬운 이름이 없는 칸을 기본 화면에 내지 않는다). */
  ui: ParamUi;
  /** 원래 스키마 조각 — 객체 목록 편집기가 항목 스키마를 읽는다. */
  raw: JsonSchema;
}

/** `$ref` 를 루트의 `$defs` 로 푼다. */
export function resolveSchema(s: JsonSchema, root: JsonSchema | null): JsonSchema {
  if (!s.$ref || !root) return s;
  return root.$defs?.[s.$ref.replace(/^#\/\$defs\//, "")] ?? s;
}

/** 객체 목록 칸(예: 뷰 목록)의 항목 스키마. 아니면 `null`. */
export function itemSchemaOf(f: FieldSpec, root: JsonSchema | null): JsonSchema | null {
  const variants = f.raw.anyOf ?? [f.raw];
  for (const v of variants) {
    if (v.items) {
      const it = resolveSchema(v.items, root);
      if (it.properties) return { ...it, $defs: root?.$defs };
    }
  }
  return null;
}

const typeOf = (s: JsonSchema): string | undefined =>
  Array.isArray(s.type) ? s.type.find((t) => t !== "null") : s.type;

/** `^(hard|probabilistic)$` · `^[MQ]$` 같은 단순 선택 패턴 → 선택지. 아니면 `null`. */
export function optionsFromPattern(pattern: string | undefined): string[] | null {
  if (!pattern) return null;
  const alt = /^\^\(([\w|]+)\)\$$/.exec(pattern);
  if (alt) return alt[1].split("|");
  const cls = /^\^\[([A-Za-z0-9]+)\]\$$/.exec(pattern);
  if (cls) return cls[1].split("");
  return null;
}

function resolveRef(s: JsonSchema, root: JsonSchema): JsonSchema {
  if (!s.$ref) return s;
  const key = s.$ref.replace(/^#\/\$defs\//, "");
  return root.$defs?.[key] ?? s;
}

function kindOf(s: JsonSchema, root: JsonSchema): Pick<FieldSpec, "kind" | "options" | "min" | "max"> {
  const r = resolveRef(s, root);
  if (r.$ref || r.properties || typeOf(r) === "object") return { kind: "json" };
  if (Array.isArray(r.enum)) return { kind: "enum", options: r.enum.map(String) };
  const t = typeOf(r);
  if (t === "boolean") return { kind: "boolean" };
  if (t === "integer" || t === "number") {
    return { kind: t, min: r.minimum, max: r.maximum };
  }
  if (t === "string") {
    const opts = optionsFromPattern(r.pattern);
    return opts ? { kind: "enum", options: opts } : { kind: "string" };
  }
  if (t === "array") {
    const it = r.items ? resolveRef(r.items, root) : undefined;
    return it && typeOf(it) === "string" ? { kind: "string_list" } : { kind: "json" };
  }
  return { kind: "json" };
}

export function fieldsOf(schema: JsonSchema | null): FieldSpec[] {
  if (!schema?.properties) return [];
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties).map(([name, prop]) => {
    const variants = prop.anyOf ?? [prop];
    const nonNull = variants.filter((v) => typeOf(v) !== "null" || v.$ref);
    const nullable = variants.length !== nonNull.length;
    const base = nonNull.length === 1 ? kindOf(nonNull[0], schema) : { kind: "json" as const };
    const ui: ParamUi = prop["x-ui"] ?? { label: prop.title ?? name, tier: "advanced" };
    return {
      name,
      raw: prop,
      ui,
      title: ui.label ?? prop.title ?? name,
      nullable,
      required: required.has(name),
      defaultValue: prop.default,
      description: prop.description,
      ...base,
    };
  });
}

/**
 * 지금 값으로 보이는 칸인가(BO O1 — `x-ui.show_if`). 조건 칸의 값은 문서 값, 없으면 스키마 기본값.
 * ★다른 방식에서는 비중을 못 움직이는 손잡이를 질문으로 내놓지 않는다★ — δ 의 교훈(BN N2).
 */
export function isShown(f: FieldSpec, params: Record<string, unknown>, fields: FieldSpec[]): boolean {
  const cond = f.ui.show_if;
  if (!cond) return true;
  return Object.entries(cond).every(([k, allowed]) => {
    const dep = fields.find((x) => x.name === k);
    const v = params[k] !== undefined ? params[k] : dep?.defaultValue;
    return allowed.some((a) => JSON.stringify(a) === JSON.stringify(v ?? null));
  });
}

/** 기본 층 질문 — 보이는 칸만, 고르는 칸(카드)이 먼저, 나머지는 서버 순서. 설정 탭·간단히 보기·요약이 같이 쓴다. */
export function basicFieldsOf(schema: JsonSchema | null, params: Record<string, unknown>): FieldSpec[] {
  const all = fieldsOf(schema);
  return all.filter((f) => f.ui.tier === "basic" && isShown(f, params, all))
    .map((f, i) => ({ f, i })).sort((a, b) => Number(!a.f.ui.options) - Number(!b.f.ui.options) || a.i - b.i)
    .map((x) => x.f);
}

/** 값 비교 — 설정 판과 노드 카드 위젯이 같은 규칙으로 '지금 고른 것'을 판정한다. */
export const sameValue = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** 칸 하나를 바꾼 새 params — `undefined` 면 칸을 지워 서버 기본값을 쓴다(설정 판·카드 위젯 공용). */
export function setOrClear(p: Record<string, unknown>, k: string, v: unknown): Record<string, unknown> {
  const next = { ...p };
  if (v === undefined) delete next[k]; else next[k] = v;
  return next;
}

/** 노드 카드 위젯이 그리는 모양(CF1) — 한 줄 고르기 또는 슬라이더. */
export type CardControl = "select" | "slider";
/** 카드에 놓는 위젯 수의 상한 — 넘거나 카드에 못 그리는 칸이 있으면 "설정 더 보기"로 오른쪽 판을 연다. */
export const CARD_WIDGETS_MAX = 4;

/**
 * 이 기본 칸을 노드 카드에 그릴 수 있나(CF1) — 고르기(선택지·프리셋·예/아니요)와 슬라이더만.
 * 저장된 것 고르기·조건·종목·포트별 값·목록·긴 글은 카드 폭에 맞지 않아 오른쪽 판(설정)에서만 다룬다.
 */
export function cardControlOf(f: FieldSpec, root: JsonSchema | null): CardControl | null {
  const w = f.ui.widget;
  if (w === "per_port" || w === "per_port_number" || w === "text" || w === "pick" || w === "filter" || w === "tickers") return null;
  if (f.kind === "string_list" || (f.kind === "json" && itemSchemaOf(f, root))) return null;
  const numeric = (f.kind === "number" || f.kind === "integer") && f.min !== undefined && f.max !== undefined;
  if (f.ui.options) return "select";
  if (f.ui.presets && w === "slider" && numeric) return "slider";
  if (f.ui.presets) return "select";
  if (w === "slider" && numeric) return "slider";
  if (f.kind === "boolean") return "select";
  return null;
}

/** 카드에 놓을 기본 칸(보이는 것만, 설정 판과 같은 순서)과 "설정 더 보기"가 필요한지. */
export function cardFieldsOf(schema: JsonSchema | null, params: Record<string, unknown>): { fields: FieldSpec[]; more: boolean } {
  const basic = basicFieldsOf(schema, params);
  const fields = basic.filter((f) => cardControlOf(f, schema)).slice(0, CARD_WIDGETS_MAX);
  return { fields, more: basic.length > fields.length };
}

/**
 * 카드가 미리 잡는 위젯 자리(CF1 — 자리 고정) — 조건부 칸(`show_if`)도 센다. 조건이 맞아 칸이 나타나도 상자가 커지지 않는다.
 */
export function cardWidgetSlots(schema: JsonSchema | null): { slots: number; more: boolean } {
  const basic = fieldsOf(schema).filter((f) => f.ui.tier === "basic");
  const slots = Math.min(CARD_WIDGETS_MAX, basic.filter((f) => cardControlOf(f, schema)).length);
  return { slots, more: basic.length > slots };
}
