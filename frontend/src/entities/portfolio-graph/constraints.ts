/**
 * 제약 편집기의 순수 규칙 (CF 3부 P2)
 * ==========================================================================
 * ★값의 모양은 서버 `ConstraintsInput` 그대로★ — 문서에 쓰는 것은 지금까지와 같은 dict 하나(옛 문서가 그대로 열린다).
 * ★범위는 스키마에서 읽는다★(`rangeOf`) — 여기에 -50·400 같은 숫자를 다시 적지 않는다.
 * 기본 칩(한 종목 최대)은 다른 제약을 지우지 않는다(`mergeMaxPreset`) — 예전에는 칩이 dict 를 통째로 바꿔
 * 업종 상한·회전율을 말없이 지웠다. 다 비면 칸을 지운다(서버 기본값).
 */
import type { JsonSchema } from "./types";

export type ConstraintsValue = Record<string, unknown>;

/** 기본 칩이 고르는 키 — 서버 프리셋(`{max_weight_pct: n}` · `null`)의 이 키만 읽고 쓴다. */
export const MAX_KEY = "max_weight_pct";

/** 숫자 칸 — 서버 키 · 질문 · 단위 · 묶음. 질문 글은 제품 문구라 여기 둔다(범위·뜻은 서버 스키마). */
export const NUMBER_CARDS: { key: string; group: string; label: string; unit: string; help?: string }[] = [
  { key: "min_weight_pct", group: "floor", label: "한 종목에 최소 얼마는 둘까요?", unit: "%",
    help: "음수로 두면 그만큼 공매도할 수 있어요(공매도는 연구용)." },
  { key: "turnover_cap_pct", group: "turnover", label: "한 번에 얼마까지 바꿀까요? (회전율)", unit: "%",
    help: "지금 비중을 적어 두었을 때만 걸려요." },
  { key: "beta_min", group: "beta", label: "시장 민감도(베타) 아래 끝", unit: "",
    help: "벤치마크가 있을 때만 걸려요." },
  { key: "beta_max", group: "beta", label: "시장 민감도(베타) 위 끝", unit: "" },
  { key: "cash_min_pct", group: "cash", label: "현금을 최소 얼마 둘까요?", unit: "%",
    help: "현금 수익은 0으로 가정해요." },
  { key: "cash_max_pct", group: "cash", label: "현금을 최대 얼마 둘까요?", unit: "%" },
  { key: "gross_max_pct", group: "exposure", label: "총 노출(롱 + 숏) 최대", unit: "%",
    help: "공매도를 쓸 때의 크기예요 — 130/30 이면 160%." },
  { key: "net_min_pct", group: "exposure", label: "순 노출(롱 − 숏) 아래 끝", unit: "%" },
  { key: "net_max_pct", group: "exposure", label: "순 노출(롱 − 숏) 위 끝", unit: "%" },
];

/**
 * 모양 프리셋 — 공매도 폭(-10% · -20%)은 ★가정★이다(화면이 그렇게 적는다). 롱온리는 공매도 칸을 걷는다.
 * 130/30 · 달러 중립의 정의는 서버 `ConstraintsInput` 주석과 같다(gross 160 · net 100 / net 0 · gross 200).
 */
export const SHAPES: { id: string; label: string; set: ConstraintsValue; assumed?: string }[] = [
  { id: "long_only", label: "롱온리", set: {} },
  { id: "130_30", label: "130/30", set: { min_weight_pct: -10, gross_max_pct: 160, net_min_pct: 100, net_max_pct: 100 },
    assumed: "종목당 공매도 최대 10%는 가정이에요 — 바꿀 수 있어요." },
  { id: "neutral", label: "달러 중립", set: { min_weight_pct: -20, gross_max_pct: 200, net_min_pct: 0, net_max_pct: 0 },
    assumed: "종목당 공매도 최대 20%는 가정이에요 — 바꿀 수 있어요." },
];
const SHAPE_KEYS = ["min_weight_pct", "gross_max_pct", "net_min_pct", "net_max_pct"] as const;

/** 지금 값 — 문서에 없으면 빈 dict. */
export const asConstraints = (v: unknown): ConstraintsValue =>
  v && typeof v === "object" && !Array.isArray(v) ? { ...(v as ConstraintsValue) } : {};

/** 서버 기본값이 0 인 칸 — 0 은 "정하지 않음" 과 같아 지운다. 순 노출 0(달러 중립)·회전율 0 은 뜻이 있어 남긴다. */
const ZERO_IS_DEFAULT = new Set(["min_weight_pct", "cash_min_pct", "cash_max_pct"]);

/** 빈 dict 는 `undefined`(칸을 지운다 — 서버 기본값). 빈 업종 상한도 같다. */
export function tidyConstraints(c: ConstraintsValue): ConstraintsValue | undefined {
  const out = { ...c };
  for (const [k, v] of Object.entries(out)) {
    if (v === undefined || v === null || v === "") delete out[k];
    else if (k === "group_caps_pct" && (typeof v !== "object" || !Object.keys(v as object).length)) delete out[k];
    else if (ZERO_IS_DEFAULT.has(k) && v === 0) delete out[k];
  }
  return Object.keys(out).length ? out : undefined;
}

/** 칸 하나를 바꾼다(`undefined` = 지움). */
export function setConstraint(cur: unknown, key: string, v: unknown): ConstraintsValue | undefined {
  return tidyConstraints({ ...asConstraints(cur), [key]: v });
}

/** 기본 칩(서버 프리셋) — ★한 종목 최대만★ 바꾸고 나머지는 그대로. 프리셋 `null`(제한 없음)은 그 키를 지운다. */
export function mergeMaxPreset(cur: unknown, preset: unknown): ConstraintsValue | undefined {
  const v = preset && typeof preset === "object" ? (preset as ConstraintsValue)[MAX_KEY] : undefined;
  return setConstraint(cur, MAX_KEY, v ?? undefined);
}

/** 이 칩이 지금 값인가 — 한 종목 최대만 비교한다(다른 제약이 있어도 칩은 켜진다). */
export function maxPresetActive(cur: unknown, preset: unknown): boolean {
  const have = asConstraints(cur)[MAX_KEY];
  const want = preset && typeof preset === "object" ? (preset as ConstraintsValue)[MAX_KEY] : undefined;
  return (have ?? null) === (want ?? null);
}

/** 모양 프리셋 — 공매도 네 칸만 바꾸고 나머지(한 종목 최대·업종·회전율…)는 그대로. */
export function applyShape(cur: unknown, shapeId: string): ConstraintsValue | undefined {
  const s = SHAPES.find((x) => x.id === shapeId);
  if (!s) return tidyConstraints(asConstraints(cur));
  const base = asConstraints(cur);
  for (const k of SHAPE_KEYS) delete base[k];
  return tidyConstraints({ ...base, ...s.set });
}

/** 지금 모양 — 네 칸이 프리셋과 같으면 그 이름, 공매도 칸이 비면 롱온리, 아니면 `custom`. */
export function shapeOf(cur: unknown): string {
  const c = asConstraints(cur);
  for (const s of SHAPES) {
    if (SHAPE_KEYS.every((k) => (c[k] ?? (k === "min_weight_pct" ? 0 : null)) === (s.set[k] ?? (k === "min_weight_pct" ? 0 : null)))) return s.id;
  }
  return "custom";
}

/** 하한이 음수면 공매도 — 서버 `ConstraintsValue.allows_short()` 와 같은 한 줄 규칙. */
export const allowsShort = (cur: unknown) => Number(asConstraints(cur).min_weight_pct ?? 0) < 0;

/** 업종 상한 dict. */
export const capsOf = (cur: unknown): Record<string, number> => {
  const g = asConstraints(cur).group_caps_pct;
  return g && typeof g === "object" ? { ...(g as Record<string, number>) } : {};
};

/** 업종 상한 하나를 바꾼다(`undefined` = 그 업종 지움). */
export function setCap(cur: unknown, group: string, pct: number | undefined): ConstraintsValue | undefined {
  const caps = capsOf(cur);
  if (pct === undefined) delete caps[group]; else caps[group] = pct;
  return setConstraint(cur, "group_caps_pct", caps);
}

/** `optimizer` params 스키마에서 `ConstraintsInput` 한 칸의 [min, max]. 없으면 `null`. */
export function rangeOf(root: JsonSchema | null, key: string): { min?: number; max?: number } | null {
  const def = root?.$defs?.ConstraintsInput?.properties?.[key];
  if (!def) return null;
  const v = (def.anyOf ?? [def]).find((x) => x.minimum !== undefined || x.maximum !== undefined) ?? def;
  return { min: v.minimum, max: v.maximum };
}

/** 한 줄 요약(카드·간단히 보기) — 값이 있는 것만, 서버 값 그대로. */
export function constraintsSummary(cur: unknown): string | null {
  const c = asConstraints(cur);
  const parts: string[] = [];
  if (c.max_weight_pct !== undefined) parts.push(`한 종목 최대 ${c.max_weight_pct}%`);
  const caps = Object.keys(capsOf(c)).length;
  if (caps) parts.push(`업종 상한 ${caps}개`);
  if (c.turnover_cap_pct !== undefined) parts.push(`회전율 ${c.turnover_cap_pct}%`);
  const sh = shapeOf(c);
  if (sh !== "long_only") parts.push(sh === "custom" ? "공매도·노출 직접" : SHAPES.find((s) => s.id === sh)!.label);
  if (c.beta_min !== undefined || c.beta_max !== undefined) parts.push("베타 범위");
  if (c.cash_min_pct !== undefined || c.cash_max_pct !== undefined) parts.push("현금 범위");
  return parts.length ? parts.join(" · ") : null;
}

/** `/allocation/constraints/check` 의 답 — 판정은 서버가(엔진의 사전 검사 그대로). `checked: false` 면 종목을 몰라 재지 않았다. */
export interface ConstraintsCheck {
  checked: boolean;
  ok: boolean | null;
  reason: string | null;
  groups: Record<string, string>;
  group_names: string[];
  unknown: string[];
  sectors_readable: boolean;
  unapplied: ({ kind: "group_cap"; group: string; cap_pct: number; text: string }
              | { kind: "unknown_sector"; names: string[]; text: string })[];
  allows_short: boolean;
  short_note: string | null;
}
