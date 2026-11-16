/**
 * 분봉 규칙 '직접 구성' — 조건 나무를 고치는 순수 함수 (자유 조건식 설계 §6.2)
 * ==========================================================================
 * 편집기의 자료는 ★조건 나무 그 자체★다(서버가 받고 돌려주는 그 꼴). 화면만의 다른 모형을 두지 않는다 —
 * 두 모형 사이의 번역이 결함의 자리다. 편집 중의 빈 칸만 다르다: 마디는 `null`, 고르지 않은 연산과 적지 않은 시각은 빈 글자.
 * ★출발값을 지어 넣지 않는다★ — 지표의 매개변수는 서버의 문법 표가 준 값이고, 상수 · 연산 · 봉 수 · 시각은 비어서 시작한다.
 * 여기의 검사(`issuesOf`)는 보내기 전에 어느 자리에 빈 칸이 있는지 말해 주려는 것이다. 판정은 서버가 한다(`rules/expand`).
 */
import type { ConstNode, Grammar, IndNode, OpNode, Tree } from "@/entities/intraday";

export type Slot = "entry" | "entry_stop" | "exit";
/** 편집 중의 마디 — `null` 은 아직 놓지 않은 칸이다. */
export type Draft = Tree | null;
export type Drafts = Record<Slot, Draft>;
/** 뿌리에서 `args` 를 따라 내려가는 길. */
export type Path = number[];

export const EMPTY: Drafts = { entry: null, entry_stop: null, exit: null };
export const ARITH = ["add", "sub", "mul"];
export const COMPARES = ["gt", "ge", "lt", "le", "cross_up", "cross_down"];
export const GROUPS = ["and", "or"];
export const WRAPS = ["not", "held_before"];

export const isInd = (n: Tree): n is IndNode => typeof (n as { ind?: unknown }).ind === "string";
export const isConst = (n: Tree): n is ConstNode => !isInd(n) && "const" in n;
export const isOp = (n: Tree): n is OpNode => !isInd(n) && typeof (n as { op?: unknown }).op === "string";

// ── 새 마디 ─────────────────────────────────────────────────────────────────

/** 지표 잎 — 매개변수는 서버가 준 출발값(문법 표의 `default`)이다. */
export const indicator = (g: Grammar, name: string): IndNode =>
  ({ ind: name, ...Object.fromEntries((g.indicators.find((i) => i.name === name)?.params ?? []).map((p) => [p.key, p.default])) });
export const constant = (): ConstNode => ({ const: null });
/** 비교 · 돌파 한 줄 — 연산은 고르지 않은 채로 시작한다. */
export const compare = (): OpNode => ({ op: "", args: [null, null] });
export const timeWindow = (): OpNode => ({ op: "time_between", args: [], from: "", to: "" });
/** 묶음 — '모두 충족'에서 시작한다(조건을 잇는다는 것이 그 뜻이다). 화면이 바꿀 수 있다. */
export const group = (...args: Draft[]): OpNode => ({ op: "and", args });
export const negate = (child: Draft): OpNode => ({ op: "not", args: [child] });
export const heldBefore = (child: Draft): OpNode => ({ op: "held_before", bars: null, args: [child] });
/** 계산 — 앞에 있던 값은 왼쪽 항이 된다(다시 고르지 않게). */
export const arithmetic = (op: string, left: Draft = null): OpNode => ({ op, args: [left, null] });
/** 조건부 값 — 조건이 충족된 봉에만 값이 있다. 앞에 있던 값이 그 값이 된다. */
export const conditional = (value: Draft = null): OpNode => ({ op: "where", args: [null, value] });
/** N봉 전 값 — 앞에 있던 값을 감싼다. 봉 수는 비어서 시작한다(1 로 지어 넣지 않는다). */
export const ago = (value: Draft = null): OpNode => ({ op: "ago", bars: null, args: [value] });
/** 봉 수를 받는 연산 → 문법 표에 그 칸이 없을 때 쓰는 이름표(범위는 지어내지 않는다 — 1 이상의 정수인지만 본다 · 판정은 서버가 한다). */
export const BARS_OPS: Record<string, string> = { held_before: "직전 봉 수", ago: "봉 수" };

// ── 길을 따라 고치기(원본은 건드리지 않는다) ────────────────────────────────

export function at(root: Draft, path: Path): Draft {
  let cur = root;
  for (const i of path) {
    if (!cur || !isOp(cur)) return null;
    cur = cur.args[i] ?? null;
  }
  return cur;
}

export function setAt(root: Draft, path: Path, node: Draft): Draft {
  if (!path.length) return node;
  if (!root || !isOp(root)) return root;
  const args = root.args.slice();
  args[path[0]] = setAt(args[path[0]] ?? null, path.slice(1), node);
  return { ...root, args };
}

/**
 * 마디를 지운다 — 묶음 안이면 그 줄이 빠지고, 그 밖(비교의 변 · 감싼 것의 안)이면 빈 칸이 되며, 뿌리면 빈 자리가 된다.
 * 지워서 조건이 ★하나만★ 남은 묶음은 그 조건이 된다(`append` 가 둘째 조건에서 묶는 것의 짝 — 하나짜리 묶음은 서버가 받지 않는다).
 * 하나도 남지 않은 묶음은 빈 채로 둔다(사용자가 직접 놓은 묶음이다 — 채우거나 지우는 것은 사용자가 한다).
 */
export function removeAt(root: Draft, path: Path): Draft {
  if (!path.length) return null;
  const parentPath = path.slice(0, -1);
  const index = path[path.length - 1];
  const parent = at(root, parentPath);
  if (!parent || !isOp(parent)) return root;
  if (!GROUPS.includes(parent.op)) return setAt(root, parentPath, { ...parent, args: parent.args.map((a, i) => (i === index ? null : a)) });
  const args = parent.args.filter((_, i) => i !== index);
  return setAt(root, parentPath, args.length === 1 ? args[0] : { ...parent, args });
}

/** 자리의 뿌리에 조건 하나를 더한다 — 비었으면 그것이 뿌리, 묶음이면 줄을 잇고, 그 밖이면 '모두 충족'으로 묶는다. */
export function append(root: Draft, node: Tree): Tree {
  if (root === null) return node;
  if (isOp(root) && GROUPS.includes(root.op)) return { ...root, args: [...root.args, node] };
  return group(root, node);
}

// ── 세기와 빈 칸 찾기 ───────────────────────────────────────────────────────

/** (마디 수, 깊이) — 서버와 같은 법으로 센다(뿌리의 깊이가 1). 빈 칸은 세지 않는다. */
export function sizeOf(node: Draft): { nodes: number; depth: number } {
  if (node === null) return { nodes: 0, depth: 0 };
  const kids = isOp(node) ? node.args.map(sizeOf) : [];
  return { nodes: 1 + kids.reduce((a, k) => a + k.nodes, 0), depth: 1 + kids.reduce((a, k) => Math.max(a, k.depth), 0) };
}

const hhmm = (s: string | undefined): boolean => typeof s === "string" && /^\d{4}$/.test(s) && Number(s.slice(0, 2)) < 24 && Number(s.slice(2)) < 60;
const inRange = (v: unknown, p: { type: string; min?: number; max?: number }): boolean =>
  typeof v === "number" && Number.isFinite(v) && (p.type !== "int" || Number.isInteger(v))
  && (p.min === undefined || v >= p.min) && (p.max === undefined || v <= p.max);
const rangeOf = (p: { min?: number; max?: number; unit?: string }): string =>
  `${p.min ?? ""}~${p.max ?? ""}${p.unit ?? ""}`;
/** 이름표 뒤의 조사 — 받침이 있으면 '은', 없으면 '는'(이름표는 서버의 한글 이름이다). */
const topic = (word: string): string => {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  return `${word}${code >= 0 && code <= 11171 && code % 28 === 0 ? "는" : "은"}`;
};

type Found = { holes: number; groups: boolean; times: boolean; ranges: string[] };

function walk(node: Draft, g: Grammar, out: Found): void {
  if (node === null) { out.holes += 1; return; }
  if (isInd(node)) {
    const spec = g.indicators.find((i) => i.name === node.ind);
    if (!spec) { out.holes += 1; return; }
    for (const p of spec.params) {
      if (!inRange(node[p.key], p)) out.ranges.push(`${topic(`${spec.label} ${p.label}`)} ${rangeOf(p)} 범위로 입력하십시오.`);
    }
    return;
  }
  if (isConst(node)) {
    if (typeof node.const !== "number" || !Number.isFinite(node.const)) out.holes += 1;
    return;
  }
  if (node.op === "") out.holes += 1;
  if (GROUPS.includes(node.op) && node.args.length < 2) out.groups = true;
  if (node.op in BARS_OPS) {                                    // 직전 M봉 동안 · N봉 전 값 — 범위는 문법 표의 그 연산에서 읽는다
    const bars = g.ops.find((o) => o.name === node.op)?.extra.find((e) => e.key === "bars") ?? { key: "bars", label: BARS_OPS[node.op], type: "int" as const, min: 1 };
    if (!inRange(node.bars, bars)) out.ranges.push(`${topic(bars.label)} ${rangeOf(bars)} 범위로 입력하십시오.`);
  }
  if (node.op === "time_between" && !(hhmm(node.from) && hhmm(node.to) && node.from! <= node.to!)) out.times = true;
  for (const arg of node.args) walk(arg, g, out);
}

/** 보낼 수 없는 사유들(없으면 빈 배열) — 자리마다 무엇이 비었는지 말한다. 서버의 검사를 대신하지 않는다. */
export function issuesOf(drafts: Drafts, g: Grammar): string[] {
  const out: string[] = [];
  if (drafts.entry === null && drafts.entry_stop === null) out.push(g.entry_rule);
  let nodes = 0;
  for (const slot of g.slots) {
    const root = drafts[slot.key];
    if (root === null) continue;                                 // 쓰지 않는 자리
    nodes += sizeOf(root).nodes;
    const found: Found = { holes: 0, groups: false, times: false, ranges: [] };
    walk(root, g, found);
    if (found.holes) out.push(`${slot.label}: 비어 있는 칸이 ${found.holes}곳 있습니다.`);
    if (found.groups) out.push(`${slot.label}: 묶음에는 조건이 둘 이상 있어야 합니다.`);
    if (found.times) out.push(`${slot.label}: 시각 창의 시작과 종료를 확인하십시오.`);
    for (const text of [...new Set(found.ranges)]) out.push(`${slot.label}: ${text}`);
  }
  if (nodes > g.limits.nodes) out.push(`조건의 마디 수가 상한 ${g.limits.nodes}개를 넘었습니다(지금 ${nodes}개).`);
  return out;
}

// ── 서버와 주고받는 꼴 ──────────────────────────────────────────────────────

const SLOTS: Slot[] = ["entry", "entry_stop", "exit"];

/** 서버에 보내는 `rule.params` — 쓰지 않는 자리는 싣지 않는다. 빈 칸이 없을 때(`issuesOf` 가 비었을 때)만 쓴다. */
export const toParams = (drafts: Drafts): Record<string, Tree> =>
  Object.fromEntries(SLOTS.filter((s) => drafts[s] !== null).map((s) => [s, drafts[s] as Tree]));

/** 서버가 준 나무 셋(풀이의 답 · 시행의 설정)을 편집기에 싣는다. 모르는 자리는 싣지 않는다. */
export const fromParams = (params: Record<string, unknown>): Drafts =>
  ({ ...EMPTY, ...Object.fromEntries(SLOTS.filter((s) => params[s] !== undefined && params[s] !== null).map((s) => [s, params[s] as Tree])) });
