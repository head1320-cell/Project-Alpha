#!/usr/bin/env node
// README 그림 다시 찍기 — 쓰는 법과 규칙: 이 폴더의 README.md
// 사용(frontend 폴더에서, 먼저 `npx next build`): node scripts/readme-shots/shoot.mjs [--only 이름,이름…]
//
// 하는 일: 제 포트(SHOTS_WEB_PORT=3900 · SHOTS_API_PORT=8900)에 새 DB 로 백엔드(KIS_USE_MOCK=1)와 프론트(next start)를 띄우고,
// 장면을 만들어 docs/images/readme/<이름>.png 를 쓰고, 끝나면(실패해도) 제가 띄운 것만 끈다. 쓰는 포트가 있으면 시작하지 않는다.
// 규칙: ① 그림에 증권사 상표(한국투자증권 · KIS)가 보이지 않는다 — 찍기 직전 화면 글자에서 '증권사'로 가리고, 남아 있으면 그 그림을 쓰지 않고 실패한다
//       (사용자 요청 2026-11-07 · 앱은 바꾸지 않음). ② AI 그림은 실제 Claude 응답만 — AI 가 답하지 못하면 AI 그림을 하나도 쓰지 않고 사유와 함께 실패한다.
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const FRONT = path.resolve(here, "..", "..");
const ROOT = path.resolve(FRONT, "..");
const OUT = path.join(ROOT, "docs", "images", "readme");
const WEB = Number(process.env.SHOTS_WEB_PORT || 3900);
const API = Number(process.env.SHOTS_API_PORT || 8900);
const BASE = `http://localhost:${WEB}`;
const BACK = `http://localhost:${API}/api/v1`;
const SANDBOX_CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const BRAND = /한국투자증권|\bKIS\b/;

const onlyIdx = process.argv.findIndex((a) => a === "--only" || a.startsWith("--only="));
const ONLY = onlyIdx < 0 ? null
  : new Set((process.argv[onlyIdx].includes("=") ? process.argv[onlyIdx].split("=")[1] : process.argv[onlyIdx + 1] ?? "").split(",").filter(Boolean));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const busy = (port) => new Promise((ok) => {
  const s = net.connect(port, "127.0.0.1");
  s.once("connect", () => { s.destroy(); ok(true); });
  s.once("error", () => ok(false));
});
async function waitFor(url, what, ms = 120_000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { if ((await fetch(url)).status === 200) return; } catch { /* 아직 */ }
    await sleep(1000);
  }
  throw new Error(`${what} 이(가) ${ms / 1000}초 안에 뜨지 않았어요: ${url}`);
}

// ── 서버: 제가 띄운 무리만 끈다 ─────────────────────────────────────────
const procs = [];
function start(cmd, argv, cwd, env, log) {
  const fd = fs.openSync(log, "a");
  const p = spawn(cmd, argv, { cwd, env, detached: true, stdio: ["ignore", fd, fd] });
  procs.push(p);
  return p;
}
/** 제 무리에 SIGTERM → 끝날 때까지(최대 10초) 기다림 → 남으면 SIGKILL. 끝나고도 제 포트가 쓰이고 있으면 말한다. */
async function stopAll() {
  const alive = (p) => { try { process.kill(-p.pid, 0); return true; } catch { return false; } };
  for (const p of procs) { try { process.kill(-p.pid, "SIGTERM"); } catch { /* 이미 끝남 */ } }
  for (let i = 0; i < 40 && procs.some(alive); i++) await sleep(250);
  for (const p of procs.filter(alive)) { try { process.kill(-p.pid, "SIGKILL"); } catch { /* 이미 끝남 */ } }
  await sleep(300);
  const still = [];
  for (const port of [WEB, API]) if (procs.length && await busy(port)) still.push(port);
  if (still.length) console.error(`주의: 끈 뒤에도 포트 ${still.join(", ")} 를 쓰는 것이 있어요(제가 띄운 것이 아닐 수 있어요).`);
}

/** Fernet 키(32바이트 urlsafe base64) — 이 실행에서만 쓰는 버릴 키. 내 계좌 장면의 지어낸 자격을 새 DB 에 암호화해 두는 데만 쓴다. */
const fernetKey = () => crypto.randomBytes(32).toString("base64").replace(/\+/g, "-").replace(/\//g, "_");

async function api(pathname, token, body, method = body ? "POST" : "GET") {
  const r = await fetch(`${BACK}${pathname}`, {
    method, headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  if (!r.ok) throw new Error(`${method} ${pathname} → ${r.status}: ${text.slice(0, 200)}`);
  return text ? JSON.parse(text) : null;
}

// ── 상표 가림(그림을 위해서만 · 앱은 그대로) ─────────────────────────────
function installRedact() {
  const once = /한국투자증권(\s*\(KIS\))?|\bKIS\b/;
  const all = /한국투자증권(\s*\(KIS\))?|\bKIS\b/g;
  const fix = (n) => { if (n.nodeType === 3 && once.test(n.nodeValue)) n.nodeValue = n.nodeValue.replace(all, "증권사"); };
  const walk = (root) => {
    if (root.nodeType === 3) { fix(root); return; }
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) fix(n);
  };
  walk(document.body);
  if (window.__readmeRedact) return;
  window.__readmeRedact = new MutationObserver((ms) => {
    for (const m of ms) {
      if (m.type === "characterData") fix(m.target);
      for (const a of m.addedNodes) walk(a);
    }
  });
  window.__readmeRedact.observe(document.body, { subtree: true, childList: true, characterData: true });
}

const written = [];
async function shot(page, name) {
  await page.evaluate(installRedact);
  await sleep(300);
  const text = await page.evaluate(() => document.body.innerText);
  const hit = text.match(BRAND);
  if (hit) throw new Error(`${name}: 그림에 상표 문구('${hit[0]}')가 남아 있어 쓰지 않았어요`);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  written.push({ name, kb: Math.round(fs.statSync(file).size / 1024) });
  console.log(`  ✓ ${name}.png (${written.at(-1).kb} KB)`);
}

// ── 장면 도우미 ───────────────────────────────────────────────────────
async function settle(page, ms = 800) {
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => { /* 길게 여는 연결이 있는 화면 */ });
  await sleep(ms);
}
async function openCanvas(page, url = "/allocation") {
  await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded" });
  await page.locator(".pg-node").first().waitFor({ timeout: 60_000 });
  await settle(page);
}
async function runCanvas(page) {
  const done = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 180_000 });
  await page.locator(".pg-run").click();
  const res = await done;
  if (!res.ok()) throw new Error(`계산이 ${res.status()} 로 끝났어요`);
  await settle(page, 1200);
}
/** 왼쪽 판 탭 — proc(절차) · add(노드 추가) · say(말로 설계). */
async function leftTab(page, tab) {
  await page.locator(`.pg-left-tab[data-tab="${tab}"]`).click();
  await sleep(400);
}
async function closeLeft(page) {
  const t = page.locator('.pg-panel-toggle[data-panel="left"]');
  if ((await t.getAttribute("aria-expanded").catch(() => null)) !== "false") await t.click().catch(() => { /* 이미 닫힘 */ });
  await sleep(400);
}
async function closeRight(page) {
  const t = page.locator('.pg-panel-toggle[data-panel="right"]');
  if ((await t.getAttribute("aria-expanded").catch(() => null)) !== "false") await t.click().catch(() => { /* 이미 닫힘 */ });
  await sleep(400);
}
async function zoomIn(page, steps) {
  for (let i = 0; i < steps; i++) { await page.locator(".react-flow__controls-zoomin").click(); await sleep(250); }
}
/** 그 노드를 지금 확대 그대로 보이는 캔버스 가운데로 — 미니맵 칸을 누르면 앱이 그렇게 옮긴다(U3). */
async function centerOn(page, nodeId) {
  const box = await page.locator(`.react-flow__node[data-id="${nodeId}"]`).boundingBox();
  const pane = await page.locator(".react-flow__pane").boundingBox();
  if (!box || !pane) return;
  const from = { x: pane.x + pane.width / 2, y: pane.y + pane.height / 2 };
  const to = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await page.mouse.move(from.x + 1, pane.y + 30);
  await page.mouse.down();
  await page.mouse.move(from.x + 1 - (to.x - from.x), pane.y + 30 - (to.y - from.y), { steps: 12 });
  await page.mouse.up();
  await sleep(500);
}
async function fit(page) {
  await page.locator(".react-flow__controls-fitview").click();
  await sleep(600);
}
/** AI 가 답했는지 — 답(ok) 이나 '보여 줄 수 없어요'(no) 중 먼저 오는 것을 기다린다. 없으면 사유와 함께 실패. */
async function aiOutcome(page, okSel, noSel, what) {
  const ok = page.locator(okSel).first();
  const no = page.locator(noSel).filter({ hasText: /보여 줄 수 없어요|로그인|못/ }).first();
  await Promise.race([ok.waitFor({ timeout: 180_000 }), no.waitFor({ timeout: 180_000 })]);
  if (await ok.isVisible().catch(() => false)) return;
  const why = (await no.innerText().catch(() => "")).replace(/\s+/g, " ").trim();
  throw new AiUnavailable(`${what}: AI 가 답할 수 없어요 — ${why || "사유 없음"}`);
}
class AiUnavailable extends Error {}

// ── 장면(AI 아닌 것 먼저) ──────────────────────────────────────────────
const SCENES = [
  // 캔버스는 처음 열 때의 맞춤(확대 0.55 이상 — 노드가 결과를 보이는 확대)을 그대로 쓴다. '맞춰 보기'는 더 멀리 가 요약 카드가 된다.
  { name: "canvas", run: async (page) => {
    await openCanvas(page); await runCanvas(page);
    await closeLeft(page);
    await zoomIn(page, 2);
    await centerOn(page, "optimizer");
    await page.locator('.pg-tab[data-tab="story"]').click().catch(() => { /* 이미 이야기 탭 */ });
    await settle(page, 600);
  } },
  { name: "canvas-wire", run: async (page) => {
    await openCanvas(page); await runCanvas(page); await leftTab(page, "proc");
    const edge = page.locator(".react-flow__edge").nth(2);
    await edge.evaluate((el) => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await settle(page, 800);
  } },
  { name: "canvas-simple", run: async (page) => {
    await openCanvas(page); await runCanvas(page);
    await page.getByRole("button", { name: /간단히 보기/ }).first().click();
    await settle(page, 800);
  } },
  // 단계 띠 · 미니맵 — 기본 사슬 그대로(전략 띠를 더하면 띠 머리와 전략 상자 머리가 겹쳐 보여 뺐다 · HISTORY 관찰).
  { name: "canvas-workspace", run: async (page) => {
    await openCanvas(page); await runCanvas(page);
    await closeLeft(page); await closeRight(page);
    const mm = page.locator('.pg-toolbar button[aria-label="미니맵"]');
    if ((await mm.getAttribute("aria-pressed")) !== "true") await mm.click();
    await page.locator(".pg-view-open").click();
    await page.locator('.pg-view-menu [data-view="lanes"]').click();
    if (!(await page.locator(".pg-view-menu").isVisible().catch(() => false))) await page.locator(".pg-view-open").click();
    await page.locator('.pg-view-menu [data-view="fit-lanes"]').click();
    await settle(page, 1000);
  } },
  { name: "home", run: async (page) => { await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" }); await settle(page, 1500); } },
  { name: "screener", run: async (page) => {
    await page.goto(`${BASE}/screener`, { waitUntil: "domcontentloaded" });
    await page.locator("table tbody tr").first().waitFor({ timeout: 60_000 }); await settle(page, 1000);
  } },
  { name: "screener-sheet", run: async (page) => {
    await page.goto(`${BASE}/screener`, { waitUntil: "domcontentloaded" });
    const row = page.locator("table tbody tr").first(); await row.waitFor({ timeout: 60_000 }); await settle(page, 600);
    await row.click(); await settle(page, 1000);
  } },
  { name: "backtest-editor", run: async (page) => { await page.goto(`${BASE}/backtest`, { waitUntil: "domcontentloaded" }); await settle(page, 1200); } },
  { name: "backtest-result", run: async (page) => {
    await page.goto(`${BASE}/backtest`, { waitUntil: "domcontentloaded" }); await settle(page, 800);
    await page.locator(".tbt-run").first().click();
    await page.waitForURL(/\/backtest\/runs\/[^/]+\/results/, { timeout: 300_000 });
    await settle(page, 2000);
  } },
  { name: "macro", run: async (page) => { await page.goto(`${BASE}/macro`, { waitUntil: "domcontentloaded" }); await settle(page, 2000); } },
  { name: "insights", run: async (page) => { await page.goto(`${BASE}/insights?code=005930`, { waitUntil: "domcontentloaded" }); await settle(page, 2500); } },
  { name: "risk", run: async (page) => { await page.goto(`${BASE}/risk-tools`, { waitUntil: "domcontentloaded" }); await settle(page, 2000); } },
  { name: "my-account", run: async (page) => { await page.goto(`${BASE}/my-account`, { waitUntil: "domcontentloaded" }); await settle(page, 2000); } },
  { name: "clients", run: async (page, s) => {
    await page.goto(`${BASE}/clients?client=${s.clients[0]}`, { waitUntil: "domcontentloaded" }); await settle(page, 1500);
  } },
  { name: "client-sheet", run: async (page, s) => {
    await openCanvas(page, `/allocation?client=${s.clients[0]}&new=review`);
    // 정기 점검 문서는 계좌 유형을 사람이 고르게 둔다(기본값으로 정하지 않음) — 연금저축/IRP 중 IRP 를 고른 뒤 계산한다.
    await page.locator('.pg-node[data-node-id="account"]').click();
    await page.locator('.pg-tab[data-tab="settings"]').click();
    await page.locator('.pg-basic-field[data-field="account_type"] .pg-choice[data-choice="irp"]').click();
    await runCanvas(page);
    await page.locator(".pg-client-chip .pg-client-sheet").click();
    await page.locator(".cs-sheet").waitFor({ timeout: 60_000 }); await settle(page, 1200);
  } },
  // ── AI(실제 Claude 응답만) ──
  { name: "ai-suggest", ai: true, run: async (page) => {
    await openCanvas(page); await runCanvas(page);
    await page.locator(".pg-ai-ask").click();
    await aiOutcome(page, '.pg-ghost[data-source="claude"]', ".pg-ai-note", "노드 추천");
    await settle(page, 600);
  } },
  { name: "ai-draft", ai: true, run: async (page) => {
    await openCanvas(page);
    await page.locator('.pg-left-tab[data-tab="say"]').click();
    const box = page.locator(".pg-say-text");
    await box.fill("삼성전자, SK하이닉스, NAVER 로 최근 3년 수익률을 보고 위험을 고르게 나눠 비중을 정해 줘");
    await box.press("Enter");
    await aiOutcome(page, ".pg-say-item", ".pg-say-note", "말로 설계");
    await settle(page, 800);
  } },
  { name: "ai-ask", ai: true, run: async (page) => {
    await openCanvas(page); await runCanvas(page);
    await page.locator('.pg-node[data-node-id="optimizer"]').click();
    const box = page.locator(".pg-ask-text");
    await box.fill("이 비중은 어떤 입력에서 나왔나요?");
    await box.press("Enter");
    await aiOutcome(page, ".pg-ask-turn .pg-ask-chip", ".pg-ask-notice, .pg-ask-note", "AI 에게 묻기");
    await settle(page, 800);
  } },
  { name: "ai-story", ai: true, run: async (page) => {
    await openCanvas(page); await runCanvas(page);
    await page.locator('.pg-tab[data-tab="story"]').click().catch(() => { /* 이미 */ });
    await page.locator(".pg-ai-story-ask").click();
    await aiOutcome(page, ".pg-ai-para", ".pg-ai-story-notice, .pg-ai-story-note", "AI 가 풀어 쓴 글");
    await settle(page, 800);
  } },
];

async function main() {
  const scenes = SCENES.filter((s) => !ONLY || ONLY.has(s.name));
  const unknown = ONLY ? [...ONLY].filter((n) => !SCENES.some((s) => s.name === n)) : [];
  if (unknown.length) throw new Error(`모르는 장면: ${unknown.join(", ")} — 장면: ${SCENES.map((s) => s.name).join(", ")}`);
  for (const p of [WEB, API]) if (await busy(p)) throw new Error(`포트 ${p} 를 이미 쓰고 있어요 — 시작하지 않았어요(그 프로세스를 끌지는 직접 정하세요).`);
  if (!fs.existsSync(path.join(FRONT, ".next"))) throw new Error("frontend/.next 가 없어요 — 먼저 'npx next build'.");
  fs.mkdirSync(OUT, { recursive: true });

  const work = fs.mkdtempSync(path.join(os.tmpdir(), "readme-shots-"));
  const db = path.join(work, "shots.db");
  console.log(`기록: ${work}`);
  const backEnv = {
    ...process.env, KIS_USE_MOCK: "1", DATABASE_URL: `sqlite:///${db}`, BROKER_CRED_KEY: fernetKey(),
    // 실제 키가 없으면 자리 표시 값 — 이 환경에서는 프록시가 진짜 키를 넣고, 아니면 AI 가 사유와 함께 답하지 못한다(그러면 AI 그림을 쓰지 않음).
    ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY || "placeholder-key-injected-by-proxy",
  };
  start("python3", ["-m", "uvicorn", "main_api:app", "--port", String(API), "--log-level", "warning"], ROOT, backEnv, path.join(work, "api.log"));
  await waitFor(`${BACK}/macro/health`, "백엔드");
  start("npx", ["next", "start", "-p", String(WEB)], FRONT, { ...process.env, BACKEND_URL: `http://localhost:${API}` }, path.join(work, "web.log"));
  await waitFor(`${BASE}/`, "프론트");

  // 준비 — 로그인 · 지어낸 고객 셋(개인 정보 없음) · 내 계좌용 지어낸 모의 계좌(새 DB 에만)
  const { access_token: token } = await api("/auth/login", null, { username: "admin", password: "frm123!" });
  const clients = [];
  for (const [alias, risk] of [["은퇴 준비 고객", "conservative"], ["자녀 교육 자금", "moderate"], ["사업 운영 자금", "aggressive"]]) {
    clients.push((await api("/pb/clients", token, { alias, risk_tolerance: risk, profile_source: "survey", assessed_at: "2026-10-01", horizon_years: 10 })).client_id);
  }
  await api("/live/init-schema", token, {});   // 운영자의 첫 준비 — 새 DB 에 live_* 표(비상 정지 기록 등)를 만든다
  await api("/broker-accounts", token, { label: "내 모의 계좌", app_key: "PSreadme0000demo", app_secret: "readme-demo-secret-not-real", account_no: "00000000", is_paper: true });

  const exe = process.env.PW_CHROMIUM_PATH || (fs.existsSync(SANDBOX_CHROMIUM) ? SANDBOX_CHROMIUM : undefined);
  const browser = await chromium.launch(exe ? { executablePath: exe } : {});
  // ★장면마다 새 문맥★ — 문맥 하나를 같이 쓰면 앞 장면이 남긴 localStorage(왼쪽 판 접힘·판 자리 등)가 다음 장면에 이어져
  // `canvas` 뒤의 `canvas-wire` 가 접힌 판에서 시작해 실패했다(2026-11-12 관측). 씨앗은 같고, 장면이 주고받는 것은 서버 쪽 `state` 뿐이다.
  const freshContext = () => browser.newContext({
    viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: "ko-KR", reducedMotion: "reduce",
    storageState: { cookies: [], origins: [{ origin: BASE, localStorage: [
      { name: "alpha_theme", value: "light" }, { name: "alpha_pg_welcomed", value: "1" }, { name: "project-alpha.auth-token", value: token },
    ] }] },
  });
  const state = { clients };
  let aiFailed = null;
  try {
    for (const s of scenes) {
      if (s.ai && aiFailed) { console.log(`  · ${s.name} 건너뜀 — ${aiFailed}`); continue; }
      const ctx = await freshContext();
      const page = await ctx.newPage();
      try {
        await s.run(page, state);
        await shot(page, s.name);
      } catch (e) {
        if (e instanceof AiUnavailable) { aiFailed = e.message; console.log(`  ✗ ${s.name} — ${e.message}`); }
        else throw new Error(`${s.name}: ${e.message}`);
      } finally { await ctx.close(); }
    }
  } finally { await browser.close(); }
  console.log(`\n쓴 그림 ${written.length}장 · 합계 ${written.reduce((a, w) => a + w.kb, 0)} KB → ${path.relative(ROOT, OUT)}`);
  if (aiFailed) throw new Error(`AI 그림을 쓰지 않았어요 — ${aiFailed}`);
}

main()
  .then(async () => { await stopAll(); process.exit(0); })
  .catch(async (e) => { console.error(`\n실패: ${e.message}`); await stopAll(); process.exit(1); });
