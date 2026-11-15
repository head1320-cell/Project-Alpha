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
// 관제 (W5c — 가동 줄 안의 판 · ★읽기만★):
//  · 도는 가동은 주기적으로 다시 읽고(읽기 요청뿐) 끝난 가동은 다시 묻지 않는다 · 든 채로는 손익이 아니다
//  · 끝까지 돈 가동: 비용 전 (10,100 − 10,080) × 99 = 1,980원 · 비용 2,299원 · 비용 후 −319원 = 그날의 분봉 백테스트가 낸 값 · ‘백테스트와 같음’
//  · 거절된 신호는 주문 경로의 문장과 함께 · 그 가상 체결이 손익에 들어 있다고 말한다 · 일 손실 한도까지 남은 폭
//  · 값이 없으면 0 이 아니라 사유 · 주문 기록에 없는 신호 · 한도에 닿음 · 백테스트와 다름 · 합성이면 판 맨 위
//  · 하루가 끝난 가동의 매매일지는 매매일지 결과와 같은 부품
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

/** 문으로 가동을 열고 `bars` 개(없으면 끝까지) 민다 → 가동 번호. 요청 줄 없이도 가동은 열린다(요청은 캔버스가 남기는 쪽지일 뿐이다). */
async function runByDoor(page: Page, c: Ctx, trialKey: string, bars?: number, day = DAY): Promise<number> {
  const made = await page.request.post(`${API}/broker-accounts/${c.account}/rule-runs`, { headers: c.headers, data: { trial_key: trialKey, day } });
  expect(made.status(), await made.text()).toBe(201);
  const runId = (await made.json()).run.run_id as number;
  const moved = await page.request.post(`${API}/broker-accounts/${c.account}/rule-runs/${runId}/advance`, { headers: c.headers, data: bars ? { bars } : {} });
  expect(moved.ok(), await moved.text()).toBe(true);
  return runId;
}

const monitorOf = async (page: Page, c: Ctx, runId: number) =>
  (await page.request.get(`${API}/broker-accounts/${c.account}/rule-runs/${runId}/monitor`, { headers: c.headers })).json();

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

test("관제: 도는 가동은 주기적으로 다시 읽고 · 끝까지 돈 가동은 손 계산과 같으며 그날의 분봉 백테스트와 같다고 말한다", async ({ page }) => {
  test.setTimeout(240_000);
  const sink = trackErrors(page);
  const c = await prepare(page);
  const { id } = await leaveRequest(page, c);
  await openAccount(page, c);
  const runId = await startFromScreen(page, id);
  const run = runRow(page);
  const polls: string[] = [];
  page.on("request", (r) => { if (/\/rule-runs\/\d+\/monitor$/.test(new URL(r.url()).pathname)) polls.push(r.method()); });

  // ① 도는 가동 — 아직 신호가 없다 · 견주지 않는다 · 주기적으로 다시 읽는다(읽기 요청뿐)
  await expect(run).toHaveAttribute("data-status", "running");                     // 가동 줄이 뜬 뒤에 잰다(줄이 없어서 0 인 것이 아니다)
  await expect(run.locator(".ma-arm-clock")).toBeVisible();
  await expect(run.locator(".ma-mon")).toHaveCount(0);                             // 펴기 전에는 판이 없고
  expect(polls, "펴기 전에는 관제를 묻지 않는다").toEqual([]);
  await run.locator(".ma-arm-mon-open").click();
  const mon = run.locator(".ma-mon");
  await expect(mon).toHaveAttribute("data-live", "true");
  await expect(mon.locator(".ma-mon-live")).toHaveText("가동 중: 5초마다 다시 읽습니다.");
  await expect(mon.locator(".ma-mon-signals")).toHaveText("신호 0건");
  await expect(mon.locator(".ma-mon-status")).toHaveCount(0);
  await expect(mon.locator(".ma-mon-virtual")).toHaveText("가상 0건");
  await expect(mon.locator(".ma-mon-gross")).toHaveText("비용 전 0원");
  await expect(mon.locator(".ma-mon-backtest")).toHaveAttribute("data-state", "not_compared");
  await expect(mon.locator(".ma-mon-backtest .tx-chip")).toHaveText("견주지 않음");
  await expect(mon.locator(".ma-mon-backtest")).toContainText("가동 중입니다.");
  await expect(mon.locator(".ma-mon-journal")).toHaveCount(0);                     // 하루가 끝나지 않았다
  await expect.poll(() => polls.length, { timeout: 20_000 }).toBeGreaterThanOrEqual(3);   // 처음 한 번 + 주기 조회 둘
  expect([...new Set(polls)]).toEqual(["GET"]);

  // 세 봉(09:02 의 매수까지)을 문으로 민다 → 새로 고침을 누르지 않아도 주기 조회가 읽어 온다 · 든 채로는 손익이 아니다
  const three = await page.request.post(`${API}/broker-accounts/${c.account}/rule-runs/${runId}/advance`, { headers: c.headers, data: { bars: 3 } });
  expect(three.ok(), await three.text()).toBe(true);
  await expect(mon.locator('.ma-mon-status[data-status="SHADOW_LOGGED"]')).toHaveText("기록만 1건", { timeout: 20_000 });
  await expect(mon.locator(".ma-mon-virtual")).toHaveText("가상 1건");
  await expect(mon.locator(".ma-mon-pnl .ma-mon-sub")).toHaveText("청산 0건 · 미청산 1종목(평가하지 않음)");
  await expect(mon.locator(".ma-mon-gross")).toHaveText("비용 전 0원");

  // ② 끝까지 — 손 계산: 비용 전 (10,100 − 10,080) × 99 = 1,980원 · 수수료 1.5bp × (997,920 + 999,900) = 299.673 · 매도세 20bp × 999,900 = 1,999.8
  await run.locator(".ma-arm-finish").click();
  await expect(mon).toHaveAttribute("data-live", "false");
  await expect(mon.locator(".ma-mon-live")).toHaveText("끝난 가동: 다시 읽지 않습니다.");
  await expect(mon.locator(".ma-mon-signals")).toHaveText("신호 2건");
  await expect(mon.locator(".ma-mon-status")).toHaveText(["기록만 2건"]);
  await expect(mon.locator(".ma-mon-orders")).toHaveAttribute("data-basis", "order_log");
  await expect(mon.locator(".ma-mon-virtual")).toHaveText("가상 2건");
  await expect(mon.locator(".ma-mon-broker")).toHaveText("증권사 체결 0건");
  await expect(mon.locator(".ma-mon-gross")).toHaveText("비용 전 +1,980원");
  await expect(mon.locator(".ma-mon-cost")).toHaveText("비용 2,299원");
  await expect(mon.locator(".ma-mon-net")).toHaveText("비용 후 −319원");
  await expect(mon.locator(".ma-mon-pnl .ma-mon-sub")).toHaveText("청산 1건 · 미청산 0종목");
  await expect(mon.locator(".ma-mon-rejected, .ma-mon-rejected-in, .ma-mon-unrecorded, .ma-mon-touched")).toHaveCount(0);
  await expect(mon.locator(".ma-mon-classified"), "시장 · 상품은 체결 줄에 적힌 가동 때의 값이다").toHaveCount(0);
  await expect(mon.locator(".ma-mon-limit")).toHaveAttribute("data-known", "false");   // 이 설정에는 한도가 없다 — 0원이 아니라 사유
  await expect(mon.locator(".ma-mon-limit")).toContainText("값 없음");
  await expect(mon.locator(".ma-mon-limit")).toContainText("이 설정에는 하루 최대 손실이 없습니다.");
  await expect(mon.locator(".ma-mon-kill")).toContainText("미사용");
  await expect(mon.locator(".ma-mon-feed")).toContainText("재지 않음");
  await expect(mon.locator(".ma-mon-backtest")).toHaveAttribute("data-state", "same");
  await expect(mon.locator(".ma-mon-backtest .tx-chip")).toHaveText("백테스트와 같음");
  await expect(mon.locator(".ma-mon-backtest")).toContainText("가상 체결 2줄 · 백테스트 체결 2줄");
  await expect(mon.locator('.tx-notice[data-tone="practice"]')).toHaveCount(0);     // 실제 분봉 — 합성 알림이 없다(짝은 아래)

  // ③ 같은 수가 분봉 백테스트의 문에서 나온다(문끼리 견준다)
  const sim = await (await page.request.post(`${API}/intraday/simulate`, { headers: c.headers, timeout: 120_000, data: {
    tickers: HAND.tickers, from: DAY, to: DAY, rule: { kind: HAND.rule, params: { minutes: 1 } },
    position: { amount: HAND.amount }, costs: { commission_bp: HAND.commission_bp, slippage_ticks: HAND.slippage_ticks, unknown_market: "KOSPI", unknown_instrument: "stock" } } })).json();
  const got = (await monitorOf(page, c, runId)).monitor;
  expect([got.pnl.gross, got.pnl.net]).toEqual([sim.journal.summary.gross.total, sim.journal.summary.net.total]);
  expect(got.pnl.gross).toBe(1_980);
  expect(got.pnl.cost).toBeCloseTo(299.673 + 1_999.8, 6);
  expect(got.backtest).toMatchObject({ state: "same", run_fills: 2, backtest_fills: 2 });

  // ④ 하루가 끝났다 — 그날의 체결을 매매일지 결과와 같은 부품으로(절 안의 절이라 제목 단계를 낮춘다)
  await mon.locator(".ma-mon-journal-open").click();
  const journal = mon.locator(".ma-mon-journal-body");
  await expect(journal.locator("h4.tx-sec-t")).toHaveText(["비용 전과 비용 후", "거래 목록", "값의 근거와 범위"]);
  await expect(journal.locator("h2, h3")).toHaveCount(0);
  await expect(journal.locator('.tj-sum tr[data-k="total"] .tj-sum-gross')).toHaveText("+1,980원");
  await expect(journal.locator('.tj-sum tr[data-k="total"] .tj-sum-net')).toHaveText("−319원");
  await expect(journal.locator(".tj-trades tbody tr")).toHaveCount(1);
  await expect(journal.locator(".tj-not-covered")).toContainText("호가·틱·체결 대기열");   // 시뮬레이션의 한계를 적는다(올린 파일의 이야기가 아니다)
  await expect(journal).toContainText("재생한 하루의 가상 체결을 집계한 것입니다.");

  // ⑤ 끝난 가동은 다시 묻지 않는다
  const seen = polls.length;
  await page.waitForTimeout(6_500);
  expect(polls.length, "끝난 가동의 주기 조회").toBe(seen);
  expect([...new Set(polls)]).toEqual(["GET"]);

  expect(uniq(sink.api404), "404").toEqual([]);
  expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("관제: 거절된 신호는 주문 경로의 문장과 함께 세고 그 가상 체결이 손익에 들어 있다고 말한다 · 일 손실 한도까지 남은 폭", async ({ page }) => {
  test.setTimeout(180_000);
  const c = await prepare(page);
  // 한 종목 4천만 원 — 계좌의 전략 비중 한도를 넘어 위험 검사가 매수를 거절한다(매도는 받는다). 참여율 상한을 끄는 칸은 캔버스 설정에 없어 문으로 실행한다.
  const big = await page.request.post(`${API}/intraday/simulate`, { headers: c.headers, timeout: 120_000, data: {
    tickers: HAND.tickers, from: HAND.start_date, to: HAND.end_date, rule: { kind: HAND.rule, params: { minutes: 1 } },
    position: { amount: 40_000_000, daily_loss_limit: 100_000 },
    costs: { commission_bp: 1.5, slippage_ticks: 1, participation_cap: null, unknown_market: "KOSPI", unknown_instrument: "stock" } } });
  expect(big.ok(), await big.text()).toBe(true);
  const trials = (await (await page.request.get(`${API}/intraday/trials`, { headers: c.headers })).json()).trials as
    { trial_key: string; request: { position: { amount: number; daily_loss_limit: number | null } } }[];
  const key = trials.find((t) => t.request.position.amount === 40_000_000 && t.request.position.daily_loss_limit === 100_000)!.trial_key;
  const runId = await runByDoor(page, c, key);
  await openAccount(page, c);
  const run = page.locator(`.ma-arm-run[data-run="${runId}"]`);
  await expect(run).toHaveAttribute("data-status", "finished");
  await run.locator(".ma-arm-mon-open").click();
  const mon = run.locator(".ma-mon");

  // 주문 — 기록만 1 · 거절 1. 거절은 주문 기록에 적힌 위험 검사의 문장 그대로(서버 문장)와 사유 코드
  await expect(mon.locator(".ma-mon-signals")).toHaveText("신호 2건");
  await expect(mon.locator(".ma-mon-status")).toHaveText(["기록만 1건", "거절 1건"]);
  const refused = mon.locator(".ma-mon-no");
  await expect(refused).toHaveCount(1);
  await expect(refused.locator(".ma-mon-no-what")).toContainText("3월 4일 09:02");
  await expect(refused.locator(".ma-mon-no-what")).toContainText("035720");
  await expect(refused.locator(".ma-mon-no-what")).toContainText("매수 3,968주");     // 4천만 원 ÷ 10,080원
  const logged = ((await (await page.request.get(`${API}/broker-accounts/${c.account}/orders`, { headers: c.headers })).json()).orders as
    { status: string; error_message: string | null }[]).find((o) => o.status === "REJECTED")!.error_message!;
  expect(logged).toContain("한도 초과");
  await expect(refused.locator(".ma-mon-no-why")).toContainText(logged);
  await expect(refused.locator(".ma-mon-no-why")).toContainText("risk_check_failed");
  // 가상 체결은 시뮬레이터가 계산한 것 — 거절된 신호의 체결도 손익에 들어 있고, 화면이 그렇게 말한다
  await expect(mon.locator(".ma-mon-gross")).toHaveText("비용 전 +79,360원");        // (10,100 − 10,080) × 3,968
  await expect(mon.locator(".ma-mon-rejected-in")).toHaveText("거절된 신호 1건의 가상 체결이 손익에 포함돼 있습니다. 실제 주문이었다면 없는 체결입니다.");

  // 일 손실 한도 — 닿지 않은 날: 한도 · 비용 전 누계 · 남은 폭
  const limit = mon.locator(".ma-mon-limit");
  await expect(limit).toHaveAttribute("data-touched", "false");
  await expect(limit.locator(".ma-mon-limit-of")).toHaveText("한도 100,000원");
  await expect(limit.locator(".ma-mon-limit-sum")).toHaveText("비용 전 누계 +79,360원");
  await expect(limit.locator(".ma-mon-room")).toHaveText("남은 폭 179,360원");
  await expect(limit.locator(".ma-mon-meter")).toHaveAttribute("aria-valuenow", "0");
  await expect(limit.locator(".ma-mon-meter")).toHaveAttribute("aria-valuemax", "100000");
  await expect(mon.locator(".ma-mon-backtest")).toHaveAttribute("data-state", "same");   // 거절돼도 가상 체결은 그날의 백테스트 그대로다
});

test("관제: 값이 없으면 0 이 아니라 사유 · 한도에 닿은 날 · 주문 기록에 없는 신호 · 백테스트와 다름 · 차단 · 합성이면 판 맨 위", async ({ page }) => {
  test.setTimeout(180_000);
  const c = await prepare(page);
  const runId = await runByDoor(page, c, await keptTrial(page, c));
  const real = await monitorOf(page, c, runId);
  const costWhy = "비용을 모르는 체결이 있어 비용 뒤 손익을 내지 않았습니다.";
  const logWhy = "주문 기록을 읽지 못했습니다. 가동 기록에 적힌 답으로 집계했으며 거절 문장은 없습니다.";
  const badWhy = "가동 기록에 적힌 설정을 지금의 규칙 틀로 읽지 못했습니다.";
  const differs = "가상 체결이 지금 적재된 봉으로 다시 계산한 그날의 분봉 백테스트 체결과 다릅니다. 가동 뒤에 봉이 바뀌었거나 결함입니다.";
  const atRead = "이 가동의 체결 줄에는 가동 때의 시장 · 상품이 적혀 있지 않아, 지금의 종목 마스터로 매도세를 정했습니다.";
  expect(real.monitor.pnl.classification, "실제 서버의 가동은 그때의 값을 줄에 적는다").toEqual({ basis: "recorded", reason: null });
  expect(real.run.fills.map((f: { classified: boolean }) => f.classified)).toEqual([true, true]);
  // 손실로 끝나 한도에 닿은 날 · 비용 미상 · 주문 기록에 없는 신호 · 백테스트와 다름 · 운영자 정지 · 합성 분봉
  let body: object = { ...real, run: { ...real.run, grade: "E0" }, monitor: { ...real.monitor,
    orders: { ...real.monitor.orders, unrecorded: 1 },
    pnl: { ...real.monitor.pnl, gross: -7_920, cost: null, net: null, net_reason: costWhy,
           classification: { basis: "read_time_master", reason: atRead } },
    loss_limit: { limit: 5_000, reason: null, realized_gross: -7_920, room: -2_920, touched: true },
    kill: { active: true, own: false },
    backtest: { state: "differs", reason: differs, run_fills: 2, backtest_fills: 3 } } };
  await page.route("**/rule-runs/*/monitor", (r) => r.fulfill({ json: body }));
  await openAccount(page, c);
  const run = page.locator(`.ma-arm-run[data-run="${runId}"]`);
  await run.locator(".ma-arm-mon-open").click();
  const mon = run.locator(".ma-mon");
  expect(await mon.evaluate((el) => el.firstElementChild?.classList.contains("tx-notice"))).toBe(true);     // 합성 알림이 판 맨 위
  await expect(mon.locator('.tx-notice[data-tone="practice"]')).toContainText("합성 분봉으로 가동한 기록입니다.");
  await expect(mon.locator(".ma-mon-unrecorded")).toHaveText("주문 기록에 없는 신호 1건");
  await expect(mon.locator(".ma-mon-gross")).toHaveText("비용 전 −7,920원");
  await expect(mon.locator(".ma-mon-cost")).toHaveText("비용 미상");                  // 0원이 아니다
  await expect(mon.locator(".ma-mon-net")).toHaveText("비용 후 미상");
  await expect(mon.locator(".ma-mon-pnl")).toContainText(costWhy);
  await expect(mon.locator(".ma-mon-classified")).toHaveText(atRead);                // 옛 줄 — 읽는 때의 종목 마스터로 정했다고 적는다
  const limit = mon.locator(".ma-mon-limit");
  await expect(limit).toHaveAttribute("data-touched", "true");
  await expect(limit.locator(".ma-mon-room")).toHaveText("한도 초과 2,920원");
  await expect(limit.locator(".ma-mon-touched")).toHaveText("한도에 닿았습니다. 그날은 새로 진입하지 않습니다.");
  await expect(limit.locator(".ma-mon-meter")).toHaveAttribute("aria-valuenow", "5000");   // 막대는 한도에서 멈춘다
  await expect(mon.locator(".ma-mon-kill")).toContainText("주문 차단 중");            // 이 계좌가 건 정지가 아니다 — ‘사용’이라고 하지 않는다
  await expect(mon.locator(".ma-mon-kill")).toContainText("이 계좌에서 발동한 정지가 아닙니다.");
  await expect(mon.locator(".ma-mon-backtest")).toHaveAttribute("data-state", "differs");
  await expect(mon.locator(".ma-mon-backtest .tx-chip")).toHaveText("백테스트와 다름");
  await expect(mon.locator(".ma-mon-backtest")).toContainText(differs);
  await expect(mon.locator(".ma-mon-backtest")).toContainText("가상 체결 2줄 · 백테스트 체결 3줄");

  // ★짝★ 이 계좌가 건 정지 · 한도가 딱 맞은 날 · 설정을 읽지 못함 · 주문 기록을 읽지 못함 · 모르는 주문 상태
  body = { ...real, monitor: { ...real.monitor,
    orders: { ...real.monitor.orders, basis: "run_record", reason: logWhy, unrecorded: null, by_status: { SHADOW_LOGGED: 1, HELD_BY_BROKER: 1 } },
    fills: { virtual: 2, broker: null, broker_reason: logWhy },
    pnl: { available: false, reason: badWhy, gross: null, cost: null, net: null, net_reason: null, closed_trades: null, open_positions: null,
           includes_rejected: null, basis: null, classification: null },
    loss_limit: { limit: null, reason: badWhy, realized_gross: null, room: null, touched: null },
    kill: { active: true, own: true },
    backtest: { state: "unknown", reason: badWhy, run_fills: 2, backtest_fills: null }, journal: null } };
  await run.locator(".ma-arm-mon-open").click();                                   // 닫고
  await run.locator(".ma-arm-mon-open").click();                                   // 다시 편다(새로 읽는다)
  await expect(mon.locator(".ma-mon-orders")).toHaveAttribute("data-basis", "run_record");
  await expect(mon.locator(".ma-mon-orders")).toContainText(logWhy);
  await expect(mon.locator(".ma-mon-status")).toHaveText(["기록만 1건", "HELD_BY_BROKER 1건"]);   // 모르는 상태는 원문 그대로
  await expect(mon.locator(".ma-mon-unrecorded")).toHaveCount(0);                  // 모른다 — '0건'이라고도 하지 않는다
  await expect(mon.locator(".ma-mon-broker")).toHaveText("증권사 체결 미상");
  await expect(mon.locator(".ma-mon-pnl")).toHaveAttribute("data-available", "false");
  await expect(mon.locator(".ma-mon-pnl")).toContainText("값 없음");
  await expect(mon.locator(".ma-mon-pnl")).toContainText(badWhy);
  await expect(mon.locator(".ma-mon-gross, .ma-mon-net")).toHaveCount(0);           // 0원을 그리지 않는다
  await expect(mon.locator(".ma-mon-limit")).toHaveAttribute("data-known", "false");
  await expect(mon.locator(".ma-mon-kill")).toContainText("사용");
  await expect(mon.locator(".ma-mon-kill")).not.toContainText("차단");
  await expect(mon.locator(".ma-mon-backtest .tx-chip")).toHaveText("견줌 미상");
  await expect(mon.locator(".ma-mon-journal")).toHaveCount(0);
  await expect(mon.locator('.tx-notice[data-tone="practice"]')).toHaveCount(0);     // 실제 분봉의 가동 — 합성 알림이 없다

  // 관제를 읽지 못하면 빈 판이 아니라 실패라고 말한다
  await page.unroute("**/rule-runs/*/monitor");
  await page.route("**/rule-runs/*/monitor", (r) => r.fulfill({ status: 503, json: { detail: { code: "store_unavailable", reason: "가동 기록이나 실행 기록을 읽거나 쓰지 못했습니다(없는 것과 다릅니다)." } } }));
  await run.locator(".ma-arm-mon-open").click();
  await run.locator(".ma-arm-mon-open").click();
  await expect(mon.locator('.tx-notice[data-tone="danger"]')).toContainText("관제 조회 실패");
  await expect(mon.locator(".ma-mon-grid")).toHaveCount(0);
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
    await run.locator(".ma-arm-mon-open").click();                                 // 관제 판도 함께 잰다 — 합성 분봉의 가동이면 판 맨 위에 적는다
    const mon = run.locator(".ma-mon");
    await expect(mon.locator(".ma-mon-grid")).toBeVisible();
    expect(await mon.evaluate((el) => el.firstElementChild?.classList.contains("tx-notice"))).toBe(true);
    await expect(mon.locator('.tx-notice[data-tone="practice"]')).toContainText("합성 분봉으로 가동한 기록입니다.");
    if (await mon.locator(".ma-mon-journal-open").count()) await mon.locator(".ma-mon-journal-open").click();   // 체결이 있는 날이면 매매일지도 편다

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
      for (const child of Array.from(el.querySelectorAll<HTMLElement>(".ma-arm-req, .ma-arm-run, .ma-arm-start, .ma-arm-act, .ma-arm-what, .ma-arm-fill, .ma-arm-virtual, .ma-arm-refresh, .ma-mon, .ma-mon-cell, .ma-mon-cell dd, .ma-mon-backtest, .ma-mon-journal-body > .tx-sec"))) {
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
