// 대표 조작의 '입력 → 다음 그림' 시간(Event Timing — INP 의 근사). 쓰임: node scripts/ux-measure/interact.mjs <결과.json>
// 조작마다: 사건 기록을 비우고 → 조작 → 500ms 뒤 가장 긴 사건 시간(ms · 8ms 눈금 · 16ms 미만은 0 으로 적힘) + 긴 작업 합.
import fs from "node:fs";
import { H, context, launch, login, open, outArg } from "./lib.mjs";
const OUT = outArg("쓰임: node scripts/ux-measure/interact.mjs <결과.json>");
const INIT = () => { window.__ev = []; window.__long = 0;
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__ev.push([e.name, e.duration, e.interactionId || 0]); }).observe({ type: "event", buffered: true, durationThreshold: 16 }); } catch {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__long += e.duration; }).observe({ type: "longtask", buffered: true }); } catch {} };
const browser = await launch();
const token = await login(browser);
const res = [];
async function session(route, steps, prep) {
  const ctx = await context(browser, { token });
  await ctx.addInitScript(INIT);
  const page = await ctx.newPage(); if (prep) await prep(page);
  await open(page, route, 1200);
  for (const [label, act] of steps) {
    let rec = { route, label };
    try {
      await page.evaluate(() => { window.__ev = []; window.__long = 0; });
      const dom0 = await page.evaluate(() => document.querySelectorAll("*").length);
      const t0 = Date.now(); await act(page); await page.waitForTimeout(500);
      const r = await page.evaluate(() => ({ ev: window.__ev, long: Math.round(window.__long), dom: document.querySelectorAll("*").length }));
      const inter = r.ev.filter((e) => e[2]); const worst = (inter.length ? inter : r.ev).sort((x, y) => y[1] - x[1])[0];
      rec = { ...rec, worstMs: worst ? Math.round(worst[1]) : 0, worstType: worst ? worst[0] : "-", longMs: r.long, dom0, dom1: r.dom, wall: Date.now() - t0 - 500 };
    } catch (e) { rec.error = String(e).slice(0, 120); }
    res.push(rec); console.log(JSON.stringify(rec));
  }
  await ctx.close();
}
const click = (sel, nth = 0) => async (p) => { await p.locator(sel).nth(nth).click({ timeout: 8000 }); };
await session("/screener", [
  ["표 머리 눌러 정렬(시가총액)", click(".bsc-table th.sortable button", 1)], ["정렬 뒤집기", click(".bsc-table th.sortable button", 1)],
  ["다음 쪽", async (p) => { await p.locator(".bsc-pager button").last().click({ timeout: 8000 }); }], ["줄 고르기", click(".bsc-table tbody tr", 3)],
  ["찾기 열기(/)", async (p) => { await p.keyboard.press("Escape"); await p.locator("body").click({ position: { x: 700, y: 5 } }).catch(() => {}); await p.keyboard.press("/"); }],
  ["찾기에 글자", async (p) => { await p.keyboard.type("삼성", { delay: 30 }); }], ["찾기 닫기", async (p) => { await p.keyboard.press("Escape"); }],
]);
await session("/macro", [["탭 2", click(".mc-tab", 1)], ["탭 3", click(".mc-tab", 2)], ["탭 4", click(".mc-tab", 3)], ["탭 1", click(".mc-tab", 0)]]);
await session("/allocation", [
  ["노드 고르기", click(".pg-node", 0)], ["다른 노드 고르기", click(".pg-node", 2)], ["명령 팔레트 열기(Ctrl+K)", async (p) => { await p.keyboard.press("Control+k"); }],
  ["팔레트에 글자", async (p) => { await p.keyboard.type("백테", { delay: 30 }); }], ["팔레트 닫기", async (p) => { await p.keyboard.press("Escape"); }],
  ["화면 맞춤", click(".react-flow__controls-fitview")], ["확대(휠)", async (p) => { await p.mouse.move(700, 450); await p.mouse.wheel(0, -400); }],
]);
await session(`/backtest/runs/${H.STUB_RUN_ID}/results`, [["전체 지표 펼치기", click(".rs-all > summary")]], (p) => H.stubCompletedRun(p));
await session("/backtest/intraday", [["배치 메뉴 열기", click(".ws-open")], ["메뉴 닫기", async (p) => { await p.keyboard.press("Escape"); }]]);
await session("/insights?code=005930", [["아래로 굴리기", async (p) => { await p.mouse.move(800, 500); await p.mouse.wheel(0, 1500); }]]);
fs.writeFileSync(OUT, JSON.stringify(res, null, 1));
await browser.close();
