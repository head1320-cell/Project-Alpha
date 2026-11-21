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
//  · ★가동 요청(W5b)★: 결과 조회 → 가동 요청 — 계산은 쓰지 않고 · 단추 한 번이 요청 한 줄만 남기며 · 아무것도 가동하지 않는다
//    (가동 · 정지는 내 계좌에서만 — `rule-arming.spec.ts`)
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

async function importDoc(page: Page, nodes: object[], edges: object[] = []) {
  const doc = { format: "project-alpha.portfolio-graph", version: 1, meta: { name: "분봉 노드" }, edges, nodes };
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
  // 자유도 공시(G3) — 같은 판정 부품이라 결과 판에도 같은 상자 · 다중 비교 관문의 마지막 사실 줄(남긴 요약의 서버 문장 그대로)
  const told = String(second.nodes[lid].view.freedom.message);
  await expect(panel.locator(".itd-free .itd-free-answer")).toHaveText(told);
  await expect(gate(page, "multiplicity").locator(".itd-gate-facts li").last()).toHaveText(told);
  await expect(panel.locator(".itd-hypo")).toHaveCount(0);                          // 캔버스에는 가설 칸이 없다 — 남은 가설이 없으면 상자도 없다
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

test("직접 구성: 설정 판에서 조건을 짓고 → 계산 → 실행 → 결과 조회의 값 = 손 계산 · 판과 고르기 목록에 조건의 글 · 빈 칸이면 서버의 사유로 실패", async ({ page }) => {
  test.setTimeout(180_000);
  const sink = trackErrors(page);
  const TEXT = "진입 조건: 종가 상향 돌파 10050";      // 손 계산의 규칙 — 틀 '시가 범위 돌파 1분'과 같은 체결(09:02 매수 · 09:03 청산)
  await login(page);
  await openCanvas(page);
  await importDoc(page, [setup()]);
  await node(page, "is").click();
  await tab(page, "settings");
  const field = page.locator('.pg-side .pg-basic-field[data-field="custom_rule"]');
  await expect(field).toHaveCount(0);                                             // 틀을 골랐을 때는 조건 칸이 없다
  await expect(page.locator('.pg-basic-field[data-field="rule"] .pg-choice')).toHaveCount(8);
  await page.locator('.pg-basic-field[data-field="rule"] .pg-choice', { hasText: "직접 구성" }).click();
  await expect(field.locator(".ire-slot-title")).toHaveText(["진입 조건", "미리 건 매수 가격", "청산 조건"]);   // 화면과 같은 편집 부품 · 비어서 시작한다
  await expect(page.locator('.pg-basic-field[data-field="opening_range_breakout__minutes"]')).toHaveCount(0);
  await expect(field.locator(".pg-itd-rule-issues li")).toHaveText(["진입 조건과 미리 건 매수 가격 가운데 하나는 있어야 합니다."]);
  await expect(field.locator('.itd-check[data-state="idle"]')).toBeVisible();
  await expect(field).toContainText("도구는 조건을 추천하지 않습니다.");
  await expect(node(page, "is").locator('[data-field="custom_rule"]')).toHaveCount(0);   // 편집은 오른쪽 설정 판에서만 — 카드에는 칸이 없다

  // ① 빈 채로 계산하면 노드가 서버의 사유로 실패한다(지어낸 조건으로 돌지 않는다)
  const empty = await run(page);
  expect(empty.nodes.is.status).toBe("failed");
  expect(empty.nodes.is.reason).toContain("진입 조건과 미리 건 매수 가격 가운데 하나는 있어야 합니다.");

  // ② 빈 줄이 있는 채로 — 서버가 어느 자리인지 말하고, 설정 판은 몇 곳이 비었는지 말한다
  const entry = field.locator('.ire-slot[data-slot="entry"]');
  await entry.locator('.ire-add[data-add="compare"]').click();
  await expect(field.locator(".pg-itd-rule-issues li")).toHaveText(["진입 조건: 비어 있는 칸이 3곳 있습니다."]);
  const half = await run(page);
  expect(half.nodes.is.status).toBe("failed");
  expect(half.nodes.is.reason).toMatch(/^진입 조건: /);

  // ③ 조건을 짓는다 → 서버의 글 → 계산 ok(요청의 규칙 = 지은 나무)
  await entry.getByLabel("진입 조건: 왼쪽 값", { exact: true }).selectOption("ind:close");
  await entry.getByLabel("진입 조건: 연산", { exact: true }).selectOption("cross_up");
  await entry.getByLabel("진입 조건: 오른쪽 값", { exact: true }).selectOption("const");
  await entry.getByLabel("진입 조건: 오른쪽 값 상수", { exact: true }).fill("10050");
  await expect(field.locator(".itd-rule-text")).toHaveText(TEXT);
  await expect(field.locator(".pg-itd-rule-issues")).toHaveCount(0);
  const sent = page.waitForRequest((r) => r.url().includes("/allocation/graph/run") && r.method() === "POST");
  const ok = await run(page);
  const carried = ((await sent).postDataJSON() as { nodes: { id: string; params: Record<string, unknown> }[] }).nodes.find((n) => n.id === "is")!.params;
  expect(carried.rule).toBe("custom");
  expect(carried.custom_rule, "문서에는 지은 나무가 그대로 · 쓰지 않는 자리는 없다").toEqual({ entry: { op: "cross_up", args: [{ ind: "close" }, { const: 10050 }] } });
  expect(Object.keys(carried.custom_rule as object)).toEqual(["entry"]);
  expect(ok.nodes.is.status, ok.nodes.is.reason).toBe("ok");
  expect(ok.nodes.is.view.request.rule).toEqual({ kind: "custom", params: { entry: { op: "cross_up", args: [{ ind: "close" }, { const: 10050 }] } } });
  expect(ok.nodes.is.view.rule_text).toBe(TEXT);
  expect(ok.nodes.is.explain.facts).toContain(`직접 구성한 조건 — ${TEXT}`);
  await tab(page, "detail");
  const kv = page.locator(".pg-side .pg-itd-setup .pg-kv");
  await expect(kv).toContainText("직접 구성");
  await expect(kv.locator(".pg-itd-rule-text")).toHaveText(TEXT);

  // ④ 단추 한 번 → 결과 조회: 값 = 틀의 손 계산과 같다 · 판과 고르기 목록이 조건의 글을 보인다
  await tab(page, "settings");
  const saved = page.waitForResponse((r) => r.url().includes("/allocation/graph/save"), { timeout: 120_000 });
  await page.locator(".pg-save-btn").click();
  const sv = await (await saved).json();
  expect(sv.ok, sv.message).toBe(true);
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
  await expect(panel.locator(".pg-itd-gross")).toHaveText("+19,800원");
  await expect(panel.locator(".pg-kv")).toContainText("직접 구성");
  await expect(panel.locator(".pg-itd-rule-text")).toHaveText(TEXT);
  await tab(page, "settings");
  const picked = page.locator(".pg-side .pg-pick-row.on");
  await expect(picked).toHaveCount(1);
  await expect(picked).toContainText("직접 구성 · 035720");
  await expect(picked.locator(".pg-pick-text")).toHaveText(TEXT);

  expect(uniq(sink.api404), "404").toEqual([]);
  expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

const BUILT = { entry: { op: "cross_up", args: [{ ind: "close" }, { const: 10050 }] }, exit: { op: "lt", args: [{ ind: "close" }, { ind: "vwap" }] } };
const BUILT_TEXT = "진입 조건: 종가 상향 돌파 10050 · 청산 조건: 종가 < VWAP";

for (const theme of ["light", "dark"] as const) {
  test(`직접 구성(${theme}): 조건이 실린 문서를 들여오면 편집기가 그 조건을 보인다 · 종류를 틀로 바꾸면 요청에 조건이 실리지 않고 문서에는 남는다 · 대비 · 문체`, async ({ page }) => {
    test.setTimeout(180_000);
    const sink = trackErrors(page);
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await login(page);
    await openCanvas(page);
    const asked: string[] = [];
    const watch = (r: Request) => { if (r.url().includes("/api/v1/intraday/")) asked.push(`${r.method()} ${new URL(r.url()).pathname}`); };
    page.on("request", watch);
    await importDoc(page, [setup({ ...HAND, rule: "custom", custom_rule: BUILT })]);
    await node(page, "is").click();
    await tab(page, "settings");
    const field = page.locator('.pg-side .pg-basic-field[data-field="custom_rule"]');
    const entry = field.locator('.ire-slot[data-slot="entry"]');
    const exit = field.locator('.ire-slot[data-slot="exit"]');

    // ① 문서의 조건이 편집기에 그대로 실린다 → 서버의 글(검사는 시행이 아니다 — 분봉 문에는 틀 목록과 검사만 간다)
    await expect(entry.getByLabel("진입 조건: 왼쪽 값", { exact: true })).toHaveValue("ind:close");
    await expect(entry.getByLabel("진입 조건: 연산", { exact: true })).toHaveValue("cross_up");
    await expect(entry.getByLabel("진입 조건: 오른쪽 값 상수", { exact: true })).toHaveValue("10050");
    await expect(exit.getByLabel("청산 조건: 오른쪽 값", { exact: true })).toHaveValue("ind:vwap");
    await expect(field.locator(".itd-rule-text")).toHaveText(BUILT_TEXT);
    await expect(field.locator(".itd-rule-size")).toHaveText("마디 6/64 · 겹침 깊이 2/12");
    await expect(field.locator(".pg-itd-rule-issues")).toHaveCount(0);
    expect([...new Set(asked)].sort()).toEqual([`GET ${API}/intraday/templates`, `POST ${API}/intraday/rules/expand`]);
    const first = await run(page);
    expect(first.nodes.is.status, first.nodes.is.reason).toBe("ok");
    expect(first.nodes.is.view.request.rule).toEqual({ kind: "custom", params: BUILT });
    expect(first.nodes.is.view.rule_text).toBe(BUILT_TEXT);

    // ② 빈 줄을 하나 더하면 — 검사를 멈추고 어느 자리에 몇 곳이 비었는지 말한다(대비 · 문체는 이 상태와 채운 상태 둘 다)
    await exit.locator(':scope > .ire-add-row .ire-add[data-add="compare"]').click();
    await expect(field.locator(".pg-itd-rule-issues li")).toHaveText(["청산 조건: 비어 있는 칸이 3곳 있습니다."]);
    await expect(field.locator('.itd-check[data-state="idle"]')).toBeVisible();
    await expect(field.locator(".itd-rule-text")).toHaveCount(0);
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
    for (const state of ["holes", "ok"] as const) {
      if (state === "ok") {
        await exit.locator(".ire-group-list").first().locator(":scope > li").nth(1).locator('.ire-tool[data-act="remove"]').click();
        await expect(field.locator(".itd-rule-text")).toHaveText(BUILT_TEXT);          // 하나 남은 묶음은 풀린다 — 처음의 조건으로 돌아온다
        await expect(field.locator(".pg-itd-rule-issues")).toHaveCount(0);
      }
      const a = (await page.evaluate(contrastAudit('.pg-side .pg-basic-field[data-field="custom_rule"]'))) as AuditResult;
      expect(a.checked, state).toBeGreaterThan(10);
      expect(a.low, `${theme} ${state}`).toEqual([]);
      if (theme === "dark") expect(a.bright, `다크에 밝은 배경 ${state}`).toEqual([]);
      const v = (await page.evaluate(voiceAudit('.pg-side .pg-basic-field[data-field="custom_rule"]'))) as VoiceResult;
      expect(v.checked, state).toBeGreaterThan(3);
      expect(v.haeyo).toEqual([]);
      expect(v.dash).toEqual([]);
      expect(v.banned).toEqual([]);
    }
    // 설정 판 안에서 넘치지 않는다(편집기는 좁은 판에 들어간다)
    const over = await page.evaluate(() => {
      const side = document.querySelector(".pg-side")!; const right = side.getBoundingClientRect().right + 1;
      return [...side.querySelectorAll(".pg-itd-rule *")].filter((el) => el.getClientRects().length && el.getBoundingClientRect().right > right).map((el) => el.className);
    });
    expect(over, "설정 판 밖으로 넘친 것").toEqual([]);

    // ③ 종류를 틀로 바꾼다 — 조건 칸이 사라지고 요청에는 틀의 것만 간다
    await page.locator('.pg-basic-field[data-field="rule"] .pg-choice', { hasText: "시가 범위 돌파" }).click();
    await expect(field).toHaveCount(0);
    const second = await run(page);
    expect(second.nodes.is.status, second.nodes.is.reason).toBe("ok");
    expect(second.nodes.is.view.request.rule).toEqual({ kind: "opening_range_breakout", params: { minutes: 1 } });
    await tab(page, "detail");
    await expect(page.locator(".pg-side .pg-itd-setup .pg-itd-rule-text")).toContainText("시가 범위 고가(1분)");   // 틀에도 규칙의 글
    await expect(page.locator(".pg-side .pg-itd-setup .pg-itd-rule-text")).not.toContainText("10050");
    // ④ 다시 직접 구성 — 지은 조건은 문서에 남아 있다(다시 짓지 않는다)
    await tab(page, "settings");
    await page.locator('.pg-basic-field[data-field="rule"] .pg-choice', { hasText: "직접 구성" }).click();
    await expect(entry.getByLabel("진입 조건: 오른쪽 값 상수", { exact: true })).toHaveValue("10050");
    await expect(field.locator(".itd-rule-text")).toHaveText(BUILT_TEXT);
    page.off("request", watch);
    expect(asked.filter((a) => !/\/(templates|rules\/expand)$/.test(a)), "편집과 계산은 분봉 백테스트를 실행하지 않는다").toEqual([]);

    expect(uniq(sink.api404), "404").toEqual([]);
    expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
    expect(uniq(sink.pageErrors), "page errors").toEqual([]);
    expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
  });
}

test("직접 구성: 새 지표와 'N봉 전 값'이 실린 문서 — 편집기가 그대로 보이고 좁은 설정 판에서도 넘치지 않는다 · 계산의 글 = 검사의 글", async ({ page }) => {
  test.setTimeout(120_000);
  const sink = trackErrors(page);
  const TEXT = "진입 조건: 종가 > 1봉 전 당일 고가 · 청산 조건: MACD(12봉, 26봉) 하향 돌파 MACD 신호선(12봉, 26봉, 9봉)";
  const rule = { entry: { op: "gt", args: [{ ind: "close" }, { op: "ago", bars: 1, args: [{ ind: "day_high" }] }] },
                 exit: { op: "cross_down", args: [{ ind: "macd", fast: 12, slow: 26 }, { ind: "macd_signal", fast: 12, slow: 26, signal: 9 }] } };
  await login(page);
  await openCanvas(page);
  await importDoc(page, [setup({ ...HAND, rule: "custom", custom_rule: rule })]);
  await node(page, "is").click();
  await tab(page, "settings");
  const field = page.locator('.pg-side .pg-basic-field[data-field="custom_rule"]');
  await expect(field.locator(".ire-ago")).toHaveCount(1);
  await expect(field.getByLabel("진입 조건: 오른쪽 값 N봉 전의 봉 수", { exact: true })).toHaveValue("1");
  await expect(field.getByLabel("진입 조건: 오른쪽 값 N봉 전의 값", { exact: true })).toHaveValue("ind:day_high");
  await expect(field.getByLabel("MACD 신호선 신호 기간", { exact: true })).toHaveValue("9");
  await expect(field.locator(".itd-rule-text")).toHaveText(TEXT);
  const over = await page.evaluate(() => {
    const side = document.querySelector(".pg-side")!; const right = side.getBoundingClientRect().right + 1;
    return [...side.querySelectorAll(".pg-itd-rule *")].filter((el) => el.getClientRects().length && el.getBoundingClientRect().right > right).map((el) => el.className);
  });
  expect(over, "설정 판 밖으로 넘친 것").toEqual([]);
  const out = await run(page);
  expect(out.nodes.is.status, out.nodes.is.reason).toBe("ok");
  expect(out.nodes.is.view.rule_text).toBe(TEXT);
  expect(out.nodes.is.view.request.rule.params.entry.args[1]).toEqual({ op: "ago", args: [{ ind: "day_high" }], bars: 1 });
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

// ── 가동 요청 (W5b) ────────────────────────────────────────────────────────────────────

type ArmRow = { id: number; trial_key: string; gates: { known: boolean; counts: Record<string, number> | null } };
const armRequests = async (page: Page, token: string): Promise<ArmRow[]> => {
  const r = await page.request.get(`${API}/intraday/arm-requests`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  return (await r.json()).requests as ArmRow[];
};
const clearArmRequests = async (page: Page, token: string) => {
  for (const row of await armRequests(page, token)) {
    await page.request.delete(`${API}/intraday/arm-requests/${row.id}`, { headers: { Authorization: `Bearer ${token}` } });
  }
};

/** 캔버스의 단추와 같은 두 문(계산 → 저장)으로 실행 하나를 남기고 그 열쇠를 돌려준다 — 화면을 거치지 않는 준비. */
async function keptTrial(page: Page, token: string): Promise<string> {
  const headers = { Authorization: `Bearer ${token}` };
  const graph = { format: "project-alpha.portfolio-graph", version: 1, edges: [], nodes: [{ id: "is", type: "intraday_setup", params: HAND }] };
  const ran = await page.request.post(`${API}/allocation/graph/run`, { data: graph, headers, timeout: 120_000 });
  expect(ran.ok(), await ran.text()).toBe(true);
  const hash = (await ran.json()).nodes.is.view_hash as string;
  const saved = await page.request.post(`${API}/allocation/graph/save`, { data: { graph, node_id: "is", preview_hash: hash }, headers, timeout: 120_000 });
  const body = await saved.json();
  expect(body.ok, body.message).toBe(true);
  return body.saved_id as string;
}

/** 틀 '시가 범위 돌파 1분'을 풀어 쓴 글 — 서버가 낸다(화면은 그대로 보인다). */
const ORB_TEXT = "진입 조건: 종가 상향 돌파 시가 범위 고가(1분) 또는 ((시가 범위 종료(1분) > 0.5 그리고 아님(직전 1봉 동안(시가 범위 종료(1분) > 0.5))) 그리고 종가 > 시가 범위 고가(1분))";

const armDoc = (key: string): [object[], object[]] => [
  [{ id: "il", type: "intraday_load", position: { x: 0, y: 0 }, params: { trial_key: key } },
   { id: "ar", type: "intraday_arm_request", position: { x: 420, y: 0 }, params: { note: "개장 전 점검" } }],
  [{ source: "il", source_port: "run", target: "ar", target_port: "run" }],
];

for (const theme of ["light", "dark"] as const) {
  test(`가동 요청(${theme}): 계산은 쓰지 않고 · 단추 한 번이 요청 한 줄만 남기며 · 아무것도 가동하지 않는다`, async ({ page }) => {
    test.setTimeout(240_000);
    const sink = trackErrors(page);
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    const token = await login(page);
    await clearArmRequests(page, token);
    const key = await keptTrial(page, token);
    await openCanvas(page);
    await importDoc(page, ...armDoc(key));

    // ① 계산 — 요청 표에 아무것도 쓰지 않는다 · 판은 무엇을 요청하게 되는지만 보인다
    const first = await run(page);
    expect(first.nodes.ar.status, first.nodes.ar.reason).toBe("ok");
    expect(first.nodes.ar.view.requested).toBe(false);
    expect(await armRequests(page, token), "계산은 요청을 남기지 않는다").toEqual([]);
    await expect(node(page, "ar")).toContainText("가동 요청");
    // 포트 — 분봉 결과의 색이 '모르는 타입'의 회색이 아니다 · 선이 이어져 있다
    const colors = await page.evaluate(() => {
      const css = getComputedStyle(document.querySelector(".pg-theme") ?? document.documentElement);
      return { run: css.getPropertyValue("--pg-port-IntradayRun").trim(), unknown: css.getPropertyValue("--pg-port-unknown").trim() };
    });
    expect(colors.run).toMatch(/^#[0-9a-f]{6}$/i);
    expect(colors.run).not.toBe(colors.unknown);
    await expect(page.locator(".react-flow__edge")).toHaveCount(1);
    await expect(node(page, "ar").locator(".pg-port--unknown")).toHaveCount(0);

    await node(page, "ar").click();
    await tab(page, "detail");
    const panel = page.locator(".pg-side .pg-itd-arm");
    await expect(panel).toHaveAttribute("data-requested", "false");
    await expect(panel).toHaveAttribute("data-grade", "E3");
    await expect(panel.locator(".tx-notice")).toHaveCount(0);                      // 실제 등급 — 합성 알림이 없다
    await expect(panel.locator(".pg-kv")).toContainText("시가 범위 돌파");
    await expect(panel.locator(".pg-itd-rule-text")).toHaveText(ORB_TEXT);          // 무엇을 가동해 달라는 것인지 — 이름표만이 아니라 조건의 글
    await expect(panel.locator(".pg-itd-rule-text")).toHaveAttribute("data-known", "true");
    await expect(panel.locator(".pg-kv")).toContainText("1개 · 2026-03-02 ~ 2026-03-13");
    await expect(panel.locator(".pg-itd-gates")).toHaveText("통과 2 · 미달 1 · 미상 4");
    await expect(panel.locator(".pg-itd-state")).toHaveText("남기지 않음");
    await expect(panel.locator(".pg-itd-memo")).toHaveText("개장 전 점검");
    await expect(panel).toContainText("요청은 가동이 아닙니다.");
    await expect(panel).toContainText("증권사로 주문을 전송하지 않습니다.");
    await expect(panel.locator(".pg-itd-go")).toHaveAttribute("href", "/my-account");

    // 대비 · 문체 — 뿌리는 이 판이다
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
    const a = (await page.evaluate(contrastAudit(".pg-side .pg-itd-arm"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(10);
    expect(a.low, theme).toEqual([]);
    if (theme === "dark") expect(a.bright, "다크에 밝은 배경").toEqual([]);
    const v = (await page.evaluate(voiceAudit(".pg-side .pg-itd-arm"))) as VoiceResult;
    expect(v.checked).toBeGreaterThan(3);
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);

    // ② 단추 한 번 — 요청 한 줄. 가동을 시작하는 요청은 어디에도 가지 않는다
    const started: string[] = [];
    const watch = (r: Request) => { if (/\/rule-runs(\/|$)/.test(new URL(r.url()).pathname)) started.push(`${r.method()} ${new URL(r.url()).pathname}`); };
    page.on("request", watch);
    await tab(page, "settings");
    await expect(page.locator(".pg-save-btn")).toHaveText("가동 요청 남기기");
    const saved = page.waitForResponse((r) => r.url().includes("/allocation/graph/save"), { timeout: 120_000 });
    await page.locator(".pg-save-btn").click();
    const sv = await (await saved).json();
    expect(sv.ok, sv.message).toBe(true);
    await expect(page.locator(".pg-save-msg")).toContainText("가동 요청을 남겼습니다");
    await expect(page.locator(".pg-save-msg")).toContainText("내 계좌 › 규칙 가동");
    await expect(page.locator(".pg-save-follow")).toHaveCount(0);                  // 이어 붙일 노드가 없다 — 다음은 내 계좌다
    const rows = await armRequests(page, token);
    expect(rows.map((r) => [String(r.id), r.trial_key])).toEqual([[sv.saved_id, key]]);
    expect(rows[0].gates).toEqual({ known: true, counts: { ok: 2, degraded: 1, unknown: 4 }, reason: null });
    expect(started, "캔버스는 가동의 문을 부르지 않는다").toEqual([]);
    page.off("request", watch);

    // ③ 다시 계산 — 이미 남긴 요청이라고 말한다
    const second = await run(page);
    expect(second.nodes.ar.view.requested).toBe(true);
    await node(page, "ar").click();
    await tab(page, "detail");
    await expect(panel).toHaveAttribute("data-requested", "true");
    await expect(panel.locator(".pg-itd-state")).toHaveText("이미 남김");

    await clearArmRequests(page, token);
    expect(uniq(sink.api404), "404").toEqual([]);
    expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
    expect(uniq(sink.pageErrors), "page errors").toEqual([]);
    expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
  });
}

test("규칙의 글: 읽은 결과는 글을 보이고 · 읽지 못했다는 답이면 그 사유를 보이며 · 둘 다 없으면 미상으로 둔다(지어내지 않는다)", async ({ page }) => {
  test.setTimeout(180_000);
  const token = await login(page);
  const key = await keptTrial(page, token);
  await openCanvas(page);
  await importDoc(page, [{ id: "il", type: "intraday_load", position: { x: 0, y: 0 }, params: { trial_key: key } }]);
  const first = await run(page);
  expect(first.nodes.il.status, first.nodes.il.reason).toBe("ok");
  expect(first.nodes.il.view.rule_text).toBe(ORB_TEXT);
  await node(page, "il").click();
  await tab(page, "detail");
  const text = page.locator(".pg-side .pg-itd-load .pg-itd-rule-text");
  await expect(text).toHaveText(ORB_TEXT);
  await expect(text).toHaveAttribute("data-known", "true");
  await expect(page.locator(".pg-side .pg-pick-row")).toHaveCount(0);            // 자세히 탭 — 고르기 목록은 설정 탭에 있다

  // 서버가 '읽지 못했다'고 답한 때(대역 — 실제 답에서 글만 걷고 서버의 사유 문장을 싣는다)
  const REASON = "이 설정의 규칙을 지금의 문법으로 읽지 못했습니다.";
  let patch: (view: Record<string, unknown>) => void = (view) => { view.rule_text = null; view.rule_text_reason = REASON; };
  await page.route("**/allocation/graph/run", async (route) => {
    const resp = await route.fetch();
    const body = await resp.json();
    patch(body.nodes.il.view);
    await route.fulfill({ response: resp, json: body });
  });
  await run(page);
  await expect(text).toHaveText(REASON);
  await expect(text).toHaveAttribute("data-known", "false");
  await expect(page.locator(".pg-side .pg-itd-load .pg-itd-gross")).toHaveText("+19,800원");   // 숫자는 그대로다 — 글만 없다

  patch = (view) => { view.rule_text = null; view.rule_text_reason = null; };
  await run(page);
  await expect(text).toHaveText("N/A");
  await expect(text).toHaveAttribute("data-known", "false");
  await expect(page.locator(".pg-side .pg-itd-load")).not.toContainText("시가 범위 고가");       // 글을 지어내지 않는다
});

test("가동 요청: 로그인 전에는 사유와 함께 실패하고 요청 판을 지어내지 않는다", async ({ page }) => {
  await openCanvas(page);
  await importDoc(page, ...armDoc("a".repeat(64)));
  const body = await run(page);
  expect(body.nodes.il.status).toBe("failed");
  expect(body.nodes.ar.status).not.toBe("ok");
  await node(page, "ar").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-itd-arm")).toHaveCount(0);
  await tab(page, "settings");
  await expect(page.locator(".pg-save-btn")).toBeDisabled();
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
