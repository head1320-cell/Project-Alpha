import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page, type Response } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════════════════════════
// 백테스트 › 분봉 규칙 › '시장 국면' › '하루 유형 비중 더하기(선택)' (K5 · 2026-11-18 · 구현 계획 §7.6)
// 분봉: `seed_share_bars.py` — 평일 2021-11-01 ~ 2025-03-31 · 005930 · 000660(모의 수집기 · 합성).
// 모형: 학습 문으로 2022-01-03 ~ 03-31 · 장 시작 30분 · 유형 넷(같은 입력 = 같은 열쇠).
// 지수는 E2E 서버(mock 게이트)의 합성 걸음이고 분봉도 합성이다 — 그래서 여기서 거는 것은 장치다:
//  · 모형 · 유형 · 바구니는 비어서 시작(도구가 고르지 않는다) · 다 채우기 전에는 묻지 않는다
//  · 유형을 전부 고르면 잠기고 안내는 서버의 거절 문장과 같다
//  · 비중 세기는 끝날 때까지 이어 묻고(심은 답 셋) · 멈춤을 누르면 더 묻지 않는다 · 진행 줄 = 서버의 수 · 요청 = 폼
//  · 국면 보기: 요청 = 폼 · 두 띠의 날마다 가장 큰 국면 = 서버 · 비중 그림의 값 = 서버 · 사실 줄 · 한계 문장 = 서버 글자 그대로
//  · 합성이면 맨 위 알림 · 거절은 서버 사유 · 실패는 재시도 · 모형이 없을 때 · 목록을 못 읽을 때 · 유형을 바꾸면 앞의 답을 지운다
//  · 라이트/다크 AA · 문체 · 390px
// ════════════════════════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const HERE = "/backtest/intraday";
const TRAIN = { tickers: ["005930", "000660"], from: "2022-01-03", to: "2022-03-31", minutes: 30, k: 4 };
const PERIOD = { k: "2", from: "2025-01-02", to: "2025-03-31" };
const BASKET = "005930, 000660";
const NO_MODELS = "학습한 하루 유형 모형이 없습니다. 백테스트 › 분봉 규칙의 ‘하루 유형’에서 먼저 학습합니다.";
const IS_COUNT = (u: string) => new URL(u).pathname.endsWith("/intraday/market-regime/day-type-counts");
const IS_INPUT = (u: string) => new URL(u).pathname.endsWith("/intraday/market-regime/day-type-input");
const IS_LIST = (u: string) => /\/intraday\/day-types$/.test(new URL(u).pathname);
const n = (v: number) => v.toLocaleString("ko-KR");

type Day = { date: string; probs: number[] | null; top: number | null; reason: string | null };
type Regime = { days: Day[]; notes: string[]; empty: { reason: string; message: string } | null; grade: string | null };
type CountAnswer = { needed_days: number; counted_days: number; remaining_days: number; stale_days: number; done: boolean };
type Center = { state: number; r20: number; sigma20: number; share: number };
type InputAnswer = {
  index_only: Regime; with_share: Regime & { centers: Center[] | null }; facts: string[]; notes: string[];
  share: { days: { date: string; value: number | null; samples: number; reason: string | null; message: string | null }[]; grade: string | null } | null;
  counts: { needed_days: number; counted_days: number; remaining_days: number } | null;
};

test.beforeAll(() => {
  test.setTimeout(300_000);
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_share_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe", timeout: 280_000 });
});

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

/** 학습 문으로 모형 하나(같은 입력은 같은 열쇠 — 몇 번 불러도 같은 모형). */
async function trainModel(page: Page, token: string): Promise<string> {
  const r = await page.request.post(`${API}/intraday/day-types`, { data: TRAIN, headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  return (await r.json()).model.key as string;
}

/** 화면을 열고 위의 국면 폼(국면 수 · 기간)을 채운다 — 하위 절은 그 값을 그대로 쓴다. */
async function open(page: Page): Promise<{ token: string; model: string }> {
  const token = await login(page);
  const model = await trainModel(page, token);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-mr-k")).toBeVisible();
  await page.locator(".itd-mr-k").selectOption(PERIOD.k);
  await page.locator(".itd-mr-from").fill(PERIOD.from);
  await page.locator(".itd-mr-to").fill(PERIOD.to);
  await expect(page.locator(".itd-mrs")).toBeVisible();
  return { token, model };
}

async function pick(page: Page, model: string, types: number[], basket = BASKET): Promise<void> {
  await page.locator(".itd-mrs-model").selectOption(model);
  for (const t of types) await page.locator(`.itd-mrs-type[data-type="${t}"]`).check();
  await page.locator(".itd-mrs-tickers").fill(basket);
}

/** 비중 세기를 눌러 끝날 때까지 — 받은 답들을 모은다(진행 줄과 견준다). */
async function countAll(page: Page): Promise<CountAnswer[]> {
  const seen: CountAnswer[] = [];
  const onResp = (r: Response) => {
    if (IS_COUNT(r.url()) && r.request().method() === "POST" && r.ok()) void r.json().then((js: CountAnswer) => seen.push(js));
  };
  page.on("response", onResp);
  await page.locator(".itd-mrs-count").click();
  await expect(page.locator(".itd-mrs-progress")).toHaveAttribute("data-done", "true", { timeout: 240_000 });
  await expect.poll(() => seen.at(-1)?.done ?? false).toBe(true);
  page.off("response", onResp);
  return seen;
}

async function look(page: Page): Promise<{ js: InputAnswer; url: URL }> {
  const got = page.waitForResponse((r) => IS_INPUT(r.url()), { timeout: 120_000 });
  await page.locator(".itd-mrs-run").click();
  const resp = await got;
  expect(resp.ok(), await resp.text()).toBe(true);
  await expect(page.locator(".itd-mrs-result")).toBeVisible();
  return { js: (await resp.json()) as InputAnswer, url: new URL(resp.url()) };
}

/** 심은 세기 답 — i 번째 부름에 센 날 i × 100 · 필요한 날 total × 100. */
const fakeCount = (i: number, total: number) => ({
  model: "x", index: "KOSPI", from: PERIOD.from, to: PERIOD.to, tickers: ["005930", "000660"],
  needed_days: total * 100, counted_days: i * 100, remaining_days: (total - i) * 100, stale_days: 0, done: i >= total,
  first_day: "2021-08-31", last_day: "2025-03-28", next_day: i >= total ? null : "2023-01-02",
  this_request: { days: 100, rows: 200, stale_rows: 0, bytes: 1, seconds: 0.1, stopped: i >= total ? null : "budget" },
  excluded_by_reason: {}, excluded_messages: {}, grade: "E0", grade_reason: "합성", gate: { mock: true },
  limits: { budget_sec: 8, bytes: 1, tickers: 30, window: 20, history_calendar_days: 1250 },
});

// ── 비어서 시작 · 고르기 ────────────────────────────────────────────────────────────────────────
test("모형 · 유형 · 바구니는 비어서 시작하고 다 채우기 전에는 묻지 않는다", async ({ page }) => {
  const sent: string[] = [];
  page.on("request", (r) => { if (IS_COUNT(r.url()) || IS_INPUT(r.url())) sent.push(r.url()); });
  const { model } = await open(page);
  await expect(page.locator(".itd-mrs-model")).toHaveValue("");
  await expect(page.locator(".itd-mrs-type")).toHaveCount(0);
  await expect(page.locator(".itd-mrs-tickers")).toHaveValue("");
  await expect(page.locator(".itd-mrs-count")).toBeDisabled();
  await expect(page.locator(".itd-mrs-run")).toBeDisabled();
  await expect(page.locator(".itd-mrs-problems li").first()).toBeVisible();
  await page.locator(".itd-mrs-model").selectOption(model);
  await expect(page.locator(".itd-mrs-type")).toHaveCount(TRAIN.k);            // 그 모형의 유형 수만큼
  await expect(page.locator(".itd-mrs-type:checked")).toHaveCount(0);
  await expect(page.locator(".itd-mrs-run")).toBeDisabled();                     // 유형도 바구니도 아직
  expect(sent).toEqual([]);
});

test("유형을 전부 고르면 잠기고 안내는 서버의 거절 문장과 같다", async ({ page }) => {
  const { token, model } = await open(page);
  await pick(page, model, [1, 2, 3, 4]);
  const q = new URLSearchParams([["index", "KOSPI"], ["k", PERIOD.k], ["from", PERIOD.from], ["to", PERIOD.to], ["model", model],
    ["types", "1"], ["types", "2"], ["types", "3"], ["types", "4"], ["tickers", "005930"], ["tickers", "000660"]]);
  const r = await page.request.get(`${API}/intraday/market-regime/day-type-input?${q.toString()}`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.status()).toBe(400);
  const refusal = (await r.json()).detail as { code: string; reason: string };
  expect(refusal.code).toBe("all_types");
  await expect(page.locator(".itd-mrs-all")).toHaveText(refusal.reason);
  await expect(page.locator(".itd-mrs-run")).toBeDisabled();
  await page.locator('.itd-mrs-type[data-type="4"]').uncheck();                    // 짝 — 하나를 풀면 열린다
  await expect(page.locator(".itd-mrs-all")).toHaveCount(0);
  await expect(page.locator(".itd-mrs-run")).toBeEnabled();
});

// ── 비중 세기 ───────────────────────────────────────────────────────────────────────────────────
test("비중 세기는 끝날 때까지 이어 묻고 진행 줄은 서버의 수다(요청 = 폼)", async ({ page }) => {
  test.setTimeout(300_000);
  const { model } = await open(page);
  await pick(page, model, [1]);
  const bodies: unknown[] = [];
  page.on("request", (r) => { if (IS_COUNT(r.url()) && r.method() === "POST") bodies.push(r.postDataJSON()); });
  const seen = await countAll(page);
  const last = seen.at(-1)!;
  expect(last.done).toBe(true);
  expect(last.counted_days).toBe(last.needed_days);
  await expect(page.locator(".itd-mrs-progress-text")).toHaveText(`센 날 ${n(last.counted_days)} / 필요한 날 ${n(last.needed_days)}`);
  await expect(page.locator(".itd-mrs-progress-state")).toHaveText("다 셌습니다.");
  await expect(page.locator(".itd-mrs-bar")).toHaveAttribute("value", String(last.counted_days));
  expect(bodies.length).toBe(seen.length);
  for (const b of bodies) {
    expect(b).toEqual({ model, tickers: ["005930", "000660"], index: "KOSPI", from: PERIOD.from, to: PERIOD.to });
  }
});

test("남은 날이 있으면 이어 묻고 끝나면 멈춘다(심은 답 셋)", async ({ page }) => {
  const { model } = await open(page);
  let calls = 0;
  await page.route((u) => IS_COUNT(u.toString()), async (route) => { calls += 1; await route.fulfill({ json: fakeCount(calls, 3) }); });
  await pick(page, model, [1]);
  await page.locator(".itd-mrs-count").click();
  await expect(page.locator(".itd-mrs-progress")).toHaveAttribute("data-done", "true");
  await expect(page.locator(".itd-mrs-progress-text")).toHaveText(`센 날 ${n(300)} / 필요한 날 ${n(300)}`);
  await page.waitForTimeout(500);
  expect(calls).toBe(3);                                                            // 끝난 뒤에는 더 묻지 않는다
});

test("멈춤을 누르면 더 묻지 않고 이어 세기로 계속한다", async ({ page }) => {
  const { model } = await open(page);
  let calls = 0;
  await page.route((u) => IS_COUNT(u.toString()), async (route) => {
    calls += 1;
    await new Promise((res) => setTimeout(res, 300));
    await route.fulfill({ json: fakeCount(Math.min(calls, 9), 10) });
  });
  await pick(page, model, [1]);
  await page.locator(".itd-mrs-count").click();
  await expect(page.locator(".itd-mrs-stop")).toBeVisible();
  await expect.poll(() => calls).toBeGreaterThanOrEqual(1);
  await page.locator(".itd-mrs-stop").click();
  await expect(page.locator(".itd-mrs-progress")).toHaveAttribute("data-state", "stopped");
  const atStop = calls;
  await page.waitForTimeout(1_200);
  expect(calls).toBe(atStop);
  await expect(page.locator(".itd-mrs-count")).toHaveText("이어 세기");
  await expect(page.locator(".itd-mrs-stop")).toHaveCount(0);
  await expect(page.locator(".itd-mrs-progress-state")).toContainText("멈췄습니다.");
});

// ── 국면 보기 ───────────────────────────────────────────────────────────────────────────────────
test("국면 보기 — 요청 = 폼 · 두 띠 · 비중 그림 · 사실 줄 · 한계 문장 = 서버 값", async ({ page }) => {
  test.setTimeout(300_000);
  const { model } = await open(page);
  await pick(page, model, [1, 3]);
  await countAll(page);
  const { js, url } = await look(page);
  expect(url.searchParams.get("index")).toBe("KOSPI");
  expect(url.searchParams.get("k")).toBe(PERIOD.k);
  expect([url.searchParams.get("from"), url.searchParams.get("to")]).toEqual([PERIOD.from, PERIOD.to]);
  expect(url.searchParams.get("model")).toBe(model);
  expect(url.searchParams.getAll("types")).toEqual(["1", "3"]);
  expect(url.searchParams.getAll("tickers")).toEqual(["005930", "000660"]);

  await expect(page.locator(".itd-mrs-band")).toHaveCount(2);
  // 두 띠가 한 화면에 있다 — 빗금 무늬 등 `id` 가 겹치면 뒤 띠가 앞 띠의 무늬를 가리킨다(문서의 id 는 하나여야 한다).
  const ids = await page.locator(".itd-mrs [id]").evaluateAll((els) => els.map((e) => e.id));
  expect(ids.length).toBeGreaterThan(0);
  expect(ids.filter((id, i) => ids.indexOf(id) !== i)).toEqual([]);
  for (const which of ["index_only", "with_share"] as const) {
    const days = page.locator(`.itd-mrs-band[data-which="${which}"] .itd-mr-day`);
    await expect(days).toHaveCount(js[which].days.length);
    const tops = await days.evaluateAll((els) => els.map((e) => e.getAttribute("data-top")));
    expect(tops).toEqual(js[which].days.map((d) => (d.top === null ? "unknown" : String(d.top))));
  }
  expect(js.with_share.days.some((d) => d.top !== null)).toBe(true);              // 공허하지 않다 — 다 센 뒤에는 값이 있다

  const share = page.locator(".itd-mrs-share .itd-mrs-share-day");
  await expect(share).toHaveCount(js.share!.days.length);
  const values = await share.evaluateAll((els) => els.map((e) => e.getAttribute("data-value")));
  expect(values).toEqual(js.share!.days.map((d) => (d.value === null ? "unknown" : String(d.value))));
  // 그림 자체 — 막대는 바닥선에서 서고 높이는 비중에 비례한다(속성만 맞고 그림이 뒤집혀도 걸리게).
  const bars = await share.evaluateAll((gs) => gs.map((g) => {
    const r = g.querySelector("rect.itd-mrs-share-bar");
    return r ? { y: Number(r.getAttribute("y")), h: Number(r.getAttribute("height")) } : null;
  }));
  const base = Number(await page.locator(".itd-mrs-share-base").getAttribute("y1"));
  const drawn = js.share!.days.map((d, i) => ({ v: d.value, bar: bars[i] })).filter((x) => x.v !== null && x.v > 0);
  expect(drawn.length).toBeGreaterThan(10);
  const scale = drawn[0].bar!.h / drawn[0].v!;
  for (const x of drawn) {
    expect(x.bar).not.toBeNull();
    expect(x.bar!.y + x.bar!.h).toBeCloseTo(base, 3);
    expect(x.bar!.h / x.v!).toBeCloseTo(scale, 3);
  }

  await expect(page.locator(".itd-mrs-facts li")).toHaveText(js.facts);
  await expect(page.locator(".itd-mrs-notes li")).toHaveText(js.notes);
  await expect(page.locator(".itd-mrs-wsfacts .itd-mr-notes li")).toHaveText(js.with_share.notes);
  await expect(page.locator(".itd-mrs-synth")).toBeVisible();                     // mock — 합성 분봉 · 합성 지수

  // 국면별 중심 = 서버의 성분 평균(마지막 적합 창) — 칸마다 화면 글자를 수로 읽어 서식의 반올림 안에서 견준다(칸이 뒤바뀌면 걸린다).
  const centers = js.with_share.centers!;
  expect(centers.length).toBe(Number(PERIOD.k));
  const rows = page.locator(".itd-mrs-centers tbody tr");
  await expect(rows).toHaveCount(centers.length);
  const shown = await rows.evaluateAll((trs) => trs.map((tr) => ({
    state: tr.getAttribute("data-state"), cells: [...tr.querySelectorAll("td")].map((td) => (td.textContent ?? "").trim()) })));
  const pct = (s: string) => Number(s.replace(/[−–]/g, "-").replace(/[+%,\s]/g, "")) / 100;
  shown.forEach((row, i) => {
    const c = centers[i];
    expect(row.state).toBe(String(c.state));
    expect(row.cells[0]).toBe(`국면 ${c.state}`);
    expect(Math.abs(pct(row.cells[1]) - c.r20)).toBeLessThanOrEqual(0.00005 + 1e-9);     // 20거래일 수익(로그) — 소수 두 자리 %
    expect(Math.abs(pct(row.cells[2]) - c.sigma20)).toBeLessThanOrEqual(0.0005 + 1e-9);  // 실현 변동성(연율) — 소수 한 자리 %
    expect(Math.abs(pct(row.cells[3]) - c.share)).toBeLessThanOrEqual(0.0005 + 1e-9);    // 하루 유형 비중 — 소수 한 자리 %
  });
});

test("유형을 바꾸면 앞의 답을 지운다 · 다시 보면 새 유형으로 묻는다", async ({ page }) => {
  test.setTimeout(300_000);
  const { model } = await open(page);
  await pick(page, model, [1]);
  await countAll(page);
  await look(page);
  await page.locator('.itd-mrs-type[data-type="2"]').check();
  await expect(page.locator(".itd-mrs-result")).toHaveCount(0);
  const { url } = await look(page);
  expect(url.searchParams.getAll("types")).toEqual(["1", "2"]);
});

// ── 거절 · 실패 · 목록 ────────────────────────────────────────────────────────────────────────────
test("거절은 서버 사유 그대로 · 실패는 다시 시도", async ({ page }) => {
  const { model } = await open(page);
  await pick(page, model, [1]);
  const refusal = "심은 거절: 하루 유형 모형의 학습 기간이 판정 기간과 겹칩니다.";
  await page.route((u) => IS_INPUT(u.toString()), (route) => route.fulfill({ status: 400, json: { detail: { code: "day_type_model_overlaps", reason: refusal } } }));
  await page.locator(".itd-mrs-run").click();
  await expect(page.locator(".itd-mrs-fail")).toContainText(refusal);
  await expect(page.locator(".itd-mrs-fail button")).toHaveCount(0);              // 거절은 다시 시도할 일이 아니다
  await page.unroute((u) => IS_INPUT(u.toString()));

  let fail = true;
  await page.route((u) => IS_COUNT(u.toString()), async (route) => {
    if (fail) { fail = false; await route.fulfill({ status: 503, json: { detail: { code: "counts_store_unavailable", reason: "심은 장애: 센 값 저장소" } } }); }
    else await route.fulfill({ json: fakeCount(1, 1) });
  });
  await page.locator(".itd-mrs-count").click();
  await expect(page.locator(".itd-mrs-fail")).toContainText("심은 장애: 센 값 저장소");
  await page.locator(".itd-mrs-fail button").click();
  await expect(page.locator(".itd-mrs-progress")).toHaveAttribute("data-done", "true");
});

test("모형이 없으면 안내 · 목록을 못 읽으면 그 사유", async ({ page }) => {
  // 화면이 열린 뒤에 가로챈다 — 같은 화면의 '하루 유형' 절도 같은 목록 문을 읽으므로 열기 전에 심으면 그 절까지 심은 답을 받는다.
  // 칸에 들어갈 때마다 이 하위 절만 다시 읽는다(다른 칸에 갔다가 돌아온다).
  await open(page);
  await page.route((u) => IS_LIST(u.toString()), (route) => route.fulfill({ json: {
    available: true, reason: null, models: [], hidden_synthetic: 0, hidden_reason: null, gate: { mock: true }, limits: {} } }));
  await page.locator(".itd-mrs-tickers").focus();
  await page.locator(".itd-mrs-model").focus();
  await expect(page.locator(".itd-mrs-no-models")).toHaveText(NO_MODELS);
  await page.unroute((u) => IS_LIST(u.toString()));
  const failed = "심은 장애: 하루 유형 모형 목록을 읽지 못했습니다.";
  await page.route((u) => IS_LIST(u.toString()), (route) => route.fulfill({ status: 503, json: { detail: failed } }));
  await page.locator(".itd-mrs-tickers").focus();
  await page.locator(".itd-mrs-model").focus();
  await expect(page.locator(".itd-mrs-models-note")).toHaveText(failed);
  await expect(page.locator(".itd-mrs-no-models")).toHaveCount(0);
});

for (const theme of ["light", "dark"] as const) {
  test(`대비(${theme}) AA · 문체 · 390px 에서 비중을 더한 국면이 넘치지 않는다`, async ({ page }) => {
    test.setTimeout(300_000);
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    const { model } = await open(page);
    await pick(page, model, [1]);
    await countAll(page);
    await look(page);
    const a = (await page.evaluate(contrastAudit(".itd-mrs"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(20);
    expect(a.low, theme).toEqual([]);
    const v = (await page.evaluate(voiceAudit(".itd-mrs"))) as VoiceResult;
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".itd-mrs-result")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    // 국면별 중심의 네 칸은 390px 에서도 가로 스크롤 없이 다 보인다(머리글이 줄을 바꾼다) — 이 절의 칸인 '하루 유형 비중'이 스크롤 뒤로 숨지 않게.
    // 첫 촬영 검수에서 찾았다(그때 351px 표가 270px 칸에 들어 넷째 칸이 가려졌다).
    const centersBox = page.locator(".itd-mrs-centersbox .itd-mr-scroll");
    await expect(centersBox).toBeVisible();
    expect(await centersBox.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  });
}
