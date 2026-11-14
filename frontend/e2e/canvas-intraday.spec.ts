import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, type Page, type Request } from "./fixtures";
import { contrastAudit, trackErrors, uniq, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ═════════════════════════════════════════════════════════════════════════════
// 캔버스의 분봉 백테스트 노드 둘 — 설정 → 결과 조회 (★실제 서버★ · 설계 `docs/superpowers/specs/2026-11-14-canvas-intraday-nodes-design.md`)
// ─────────────────────────────────────────────────────────────────────────────
// 분봉은 `intraday.spec.ts` 와 같은 손 계산 열흘(035720 · 2026-03-02 ~ 03-13 · 출처 열 `kis`)이다 — 계산 과정은 그 스펙의 머리에 있다.
//   규칙 '시가 범위 돌파 · 1분' · 진입 금액 100만원 · 수수료 1.5bp · 슬리피지 1틱 · 시장 가정 코스피·주식
//   → 비용 전 +19,800원 · 비용 후 −3,195원 · 손익분기 9.9bp · 관문 통과 2 · 미달 1 · 미상 4.
// 거는 것:
//  · 로그인 전: 분봉 노드만 사유와 함께 실패하고 다른 노드는 계산된다(문은 열려 있다)
//  · ★계산은 실행하지 않는다★ — 계산 동안 분봉 문으로 가는 요청 0 · 단추 '분봉 백테스트 실행' 한 번이 실행한다
//  · 실행 뒤 '결과 조회 노드 추가' → 결과 판의 값 = 손 계산 = 화면(백테스트 › 분봉 규칙)과 같은 판정 부품
//  · 설정 판은 고른 규칙 틀의 칸만 보인다 · 고르기 목록에 내 결과가 뜬다
//  · 오류 0 · 라이트/다크 AA · 문체
// ═════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const MINUS = "−";
const HAND = { tickers: ["035720"], start_date: "2026-03-02", end_date: "2026-03-13", rule: "opening_range_breakout",
  opening_range_breakout__minutes: 1, amount: 1_000_000, commission_bp: 1.5, slippage_ticks: 1,
  unknown_market: "KOSPI", unknown_instrument: "stock" };

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();
const gate = (page: Page, key: string) => page.locator(`.pg-itd-load .itd-gate[data-gate="${key}"]`);

async function login(page: Page): Promise<void> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
}

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

async function importDoc(page: Page, nodes: object[]) {
  const doc = { format: "project-alpha.portfolio-graph", version: 1, meta: { name: "분봉 노드" }, edges: [], nodes };
  await page.locator(".pg-import-input").setInputFiles({ name: "intraday.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
}

/** 계산 단추 → `/graph/run` 의 답. 실패한 노드가 있어도 기다린다(요약 문구에 기대지 않는다). */
async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 120_000 });
  await page.locator(".pg-run").click();
  return (await resp).json();
}

const setup = (params: object = HAND) => ({ id: "is", type: "intraday_setup", position: { x: 0, y: 0 }, params });

test("로그인 전: 분봉 노드는 사유와 함께 실패하고 다른 노드는 계산된다", async ({ page }) => {
  await openCanvas(page);
  await importDoc(page, [{ id: "u", type: "universe", position: { x: 0, y: 0 }, params: { tickers: ["005930"] } }, { ...setup(), position: { x: 0, y: 260 } }]);
  const body = await run(page);
  expect(body.nodes.u.status).toBe("ok");
  expect(body.nodes.is.status).toBe("failed");
  expect(body.nodes.is.reason).toContain("로그인하지 않았습니다");
  await expect(node(page, "is").locator(".pg-node-status-k")).not.toHaveText("완료");
  await node(page, "is").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-side")).toContainText("분봉 백테스트는 로그인한 사용자만 사용합니다");
  await expect(page.locator(".pg-side .pg-itd")).toHaveCount(0);                  // 결과를 지어내지 않는다
});

test("설정 → 실행 → 결과 조회: 계산은 실행하지 않고 · 단추 한 번이 실행하며 · 결과 판의 값 = 손 계산", async ({ page }) => {
  test.setTimeout(180_000);
  const sink = trackErrors(page);
  await login(page);
  await openCanvas(page);
  await importDoc(page, [setup()]);

  // ① 계산 — 분봉 문으로 가는 요청이 없다(실행하지 않는다 · 시행을 세지 않는다)
  const intraday: string[] = [];
  const watch = (r: Request) => { if (r.url().includes("/api/v1/intraday/")) intraday.push(`${r.method()} ${new URL(r.url()).pathname}`); };
  page.on("request", watch);
  const first = await run(page);
  expect(first.nodes.is.status, first.nodes.is.reason).toBe("ok");
  expect(intraday, "계산은 분봉 백테스트를 실행하지 않는다").toEqual([]);
  expect(first.nodes.is.view.work).toEqual({ ticker_days: 10, simulations: 3, total: 30, limit: 6000 });

  await node(page, "is").click();
  await tab(page, "detail");
  const kv = page.locator(".pg-side .pg-itd-setup .pg-kv");
  await expect(kv).toContainText("시가 범위 돌파");
  await expect(kv).toContainText("달력 12일 가운데 10일");
  await expect(kv).toContainText("1.5bp");
  await expect(page.locator(".pg-side .pg-itd-setup")).toContainText("실행마다 시행으로 기록합니다");

  // ② 설정 판 — 고른 규칙 틀의 칸만 보인다 · 종목 칸은 추천 없이 사용자가 넣은 것 그대로
  await tab(page, "settings");
  await expect(page.locator('.pg-basic-field[data-field="opening_range_breakout__minutes"]')).toBeVisible();
  await expect(page.locator('.pg-basic-field[data-field="rsi_reversal__n"]')).toHaveCount(0);
  await expect(page.locator('.pg-basic-field[data-field="rule"]')).toContainText("볼린저 밴드");
  await expect(page.locator(".pg-save-btn")).toHaveText("분봉 백테스트 실행");

  // ③ 단추 한 번 — 계산 · 판정 · 시행 기록
  const saved = page.waitForResponse((r) => r.url().includes("/allocation/graph/save"), { timeout: 120_000 });
  await page.locator(".pg-save-btn").click();
  const sv = await (await saved).json();
  expect(sv.ok, sv.message).toBe(true);
  expect(sv.saved_id).toMatch(/^[0-9a-f]{64}$/);
  await expect(page.locator(".pg-save-msg")).toContainText("시행으로 기록했습니다");
  page.off("request", watch);

  // ④ 결과 조회 노드 — 남긴 요약을 읽는다
  await page.locator(".pg-save-follow").click();
  const loader = page.locator(".pg-node").filter({ hasText: "분봉 결과 조회" });
  await expect(loader).toHaveCount(1);
  const second = await run(page);
  const lid = Object.keys(second.nodes).find((k) => second.nodes[k].type === "intraday_load")!;
  expect(second.nodes[lid].status, second.nodes[lid].reason).toBe("ok");
  expect(second.nodes[lid].view.trial_key).toBe(sv.saved_id);
  await loader.click();
  await tab(page, "detail");
  const panel = page.locator(".pg-side .pg-itd-load");
  await expect(panel).toHaveAttribute("data-grade", "E3");
  await expect(panel.locator(".tx-notice")).toHaveCount(0);                        // 실제 등급 — 합성 알림이 없다(짝은 아래 스펙)
  await expect(panel.locator(".pg-itd-gross")).toHaveText("+19,800원");
  await expect(panel.locator(".pg-itd-net")).toHaveText(`${MINUS}3,195원`);
  await expect(panel.locator(".pg-itd-breakeven")).toHaveText("9.9bp");
  await expect(panel.locator(".pg-kv")).toContainText("거래");
  await expect(panel.locator(".pg-kv")).toContainText("10건");
  // 화면(백테스트 › 분봉 규칙)과 같은 판정 부품 — 상태와 사유는 서버 값 그대로 · 종합 점수 없음
  await expect(panel.locator(".itd-verdict .tx-answer-s")).toHaveText("관문 일곱 가운데 통과 2 · 미달 1 · 미상 4 입니다.");
  await expect(panel.locator(".itd-gate .itd-gate-state")).toHaveText(["통과", "미상", "통과", "미상", "미달", "미상", "미상"]);
  await expect(gate(page, "cost_robustness").locator(".itd-gate-reason")).toHaveText("비용을 두 배로 놓으면 거래당 기대값이 0 이하입니다.");
  await expect(gate(page, "economic_value").locator(".itd-gate-reason")).toContainText("재지 않습니다");
  await expect(panel.locator(".tx-chip", { hasText: "종합 점수 없음" })).toBeVisible();
  await expect(panel.locator(".itd-slippage tr[data-ticks='0']")).toContainText("+39,600원");
  await expect(panel.locator(".itd-trial")).toHaveAttribute("data-recorded", "true");
  // 카드 — 머리 수는 원 단위 정수를 천 단위로 끊어 그린다
  await expect(loader.locator(".pg-node-v")).toContainText("-3,195");
  await expect(loader.locator(".pg-node-v")).toContainText("비용 후 실현손익");

  // ⑤ 고르기 목록 — 내 결과가 뜬다(설정 탭)
  await tab(page, "settings");
  const picked = page.locator(".pg-side .pg-pick-row.on");
  await expect(picked).toHaveCount(1);
  await expect(picked).toContainText("시가 범위 돌파 · 035720");
  await expect(picked).toContainText("2026-03-02 ~ 2026-03-13");

  expect(uniq(sink.api404), "404").toEqual([]);
  expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("합성 분봉 위의 결과는 판 맨 위에 그렇게 적는다 · 고르기 목록에도 표식", async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  await openCanvas(page);
  await importDoc(page, [setup({ ...HAND, tickers: ["005930"], start_date: "2026-04-01", end_date: "2026-04-16", unknown_market: undefined, unknown_instrument: undefined })]);
  const first = await run(page);
  expect(first.nodes.is.status, first.nodes.is.reason).toBe("ok");
  await node(page, "is").click();
  await tab(page, "settings");
  const saved = page.waitForResponse((r) => r.url().includes("/allocation/graph/save"), { timeout: 120_000 });
  await page.locator(".pg-save-btn").click();
  expect((await (await saved).json()).ok).toBe(true);
  await page.locator(".pg-save-follow").click();
  const loader = page.locator(".pg-node").filter({ hasText: "분봉 결과 조회" });
  await run(page);
  await loader.click();
  await tab(page, "detail");
  const panel = page.locator(".pg-side .pg-itd-load");
  await expect(panel).toHaveAttribute("data-grade", "E0");
  await expect(panel.locator(":scope > .tx-notice").first()).toContainText("합성 분봉 위의 결과입니다.");
  expect(await panel.evaluate((el) => el.firstElementChild?.classList.contains("tx-notice"))).toBe(true);   // 맨 위
  await expect(gate(page, "data_integrity")).toHaveAttribute("data-state", "degraded");
  // ★미상 ≠ 0★ — 시장 구분을 모르는 종목이라 매도세를 산출하지 못했다. 비용 후는 0원이 아니라 N/A 다.
  await expect(panel.locator(".pg-itd-net")).toHaveText("N/A");
  await expect(panel.locator(".pg-itd-gross")).toHaveText(/^[+−]?[\d,]+원$/);
  await tab(page, "settings");
  await expect(page.locator(".pg-side .pg-pick-row.on .pg-tag")).toContainText("합성 분봉");
});

test("설정 판의 직접 적는 칸: 적으면 요청이 바뀌고 · 비우면 0 이 아니라 정하지 않음 · 틀을 바꾸면 그 틀의 칸", async ({ page }) => {
  await login(page);
  await openCanvas(page);
  await importDoc(page, [setup()]);
  await node(page, "is").click();
  await tab(page, "settings");
  const input = (name: string) => page.locator(`.pg-basic-field[data-field="${name}"] .pg-input`);
  await expect(input("opening_range_breakout__minutes")).toHaveValue("1");
  await expect(input("commission_bp")).toHaveValue("1.5");
  // 칸의 모양은 값의 종류를 따른다 — 날짜는 달력 입력, 수는 수 입력(단위는 칸 옆에)
  await expect(input("start_date")).toHaveAttribute("type", "date");
  await expect(input("commission_bp")).toHaveAttribute("type", "number");
  await expect(page.locator('.pg-basic-field[data-field="commission_bp"] .pg-input-unit')).toHaveText("bp");
  await input("opening_range_breakout__minutes").fill("5");
  await input("commission_bp").fill("");                                          // 비움 = 모름(0 이 아니다)
  await input("start_date").fill("2026-03-03");
  await input("stop_pct").fill("2.5");
  const body = await run(page);
  expect(body.nodes.is.status, body.nodes.is.reason).toBe("ok");
  const req = body.nodes.is.view.request;
  expect(req.rule.params.minutes).toBe(5);
  expect(req.costs.commission_bp).toBeNull();
  expect(req.from).toBe("2026-03-03");
  expect(req.position.stop_pct).toBe(2.5);
  await expect(input("commission_bp")).toHaveValue("");
  await expect(input("commission_bp")).toHaveAttribute("placeholder", "정하지 않음");

  // 틀을 바꾸면 그 틀의 칸만 보인다(기본값은 등록부의 것)
  await page.locator('.pg-basic-field[data-field="rule"] .pg-choice', { hasText: "RSI" }).click();
  await expect(input("rsi_reversal__n")).toHaveValue("14");
  await expect(input("opening_range_breakout__minutes")).toHaveCount(0);
  // 기본값이 있는 칸은 적는 동안에는 빈 채로 두고, 칸을 떠나면 쓰이는 값(기본값)을 보인다
  await input("rsi_reversal__n").fill("");
  await expect(input("rsi_reversal__n")).toHaveValue("");
  await input("rsi_reversal__n").blur();
  await expect(input("rsi_reversal__n")).toHaveValue("14");
});

test("고르기 목록: 결과 저장소를 못 읽으면 빈 목록이 아니라 사유", async ({ page }) => {
  await login(page);
  const why = "분봉 결과 저장소를 읽지 못했습니다(결과가 없는 것과 다릅니다).";
  await page.route("**/api/v1/intraday/results", (r) => r.fulfill({ json: { available: false, reason: why, results: [] } }));
  await openCanvas(page);
  await importDoc(page, [{ id: "l", type: "intraday_load", position: { x: 0, y: 0 }, params: {} }]);
  await node(page, "l").click();
  await tab(page, "settings");
  await expect(page.locator(".pg-side .pg-pick-err")).toContainText(why);
  await expect(page.locator(".pg-side .pg-pick")).toHaveCount(0);                 // '실행한 분봉 백테스트가 없습니다'로 보이지 않는다
});

for (const theme of ["light", "dark"] as const) {
  test(`결과 판: ${theme} 대비 AA · 문체`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await login(page);
    await openCanvas(page);
    await importDoc(page, [setup()]);
    await run(page);
    await node(page, "is").click();
    await tab(page, "settings");
    const saved = page.waitForResponse((r) => r.url().includes("/allocation/graph/save"), { timeout: 120_000 });
    await page.locator(".pg-save-btn").click();
    expect((await (await saved).json()).ok).toBe(true);
    await page.locator(".pg-save-follow").click();
    await run(page);
    await page.locator(".pg-node").filter({ hasText: "분봉 결과 조회" }).click();
    await tab(page, "detail");
    await expect(page.locator(".pg-side .pg-itd-load .itd-gate")).toHaveCount(7);
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
    // 뿌리는 이 판이다 — 오른쪽 판 전체에는 기존 부품(실행 기록 표의 빈 칸 줄표)이 함께 있다.
    const a = (await page.evaluate(contrastAudit(".pg-side .pg-itd"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(60);
    expect(a.low, theme).toEqual([]);
    if (theme === "dark") expect(a.bright, "다크에 밝은 배경").toEqual([]);
    const v = (await page.evaluate(voiceAudit(".pg-side .pg-itd"))) as VoiceResult;
    expect(v.checked).toBeGreaterThan(40);
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
  });
}
