/**
 * 분봉 백테스트 설정 칸 — 글자 → 서버가 받는 값. 순수 함수(화면은 이 값을 그대로 보낸다).
 * ==========================================================================
 * ★기본값을 지어 넣지 않는다★ — 칸의 출발값은 서버의 틀 목록(`GET /templates`)이 준 것이고 "좋은 값"이라는 뜻이 아니다.
 * 비워 둔 칸은 '그 규칙을 쓰지 않음'(`null`)이다: 수수료율을 비우면 0 이 아니라 모름이고, 손절을 비우면 손절이 없다.
 * 범위와 꼴은 서버가 다시 검사한다 — 여기의 검사는 보내기 전에 어느 칸이 어긋났는지 말해 주려는 것이다.
 */
import type { FieldDef, Grid, SimulateRequest, Template, Templates, Value } from "@/entities/intraday";

export type Texts = Record<string, string>;
export type Form = {
  tickers: string; from: string; to: string;
  kind: string; params: Texts; position: Texts; costs: Texts;
  grid: { on: boolean; folds: string; rule: Texts; position: Texts };
};

/** 비워 둘 수 없는 칸 — 서버가 값 없이는 받지 않는다. 규칙 매개변수는 전부 필수다. */
const REQUIRED = new Set(["position.amount", "costs.slippage_ticks"]);
/** 격자에 올릴 수 있는 포지션 칸 — 수로 견줄 수 있는 것만. */
export const GRID_POSITION = ["stop_pct", "target_pct", "trail_pct"];

const text = (v: number | string | null | undefined): string => (v === null || v === undefined ? "" : String(v));
const defaults = (fields: FieldDef[]): Texts => Object.fromEntries(fields.map((f) => [f.key, text(f.default)]));

export const templateOf = (t: Templates, kind: string): Template => t.templates.find((x) => x.kind === kind) ?? t.templates[0];

export function initialForm(t: Templates, period: { from: string; to: string }): Form {
  const first = t.templates[0];
  return {
    tickers: "", ...period, kind: first.kind, params: defaults(first.params), position: defaults(t.position), costs: defaults(t.costs),
    grid: { on: false, folds: "4", rule: {}, position: {} },
  };
}

/** 틀을 바꾸면 매개변수는 새 틀의 출발값으로 돌아간다(앞 틀의 값을 끌고 가지 않는다). 격자도 비운다. */
export const withKind = (form: Form, t: Templates, kind: string): Form =>
  ({ ...form, kind, params: defaults(templateOf(t, kind).params), grid: { ...form.grid, rule: {} } });

/** 쉼표·공백·줄바꿈으로 나눈 종목코드 — 순서를 지키고 겹친 것은 한 번만. */
export const parseTickers = (raw: string): string[] => [...new Set(raw.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean))];

type Read = { value: Value; error: string | null };

/** 칸 하나의 글자를 값으로. 빈칸은 `null`(쓰지 않음)이고, 꼴이나 범위가 어긋나면 사유를 준다. */
export function readField(def: FieldDef, raw: string): Read {
  const s = raw.trim();
  if (s === "") return { value: null, error: null };
  if (def.type === "choice") {
    return def.choices?.some((c) => c.value === s) ? { value: s, error: null } : { value: null, error: "고를 수 없는 값입니다." };
  }
  if (def.type === "time") {
    const ok = /^\d{4}$/.test(s) && Number(s.slice(0, 2)) < 24 && Number(s.slice(2)) < 60;
    return ok ? { value: s, error: null } : { value: null, error: "시각은 네 자리 숫자(HHMM)로 입력하십시오." };
  }
  if (!(def.type === "int" ? /^\d+$/ : /^\d+(\.\d+)?$/).test(s)) {
    return { value: null, error: def.type === "int" ? "정수로 입력하십시오." : "수로 입력하십시오." };
  }
  const v = Number(s);
  if ((def.min != null && v < def.min) || (def.max != null && v > def.max)) {
    return { value: null, error: `${rangeText(def)} 범위로 입력하십시오.` };
  }
  return { value: v, error: null };
}

export const rangeText = (def: FieldDef): string =>
  def.min == null || def.max == null ? "" : `${def.min.toLocaleString("ko-KR")}~${def.max.toLocaleString("ko-KR")}${def.unit ?? ""}`;

function readAll(scope: string, fields: FieldDef[], texts: Texts, required: (key: string) => boolean): { values: Record<string, Value>; problems: string[] } {
  const values: Record<string, Value> = {};
  const problems: string[] = [];
  for (const f of fields) {
    const r = readField(f, texts[f.key] ?? "");
    values[f.key] = r.value;
    if (r.error) problems.push(`${f.label}: ${r.error}`);
    else if (r.value === null && required(`${scope}.${f.key}`)) problems.push(`${f.label}: 값을 입력하십시오.`);
  }
  return { values, problems };
}

const isDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(s));
const daysBetween = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000) + 1;

export type Built = { request: SimulateRequest; problems: string[] };

/** 지금 설정 → 서버에 보낼 요청과, 보낼 수 없는 사유들(없으면 빈 배열). */
export function build(form: Form, t: Templates): Built {
  const template = templateOf(t, form.kind);
  const tickers = parseTickers(form.tickers);
  const problems: string[] = [];
  if (!tickers.length) problems.push("종목코드를 하나 이상 입력하십시오.");
  else if (tickers.length > t.limits.tickers) problems.push(`종목은 한 번에 ${t.limits.tickers}개까지입니다(지금 ${tickers.length}개).`);
  if (!isDate(form.from) || !isDate(form.to)) problems.push("기간의 시작일과 종료일을 입력하십시오.");
  else if (form.from > form.to) problems.push("시작일이 종료일보다 늦습니다.");
  else if (daysBetween(form.from, form.to) > t.limits.range_days) problems.push(`기간은 한 번에 ${t.limits.range_days}일까지입니다.`);
  const params = readAll("rule", template.params, form.params, () => true);
  const position = readAll("position", t.position, form.position, (k) => REQUIRED.has(k));
  const costs = readAll("costs", t.costs, form.costs, (k) => REQUIRED.has(k));
  problems.push(...params.problems, ...position.problems, ...costs.problems);
  return {
    request: { tickers, from: form.from, to: form.to, rule: { kind: form.kind, params: params.values }, position: position.values, costs: costs.values },
    problems,
  };
}

export type BuiltGrid = { grid: Grid | undefined; cells: number; problems: string[] };

/** 선언한 격자 — 칸마다 쉼표로 나눈 값들. 켜지 않았으면 격자가 없다(워크포워드를 하지 않는다). */
export function buildGrid(form: Form, t: Templates): BuiltGrid {
  if (!form.grid.on) return { grid: undefined, cells: 0, problems: [] };
  const template = templateOf(t, form.kind);
  const problems: string[] = [];
  const axis = (fields: FieldDef[], texts: Texts): Record<string, Value[]> => {
    const out: Record<string, Value[]> = {};
    for (const f of fields) {
      const raw = (texts[f.key] ?? "").trim();
      if (!raw) continue;
      const values: Value[] = [];
      for (const piece of raw.split(/[\s,]+/).filter(Boolean)) {
        const r = readField(f, piece);
        if (r.error || r.value === null) problems.push(`격자 ${f.label}: ${r.error ?? "값을 입력하십시오."}`);
        else if (!values.includes(r.value)) values.push(r.value);
      }
      if (values.length) out[f.key] = values;
    }
    return out;
  };
  const rule = axis(template.params.filter((p) => p.type !== "choice"), form.grid.rule);
  const position = axis(t.position.filter((p) => GRID_POSITION.includes(p.key)), form.grid.position);
  const sizes = [...Object.values(rule), ...Object.values(position)].map((v) => v.length);
  const cells = sizes.length ? sizes.reduce((a, b) => a * b, 1) : 0;
  const folds = Number(form.grid.folds.trim());
  if (!/^\d+$/.test(form.grid.folds.trim()) || folds < t.limits.folds_min || folds > t.limits.folds_max) {
    problems.push(`구간 수는 ${t.limits.folds_min}~${t.limits.folds_max}의 정수로 입력하십시오.`);
  }
  if (cells < 2) problems.push("격자에는 칸이 둘 이상 있어야 합니다. 값을 쉼표로 나눠 둘 이상 입력하십시오.");
  else if (cells > t.limits.grid_cells) problems.push(`격자는 ${t.limits.grid_cells}칸까지입니다(지금 ${cells}칸).`);
  return { grid: { folds, rule, position }, cells, problems };
}

/** 오늘을 끝으로 하는 `days` 일의 기간(이 브라우저의 날짜 기준) — 화면의 출발값일 뿐이다. */
export function recentPeriod(days: number, today = new Date()): { from: string; to: string } {
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const start = new Date(today);
  start.setDate(start.getDate() - (days - 1));
  return { from: iso(start), to: iso(today) };
}
