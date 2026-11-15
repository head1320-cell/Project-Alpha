import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, type Page } from "./fixtures";
import { contrastAudit, trackErrors, uniq, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ═════════════════════════════════════════════════════════════════════════════
// 규칙 가동 (W5b) — 캔버스의 요청 → 내 계좌에서 가동(재생) → 가상 체결  (★실제 서버★ · 설계 `…paper-trading-monitor-design.md`)
// ─────────────────────────────────────────────────────────────────────────────
// 분봉은 `intraday.spec.ts` 와 같은 손 계산 열흘(035720 · 2026-03-02 ~ 03-13 · 출처 열 `kis` · 하루 봉 넷)이다:
//     09:00  시 10,000 · 고 10,020 · 저  9,990 · 종 10,000
//     09:01  시 10,000 · 고 10,060 · 저 10,000 · 종 10,060      ← 개장 1분 범위(고 10,020) 돌파 = 신호 봉
//     09:02  시 10,070 …                                         ← 다음 봉 시가 + 한 틱(10) = 10,080 에 매수 · 100만원 ÷ 10,080 = 99주
//     09:03  … 종 10,110                                         ← 하루의 끝 · 종가 − 한 틱 = 10,100 에 강제 청산
//   → 가상 체결 두 줄: 09:02 매수 99주 @10,080 · 09:03 매도 99주 @10,100 (= 그 하루의 분봉 백테스트 체결)
// 계좌는 이 스펙이 실제 서버에 연결한다(합성 데이터 모드라 증권사에 닿지 않는다 · 서버의 금고 키는 `playwright.config.ts` 가 준다).
// 거는 것:
//  · ★요청은 가동이 아니다★ — 캔버스에서 남긴 요청이 내 계좌의 목록에 뜨고, 가동은 여기서 사람이 켠다
//  · 재생한 가상 체결 = 손 계산 = 같은 날의 분봉 백테스트 체결 · 줄마다 ‘가상’ 표식 · 주문은 ‘기록만’으로 남는다
//  · 정지하면 멈춘 까닭이 서버 문장 그대로 뜨고 다시 밀 단추가 없다 · 요청은 확인을 거쳐 목록에서 뺀다
//  · 실행 모드가 ‘기록만’이 아니거나 비상 정지 중이면 시작 단추가 잠기고 까닭을 말한다(↔ 풀면 열린다) · 서버의 거절은 서버 문장으로
//  · 못 읽음은 빈 목록이 아니다 · 시행이 없는 요청은 가동 단추가 없다 · 합성 분봉이면 절 맨 위에 적는다
//  · 오류 0 · 라이트/다크 AA · 문체 · 좁은 폭에서 넘치지 않는다
// ═════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";
const DAY = "2026-03-04";
const HAND = { tickers: ["035720"], start_date: "2026-03-02", end_date: "2026-03-13", rule: "opening_range_breakout",
  opening_range_breakout__minutes: 1, amount: 1_000_000, commission_bp: 1.5, slippage_ticks: 1,
  unknown_market: "KOSPI", unknown_instrument: "stock" };
const SYNTHETIC = { ...HAND, tickers: ["005930"], start_date: "2026-04-01", end_date: "2026-04-16", unknown_market: undefined, unknown_instrument: undefined };
const LABEL = "E2E 가동 계좌";

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

type Ctx = { token: string; headers: Record<string, string>; account: string };

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

/** 이 스펙이 남긴 계좌와 요청을 걷는다 — 다른 스펙이 '연결한 계좌 없음' 화면을 보게 둔다. */
async function sweep(page: Page, headers: Record<string, string>) {
  const list = await page.request.get(`${API}/broker-accounts`, { headers });
  for (const a of ((await list.json()).accounts ?? []) as { account_id: string; label: string }[]) {
    if (a.label === LABEL) await page.request.delete(`${API}/broker-accounts/${a.account_id}`, { headers });
  }
  const reqs = await page.request.get(`${API}/intraday/arm-requests`, { headers });
  for (const r of ((await reqs.json()).requests ?? []) as { id: number }[]) {
    await page.request.delete(`${API}/intraday/arm-requests/${r.id}`, { headers });
  }
}

/** 로그인 + 깨끗한 요청 목록 + 새 모의투자 계좌 하나(실제 서버 · 합성 데이터 모드). */
async function prepare(page: Page): Promise<Ctx> {
  const token = await login(page);
  const headers = { Authorization: `Bearer ${token}` };
  // 주문 · 감사 · 비상 정지의 표를 만든다(운영자의 초기화 문 — 여러 번 불러도 같다). 표가 없으면 비상 정지는 '상태 조회 실패 = 차단'으로
  // 읽힌다(닫힌 실패 — 그 화면은 아래 '차단' 스펙이 따로 건다).
  const schema = await page.request.post(`${API}/live/init-schema`, { headers });
  expect(schema.ok(), await schema.text()).toBe(true);
  await sweep(page, headers);
  const made = await page.request.post(`${API}/broker-accounts`, { headers, data: {
    label: LABEL, app_key: "PSkey-0123456789abcdef", app_secret: "secret-0123456789abcdefghijklmnop", account_no: "50123456", is_paper: true } });
  expect(made.status(), `계좌 연결 — E2E 서버에 금고 키가 있어야 한다: ${await made.text()}`).toBe(201);
  return { token, headers, account: (await made.json()).account_id as string };
}

const graphOf = (nodes: object[], edges: object[] = []) => ({ format: "project-alpha.portfolio-graph", version: 1, edges, nodes });

/** 캔버스의 단추와 같은 두 문(계산 → 저장) — 그 노드의 단추를 누른 것과 같다. */
async function press(page: Page, headers: Record<string, string>, graph: object, nodeId: string): Promise<string> {
  const ran = await page.request.post(`${API}/allocation/graph/run`, { data: graph, headers, timeout: 120_000 });
  expect(ran.ok(), await ran.text()).toBe(true);
  const node = (await ran.json()).nodes[nodeId];
  expect(node.status, node.reason).toBe("ok");
  const saved = await page.request.post(`${API}/allocation/graph/save`, { data: { graph, node_id: nodeId, preview_hash: node.view_hash }, headers, timeout: 120_000 });
  const body = await saved.json();
  expect(body.ok, body.message).toBe(true);
  return body.saved_id as string;
}

const keptTrial = (page: Page, c: Ctx, params: object = HAND) =>
  press(page, c.headers, graphOf([{ id: "is", type: "intraday_setup", params }]), "is");
const armGraph = (key: string, note?: string) => graphOf(
  [{ id: "il", type: "intraday_load", position: { x: 0, y: 0 }, params: { trial_key: key } },
   { id: "ar", type: "intraday_arm_request", position: { x: 420, y: 0 }, params: note ? { note } : {} }],
  [{ source: "il", source_port: "run", target: "ar", target_port: "run" }]);
/** 요청 한 줄을 남긴다(캔버스의 ‘가동 요청 남기기’와 같은 문). */
const leaveRequest = async (page: Page, c: Ctx, params: object = HAND, note?: string) => {
  const key = await keptTrial(page, c, params);
  return { key, id: Number(await press(page, c.headers, armGraph(key, note), "ar")) };
};

async function openAccount(page: Page, c: Ctx) {
  await page.goto(`/my-account?account=${c.account}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".ma-arm")).toBeVisible({ timeout: 30_000 });
}

const arm = (page: Page) => page.locator(".ma-arm");
const request = (page: Page, id: number) => page.locator(`.ma-arm-req[data-request="${id}"]`);
const runRow = (page: Page) => page.locator(".ma-arm-run").first();

/** 가동 준비를 열어 날짜를 고르고 시작한다 → 가동 번호. */
async function startFromScreen(page: Page, id: number, day = DAY): Promise<number> {
  await request(page, id).locator(".ma-arm-open").click();
  const panel = request(page, id).locator(".ma-arm-start");
  await expect(panel.locator(".ma-arm-day-pick")).toBeVisible();
  await panel.locator(".ma-arm-day-pick").selectOption(day);
  const started = page.waitForResponse((r) => /\/rule-runs$/.test(new URL(r.url()).pathname) && r.request().method() === "POST");
  await panel.locator(".ma-arm-go").click();
  const res = await started;
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()).run.run_id as number;
}

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  const token = await login(page);
  await sweep(page, { Authorization: `Bearer ${token}` });
  await page.close();
});

test("캔버스의 요청 → 내 계좌에서 가동 → 끝까지: 가상 체결 = 손 계산 = 그 하루의 분봉 백테스트 체결", async ({ page }) => {
  test.setTimeout(240_000);
  const sink = trackErrors(page);
  const c = await prepare(page);
  const key = await keptTrial(page, c);

  // ① 캔버스 — 요청 한 줄을 남기고(가동하지 않는다) 판의 링크로 내 계좌에 간다
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  const g = armGraph(key, "개장 전 점검") as { nodes: object[]; edges: object[] };
  await page.locator(".pg-import-input").setInputFiles({ name: "arm.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ ...g, meta: { name: "가동 요청" } })) });
  const ran = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 120_000 });
  await page.locator(".pg-run").click();
  expect((await (await ran).json()).nodes.ar.status).toBe("ok");
  await page.locator('.pg-node[data-node-id="ar"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  const saved = page.waitForResponse((r) => r.url().includes("/allocation/graph/save"), { timeout: 120_000 });
  await page.locator(".pg-save-btn").click();
  const sv = await (await saved).json();
  expect(sv.ok, sv.message).toBe(true);
  const requestId = Number(sv.saved_id);
  const none = await (await page.request.get(`${API}/broker-accounts/${c.account}/rule-runs`, { headers: c.headers })).json();
  expect(none.runs, "요청은 가동이 아니다").toEqual([]);
  await page.locator('.pg-tab[data-tab="detail"]').click();
  await page.locator(".pg-side .pg-itd-go").click();
  await expect(page).toHaveURL(/\/my-account/);

  // ② 내 계좌 — 받은 요청: 무엇을 가동하게 되는지 · 관문 수(표시만). 링크로 온 그 화면 그대로 본다(계좌가 하나라 그 계좌가 뜬다)
  await expect(arm(page)).toBeVisible({ timeout: 30_000 });
  const row = request(page, requestId);
  await expect(arm(page).locator(".ma-arm-req")).toHaveCount(1);
  await expect(row.locator(".ma-arm-rule")).toHaveText("시가 범위 돌파");
  await expect(row.locator(".ma-arm-what")).toContainText("종목 1개");
  await expect(row.locator(".ma-arm-what")).toContainText("035720");
  await expect(row.locator(".ma-arm-period")).toHaveText("실행 기간 2026-03-02 ~ 2026-03-13");
  await expect(row.locator(".ma-arm-gates")).toHaveText("관문 일곱 통과 2 · 미달 1 · 미상 4");
  await expect(row.locator(".ma-arm-note")).toHaveText("메모 개장 전 점검");
  await expect(arm(page).locator('.tx-notice[data-tone="practice"]')).toHaveCount(0);   // 실제 분봉 — 합성 알림이 없다(짝은 아래)
  await expect(arm(page).locator(".ma-arm-none")).toHaveText("가동 기록 없음");
  await expect(arm(page).locator(".ma-arm-limits")).toHaveText("동시 가동 3건 · 가동당 종목 10개 · 봉 간격이 5분을 넘으면 중단");

  // ③ 가동 준비 — 날짜는 그 설정의 실행 기간 가운데 분봉이 적재된 날 · 지금 모드 · 비상 정지 · 관문 · 출처를 본다
  await row.locator(".ma-arm-open").click();
  const panel = row.locator(".ma-arm-start");
  await expect(panel.locator(".ma-arm-day-pick option")).toHaveCount(10);
  await expect(panel.locator(".ma-arm-day-pick")).toHaveValue("2026-03-13");       // 기본은 가장 최근에 적재된 날
  await expect(panel.locator(".ma-arm-mode")).toHaveText("기록만");
  await expect(panel.locator(".ma-arm-kill")).toHaveText("미사용");
  await expect(panel.locator(".ma-arm-facts")).toContainText("통과 2 · 미달 1 · 미상 4");
  await expect(panel.locator(".ma-arm-facts")).toContainText("적재된 실제 분봉");
  await expect(panel.locator(".ma-arm-block")).toHaveCount(0);
  await panel.locator(".ma-arm-day-pick").selectOption(DAY);
  const started = page.waitForResponse((r) => /\/rule-runs$/.test(new URL(r.url()).pathname) && r.request().method() === "POST");
  await panel.locator(".ma-arm-go").click();
  const startRes = await started;
  expect(startRes.status()).toBe(201);
  expect(startRes.request().postDataJSON(), "본문은 시행 열쇠와 날짜뿐").toEqual({ trial_key: key, day: DAY });
  const runId = (await startRes.json()).run.run_id as number;
  await expect(arm(page).locator(".ma-arm-msg")).toContainText(`가동 ${runId}번을 시작했습니다.`);
  await expect(row.locator(".ma-arm-start")).toHaveCount(0);                      // 시작하면 준비 판이 닫힌다
  await expect(arm(page).locator(".ma-arm-req")).toHaveCount(1);                  // 요청은 남는다 — 다른 날로 다시 가동할 수 있다

  // ④ 가동 중 — 시계 · 두 봉을 민 뒤(문으로) 새로 고치면 화면이 그 자리를 읽는다
  const run = runRow(page);
  await expect(run).toHaveAttribute("data-status", "running");
  await expect(run.locator(".ma-arm-status")).toHaveText("가동 중");
  await expect(run.locator(".ma-arm-daytext")).toHaveText(DAY);
  await expect(run.locator(".ma-arm-clock")).toHaveText("봉 0 / 4 · 다음 09:00");
  await expect(run.locator(".ma-arm-meter")).toHaveAttribute("aria-valuenow", "0");
  await expect(run.locator(".ma-arm-meter")).toHaveAttribute("aria-valuemax", "4");
  const two = await page.request.post(`${API}/broker-accounts/${c.account}/rule-runs/${runId}/advance`, { headers: c.headers, data: { bars: 2 } });
  expect(two.ok(), await two.text()).toBe(true);
  await arm(page).locator(".ma-arm-refresh").click();
  await expect(run.locator(".ma-arm-clock")).toHaveText("봉 2 / 4 · 다음 09:02");
  await expect(run.locator(".ma-arm-last")).toHaveText("마지막 봉 09:01");
  await expect(run.locator(".ma-arm-signals")).toHaveText("신호 0건");             // 신호 봉이 닫혔을 뿐 — 체결은 다음 봉이다

  // ⑤ 끝까지 — 가상 체결 두 줄 = 손 계산
  await run.locator(".ma-arm-finish").click();
  await expect(run).toHaveAttribute("data-status", "finished");
  await expect(run.locator(".ma-arm-status")).toHaveText("하루 끝까지 완료");
  await expect(run.locator(".ma-arm-why")).toHaveText("하루의 봉을 끝까지 돌았습니다.");
  await expect(run.locator(".ma-arm-signals")).toHaveText("신호 2건");
  await expect(run.locator(".ma-arm-step, .ma-arm-finish, .ma-arm-stop")).toHaveCount(0);   // 멈춘 가동은 되살리지 않는다
  await expect(arm(page).locator(".ma-arm-msg")).toHaveText(`가동 ${runId}번: 봉 2개를 재생했습니다. 새 가상 체결 2건. 하루의 끝까지 돌았습니다.`);
  const fills = run.locator(".ma-arm-fill");
  await expect(fills).toHaveCount(2);
  await expect(run.locator(".ma-arm-fill-at")).toHaveText(["3월 4일 09:02", "3월 4일 09:03"]);
  await expect(run.locator(".ma-arm-fill-side")).toHaveText(["매수", "매도"]);
  await expect(run.locator(".ma-arm-fill-qty")).toHaveText(["99주", "99주"]);
  await expect(run.locator(".ma-arm-fill-price")).toHaveText(["10,080원", "10,100원"]);
  await expect(run.locator(".ma-arm-fill-what").first()).toContainText("035720");
  await expect(run.locator(".ma-arm-virtual")).toHaveText(["가상", "가상"]);                           // 줄마다 표식
  await expect(run.locator(".ma-arm-fill-order")).toHaveText(["주문 경로 기록만", "주문 경로 기록만"]);   // 주문 경로의 답
  await expect(run.locator(".ma-arm-cap")).toContainText("실제 체결이 아닙니다");

  // ⑥ 같은 날의 분봉 백테스트 체결과 같다(문끼리 견준다) · 주문은 ‘기록만’ 두 줄로 남는다
  const sim = await (await page.request.post(`${API}/intraday/simulate`, { headers: c.headers, timeout: 120_000, data: {
    tickers: HAND.tickers, from: DAY, to: DAY, rule: { kind: HAND.rule, params: { minutes: 1 } },
    position: { amount: HAND.amount }, costs: { commission_bp: HAND.commission_bp, slippage_ticks: HAND.slippage_ticks, unknown_market: "KOSPI", unknown_instrument: "stock" } } })).json();
  expect(sim.journal.trades).toHaveLength(1);
  // 매매일지의 시각은 ISO(`T`)이고 가상 체결의 시각은 빈칸으로 적는다 — 같은 순간을 같은 글자로 놓고 견준다
  const at = (iso: string) => iso.replace("T", " ");
  const trade = { ...sim.journal.trades[0], opened_at: at(sim.journal.trades[0].opened_at), closed_at: at(sim.journal.trades[0].closed_at) };
  const got = (await (await page.request.get(`${API}/broker-accounts/${c.account}/rule-runs/${runId}`, { headers: c.headers })).json()).run.fills;
  expect(got.map((f: { executed_at: string; side: string; quantity: number; price: number; kind: string }) =>
    [f.executed_at, f.side, f.quantity, f.price, f.kind])).toEqual([
    [trade.opened_at, "buy", trade.quantity, trade.avg_buy, "virtual"], [trade.closed_at, "sell", trade.quantity, trade.avg_sell, "virtual"]]);
  expect([trade.opened_at, trade.quantity, trade.avg_buy, trade.closed_at, trade.avg_sell]).toEqual([`${DAY} 09:02:00`, 99, 10_080, `${DAY} 09:03:00`, 10_100]);
  const orders = page.locator(".ma-orders .ma-ord");
  await expect(orders).toHaveCount(2);
  await expect(page.locator(".ma-orders .ma-ord-status")).toHaveText(["기록만", "기록만"]);

  // ⑦ 좁은 폭 — 줄마다 ‘가상’ 표식이 옆으로 밀려 가려지지 않는다(체결이 있는 이 하루에서 잰다)
  await page.setViewportSize({ width: 390, height: 844 });
  for (const mark of await run.locator(".ma-arm-virtual").all()) {
    await mark.scrollIntoViewIfNeeded();
    await expect(mark).toBeInViewport({ ratio: 1 });
  }
  await expect(run.locator(".ma-arm-virtual")).toHaveCount(2);

  expect(uniq(sink.api404), "404").toEqual([]);
  expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("정지하면 까닭이 서버 문장으로 뜨고 다시 밀 수 없다 · 요청은 확인을 거쳐 목록에서 뺀다", async ({ page }) => {
  test.setTimeout(180_000);
  const c = await prepare(page);
  const { id } = await leaveRequest(page, c);
  await openAccount(page, c);
  const runId = await startFromScreen(page, id);
  const run = runRow(page);
  await expect(run).toHaveAttribute("data-run", String(runId));
  await expect(run.locator(".ma-arm-step")).toHaveText("다음 봉 30개");
  await run.locator(".ma-arm-stop").click();
  await expect(run).toHaveAttribute("data-status", "stopped");
  await expect(run.locator(".ma-arm-status")).toHaveText("정지");
  await expect(run.locator(".ma-arm-why")).toHaveText("사용자가 정지했습니다.");
  await expect(run.locator(".ma-arm-clock")).toHaveCount(0);                      // 멈춘 가동에는 시계가 없다
  await expect(run.locator(".ma-arm-step, .ma-arm-finish, .ma-arm-stop")).toHaveCount(0);
  await run.locator(".ma-arm-fills-open").click();
  await expect(run.locator(".ma-arm-nofills")).toHaveText("가상 체결 없음");        // 멈춘 가동은 청산을 지어내지 않는다
  const again = await page.request.post(`${API}/broker-accounts/${c.account}/rule-runs/${runId}/advance`, { headers: c.headers, data: {} });
  expect([again.status(), (await again.json()).detail.code]).toEqual([400, "not_running"]);

  // 요청 빼기 — 확인을 거친다 · '그대로 두기'는 아무것도 지우지 않는다
  const row = request(page, id);
  await row.locator(".ma-arm-remove").click();
  await row.locator(".ma-arm-remove-no").click();
  await expect(arm(page).locator(".ma-arm-req")).toHaveCount(1);
  await row.locator(".ma-arm-remove").click();
  await row.locator(".ma-arm-remove-yes").click();
  await expect(arm(page).locator(".ma-arm-req")).toHaveCount(0);
  await expect(arm(page).locator(".ma-arm-empty")).toContainText("받은 가동 요청 없음");
  await expect(arm(page).locator(".ma-arm-canvas")).toHaveAttribute("href", "/allocation");
  await expect(arm(page).locator(".ma-arm-run")).toHaveCount(1);                  // 가동 기록은 남는다
});

test("‘기록만’이 아니거나 비상 정지 중이면 시작 단추가 잠기고 까닭을 말한다 ↔ 풀면 열린다 · 서버의 거절은 서버 문장", async ({ page }) => {
  test.setTimeout(180_000);
  const c = await prepare(page);
  const { id } = await leaveRequest(page, c);
  const post = (tail: string, data: object) => page.request.post(`${API}/broker-accounts/${c.account}${tail}`, { headers: c.headers, data });

  // 모의 체결 모드 — 잠김
  expect((await post("/mode", { mode: "PAPER" })).ok()).toBe(true);
  await openAccount(page, c);
  await request(page, id).locator(".ma-arm-open").click();
  const panel = request(page, id).locator(".ma-arm-start");
  await expect(panel.locator(".ma-arm-mode")).toHaveText("모의 체결");
  await expect(panel.locator(".ma-arm-block")).toContainText("실행 모드가 ‘기록만’이 아니어서 가동할 수 없습니다.");
  await expect(panel.locator(".ma-arm-go")).toBeDisabled();

  // 기록만 + 비상 정지 — 잠김
  expect((await post("/mode", { mode: "SHADOW" })).ok()).toBe(true);
  expect((await post("/kill-switch/trigger", { reason: "E2E 점검", liquidation_mode: "hold" })).ok()).toBe(true);
  await openAccount(page, c);
  await request(page, id).locator(".ma-arm-open").click();
  await expect(panel.locator(".ma-arm-kill")).toHaveText("사용");
  await expect(panel.locator(".ma-arm-block")).toHaveText("비상 정지 중에는 가동할 수 없습니다.");
  await expect(panel.locator(".ma-arm-go")).toBeDisabled();

  // ★짝★ 풀면 열린다
  expect((await post("/kill-switch/resolve", { notes: "E2E 해제" })).ok()).toBe(true);
  await openAccount(page, c);
  await request(page, id).locator(".ma-arm-open").click();
  await expect(panel.locator(".ma-arm-block")).toHaveCount(0);
  await expect(panel.locator(".ma-arm-go")).toBeEnabled();

  // 화면이 아는 것과 서버가 어긋난 순간(다른 창에서 정지를 걸었다) — 서버가 거절하고 화면은 그 문장을 그대로 보인다
  expect((await post("/kill-switch/trigger", { reason: "다른 창", liquidation_mode: "hold" })).ok()).toBe(true);
  await panel.locator(".ma-arm-go").click();
  await expect(panel.locator(".ma-arm-refused")).toHaveText("비상 정지가 걸려 있어 가동을 시작하지 않았습니다.");
  await expect(arm(page).locator(".ma-arm-run")).toHaveCount(0);
  expect((await post("/kill-switch/resolve", { notes: "E2E 해제" })).ok()).toBe(true);
});

test("운영자 정지나 상태 조회 실패로 차단된 계좌: ‘사용’이라고 하지 않고 차단이라고 말하며 시작 단추가 잠긴다", async ({ page }) => {
  const c = await prepare(page);
  const { id } = await leaveRequest(page, c);
  // 서버의 `active` 는 운영자 전역 정지와 상태 조회 실패도 센다 — 이 계좌가 건 정지(event)가 없는 켜짐
  await page.route("**/broker-accounts/*/kill-switch", (r) => r.fulfill({ json: { active: true, event: null } }));
  await openAccount(page, c);
  await request(page, id).locator(".ma-arm-open").click();
  const panel = request(page, id).locator(".ma-arm-start");
  await expect(panel.locator(".ma-arm-kill")).toHaveText("주문 차단 중");
  await expect(panel.locator(".ma-arm-block")).toContainText("이 계좌에서 발동한 정지가 아닙니다.");
  await expect(panel.locator(".ma-arm-block")).toContainText("운영자 정지이거나 상태 조회 실패입니다.");
  await expect(panel.locator(".ma-arm-go")).toBeDisabled();
});

test("가동할 날짜는 분봉이 적재된 날만이다 · 적재된 날이 없으면 시작 단추가 잠긴다", async ({ page }) => {
  const c = await prepare(page);
  const { id } = await leaveRequest(page, c);
  const day = (date: string, status: string) => ({ date, status, tickers: 1, bars: 4, sources: null, defect_total: 0, session_shifted: false,
    blocked_rows: 0, reason: null, message: null, by_ticker: {}, missing_tickers: [] });
  const coverage = (days: object[]) => ({ from: "2026-03-02", to: "2026-03-13", gate: { mock: true }, days, empty: null, unknowns: [],
    summary: { calendar_days: 12, loaded_days: 0, blocked_days: 0, unreadable_days: 0, not_checked_days: 0, bars: 0, sources: {}, defect_total: 0 },
    session_rules: {}, limits: { days: 62, tickers: 30 } });
  // 운영에서 막힌 날(합성 행) · 읽지 못한 날 · 검사하지 않은 날은 고를 수 없다 — 적재된 날 하나만 남는다
  let days: object[] = [day("2026-03-02", "blocked"), day("2026-03-03", "loaded"), day("2026-03-04", "unreadable"), day("2026-03-05", "not_checked")];
  await page.route("**/api/v1/intraday/coverage*", (r) => r.fulfill({ json: coverage(days) }));
  await openAccount(page, c);
  await request(page, id).locator(".ma-arm-open").click();
  const panel = request(page, id).locator(".ma-arm-start");
  await expect(panel.locator(".ma-arm-day-pick option")).toHaveText(["2026-03-03"]);
  await expect(panel.locator(".ma-arm-go")).toBeEnabled();

  // ★짝★ 적재된 날이 하나도 없으면 날짜 칸 대신 그렇게 말하고 시작하지 않는다
  days = [day("2026-03-02", "blocked"), day("2026-03-04", "unreadable")];
  await request(page, id).locator(".ma-arm-open").click();           // 닫고
  await request(page, id).locator(".ma-arm-open").click();           // 다시 연다(적재 범위를 새로 읽는다)
  await expect(panel.locator(".ma-arm-nodays")).toContainText("분봉이 적재된 날 없음");
  await expect(panel.locator(".ma-arm-day-pick")).toHaveCount(0);
  await expect(panel.locator(".ma-arm-go")).toBeDisabled();
});

test("못 읽음은 빈 목록이 아니다 · 시행이 없는 요청에는 가동 단추가 없다", async ({ page }) => {
  const c = await prepare(page);
  const why = "가동 기록을 읽거나 쓰지 못했습니다.";
  await page.route("**/api/v1/intraday/arm-requests", (r) => r.fulfill({ json: { available: false, reason: why, requests: [], gate: { mock: true } } }));
  await page.route("**/rule-runs", (r) => r.fulfill({ json: { available: false, reason: why, runs: [], mode: "SHADOW", kill_switch: false,
    gate: { mock: true }, limits: { runs: 3, tickers: 10, gap_minutes: 5 } } }));
  await openAccount(page, c);
  const failed = arm(page).locator('.tx-notice[data-tone="danger"]');
  await expect(failed).toHaveCount(2);
  await expect(failed.first()).toContainText(why);
  await expect(failed.last()).toContainText(why);
  await expect(arm(page).locator(".ma-arm-empty, .ma-arm-none")).toHaveCount(0);   // '받은 가동 요청 없음' · '가동 기록 없음'으로 보이지 않는다

  await page.unroute("**/api/v1/intraday/arm-requests");
  const gone = "이 요청이 가리키는 분봉 백테스트 기록이 없습니다. 가동할 수 없는 요청입니다.";
  const noVerdict = "판정 결과를 남기지 않은 실행입니다. 관문의 상태를 알 수 없습니다.";
  await page.route("**/api/v1/intraday/arm-requests", (r) => r.fulfill({ json: { available: true, reason: null, gate: { mock: true }, requests: [
    { id: 7, trial_key: "e".repeat(64), note: null, created_at: 1_773_000_000, trial: { found: false, reason: gone }, gates: { known: false, counts: null, reason: noVerdict } }] } }));
  await openAccount(page, c);
  const row = request(page, 7);
  await expect(row.locator(".ma-arm-gone")).toHaveText(gone);
  await expect(row.locator(".ma-arm-gates")).toHaveText(`관문 일곱 ${noVerdict}`);  // 관문 수를 지어내지 않는다
  await expect(row.locator(".ma-arm-open")).toHaveCount(0);
  await expect(row.locator(".ma-arm-remove")).toBeVisible();
});

for (const theme of ["light", "dark"] as const) {
  test(`합성 분봉(${theme}): 절 맨 위에 적는다 · 대비 AA · 문체 · 좁은 폭에서 넘치지 않는다`, async ({ page }) => {
    test.setTimeout(240_000);
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    const c = await prepare(page);
    const { id } = await leaveRequest(page, c, SYNTHETIC);
    await openAccount(page, c);
    await expect(request(page, id).locator(".tx-chip", { hasText: "합성 분봉" })).toBeVisible();
    const notice = arm(page).locator('.tx-notice[data-tone="practice"]');
    await expect(notice).toContainText("합성 분봉으로 만든 요청이나 가동이 있습니다.");
    expect(await arm(page).locator(".tx-sec-body").evaluate((el) => el.firstElementChild?.classList.contains("tx-notice"))).toBe(true);   // 맨 위
    const runId = await startFromScreen(page, id, "2026-04-01");
    const run = runRow(page);
    await expect(run).toHaveAttribute("data-run", String(runId));
    await expect(run.locator(".tx-chip", { hasText: "합성 분봉" })).toBeVisible();
    await run.locator(".ma-arm-step").click();
    await expect(run.locator(".ma-arm-bars")).toHaveText("재생한 봉 30개");
    await expect(run).toHaveAttribute("data-status", "running");
    await run.locator(".ma-arm-finish").click();
    await expect(run).toHaveAttribute("data-status", "finished");
    await expect(run.locator(".ma-arm-fills, .ma-arm-nofills")).toHaveCount(1);
    await request(page, id).locator(".ma-arm-open").click();                       // 준비 판도 함께 잰다
    await expect(request(page, id).locator(".ma-arm-facts")).toContainText("합성 분봉");

    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
    const a = (await page.evaluate(contrastAudit(".ma-arm"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(30);
    expect(a.low, theme).toEqual([]);
    if (theme === "dark") expect(a.bright, "다크에 밝은 배경").toEqual([]);
    const v = (await page.evaluate(voiceAudit(".ma-arm"))) as VoiceResult;
    expect(v.checked).toBeGreaterThan(15);
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);

    await page.setViewportSize({ width: 390, height: 844 });
    const wide = await arm(page).evaluate((el) => {
      const out: string[] = [];
      const box = el.getBoundingClientRect();
      for (const child of Array.from(el.querySelectorAll<HTMLElement>(".ma-arm-req, .ma-arm-run, .ma-arm-start, .ma-arm-act, .ma-arm-what, .ma-arm-fill, .ma-arm-virtual, .ma-arm-refresh"))) {
        const r = child.getBoundingClientRect();
        if (r.right > box.right + 1 || r.left < box.left - 1) out.push(child.className);
      }
      return { out, scroll: document.documentElement.scrollWidth - document.documentElement.clientWidth };
    });
    expect(wide.out, "절 밖으로 나간 줄").toEqual([]);
    expect((await arm(page).locator(".ma-arm-refresh").boundingBox())!.height).toBeLessThan(40);   // 글자 단위로 꺾이지 않는다
    expect(wide.scroll, "가로 스크롤").toBeLessThanOrEqual(0);
  });
}
