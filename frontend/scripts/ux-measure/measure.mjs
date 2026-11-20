// 화면 재기(읽기 전용) — 라우트 × 뷰포트 × 테마. 빌드한 화면 서버 + mock API 서버가 떠 있어야 한다(README.md).
// 쓰임: node scripts/ux-measure/measure.mjs <결과 폴더> [라우트 이름 정규식]
// 결과: <폴더>/<이름>__<변형>.json(잰 값 전부) · .png(그 순간의 그림) · summary.tsv(한 줄 요약)
import fs from "node:fs";
import path from "node:path";
import { BASE, H, context, launch, login, outArg } from "./lib.mjs";
const OUT = outArg("쓰임: node scripts/ux-measure/measure.mjs <결과 폴더> [라우트 이름 정규식]");
const ONLY = process.argv[3] ? new RegExp(process.argv[3]) : null;
fs.mkdirSync(OUT, { recursive: true });
const ROUTES = [  // [이름, 경로, 로그인, 묶음, 단(작업 · 해석 · 설명)]
  ["home", "/dashboard", true, "home", "해석"], ["screener", "/screener", true, "screener", "작업"],
  ["backtest", "/backtest", true, "backtester", "작업"], ["bt-results", `/backtest/runs/${H.STUB_RUN_ID}/results`, true, "backtester", "작업"],
  ["intraday", "/backtest/intraday", true, "intraday", "작업"],
  ["macro", "/macro", true, "macro", "해석"], ["macro-views", "/macro/agentic-mcp", true, "macro", "해석"], ["macro-causal", "/macro/causal-deepm", true, "macro", "해석"],
  ["insights", "/insights?code=005930", true, "company", "해석"], ["risk", "/risk-tools", true, "risk", "작업"],
  ["allocation", "/allocation", true, "canvas", "해석"], ["clients", "/clients", true, "clients", "설명"],
  ["my-account", "/my-account", true, "my-account", "작업"], ["journal", "/my-account/journal", true, "my-account", "작업"],
  ["admin-data", "/admin/data", true, "data", "작업"], ["live", "/admin/live-trading", true, "admin", "작업"], ["realism", "/admin/realism", true, "admin", "작업"],
  ["derivatives", "/derivatives", true, "derivatives", "해석"], ["settings", "/settings", true, "shell", "설명"], ["builder", "/builder", true, "canvas", "해석"],
  ["dev-ui", "/dev/ui", true, "shell", "설명"], ["landing", "/", false, "landing", "설명"], ["login", "/login", false, "landing", "설명"],
];
const VARIANTS = [  // [이름, 폭, 높이, 테마, 초점 걷기, 줄인 모션]
  ["1440-light", 1440, 900, "light", true, false], ["1440-dark", 1440, 900, "dark", false, false],
  ["1920-light", 1920, 1080, "light", false, false], ["1280-light", 1280, 800, "light", false, false], ["390-light", 390, 844, "light", false, false],
  ["1440-reduced", 1440, 900, "light", false, true],
];
// 내 계좌: 연결된 계좌가 있는 상태(응답은 정한 모의 — workspace-account.spec 과 같은 꼴)
const acc = { account_id: "ba_1", label: "내 모의 계좌", is_paper: true, account_prdt: "01", app_key_last4: "cdef", account_no_masked: "****5678", created_at: "2026-10-09T08:00:00" };
const order = (i, status) => ({ client_order_id: `CO-${i}`, ticker: i % 2 ? "005930" : "000660", side: i % 3 ? "BUY" : "SELL", quantity: 10 + i, price: 71000 + i * 100, status, execution_mode: "SHADOW", reason_code: null, error_message: null, created_at: `2026-11-20T0${i % 9}:1${i % 6}:00+00:00`, strategy_id: null, source: "manual" });
const ORDERS = Array.from({ length: 40 }, (_, i) => order(i + 1, ["SHADOW_LOGGED", "SUBMITTED", "REJECTED"][i % 3]));
async function mockAccount(page) {
  await page.route("**/api/v1/broker-accounts**", async (r) => {
    const req = r.request(); const url = new URL(req.url());
    const p = url.pathname.slice(url.pathname.indexOf("/api/v1/broker-accounts") + "/api/v1/broker-accounts".length); const m = req.method();
    if (p === "" && m === "GET") return r.fulfill({ json: { accounts: [acc] } });
    const tail = p.split("/").slice(2).join("/");
    if (tail === "mode" && m === "GET") return r.fulfill({ json: { mode: "SHADOW", changed_by: null, last_mode_change: null } });
    if (tail === "kill-switch" && m === "GET") return r.fulfill({ json: { active: false, event: null } });
    if (tail === "live-readiness") return r.fulfill({ json: { account_id: "ba_1", ready: false, items: [{ key: "gate", ok: false, reason: "운영자가 실계좌 관문을 열지 않았습니다(선언 없음)." }] } });
    if (tail === "balance") return r.fulfill({ json: { account_id: "ba_1", practice: true, as_of: "2026-11-20T03:04:00+00:00", state: "ok", cash_krw: 100000000, evaluated_total: 102000000,
      positions: [{ ticker: "005930", quantity: 3, avg_price: 70100, current_price: 71000, eval_amount: 213000, pnl_pct: 1.28 }, { ticker: "000660", quantity: 2, avg_price: 132000, current_price: 130000, eval_amount: 260000, pnl_pct: -1.52 }] } });
    if (tail === "orders" && m === "GET") return r.fulfill({ json: { count: ORDERS.length, orders: ORDERS } });
    if (tail === "rule-runs" && m === "GET") return r.fulfill({ json: { available: true, reason: null, runs: [], mode: "SHADOW", kill_switch: false, gate: { mock: true }, limits: { runs: 3, tickers: 10, gap_minutes: 5 } } });
    return r.fulfill({ status: 404, json: { detail: "measure 가 정하지 않은 경로" } });
  });
}
const INIT = () => {
  window.__ux = { lcp: 0, cls: 0, long: 0, longN: 0, events: [] };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__ux.lcp = Math.max(window.__ux.lcp, e.startTime); }).observe({ type: "largest-contentful-paint", buffered: true }); } catch {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__ux.cls += e.value; }).observe({ type: "layout-shift", buffered: true }); } catch {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) { window.__ux.long += e.duration; window.__ux.longN += 1; } }).observe({ type: "longtask", buffered: true }); } catch {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__ux.events.push([e.name, Math.round(e.duration)]); }).observe({ type: "event", buffered: true, durationThreshold: 16 }); } catch {}
};
const COLLECT = () => {
  const vw = innerWidth, vh = innerHeight;
  const vis = (el) => { const r = el.getBoundingClientRect(); if (r.width <= 0 || r.height <= 0) return false; const cs = getComputedStyle(el); return cs.visibility !== "hidden" && cs.display !== "none" && cs.opacity !== "0"; };
  const inView = (r) => r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  const cls = (el) => (typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\s+/)[0] : el.tagName.toLowerCase());
  const fs = {}, ff = {}, fw = {}; let chars = 0, charsInView = 0;
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const s = w.currentNode.nodeValue.trim(); if (!s) continue; const el = w.currentNode.parentElement; if (!el || !vis(el) || el.closest("[hidden], [aria-hidden='true'], script, style, noscript")) continue;
    const cs = getComputedStyle(el); const k = String(Math.round(parseFloat(cs.fontSize) * 2) / 2);
    fs[k] = (fs[k] || 0) + s.length; chars += s.length; fw[cs.fontWeight] = (fw[cs.fontWeight] || 0) + s.length;
    const fam = /Mono/.test(cs.fontFamily) ? "mono" : /Pretendard/.test(cs.fontFamily.split(",")[0]) ? "pretendard" : cs.fontFamily.split(",")[0].replace(/["']/g, "");
    ff[fam] = (ff[fam] || 0) + s.length; if (inView(el.getBoundingClientRect())) charsInView += s.length;
  }
  const NUM = /^[\s+\-−–]?[\d,.]+\s*(%|%p|원|억|조|배|bp|주|건|일|회|초|분|개|x)?$/;
  const tables = [...document.querySelectorAll("table")].filter(vis).map((tb) => {
    const rows = [...tb.querySelectorAll("tbody tr")].filter(vis); const hs = rows.slice(0, 60).map((r) => r.getBoundingClientRect().height).sort((a, b) => a - b);
    const th = tb.querySelector("thead th"); const cells = [...tb.querySelectorAll("tbody td")].slice(0, 600); const numeric = cells.filter((c) => NUM.test(c.textContent.trim()));
    const td = cells[0] ? getComputedStyle(cells[0]) : null;
    let sc = "none"; for (let p = tb.parentElement; p && p !== document.body; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === "auto" || o === "scroll") { sc = p.scrollWidth > p.clientWidth + 1 ? "overflowing" : "fits"; break; } }
    return { cls: cls(tb), rows: rows.length, cols: tb.tHead?.rows[0]?.cells.length ?? rows[0]?.cells.length ?? 0, rowH: hs.length ? Math.round(hs[Math.floor(hs.length / 2)] * 10) / 10 : null,
      inView: rows.filter((r) => inView(r.getBoundingClientRect())).length,
      fullInView: rows.filter((r) => { const b = r.getBoundingClientRect(); return b.top >= 0 && b.bottom <= vh; }).length, sticky: !!th && (getComputedStyle(th).position === "sticky" || getComputedStyle(tb.tHead).position === "sticky"),
      tdFont: td?.fontSize ?? null, tdPadY: td ? parseFloat(td.paddingTop) + parseFloat(td.paddingBottom) : null, numeric: numeric.length,
      numRight: numeric.filter((c) => ["right", "end"].includes(getComputedStyle(c).textAlign)).length,
      numTabular: numeric.filter((c) => { const s = getComputedStyle(c); return s.fontVariantNumeric.includes("tabular-nums") || /Mono/.test(s.fontFamily); }).length,
      scroller: sc, sortable: tb.querySelectorAll("th[aria-sort], thead th button").length, named: !!(tb.caption || tb.getAttribute("aria-label") || tb.getAttribute("aria-labelledby")) };
  });
  const inter = [...document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=tab], [role=menuitem], [role=switch], [role=separator][tabindex]")].filter(vis);
  const small = inter.filter((el) => { const r = el.getBoundingClientRect(); return (r.width < 24 || r.height < 24) && !(el.tagName === "A" && getComputedStyle(el).display.startsWith("inline") && el.closest("p, li, td, span")); });
  const name = (el) => (el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || el.textContent.trim() || el.getAttribute("title") || el.getAttribute("placeholder") || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.textContent) || el.closest("label")?.textContent || "").trim();
  const unnamed = inter.filter((el) => !name(el) && el.getAttribute("type") !== "checkbox" && el.getAttribute("type") !== "radio");
  const main = document.querySelector(".terminal-main") || document.scrollingElement;
  const hx = [...document.querySelectorAll("h1, h2, h3, h4")].filter(vis).map((h) => +h.tagName[1]);
  let skips = 0; for (let i = 1; i < hx.length; i++) if (hx[i] - hx[i - 1] > 1) skips++;
  const anim = document.getAnimations().filter((a) => a.playState === "running");
  const nav = performance.getEntriesByType("navigation")[0];
  const box = (sel) => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; };
  const firstBlock = [...document.querySelectorAll(".terminal-main table, .terminal-main svg, .terminal-main .tx-sec, .terminal-main section")].filter(vis)[0];
  const shell = { header: box(".terminal-header"), side: box(".terminal-sidebar"), main: box(".terminal-main"), firstBlockY: firstBlock ? Math.round(firstBlock.getBoundingClientRect().top) : null,
    firstTableY: (() => { const t = [...document.querySelectorAll("table")].filter(vis)[0]; return t ? Math.round(t.getBoundingClientRect().top) : null; })() };
  // 색의 뜻 — 글자 색이 뜻 있는 색(등락 · 강조 · 상태)일 때: 그 글자가 숫자인가 · 누를 수 있는 것인가
  const hex = (c) => { const m = c.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/); if (!m || m[4] === "0") return null; return "#" + [m[1], m[2], m[3]].map((v) => (+v).toString(16).padStart(2, "0")).join(""); };
  const rs = getComputedStyle(document.documentElement); const SEM = {};
  for (const k of ["--tx-up", "--tx-up-ink", "--tx-down", "--tx-down-ink", "--tx-blue", "--tx-cta", "--tx-danger", "--tx-ok", "--tx-warn", "--color-bull", "--color-bear", "--color-caution", "--pg-blue", "--pg-blue-ink", "--pg-fail", "--pg-ok", "--t-accent"]) {
    const v = rs.getPropertyValue(k).trim().toLowerCase(); if (/^#[0-9a-f]{6}$/.test(v)) (SEM[v] = SEM[v] || []).push(k.replace(/^--/, "")); }
  const colorUse = {}; const w2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w2.nextNode()) { const s2 = w2.currentNode.nodeValue.trim(); if (!s2) continue; const el = w2.currentNode.parentElement; if (!el || !vis(el)) continue;
    const h = hex(getComputedStyle(el).color); if (!h || !SEM[h]) continue;
    const kind = NUM.test(s2) ? "숫자" : (el.closest("a[href], button, [role=tab], [role=button], summary") ? "누르는 것" : "글");
    const key = SEM[h].join("=") + " " + h + " | " + kind; const o = (colorUse[key] = colorUse[key] || { n: 0, sample: [] }); o.n++; if (o.sample.length < 3) o.sample.push(cls(el) + ":" + s2.slice(0, 14)); }
  const fills = {}; for (const el of [...document.querySelectorAll("button, a[href], [role=tab], .tx-chip, [class*=badge], [class*=chip]")].filter(vis)) { const h = hex(getComputedStyle(el).backgroundColor); if (h && SEM[h]) { const key = SEM[h].join("=") + " " + h + " | 바탕"; const o = (fills[key] = fills[key] || { n: 0, sample: [] }); o.n++; if (o.sample.length < 3) o.sample.push(cls(el)); } }
  const scen = [...document.querySelectorAll(".ca-scen-card")].filter(vis).map((e) => ({ cls: e.className, top: hex(getComputedStyle(e).borderTopColor) }));
  const top = (o, n = 6) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n);
  const uniq = (els, n = 8) => [...new Set(els.map(cls))].slice(0, n);
  return { url: location.pathname + location.search, dark: document.documentElement.classList.contains("dark"), dom: document.querySelectorAll("*").length, chars, charsInView,
    fontSizes: top(fs, 10), fontSizeKinds: Object.keys(fs).length, families: top(ff, 4), weights: top(fw, 5), tables,
    interactive: inter.length, smallTargets: small.length, smallSample: uniq(small), unnamed: unnamed.length, unnamedSample: uniq(unnamed),
    scrollPages: Math.round((main.scrollHeight / Math.max(1, main.clientHeight)) * 10) / 10, docOverflowX: document.documentElement.scrollWidth - vw,
    h1: hx.filter((x) => x === 1).length, headings: hx.length, headingSkips: skips, landmarks: { main: document.querySelectorAll("main, [role=main]").length, nav: document.querySelectorAll("nav, [role=navigation]").length },
    runningAnimations: anim.length, infiniteAnimations: anim.filter((a) => a.effect?.getComputedTiming().iterations === Infinity).length,
    perf: { ttfb: Math.round(nav?.responseStart ?? 0), dcl: Math.round(nav?.domContentLoadedEventEnd ?? 0), load: Math.round(nav?.loadEventEnd ?? 0), lcp: Math.round(window.__ux?.lcp ?? 0), cls: Math.round((window.__ux?.cls ?? 0) * 1000) / 1000, longMs: Math.round(window.__ux?.long ?? 0), longN: window.__ux?.longN ?? 0 },
    states: { status: document.querySelectorAll("[role=status]").length, alert: document.querySelectorAll("[role=alert]").length, skeleton: document.querySelectorAll("[class*=skeleton], [class*=Skeleton]").length },
    shell, colorUse, fills, scen, sem: SEM,
    provenance: { chips: document.querySelectorAll("[class*=perf-label], [class*=PerfLabel], [class*=evidence], [class*=grade], [class*=origin], .tx-chip").length, mockNotice: /연습용|합성|모의/.test(document.body.innerText) } };
};
const FOCUS = () => { const el = document.activeElement; if (!el || el === document.body) return null; const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
  return { el: (typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\s+/)[0] : el.tagName.toLowerCase()), name: (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 24),
    ring: (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== "none", inView: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth,
    covered: (() => { if (!(r.top >= 0 && r.bottom <= innerHeight)) return null; const c = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !(c && (el.contains(c) || c.contains(el))); })(),
    tag: el.tagName.toLowerCase(), h: Math.round(r.height), w: Math.round(r.width) }; };
const browser = await launch();
const token = await login(browser);
const summary = [];
for (const [name, route, authed, group, tier] of ROUTES) {
  if (ONLY && !ONLY.test(name)) continue;
  for (const [vname, vw, vh, theme, walk, reduced] of VARIANTS) {
    const ctx = await context(browser, { token: authed ? token : null, theme, viewport: { width: vw, height: vh }, reducedMotion: reduced ? "reduce" : "no-preference", deviceScaleFactor: 1 });
    await ctx.addInitScript(INIT);
    const page = await ctx.newPage(); const errors = [], bad = [], sizes = { js: 0, css: 0, jsN: 0 };
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 140)); }); page.on("pageerror", (e) => errors.push("PAGEERROR " + String(e).slice(0, 140)));
    page.on("response", (r) => { if (r.status() >= 400) bad.push(`${r.status()} ${new URL(r.url()).pathname.slice(0, 70)}`); });
    page.on("requestfinished", async (req) => { const t = req.resourceType(); if (t !== "script" && t !== "stylesheet") return; try { const s = await req.sizes(); if (t === "script") { sizes.js += s.responseBodySize; sizes.jsN++; } else sizes.css += s.responseBodySize; } catch {} });
    if (name === "my-account") await mockAccount(page);
    if (name === "bt-results") await H.stubCompletedRun(page);
    const t0 = Date.now(); let nav = "ok";
    try { await page.goto(BASE + route, { waitUntil: "domcontentloaded", timeout: 45000 }); await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => { nav = "busy"; }); await page.waitForTimeout(900); } catch (e) { nav = "FAIL " + String(e).slice(0, 80); }
    const settle = Date.now() - t0; let m = null, contrast = null, focus = null;
    try { m = await page.evaluate(COLLECT); } catch (e) { nav += " | collect " + String(e).slice(0, 80); }
    if (!reduced) { try { contrast = await page.evaluate(H.contrastAudit("body")); } catch (e) { contrast = { error: String(e).slice(0, 80) }; } }
    if (walk) { focus = []; try { for (let i = 0; i < 36; i++) { await page.keyboard.press("Tab"); const f = await page.evaluate(FOCUS); if (f) focus.push(f); } } catch {} }
    if (!reduced) await page.screenshot({ path: path.join(OUT, `${name}__${vname}.png`) }).catch(() => {});
    const rec = { name, route, group, tier, variant: vname, nav, settleMs: settle, sizes, errors: [...new Set(errors)].slice(0, 8), bad: [...new Set(bad)].slice(0, 8), m, contrast: contrast && { checked: contrast.checked, low: contrast.low?.length ?? null, bright: contrast.bright?.length ?? null, lowSample: (contrast.low ?? []).slice(0, 6), error: contrast.error }, focus };
    fs.writeFileSync(path.join(OUT, `${name}__${vname}.json`), JSON.stringify(rec));
    const t = m?.tables ?? []; const big = t.slice().sort((a, b) => b.rows - a.rows)[0];
    summary.push([name, vname, nav, settle, m?.dom, m?.chars, m?.charsInView, m?.fontSizeKinds, m?.scrollPages, t.length, big ? `${big.cls}:${big.rows}r/${big.inView}v/${big.rowH}px/${big.sticky ? "sticky" : "-"}` : "-",
      m?.smallTargets, m?.unnamed, contrast?.low?.length ?? "", m?.perf.lcp, m?.perf.cls, m?.perf.longMs, Math.round(sizes.js / 1024), Math.round(sizes.css / 1024), errors.length, bad.length, m?.runningAnimations, focus ? focus.filter((f) => !f.ring).length + "/" + focus.filter((f) => f.covered).length + "/" + focus.length : ""].join("\t"));
    await ctx.close();
  }
  console.log("done", name);
}
fs.writeFileSync(path.join(OUT, "summary.tsv"), ["name\tvariant\tnav\tsettle\tdom\tchars\tcharsInView\tfontKinds\tscrollPages\ttables\tbiggestTable\tsmallTargets\tunnamed\tcontrastLow\tlcp\tcls\tlongMs\tjsKB\tcssKB\terrors\tbad\tanim\tfocusNoRing/covered/n", ...summary].join("\n"));
await browser.close();
