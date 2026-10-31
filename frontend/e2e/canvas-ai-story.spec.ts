import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * AI2 · 'AI 가 풀어 쓴 글' — 이야기 탭 맨 위, 서버가 봉인한 설명만 근거로(스펙 §AI2, 사용자 결정 2026-10-22)
 *  · ★누를 때만★ [AI 로 풀어 쓰기] · 계산 전이면 안내만(단추 없음) · 로그아웃이면 로그인 링크, 요청 0
 *  · 보내는 것 = 화면 결과의 설명과 봉인(`explain_sig`) 그대로, 흐름 순서 — 낡은 결과는 보내지 않는다
 *  · 문단마다 근거 칩(화면 번호 + 이름) — 누르면 그 노드 · 연습용 경고는 ★서버가 붙인 것★만(`notice`)
 *  · 못 보이면 서버 사유 그대로 · 검사에서 빠진 문단·확인 못 한 결과는 수와 사유를 말한다 · 아래 서버 설명은 그대로
 *  · 계산 결과가 바뀌면(노드를 지움 등) AI 글을 지우고 말한다 — 짝: 옮기기만 하면 남는다
 *  · 이 환경의 실제 서버는 Claude 키가 없다 — 가로채지 않은 길로 ★실제 봉인이 브라우저 왕복을 견디는지★까지 한 번 돈다
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
/** 종목 → 수익률 → 추정 → 비중: 끝까지 계산된다(연습용 데이터). */
const CORE = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 320, 0),
                             n("estimate", "estimate", 640, 0), n("optimizer", "optimizer", 960, 0)],
               edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
                       e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")] };
const NARRATE = "**/api/v1/assist/canvas/narrate";
const NOTICE = "연습용 결과예요. 실제 시세가 아니라 합성 데이터로 계산했어요. 투자 판단에 쓰기 전에 실데이터로 다시 계산해 주세요.";
type Fact = { node_id: string; explain: unknown; sig: string };
type RunNode = { explain?: unknown; explain_sig?: string };
const PARAS = [{ text: "종목 둘을 골라 최근 수익률을 불러왔어요.", node_ids: ["universe", "returns"] },
               { text: "비중은 수익 대비 위험 최적으로 나눴어요.", node_ids: ["optimizer"] }];
const ok = (paragraphs = PARAS, extra: Record<string, unknown> = {}) => ({
  available: true, source: "claude", model: "claude-opus-5-5", paragraphs, rejected: [], dropped: [], notice: NOTICE, cached: false,
  usage: { input_tokens: 2400, output_tokens: 400, cost_usd: 0.0176, cost_note: null }, ...extra });

const card = (page: Page) => page.locator(".pg-ai-story");
const ask = (page: Page) => page.locator(".pg-ai-story-ask");

async function signIn(page: Page) {
  await page.addInitScript(() => { try { localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"); } catch { /* */ } });
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
    principal: { username: "alice", role: "analyst" }, must_change_password: false, password_changed_at: null } }));
}

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("ai2_seeded")) return;
      sessionStorage.setItem("ai2_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      localStorage.removeItem("alpha_pg_view");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
}

/** 실제 백엔드로 전부 계산하고 `/run` 보고서를 돌려준다. */
async function runAll(page: Page): Promise<{ nodes: Record<string, RunNode> }> {
  const res = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = await (await res).json();
  await expect(page.locator(".pg-run")).toHaveText("계산하기", { timeout: 120_000 });
  return body;
}

function answer(page: Page, body: object | ((route: Route) => Promise<void>)) {
  const seen: { graph: { nodes: { id: string }[] }; facts: Fact[] }[] = [];
  return page.route(NARRATE, async (route) => {
    seen.push(route.request().postDataJSON());
    if (typeof body === "function") return body(route);
    await route.fulfill({ json: body });
  }).then(() => seen);
}

test.use({ viewport: { width: 1440, height: 900 } });

test("계산 전에는 안내만(단추 없음) — 짝: 계산하면 [AI 로 풀어 쓰기]", async ({ page }) => {
  await signIn(page);
  await openWith(page, CORE);
  await expect(card(page).locator(".pg-ai-story-h")).toHaveText("AI 가 풀어 쓴 글");
  await expect(card(page).locator(".pg-ai-story-wait")).toHaveText("계산한 뒤에 풀어 쓸 수 있어요");
  await expect(ask(page)).toHaveCount(0);
  await runAll(page);
  await expect(ask(page)).toHaveText("AI 로 풀어 쓰기");                                   // ★짝★
  await expect(card(page).locator(".pg-ai-story-wait")).toHaveCount(0);
});

test("로그아웃이면 로그인 링크 · 요청 0", async ({ page }) => {
  const sent: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/assist/canvas/narrate")) sent.push(r.url()); });
  await openWith(page, CORE);
  await runAll(page);
  await expect(card(page).locator(".pg-ai-story-login")).toHaveText("로그인하면 AI 로 풀어 쓸 수 있어요");
  await expect(card(page).locator(".pg-ai-story-login")).toHaveAttribute("href", "/login");
  await expect(ask(page)).toHaveCount(0);
  await page.waitForTimeout(400);
  expect(sent).toEqual([]);
});

test("누르면 화면 결과의 설명·봉인을 흐름 순서로 그대로 보낸다 → 문단·근거 칩 · 칩을 누르면 그 노드 · 서버 연습용 경고", async ({ page }) => {
  await signIn(page);
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  const seen = await answer(page, async (route) => { await gate; await route.fulfill({ json: ok() }); });
  await openWith(page, CORE);
  const rep = await runAll(page);
  await ask(page).click();
  await expect(ask(page)).toHaveText("AI 가 풀어 쓰는 중이에요");
  await expect(ask(page)).toBeDisabled();
  release();
  await expect(card(page).locator(".pg-ai-para")).toHaveCount(2);
  expect(seen).toHaveLength(1);
  expect(seen[0].facts.map((f) => f.node_id)).toEqual(["universe", "returns", "estimate", "optimizer"]);
  for (const f of seen[0].facts) {
    expect(f.sig).toBe(rep.nodes[f.node_id].explain_sig);
    expect(f.explain).toEqual(rep.nodes[f.node_id].explain);
  }
  expect(seen[0].graph.nodes.map((x) => x.id)).toEqual(["universe", "returns", "estimate", "optimizer"]);
  const first = card(page).locator(".pg-ai-para").first();
  await expect(first.locator(".pg-ai-para-text")).toHaveText(PARAS[0].text);
  await expect(first.locator(".pg-ai-chip")).toHaveText(["1 종목 고르기", "2 수익률 불러오기"]);
  await expect(card(page).locator(".pg-ai-story-notice")).toHaveText(NOTICE);
  await expect(card(page).locator(".pg-ai-story-cap")).toContainText("서버 설명을 근거로");
  await card(page).locator(".pg-ai-para").nth(1).locator(".pg-ai-chip").click();
  await expect(page.locator('.pg-step[data-node-id="optimizer"]')).toHaveClass(/pg-step--cur/);
  await expect(page.locator(".pg-step")).toHaveCount(4);                                   // 서버 설명은 그대로
  await expect(ask(page)).toHaveText("AI 로 다시 풀어 쓰기");
});

test("연습용 경고는 서버가 붙였을 때만 — 짝: notice 가 없으면 없다", async ({ page }) => {
  await signIn(page);
  await answer(page, ok(PARAS, { notice: null }));
  await openWith(page, CORE);
  await runAll(page);
  await ask(page).click();
  await expect(card(page).locator(".pg-ai-para")).toHaveCount(2);
  await expect(card(page).locator(".pg-ai-story-notice")).toHaveCount(0);
});

test("못 보이면 서버 사유를 그대로 · 문단 0 · 서버 설명은 그대로", async ({ page }) => {
  await signIn(page);
  await answer(page, { available: false, source: "unavailable", reason_code: "rate_limited", reason: "한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요", dropped: [] });
  await openWith(page, CORE);
  await runAll(page);
  await ask(page).click();
  await expect(card(page).locator(".pg-ai-story-note")).toHaveText("AI 글을 보여 줄 수 없어요: 한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요");
  await expect(card(page).locator(".pg-ai-para")).toHaveCount(0);
  await expect(page.locator(".pg-step")).toHaveCount(4);
  await expect(ask(page)).toHaveText("AI 로 풀어 쓰기");
});

test("검사에서 빠진 문단 · 확인하지 못한 결과는 수와 사유를 말한다", async ({ page }) => {
  await signIn(page);
  await answer(page, ok([PARAS[1]], {
    rejected: [{ code: "numbers", reason: "근거 노드에 없는 숫자 9 를 썼어요" }],
    dropped: [{ node_id: "universe", reason: "서명이 맞지 않아요(그래프가 바뀌었거나 서버가 다시 시작했어요). 다시 계산하면 풀어 쓸 수 있어요" }] }));
  await openWith(page, CORE);
  await runAll(page);
  await ask(page).click();
  await expect(card(page).locator(".pg-ai-para")).toHaveCount(1);
  const note = card(page).locator(".pg-ai-story-note");
  await expect(note).toContainText("1문단은 검사에서 빠졌어요: 근거 노드에 없는 숫자 9 를 썼어요");
  await expect(note).toContainText("1개 단계의 결과는 확인하지 못해 뺐어요: 서명이 맞지 않아요");
});

test("계산 결과가 바뀌면 AI 글을 지우고 말한다 — 짝: 노드를 옮기기만 하면 남는다 · 다시 물으면 낡지 않은 결과만 보낸다", async ({ page }) => {
  await signIn(page);
  const seen = await answer(page, ok());
  await openWith(page, CORE);
  await runAll(page);
  await ask(page).click();
  await expect(card(page).locator(".pg-ai-para")).toHaveCount(2);
  const b = (await page.locator('.react-flow__node[data-id="universe"]').boundingBox())!;      // ★짝★ 옮기기
  await page.mouse.move(b.x + 30, b.y + 14);
  await page.mouse.down();
  await page.mouse.move(b.x + 60, b.y + 160, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(600);
  await expect(card(page).locator(".pg-ai-para")).toHaveCount(2);
  await expect(card(page).locator(".pg-ai-story-stale")).toHaveCount(0);
  await page.locator('.react-flow__node[data-id="estimate"]').click();                       // 지운다 — 아래 비중 계산도 낡는다
  await page.keyboard.press("Delete");
  await expect(card(page).locator(".pg-ai-para")).toHaveCount(0);
  await expect(card(page).locator(".pg-ai-story-stale")).toHaveText("계산 결과가 바뀌어 AI 글을 지웠어요");
  await expect(ask(page)).toHaveText("AI 로 다시 풀어 쓰기");
  await ask(page).click();                                                                  // 비중 계산은 위가 바뀌어 낡았다 — 보내지 않는다
  await expect.poll(() => seen.length).toBe(2);
  expect(seen[1].facts.map((f) => f.node_id)).toEqual(["universe", "returns"]);
});

test("가로채지 않은 실제 서버: 실제 계산 → 실제 봉인 → 브라우저 왕복 → 서버 확인(버린 것 0) → 키 없음 사유", async ({ page }) => {
  const login = await page.request.post("/api/backend/api/v1/auth/login", { data: { username: "admin", password: "frm123!" } });
  expect(login.ok(), await login.text()).toBe(true);
  const token = (await login.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  await openWith(page, CORE);
  await runAll(page);
  const res = page.waitForResponse((r) => r.url().includes("/assist/canvas/narrate"));
  await ask(page).click();
  const body = await (await res).json();
  expect(body).toMatchObject({ available: false, source: "unavailable", reason_code: "no_key", dropped: [] });
  await expect(card(page).locator(".pg-ai-story-note")).toHaveText("AI 글을 보여 줄 수 없어요: 서버에 Claude 키가 없어요");
  await expect(card(page).locator(".pg-ai-para")).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`AI 글 대비(${scheme}) AA`, async ({ page }) => {
    await signIn(page);
    await answer(page, ok());
    await openWith(page, CORE);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await runAll(page);
    await ask(page).click();
    await expect(card(page).locator(".pg-ai-para")).toHaveCount(2);
    const a = await page.evaluate<AuditResult>(contrastAudit(".pg-ai-story"));
    expect(a.checked).toBeGreaterThanOrEqual(8);
    expect(a.low, scheme).toEqual([]);
  });
}

test.describe("좁은 화면(390)", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("오른쪽 창을 열면 카드·단추가 화면 안 · 누르면 문단", async ({ page }) => {
    await signIn(page);
    await answer(page, ok());
    await openWith(page, CORE);
    await runAll(page);
    // 좁으면 오른쪽 창은 닫힌 채 시작하고, 노드를 고르면 아래 시트로 열린다(canvas-panels 390 과 같은 길).
    await page.locator('.pg-node[data-node-id="universe"]').click();
    await expect(page.locator(".pg-side")).toBeVisible();
    await page.locator('.pg-tab[data-tab="story"]').click();
    await expect(ask(page)).toBeVisible();
    const b = (await ask(page).boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(0);
    expect(b.x + b.width).toBeLessThanOrEqual(390);
    await ask(page).click();
    await expect(card(page).locator(".pg-ai-para")).toHaveCount(2);
  });
});
