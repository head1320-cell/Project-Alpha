#!/usr/bin/env node
/**
 * 라이트 골든 키 단위 diff (BU0a) — 의도한 라이트 변경이 **어느 범위**를 건드렸는지 커밋 전에 본다.
 *
 *   node scripts/golden-diff.mjs <이전.json> [<이후.json>]          (이후 기본값: e2e/golden/light-styles.json)
 *   node scripts/golden-diff.mjs --rev <git-rev> [<이후.json>]      (이전을 git 에서 꺼낸다)
 *   node scripts/golden-diff.mjs --unscoped <이전.json> [<이후.json>] (범위 접두사를 떼고 같은지 — BU0a 다시 뜨기 확인용)
 *
 * 출력: 라우트 × 범위(shell·main·frame)마다 더해진 키 · 사라진 키 · 새 스타일 조합 수(+ 예시 몇 개).
 * `--expect-scope shell` 처럼 주면 그 밖의 범위에 새 조합이 하나라도 있으면 종료 코드 1 — 셸만 바꾼 커밋의 문지기.
 * `--allow-keys <정규식>` 은 범위 밖이라도 이 키는 바뀌어도 된다고 **이름으로** 연다(BU0 — 브레드크럼 `.tcrumb*` 는 본문 안에
 * 그려져 `main:` 키다). 열린 키는 출력에 `(허용)` 으로 따로 센다 — 조용히 빠지지 않는다.
 * `--expect-routes /dashboard,/screener` 는 그 밖의 라우트에 더한 키·새 조합이 하나라도 있으면 종료 코드 1 — 모듈 한 개만 바꾼
 * 커밋의 문지기(BU1~). `--expect-scope` 와 함께 쓰면 둘 다 지켜야 한다.
 * ★사라진 키·조합은 실패로 세지 않는다★ — 늦게 그려진 요소(데이터 지연)는 바뀐 것이 아니다(골든 테스트와 같은 규칙).
 */
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT = path.join(here, "..", "e2e", "golden", "light-styles.json");
const args = process.argv.slice(2);
const flag = (name) => { const i = args.indexOf(name); if (i < 0) return null; const v = args[i + 1]; args.splice(i, 2); return v; };
const bool = (name) => { const i = args.indexOf(name); if (i < 0) return false; args.splice(i, 1); return true; };

const rev = flag("--rev");
const expectScope = flag("--expect-scope");
const expectRoutes = (() => { const v = flag("--expect-routes"); return v ? new Set(v.split(",").map((x) => x.trim()).filter(Boolean)) : null; })();
const allowRe = (() => { const v = flag("--allow-keys"); return v ? new RegExp(v) : null; })();
const unscoped = bool("--unscoped");
const read = (f) => JSON.parse(readFileSync(f, "utf8"));
const before = rev
  ? JSON.parse(execSync(`git show ${rev}:frontend/e2e/golden/light-styles.json`, { cwd: path.join(here, "..", ".."), encoding: "utf8" }))
  : read(args.shift() ?? usage());
const after = read(args.shift() ?? DEFAULT);

function usage() {
  console.error("사용: golden-diff.mjs <이전.json> [<이후.json>] | --rev <git-rev> [<이후.json>] [--expect-scope shell] [--allow-keys 정규식] [--expect-routes /a,/b] [--unscoped]");
  process.exit(2);
}
const scopeOf = (k) => (/^(shell|main|frame):/.exec(k)?.[1] ?? "(범위 없음)");
const strip = (k) => k.replace(/^(shell|main|frame):/, "");
/** 범위를 떼고 합친다 — 같은 태그.클래스가 두 범위에 있으면 조합을 합집합으로. */
function unscope(route) {
  const out = {};
  for (const [k, v] of Object.entries(route ?? {})) out[strip(k)] = [...new Set([...(out[strip(k)] ?? []), ...v])].sort();
  return out;
}

let bad = 0;
const routes = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
for (const r of routes) {
  const a = unscoped ? unscope(before[r]) : (before[r] ?? {});
  const b = unscoped ? unscope(after[r]) : (after[r] ?? {});
  const by = {};
  const bucket = (k) => (unscoped ? "(전체)" : scopeOf(k)) + (allowRe && scopeOf(k) !== expectScope && allowRe.test(k) ? " (허용)" : "");
  const bump = (k, field, ex) => { const s = (by[bucket(k)] ??= { added: 0, removed: 0, combos: 0, ex: [] });
                                   s[field] += 1; if (ex && s.ex.length < 3) s.ex.push(ex); };
  for (const k of Object.keys(b)) if (!(k in a)) bump(k, "added", `+ ${k}`);
  for (const k of Object.keys(a)) if (!(k in b)) bump(k, "removed");
  for (const k of Object.keys(b)) if (k in a) for (const v of b[k]) if (!a[k].includes(v)) bump(k, "combos", `~ ${k} :: ${v}`);
  const lines = Object.entries(by);
  if (!lines.length) { console.log(`${r}  변화 없음`); continue; }
  for (const [scope, s] of lines) {
    console.log(`${r}  [${scope}] 더함 ${s.added} · 사라짐 ${s.removed} · 새 조합 ${s.combos}`);
    for (const e of s.ex) console.log(`    ${e}`);
    if (expectScope && scope !== expectScope && !scope.endsWith(" (허용)") && (s.combos || s.added)) bad += 1;
    if (unscoped && s.combos) bad += 1;
    if (expectRoutes && !expectRoutes.has(r) && (s.combos || s.added)) bad += 1;
  }
}
if (bad) { console.error(`\n✗ 기대 밖 변화 ${bad}곳`); process.exit(1); }
