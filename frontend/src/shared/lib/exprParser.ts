// ═══════════════════════════════════════════════════════════════════════════════
// exprParser — 팩터 불리언 조건식 파서
//   "팩터1 and (팩터2 or 팩터3)" → 중첩 AND/OR 트리 (백엔드 filter_ast 와 1:1)
//   순수 함수(외부 의존 0). 토큰: 팩터N / FN (1-based) · and|&|&& · or|| · ( )
// ═══════════════════════════════════════════════════════════════════════════════

export type ExprNode =
  | { type: "ref"; index: number }                       // 0-based 조건 인덱스
  | { type: "op"; op: "AND" | "OR"; children: ExprNode[] };

export type ParseResult =
  | { ok: true; ast: ExprNode }
  | { ok: false; error: string };

type Tok =
  | { t: "ref"; index: number }
  | { t: "and" }
  | { t: "or" }
  | { t: "lp" }
  | { t: "rp" };

class ParseError extends Error {}

// ── 토큰화 ──
function tokenize(text: string, count: number): Tok[] {
  const toks: Tok[] = [];
  const s = text;
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch === " " || ch === "\t" || ch === "\n" || ch === "\r") { i++; continue; }
    if (ch === "(") { toks.push({ t: "lp" }); i++; continue; }
    if (ch === ")") { toks.push({ t: "rp" }); i++; continue; }
    if (ch === "&") { i++; if (s[i] === "&") i++; toks.push({ t: "and" }); continue; }
    if (ch === "|") { i++; if (s[i] === "|") i++; toks.push({ t: "or" }); continue; }
    // 팩터N (한글 토큰)
    if (s.startsWith("팩터", i)) {
      let j = i + 2;
      let num = "";
      while (j < s.length && s[j] >= "0" && s[j] <= "9") { num += s[j]; j++; }
      if (num === "") throw new ParseError("'팩터' 뒤에 번호가 필요합니다");
      const n = parseInt(num, 10);
      if (n < 1 || n > count) throw new ParseError(`팩터${n} 는 없는 팩터입니다 (팩터1~팩터${count})`);
      toks.push({ t: "ref", index: n - 1 });
      i = j; continue;
    }
    // 영문 단어: and / or / FN
    if (/[A-Za-z]/.test(ch)) {
      let j = i;
      let w = "";
      while (j < s.length && /[A-Za-z0-9]/.test(s[j])) { w += s[j]; j++; }
      const lw = w.toLowerCase();
      if (lw === "and") { toks.push({ t: "and" }); i = j; continue; }
      if (lw === "or") { toks.push({ t: "or" }); i = j; continue; }
      const m = /^f(\d+)$/i.exec(w);
      if (m) {
        const n = parseInt(m[1], 10);
        if (n < 1 || n > count) throw new ParseError(`F${n} 는 없는 팩터입니다 (팩터1~팩터${count})`);
        toks.push({ t: "ref", index: n - 1 });
        i = j; continue;
      }
      throw new ParseError(`알 수 없는 토큰: ${w}`);
    }
    throw new ParseError(`알 수 없는 문자: ${ch}`);
  }
  return toks;
}

// ── 재귀하강 파서 (정밀도: OR < AND < atom, 괄호 최우선) ──
function parseTokens(toks: Tok[]): ExprNode {
  let pos = 0;
  const peek = (): Tok | undefined => toks[pos];
  const next = (): Tok | undefined => toks[pos++];

  function parseOr(): ExprNode {
    const children: ExprNode[] = [parseAnd()];
    while (peek()?.t === "or") { next(); children.push(parseAnd()); }
    return children.length === 1 ? children[0] : { type: "op", op: "OR", children };
  }
  function parseAnd(): ExprNode {
    const children: ExprNode[] = [parseAtom()];
    while (peek()?.t === "and") { next(); children.push(parseAtom()); }
    return children.length === 1 ? children[0] : { type: "op", op: "AND", children };
  }
  function parseAtom(): ExprNode {
    const tk = peek();
    if (!tk) throw new ParseError("팩터가 필요한 자리에 식이 끝났습니다");
    if (tk.t === "lp") {
      next();
      const inner = parseOr();
      if (peek()?.t !== "rp") throw new ParseError("괄호가 맞지 않습니다");
      next();
      return inner;
    }
    if (tk.t === "ref") { next(); return { type: "ref", index: tk.index }; }
    if (tk.t === "and" || tk.t === "or") throw new ParseError("연산자 앞에 팩터가 필요합니다");
    throw new ParseError("괄호가 맞지 않습니다");
  }

  const ast = parseOr();
  if (pos < toks.length) {
    const tk = toks[pos];
    if (tk.t === "ref") throw new ParseError("팩터 사이에 연산자(and/or)가 필요합니다");
    if (tk.t === "rp") throw new ParseError("괄호가 맞지 않습니다");
    throw new ParseError("조건식을 끝까지 해석하지 못했습니다");
  }
  return ast;
}

export function parseExpr(text: string, count: number): ParseResult {
  try {
    const toks = tokenize(text, count);
    if (toks.length === 0) return { ok: false, error: "조건식이 비어 있습니다" };
    return { ok: true, ast: parseTokens(toks) };
  } catch (e) {
    if (e instanceof ParseError) return { ok: false, error: e.message };
    return { ok: false, error: "조건식을 해석할 수 없습니다" };
  }
}

// ── materialize: ExprNode + 정렬된 조건 → 중첩 group 트리 ──
export type Group<C> = { logic: "AND" | "OR"; conditions: C[]; groups: Group<C>[] };

export function materialize<C>(node: ExprNode, conds: C[]): Group<C> {
  if (node.type === "ref") return { logic: "AND", conditions: [conds[node.index]], groups: [] };
  const conditions: C[] = [];
  const groups: Group<C>[] = [];
  for (const ch of node.children) {
    if (ch.type === "ref") conditions.push(conds[ch.index]);
    else groups.push(materialize(ch, conds));
  }
  return { logic: node.op, conditions, groups };
}
