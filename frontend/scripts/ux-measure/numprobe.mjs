// 숫자 글꼴 재기 — 본문 글꼴(Pretendard)의 고정폭 숫자(tnum)가 실제로 고정폭인지, 고정폭 글꼴(JetBrains Mono)보다 얼마나 좁은지.
// 쓰임: node scripts/ux-measure/numprobe.mjs <결과.json>   (서버가 떠 있어야 한다 — 글꼴은 앱이 같은 서버에서 준다)
import fs from "node:fs";
import { BASE, context, launch, login, outArg } from "./lib.mjs";
const out = outArg("쓰임: node scripts/ux-measure/numprobe.mjs <결과.json>");
const b = await launch();
const ctx = await context(b, { token: await login(b), deviceScaleFactor: 1 });
const page = await ctx.newPage();
await page.goto(`${BASE}/screener`, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
const res = await page.evaluate(async () => {
  const cs = getComputedStyle(document.documentElement);
  const body = cs.getPropertyValue("--tx-font").trim();
  const mono = cs.getPropertyValue("--t-mono").trim();
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;visibility:hidden;white-space:nowrap";
  document.body.appendChild(host);
  const SAMPLES = ["0000000000", "1111111111", "8888888888", "1,234,567.89", "-12.34%", "+1,234", "005930", "12,345,678,900"];
  const rows = [];
  for (const [name, fam, fv] of [["본문 글꼴 · 비례폭 숫자", body, "normal"], ["본문 글꼴 · 고정폭 숫자(tnum)", body, "tabular-nums"], ["고정폭 글꼴", mono, "tabular-nums"]]) {
    for (const px of [11, 12, 13, 14]) {
      const w = {};
      for (const s of SAMPLES) {
        const el = document.createElement("span");
        el.textContent = s; el.style.cssText = `font-family:${fam};font-size:${px}px;font-variant-numeric:${fv};font-weight:500`;
        host.appendChild(el); w[s] = +el.getBoundingClientRect().width.toFixed(2); el.remove();
      }
      rows.push({ name, px, w });
    }
  }
  host.remove();
  const loaded = [...document.fonts].filter((f) => f.status === "loaded").map((f) => `${f.family} ${f.weight} ${f.unicodeRange.slice(0, 24)}`);
  return { body, mono, rows, loaded: [...new Set(loaded.map((s) => s.split(" U+")[0]))].slice(0, 12), nLoaded: loaded.length };
});
fs.writeFileSync(out, JSON.stringify(res, null, 1));
for (const row of res.rows) console.log(row.name.padEnd(22), row.px, JSON.stringify(row.w));
console.log("loaded", res.nLoaded, res.loaded);
await b.close();
