import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * AI1 · 'AI 추천' 유령 — 서버 `POST /api/v1/assist/canvas/suggest`(AI0, 로그인)의 답을 CF6 유령 자리에(스펙 §AI1, 사용자 결정 2026-10-22)
 *  · ★누를 때만 부른다★ — 아래 바의 [AI 추천 받기] · Ctrl+K "AI 에게 다음 노드 묻기". 로그아웃이면 단추 대신 로그인 안내, 요청 0
 *  · AI 유령 = "AI 추천" 칩 + 서버가 검사를 통과시킨 이유 한 줄 · 규칙 추천과 같은 것은 ★유령 하나에 두 칩★ · 붙이기·닫기·자리는 CF6 그대로
 *  · 못 보일 때는 서버 사유를 그대로 말한다(규칙 유령은 남는다) · 검사에서 빠진 것은 수와 사유를 말한다 — 바 안의 상태 줄(`.pg-ai-note`).
 *    토스트가 아닌 까닭: 토스트는 닫을 때까지 아래 바를 가려 다시 묻기 단추까지 숨긴다(이 스펙의 첫 초록 시도가 찾음)
 *  · 답의 AI 유령이 오른쪽 창 밑·화면 밖이면 그쪽으로 옮겨 보인다 — 깔리면 [붙이기]를 누를 수 없다
 *  · ★그래프 구조가 바뀌면 AI 유령을 지운다★(물을 때의 그래프에 대한 답이다) — 짝: 노드를 옮기기만 하면 남는다
 *  · 이 환경의 실제 서버는 Claude 키가 없다 — 가로채지 않은 길도 끝까지(인증·프록시·경로·사유 문장) 한 번 돈다
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
/** 종목 → 수익률 → 비중: 규칙 유령 둘(next = 기대 수익 추정 · 비용·표본외 = 과거로 돌려 보기). */
const CHAIN = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 320, 0),
                              n("optimizer", "optimizer", 640, 0, { model: "risk_parity" })],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns")] };

type Edge = { source: string; source_port: string; target: string; target_port: string };
type Sug = { action: string; kind: string | null; label: string | null; text: string; attach: Edge[] };
type Proc = { next: Sug | null; by_gate: Record<string, Sug | null> };
type Doc = { nodes: { id: string; type: string; position: { x: number; y: number } }[]; edges: Edge[] };
const SUGGEST = "**/api/v1/assist/canvas/suggest";
const RISK = { action: "add", kind: "risk", label: "흔들림 나눠 보기", reason: "비중이 어디에서 흔들리는지 나눠 볼 수 있어요.",
               attach: [{ source: "optimizer", source_port: "weights", target: "@new", target_port: "weights" }] };
const ok = (suggestions: object[], rejected: object[] = []) => ({
  available: true, source: "claude", model: "claude-opus-5-5", suggestions, rejected, cached: false,
  usage: { input_tokens: 1200, output_tokens: 300, cost_usd: 0.0108, cost_note: null } });
const unavailable = (code: string, reason: string) => ({ available: false, source: "unavailable", reason_code: code, reason, rule: null });

const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const aiGhosts = (page: Page) => page.locator('.pg-ghost[data-source="claude"]');
const ask = (page: Page) => page.locator(".pg-ai-ask");

/** 가짜 로그인 — 토큰을 두고 `/auth/me` 가 이름을 준다(경로 응답은 테스트마다 가로챈다). */
async function signIn(page: Page) {
  await page.addInitScript(() => { try { localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"); } catch { /* */ } });
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
    principal: { username: "alice", role: "analyst" }, must_change_password: false, password_changed_at: null } }));
}

/** 문서를 심고 열어 첫 검증 응답(절차)을 돌려준다. */
async function openWith(page: Page, doc: object): Promise<Proc> {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("ai1_seeded")) return;
      sessionStorage.setItem("ai1_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      localStorage.removeItem("alpha_pg_view");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  const validated = page.waitForResponse((r) => r.url().includes("/allocation/graph/validate") && r.request().method() === "POST");
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  const body = await (await validated).json();
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(300);
  return body.procedure as Proc;
}

/** 묻기 경로를 가로챈다 — 받은 요청 본문을 모은다. */
function answer(page: Page, body: object | ((route: Route) => Promise<void>), status = 200) {
  const seen: Doc[] = [];
  return page.route(SUGGEST, async (route) => {
    seen.push(route.request().postDataJSON() as Doc);
    if (typeof body === "function") return body(route);
    await route.fulfill({ status, json: body });
  }).then(() => seen);
}

const overlaps = (a: { x: number; y: number; width: number; height: number }, b: { x: number; y: number; width: number; height: number }) =>
  a.x < b.x + b.width - 1 && a.x + a.width > b.x + 1 && a.y < b.y + b.height - 1 && a.y + a.height > b.y + 1;

test.use({ viewport: { width: 1440, height: 900 } });

test("로그아웃이면 단추 대신 로그인 안내 · Ctrl+K 로 물어도 요청 0 — 짝: 로그인하면 단추가 있고 Ctrl+K 가 묻는다", async ({ page, context }) => {
  const sent: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/assist/canvas/suggest")) sent.push(r.url()); });
  await openWith(page, CHAIN);
  await expect(page.locator(".pg-ai-login")).toHaveText("로그인하면 AI 추천");
  await expect(page.locator(".pg-ai-login")).toHaveAttribute("href", "/login");
  await expect(ask(page)).toHaveCount(0);
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("AI 에게");
  await expect(page.locator('.pg-cmd-item[data-cmd="ai-ask"]')).toContainText("AI 에게 다음 노드 묻기");
  await page.keyboard.press("Enter");
  await expect(page.locator(".pg-note")).toContainText("로그인하면 AI 추천을 받을 수 있어요");
  await page.waitForTimeout(500);
  expect(sent, "로그아웃인데 물었다").toEqual([]);

  const other = await context.newPage();                                             // ★짝★
  await signIn(other);
  const seen = await answer(other, ok([RISK]));
  await openWith(other, CHAIN);
  await expect(ask(other)).toHaveText("AI 추천 받기");
  await expect(other.locator(".pg-ai-login")).toHaveCount(0);
  await other.keyboard.press("Control+k");
  await other.getByLabel("명령 찾기").last().fill("AI 에게");
  await other.keyboard.press("Enter");
  await expect(aiGhosts(other)).toHaveCount(1);
  expect(seen).toHaveLength(1);
});

test("누르면 묻는 중 → 'AI 추천' 유령과 이유 · 요청 본문은 지금 문서 · 규칙 유령은 그대로 · 카드·유령과 겹치지 않는다", async ({ page }) => {
  await signIn(page);
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  const seen = await answer(page, async (route) => { await gate; await route.fulfill({ json: ok([RISK]) }); });
  await openWith(page, CHAIN);
  await expect(page.locator('.pg-ghost[data-source="rule"]')).toHaveCount(2);
  await ask(page).click();
  await expect(ask(page)).toHaveText("AI 추천을 묻는 중이에요");
  await expect(ask(page)).toBeDisabled();
  release();
  await expect(aiGhosts(page)).toHaveCount(1);
  const g = aiGhosts(page);
  await expect(g).toHaveAttribute("data-kind", "risk");
  await expect(g.locator(".pg-ghost-chip--ai")).toHaveText("AI 추천");
  await expect(g.locator(".pg-ghost-chip")).toHaveCount(1);                         // 규칙 칩은 없다
  await expect(g.locator(".pg-ghost-text")).toHaveText(RISK.reason);
  await expect(g.locator(".pg-ghost-name")).toHaveText("흔들림 나눠 보기");
  expect(await g.getAttribute("aria-label")).toMatch(/^AI 추천: /);
  await expect(page.locator('.pg-ghost-wire[data-to="risk"][data-from="optimizer"]')).toHaveCount(1);
  await expect(page.locator('.pg-ghost[data-source="rule"]')).toHaveCount(2);         // 규칙 유령은 그대로
  await expect(page.locator(".pg-ai-note")).toHaveText("AI 추천 1개를 보였어요.");
  await expect(ask(page)).toBeEnabled();
  expect(seen).toHaveLength(1);
  expect(seen[0].nodes.map((x) => x.id).sort()).toEqual(["optimizer", "returns", "universe"]);
  expect(seen[0].edges).toHaveLength(2);
  const cards = await Promise.all((await page.locator(".react-flow__node").all()).map((x) => x.boundingBox()));
  const gb = (await g.boundingBox())!;
  for (const c of cards) expect(overlaps(gb, c!), "AI 유령이 카드와 겹친다").toBe(false);
  for (const r of await page.locator('.pg-ghost[data-source="rule"]').all()) expect(overlaps(gb, (await r.boundingBox())!), "AI 유령이 규칙 유령과 겹친다").toBe(false);
  expect((await wip(page)).nodes).toHaveLength(3);                                    // 문서가 아니다
});

test("규칙과 같은 AI 추천은 유령 하나에 두 칩 — 규칙 글 + AI 이유 · 짝: 다른 추천은 따로", async ({ page }) => {
  await signIn(page);
  await answer(page, async (route) => route.fulfill({ json: ok([BT_SAME, RISK]) }));
  const proc = await openWith(page, CHAIN);
  const rule = proc.by_gate.cost!;
  BT_SAME.attach = [...rule.attach].reverse();                                         // 잇는 선 순서가 달라도 같은 추천
  await ask(page).click();
  await expect(aiGhosts(page)).toHaveCount(1);                                         // AI 만 = 흔들림 나눠 보기
  const both = page.locator('.pg-ghost[data-kind="backtest"]');
  await expect(both).toHaveCount(1);
  await expect(both).toHaveAttribute("data-source", "rule claude");
  await expect(both.locator(".pg-ghost-chip")).toHaveText(["규칙 추천", "AI 추천"]);
  await expect(both.locator(".pg-ghost-text")).toHaveText(rule.text);
  await expect(both.locator(".pg-ghost-reason")).toContainText(BT_SAME.reason);
  await expect(page.locator(".pg-ghost")).toHaveCount(3);                              // 규칙 둘 + AI 만 하나
  await expect(page.locator('.pg-ghost[data-kind="risk"]')).toHaveAttribute("data-source", "claude");
});
const BT_SAME: { action: string; kind: string; label: string; reason: string; attach: Edge[] } = {
  action: "add", kind: "backtest", label: "과거로 돌려 보기", reason: "거래비용을 넣어 과거로 돌려 볼 수 있어요.", attach: [] };

test("AI 유령 [붙이기] → 유령이 보인 자리에 진짜 노드 + 추천 선 · 되돌리기 한 번에 원래", async ({ page }) => {
  await signIn(page);
  await answer(page, ok([RISK]));
  await openWith(page, CHAIN);
  await ask(page).click();
  const g = aiGhosts(page);
  await expect(g).toHaveCount(1);
  const at = { x: Number(await g.getAttribute("data-x")), y: Number(await g.getAttribute("data-y")) };
  await g.locator(".pg-ghost-add").click();
  await expect(page.locator(".pg-note")).toContainText("흔들림 나눠 보기");
  const doc = await wip(page);
  const made = doc.nodes.find((x) => x.type === "risk")!;
  expect(made.position).toEqual(at);
  expect(doc.edges.some((x) => x.source === "optimizer" && x.source_port === "weights" && x.target === made.id && x.target_port === "weights")).toBe(true);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(3);
});

test("못 보일 때는 서버 사유를 그대로 말한다 · AI 유령 0 · 규칙 유령은 남는다", async ({ page }) => {
  await signIn(page);
  await answer(page, unavailable("rate_limited", "한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요"));
  await openWith(page, CHAIN);
  await ask(page).click();
  await expect(page.locator(".pg-ai-note")).toHaveText("AI 답을 보여 줄 수 없어요: 한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요");
  await expect(aiGhosts(page)).toHaveCount(0);
  await expect(page.locator('.pg-ghost[data-source="rule"]')).toHaveCount(2);
  await expect(ask(page)).toHaveText("AI 추천 받기");
});

test("로그인이 끝났으면(401) 그렇게 말한다 — 이름을 지어내거나 조용히 숨기지 않는다", async ({ page }) => {
  await signIn(page);
  await answer(page, { detail: "인증이 필요합니다" }, 401);
  await openWith(page, CHAIN);
  await ask(page).click();
  await expect(page.locator(".pg-ai-note")).toContainText("AI 답을 보여 줄 수 없어요: 로그인이 끝났어요");
  await expect(aiGhosts(page)).toHaveCount(0);
});

test("검사에서 빠진 AI 추천은 수와 사유를 말한다 — 통과한 것만 유령 · 모두 빠지면 그렇게", async ({ page }) => {
  await signIn(page);
  const bad = { kind: "magic", code: "unknown_kind", reason: "카탈로그에 없는 종류 ‘magic’예요" };
  let reply: object = ok([RISK], [bad]);
  await answer(page, async (route) => route.fulfill({ json: reply }));
  await openWith(page, CHAIN);
  await ask(page).click();
  await expect(page.locator(".pg-ai-note")).toHaveText("AI 추천 1개를 보였어요 · 1개는 검사에서 빠졌어요: 카탈로그에 없는 종류 ‘magic’예요");
  await expect(aiGhosts(page)).toHaveCount(1);
  reply = ok([], [bad, { kind: "risk", code: "numbers", reason: "근거에 없는 숫자 0.3 를 썼어요" }]);
  await expect(ask(page)).toBeVisible();                                              // 상태 줄이 단추를 가리지 않는다
  await ask(page).click();
  await expect(page.locator(".pg-ai-note")).toHaveText("AI 추천 2개는 검사에서 빠졌어요: 카탈로그에 없는 종류 ‘magic’예요");
  await expect(aiGhosts(page)).toHaveCount(0);                                         // 다시 물으면 새 답으로 바꾼다
});

test("그래프 구조가 바뀌면 AI 유령을 지우고 말한다 — 짝: 노드를 옮기기만 하면 남는다", async ({ page }) => {
  await signIn(page);
  await answer(page, ok([RISK]));
  await openWith(page, CHAIN);
  await ask(page).click();
  await expect(aiGhosts(page)).toHaveCount(1);
  await page.locator(".react-flow__controls-fitview").click();                       // 답 쪽으로 옮겨 보였으니 다시 전체를
  await page.waitForTimeout(400);
  // ★짝★ 옮기기 — 구조는 같다.
  const b = (await page.locator('.react-flow__node[data-id="universe"]').boundingBox())!;
  await page.mouse.move(b.x + 30, b.y + 14);
  await page.mouse.down();
  await page.mouse.move(b.x + 60, b.y + 120, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(800);
  await expect(aiGhosts(page)).toHaveCount(1);
  await expect(page.locator(".pg-ai-stale")).toHaveCount(0);
  // 구조가 바뀐다 — 규칙 next(기대 수익 추정)를 붙인다.
  await page.locator('.pg-ghost[data-kind="estimate"] .pg-ghost-add').click();
  await expect(aiGhosts(page)).toHaveCount(0);
  await expect(page.locator(".pg-ai-stale")).toHaveText("그래프가 바뀌어 AI 추천을 지웠어요");
  await expect(ask(page)).toHaveText("다시 묻기");
});

test("가로채지 않은 실제 서버: 로그인 → 경로·프록시·인증 끝까지 · E2E 서버는 Claude 키 없이 돈다(실제 호출 0)", async ({ page }) => {
  const login = await page.request.post("/api/backend/api/v1/auth/login", { data: { username: "admin", password: "frm123!" } });
  expect(login.ok(), await login.text()).toBe(true);
  const token = (await login.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  await openWith(page, CHAIN);
  const res = page.waitForResponse((r) => r.url().includes("/assist/canvas/suggest"));
  await ask(page).click();
  const body = await (await res).json();
  expect(body).toMatchObject({ available: false, source: "unavailable", reason_code: "no_key" });
  await expect(page.locator(".pg-ai-note")).toHaveText("AI 답을 보여 줄 수 없어요: 서버에 Claude 키가 없어요");
  await expect(aiGhosts(page)).toHaveCount(0);
  await expect(page.locator('.pg-ghost[data-source="rule"]')).toHaveCount(2);
});

for (const scheme of ["light", "dark"] as const) {
  test(`AI 유령·묻기 단추 대비(${scheme}) AA`, async ({ page }) => {
    await signIn(page);
    await answer(page, async (route) => route.fulfill({ json: ok([BT_SAME, RISK]) }));
    const proc = await openWith(page, CHAIN);
    BT_SAME.attach = proc.by_gate.cost!.attach;
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await ask(page).click();
    await expect(page.locator(".pg-ghost")).toHaveCount(3);
    const a = await page.evaluate<AuditResult>(contrastAudit(".pg-ghosts"));
    expect(a.checked).toBeGreaterThanOrEqual(12);
    expect(a.low, scheme).toEqual([]);
    const bar = await page.evaluate<AuditResult>(contrastAudit(".pg-next"));
    expect(bar.low, scheme).toEqual([]);
  });
}

test.describe("좁은 화면(390)", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("묻기 단추가 화면 안에 있고 진짜로 눌린다", async ({ page }) => {
    await signIn(page);
    await answer(page, ok([RISK]));
    await openWith(page, CHAIN);
    const b = (await ask(page).boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(0);
    expect(b.x + b.width).toBeLessThanOrEqual(390);
    await ask(page).click();
    await expect(aiGhosts(page)).toHaveCount(1);
  });
});
