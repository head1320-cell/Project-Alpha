// CSS 사용 범위(읽기 전용) — 화면 23 × (라이트 · 다크)의 첫 그림에서 한 번이라도 쓰인 규칙의 글자 수 비율.
// 쓰임: node scripts/ux-measure/csscov.mjs <결과.json>
// ★상한★: 열지 않은 시트 · 메뉴 · 호버 · 오류 상태 · 판 배치를 켠 화면의 규칙은 '안 쓰임'으로 잡힌다 — 죽은 CSS 의 수가 아니라 그 위쪽 끝이다.
import fs from "node:fs";
import { H, context, launch, login, open, outArg } from "./lib.mjs";
const OUT = outArg("쓰임: node scripts/ux-measure/csscov.mjs <결과.json>");
const ROUTES = [["/dashboard", 1], ["/screener", 1], ["/backtest", 1], [`/backtest/runs/${H.STUB_RUN_ID}/results`, 1], ["/backtest/intraday", 1], ["/macro", 1], ["/macro/agentic-mcp", 1], ["/macro/causal-deepm", 1], ["/insights?code=005930", 1], ["/risk-tools", 1],
  ["/allocation", 1], ["/clients", 1], ["/my-account", 1], ["/my-account/journal", 1], ["/admin/data", 1], ["/admin/live-trading", 1], ["/admin/realism", 1], ["/derivatives", 1], ["/settings", 1], ["/builder", 1], ["/dev/ui", 1], ["/", 0], ["/login", 0]];
const b = await launch();
const token = await login(b);
const sheets = new Map();   // url → { len, used:Set of "s-e", perRoute }
const perRoute = [];
for (const [route, authed] of ROUTES) for (const theme of ["light", "dark"]) {
  const ctx = await context(b, { token: authed ? token : null, theme });
  const page = await ctx.newPage(); if (route.includes("/results")) await H.stubCompletedRun(page);
  await page.coverage.startCSSCoverage({ resetOnNavigation: false });
  await open(page, route, 700);
  await page.evaluate(async () => { const m = document.querySelector(".terminal-main") || document.scrollingElement; for (let y = 0; y < m.scrollHeight; y += 700) { m.scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); } m.scrollTo(0, 0); });
  const cov = await page.coverage.stopCSSCoverage(); let tot = 0, used = 0;
  for (const e of cov) { if (!e.url.includes("/_next/")) continue; const key = e.url.replace(/^https?:\/\/[^/]+/, ""); const s = sheets.get(key) || { len: e.text.length, text: e.text, ranges: [] }; for (const r of e.ranges) s.ranges.push([r.start, r.end]); sheets.set(key, s);
    tot += e.text.length; used += e.ranges.reduce((x, r) => x + r.end - r.start, 0); }
  perRoute.push({ route, theme, cssBytes: tot, usedBytes: used, share: tot ? +(used / tot).toFixed(3) : null }); await ctx.close();
}
const summary = []; let T = 0, U = 0;
for (const [url, s] of sheets) { const mark = new Uint8Array(s.len); for (const [x, y] of s.ranges) mark.fill(1, x, y); const u = mark.reduce((p, c) => p + c, 0); T += s.len; U += u;
  // 안 쓰인 규칙의 클래스 접두어(가족)
  const fam = {}; let i = 0; while (i < s.len) { if (!mark[i]) { let j = i; while (j < s.len && !mark[j]) j++; const chunk = s.text.slice(i, j); for (const m of chunk.matchAll(/\.([a-z]+)[-_]/g)) fam[m[1]] = (fam[m[1]] || 0) + 1; i = j; } else i++; }
  summary.push({ url: url.slice(-40), len: s.len, used: u, share: +(u / s.len).toFixed(3), unusedFamilies: Object.entries(fam).sort((x, y) => y[1] - x[1]).slice(0, 14) }); }
fs.writeFileSync(OUT, JSON.stringify({ total: T, used: U, share: +(U / T).toFixed(3), sheets: summary, perRoute }, null, 1));
console.log("합(전 화면 · 두 테마의 합집합): CSS", T, "자 가운데 쓰인", U, `(${(U / T * 100).toFixed(1)}%)`); for (const x of summary) console.log(" ", x.url, x.len, x.share, JSON.stringify(x.unusedFamilies));
const pr = perRoute.filter((r) => r.theme === "light").map((r) => `${r.route.slice(0, 22)} ${(r.share * 100).toFixed(0)}%`); console.log("화면별(라이트) 쓰인 비율:", pr.join(" · "));
await b.close();
