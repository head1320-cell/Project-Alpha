import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "./fixtures";
import { contrastAudit, trackErrors, uniq, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ═════════════════════════════════════════════════════════════════════════════════════════════════
// 캔버스의 국면 조건(K3 · 2026-11-17 · 구현 계획 2026-11-16 §7.4) — 분봉 설정 노드의 '직접 구성' · 분봉 결과 조회 판
// 자료는 화면 스펙과 같은 손 계산 열흘(035720 · `seed_bars.py`) — '종가 상향 돌파 10050'(= 틀 '시가 범위 돌파 1분'의 체결) 그리고
// '코스피 국면 1 확률(국면 2개) > 0.5'. 국면은 E2E 서버(모의 게이트)의 합성 지수 — n 은 같은 서버의 시장 국면 문에 묻는다.
// 거는 것:
//  · 설정 판의 편집기가 국면 조건(고르기 칸 · 국면 수 · 번호)을 그대로 보이고 규칙의 글 = 서버의 글 · 좁은 판(300px)에서 넘치지 않는다
//  · 계산하면 판의 사실 줄 '규칙이 쓴 시장 국면' = 서버 문장 · 하루 유형 묶음은 없다 · 해설의 확인 줄은 국면의 것만(모형 검사를 말하지 않는다)
//  · 실행 단추로 남긴 결과의 조회 판: '국면 조건을 뺀 판과 견줌' — 뺀 판 = 손 계산 열흘 · 넣은 판 = n × 하루 손 계산 · 사실 줄도 남는다
//  · 라이트/다크 AA · 문체
// ═════════════════════════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const MINUS = "−";
const HAND_DAYS = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06",
                   "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13"];
const REGIME = { op: "gt", args: [{ ind: "regime_prob", index: "KOSPI", k: 2, state: 1 }, { const: 0.5 }] };
const RULE = { entry: { op: "and", args: [{ op: "cross_up", args: [{ ind: "close" }, { const: 10050 }] }, REGIME] } };
const TEXT = "진입 조건: 종가 상향 돌파 10050 그리고 코스피 국면 1 확률(국면 2개) > 0.5";
const PARAMS = { tickers: ["035720"], start_date: "2026-03-02", end_date: "2026-03-13", rule: "custom", custom_rule: RULE,
  amount: 1_000_000, commission_bp: 1.5, slippage_ticks: 1, unknown_market: "KOSPI", unknown_instrument: "stock" };
const DAY_TYPE_TRUST = "하루 유형 모형이 본인의 것이고 학습이 판정 시작일 전에 끝났는지 검사했습니다.";
const n = (v: number) => v.toLocaleString("ko-KR");
const won = (v: number) => { const r = Math.round(Math.abs(v)); return `${r === 0 ? "" : v < 0 ? MINUS : "+"}${n(r)}원`; };

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

async function importDoc(page: Page, nodes: object[]) {
  const doc = { format: "project-alpha.portfolio-graph", version: 1, meta: { name: "국면 조건" }, edges: [], nodes };
  await page.locator(".pg-import-input").setInputFiles({ name: "regime.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
}

async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 120_000 });
  await page.locator(".pg-run").click();
  return (await resp).json();
}

/** 판(.pg-side) 밖으로 넘친 요소의 클래스 — 없어야 한다. */
const overflowing = (page: Page, inner: string) => page.evaluate((sel) => {
  const side = document.querySelector(".pg-side")!; const right = side.getBoundingClientRect().right + 1;
  return [...side.querySelectorAll(`${sel} *`)].filter((el) => el.getClientRects().length && el.getBoundingClientRect().right > right).map((el) => el.className);
}, inner);

/** 같은 서버의 시장 국면 문 — 손 계산 열흘 가운데 국면 1 확률(국면 2개)이 0.5 보다 큰 날 수. */
async function daysAbove(page: Page, token: string): Promise<number> {
  const q = new URLSearchParams({ index: "KOSPI", k: "2", from: "2026-03-02", to: "2026-03-13" });
  const r = await page.request.get(`${API}/intraday/market-regime?${q}`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  const days = (await r.json()).days as { date: string; probs: number[] | null }[];
  return days.filter((d) => HAND_DAYS.includes(d.date) && d.probs !== null && d.probs[0] > 0.5).length;
}

/** 캔버스의 단추와 같은 두 문(계산 → 저장)으로 국면 조건 규칙의 실행 하나를 남기고 그 열쇠를 돌려준다(이 실행에서만 쓰는 진입 금액 — 99주 그대로). */
async function keptTrial(page: Page, token: string): Promise<string> {
  const headers = { Authorization: `Bearer ${token}` };
  const params = { ...PARAMS, amount: 1_000_000 + (Date.now() % 7_000) + 1 };
  const graph = { format: "project-alpha.portfolio-graph", version: 1, edges: [], nodes: [{ id: "is", type: "intraday_setup", params }] };
  const ran = await page.request.post(`${API}/allocation/graph/run`, { data: graph, headers, timeout: 120_000 });
  expect(ran.ok(), await ran.text()).toBe(true);
  const hash = (await ran.json()).nodes.is.view_hash as string;
  const saved = await page.request.post(`${API}/allocation/graph/save`, { data: { graph, node_id: "is", preview_hash: hash }, headers, timeout: 120_000 });
  const body = await saved.json();
  expect(body.ok, body.message).toBe(true);
  return body.saved_id as string;
}

test("설정 노드: 판의 편집기가 국면 조건을 그대로 보이고 · 계산하면 '규칙이 쓴 시장 국면' = 서버 문장 · 확인 줄은 국면의 것만 · 300px 판에서 넘치지 않는다", async ({ page }) => {
  test.setTimeout(120_000);
  const sink = trackErrors(page);
  await page.addInitScript(() => { try { localStorage.setItem("alpha_pg_panels", JSON.stringify({ left: true, right: true, rightW: 300 })); } catch { /* */ } });
  await login(page);
  await openCanvas(page);
  await importDoc(page, [{ id: "is", type: "intraday_setup", position: { x: 0, y: 0 }, params: PARAMS }]);
  await node(page, "is").click();
  await tab(page, "settings");
  const field = page.locator('.pg-side .pg-basic-field[data-field="custom_rule"]');
  await expect(field.getByLabel("시장 국면 확률 지수", { exact: true })).toHaveValue("KOSPI");
  await expect(field.getByLabel("시장 국면 확률 국면 수", { exact: true })).toHaveValue("2");
  await expect(field.getByLabel("시장 국면 확률 국면 번호", { exact: true })).toHaveValue("1");
  await expect(field.locator(".itd-rule-text")).toHaveText(TEXT);
  await expect(field.locator(".ire-regime-add")).toHaveCount(1);                              // 같은 부품 — 진입 조건 자리의 단추
  expect(await page.locator(".pg-side").evaluate((el) => Math.round(el.getBoundingClientRect().width))).toBe(300);
  expect(await overflowing(page, ".pg-itd-rule"), "설정 판 밖으로 넘친 것").toEqual([]);

  const out = await run(page);
  expect(out.nodes.is.status, out.nodes.is.reason).toBe("ok");
  expect(out.nodes.is.view.rule_text).toBe(TEXT);
  const facts = (out.nodes.is.view.context as { kind?: string; sentences: string[] }[]);
  expect(facts.map((f) => f.kind)).toEqual(["regime"]);
  const trust = (out.nodes.is.explain.trust as { text: string }[]).map((t) => t.text);
  expect(trust.some((t) => t.startsWith("시장 국면 확률이 그날 시가 전에 알던 값"))).toBe(true);
  expect(trust).not.toContain(DAY_TYPE_TRUST);                                                 // 모형을 쓰지 않은 규칙에 모형 검사를 말하지 않는다
  await tab(page, "detail");
  await expect(page.locator(".pg-side .itd-rctx-line")).toHaveText(facts[0].sentences);
  await expect(page.locator(".pg-side .itd-ctx")).toHaveCount(0);
  expect(await overflowing(page, ".itd-rctx"), "판 밖으로 넘친 사실 줄").toEqual([]);
  expect(uniq(sink.api404), "404").toEqual([]);
  expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

for (const theme of ["light", "dark"] as const) {
  test(`결과 조회 판(${theme}): '국면 조건을 뺀 판과 견줌' — 뺀 판 = 손 계산 열흘 · 넣은 판 = n × 하루 손 계산 · 사실 줄 · 대비 · 문체`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    const token = await login(page);
    const nAbove = await daysAbove(page, token);
    expect(nAbove, "국면이 열흘 모두 같으면 견줄 것이 없다").toBeGreaterThan(0);
    expect(nAbove).toBeLessThan(10);
    const key = await keptTrial(page, token);
    await openCanvas(page);
    await importDoc(page, [{ id: "il", type: "intraday_load", position: { x: 0, y: 0 }, params: { trial_key: key } }]);
    const out = await run(page);
    expect(out.nodes.il.status, out.nodes.il.reason).toBe("ok");
    const pair = out.nodes.il.view.regime_pair as { known: boolean; note: string };
    expect(pair.known).toBe(true);
    expect((out.nodes.il.explain.facts as string[]).some((f) => f.startsWith("국면 조건을 뺀 같은 규칙: 거래 10건 · 비용 후 실현손익 −3,195원"))).toBe(true);
    await node(page, "il").click();
    await tab(page, "detail");
    const panel = page.locator(".pg-side .pg-itd-load");
    const table = panel.locator(".itd-rpair-table");
    await expect(table.locator('tr[data-k="without"] td').nth(0)).toHaveText("10건");
    await expect(table.locator('tr[data-k="without"] td').nth(1)).toHaveText("+19,800원");
    await expect(table.locator('tr[data-k="without"] td').nth(2)).toHaveText(won(-3_194.73));
    await expect(table.locator('tr[data-k="with"] td').nth(0)).toHaveText(`${n(nAbove)}건`);
    await expect(table.locator('tr[data-k="with"] td').nth(1)).toHaveText(won(1_980 * nAbove));
    await expect(table.locator('tr[data-k="with"] td').nth(2)).toHaveText(won(-319.473 * nAbove));
    await expect(panel.locator(".itd-rpair-rule [data-server]")).toHaveText("진입 조건: 종가 상향 돌파 10050");
    await expect(panel.locator(".itd-rpair-note")).toHaveText(pair.note);
    // 좁은 판: 표는 판 안의 넘김 상자에서만 옆으로 넘는다(전제: 다섯 칸이 판 폭에 들지 않는다) — 상자 밖으로 넘친 칸 0 · 상자는 판 안
    const spill = await page.evaluate(() => {
      const side = document.querySelector(".pg-side")!; const right = side.getBoundingClientRect().right + 1;
      const over = [...side.querySelectorAll(".itd-rpair *")].filter((el) => el.getClientRects().length && el.getBoundingClientRect().right > right);
      const box = side.querySelector(".itd-rpair .tj-scroll-x");
      return { outside: over.filter((el) => !el.closest(".tj-scroll-x")).length, boxInside: !!box && box.getBoundingClientRect().right <= right,
               scrolls: !!box && box.scrollWidth > box.clientWidth };
    });
    expect(spill, "짝 비교 표는 판 안의 넘김 상자에서만 넘는다").toEqual({ outside: 0, boxInside: true, scrolls: true });
    await expect(panel.locator(".itd-rctx-title")).toHaveText("규칙이 쓴 시장 국면");            // 실행 단추가 남긴 요약에 사실 줄이 그대로 실린다
    for (const root of [".pg-side .itd-rpair", ".pg-side .itd-rctx"]) {
      const a = (await page.evaluate(contrastAudit(root))) as AuditResult;
      expect(a.checked, root).toBeGreaterThan(3);
      expect(a.low, `${theme} ${root}`).toEqual([]);
      const v = (await page.evaluate(voiceAudit(root))) as VoiceResult;
      expect(v.haeyo, root).toEqual([]);
      expect(v.dash, root).toEqual([]);
      expect(v.banned, root).toEqual([]);
    }
  });
}
