import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page, type Request } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════════════════════════
// 국면 조건(K3 · 2026-11-17 · 구현 계획 2026-11-16 §7.4) — 백테스트 › 분봉 규칙의 '직접 구성'
// 실행은 ★실제 서버★다 — 손으로 만든 열흘(035720 · 2026-03-02 ~ 03-13 · `seed_bars.py`)에 틀 '시가 범위 돌파 1분'을 편 조건
// (하루 +1,980원 비용 전 · 수수료 1.5bp · 코스피 주식 가정 → 열흘 비용 뒤 −3,194.73원 · `intraday.spec.ts` 의 손 계산)을 두고,
// 그 조건 ★전체★에 '코스피 국면 1 확률(국면 2개) > 0.5'를 '모두 충족'으로 잇는다.
// 국면은 E2E 서버(모의 게이트)의 합성 지수 걸음이다 — 그래서 n(국면 1 확률 > 0.5 인 날)은 ★같은 서버의 시장 국면 문★에 물어 정한다(같은 함수).
// 거는 것:
//  · 지수 · 국면 수 · 국면 번호는 비어서 시작하고 빈 칸을 말한다 · 시장 국면 확률은 진입 조건 자리의 목록에만 있다(짝: 청산 조건엔 없다)
//  · '국면 조건 추가'는 '하나 이상 충족' 뿌리를 '모두 충족'으로 묶는다(그 안에 넣지 않는다) · 규칙의 글 = 서버의 글
//  · 번호 > 국면 수 · '하나 이상 충족' 안의 국면 조건은 서버 문장 그대로 거절된다
//  · 실행의 사실 줄 '규칙이 쓴 시장 국면' = 서버 문장 · 하루 유형 묶음은 없다
//  · 판정의 짝 비교: ★뺀 판 = 손 계산의 열흘★ · ★넣은 판 = n × 하루 손 계산★ · 한계 문장 = 서버 · 뺀 판은 시행이 아니다
//  · 라이트/다크 AA · 문체 · 390px
// ════════════════════════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const HERE = "/backtest/intraday";
const HAND = { tickers: "035720", from: "2026-03-02", to: "2026-03-13" };
const HAND_DAYS = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06",
                   "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13"];
const GROSS_DAY = 1_980;                              // 하루 비용 전(손 계산)
const NET_DAY = -319.473;                             // 하루 비용 뒤 = 1,980 − 수수료 299.673 − 매도세 1,999.8(손 계산)
const MINUS = "−";
const n = (v: number) => v.toLocaleString("ko-KR");
/** 화면의 손익 서식(`krFormat.signedWon`)과 같은 규칙 — 원 단위 반올림 · 늘 부호(빼기는 U+2212) · 0 이면 부호 없음. */
const won = (v: number) => { const r = Math.round(Math.abs(v)); return `${r === 0 ? "" : v < 0 ? MINUS : "+"}${n(r)}원`; };
const STATE_OVER_K = "국면 번호가 국면 수보다 큽니다.";
const NOT_IN_AND = "시장 국면 조건은 진입 조건에 ‘모두 충족’으로만 잇습니다. ‘하나 이상 충족’ · ‘아님’ · ‘직전 봉 동안 계속’ 안에는 둘 수 없습니다.";

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

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);
const kind = (page: Page, name: string) => page.locator(".itd-kinds").getByRole("radio", { name });
const slot = (page: Page, key: "entry" | "entry_stop" | "exit") => page.locator(`.ire-slot[data-slot="${key}"]`);
const check = (page: Page, state: string) => page.locator(`.itd-check[data-state="${state}"]`);
const ruleText = (page: Page) => page.locator(".itd-check .itd-rule-text");
/** 진입 조건 뿌리 묶음의 줄 i(0 부터). */
const line = (page: Page, i: number) => slot(page, "entry").locator(".ire-group-list").first().locator(":scope > li").nth(i);

async function open(page: Page): Promise<string> {
  const token = await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  return token;
}

/** 손 계산의 자료와 비용 가정 — 035720 열흘 · 수수료 1.5bp · 코스피 주식으로 가정 · 이 실행에서만 쓰는 진입 금액(새 시행 · 99주 그대로). */
async function setHand(page: Page) {
  await page.locator(".itd-tickers").fill(HAND.tickers);
  await page.locator(".itd-from").fill(HAND.from);
  await page.locator(".itd-to").fill(HAND.to);
  await field(page, "commission_bp").fill("1.5");
  await field(page, "unknown_market").selectOption("KOSPI");
  await field(page, "unknown_instrument").selectOption("stock");
  await field(page, "amount").fill(String(1_000_000 + (Date.now() % 7_000) + 1));
}

/** 틀 '시가 범위 돌파 1분'을 편집기로 편다 → 뿌리가 '하나 이상 충족'인 진입 조건. */
async function expandOrb(page: Page) {
  await kind(page, "시가 범위 돌파").click();
  await field(page, "minutes").fill("1");
  const moved = page.waitForResponse((r) => r.url().includes("/intraday/rules/expand") && r.request().method() === "POST");
  await page.locator(".itd-expand").click();
  expect((await moved).ok()).toBe(true);
  await expect(page.locator(".ire")).toBeVisible();
  await expect(slot(page, "entry").locator(".ire-group-op").first()).toHaveValue("or");
}

/** 국면 조건 한 줄을 채운다 — 지수 · 국면 수 · 번호 · 연산 · 상수. */
async function fillRegime(row: ReturnType<Page["locator"]>, k: string, state: string, op = "gt", value = "0.5") {
  await row.getByLabel("시장 국면 확률 지수", { exact: true }).selectOption("KOSPI");
  await row.getByLabel("시장 국면 확률 국면 수", { exact: true }).fill(k);
  await row.getByLabel("시장 국면 확률 국면 번호", { exact: true }).fill(state);
  await row.getByLabel(/: 연산$/).first().selectOption(op);
  await row.getByLabel(/: 오른쪽 값 상수$/).first().fill(value);
}

/** 손 계산의 틀 조건 전체에 '코스피 국면 1 확률(국면 2개) > 0.5' 를 '모두 충족'으로 이은 규칙을 짓는다. */
async function buildRegimeRule(page: Page) {
  await setHand(page);
  await expandOrb(page);
  await slot(page, "entry").locator(".ire-regime-add").click();
  await expect(slot(page, "entry").locator(".ire-group-op").first()).toHaveValue("and");       // 새 '모두 충족'이 뿌리
  await expect(line(page, 0).locator(".ire-group-op").first()).toHaveValue("or");               // 틀의 '하나 이상 충족'은 그대로 첫 줄
  await fillRegime(line(page, 1), "2", "1");
  await expect(check(page, "ok")).toBeVisible();
}

async function run(page: Page): Promise<{ req: Request; body: Record<string, unknown> }> {
  const sent = page.waitForResponse((r) => r.url().includes("/intraday/simulate") && r.request().method() === "POST");
  await page.locator(".itd-run").click();
  const res = await sent;
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 30_000 });
  return { req: res.request(), body: (await res.json()) as Record<string, unknown> };
}

async function judge(page: Page): Promise<Record<string, unknown>> {
  const sent = page.waitForResponse((r) => r.url().includes("/intraday/validate") && r.request().method() === "POST");
  await page.locator(".itd-judge-btn").click();
  const res = await sent;
  expect(res.ok(), await res.text()).toBe(true);
  await expect(page.locator(".itd-verdict")).toBeVisible({ timeout: 60_000 });
  return (await res.json()) as Record<string, unknown>;
}

async function trialKeys(page: Page, token: string): Promise<string[]> {
  const r = await page.request.get(`${API}/intraday/trials?limit=200`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  return ((await r.json()).trials as { trial_key: string }[]).map((t) => t.trial_key);
}

/** 같은 서버의 시장 국면 문 — 손 계산 열흘 가운데 국면 1 확률(국면 2개)이 0.5 보다 큰 날 수. */
async function daysAbove(page: Page, token: string): Promise<number> {
  const q = new URLSearchParams({ index: "KOSPI", k: "2", from: HAND.from, to: HAND.to });
  const r = await page.request.get(`${API}/intraday/market-regime?${q}`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  const days = (await r.json()).days as { date: string; probs: number[] | null }[];
  return days.filter((d) => HAND_DAYS.includes(d.date) && d.probs !== null && d.probs[0] > 0.5).length;
}

// ── 편집기 ─────────────────────────────────────────────────────────────────────────────────────
test("편집기: 시장 국면 확률은 진입 조건 자리의 목록에만 있고(짝: 청산 조건엔 없다) 지수 · 국면 수 · 번호는 비어서 시작해 빈 칸을 말한다", async ({ page }) => {
  await open(page);
  await kind(page, "직접 구성").click();
  await expect(page.locator(".ire")).toBeVisible();
  await slot(page, "entry").locator('.ire-add[data-add="compare"]').click();
  await slot(page, "exit").locator('.ire-add[data-add="compare"]').click();
  const entryLeft = slot(page, "entry").getByLabel(/: 왼쪽 값$/).first();
  const exitLeft = slot(page, "exit").getByLabel(/: 왼쪽 값$/).first();
  await expect(entryLeft.locator('option[value="ind:regime_prob"]')).toHaveCount(1);
  await expect(exitLeft.locator('option[value="ind:regime_prob"]')).toHaveCount(0);
  await expect(exitLeft.locator('option[value="ind:close"]')).toHaveCount(1);                // 짝 — 다른 지표는 청산 조건에도
  await expect(slot(page, "exit").locator(".ire-regime-add")).toHaveCount(0);                // '국면 조건 추가'는 진입 조건에만
  await entryLeft.selectOption("ind:regime_prob");
  const entry = slot(page, "entry");
  await expect(entry.getByLabel("시장 국면 확률 지수", { exact: true })).toHaveValue("");
  await expect(entry.getByLabel("시장 국면 확률 지수", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await expect(entry.getByLabel("시장 국면 확률 국면 수", { exact: true })).toHaveValue("");
  await expect(entry.getByLabel("시장 국면 확률 국면 번호", { exact: true })).toHaveValue("");
  await expect(page.locator(".itd-problems li")).toContainText([
    "진입 조건: 시장 국면 확률 지수를 고르십시오.",
    "진입 조건: 시장 국면 확률 국면 수는 2~4개 범위로 입력하십시오.",
    "진입 조건: 시장 국면 확률 국면 번호는 1~4번 범위로 입력하십시오.",
  ]);
  await expect(page.locator(".itd-run")).toBeDisabled();
});

test("'국면 조건 추가'는 틀의 '하나 이상 충족' 뿌리를 그 안이 아니라 '모두 충족'으로 묶고, 규칙의 글은 서버의 글이다", async ({ page }) => {
  await open(page);
  const expanded: unknown[] = [];
  page.on("request", (r) => { if (r.url().includes("/intraday/rules/expand")) expanded.push(r.postDataJSON()); });
  await buildRegimeRule(page);
  const sent = expanded.at(-1) as { rule: { kind: string; params: { entry: { op: string; args: { op?: string; args?: unknown[] }[] } } } };
  expect(sent.rule.kind).toBe("custom");
  expect(sent.rule.params.entry.op).toBe("and");
  expect(sent.rule.params.entry.args.map((a) => a.op)).toEqual(["or", "gt"]);
  expect(sent.rule.params.entry.args[1]).toEqual({ op: "gt", args: [{ ind: "regime_prob", index: "KOSPI", k: 2, state: 1 }, { const: 0.5 }] });
  await expect(ruleText(page)).toHaveText(/^진입 조건: \(종가 상향 돌파 시가 범위 고가\(1분\) 또는 .+\) 그리고 코스피 국면 1 확률\(국면 2개\) > 0\.5$/);
  await expect(page.locator(".itd-notes")).toContainText("시장 국면 확률은 0 에서 1 사이의 값이며 그날 시가 전에 알던 값");   // 규칙의 주석 = 서버 문장
  const button = await slot(page, "entry").locator(".ire-regime-add").boundingBox();
  const area = await slot(page, "entry").boundingBox();
  expect(button && area && button.width < area.width / 3, "단추가 자리의 폭으로 늘었다(다른 '추가' 단추와 다른 꼴)").toBe(true);
});

test("서버의 거절은 서버 문장 그대로 — 번호 > 국면 수 · '하나 이상 충족' 안의 국면 조건 (짝: 고치면 지난다)", async ({ page }) => {
  await open(page);
  await setHand(page);
  await expandOrb(page);
  await slot(page, "entry").locator(".ire-regime-add").click();
  await fillRegime(line(page, 1), "2", "3");
  await expect(check(page, "refused")).toContainText(STATE_OVER_K);
  await line(page, 1).getByLabel("시장 국면 확률 국면 번호", { exact: true }).fill("2");
  await expect(check(page, "ok")).toBeVisible();
  await slot(page, "entry").locator(".ire-group-op").first().selectOption("or");             // 뿌리를 '하나 이상 충족'으로 — 국면 조건이 그 안에 든다
  await expect(check(page, "refused")).toContainText(NOT_IN_AND);
  await expect(page.locator(".itd-run")).toBeDisabled();
});

// ── 실행 · 판정 — 사실 줄 · 짝 비교(손 계산) ────────────────────────────────────────────────────────
test("실행의 사실 줄 = 서버 문장 · 판정의 짝 비교: 뺀 판 = 손 계산 열흘 · 넣은 판 = n × 하루 손 계산 · 뺀 판은 시행이 아니다", async ({ page }) => {
  const token = await open(page);
  const nAbove = await daysAbove(page, token);
  expect(nAbove, "국면이 열흘 모두 같으면 이 시험이 견주는 것이 없다").toBeGreaterThan(0);
  expect(nAbove).toBeLessThan(10);
  await buildRegimeRule(page);
  const before = await trialKeys(page, token);

  const { body: sim } = await run(page);
  const facts = (sim.context as { kind?: string; sentences: string[] }[]).filter((f) => f.kind === "regime");
  expect(facts).toHaveLength(1);
  await expect(page.locator(".itd-rctx-title")).toHaveText("규칙이 쓴 시장 국면");
  await expect(page.locator(".itd-rctx-line")).toHaveText(facts[0].sentences);
  await expect(page.locator(".itd-ctx")).toHaveCount(0);                                     // 하루 유형 묶음은 없다
  await expect(page.locator(".itd-rctx-line").nth(1)).toHaveText("분봉이 적재된 날 10일 가운데 국면 확률을 아는 날은 10일입니다.");

  const v = await judge(page);
  const pair = v.regime_pair as { known: boolean; note: string; rule_text: string;
    with: { trades: number; gross_total: number; net_total: number }; without: { trades: number; gross_total: number; net_total: number } };
  expect(pair.known).toBe(true);
  // 뺀 판 = 틀의 손 계산 그대로(열흘 · 거래 10 · 비용 전 +19,800 · 비용 뒤 −3,194.73)
  expect(pair.without.trades).toBe(10);
  expect(pair.without.gross_total).toBeCloseTo(19_800, 6);
  expect(pair.without.net_total).toBeCloseTo(-3_194.73, 2);
  // 넣은 판 = 국면 1 확률 > 0.5 인 날 n 개 × 하루 손 계산(같은 함수로 계산한 국면 · 하루 상태는 날마다 새로)
  expect(pair.with.trades).toBe(nAbove);
  expect(pair.with.gross_total).toBeCloseTo(GROSS_DAY * nAbove, 6);
  expect(pair.with.net_total).toBeCloseTo(NET_DAY * nAbove, 2);

  const table = page.locator(".itd-rpair-table");
  await expect(table.locator('tr[data-k="with"] td').nth(0)).toHaveText(`${n(nAbove)}건`);
  await expect(table.locator('tr[data-k="with"] td').nth(1)).toHaveText(won(GROSS_DAY * nAbove));
  await expect(table.locator('tr[data-k="with"] td').nth(2)).toHaveText(won(NET_DAY * nAbove));
  await expect(table.locator('tr[data-k="without"] td').nth(0)).toHaveText("10건");
  await expect(table.locator('tr[data-k="without"] td').nth(1)).toHaveText("+19,800원");
  await expect(table.locator('tr[data-k="without"] td').nth(2)).toHaveText(won(-3_194.73));
  await expect(page.locator(".itd-rpair-rule [data-server]")).toHaveText(pair.rule_text);
  expect(pair.rule_text).toMatch(/^진입 조건: 종가 상향 돌파 시가 범위 고가\(1분\) 또는 /);   // 뺀 판 = 틀이 만든 조건 그대로
  await expect(page.locator(".itd-rpair-note")).toHaveText(pair.note);
  await expect(page.locator(".itd-rpair-note")).toContainText("국면 조건이 성과를 낫게 한다는 증거가 아닙니다.");

  const after = await trialKeys(page, token);
  expect(after.filter((k) => !before.includes(k))).toHaveLength(1);                        // 실행과 판정이 같은 시행 하나 — 뺀 판은 시행이 아니다
});

test("봉과 체결: 국면 조건 시행의 하루 보기는 사실 줄 끝에 그날 국면 확률 한 줄을 서버 글 그대로 보이고 그 값은 시장 국면 문의 그날 값이다", async ({ page }) => {
  const token = await open(page);
  await buildRegimeRule(page);
  const viewed = page.waitForResponse((r) => /\/intraday\/trials\/[^/?]+\/day/.test(r.url()) && r.request().method() === "GET");
  await run(page);
  const res = await viewed;
  expect(res.ok(), await res.text()).toBe(true);
  const day = (await res.json()) as { facts: string[]; date: string; empty: unknown; fills: unknown[] };
  expect(day.empty).toBeNull();
  expect(day.fills.length, "기본 날은 시행 줄에서 거래가 있는 첫 날이다").toBeGreaterThan(0);
  const lines = day.facts.filter((f) => f.startsWith("그날 코스피 시장 국면(국면 2개)의 확률은 "));
  expect(lines).toHaveLength(1);
  expect(day.facts[day.facts.length - 1]).toBe(lines[0]);                                    // 늘 싣는 사실 줄 끝에 한 줄
  // 그날 확률 = 같은 서버의 시장 국면 문이 시행의 기간으로 낸 그날 값(화면은 두 자리)
  const q = new URLSearchParams({ index: "KOSPI", k: "2", from: HAND.from, to: HAND.to });
  const mr = await page.request.get(`${API}/intraday/market-regime?${q}`, { headers: { Authorization: `Bearer ${token}` } });
  expect(mr.ok(), await mr.text()).toBe(true);
  const probs = ((await mr.json()).days as { date: string; probs: number[] | null }[]).find((d) => d.date === day.date)?.probs;
  expect(probs, "들어간 날의 국면 확률은 안다").toBeTruthy();
  const shown = [...lines[0].matchAll(/국면 (\d) (\d\.\d\d)/g)].map((m) => [Number(m[1]), Number(m[2])] as const);
  expect(shown.map(([i]) => i)).toEqual([1, 2]);
  for (const [i, p] of shown) expect(Math.abs(p - (probs as number[])[i - 1])).toBeLessThanOrEqual(0.005 + 1e-9);
  expect((probs as number[])[0]).toBeGreaterThan(0.5);                                       // 그래서 그날 들어갔다(조건 '국면 1 > 0.5')
  await expect(page.locator(".itd-day-facts li")).toHaveText(day.facts);                    // 화면 = 서버 글 그대로(순서까지)
});

for (const theme of ["light", "dark"] as const) {
  test(`대비(${theme}) AA · 문체 · 390px 에서 국면 사실 줄과 짝 비교가 넘치지 않는다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    await buildRegimeRule(page);
    await run(page);
    await judge(page);
    for (const root of [".itd-rctx", ".itd-rpair", ".ire-slot[data-slot=\"entry\"]"]) {
      const a = (await page.evaluate(contrastAudit(root))) as AuditResult;
      expect(a.checked, root).toBeGreaterThan(3);
      expect(a.low, `${theme} ${root}`).toEqual([]);
      const v = (await page.evaluate(voiceAudit(root))) as VoiceResult;
      expect(v.haeyo, root).toEqual([]);
      expect(v.dash, root).toEqual([]);
      expect(v.banned, root).toEqual([]);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".itd-rpair")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    const box = page.locator(".itd-rpair .tj-scroll-x");
    await box.focus();
    await expect(box).toBeFocused();                                                           // 넘치는 표는 키보드로 닿는 상자 안에서만 넘는다
  });
}
