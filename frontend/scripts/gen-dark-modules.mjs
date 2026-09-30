#!/usr/bin/env node
/**
 * BS5 — 레거시 모듈 다크 규칙 생성기
 * ==========================================================================
 * `src/app/globals.css` 의 ★다크가 없는 레거시 규칙★(대시보드·스크리너·백테스터·매크로·기업·위험·데이터 화면)에서
 * 색을 글자로 적어 둔 선언만 골라, 같은 선택자 앞에 `.dark ` 를 붙인 규칙을 `src/app/dark-modules.css` 로 낸다.
 *
 * ★라이트는 바뀌지 않는다(구조적으로)★ 나오는 규칙은 모두 `.dark` 아래라 `html.dark` 가 없으면 하나도 적용되지 않는다.
 * `html.dark` 는 `DARK_READY` 화면에서만 켜진다(shared/theme). E2E `dark-modules.spec.ts` 가 라이트 계산 스타일 골든으로 잰다.
 *
 * ★색 바꾸는 규칙(명도 뒤집기)★ — 속성의 역할로 나눈다:
 *   바탕(background·그라데이션 칸): 밝은 무채색 → zinc 어두운 계단 · 밝은 옅은 유채색(알림 바탕) → 같은 색상각의 어두운 칠 ·
 *                                   중간·어두운 색(단추 등)은 그대로 · 검은 반투명(눌림·겹침) → 흰 반투명
 *   테두리: 밝은 무채색 → 어두운 선 · 옅은 유채색 → 어두운 칠 · 나머지 그대로
 *   글자·선(color·fill·stroke·caret·text-decoration): 어두운 무채색 → 밝은 계단 · 어두운 유채색 → 같은 색상각을 밝게(명도 0.74)
 *   그림자는 그대로다(검은 그림자는 어두운 바탕에서도 뜻이 같다).
 * 생성 뒤 남는 대비 결함은 사람이 `globals.css` 의 "BS5 손질" 절에서 고친다(생성 파일은 손대지 않는다 — 다시 만들면 사라진다).
 *
 * 실행: node scripts/gen-dark-modules.mjs  (frontend 에서)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import postcss from "postcss";

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "src", "app", "globals.css");
const BEGIN = "/* BS5-GEN:BEGIN */", END = "/* BS5-GEN:END */";

/** 이미 다크를 설계해 둔 표면 — 손대지 않는다. */
const SKIP = /\.dark\b|\.pg-|\.aas-|\.brun-results|\.set-|\.set\b|\.pf-|\.shad-|\.devui-|:root|^html|^body|\.cockpit|\.glass-card-dark/;

/** 다크에서 밝아지는 강조·상태 토큰 — 이것으로 채운 바탕 위 흰 글자는 --on-accent 로. */
const ACCENT_FILL = /var\(--(t-accent|bs-primary|primary|bs-danger|bs-success|danger|success|color-bull|color-bear|accent-hover|bs-link-color)\b/;
const TEXT = new Set(["color", "fill", "stroke", "caret-color", "text-decoration-color", "-webkit-text-fill-color", "column-rule-color"]);
const BG = new Set(["background", "background-color", "background-image"]);
const BORDER = /^(border(-(top|right|bottom|left|block|inline)(-(start|end))?)?(-color)?|outline(-color)?)$/;

// ── 색 읽기·쓰기 ─────────────────────────────────────────────────────────────
const NAMED = { white: [255, 255, 255, 1], black: [0, 0, 0, 1] };
const COLOR_RE = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?:white|black)\b/g;

function parse(s) {
  s = s.trim().toLowerCase();
  if (NAMED[s]) return [...NAMED[s]];
  if (s[0] === "#") {
    let h = s.slice(1);
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join("");
    if (h.length !== 6 && h.length !== 8) return null;
    const n = (i) => parseInt(h.slice(i, i + 2), 16);
    return [n(0), n(2), n(4), h.length === 8 ? n(6) / 255 : 1];
  }
  const m = s.match(/rgba?\(([^)]*)\)/);
  if (!m) return null;
  const parts = m[1].split(/[\s,/]+/).filter(Boolean);
  if (parts.length < 3) return null;
  const num = (x) => (x.endsWith("%") ? (parseFloat(x) / 100) * 255 : parseFloat(x));
  const a = parts[3] === undefined ? 1 : parts[3].endsWith("%") ? parseFloat(parts[3]) / 100 : parseFloat(parts[3]);
  return [num(parts[0]), num(parts[1]), num(parts[2]), a];
}

function toHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
  if (mx === mn) return [0, 0, l];
  const d = mx - mn, s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
  const h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s, l];
}
function fromHsl(h, s, l) {
  const k = (n) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)].map((x) => Math.round(Math.max(0, Math.min(1, x)) * 255));
}
function fmt([r, g, b], a) {
  const hex = "#" + [r, g, b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return a >= 1 ? hex : `rgb(${r} ${g} ${b} / ${+a.toFixed(3)})`;
}

/** 역할별 다크 색. 같으면 null(바꿀 필요 없음). */
export function darkColor(src, role) {
  const c = parse(src);
  if (!c) return null;
  const [r, g, b, a] = c;
  const [h, s, l] = toHsl([r, g, b]);
  const neutral = s < 0.12 || (l > 0.97 || l < 0.03);
  let out = null;
  if (role === "bg") {
    if (a < 1 && l < 0.2 && neutral) out = [[255, 255, 255], Math.min(1, a * 1.4)];          // 검은 반투명 겹침 → 흰 반투명
    else if (a < 1 && l > 0.9 && neutral) out = [[24, 24, 27], a];                              // 흰 유리 → 어두운 유리
    else if (neutral && l >= 0.6) out = [fromHsl(240, 0.06, 0.1 + (1 - l) * 0.6), a];         // 밝은 무채색 → zinc 계단
    else if (!neutral && l > 0.82) out = [fromHsl(h, Math.min(s, 0.5) * 0.7, 0.13 + (1 - l) * 0.35), a];  // 옅은 알림 바탕
  } else if (role === "border") {
    if (neutral && l >= 0.6) out = [fromHsl(240, 0.05, 0.16 + (1 - l) * 0.5), a];
    else if (!neutral && l > 0.8) out = [fromHsl(h, Math.min(s, 0.5) * 0.7, 0.24), a];
    else if (!neutral && l < 0.45) out = [fromHsl(h, s, 0.6), a];
  } else if (role === "text") {
    if (neutral && l <= 0.6) out = [fromHsl(240, 0.05, 0.96 - l * 0.7), a];
    else if (!neutral && l < 0.72) out = [fromHsl(h, Math.min(1, s), 0.74), a];   // 0.70 은 순청색에서 4.26:1 이었다
  }
  if (!out) return null;
  const v = fmt(out[0], out[1]);
  return v.toLowerCase() === src.trim().toLowerCase() ? null : v;
}

function roleOf(prop) {
  if (TEXT.has(prop)) return "text";
  if (BG.has(prop)) return "bg";
  if (BORDER.test(prop)) return "border";
  return null;
}

function mapValue(value, role) {
  let changed = false;
  const v = value.replace(COLOR_RE, (m) => {
    const d = darkColor(m, role);
    if (d) { changed = true; return d; }
    return m;
  });
  return changed ? v : null;
}

// ── 생성 ─────────────────────────────────────────────────────────────────────
const text = fs.readFileSync(SRC, "utf8");
const bi = text.indexOf(BEGIN), ei = text.indexOf(END);
if (bi < 0 || ei < bi) throw new Error("globals.css 에 생성 구역 표시(BS5-GEN:BEGIN/END)가 없다");
// 생성 구역 자체는 읽지 않는다(다시 만들 때 자기 출력을 입력으로 삼지 않게).
const root = postcss.parse(text.slice(0, bi) + text.slice(ei + END.length));
const out = postcss.root();
let rules = 0, decls = 0;

root.walkRules((rule) => {
  if (rule.parent?.type === "atrule" && /keyframes/.test(rule.parent.name)) return;
  const sels = rule.selectors.filter((s) => !SKIP.test(s));
  if (!sels.length) return;
  const nd = [];
  rule.walkDecls((d) => {
    const role = roleOf(d.prop);
    if (!role) return;
    const mv = mapValue(d.value, role);
    if (mv) nd.push(postcss.decl({ prop: d.prop, value: mv, important: d.important }));
  });
  // 채운 강조색·상태색 위 흰 글자 — 다크의 강조·상태색은 글자로 읽히게 밝아서 흰 글자가 2.3~3.6:1 이 된다.
  // 같은 규칙이 그 토큰으로 바탕을 칠하고 흰 글자를 쓰면 다크에서는 --on-accent(어두운 글자)로 바꾼다.
  let fill = false, white = null;
  rule.walkDecls((d) => {
    if (BG.has(d.prop) && ACCENT_FILL.test(d.value)) fill = true;
    if (d.prop === "color" && /^(#fff|#ffffff|white|rgb\(255,\s*255,\s*255\))$/i.test(d.value.trim())) white = d;
  });
  if (fill && white) nd.push(postcss.decl({ prop: "color", value: "var(--on-accent)", important: white.important }));
  if (!nd.length) return;
  // ★:where(.dark) — 특이도 0★ `.dark ` 를 그냥 붙이면 바탕 규칙(.bsc-pager button)의 다크 짝이 라이트의 상태 규칙
  // (.bsc-pager button.on — 색을 토큰으로 써서 짝이 없다)보다 특이도가 같거나 높아져 뒤에 온 짝이 이겼다(켜진 단추가 꺼진
  // 바탕으로 칠해짐 — 감사가 찾음). 특이도를 원래 그대로 두면 라이트와 같은 순서로 겨루고, 같은 특이도에서는 뒤에 오는 짝이 이긴다.
  const r = postcss.rule({ selectors: sels.map((s) => `:where(.dark) ${s}`) });
  nd.forEach((d) => r.append(d));
  rules++; decls += nd.length;
  // @media 등은 같은 감싸개 안에 둔다.
  let target = out;
  const chain = [];
  for (let p = rule.parent; p && p.type === "atrule"; p = p.parent) chain.unshift(p);
  for (const at of chain) {
    const key = `${at.name} ${at.params}`;
    let found = target.nodes.find((n) => n.type === "atrule" && `${n.name} ${n.params}` === key);
    if (!found) { found = postcss.atRule({ name: at.name, params: at.params }); target.append(found); }
    target = found;
  }
  target.append(r);
});

// ── 인라인 hex 토큰(--hx-*) — hex-to-tokens.mjs 가 TSX 문자열을 var(--hx-xxxxxx) 로 바꾼 것들의 짝 ─────────────
// 라이트 = 같은 hex(한 글자도 다르지 않다) · 다크 = 위와 같은 규칙. 역할(t 글자·b 바탕·d 테두리)은 코드 변환이 이름에 실었다.
const used = new Set();
const scan = (d) => { for (const x of fs.readdirSync(d)) { const q = path.join(d, x); const st = fs.statSync(q);
  if (st.isDirectory()) scan(q); else if (/\.(tsx?|jsx?)$/.test(x)) for (const m of fs.readFileSync(q, "utf8").matchAll(/var\(--hx-([tbd])-([0-9a-f]{6})\)/g)) used.add(`${m[1]}-${m[2]}`); } };
scan(path.join(here, "..", "src"));
if (used.size) {
  const hx = [...used].sort();
  const light = postcss.rule({ selector: ":root" }), dark = postcss.rule({ selector: ".dark" });
  const ROLE = { t: "text", b: "bg", d: "border" };
  for (const k of hx) {
    const [r, h] = k.split("-");
    light.append(postcss.decl({ prop: `--hx-${k}`, value: `#${h}` }));
    dark.append(postcss.decl({ prop: `--hx-${k}`, value: darkColor(`#${h}`, ROLE[r]) ?? `#${h}` }));
  }
  out.prepend(dark); out.prepend(light);
}

const head = `/* ★생성 구역 — 손대지 마세요★ scripts/gen-dark-modules.mjs 가 이 파일의 나머지에서 만든다(BS5).
   레거시 모듈 규칙의 글자로 적힌 색에 대한 다크 짝 — 모두 .dark 아래라 라이트에는 적용되지 않는다.
   규칙 ${rules}개 · 선언 ${decls}개 · 인라인 hex 토큰 ${used.size}개. 남는 결함은 아래 "BS5 손질" 절에서 고친다. */\n`;
fs.writeFileSync(SRC, text.slice(0, bi) + BEGIN + "\n" + head + out.toString() + "\n" + text.slice(ei));
console.log(`globals.css 생성 구역: rules=${rules} decls=${decls}`);
