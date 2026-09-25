/**
 * `params_schema`(서버 pydantic 이 만든 JSON Schema) → 폼 칸 목록 (BI3)
 * ==========================================================================
 * ★범위·선택지를 여기 다시 적지 않는다★ — 서버 요청 모델이 단일 출처다. 이 파일은 스키마를
 * 읽어 칸의 **종류**만 정한다. 스키마가 표현하는 것 중 폼으로 옮기기 어려운 것(객체·객체
 * 목록 — 뷰·제약)은 JSON 편집칸으로 두고, 옳은지는 서버 검증(`/validate`)이 말한다.
 */
import type { JsonSchema } from "./types";

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
    return {
      name,
      title: prop.title ?? name,
      nullable,
      required: required.has(name),
      defaultValue: prop.default,
      description: prop.description,
      ...base,
    };
  });
}
