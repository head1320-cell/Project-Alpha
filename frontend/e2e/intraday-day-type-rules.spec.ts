import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page, type Request } from "./fixtures";
import { contrastAudit, trackErrors, uniq, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 하루 유형 조건(T2 · 2026-11-17 · 구현 계획 2026-11-16 §6) — 백테스트 › 분봉 규칙의 '직접 구성' · 캔버스 분봉 설정 노드
// 분봉: `seed_day_types.py`(학습 — 005380 · 035420 · 2026-05-04 ~ 05-19 · 5분 · 유형 넷) + `seed_day_type_rules.py`(판정 날 넷).
//  · 번호(끝값 오름차순): 1 = 내림 · 2 = V · 3 = 역V · 4 = 오름.
//  · 판정 날: 07-01 역V · 07-02 오름 · 07-03 내림 · 07-06 V — 날마다 두 종목이 같은 경로 · 봉 여덟(창 다섯 + 뒤 셋).
//  · '하루 유형 3 > 0.5' → 07-01 에만 09:04(창의 마지막 봉)에 서고 09:05 시가에 산다 → 거래 2건(두 종목) · 그날 청산.
//    짝: 번호 4 → 07-02 에만.
// 거는 것: 모형 칸은 비어서 시작(도구가 고르지 않는다) · 보낸 나무 = 화면 · 규칙의 글 · 주석 · 사실 줄 = 서버 문장 ·
//  모형을 고르지 않으면 실행이 잠기고 서버에 묻지 않는다 · 번호 > 유형 수는 그 칸과 서버가 말한다 ·
//  학습 기간과 겹치면 서버가 거절(문장 그대로) ↔ 학습 끝 다음 날부터면 돈다 · 모형이 없을 때 · 목록을 못 읽을 때 · 칸에 들어갈 때마다 다시 읽는다 ·
//  판정도 같은 모형으로 · 캔버스도 같은 부품과 같은 사실 줄 · 라이트/다크 AA · 문체 · 390px
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const HERE = "/backtest/intraday";
const TRAIN = { tickers: ["005380", "035420"], from: "2026-05-04", to: "2026-05-19", minutes: 5, k: 4 };
const JUDGE = { tickers: "005380, 035420", from: "2026-07-01", to: "2026-07-06" };
const NOTE = "하루 유형은 장 시작 N분의 창이 끝난 봉부터 값이 있습니다. 창이 어긋난 날은 값이 없어 조건을 충족하지 않습니다. 모형의 학습 기간이 끝난 뒤의 날에만 씁니다.";
const OVERLAP = "하루 유형 모형의 학습 기간이 판정 기간과 겹치거나 판정 기간보다 뒤에 있습니다. 학습은 판정 시작일 전에 끝나야 합니다.";
const OVER_K = "유형 번호가 그 모형의 유형 수보다 큽니다.";
const NO_MODELS = "학습한 하루 유형 모형이 없습니다. 백테스트 › 분봉 규칙의 ‘하루 유형’에서 먼저 학습합니다.";
const DOWN = "하루 유형 모형 저장소를 읽거나 쓰지 못했습니다(모형이 없는 것과 다릅니다).";
const LIST = /\/intraday\/day-types(\?|$)/;

test.beforeAll(() => {
  for (const script of ["seed_day_types.py", "seed_day_type_rules.py"]) {
    execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", script)],
      { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
  }
});

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

/** 심은 네 유형으로 학습한다 → 모형 열쇠(같은 입력은 같은 모형 — 다시 학습하지 않는다). */
async function trained(page: Page, token: string): Promise<string> {
  const r = await page.request.post(`${API}/intraday/day-types`, { data: TRAIN, headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  return (await r.json()).model.key as string;
}

/** 서버의 사실 줄 — 학습 기간 · 종목 수 · 판정 종목과 같은지(손으로 적은 기대값). */
const facts = (key: string) => [
  `하루 유형 모형 ${key.slice(0, 8)}의 학습 기간은 2026-05-04~2026-05-19이며 종목 2개로 학습했습니다. 학습은 판정 시작일 전에 끝났습니다.`,
  "판정 종목과 같은 종목으로 학습했습니다.",
];
const entry = (page: Page) => page.locator('.ire-slot[data-slot="entry"]');
const pick = (page: Page) => entry(page).getByLabel("하루 유형 모형", { exact: true });
const num = (page: Page) => entry(page).getByLabel("하루 유형 유형 번호", { exact: true });
const ruleText = (page: Page) => page.locator(".itd-check .itd-rule-text");
const said = (key: string, n: number) => `진입 조건: 하루 유형 ${n}번(모형 ${key.slice(0, 8)}) > 0.5`;

/** 화면을 열고 판정할 종목 · 기간을 넣은 뒤 '직접 구성'을 고른다 → 토큰 · 모형 열쇠. */
async function openEditor(page: Page, period: { from: string; to: string } = JUDGE): Promise<{ token: string; key: string }> {
  const token = await login(page);
  const key = await trained(page, token);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await page.locator(".itd-tickers").fill(JUDGE.tickers);
  await page.locator(".itd-from").fill(period.from);
  await page.locator(".itd-to").fill(period.to);
  await page.locator(".itd-kinds").getByRole("radio", { name: "직접 구성" }).click();
  await expect(page.locator(".ire")).toBeVisible();
  return { token, key };
}

/** 진입 조건 한 줄 '하루 유형 [모형] [번호] > 0.5'. 모형 칸은 비어서 시작하고 번호 칸은 문법 표의 출발값(1)이다. */
async function dayTypeRow(page: Page, key: string | null, n: string) {
  const row = entry(page);
  await row.locator('.ire-add[data-add="compare"]').click();
  await row.getByLabel(/: 왼쪽 값$/).first().selectOption("ind:day_type_is");
  await expect(pick(page)).toHaveValue("");                                          // 도구는 모형을 고르지 않는다
  await expect(pick(page)).toHaveAttribute("aria-invalid", "true");
  await expect(num(page)).toHaveValue("1");
  if (key) await pick(page).selectOption(key);
  await num(page).fill(n);
  await row.getByLabel(/: 연산$/).first().selectOption("gt");
  await row.getByLabel(/: 오른쪽 값$/).first().selectOption("const");
  await row.getByLabel(/: 오른쪽 값 상수$/).first().fill("0.5");
}

/** 실행 → 보낸 요청(답까지 기다린다 — 앞의 결과를 읽지 않게). */
async function run(page: Page): Promise<Request> {
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/simulate") && r.method() === "POST");
  const got = page.waitForResponse((r) => r.url().includes("/intraday/simulate") && r.request().method() === "POST", { timeout: 60_000 });
  await page.locator(".itd-run").click();
  const req = await sent;
  await got;
  return req;
}

const closedOn = async (page: Page): Promise<string[]> =>
  (await page.locator(".itd-result .tj-trades tbody .tj-when").allTextContents()).map((t) => t.slice(0, 10));

test("하루 유형 조건: 고른 모형의 유형 3 이면 역V 날(7월 1일)에만 산다 · 보낸 나무 = 화면 · 글 · 주석 · 사실 줄은 서버 문장 · 유형 4 면 7월 2일", async ({ page }) => {
  test.setTimeout(120_000);
  const sink = trackErrors(page);
  const { key } = await openEditor(page);
  await dayTypeRow(page, key, "3");
  await expect(pick(page)).toHaveAttribute("aria-invalid", "false");
  await expect(ruleText(page)).toHaveText(said(key, 3));                          // 규칙의 글은 서버가 짓는다
  await expect(page.locator(".itd-notes")).toContainText(NOTE);
  const req = await run(page);
  expect(req.postDataJSON().rule).toEqual({ kind: "custom", params: { entry: { op: "gt", args: [{ ind: "day_type_is", model: key, type: 3 }, { const: 0.5 }] } } });
  await expect(page.locator(".itd-result .tx-answer-s")).toContainText("시뮬레이션 거래 2건");
  expect(await closedOn(page)).toEqual(["2026-07-01", "2026-07-01"]);
  const item = page.locator(`.itd-result .itd-ctx-item[data-key="${key}"]`);
  await expect(item).toHaveAttribute("data-same", "true");
  await expect(item).toHaveAttribute("data-grade", "E3");
  await expect(item.locator(".itd-ctx-line")).toHaveText(facts(key));
  await expect(page.locator(".itd-result .itd-ctx-title")).toHaveText("규칙이 쓴 하루 유형 모형");

  // 짝 — 번호 4(오름)는 7월 2일에만 · 결과는 다시 실행해야 바뀐다
  await num(page).fill("4");
  await expect(ruleText(page)).toHaveText(said(key, 4));
  await run(page);
  await expect(page.locator(".itd-result .tx-answer-s")).toContainText("시뮬레이션 거래 2건");
  expect(await closedOn(page)).toEqual(["2026-07-02", "2026-07-02"]);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("모형을 고르지 않으면 실행이 잠기고 문제 목록이 말한다(서버에 묻지 않는다) · 번호가 유형 수보다 크면 그 칸이 말하고 서버가 거절한다", async ({ page }) => {
  const { key } = await openEditor(page);
  let expanded = 0;
  page.on("request", (r) => { if (r.url().includes("/intraday/rules/expand")) expanded += 1; });
  await dayTypeRow(page, null, "3");
  await expect(page.locator(".itd-problems li")).toHaveText(["진입 조건: 하루 유형 모형을 고르십시오."]);
  await expect(page.locator(".itd-run")).toBeDisabled();
  await expect(page.locator('.itd-check[data-state="idle"]')).toBeVisible();
  expect(expanded, "모형이 빈 조건은 서버에 묻지 않는다").toBe(0);

  await pick(page).selectOption(key);
  await expect(page.locator(".itd-problems")).toHaveCount(0);
  await expect(ruleText(page)).toHaveText(said(key, 3));

  // 번호 5 > 유형 4개 — 칸의 상한은 고른 모형의 유형 수다(문법 표의 상한 16 이 아니라) · 서버도 같은 사유로 거절한다
  await num(page).fill("5");
  await expect(num(page)).toHaveAttribute("aria-invalid", "true");
  await expect(ruleText(page)).toHaveText(said(key, 5));
  await run(page);
  await expect(page.locator(".itd-run-fail")).toContainText(OVER_K);
  await expect(page.locator(".itd-run-fail")).toContainText("실행 요청 거절");
  await expect(page.locator(".itd-result")).toHaveCount(0);
  await num(page).fill("4");
  await expect(num(page)).toHaveAttribute("aria-invalid", "false");                // 짝 — 상한 안이면 칸이 풀린다
});

test("학습 기간과 겹치는 판정은 서버가 거절한다(문장 그대로 · 결과 없음) ↔ 학습 끝 다음 날부터면 돈다(그 기간 분봉이 없어 결과 없음 · 사실 줄은 있다)", async ({ page }) => {
  const { key } = await openEditor(page, { from: "2026-05-19", to: "2026-05-29" });
  await dayTypeRow(page, key, "3");
  await expect(ruleText(page)).toHaveText(said(key, 3));                          // 규칙 검사는 지난다 — 겹침은 판정 기간을 보고서야 안다
  await run(page);
  await expect(page.locator(".itd-run-fail")).toContainText(OVERLAP);
  await expect(page.locator(".itd-result")).toHaveCount(0);

  await page.locator(".itd-from").fill("2026-05-20");
  await run(page);
  await expect(page.locator(".itd-run-fail")).toHaveCount(0);
  await expect(page.locator(".itd-result")).toHaveAttribute("data-empty", "not_loaded");
  await expect(page.locator(`.itd-result .itd-ctx-item[data-key="${key}"] .itd-ctx-line`)).toHaveText(facts(key));
});

test("모형 목록: 없으면 어디서 학습하는지 안내 · 못 읽으면(저장소 장애 · 문 실패) 빈 목록이 아니라 서버 사유 · 칸에 들어갈 때마다 다시 읽는다", async ({ page }) => {
  let mode: "none" | "down" | "fail" | "real" = "none";
  let listed = 0;
  const FAIL = "심은 장애: 하루 유형 모형 목록을 읽지 못했습니다.";
  await page.route(LIST, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    listed += 1;
    if (mode === "fail") return route.fulfill({ status: 503, json: { detail: FAIL } });   // 목록 문 자체가 실패(서버 사유)
    const real = await route.fetch();
    const body = await real.json();
    if (mode === "real") return route.fulfill({ response: real, json: body });
    if (mode === "none") return route.fulfill({ response: real, json: { ...body, models: [], hidden_synthetic: null, hidden_reason: null } });
    return route.fulfill({ response: real, json: { ...body, available: false, reason: DOWN, models: [] } });
  });
  const { key } = await openEditor(page);
  const row = entry(page);
  await row.locator('.ire-add[data-add="compare"]').click();
  await row.getByLabel(/: 왼쪽 값$/).first().selectOption("ind:day_type_is");
  const note = row.locator(".ire-model-note");
  await expect(note).toHaveText(NO_MODELS);
  await expect(pick(page).locator("option")).toHaveText(["모형 선택"]);

  mode = "down";
  let before = listed;
  await pick(page).focus();
  await expect.poll(() => listed).toBeGreaterThan(before);
  await expect(note).toHaveText(DOWN);                                              // 못 읽음 ≠ 없음
  await expect(note).not.toHaveText(NO_MODELS);

  mode = "fail";                                                                     // 같은 훅의 다른 갈래 — 답이 오지 않은 실패도 없음이 아니다
  await page.locator(".itd-tickers").focus();
  before = listed;
  await pick(page).focus();
  await expect.poll(() => listed).toBeGreaterThan(before);
  await expect(note).toHaveText(FAIL);

  mode = "real";
  await page.locator(".itd-tickers").focus();
  before = listed;
  await pick(page).focus();
  await expect.poll(() => listed).toBeGreaterThan(before);
  await expect(pick(page).locator(`option[value="${key}"]`)).toHaveText(`${key.slice(0, 8)} · 2026-05-04~2026-05-19 · 유형 4개 · 5분`);
  await expect(note).toHaveCount(0);
  await expect(pick(page)).toHaveValue("");                                          // 목록이 와도 고르지 않는다
});

test("판정도 같은 모형으로 돈다 — 판정 요청의 규칙 = 실행 요청의 규칙 · 답에 같은 사실 줄 · 거래 2건", async ({ page }) => {
  test.setTimeout(120_000);
  const { key } = await openEditor(page);
  await dayTypeRow(page, key, "3");
  await expect(ruleText(page)).toHaveText(said(key, 3));
  const ran = await run(page);
  await expect(page.locator(".itd-result .tx-answer-s")).toContainText("시뮬레이션 거래 2건");
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/validate") && r.method() === "POST");
  const got = page.waitForResponse((r) => r.url().includes("/intraday/validate") && r.request().method() === "POST", { timeout: 90_000 });
  await page.locator(".itd-judge-btn").click();
  expect((await sent).postDataJSON().rule).toEqual(ran.postDataJSON().rule);
  const js = await (await got).json();
  expect(js.context.map((f: { key: string }) => f.key)).toEqual([key]);
  expect(js.summary.trades).toBe(2);
  await expect(page.locator(".itd-verdict")).toBeVisible({ timeout: 60_000 });
});

test("매매일지의 '백테스트와 견주기' — 하루 유형 조건의 백테스트와 견주면 그 설정 그대로(모형 열쇠 포함) 다시 돌리고 같은 사실 줄을 보인다", async ({ page }) => {
  test.setTimeout(120_000);
  const { key } = await openEditor(page);
  await dayTypeRow(page, key, "3");
  await expect(ruleText(page)).toHaveText(said(key, 3));
  await run(page);
  await expect(page.locator(".itd-result .tx-answer-s")).toContainText("시뮬레이션 거래 2건");

  await page.goto("/my-account/journal", { waitUntil: "domcontentloaded" });
  const fills = ["체결일시,종목코드,매매구분,체결수량,체결단가",
    "2026-07-01 09:05:10,005380,매수,99,10020", "2026-07-01 09:07:30,005380,매도,99,10010"].join("\n") + "\n";
  await page.locator(".tj-file-input").setInputFiles({ name: "fills.csv", mimeType: "text/csv", buffer: Buffer.from(fills, "utf-8") });
  await expect(page.locator(".tj-run")).toBeEnabled();
  await page.locator(".tj-run").click();
  await expect(page.locator(".dv-compare")).toBeVisible();
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/divergence") && r.method() === "POST");
  await page.locator(".dv-run").click();
  expect((await sent).postDataJSON().rule).toEqual({ kind: "custom", params: { entry: { op: "gt", args: [{ ind: "day_type_is", model: key, type: 3 }, { const: 0.5 }] } } });
  await expect(page.locator(".dv-result")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(`.itd-ctx-item[data-key="${key}"] .itd-ctx-line`)).toHaveText(facts(key));
});

test("캔버스: 하루 유형 조건이 실린 문서 — 설정 판에 같은 모형 칸 · 계산의 보기와 판에 같은 사실 줄 · 설명의 사실에 그 문장", async ({ page }) => {
  test.setTimeout(150_000);
  const sink = trackErrors(page);
  const token = await login(page);
  const key = await trained(page, token);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  const params = { tickers: TRAIN.tickers, start_date: JUDGE.from, end_date: JUDGE.to, rule: "custom",
    custom_rule: { entry: { op: "gt", args: [{ ind: "day_type_is", model: key, type: 3 }, { const: 0.5 }] } },
    amount: 1_000_000, commission_bp: 1.5, slippage_ticks: 1, unknown_market: "KOSPI", unknown_instrument: "stock" };
  const doc = { format: "project-alpha.portfolio-graph", version: 1, meta: { name: "하루 유형 조건" }, edges: [],
    nodes: [{ id: "is", type: "intraday_setup", position: { x: 0, y: 0 }, params }] };
  await page.locator(".pg-import-input").setInputFiles({ name: "day-type.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
  await page.locator('.pg-node[data-node-id="is"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  const field = page.locator('.pg-side .pg-basic-field[data-field="custom_rule"]');
  await expect(field.getByLabel("하루 유형 모형", { exact: true })).toHaveValue(key);         // 화면과 같은 부품 — 문서의 모형이 그대로 실린다
  await expect(field.getByLabel("하루 유형 유형 번호", { exact: true })).toHaveValue("3");
  await expect(field.locator(".itd-rule-text")).toHaveText(said(key, 3));
  const over = await page.evaluate(() => {
    const side = document.querySelector(".pg-side")!; const right = side.getBoundingClientRect().right + 1;
    return [...side.querySelectorAll(".ire-model *")].filter((el) => el.getClientRects().length && el.getBoundingClientRect().right > right).map((el) => el.className);
  });
  expect(over, "설정 판 밖으로 넘친 모형 칸").toEqual([]);

  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const out = await (await resp).json();
  expect(out.nodes.is.status, out.nodes.is.reason).toBe("ok");
  expect(out.nodes.is.view.context.map((f: { key: string }) => f.key)).toEqual([key]);
  expect(out.nodes.is.explain.facts).toContain(facts(key)[0]);
  await page.locator('.pg-tab[data-tab="detail"]').click();
  await expect(page.locator(`.pg-side .pg-itd-setup .itd-ctx-item[data-key="${key}"] .itd-ctx-line`)).toHaveText(facts(key));
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

for (const theme of ["light", "dark"] as const) {
  test(`대비(${theme}) AA · 문체 · 390px — 모형 칸과 사실 줄이 넘치지 않는다`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    const { key } = await openEditor(page);
    await dayTypeRow(page, key, "3");
    await expect(ruleText(page)).toHaveText(said(key, 3));
    await run(page);
    await expect(page.locator(".itd-result .itd-ctx")).toBeVisible();
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
    for (const sel of [".ire-model", ".itd-result .itd-ctx"]) {
      const a = (await page.evaluate(contrastAudit(sel))) as AuditResult;
      expect(a.checked, sel).toBeGreaterThan(1);
      expect(a.low, `${theme} ${sel}`).toEqual([]);
      const v = (await page.evaluate(voiceAudit(sel))) as VoiceResult;
      expect(v.haeyo, sel).toEqual([]);
      expect(v.dash, sel).toEqual([]);
      expect(v.banned, sel).toEqual([]);
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".itd-result .itd-ctx")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    const clipped = await page.evaluate(() => {
      const out: string[] = [];
      for (const box of document.querySelectorAll<HTMLElement>(".ire-slot, .itd-ctx")) {
        const cs = getComputedStyle(box);
        const right = box.getBoundingClientRect().right - parseFloat(cs.paddingRight) + 1;
        for (const el of box.querySelectorAll<HTMLElement>(".ire-model, .ire-model *, .itd-ctx-line, .itd-ctx-title")) {
          if (el.getClientRects().length && el.getBoundingClientRect().right > right) out.push(`${el.tagName}.${el.className}`);
        }
      }
      return [...new Set(out)].slice(0, 12);
    });
    expect(clipped, `${theme} · 390px 에서 상자 밖으로 나간 것`).toEqual([]);
  });
}
