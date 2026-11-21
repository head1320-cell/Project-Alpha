import { test, expect, type Locator, type Page } from "./fixtures";
import { liveState, routeConnection, routeGate, routeLive, signIn } from "./fixtures/admin";

/**
 * 갱신 시각 줄 — 주기 조회 화면 셋(실거래 · 백테스트 실행 · 데이터 상태) (U2-c · 설계 문서 §2.2 C14 · 계획 `docs/superpowers/plans/2026-11-21-uiux-u2-provenance.md`)
 * ─────────────────────────────────────────────────────────────────
 * 규칙 관제(내 계좌)는 실제 서버로 가동을 띄우는 `rule-arming.spec.ts` 의 관제 시험에 함께 건다.
 * 시계는 Playwright 의 가짜 시계(`page.clock`) — 시각은 흐르고 `runFor` 로 주기를 앞당긴다. 받은 때는 페이지의 시계로 견준다(±2초).
 * 지키는 것(짝으로):
 *  · '마지막 수신' 은 받은 때의 이 기기 시각(24시) — 다음 응답에 따라 간다
 *  · ★받지 못하면 앞 시각에 멈춘다★(지어내지 않는다) — 실거래는 읽기 넷이 ★모두★ 실패할 때(짝: 하나라도 받으면 간다)
 *  · 낭독하지 않는다(그 줄과 조상에 aria-live · role=status · alert · log 0) · 조회 중에도 글자가 바뀌지 않는다(실거래)
 *  · 주기는 조회 주기와 같은 값을 적는다(실거래 10 · 실행 1 · 적재 5) · 다시 읽지 않는 화면은 주기를 적지 않는다(짝)
 */

const LINE = /^(?:(\d+)초마다 다시 읽습니다 · )?마지막 수신 (\d\d):(\d\d):(\d\d)$/;
/** 줄의 받은 때(하루의 초) — 주기 글이 기대값과 같은지도 건다(null 이면 주기 글이 없어야 한다). */
async function shownSec(loc: Locator, every: number | null): Promise<number> {
  const t = (await loc.innerText()).trim();
  const m = t.match(LINE);
  expect(m, `갱신 시각 줄: '${t}'`).not.toBeNull();
  expect(m![1] ? Number(m![1]) : null, `주기 글: '${t}'`).toBe(every);
  return Number(m![2]) * 3600 + Number(m![3]) * 60 + Number(m![4]);
}
const nowSec = (page: Page) => page.evaluate(() => { const d = new Date(); return d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds(); });
async function notAnnounced(loc: Locator) {
  const hits = await loc.evaluate((el) => {
    const out: string[] = [];
    for (let n: Element | null = el; n && n !== document.body; n = n.parentElement) {
      if (n.hasAttribute("aria-live") || ["status", "alert", "log"].includes(n.getAttribute("role") ?? "")) out.push(`${n.tagName.toLowerCase()}.${n.className}`);
    }
    return out;
  });
  expect(hits, "갱신 시각 줄은 낭독 영역 안에 있지 않다").toEqual([]);
}

test("실거래: 받은 때 · 10초 뒤 다음 읽기에 간다 · ★읽기 넷이 모두 실패하면 멈춘다★(짝: 하나라도 받으면 간다) · 조회 중에도 글자 그대로 · 낭독 0", async ({ page }) => {
  test.setTimeout(90_000);
  await signIn(page, "admin");
  await routeConnection(page);
  await routeGate(page, { current: null, history: [] });
  const st = liveState();
  await routeLive(page, st);
  let reads = 0;
  page.on("response", (res) => { if (res.request().method() === "GET" && /\/api\/v1\/live\/mode$/.test(new URL(res.url()).pathname)) reads += 1; });
  await page.clock.install({ time: new Date(2026, 10, 21, 9, 0, 0) });
  await page.goto("/admin/live-trading", { waitUntil: "domcontentloaded" });
  const line = page.locator(".lv-head-act .lv-polled.tx-fresh");
  await expect(line).toHaveText(LINE, { timeout: 20_000 });
  await notAnnounced(line);
  const t1 = await shownSec(line, 10);
  expect(Math.abs((await nowSec(page)) - t1), "받은 때 = 이 기기의 지금(±2초)").toBeLessThanOrEqual(2);

  // ② 10초 뒤 — 다음 읽기에 간다
  await page.clock.runFor(10_500);
  await expect.poll(() => reads).toBe(2);
  await expect.poll(() => shownSec(line, 10)).toBeGreaterThanOrEqual(t1 + 9);
  const t2 = await shownSec(line, 10);

  // ③ 읽기 넷이 모두 실패 — 받은 것이 없다 → 앞 시각에 멈춘다(실패는 갈래마다 사유와 함께 보인다)
  st.fail = { mode: 500, balance: 500, orders: 500, kill: 500 };
  await page.clock.runFor(10_000);
  await expect.poll(() => reads).toBe(3);
  await expect(page.locator('.lv .tx-notice[data-tone="danger"]').first()).toContainText("모드 읽기 실패");
  expect(await shownSec(line, 10), "넷 모두 실패한 읽기는 받은 것이 아니다").toBe(t2);

  // ④ 짝: 잔고 하나만 실패 — 받은 것이 있어 간다
  st.fail = { balance: 500 };
  await page.clock.runFor(10_000);
  await expect.poll(() => reads).toBe(4);
  await expect.poll(() => shownSec(line, 10)).toBeGreaterThanOrEqual(t2 + 19);
  const shown = await line.innerText();

  // ⑤ 조회 중에도 글자 그대로 — 다음 읽기를 붙잡아 두고 본다(예전에는 '갱신 중입니다'로 바뀌었다)
  let release!: () => void;
  const held = new Promise<void>((r) => { release = r; });
  let heldSeen = false;
  await page.route("**/api/v1/live/mode", async (r) => { heldSeen = true; await held; return r.fallback(); });
  await page.clock.runFor(10_000);
  await expect.poll(() => heldSeen).toBe(true);
  await page.waitForTimeout(300);
  await expect(line).toHaveText(shown);
  release();
  await expect.poll(() => reads).toBe(5);
  await notAnnounced(line);
});

const RID = "bt_fresh_e2e_1";
const runStatus = () => ({
  run_id: RID, status: "simulating", progress_percent: 40, current_stage: "simulating", status_message: "시뮬레이션 100/400일",
  strategy_name: "조건 전략", created_at: 1_700_000_000, started_at: 1_700_000_001, completed_at: null, error_code: null,
  error_message: null, correlation_id: RID, is_mock_data: true, is_pit_verified: false, engine_version: "dev",
});

test("백테스트 실행: 1초마다 다시 읽고 받은 때를 적는다 · ★상태를 못 받으면 앞 시각에 멈춘다★(짝: 다시 받으면 간다) · 낭독 0", async ({ page }) => {
  test.setTimeout(60_000);
  let fail = false;
  let polls = 0;
  await page.route(new RegExp(`/runs/${RID}/status`), (r) => {
    polls += 1;
    return fail ? r.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"저장소가 잠겼습니다"}' }) : r.fulfill({ json: runStatus() });
  });
  await page.route(new RegExp(`/runs/${RID}$`), (r) => r.fulfill({ json: { ...runStatus(), input_snapshot: { universe: "kospi200" }, parameter_snapshot: {}, result: null } }));
  await page.clock.install({ time: new Date(2026, 10, 21, 10, 0, 0) });
  await page.goto(`/backtest/runs/${RID}/loading`, { waitUntil: "domcontentloaded" });
  const line = page.locator(".rs-run .rs-answer .tx-fresh");
  await expect(line).toHaveText(LINE, { timeout: 20_000 });
  await notAnnounced(line);
  const t1 = await shownSec(line, 1);
  expect(Math.abs((await nowSec(page)) - t1), "받은 때 = 이 기기의 지금(±2초)").toBeLessThanOrEqual(2);

  // 다음 응답에 따라 간다
  await page.clock.runFor(3_000);
  await expect.poll(() => shownSec(line, 1)).toBeGreaterThanOrEqual(t1 + 2);

  // 상태를 못 받는다 → 재연결 문구가 뜨고, 그동안 받은 때는 앞 값에 멈춘다
  const before = polls;
  fail = true;
  await page.clock.runFor(1_000);
  await expect.poll(() => polls).toBeGreaterThan(before);
  const frozen = await shownSec(line, 1);
  await page.clock.runFor(4_000);
  await expect.poll(() => polls).toBeGreaterThanOrEqual(before + 4);
  await expect(page.locator(".brun-reconnect")).toBeVisible();
  // 이 알림은 U2-c 전에는 뜬 적이 없다(판정이 참이 될 수 없었다) — 이제 보이므로 문체 규칙(보이는 줄표 0)을 건다.
  await expect(page.locator(".brun-reconnect")).not.toContainText("—");
  expect(await shownSec(line, 1), "못 받은 동안 받은 때가 가지 않는다").toBe(frozen);

  // 짝: 다시 받으면 간다
  fail = false;
  await page.clock.runFor(2_000);
  await expect.poll(() => shownSec(line, 1)).toBeGreaterThan(frozen);
});

const DATA = "**/api/backend/api/v1/data";
const dbChip = (page: Page) => page.locator(".dsx .tx-answer .tx-chip").filter({ hasText: "마지막 수신" });

test("데이터 상태: 적재 중이면 '5초마다 다시 읽습니다 · 마지막 수신' · 다음 응답에 간다 · 실패 알림의 시각은 같은 24시 꼴의 마지막 수신", async ({ page }) => {
  test.setTimeout(90_000);
  let n = 0;
  let failFrom = Number.POSITIVE_INFINITY;
  await page.route(`${DATA}/db-status`, async (route) => {
    n += 1;
    if (n >= failFrom) return route.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"boom"}' });
    const res = await route.fetch();
    const body = await res.json();
    body.ingest_running = { ...(body.ingest_running ?? {}), stocks: true };
    await route.fulfill({ response: res, json: body });
  });
  await page.clock.install({ time: new Date(2026, 10, 21, 13, 30, 0) });   // 오후 — 옛 꼴은 '오후 01:30:..'
  await page.goto("/admin/data", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".dsx")).toBeVisible({ timeout: 40_000 });
  const chip = dbChip(page);
  await expect(chip).toHaveText(LINE, { timeout: 20_000 });
  await notAnnounced(chip);
  const t1 = await shownSec(chip, 5);
  expect(Math.floor(t1 / 3600), "24시 꼴(13시)").toBe(13);
  expect(Math.abs((await nowSec(page)) - t1), "받은 때 = 이 기기의 지금(±2초)").toBeLessThanOrEqual(2);

  await page.clock.runFor(5_500);
  await expect.poll(() => n).toBeGreaterThanOrEqual(2);
  await expect.poll(() => shownSec(chip, 5)).toBeGreaterThanOrEqual(t1 + 4);
  const t2 = await shownSec(chip, 5);

  // 실패 → 옛 값은 남고 알림이 '최근 수신값(hh:mm:ss)' — 칩과 같은 시각 · 같은 24시 꼴
  failFrom = n + 1;
  await page.clock.runFor(5_500);
  const notice = page.getByText(/^최근 수신값입니다\((\d\d:\d\d:\d\d)\)\. 새 값 수신 실패$/);
  await expect(notice).toBeVisible({ timeout: 15_000 });
  const at = (await notice.innerText()).match(/\((\d\d):(\d\d):(\d\d)\)/)!;
  expect(Number(at[1]) * 3600 + Number(at[2]) * 60 + Number(at[3]), "알림의 시각 = 칩의 마지막 수신").toBe(t2);
  expect(await shownSec(chip, 5), "실패한 응답은 받은 것이 아니다").toBe(t2);
});

test("데이터 상태 짝: 적재가 없으면 주기 없이 '마지막 수신' 만 — 다시 읽지 않는다", async ({ page }) => {
  let n = 0;
  await page.route(`${DATA}/db-status`, async (route) => {
    n += 1;
    const res = await route.fetch();
    const body = await res.json();
    body.ingest_running = {};
    await route.fulfill({ response: res, json: body });
  });
  await page.clock.install({ time: new Date(2026, 10, 21, 13, 30, 0) });
  await page.goto("/admin/data", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".dsx")).toBeVisible({ timeout: 40_000 });
  const chip = dbChip(page);
  await expect(chip).toHaveText(LINE, { timeout: 20_000 });
  const t1 = await shownSec(chip, null);
  await page.clock.runFor(12_000);
  await page.waitForTimeout(300);
  expect(n, "적재가 없으면 다시 묻지 않는다").toBe(1);
  expect(await shownSec(chip, null)).toBe(t1);
});
