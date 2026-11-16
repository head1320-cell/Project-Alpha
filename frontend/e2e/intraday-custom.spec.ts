import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, type Page, type Request } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 분봉 규칙 '직접 구성' — 백테스트 › 분봉 규칙의 여덟째 선택지 (★실제 서버★ · 설계 `docs/superpowers/specs/2026-11-15-intraday-free-conditions-design.md` §6)
// ────────────────────────────────────────────────────────────────────────────
// 분봉은 `intraday.spec.ts` 와 같은 자료다(손으로 만든 열흘 035720 — 봉 넷: 09:00 종 10,000 / 09:01 종 10,060 / 09:02 시 10,070 / 09:03 종 10,110).
//   손으로 지은 조건 `종가 상향 돌파 10050`: 09:01 종가가 10,050 을 넘는다 → 09:02 시가 + 1틱 = 10,080 에 99주 → 마지막 봉 종가 − 1틱 = 10,100 에 청산.
//   하루 +1,980원 × 10일 = 비용 전 +19,800원 — 틀 '시가 범위 돌파 1분'의 손 계산과 같은 체결이다.
// 거는 것:
//  · 편집기의 자료는 조건 나무 그 자체 — 서버로 가는 본문 = 화면에서 지은 나무 · 규칙의 글은 ★서버가 낸 글★(조건 줄과 같은 순서)
//  · 빈 칸이 있으면 실행이 잠기고 어느 자리에 몇 곳인지 말한다 · 그 칸에 표시한다 · 그동안 서버에 묻지 않는다
//  · 틀에서 출발: 틀이 만드는 조건이 편집기에 실리고 같은 숫자가 나온다 · 틀과는 다른 시행으로 센다
//  · ★검사는 시행이 아니다★(편집 · 검사로는 시행 목록이 그대로) ↔ 실행은 시행을 남긴다
//  · 내 시행에서 불러오기: 규칙만 싣는다 · 서버의 거절은 서버 문장 그대로 · 실패는 재시도
//  · 격자는 포지션 축만 · 라이트/다크 AA · 문체 · 390px
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const HAND = { tickers: "035720", from: "2026-03-02", to: "2026-03-13" };
const HERE = "/backtest/intraday";
const CROSSING = { op: "cross_up", args: [{ ind: "close" }, { const: 10050 }] };
const CROSSING_TEXT = "진입 조건: 종가 상향 돌파 10050";

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

/** 화면을 열고 '직접 구성'을 고른다 → 로그인 토큰(문을 직접 물을 때 쓴다). */
async function openEditor(page: Page): Promise<string> {
  const token = await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await kind(page, "직접 구성").click();
  await expect(page.locator(".ire")).toBeVisible();
  return token;
}

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);
const kind = (page: Page, name: string) => page.locator(".itd-kinds").getByRole("radio", { name });
const slot = (page: Page, key: "entry" | "entry_stop" | "exit") => page.locator(`.ire-slot[data-slot="${key}"]`);
const check = (page: Page, state: string) => page.locator(`.itd-check[data-state="${state}"]`);
const text = (page: Page) => page.locator(".itd-check .itd-rule-text");
const sum = (page: Page, k: string, side: "gross" | "net") => page.locator(`.tj-sum tr[data-k="${k}"] .tj-sum-${side}`);

async function setData(page: Page, d: { tickers: string; from: string; to: string }) {
  await page.locator(".itd-tickers").fill(d.tickers);
  await page.locator(".itd-from").fill(d.from);
  await page.locator(".itd-to").fill(d.to);
}

/** 손 계산의 자료와 비용 가정 — 035720 열흘 · 수수료 1.5bp · 코스피 주식으로 가정. */
async function setHand(page: Page) {
  await setData(page, HAND);
  await field(page, "commission_bp").fill("1.5");
  await field(page, "unknown_market").selectOption("KOSPI");
  await field(page, "unknown_instrument").selectOption("stock");
}

/** 한 줄(비교 · 돌파)의 세 칸을 채운다. `right` 가 수면 상수, 글자면 지표 이름이다. */
async function fillRow(row: ReturnType<Page["locator"]>, left: string, op: string, right: string | number) {
  await row.getByLabel(/: 왼쪽 값$/).first().selectOption(`ind:${left}`);
  await row.getByLabel(/: 연산$/).first().selectOption(op);
  const value = row.getByLabel(/: 오른쪽 값$/).first();
  if (typeof right === "number") {
    await value.selectOption("const");
    await row.getByLabel(/: 오른쪽 값 상수$/).first().fill(String(right));
  } else {
    await value.selectOption(`ind:${right}`);
  }
}

/** 진입 조건에 `종가 상향 돌파 10050` 한 줄 — 손 계산의 그 규칙. */
async function crossing(page: Page) {
  const entry = slot(page, "entry");
  await entry.locator('.ire-add[data-add="compare"]').click();
  await fillRow(entry, "close", "cross_up", 10050);
  await expect(text(page)).toHaveText(CROSSING_TEXT);
}

async function run(page: Page): Promise<Request> {
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/simulate") && r.method() === "POST");
  await page.locator(".itd-run").click();
  const req = await sent;
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 30_000 });
  return req;
}

/** 내 시행의 열쇠들(마지막으로 돌린 것이 먼저) — 문에 직접 묻는다. */
async function trialKeys(page: Page, token: string): Promise<string[]> {
  const r = await page.request.get(`${API}/intraday/trials?limit=200`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  return ((await r.json()).trials as { trial_key: string }[]).map((t) => t.trial_key);
}

/** 이 실행에서만 쓰는 진입 금액 — 기록에 없는 설정이어야 '새 시행'이다. 10,080원에 99주가 되는 범위 안(손 계산이 그대로다). */
const freshAmount = () => String(1_000_000 + (Date.now() % 7_000) + 1);

test("직접 구성: 자리 셋은 비어서 시작한다 · 빈 칸이 있으면 실행이 잠기고 어느 자리에 몇 곳인지 말한다 · 그동안 서버에 묻지 않는다", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/intraday/rules/expand")) asked.push(r.postData() ?? ""); });
  await openEditor(page);
  await setData(page, HAND);
  await expect(page.locator(".ire-slot-title")).toHaveText(["진입 조건", "미리 건 매수 가격", "청산 조건"]);
  await expect(page.locator(".itd-rule-summary")).toHaveText("진입 조건, 미리 건 매수 가격, 청산 조건을 지표와 연산으로 직접 구성합니다.");
  await expect(page.locator(".itd-params")).toHaveCount(0);                          // 매개변수 칸이 없다 — 조건을 짓는다
  await expect(page.locator(".itd-expand")).toHaveCount(0);
  await expect(page.locator(".itd-notes li")).toHaveCount(2);
  await expect(page.locator(".itd-notes")).toContainText("조건을 변경해 실행할 때마다 시행으로 기록됩니다.");
  await expect(page.locator(".itd-notes")).toContainText("값이 없는 조건은 충족으로 보지 않습니다.");
  await expect(check(page, "idle")).toBeVisible();
  await expect(page.locator(".itd-run")).toBeDisabled();
  await expect(page.locator(".itd-problems li")).toHaveText(["진입 조건과 미리 건 매수 가격 가운데 하나는 있어야 합니다."]);
  await expect(slot(page, "entry_stop").locator(".ire-num-kind")).toHaveAttribute("aria-invalid", "false");   // 쓰지 않는 자리는 빈 칸이 아니다

  const entry = slot(page, "entry");
  await entry.locator('.ire-add[data-add="compare"]').click();
  await expect(page.locator(".itd-problems li")).toHaveText(["진입 조건: 비어 있는 칸이 3곳 있습니다."]);
  await expect(entry.locator('[aria-invalid="true"]')).toHaveCount(3);               // 왼쪽 값 · 연산 · 오른쪽 값 — 출발값을 지어 넣지 않는다
  await entry.getByLabel("진입 조건: 왼쪽 값", { exact: true }).selectOption("ind:close");
  await entry.getByLabel("진입 조건: 연산", { exact: true }).selectOption("cross_up");
  await entry.getByLabel("진입 조건: 오른쪽 값", { exact: true }).selectOption("const");
  await expect(page.locator(".itd-problems li")).toHaveText(["진입 조건: 비어 있는 칸이 1곳 있습니다."]);
  await expect(entry.getByLabel("진입 조건: 오른쪽 값 상수", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator(".itd-run")).toBeDisabled();
  expect(asked).toEqual([]);                                                          // 빈 칸이 있는 동안에는 묻지 않는다

  await entry.getByLabel("진입 조건: 오른쪽 값 상수", { exact: true }).fill("10050");
  await expect(text(page)).toHaveText(CROSSING_TEXT);                                // 서버가 낸 글
  await expect(page.locator(".itd-rule-size")).toHaveText("마디 3/64 · 겹침 깊이 2/12");
  await expect(page.locator(".itd-needs-prev")).toHaveCount(0);                       // 전일 값을 쓰지 않는 조건에는 그 안내가 없다
  await expect(page.locator(".itd-problems")).toHaveCount(0);
  await expect(page.locator(".itd-run")).toBeEnabled();
  expect(asked.length).toBeGreaterThan(0);
  expect(JSON.parse(asked[asked.length - 1])).toEqual({ rule: { kind: "custom", params: { entry: CROSSING } } });

  // 틀로 갔다 돌아와도 지은 조건을 잃지 않는다.
  await kind(page, "RSI").click();
  await expect(page.locator(".ire")).toHaveCount(0);
  await expect(field(page, "n")).toHaveValue("14");
  await kind(page, "직접 구성").click();
  await expect(text(page)).toHaveText(CROSSING_TEXT);
});

test("손으로 지은 조건: 화면의 값이 손 계산과 같다 · 서버로 가는 본문이 화면에서 지은 나무와 같다 · 격자는 포지션 축만", async ({ page }) => {
  await openEditor(page);
  await setHand(page);
  await crossing(page);
  const req = await run(page);
  expect(req.postDataJSON().rule).toEqual({ kind: "custom", params: { entry: CROSSING } });
  await expect(page.locator(".itd-result .tx-answer-s")).toContainText("시뮬레이션 거래 10건");
  await expect(sum(page, "total", "gross")).toHaveText("+19,800원");              // 열흘 × +1,980원 — 틀의 손 계산과 같은 체결

  // 격자: 직접 구성에는 이름 붙은 규칙 매개변수가 없다 — 포지션 축 셋만 있다.
  await page.locator(".itd-grid-on input").check();
  await expect(page.locator('.itd-grid [data-grid^="rule."]')).toHaveCount(0);
  await expect(page.locator('.itd-grid [data-grid^="position."]')).toHaveCount(3);
  await expect(page.locator(".itd-grid-custom")).toHaveText("직접 구성한 규칙은 포지션 설정의 격자만 사용할 수 있습니다.");
  await page.locator(".itd-grid-on input").uncheck();
  const judged = page.waitForRequest((r) => r.url().includes("/intraday/validate") && r.method() === "POST");
  await page.locator(".itd-judge-btn").click();
  expect((await judged).postDataJSON().rule).toEqual({ kind: "custom", params: { entry: CROSSING } });
  await expect(page.locator(".itd-verdict")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".itd-verdict")).toContainText("관문 일곱 가운데");
});

test("틀에서 출발: 틀이 만드는 조건이 편집기에 실리고 같은 숫자가 나온다 · 틀과는 다른 시행으로 센다", async ({ page }) => {
  const token = await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await setHand(page);
  await field(page, "minutes").fill("1");
  await field(page, "amount").fill(freshAmount());
  await run(page);
  const byTemplate = await sum(page, "total", "gross").innerText();
  expect(byTemplate).toBe("+19,800원");
  const before = await trialKeys(page, token);

  const moved = page.waitForRequest((r) => r.url().includes("/intraday/rules/expand") && r.method() === "POST");
  await page.locator(".itd-expand").click();
  expect((await moved).postDataJSON()).toEqual({ rule: { kind: "opening_range_breakout", params: { minutes: 1 } } });
  await expect(page.locator(".ire")).toBeVisible();
  await expect(kind(page, "직접 구성")).toHaveAttribute("aria-checked", "true");
  await expect(page.locator(".itd-result")).toHaveCount(0);                          // 규칙이 바뀌었다 — 앞의 결과를 지운다
  await expect(text(page)).toContainText("진입 조건: 종가 상향 돌파 시가 범위 고가(1분) 또는 ");
  const entry = slot(page, "entry");
  await expect(entry.locator(".ire-group-op").first()).toHaveValue("or");            // 틀이 만든 나무 그대로다
  const first = entry.locator(".ire-group-list").first().locator(":scope > li").first();
  await expect(first.getByLabel(/: 왼쪽 값$/)).toHaveValue("ind:close");
  await expect(first.getByLabel(/: 연산$/)).toHaveValue("cross_up");
  await expect(first.getByLabel(/: 오른쪽 값$/)).toHaveValue("ind:or_high");
  await expect(first.getByLabel("시가 범위 고가 범위를 재는 시간")).toHaveValue("1");
  expect(await trialKeys(page, token)).toEqual(before);                               // 풀기만으로는 시행이 늘지 않는다

  const req = await run(page);
  expect(req.postDataJSON().rule.kind).toBe("custom");
  expect(await sum(page, "total", "gross").innerText()).toBe(byTemplate);            // 같은 조건 · 같은 체결
  const after = await trialKeys(page, token);
  expect(before).not.toContain(after[0]);                                             // 종류가 달라 새 시행이다
  await expect(page.locator(".itd-result .itd-trial")).not.toContainText("새 시행이 아님");
});

test("틀을 조건으로 풀지 못하면 서버의 사유를 보이고 틀에 머문다 · 설정을 고치면 그 알림이 사라진다", async ({ page }) => {
  await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await expect(page.locator(".itd-move-fail")).toHaveCount(0);
  await page.route("**/intraday/rules/expand", (r) => r.fulfill({
    status: 400, contentType: "application/json",
    body: JSON.stringify({ detail: { code: "bad_param", reason: "매개변수 값이 범위를 벗어났습니다.", detail: "minutes" } }) }));
  await page.locator(".itd-expand").click();
  await expect(page.locator(".itd-move-fail [data-server]")).toHaveText("매개변수 값이 범위를 벗어났습니다.");
  await expect(kind(page, "시가 범위 돌파")).toHaveAttribute("aria-checked", "true");      // 틀에 머문다 — 빈 편집기로 넘어가지 않는다
  await expect(page.locator(".ire")).toHaveCount(0);
  await expect(page.locator(".itd-expand")).toBeEnabled();                             // 다시 누를 수 있다
  await field(page, "minutes").fill("15");                                            // 설정을 고치면 낡은 알림이 사라진다
  await expect(page.locator(".itd-move-fail")).toHaveCount(0);
});

test("★검사는 시행이 아니다★ — 조건을 짓고 고치는 동안 시행 목록이 그대로다 ↔ 실행하면 한 줄 는다", async ({ page }) => {
  let asked = 0;
  page.on("request", (r) => { if (r.url().includes("/intraday/rules/expand")) asked += 1; });
  const token = await openEditor(page);
  await setHand(page);
  await field(page, "amount").fill(freshAmount());
  const before = await trialKeys(page, token);
  await crossing(page);
  const constant = slot(page, "entry").getByLabel("진입 조건: 오른쪽 값 상수", { exact: true });
  for (const value of ["10040", "10045", "10050"]) {
    await constant.fill(value);
    await expect(text(page)).toHaveText(`진입 조건: 종가 상향 돌파 ${value}`);
  }
  expect(asked).toBeGreaterThanOrEqual(3);                                            // 공허하지 않다 — 실제로 여러 번 검사했다
  expect(await trialKeys(page, token)).toEqual(before);
  await run(page);
  const after = await trialKeys(page, token);
  expect(before).not.toContain(after[0]);
  expect(after.slice(1, before.length + 1)).toEqual(before.slice(0, Math.min(before.length, after.length - 1)));
});

test("묶음 · 아님 · 직전 M봉 동안 · 시각 창 · 가격 식: 서버의 글이 조건 줄의 순서 그대로다 · 줄을 지우면 그 줄만 빠진다", async ({ page }) => {
  await openEditor(page);
  await setData(page, HAND);
  await crossing(page);
  const entry = slot(page, "entry");
  await entry.locator(':scope > .ire-add-row .ire-add[data-add="compare"]').click();  // 둘째 조건 — 뿌리가 '모두 충족' 묶음이 된다
  await expect(entry.locator(".ire-group-op").first()).toHaveValue("and");
  await expect(entry.locator(".ire-group-op").first().locator("option:checked")).toHaveText("모두 충족");   // 이름표는 서버의 것
  await expect(page.locator(".itd-notes")).not.toContainText("그 봉을 포함하지 않습니다");                    // '직전 M봉 동안'을 쓰기 전에는 그 말이 없다(짝)
  const rows = entry.locator(".ire-group-list").first().locator(":scope > li");
  await fillRow(rows.nth(1), "close", "lt", "vwap");
  await rows.nth(1).locator('.ire-tool[data-act="held"]').click();
  await expect(page.locator(".itd-problems li")).toHaveText(["진입 조건: 직전 봉 수는 1~240봉 범위로 입력하십시오."]);   // 봉 수는 비어서 시작한다
  await rows.nth(1).getByLabel(/: 직전 봉 수$/).fill("2");
  await rows.nth(1).locator('.ire-tool[data-act="not"]').click();
  await entry.locator(".ire-group").first().locator(':scope > .ire-add-row .ire-add[data-add="time"]').click();
  await expect(page.locator(".itd-problems li")).toHaveText(["진입 조건: 시각 창의 시작과 종료를 확인하십시오."]);
  await rows.nth(2).getByLabel(/: 시작 시각$/).fill("09:00");
  await rows.nth(2).getByLabel(/: 종료 시각$/).fill("15:00");
  await expect(text(page)).toHaveText("진입 조건: 종가 상향 돌파 10050 그리고 아님(직전 2봉 동안(종가 < VWAP)) 그리고 시각 09:00~15:00");
  // '직전 M봉 동안'은 그 봉 자신을 보지 않는다 — 쓰는 규칙에는 서버가 그렇게 말한다.
  await expect(page.locator(".itd-notes")).toContainText("‘직전 M봉 동안 계속’은 그 봉을 포함하지 않습니다. 앞선 M개 봉에서 모두 충족했는지 봅니다.");

  await entry.locator(".ire-group-op").first().selectOption("or");
  await expect(entry.locator(".ire-group-op").first().locator("option:checked")).toHaveText("하나 이상 충족");
  await expect(text(page)).toHaveText("진입 조건: 종가 상향 돌파 10050 또는 아님(직전 2봉 동안(종가 < VWAP)) 또는 시각 09:00~15:00");

  // 가운데 줄을 지운다 — 그 줄만 빠지고, 남은 줄의 칸은 제 값을 그대로 보인다.
  await rows.nth(1).locator(':scope > .ire-cond > .ire-line .ire-tool[data-act="remove"]').click();
  await expect(rows).toHaveCount(2);
  await expect(text(page)).toHaveText("진입 조건: 종가 상향 돌파 10050 또는 시각 09:00~15:00");
  await expect(rows.nth(0).getByLabel(/: 오른쪽 값 상수$/)).toHaveValue("10050");
  await expect(rows.nth(1).getByLabel(/: 시작 시각$/)).toHaveValue("09:00");

  // 청산 조건과 미리 건 매수 가격 — 자리 이름과 함께 한 줄로 이어진다(자리의 순서대로).
  const exit = slot(page, "exit");
  await exit.locator('.ire-add[data-add="compare"]').click();
  await fillRow(exit, "close", "lt", "vwap");
  const price = slot(page, "entry_stop");
  await price.getByLabel("미리 건 매수 가격", { exact: true }).selectOption("ind:day_open");
  await price.getByLabel("미리 건 매수 가격", { exact: true }).selectOption("add");   // 앞의 값이 왼쪽 항이 된다
  await expect(page.locator(".itd-problems li")).toHaveText(["미리 건 매수 가격: 비어 있는 칸이 1곳 있습니다."]);
  await price.getByLabel("미리 건 매수 가격 계산의 오른쪽 값", { exact: true }).selectOption("const");
  await price.getByLabel("미리 건 매수 가격 계산의 오른쪽 값 상수", { exact: true }).fill("50");
  await expect(text(page)).toHaveText(
    "진입 조건: 종가 상향 돌파 10050 또는 시각 09:00~15:00 · 미리 건 매수 가격: 당일 시가 + 50 · 청산 조건: 종가 < VWAP");
  await expect(page.locator(".itd-rule-size")).toHaveText("마디 11/64 · 겹침 깊이 3/12");
  await price.locator('.ire-tool[data-act="remove"]').click();
  await expect(text(page)).toHaveText("진입 조건: 종가 상향 돌파 10050 또는 시각 09:00~15:00 · 청산 조건: 종가 < VWAP");

  // 감싼 것을 풀면 안의 조건이 남는다.
  await exit.locator('.ire-tool[data-act="not"]').click();
  await expect(text(page)).toContainText("청산 조건: 아님(종가 < VWAP)");
  await exit.getByRole("button", { name: "청산 조건: 아님 해제" }).click();
  await expect(text(page)).toContainText("청산 조건: 종가 < VWAP");
});

test("줄을 지워 자리가 당겨져도 칸에는 그 줄의 값이 보인다(앞 줄에 치던 글자가 남지 않는다) · 조건이 하나만 남으면 묶음이 풀린다", async ({ page }) => {
  await openEditor(page);
  await setData(page, HAND);
  await crossing(page);
  const entry = slot(page, "entry");
  await entry.locator(':scope > .ire-add-row .ire-add[data-add="compare"]').click();
  const group = entry.locator(".ire-group").first();
  const rows = entry.locator(".ire-group-list").first().locator(":scope > li");
  await fillRow(rows.nth(1), "volume", "gt", 20000);
  await group.locator(':scope > .ire-add-row .ire-add[data-add="compare"]').click();
  await fillRow(rows.nth(2), "close", "lt", 30000);
  await expect(text(page)).toHaveText("진입 조건: 종가 상향 돌파 10050 그리고 거래량 > 20000 그리고 종가 < 30000");
  await rows.nth(0).getByLabel(/: 오른쪽 값 상수$/).fill("10055");                    // 첫 줄의 칸에 치던 글자
  await rows.nth(0).locator('.ire-tool[data-act="remove"]').click();                  // 첫 줄을 지운다 — 뒤의 두 줄이 한 칸씩 당겨진다
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).getByLabel(/: 왼쪽 값$/)).toHaveValue("ind:volume");
  await expect(rows.nth(0).getByLabel(/: 오른쪽 값 상수$/)).toHaveValue("20000");      // 10055 가 아니다
  await expect(rows.nth(1).getByLabel(/: 오른쪽 값 상수$/)).toHaveValue("30000");
  await expect(text(page)).toHaveText("진입 조건: 거래량 > 20000 그리고 종가 < 30000");

  await rows.nth(0).locator('.ire-tool[data-act="remove"]').click();                  // 하나만 남는다 — 묶음이 그 조건이 된다
  await expect(entry.locator(".ire-group")).toHaveCount(0);
  await expect(entry.getByLabel("진입 조건: 왼쪽 값", { exact: true })).toHaveValue("ind:close");
  await expect(entry.getByLabel("진입 조건: 오른쪽 값 상수", { exact: true })).toHaveValue("30000");
  await expect(text(page)).toHaveText("진입 조건: 종가 < 30000");
  await expect(page.locator(".itd-problems")).toHaveCount(0);                         // 잠기지 않는다
  await expect(page.locator(".itd-run")).toBeEnabled();
});

test("전일 값을 쓰는 조건이면 그렇게 말한다 · 범위 밖 매개변수는 그 칸과 문제 목록이 말한다 · 서버의 거절은 서버 문장 그대로 · 실패는 재시도", async ({ page }) => {
  await openEditor(page);
  await setData(page, HAND);
  const entry = slot(page, "entry");
  await entry.locator('.ire-add[data-add="compare"]').click();
  await expect(page.locator(".itd-needs-prev")).toHaveCount(0);
  await fillRow(entry, "close", "gt", "prev_high");
  await expect(text(page)).toHaveText("진입 조건: 종가 > 전일 고가");
  await expect(page.locator(".itd-needs-prev")).toContainText("전일 값은 앞선 적재일의 분봉에서 얻습니다.");
  await expect(page.locator(".itd-notes")).toContainText("전일 값은 원주가입니다.");   // 서버 주석

  await entry.getByLabel("진입 조건: 오른쪽 값", { exact: true }).selectOption("ind:sma");
  const period = entry.getByLabel("이동평균 기간", { exact: true });
  await expect(period).toHaveValue("20");                                             // 서버가 준 출발값
  await expect(text(page)).toHaveText("진입 조건: 종가 > 이동평균(20봉)");
  await expect(page.locator(".itd-needs-prev")).toHaveCount(0);                       // 짝 — 전일 지표를 빼면 사라진다(검사가 끝난 뒤에 본다)
  await expect(page.locator(".itd-notes")).not.toContainText("전일 값은 원주가입니다.");
  await period.fill("500");
  await expect(period).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator(".itd-problems li")).toHaveText(["진입 조건: 이동평균 기간은 1~240봉 범위로 입력하십시오."]);
  await expect(page.locator(".itd-run")).toBeDisabled();
  await expect(check(page, "idle")).toBeVisible();                                    // 어긋난 조건은 서버에 묻지 않는다

  // 서버가 거절하면 서버의 문장을 그대로 보이고 실행을 잠근다.
  await page.route("**/intraday/rules/expand", (r) => r.fulfill({
    status: 400, contentType: "application/json",
    body: JSON.stringify({ detail: { code: "too_deep", reason: "조건의 겹침 깊이가 상한을 넘었습니다.", detail: "12", slot: "entry" } }) }));
  await period.fill("21");
  await expect(check(page, "refused").locator("[data-server]")).toHaveText("조건의 겹침 깊이가 상한을 넘었습니다.");
  await expect(page.locator(".itd-run")).toBeDisabled();
  await expect(page.locator(".itd-problems li")).toHaveText(["조건 검사에서 거절됐습니다. 규칙 절의 사유를 확인하십시오."]);
  await page.unroute("**/intraday/rules/expand");

  // 요청의 모양이 틀렸다는 답(422)도 거절이다 — 다시 물어도 같은 답이라 재시도 단추를 내놓지 않는다.
  await page.route("**/intraday/rules/expand", (r) => r.fulfill({
    status: 422, contentType: "application/json",
    body: JSON.stringify({ detail: [{ loc: ["body", "rule", "params"], msg: "Input should be a valid dictionary", type: "dict_type" }] }) }));
  await period.fill("24");
  await expect(check(page, "refused").locator("[data-server]")).toHaveText("body.rule.params: Input should be a valid dictionary");
  await expect(check(page, "refused").getByRole("button")).toHaveCount(0);
  await expect(check(page, "fail")).toHaveCount(0);
  await expect(page.locator(".itd-run")).toBeDisabled();
  await page.unroute("**/intraday/rules/expand");

  // 서버가 답하지 못하면 재시도할 수 있다(거절과 가른다).
  let fail = true;
  await page.route("**/intraday/rules/expand", (r) => (fail
    ? r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "조건 검사 중 오류가 발생했습니다." }) })
    : r.continue()));
  await period.fill("22");
  await expect(check(page, "fail").locator("[data-server]")).toHaveText("조건 검사 중 오류가 발생했습니다.");
  await expect(page.locator(".itd-run")).toBeEnabled();                               // 실패는 거절이 아니다 — 실행은 서버가 다시 검사한다
  fail = false;
  await check(page, "fail").getByRole("button").click();
  await expect(text(page)).toHaveText("진입 조건: 종가 > 이동평균(22봉)");
});

test("내 시행에서 불러오기: 규칙만 실린다 — 종목과 기간은 건드리지 않는다", async ({ page }) => {
  await openEditor(page);
  await setHand(page);
  await crossing(page);
  await run(page);                                                                    // 방금 돌린 직접 구성이 목록의 맨 위다

  const listed: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/intraday/trials")) listed.push(r.url()); });
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await kind(page, "직접 구성").click();
  await expect(check(page, "idle")).toBeVisible();
  await expect(page.locator(".itd-load-list")).toHaveCount(0);
  expect(listed).toEqual([]);                                                         // 누르기 전에는 묻지 않는다
  await page.locator(".itd-load-btn").click();
  const row = page.locator(".itd-load-row").first();
  await expect(row.locator("b")).toHaveText("직접 구성");
  await expect(row.locator(".itd-load-text")).toHaveText(CROSSING_TEXT);
  await expect(row).toContainText("035720 · 2026-03-02 ~ 2026-03-13");
  expect(listed.length).toBe(1);
  const moved = page.waitForRequest((r) => r.url().includes("/intraday/rules/expand") && r.method() === "POST");
  await row.click();
  expect((await moved).postDataJSON()).toEqual({ rule: { kind: "custom", params: { entry: CROSSING } } });   // 그 시행의 규칙을 서버의 풀이에 보낸다
  await expect(page.locator(".itd-load-list")).toHaveCount(0);
  await expect(text(page)).toHaveText(CROSSING_TEXT);
  await expect(slot(page, "entry").getByLabel("진입 조건: 오른쪽 값 상수", { exact: true })).toHaveValue("10050");
  await expect(page.locator(".itd-tickers")).toHaveValue("");                         // 종목은 그대로 — 규칙만 불러온다
  await expect(page.locator(".itd-problems li")).toHaveText(["종목코드를 하나 이상 입력하십시오."]);
});

test("직접 구성으로 돌린 시행은 매매일지의 견주기에서도 조건의 글로 구별된다 ↔ 다른 백테스트를 고르면 그 규칙의 글로 바뀐다", async ({ page }) => {
  await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await setHand(page);
  await field(page, "minutes").fill("1");
  await run(page);                                                                    // 틀로 한 번
  await kind(page, "직접 구성").click();
  await crossing(page);
  await run(page);                                                                    // 직접 구성으로 한 번 — 이것이 목록의 맨 위다

  await page.goto("/my-account/journal", { waitUntil: "domcontentloaded" });
  await page.locator(".tj-file-input").setInputFiles({ name: "fills.csv", mimeType: "text/csv", buffer: Buffer.from(
    ["체결일시,종목코드,매매구분,체결수량,체결단가", "2026-03-02 09:02:40,035720,매수,99,10090", "2026-03-02 09:03:20,035720,매도,99,10090"].join("\n") + "\n", "utf-8") });
  await expect(page.locator(".tj-run")).toBeEnabled();
  await page.locator(".tj-run").click();
  await expect(page.locator(".dv-compare")).toBeVisible();
  const picked = () => page.locator(".dv-trial").evaluate((el) => (el as HTMLSelectElement).selectedOptions[0]?.textContent ?? "");
  expect(await picked()).toMatch(/^직접 구성 · 035720 · 2026-03-02 ~ 2026-03-13 · /);
  await expect(page.locator(".dv-rule-text")).toHaveText(CROSSING_TEXT);             // 이름표가 같은 시행을 가르는 것은 조건의 글이다
  await expect(page.locator(".dv-rule")).toHaveAttribute("data-known", "true");

  const other = await page.locator(".dv-trial option").filter({ hasText: /^시가 범위 돌파 · 035720 · 2026-03-02 ~ 2026-03-13 · / }).first().getAttribute("value");
  expect(other).toBeTruthy();
  await page.locator(".dv-trial").selectOption(other!);
  await expect(page.locator(".dv-rule-text")).toContainText("진입 조건: 종가 상향 돌파 시가 범위 고가(");
  await expect(page.locator(".dv-rule-text")).not.toHaveText(CROSSING_TEXT);
});

for (const theme of ["light", "dark"] as const) {
  test(`편집기 — 대비(${theme}) AA · 문체 · 좁은 화면에서 넘치지 않는다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await openEditor(page);
    await setData(page, HAND);
    await crossing(page);
    const entry = slot(page, "entry");
    await entry.locator(':scope > .ire-add-row .ire-add[data-add="compare"]').click();
    const rows = entry.locator(".ire-group-list").first().locator(":scope > li");
    await fillRow(rows.nth(1), "close", "lt", "bb_lower");
    await rows.nth(1).locator('.ire-tool[data-act="held"]').click();
    await rows.nth(1).getByLabel(/: 직전 봉 수$/).fill("3");
    await rows.nth(1).locator('.ire-tool[data-act="not"]').click();
    await entry.locator(".ire-group").first().locator(':scope > .ire-add-row .ire-add[data-add="time"]').click();
    await rows.nth(2).getByLabel(/: 시작 시각$/).fill("09:30");
    await rows.nth(2).getByLabel(/: 종료 시각$/).fill("14:50");
    const price = slot(page, "entry_stop");
    await price.getByLabel("미리 건 매수 가격", { exact: true }).selectOption("ind:day_open");
    await price.getByLabel("미리 건 매수 가격", { exact: true }).selectOption("mul");
    await price.getByLabel("미리 건 매수 가격 계산의 오른쪽 값", { exact: true }).selectOption("const");
    await price.getByLabel("미리 건 매수 가격 계산의 오른쪽 값 상수", { exact: true }).fill("1.01");
    await expect(text(page)).toContainText("미리 건 매수 가격: 당일 시가 × 1.01");
    await slot(page, "exit").locator('.ire-add[data-add="compare"]').click();         // 빈 칸이 있는 줄 — 표시된 칸의 대비도 본다
    await expect(page.locator(".itd-problems li")).toHaveText(["청산 조건: 비어 있는 칸이 3곳 있습니다."]);
    await page.locator(".itd-load-btn").click();
    await expect(page.locator(".itd-load-row").first()).toBeVisible();

    const a = (await page.evaluate(contrastAudit(".itd-rule"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(40);
    expect(a.low, theme).toEqual([]);
    const v = (await page.evaluate(voiceAudit(".itd-rule"))) as VoiceResult;
    expect(v.checked).toBeGreaterThan(20);
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    expect(v.titles).toBe(0);

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".ire")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    const clipped = await page.evaluate(() => {
      const sec = document.querySelector(".itd-rule")?.closest(".tx-sec") as HTMLElement;
      const right = sec.getBoundingClientRect().right - parseFloat(getComputedStyle(sec).paddingRight) + 1;
      const out: string[] = [];
      for (const el of sec.querySelectorAll<HTMLElement>("select, input, button, span, p, li, h3, ul, div")) {
        if (!el.getClientRects().length || el.closest(".tx-seg, .tx-sr, .itd-load-list")) continue;
        if (el.getBoundingClientRect().right > right) out.push(`${el.tagName}.${el.className} :: ${(el.textContent ?? "").trim().slice(0, 24)}`);
      }
      return [...new Set(out)].slice(0, 12);
    });
    expect(clipped, `${theme} · 390px 에서 절 밖으로 나간 것`).toEqual([]);
  });
}
