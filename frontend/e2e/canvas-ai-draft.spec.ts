import { readFileSync } from "node:fs";
import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * AI4 · 말로 설계 — 왼쪽 창 '말로' 탭 + 캔버스 유령(스펙 §AI4 설계, 사용자 결정 2026-10-23)
 *  · 말씀 → 서버 초안(더하기 · 잇기 · 값 — ★값은 서버가 말씀에서 읽는다★) → 바뀐 점 묶음 + 캔버스 점선 유령 · 값이 바뀔 노드 표시
 *  · ★[받아들이기]만 반영★(짝: 그 전엔 문서 그대로) · 되돌리기 한 번이면 전부 원래대로
 *  · 값의 출처는 노드에 남아 설정 탭에 '말씀에서' 칩 — 그 칸을 고치면 사라진다(짝: 다른 칸 칩은 남음) · 새로고침·내보내기에 남는다
 *  · 캔버스(노드·선·설정)가 바뀌면 초안을 지우고 말한다(짝: 옮기기만은 그대로) · 미리보기 동안 규칙 유령은 숨는다
 *  · 이해 못 함·투자 판단은 서버 고정 문장 · 빈 것·빠진 것은 사유와 함께 · 못 보임 사유 · 로그아웃이면 로그인 링크(요청 0)
 *  · 이 환경의 실제 서버는 Claude 키가 없다 — 가로채지 않은 길은 '키 없음' 사유까지
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
/** 종목 → 수익률 → 추정 → 비중(과거로 돌려 보기는 아직 없음 — 규칙 유령이 그것을 권한다). */
const CORE = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 320, 0),
                             n("estimate", "estimate", 640, 0), n("optimizer", "optimizer", 960, 0)],
               edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
                       e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")] };
const DRAFT_URL = "**/api/v1/assist/canvas/draft";
const SENTENCE = "과거로 돌려 보기를 붙이고 5년 기준, 거래비용 0.3%로 해 줘";
const DRAFT = {
  summary: "과거로 돌려 보기를 붙이고 5년 기준으로 바꿔요",
  add: [{ ref: "b", id: "backtest", kind: "backtest", label: "과거로 돌려 보기" }],
  connect: [{ id: "optimizer.weights->backtest.weights", source: "optimizer", source_port: "weights", target: "backtest", target_port: "weights" },
            { id: "returns.returns->backtest.returns", source: "returns", source_port: "returns", target: "backtest", target_port: "returns" }],
  set: [{ node: "returns", field: "lookback_days", label: "기간", value: 1260, display: "5년", quote: "5년", read: "preset" },
        { node: "backtest", field: "cost_bps", label: "거래비용", value: 30, display: "0.3%", quote: "0.3%", read: "preset" }],
  empty: [] as unknown[],
};
const REJ = [{ op: "set", code: "ticker_ambiguous", reason: "여러 종목이 맞아요 — ‘삼성’: 삼성전자 · 삼성SDI. 이름을 정확히 말해 주세요" }];
const ok = (extra: Record<string, unknown> = {}) => ({
  available: true, source: "claude", model: "claude-opus-5-5", understood: true, cannot: null, draft: DRAFT, rejected: REJ,
  cached: false, usage: { input_tokens: 4200, output_tokens: 300, cost_usd: 0.0228, cost_note: null }, ...extra });
type Sent = { graph: { nodes: { id: string; params: Record<string, unknown> }[] }; sentence: string };
type Doc = { nodes: { id: string; type: string; params: Record<string, unknown>; said?: Record<string, string> }[]; edges: { id: string }[] };

const panel = (page: Page) => page.locator(".pg-say");
const text = (page: Page) => page.locator(".pg-say-text");
const sec = (page: Page, k: string) => panel(page).locator(`.pg-say-sec[data-sec="${k}"]`);
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const nodeOf = (d: Doc, id: string) => d.nodes.find((x) => x.id === id);

async function signIn(page: Page) {
  await page.addInitScript(() => { try { localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"); } catch { /* */ } });
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
    principal: { username: "alice", role: "analyst" }, must_change_password: false, password_changed_at: null } }));
}

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("ai4_seeded")) return;
      sessionStorage.setItem("ai4_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      localStorage.removeItem("alpha_pg_view");
      localStorage.removeItem("alpha_pg_left_tab");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
}

function answer(page: Page, body: object | ((route: Route, i: number) => Promise<void>)) {
  const seen: Sent[] = [];
  return page.route(DRAFT_URL, async (route) => {
    seen.push(route.request().postDataJSON());
    if (typeof body === "function") return body(route, seen.length - 1);
    await route.fulfill({ json: body });
  }).then(() => seen);
}

async function openTab(page: Page) {
  await page.locator('.pg-left-tab[data-tab="say"]').click();
  await expect(panel(page)).toBeVisible();
}

async function say(page: Page, words = SENTENCE) {
  await text(page).fill(words);
  await text(page).press("Enter");
}

test.use({ viewport: { width: 1440, height: 900 } });

test("탭 '말로' — 로그아웃이면 로그인 링크만 · 요청 0", async ({ page }) => {
  const seen = await answer(page, ok());
  await openWith(page, CORE);
  await expect(page.locator('.pg-left-tab[data-tab="say"]')).toHaveText("말로");
  await openTab(page);
  await expect(panel(page).locator(".pg-say-login")).toHaveAttribute("href", "/login");
  await expect(text(page)).toHaveCount(0);
  await page.waitForTimeout(300);
  expect(seen).toHaveLength(0);
});

test("보낸 것 = 지금 문서 + 말씀 · 답 → 바뀐 점 묶음(수) = 캔버스 유령·점선 · 값이 바뀔 노드 표시 · 출처 칩", async ({ page }) => {
  await signIn(page);
  const seen = await answer(page, ok());
  await openWith(page, CORE);
  await openTab(page);
  await say(page);
  await expect(panel(page).locator(".pg-say-result")).toBeVisible();
  expect(seen).toHaveLength(1);
  expect(seen[0].sentence).toBe(SENTENCE);
  expect(seen[0].graph.nodes.map((x) => x.id)).toEqual(["universe", "returns", "estimate", "optimizer"]);
  await expect(panel(page).locator(".pg-say-sent")).toContainText(SENTENCE);
  await expect(panel(page).locator(".pg-say-summary")).toHaveText(DRAFT.summary);
  await expect(sec(page, "add").locator(".pg-say-item")).toHaveCount(1);
  await expect(sec(page, "add")).toContainText("과거로 돌려 보기");
  await expect(sec(page, "connect").locator(".pg-say-item")).toHaveCount(2);
  await expect(sec(page, "set").locator(".pg-say-item")).toHaveCount(2);
  await expect(sec(page, "set").locator(".pg-say-item").first()).toContainText("기간");
  await expect(sec(page, "set").locator(".pg-say-item").first()).toContainText("5년");
  await expect(sec(page, "set").locator(".pg-said-chip").first()).toHaveText("말씀에서 ‘5년’");
  await expect(sec(page, "rejected").locator(".pg-say-item")).toHaveText([REJ[0].reason]);
  await expect(sec(page, "empty")).toHaveCount(0);                                  // 빈 것이 없으면 묶음도 없다
  // 캔버스 — 더할 노드 유령 하나 · 이을 선 점선 둘 · 값이 바뀔 지금 노드(수익률)만 표시(짝: 잇기만 하는 비중 계산은 아님)
  await expect(page.locator(".pg-draft-node")).toHaveCount(1);
  await expect(page.locator('.pg-draft-node[data-id="backtest"]')).toContainText("과거로 돌려 보기");
  await expect(page.locator(".pg-draft-wire")).toHaveCount(2);
  await expect(page.locator('.pg-draft-touched[data-node-id="returns"]')).toBeVisible();
  await expect(page.locator('.pg-draft-touched[data-node-id="optimizer"]')).toHaveCount(0);
  // PNG 검토에서 찾음: 더할 노드가 오른쪽 창 밑에 깔렸고, [받아들이기]는 왼쪽 창 아래로 밀려 스크롤해야 보였다.
  await page.waitForTimeout(400);
  const ghost = (await page.locator('.pg-draft-node[data-id="backtest"]').boundingBox())!;
  const side = (await page.locator(".pg-side").boundingBox())!;
  const pal = (await page.locator(".pg-palette").boundingBox())!;
  expect(ghost.x + ghost.width, "유령이 오른쪽 창 밑이 아니다").toBeLessThanOrEqual(side.x);
  expect(ghost.x, "유령이 왼쪽 창 밑이 아니다").toBeGreaterThanOrEqual(pal.x + pal.width);
  await expect(panel(page).locator(".pg-say-accept")).toBeInViewport();             // 스크롤하지 않고
  const acc = (await panel(page).locator(".pg-say-accept").boundingBox())!;
  expect(acc.y + acc.height).toBeLessThanOrEqual(pal.y + pal.height);
});

test("받아들이기 전엔 문서 그대로(짝) · [받아들이기] → 노드·선·값·출처가 한 번에 · Ctrl+Z 한 번에 전부 원래대로", async ({ page }) => {
  await signIn(page);
  await answer(page, ok());
  await openWith(page, CORE);
  await openTab(page);
  await say(page);
  await expect(page.locator(".pg-draft-node")).toHaveCount(1);
  let d = await wip(page);
  expect(d.nodes).toHaveLength(4);                                                   // ★짝★ 미리보기는 문서가 아니다
  expect(nodeOf(d, "returns")!.params).toEqual({});
  await panel(page).locator(".pg-say-accept").click();
  await expect(page.locator(".pg-node")).toHaveCount(5);
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(5);
  d = await wip(page);
  expect(nodeOf(d, "backtest")!.params).toEqual({ cost_bps: 30 });
  expect(nodeOf(d, "backtest")!.said).toEqual({ cost_bps: "0.3%" });
  expect(nodeOf(d, "returns")!.params).toEqual({ lookback_days: 1260 });
  expect(nodeOf(d, "returns")!.said).toEqual({ lookback_days: "5년" });
  expect(d.edges.map((x) => x.id)).toEqual(expect.arrayContaining(DRAFT.connect.map((c) => c.id)));
  await expect(page.locator(".pg-note")).toContainText("말씀대로");
  await expect(page.locator(".pg-draft-node")).toHaveCount(0);                        // 받아들이면 유령·목록은 걷힌다
  await expect(panel(page).locator(".pg-say-result")).toHaveCount(0);
  await page.locator(".react-flow__pane").click({ position: { x: 700, y: 120 } });
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(4);
  d = await wip(page);
  expect(nodeOf(d, "returns")!.params).toEqual({});
  expect(nodeOf(d, "returns")!.said).toBeUndefined();
  expect(d.edges).toHaveLength(4);
});

test("설정 탭의 '말씀에서' 칩 — 그 칸을 고치면 사라지고 다른 노드의 칩은 남는다(짝) · 새로고침·내보내기에 남는다", async ({ page }) => {
  await signIn(page);
  await answer(page, ok());
  await openWith(page, CORE);
  await openTab(page);
  await say(page);
  await panel(page).locator(".pg-say-accept").click();
  await expect(page.locator(".pg-node")).toHaveCount(5);
  const field = (f: string) => page.locator(`.pg-side .pg-basic-field[data-field="${f}"]`);
  await page.locator('.pg-node[data-node-id="returns"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await expect(field("lookback_days").locator(".pg-said")).toHaveText("말씀에서 ‘5년’");
  await field("lookback_days").locator(".pg-chip", { hasText: "3년" }).click();
  await expect(field("lookback_days").locator(".pg-said")).toHaveCount(0);
  await expect.poll(async () => nodeOf(await wip(page), "returns")!.said).toBeUndefined();
  await page.locator('.pg-node[data-node-id="backtest"]').click();                  // ★짝★ 다른 노드의 칩은 그대로
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await expect(field("cost_bps").locator(".pg-said")).toHaveText("말씀에서 ‘0.3%’");
  await page.waitForTimeout(400);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node")).toHaveCount(5, { timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();                     // 처음 열림은 맞추지 않는다 — 사람처럼 맞춤 단추로 전체를 본 뒤
  await page.locator('.pg-node[data-node-id="backtest"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await expect(field("cost_bps").locator(".pg-said")).toHaveText("말씀에서 ‘0.3%’");
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  const file = JSON.parse(readFileSync((await (await dl).path())!, "utf-8")) as Doc;
  expect(nodeOf(file, "backtest")!.said).toEqual({ cost_bps: "0.3%" });
  expect(nodeOf(file, "returns")!.said).toBeUndefined();
});

test("출처가 망가진 문서: 값은 그대로 두고 출처만 빼며 그렇게 말한다 · 값 없는 칸의 출처는 버린다(짝: 멀쩡한 출처는 남는다)", async ({ page }) => {
  const doc = { ...CORE, nodes: CORE.nodes.map((x) =>
    x.id === "returns" ? { ...x, params: { lookback_days: 1260 }, said: { lookback_days: 5 } }                 // 글이 아니다 — 망가짐
      : x.id === "optimizer" ? { ...x, said: { model: "위험 똑같이" } }                                      // 값 없는 칸의 출처
        : x.id === "universe" ? { ...x, said: { tickers: "삼성전자, SK하이닉스" } } : x) };                   // ★짝★ 멀쩡함
  await openWith(page, doc);
  await expect(page.locator(".pg-load-problems")).toContainText("노드 returns 의 ‘말씀에서’ 출처가 형식에 맞지 않아 뺐어요 — 값은 그대로예요.");
  await page.locator('.pg-node[data-node-id="universe"]').click();                  // 문서를 다시 쓰게 한 번 건드린다(고르기만 — 값은 그대로)
  await expect.poll(async () => nodeOf(await wip(page), "returns")!.said).toBeUndefined();
  const d = await wip(page);
  expect(nodeOf(d, "returns")!.params).toEqual({ lookback_days: 1260 });
  expect(nodeOf(d, "optimizer")!.said).toBeUndefined();
  expect(nodeOf(d, "universe")!.said).toEqual({ tickers: "삼성전자, SK하이닉스" });
});

test("[버리기] — 유령·목록이 사라지고 문서 그대로 · 미리보기 동안 숨었던 규칙 유령이 돌아온다", async ({ page }) => {
  await signIn(page);
  await answer(page, ok());
  await openWith(page, CORE);
  await expect(page.locator(".pg-ghost").first()).toBeVisible();                    // 규칙 유령(과거로 돌려 보기를 붙이자)
  await openTab(page);
  await say(page);
  await expect(page.locator(".pg-draft-node")).toHaveCount(1);
  await expect(page.locator(".pg-ghost")).toHaveCount(0);                            // 미리보기 동안은 초안만
  await panel(page).locator(".pg-say-discard").click();
  await expect(page.locator(".pg-draft-node")).toHaveCount(0);
  await expect(panel(page).locator(".pg-say-result")).toHaveCount(0);
  await expect(page.locator(".pg-ghost").first()).toBeVisible();                    // ★짝★ 돌아온다
  expect((await wip(page)).nodes).toHaveLength(4);
});

test("캔버스가 바뀌면 초안을 지우고 말한다 — 짝: 노드를 옮기기만 하면 그대로", async ({ page }) => {
  await signIn(page);
  await answer(page, ok());
  await openWith(page, CORE);
  await openTab(page);
  await say(page);
  await expect(page.locator(".pg-draft-node")).toHaveCount(1);
  const b = (await page.locator('.react-flow__node[data-id="estimate"]').boundingBox())!;
  await page.mouse.move(b.x + b.width / 2, b.y + 14);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2 + 30, b.y + 64, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  await expect(page.locator(".pg-draft-node")).toHaveCount(1);                       // ★짝★ 옮기기만은 그대로
  await page.locator('.pg-node[data-node-id="optimizer"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-side .pg-basic-field[data-field="constraints"] .pg-chip', { hasText: "20%" }).click();
  await expect(page.locator(".pg-draft-node")).toHaveCount(0);
  await expect(panel(page).locator(".pg-say-note")).toHaveText("캔버스가 바뀌어 초안을 지웠어요 — 다시 말해 주세요");
  await expect(panel(page).locator(".pg-say-accept")).toHaveCount(0);
});

test("이해 못 함·투자 판단은 서버 고정 문장 · 받아들일 것이 없다 / 빈 것·빠진 것은 사유와 함께", async ({ page }) => {
  await signIn(page);
  const cannot = "어떤 종목이 좋을지는 말하지 않아요 — 말씀대로 설계만 지어요";
  const empty = { summary: null, add: [], connect: [], set: [], empty: [] };
  await answer(page, async (route, i) => route.fulfill({ json: i === 0
    ? ok({ understood: false, cannot, draft: empty, rejected: [] })
    : ok({ draft: { ...DRAFT, connect: DRAFT.connect.slice(0, 1),
                    empty: [{ node: "backtest", port: "returns", why: "‘과거로 돌려 보기’가 받을 ‘수익률’을 내는 노드가 없어요" }] } }) }));
  await openWith(page, CORE);
  await openTab(page);
  await say(page, "무슨 종목을 살까?");
  await expect(panel(page).locator(".pg-say-cannot")).toHaveText(cannot);
  await expect(panel(page).locator(".pg-say-accept")).toHaveCount(0);
  await expect(page.locator(".pg-draft-node")).toHaveCount(0);
  await say(page);
  await expect(sec(page, "empty").locator(".pg-say-item")).toHaveText(["‘과거로 돌려 보기’가 받을 ‘수익률’을 내는 노드가 없어요"]);
  await expect(sec(page, "rejected").locator(".pg-say-item")).toHaveCount(1);
  await expect(panel(page).locator(".pg-say-accept")).toBeVisible();
});

test("못 보이면 사유 — 미리보기·문서는 그대로", async ({ page }) => {
  await signIn(page);
  await answer(page, { available: false, source: "unavailable", reason_code: "rate_limited", reason: "한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요" });
  await openWith(page, CORE);
  await openTab(page);
  await say(page);
  await expect(panel(page).locator(".pg-say-note")).toHaveText("초안을 보여 줄 수 없어요: 한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요");
  await expect(page.locator(".pg-draft-node")).toHaveCount(0);
  expect((await wip(page)).nodes).toHaveLength(4);
});

test("가로채지 않은 실제 서버: 실제 문서·말씀 → 서버 형식 검사 통과(422 아님) → 키 없음 사유", async ({ page }) => {
  const login = await page.request.post("/api/backend/api/v1/auth/login", { data: { username: "admin", password: "frm123!" } });
  expect(login.ok(), await login.text()).toBe(true);
  const token = (await login.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  await openWith(page, CORE);
  await openTab(page);
  const res = page.waitForResponse((r) => r.url().includes("/assist/canvas/draft"));
  await say(page);
  const r = await res;
  expect(r.status()).toBe(200);
  expect(await r.json()).toMatchObject({ available: false, reason_code: "no_key" });
  await expect(panel(page).locator(".pg-say-note")).toHaveText("초안을 보여 줄 수 없어요: 서버에 Claude 키가 없어요");
});

test("Ctrl+K '말로 설계' → 왼쪽 창 '말로' 탭 + 입력에 초점", async ({ page }) => {
  await signIn(page);
  await openWith(page, CORE);
  await expect(panel(page)).toHaveCount(0);
  await page.locator(".react-flow__pane").click({ position: { x: 700, y: 120 } });
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("말로 설계");
  await page.keyboard.press("Enter");
  await expect(panel(page)).toBeVisible();
  await expect(text(page)).toBeFocused();
});

for (const scheme of ["light", "dark"] as const) {
  test(`말로 탭 대비(${scheme}) AA`, async ({ page }) => {
    await signIn(page);
    await answer(page, ok());
    await openWith(page, CORE);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await openTab(page);
    await say(page);
    await expect(panel(page).locator(".pg-say-result")).toBeVisible();
    const a = await page.evaluate<AuditResult>(contrastAudit(".pg-say"));
    expect(a.checked).toBeGreaterThanOrEqual(10);
    expect(a.low, scheme).toEqual([]);
    const g = await page.evaluate<AuditResult>(contrastAudit(".pg-draft-node"));
    expect(g.low, `${scheme} 유령`).toEqual([]);
  });
}

test.describe("좁은 화면(390)", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("왼쪽 창을 열어 '말로' 탭 — 칸·단추가 화면 안 · 받아들이기까지", async ({ page }) => {
    await signIn(page);
    await answer(page, ok());
    await openWith(page, CORE);
    await page.locator(".pg-palette-fab").click();
    await openTab(page);
    await say(page);
    await expect(panel(page).locator(".pg-say-accept")).toBeInViewport();             // 결과가 길어도 단추는 시트 맨 아래에 붙어 보인다
    for (const loc of [text(page), panel(page).locator(".pg-say-accept")]) {
      await loc.scrollIntoViewIfNeeded();
      const b = (await loc.boundingBox())!;
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width).toBeLessThanOrEqual(390);
    }
    await panel(page).locator(".pg-say-accept").click();
    await expect.poll(async () => (await wip(page)).nodes.length).toBe(5);
  });
});

test.describe("두 창을 연 1024", () => {
  test.use({ viewport: { width: 1024, height: 768 } });
  test("'말로' 탭이 왼쪽 창 안 — 입력과 단추가 창 폭 안", async ({ page }) => {
    await signIn(page);
    await answer(page, ok());
    await openWith(page, CORE);
    await openTab(page);
    await say(page);
    const pal = (await page.locator(".pg-palette").boundingBox())!;
    await expect(panel(page).locator(".pg-say-accept")).toBeInViewport();
    for (const loc of [text(page), panel(page).locator(".pg-say-accept"), panel(page).locator(".pg-say-discard")]) {
      await loc.scrollIntoViewIfNeeded();
      const b = (await loc.boundingBox())!;
      expect(b.x).toBeGreaterThanOrEqual(pal.x - 1);
      expect(b.x + b.width).toBeLessThanOrEqual(pal.x + pal.width + 1);
    }
  });
});
