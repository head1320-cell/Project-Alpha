#!/usr/bin/env node
/**
 * BS5 — 인라인 hex → 토큰 (한 번 돌리는 코드 변환)
 * ==========================================================================
 * 인라인 style·SVG 속성에 글자로 적은 색(`"#dc2626"`)은 CSS 규칙으로 덮을 수 없다(인라인이 이긴다). 그래서 값 자체를
 * `var(--hx-t-dc2626)` 로 바꾼다. 토큰의 라이트 값은 **같은 hex** 라 라이트는 그대로고(E2E 라이트 골든), 다크 짝은
 * `gen-dark-modules.mjs` 가 같은 규칙으로 만든다. §52(A4-X2)가 국면 색에 쓴 방법과 같다 — 거기선 이름을 붙였고, 여기선
 * 수가 많아 hex 를 이름으로 쓴다.
 *
 * ★문자열 리터럴만★ TypeScript 구문 트리로 문자열·템플릿 조각만 고친다(주석·코드는 건드리지 않는다).
 * `var(` 가 이미 든 문자열(대체값 hex)은 건너뛴다.
 *
 * ★역할을 이름에 싣는다★ `--hx-t-*`(글자) · `--hx-b-*`(바탕) · `--hx-d-*`(테두리). 같은 흰색이 단추 글자로도(다크에서도
 * 흰색이어야 한다) 풍선 바탕으로도(다크에서는 어두워야 한다) 쓰인다 — 첫 판은 밝기로만 정해 흰 글자가 어두워졌다(감사가 찾음).
 * 역할은 문자열이 값으로 들어가는 자리로 정한다: style 키(color·background·border…) · SVG 속성(fill·stroke·stopColor).
 * 조건식·괄호·`??` 를 거슬러 올라가 자리를 찾는다. 자리를 모르면(상수 표 등) 밝기로: 옅으면(명도 > 0.8) 바탕, 아니면 글자.
 * fill·stroke 도 밝기로 — 옅은 칠은 판(바탕), 진한 칠은 계열선(글자)이다.
 * 실행: node scripts/hex-to-tokens.mjs <파일|폴더>...
 */
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const HEX = /#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/g;
const full = (h) => (h.length === 3 ? [...h].map((c) => c + c).join("") : h).toLowerCase();

const TEXT_KEYS = new Set(["color", "caretColor", "textDecorationColor", "WebkitTextFillColor"]);
const BG_KEYS = new Set(["background", "backgroundColor", "backgroundImage"]);
const BORDER_KEY = /^(border|outline)/i;

function lightness(h) {
  const n = (i) => parseInt(h.slice(i, i + 2), 16) / 255;
  const [r, g, b] = [n(0), n(2), n(4)];
  return (Math.max(r, g, b) + Math.min(r, g, b)) / 2;
}

/** 문자열이 들어가는 자리의 이름(style 키·JSX 속성) — 조건식·괄호·?? 를 거슬러 올라간다. */
function slotName(node) {
  let n = node;
  for (let i = 0; i < 8 && n.parent; i++) {
    const p = n.parent;
    if (ts.isConditionalExpression(p) || ts.isParenthesizedExpression(p) || ts.isAsExpression(p) ||
        (ts.isBinaryExpression(p) && [ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.AmpersandAmpersandToken].includes(p.operatorToken.kind)) ||
        ts.isTemplateSpan(p) || ts.isTemplateExpression(p) || ts.isJsxExpression(p)) { n = p; continue; }
    if (ts.isPropertyAssignment(p) && p.initializer === n) return p.name.getText().replace(/["']/g, "");
    if (ts.isJsxAttribute(p)) return p.name.getText();
    return null;
  }
  return null;
}

function roleFor(slot, hex) {
  if (slot && TEXT_KEYS.has(slot)) return "t";
  if (slot && BG_KEYS.has(slot)) return "b";
  if (slot && BORDER_KEY.test(slot)) return "d";
  return lightness(hex) > 0.8 ? "b" : "t";   // 칠·선·상수 표 — 밝기로
}

function files(p) {
  const st = fs.statSync(p);
  if (st.isFile()) return /\.(tsx?|jsx?)$/.test(p) ? [p] : [];
  return fs.readdirSync(p).flatMap((x) => files(path.join(p, x)));
}

let total = 0;
for (const f of process.argv.slice(2).flatMap(files)) {
  const src = fs.readFileSync(f, "utf8");
  const sf = ts.createSourceFile(f, src, ts.ScriptTarget.Latest, true, f.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const edits = [];
  const visit = (n) => {
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n) || ts.isTemplateHead(n) || ts.isTemplateMiddle(n) || ts.isTemplateTail(n)) {
      const start = n.getStart(sf), end = n.getEnd();
      const raw = src.slice(start, end);
      if (!raw.includes("var(") && HEX.test(raw)) {
        HEX.lastIndex = 0;
        const slot = slotName(n);
        edits.push([start, end, raw.replace(HEX, (_, h) => `var(--hx-${roleFor(slot, full(h))}-${full(h)})`)]);
      }
      HEX.lastIndex = 0;
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  if (!edits.length) continue;
  let out = src;
  for (const [s, e, r] of edits.sort((a, b) => b[0] - a[0])) out = out.slice(0, s) + r + out.slice(e);
  fs.writeFileSync(f, out);
  total += edits.length;
  console.log(`${f}: ${edits.length}`);
}
console.log(`문자열 ${total}개를 바꿨다`);
