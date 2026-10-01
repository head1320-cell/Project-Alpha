import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BT2 · 절차 탭 + 관문 알약 ↔ 노드 — ★그래프가 스스로 절차를 말한다★
 * 거는 것(짝으로 항상-제안·항상-침묵을 배제):
 *  · 빈 캔버스는 절차 탭을 먼저 연다 · 첫 한 걸음을 누르면 노드가 생기고, 다음 걸음은 **선까지 이어서** 붙는다
 *  · 비중까지만 있는 흐름: 확인하기 단계가 비어 있고 [‘과거로 돌려 보기’ 붙이기] → 새 노드 + 선 2개(짝: 채운 단계에는 단추가 없다)
 *  · 단계 줄에 올리면 그 단계 노드만 또렷하다(짝: 다른 노드는 흐림 · 떼면 흐림 없음)
 *  · 노드를 고르면 그 단계 줄에 표시가 켜진다
 *  · 관문 설명에 판정한 노드 목록 → 누르면 그 노드가 골라진다 · 건너뛴 관문의 [붙이기] 가 그 관문을 잴 노드를 이어 붙인다
 *  · 서버에 닿지 못하면 절차를 지어내지 않고 그렇다고 말한다(짝: 다시 시도하면 단계가 나온다)
 *  · 라이트·다크 AA
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const TICKERS = ["005930", "000660", "035420"];
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const EMPTY = { ...F, nodes: [], edges: [] };
const BUILD_ONLY = {
  ...F,
  nodes: [n("universe", "universe", 0, 140, { tickers: TICKERS }), n("returns", "returns", 230, 140),
          n("estimate", "estimate", 460, 20), n("optimizer", "optimizer", 690, 140)],
  edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
          e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")],
};

async function openWith(page: Page, doc: object | null, tab: "proc" | "add" | null = null) {
  await page.addInitScript(([d, t]) => {
    try {
      if (sessionStorage.getItem("bt2_seeded")) return;
      sessionStorage.setItem("bt2_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      if (t) localStorage.setItem("alpha_pg_left_tab", t as string); else localStorage.removeItem("alpha_pg_left_tab");
      if (d) sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d)); else sessionStorage.removeItem("alpha_pg_wip");
    } catch { /* */ }
  }, [doc, tab] as const);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-palette")).toBeVisible({ timeout: 30_000 });
}
const step = (page: Page, key: string) => page.locator(`.pg-proc-step[data-step="${key}"]`);
const edges = (page: Page) => page.locator(".react-flow__edge");
const nodeOf = (page: Page, kind: string) => page.locator(`.pg-node[data-kind="${kind}"]`);

test("빈 캔버스: 절차 탭이 먼저 · 첫 걸음은 종목 고르기 · 다음 걸음은 선까지 이어서 붙는다", async ({ page }) => {
  await openWith(page, EMPTY);
  await expect(page.locator('.pg-left-tab[data-tab="proc"]')).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".pg-proc-step")).toHaveCount(6);
  await expect(step(page, "data")).toHaveAttribute("data-state", "empty");
  await expect(step(page, "data").locator(".pg-proc-need")).toHaveText("필수");
  await step(page, "data").locator(".pg-proc-fix").click();
  await expect(nodeOf(page, "universe")).toHaveCount(1);
  await expect(edges(page)).toHaveCount(0);
  await expect(step(page, "data")).toHaveAttribute("data-state", "partial");          // 종목만으로는 데이터 관문을 잴 수 없다
  // 다음 걸음 — 수익률은 종목에서 이어 붙는다(붙이기만 하고 잇지 않는 제안은 없다)
  await expect(step(page, "data").locator(".pg-proc-fix")).toHaveText("‘수익률 불러오기’ 붙이기");
  await step(page, "data").locator(".pg-proc-fix").click();
  await expect(nodeOf(page, "returns")).toHaveCount(1);
  await expect(edges(page)).toHaveCount(1);
  await expect(step(page, "data")).toHaveAttribute("data-state", "filled");
  await expect(step(page, "data").locator(".pg-proc-fix")).toHaveCount(0);           // ★짝★ 채운 단계는 단추가 없다
  // 되돌리기 한 번에 노드와 선이 함께 사라진다
  await page.keyboard.press("Control+z");
  await expect(nodeOf(page, "returns")).toHaveCount(0);
  await expect(edges(page)).toHaveCount(0);
});

test("비중까지만: 확인하기가 비어 있고 붙이면 과거로 돌려 보기가 선 2개로 이어진다", async ({ page }) => {
  await openWith(page, BUILD_ONLY, "proc");
  await expect(step(page, "build")).toHaveAttribute("data-state", "filled");
  await expect(step(page, "build").locator(".pg-proc-fix")).toHaveCount(0);
  await expect(step(page, "check")).toHaveAttribute("data-state", "empty");
  await expect(step(page, "check").locator(".pg-proc-need")).toHaveText("권장");
  await expect(step(page, "check").locator('.pg-proc-gate[data-gate="cost"]')).toBeVisible();
  const before = await edges(page).count();
  await step(page, "check").locator(".pg-proc-fix").click();
  await expect(nodeOf(page, "backtest")).toHaveCount(1);
  await expect(edges(page)).toHaveCount(before + 2);
  // 새 노드는 비중 계산의 비중과 수익률을 받는다
  const bt = await page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}"));
  const id = bt.nodes.find((x: { type: string }) => x.type === "backtest").id;
  expect(bt.edges.filter((x: { target: string }) => x.target === id).map((x: { source: string; target_port: string }) => `${x.source}.${x.target_port}`).sort())
    .toEqual(["optimizer.weights", "returns.returns"]);
  await expect(step(page, "check")).toHaveAttribute("data-state", "filled");
  await expect(page.locator(".pg-proc-done")).toContainText("절차를 다 채웠어요");
});

test("양방향: 단계에 올리면 그 노드만 또렷하고, 노드를 고르면 그 단계가 켜진다", async ({ page }) => {
  await openWith(page, BUILD_ONLY, "proc");
  await expect(step(page, "build")).toHaveAttribute("data-state", "filled");
  await step(page, "build").hover();
  await expect(page.locator('.react-flow__node:has(.pg-node[data-kind="optimizer"])')).not.toHaveClass(/pg-dim/);
  await expect(page.locator('.react-flow__node:has(.pg-node[data-kind="returns"])')).toHaveClass(/pg-dim/);      // ★짝★
  await page.mouse.move(900, 20);
  await expect(page.locator(".react-flow__node.pg-dim")).toHaveCount(0);
  await expect(page.locator(".pg-proc-step--here")).toHaveCount(0);
  await nodeOf(page, "returns").click();
  await expect(step(page, "data")).toHaveClass(/pg-proc-step--here/);
  await expect(step(page, "build")).not.toHaveClass(/pg-proc-step--here/);
});

test("관문 알약: 판정한 노드로 가고, 건너뛴 관문의 [붙이기] 가 그 관문을 잴 노드를 잇는다", async ({ page }) => {
  await openWith(page, BUILD_ONLY, "add");
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await page.locator(".pg-rail-pill").click();
  await page.locator('.pg-stn[data-gate="data"] button').click();
  const nodes = page.locator(".pg-gate-pop .pg-gate-node");
  await expect(nodes).toHaveCount(1);
  await expect(nodes.first()).toContainText("수익률 불러오기");
  await nodes.first().click();
  await expect(page.locator('.pg-node[data-kind="returns"].pg-node--selected')).toHaveCount(1);
  // ★짝★ 잴 걸음이 없는 관문(데이터 — 이미 수익률이 있다)에는 [붙이기] 가 없다
  await page.locator('.pg-stn[data-gate="data"] button').click();
  await expect(page.locator(".pg-gate-pop")).toBeVisible();
  await expect(page.locator(".pg-gate-pop .pg-gate-fix")).toHaveCount(0);
  await page.locator('.pg-stn[data-gate="cost"] button').click();
  await expect(page.locator('.pg-stn[data-gate="cost"]')).toHaveClass(/pg-stn--skipped/);
  const before = await edges(page).count();
  await page.locator(".pg-gate-pop .pg-gate-fix").click();
  await expect(nodeOf(page, "backtest")).toHaveCount(1);
  await expect(edges(page)).toHaveCount(before + 2);
});

test("서버에 닿지 못하면 절차를 지어내지 않는다 · 다시 시도하면 나온다", async ({ page }) => {
  await page.route("**/allocation/graph/validate", (r) => r.abort());
  await openWith(page, BUILD_ONLY, "proc");
  await expect(page.locator(".pg-proc-empty")).toContainText("절차를 불러오지 못했어요");
  await expect(page.locator(".pg-proc-step")).toHaveCount(0);
  await page.unroute("**/allocation/graph/validate");
  await page.locator(".pg-proc-retry").click();
  await expect(page.locator(".pg-proc-step")).toHaveCount(6);                           // ★짝★
});

for (const theme of ["light", "dark"] as const) {
  test(`절차 탭 대비 AA (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await openWith(page, BUILD_ONLY, "proc");
    await expect(page.locator(".pg-proc-step")).toHaveCount(6);
    if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    const r = await page.evaluate<AuditResult>(contrastAudit(".pg-palette"));
    expect(r.checked).toBeGreaterThan(20);
    expect(r.low, JSON.stringify(r.low)).toEqual([]);
  });
}

// ── BT3 · 다음 한 걸음 · 추가하면 이어진다 · "이어 주세요" 단추 ────────────────────────────────

test("다음 한 걸음: 서버 문장 그대로 · [붙이기] 뒤 다음 규칙으로 · 다 채우면 조작 도움말(짝)", async ({ page }) => {
  await openWith(page, BUILD_ONLY, "add");
  const next = page.locator(".pg-next");
  await expect(next).toContainText("‘과거로 돌려 보기’");
  await expect(next).toContainText("잴 수 있게 돼요");
  const before = await edges(page).count();
  await next.locator(".pg-next-go").click();
  await expect(nodeOf(page, "backtest")).toHaveCount(1);
  await expect(edges(page)).toHaveCount(before + 2);
  await expect(next).toHaveCount(0);                                              // 다 채웠다 — 제안이 없다
  await page.locator(".react-flow__pane").click({ position: { x: 600, y: 60 } });   // 새 노드 고름을 풀면 조작 도움말
  await expect(page.locator(".pg-hint")).toContainText("같은 색 점끼리");
});

test("[다음에] 는 이 모양에서 숨기고, 기본 흐름(다 채움)에는 처음부터 없다(짝)", async ({ page }) => {
  await openWith(page, BUILD_ONLY, "add");
  await expect(page.locator(".pg-next")).toBeVisible();
  await page.locator(".pg-next-later").click();
  await expect(page.locator(".pg-next")).toHaveCount(0);
  await expect(page.locator(".pg-hint")).toContainText("같은 색 점끼리");
});

test("기본 흐름은 절차를 다 채웠다 — 다음 한 걸음이 없다(짝)", async ({ page }) => {
  await openWith(page, null, "add");
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".pg-hint")).toBeVisible();
  await expect(page.locator(".pg-next")).toHaveCount(0);
});

test("사람이 고른 노드 뒤에 붙인다 · 고르지 않았으면 잇지 않는다(짝) · 연속 추가는 사슬이 되지 않는다", async ({ page }) => {
  await openWith(page, BUILD_ONLY, "add");
  const base = await edges(page).count();
  await nodeOf(page, "optimizer").click();
  await page.locator('.pg-palette-item[data-kind="risk"]').click();
  await expect(nodeOf(page, "risk")).toHaveCount(1);
  await expect(edges(page)).toHaveCount(base + 1);
  await expect(page.locator(".pg-note")).toContainText("‘비중 계산’ 뒤에 이었어요");
  // 새 노드가 자동으로 골라졌지만 사람이 고른 것이 아니다 — 한 번 더 눌러도 사슬로 잇지 않는다.
  // ★공허하지 않게★ 비중을 받아 비중을 내는 노출 조절로 본다(자기 자신 뒤에 이을 수 있는 종류 — 흔들림 나눠 보기는 그럴 수 없다).
  await nodeOf(page, "optimizer").click();
  await page.locator('.pg-palette-item[data-kind="exposure_overlay"]').click();
  await expect(nodeOf(page, "exposure_overlay")).toHaveCount(1);
  await expect(edges(page)).toHaveCount(base + 2);
  await page.locator('.pg-palette-item[data-kind="exposure_overlay"]').click();
  await expect(nodeOf(page, "exposure_overlay")).toHaveCount(2);
  await expect(edges(page)).toHaveCount(base + 2);
  // ★짝★ 아무것도 고르지 않으면 잇지 않는다
  await page.locator(".react-flow__pane").click({ position: { x: 600, y: 60 } });
  await page.locator('.pg-palette-item[data-kind="risk"]').click();
  await expect(nodeOf(page, "risk")).toHaveCount(2);
  await expect(edges(page)).toHaveCount(base + 2);
});

test("‘기대 수익’을 이어 주세요 — 이름을 누르면 그 값을 내는 노드만 보이고, 고르면 잇는다", async ({ page }) => {
  const doc = { ...BUILD_ONLY, edges: BUILD_ONLY.edges.filter((x) => x.target_port !== "belief") };
  await openWith(page, doc, "add");
  const btn = nodeOf(page, "optimizer").locator('.pg-node-need-btn[data-port="belief"]');
  await expect(btn).toHaveText("‘기대 수익’");
  await btn.click();
  const items = page.locator(".pg-quick .pg-quick-item");
  await expect(items.first()).toBeVisible();
  const kinds = await items.evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")));
  expect(kinds).toContain("estimate");
  expect(kinds).not.toContain("backtest");                                        // ★짝★ 기대 수익을 내지 않는 노드는 없다
  const before = await edges(page).count();
  await page.locator('.pg-quick .pg-quick-item[data-kind="estimate"]').click();
  await expect(edges(page)).toHaveCount(before + 1);
  await expect(nodeOf(page, "optimizer").locator(".pg-node-need")).toHaveCount(0);
});
