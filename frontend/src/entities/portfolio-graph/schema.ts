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
