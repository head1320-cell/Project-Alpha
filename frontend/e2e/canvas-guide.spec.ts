import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * AI5 · 길잡이 — 캔버스 도구를 쓰게 이끄는 코치(스펙 §AI5 설계, 사용자 결정 2026-10-23: 규칙 줄 + 누르면 AI)
 *  · 아래 바 세 번째 자리(환영 > 다음 한 걸음 > ★길잡이★ > 기본 안내) — 노드가 있고, 다음 한 걸음이 없고, 아무것도 고르지 않았을 때
 *  · 규칙 줄: 칩 "규칙 길잡이" · 왜 한 줄 · [해 보기](그 도구를 실제로 실행 + ★다음엔 어디서 하나★) · [다음에](이번 방문 동안 숨김 → 다음 도구)
 *  · [AI 길잡이](로그인 · 누를 때만): Claude 가 적용되는 도구 중 1~2 · 넘기기 · 상태가 바뀌면 AI 줄을 지우고 규칙 줄로(말함) · 못 보이면 사유(규칙 줄은 남음)
 *  · 도구 안내만 — 투자 판단 없음(서버가 검사) · 이 환경의 실제 서버는 키가 없다 — 가로채지 않은 길도 한 번(`no_key`)
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
/** 절차를 다 채운 흐름(다음 한 걸음 없음): 종목 → 수익률 → 추정 → 비중 → 백테스트 · 위험. 계산하면 선 하나에 '빠지거나 바뀐 것'이 있다. */
const FULL = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 320, 0),
                             n("estimate", "estimate", 640, 0), n("optimizer", "optimizer", 960, 0), n("backtest", "backtest", 1280, 0),
                             n("risk", "risk", 1600, 0)],
               edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
                       e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief"),
                       e("optimizer", "weights", "backtest", "weights"), e("returns", "returns", "backtest", "returns"),
                       e("optimizer", "weights", "risk", "weights")] };
/** 다음 한 걸음이 있는 흐름(기대 수익 추정이 빠짐). */
const CHAIN = { ...F, nodes: FULL.nodes.slice(0, 2).concat([n("optimizer", "optimizer", 640, 0, { model: "risk_parity" })]),
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns")] };
const GUIDE = "**/api/v1/assist/canvas/guide";
type Sent = { state: Record<string, unknown>; applicable: string[] };

const bar = (page: Page) => page.locator(".pg-guidebar");
const why = (page: Page) => page.locator(".pg-guide-why");

async function signIn(page: Page) {
  await page.addInitScript(() => { try { localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"); } catch { /* */ } });
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
    principal: { username: "alice", role: "analyst" }, must_change_password: false, password_changed_at: null } }));
}

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("guide_seeded")) return;
      sessionStorage.setItem("guide_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      localStorage.removeItem("alpha_pg_view");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(500);
}

async function runAll(page: Page) {
  const res = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await res;
  await expect(page.locator(".pg-run")).toHaveText("계산하기", { timeout: 120_000 });
  await page.waitForTimeout(300);
}

function answer(page: Page, body: object | ((route: Route) => Promise<void>)) {
  const seen: Sent[] = [];
  return page.route(GUIDE, async (route) => {
    seen.push(route.request().postDataJSON() as Sent);
    if (typeof body === "function") return body(route);
    await route.fulfill({ json: body });
  }).then(() => seen);
}
const ok = (tips: { feature: string; label: string; why: string }[]) => ({
  available: true, source: "claude", model: "claude-opus-5-5", tips, rejected: [], cached: false,
  usage: { input_tokens: 600, output_tokens: 80, cost_usd: 0.004, cost_note: null } });

test.use({ viewport: { width: 1440, height: 900 } });

test("계산 전 · 절차를 다 채움 → 규칙 길잡이 '계산하기' · [해 보기]가 실제로 계산하고 다음엔 어디서 하는지 말한다", async ({ page }) => {
  await openWith(page, FULL);
  await expect(bar(page)).toHaveAttribute("data-tool", "run");
  await expect(bar(page).locator(".pg-guide-chip")).toHaveText("규칙 길잡이");
  await expect(why(page)).toHaveText("절차를 다 채웠어요 — 계산하면 노드마다 결과와 설명이 나와요");
  const res = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await bar(page).locator(".pg-guide-go").click();
  await res;
  await expect(page.locator(".pg-note")).toContainText("다음엔 Ctrl+Enter 로도 계산해요");
});

test("계산 뒤 우선순위: 전달 점검 보기 → [다음에] → 갈래 만들기 → [다음에] → 전략 더하기 · 해 보기는 그 도구를 연다", async ({ page }) => {
  await openWith(page, FULL);
  await runAll(page);
  await expect(bar(page)).toHaveAttribute("data-tool", "wire_check");
  await expect(why(page)).toHaveText("빠지거나 바뀐 것이 있는 선이 1개예요 — 무엇이 빠졌는지 볼 수 있어요");
  await bar(page).locator(".pg-guide-go").click();
  await page.mouse.move(700, 300);                                                              // 안내 위에 머물면 닫히지 않는다(설계) — 사람처럼 옮긴다
  await expect(page.locator('.pg-tab[data-tab="wire"]')).toHaveAttribute("aria-selected", "true");      // 그 선을 골라 '선' 탭
  await expect(page.locator(".pg-wire-issue")).toHaveCount(1);
  await expect(page.locator(".pg-note")).toContainText("다음엔 선을 눌러 오른쪽 창 ‘선’ 탭에서 봐요");
  // '다음엔 어디서' 는 알림일 뿐 — 스스로 닫힌다(토스트는 아래 바를 가린다: 닫히지 않으면 길잡이가 사라진 채 남았다)
  await expect(page.locator(".pg-note")).toHaveCount(0, { timeout: 12_000 });
  await page.locator(".react-flow__pane").click({ position: { x: 700, y: 650 } });
  await expect(bar(page)).toHaveAttribute("data-tool", "wire_check");
  await bar(page).locator(".pg-guide-later").click();
  await expect(bar(page)).toHaveAttribute("data-tool", "branch");
  await expect(why(page)).toHaveText("설정을 바꾼 설계를 나란히 비교할 수 있어요");
  await bar(page).locator(".pg-guide-later").click();
  await expect(bar(page)).toHaveAttribute("data-tool", "strategy_add");
  await bar(page).locator(".pg-guide-go").click();
  await expect(page.locator(".pg-strat-menu")).toBeVisible();                                    // 무엇을 더할지는 사람이 고른다
});

test("갈래 만들기 [해 보기] → 갈래가 생기고 되돌리기 한 번이면 사라진다 · 안내 줄에 다음엔 어디서", async ({ page }) => {
  await openWith(page, FULL);
  await runAll(page);
  await bar(page).locator(".pg-guide-later").click();                                             // 전달 점검 건너뛰기
  await expect(bar(page)).toHaveAttribute("data-tool", "branch");
  const before = await page.locator(".pg-node").count();
  await bar(page).locator(".pg-guide-go").click();
  await expect.poll(() => page.locator(".pg-node").count()).toBeGreaterThan(before);
  await expect(page.locator(".pg-note")).toContainText("다음엔 노드를 고르고 Ctrl+K ‘갈래’로도 돼요");
  await page.keyboard.press("Control+z");
  await expect.poll(() => page.locator(".pg-node").count()).toBe(before);
});

// 길잡이 바는 단추가 있어 기본 안내보다 높다(48 + 아래 18) — 맞춰 보기의 아래 여백 64 를 넘어 가장 아래 노드의 끝을 덮었다(전체 게이트가 찾음:
// canvas-workspace '맞춰 보기' 1136 > 1127). 맞춰 보기는 ★보이는 아래 바의 실제 위 끝★까지 비운다. 세로로 긴 흐름이라 높이로 맞춰진다(틈 = 비운 만큼).
test("맞춰 보기는 길잡이 바를 비운다 — 가장 아래 노드가 바 위 · 짝: 바 위 틈은 작다(큰 상수로 비우지 않는다)", async ({ page }) => {
  // 카드가 겹치지 않을 만큼 띄우고(비중 계산 카드 ≈ 490) · 가장 작게(0.2) 줄이기 전에 높이로 다 담기는 창(넘치면 맞춤이 왼쪽 위에 붙인다 — 다른 규칙).
  await page.setViewportSize({ width: 1440, height: 1200 });
  const TALL = { ...FULL, nodes: FULL.nodes.map((x, i) => ({ ...x, position: { x: 0, y: i * 640 } })) };
  await openWith(page, TALL);
  await expect(bar(page)).toHaveAttribute("data-tool", "run");
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(400);
  await expect(bar(page)).toBeVisible();                                       // 카드가 겹치지 않는 문서 — '겹쳐요' 토스트가 바를 가리지 않는다
  const b = (await bar(page).boundingBox())!;
  const bottom = await page.locator(".react-flow__node:not([style*='visibility: hidden'])").evaluateAll((els) =>
    Math.max(...els.filter((x) => (x as HTMLElement).offsetParent !== null).map((x) => x.getBoundingClientRect().bottom)));
  expect(bottom, "가장 아래 노드가 길잡이 바 위").toBeLessThanOrEqual(b.y);
  expect(b.y - bottom, "높이로 맞춘 흐름 — 바 위 틈은 작다").toBeLessThanOrEqual(24);
});

test("길잡이가 숨는 때: 다음 한 걸음이 있으면(짝: 없으면 보임) · 노드를 고르면 · 빈 캔버스", async ({ page }) => {
  await openWith(page, CHAIN);
  await expect(page.locator(".pg-next")).toBeVisible();
  await expect(bar(page)).toHaveCount(0);
  await page.locator(".pg-next-later").click();                                          // 다음 한 걸음을 넘기면 길잡이 자리
  await expect(bar(page)).toBeVisible();
  await expect(page.locator(".pg-next")).toHaveCount(0);       // 길잡이는 '다음 한 걸음'이 아니다 — `.pg-next` 계약을 빌리지 않는다
  await expect(page.locator(".pg-guide")).toHaveCount(0);      // CF4a 맞춤 안내선(.pg-guide)과 이름이 겹치지 않는다
  await page.locator('.pg-node[data-node-id="returns"]').click();
  await expect(bar(page)).toHaveCount(0);
  await page.locator(".react-flow__pane").click({ position: { x: 700, y: 650 } });
  await expect(bar(page)).toBeVisible();
  await page.evaluate(() => { sessionStorage.setItem("alpha_pg_wip", JSON.stringify({ format: "project-alpha.portfolio-graph", version: 1, nodes: [], edges: [] })); });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  await expect(bar(page)).toHaveCount(0);
});

test("AI 길잡이: 상태·적용 도구를 보내고 · 답(2개 중 1 · 넘기기) · 상태가 바뀌면 지우고 규칙 줄로 · 로그아웃이면 로그인 링크", async ({ page }) => {
  await signIn(page);
  const seen = await answer(page, ok([
    { feature: "branch", label: "갈래 만들기", why: "계산을 마쳤고 갈래가 없어요. 설정을 바꾼 설계를 나란히 볼 수 있어요." },
    { feature: "records", label: "기록함", why: "과거로 돌려 본 기록을 모아 볼 수 있어요." }]));
  await openWith(page, FULL);
  await runAll(page);
  await bar(page).locator(".pg-guide-ai").click();
  await expect(bar(page).locator(".pg-guide-chip")).toHaveText("AI 길잡이");
  await expect(bar(page)).toHaveAttribute("data-tool", "branch");
  await expect(why(page)).toHaveText("계산을 마쳤고 갈래가 없어요. 설정을 바꾼 설계를 나란히 볼 수 있어요.");
  await expect(bar(page).locator(".pg-guide-more")).toHaveText("2개 중 1 · 다음");
  await bar(page).locator(".pg-guide-more").click();
  await expect(bar(page)).toHaveAttribute("data-tool", "records");
  expect(seen).toHaveLength(1);
  expect(seen[0].state).toMatchObject({ computed: true, fresh: true, nodes: 6, failed: 0, wire_issues: 1, weight_nodes: 1, branches: 0, backtest: true });
  expect(seen[0].applicable).toEqual(["wire_check", "branch", "strategy_add", "story_ai", "ask_ai", "records", "lanes"]);
  expect(Object.keys(seen[0].state).sort()).toEqual(["backtest", "branches", "computed", "failed", "fresh", "gates_blocked", "lanes", "minimap",
                                                     "nodes", "overlapping", "ready_to_run", "robustness", "weight_nodes", "wire_issues"]);
  // 상태가 바뀐다(레인을 켬) → AI 줄을 지우고 규칙 줄로
  await page.locator(".pg-view-open").click();
  await page.locator('[data-view="lanes"]').click();
  await expect(bar(page).locator(".pg-guide-chip")).toHaveText("규칙 길잡이");
  await expect(bar(page).locator(".pg-guide-note")).toHaveText("캔버스가 바뀌어 AI 길잡이를 지웠어요");
});

test("AI 길잡이를 보여 줄 수 없으면 사유 · 규칙 줄은 그대로", async ({ page }) => {
  await signIn(page);
  await answer(page, { available: false, source: "unavailable", reason_code: "rate_limited", reason: "한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요" });
  await openWith(page, FULL);
  await runAll(page);
  await bar(page).locator(".pg-guide-ai").click();
  await expect(bar(page).locator(".pg-guide-note")).toHaveText("AI 길잡이를 보여 줄 수 없어요: 한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요");
  await expect(bar(page).locator(".pg-guide-chip")).toHaveText("규칙 길잡이");
  await expect(bar(page)).toHaveAttribute("data-tool", "wire_check");
});

test("로그아웃이면 AI 길잡이 대신 로그인 링크 · 요청 0 · 규칙 줄은 보인다", async ({ page }) => {
  const sent: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/assist/canvas/guide")) sent.push(r.url()); });
  await openWith(page, FULL);
  await runAll(page);
  await expect(bar(page).locator(".pg-guide-chip")).toHaveText("규칙 길잡이");
  await expect(bar(page).locator(".pg-guide-ai")).toHaveCount(0);
  await expect(bar(page).locator(".pg-guide-login")).toHaveAttribute("href", "/login");
  await page.waitForTimeout(300);
  expect(sent).toEqual([]);
});

test("가로채지 않은 실제 서버: 실제 상태 → 서버 검증(422 아님) → 키 없음 사유", async ({ page }) => {
  const login = await page.request.post("/api/backend/api/v1/auth/login", { data: { username: "admin", password: "frm123!" } });
  expect(login.ok(), await login.text()).toBe(true);
  const token = (await login.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  await openWith(page, FULL);
  await runAll(page);
  const res = page.waitForResponse((r) => r.url().includes("/assist/canvas/guide"));
  await bar(page).locator(".pg-guide-ai").click();
  const r = await res;
  expect(r.status()).toBe(200);
  expect(await r.json()).toMatchObject({ available: false, reason_code: "no_key" });
  await expect(bar(page).locator(".pg-guide-note")).toHaveText("AI 길잡이를 보여 줄 수 없어요: 서버에 Claude 키가 없어요");
});

for (const scheme of ["light", "dark"] as const) {
  test(`길잡이 줄 대비(${scheme}) AA`, async ({ page }) => {
    await signIn(page);
    await openWith(page, FULL);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await runAll(page);
    await expect(bar(page)).toBeVisible();
    await expect(bar(page).locator(".pg-ai-ask")).toBeVisible();                              // ★짝★ 넓으면 AI 노드 추천도 바 안
    const a = await page.evaluate<AuditResult>(contrastAudit(".pg-guidebar"));
    expect(a.checked).toBeGreaterThanOrEqual(5);
    expect(a.low, scheme).toEqual([]);
  });
}

test.describe("두 창을 연 1024", () => {
  test.use({ viewport: { width: 1024, height: 768 } });
  test("길잡이 바는 120px 미만 · 단추가 바 안", async ({ page }) => {
    await signIn(page);
    await openWith(page, FULL);
    await runAll(page);
    const b = (await bar(page).boundingBox())!;
    expect(b.height).toBeLessThan(120);
    await expect(bar(page).locator(".pg-ai-ask")).toBeHidden();                               // 이 폭에선 AI 노드 추천을 접는다(Ctrl+K 로 남음)
    for (const sel of [".pg-guide-go", ".pg-guide-later", ".pg-guide-ai"]) {
      const x = (await bar(page).locator(sel).boundingBox())!;
      expect(x.x).toBeGreaterThanOrEqual(b.x - 1);
      expect(x.x + x.width).toBeLessThanOrEqual(b.x + b.width + 1);
    }
  });
});

test.describe("좁은 화면(390)", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("길잡이 바가 화면 안", async ({ page }) => {
    await openWith(page, FULL);
    const b = (await bar(page).boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(0);
    expect(b.x + b.width).toBeLessThanOrEqual(390);
    expect(b.y + b.height).toBeLessThanOrEqual(844);
  });
});
