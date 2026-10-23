import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * CF5a · 실행 줄 — 계산하는 동안 노드마다 대기 → 계산 중 → 완료·막힘·실패를, 끝나면 노드별 상태·시간을(ComfyUI 큐)
 *  · 진행은 곁줄(`GET /allocation/graph/progress/{rid}` SSE)로 받는다 — `/run` 응답은 그대로다. ★최종 상태·시간은 보고서가 정한다★
 *  · 계산 중: 알약 아래 한 줄 칩(`.pg-runchip`) + 알약 글 "계산 중 k/n · ‘지금 노드’" · 끝나면 칩은 사라지고, 알약 카드에 '이번 계산' 목록이 남는다
 *  · 곁줄이 끊기면 "진행을 받지 못했어요"(조용히 숨기지 않는다) — 짝: 끝나면 보고서로 목록이 채워진다
 *  · 줄·칩을 누르면 그 노드로 · 여기까지 계산은 계산한 노드만 · 라이트/다크 AA
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const chain = (tickers: string[]) => ({
  ...F,
  nodes: [n("universe", "universe", 0, 140, { tickers }), n("returns", "returns", 320, 140),
          n("optimizer", "optimizer", 640, 140, { model: "risk_parity" }), n("corr", "corr_stress", 960, 140)],
  edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns"),
          e("returns", "returns", "corr", "returns"), e("optimizer", "weights", "corr", "weights")],
});
const OK = chain(["005930", "000660", "035420"]);
const FAIL = chain(["005930"]);                          // 종목 하나 — 수익률이 실패하고 아래가 막힌다
const IDS = ["universe", "returns", "optimizer", "corr"];

type RunBody = { order: string[]; nodes: Record<string, { status: string; elapsed_ms: number | null }>; partial?: { computed: string[] } };

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("cf5a_seeded")) return;
      sessionStorage.setItem("cf5a_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}
const isRun = (u: URL) => u.pathname.endsWith("/allocation/graph/run");
const isProgress = (u: URL) => u.pathname.includes("/allocation/graph/progress/");
/** 계산을 붙잡는다 — 놓을 때까지 서버로 보내지 않는다. */
async function holdRun(page: Page): Promise<() => void> {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  await page.route(isRun, async (route: Route) => { await gate; await route.continue(); });
  return release;
}
const sse = (events: object[]) => events.map((ev) => `data: ${JSON.stringify(ev)}\n\n`).join("");
const chip = (page: Page, id: string) => page.locator(`.pg-runchip[data-node-id="${id}"]`);
const row = (page: Page, id: string) => page.locator(`.pg-runrow[data-node-id="${id}"]`);
const fmt = (ms: number | null) => (ms == null ? "—" : ms < 10 ? "0.01초 미만" : `${(ms / 1000).toFixed(ms < 1000 ? 2 : 1)}초`);
async function openCard(page: Page) {
  if ((await page.locator(".pg-rail-pill").getAttribute("aria-expanded")) !== "true") await page.locator(".pg-rail-pill").click();
  await expect(page.locator(".pg-runlist")).toBeVisible();
}

test("계산 중: 곁줄로 받은 만큼 칩이 바뀐다 — 완료·계산 중·대기 · 알약 '계산 중 1/4 · 지금 노드' · 놓으면 보고서대로", async ({ page }) => {
  await openWith(page, OK);
  const release = await holdRun(page);
  await page.route(isProgress, (route) => route.fulfill({
    status: 200, headers: { "content-type": "text/event-stream" },
    body: sse([{ type: "plan", order: IDS }, { type: "node_start", id: "universe" },
               { type: "node_done", id: "universe", status: "ok", elapsed_ms: 12 }, { type: "node_start", id: "returns" }, { type: "end" }]),
  }));
  await page.locator(".pg-run").click();
  await expect(chip(page, "universe")).toHaveAttribute("data-phase", "done");
  await expect(chip(page, "universe")).toHaveAttribute("data-status", "ok");
  await expect(chip(page, "returns")).toHaveAttribute("data-phase", "running");
  await expect(chip(page, "optimizer")).toHaveAttribute("data-phase", "waiting");
  await expect(chip(page, "corr")).toHaveAttribute("data-phase", "waiting");
  expect(await page.locator(".pg-runchip").evaluateAll((els) => els.map((x) => x.getAttribute("data-node-id")))).toEqual(IDS);
  await expect(page.locator(".pg-rail-pill-text")).toHaveText(/계산 중 1\/4 · ‘.+’/);
  await expect(page.locator(".pg-runline-note")).toHaveCount(0);                    // 짝 — 끊긴 게 아니다
  const resp = page.waitForResponse((r) => isRun(new URL(r.url())));
  release();
  const body = (await (await resp).json()) as RunBody;
  await expect(page.locator(".pg-runchip")).toHaveCount(0);                         // 끝나면 칩은 사라진다
  await openCard(page);
  for (const id of IDS) {
    await expect(row(page, id)).toHaveAttribute("data-status", body.nodes[id].status);
    await expect(row(page, id).locator(".pg-runrow-time")).toHaveText(fmt(body.nodes[id].elapsed_ms));
  }
});

test("실제 계산: 목록 순서·상태·시간 = 보고서 · 곁줄이 프록시를 지나 모든 노드의 끝을 실어 왔다", async ({ page }) => {
  await openWith(page, OK);
  const progress = page.waitForResponse((r) => isProgress(new URL(r.url())));
  const resp = page.waitForResponse((r) => isRun(new URL(r.url())));
  await page.locator(".pg-run").click();
  const body = (await (await resp).json()) as RunBody;
  const stream = await (await progress).text();
  const done = stream.split("\n").filter((l) => l.startsWith("data:")).map((l) => JSON.parse(l.slice(5))).filter((ev) => ev.type === "node_done");
  expect(done.map((ev) => ev.id)).toEqual(body.order);
  await openCard(page);
  expect(await page.locator(".pg-runrow").evaluateAll((els) => els.map((x) => x.getAttribute("data-node-id")))).toEqual(body.order);
  for (const id of body.order) {
    await expect(row(page, id)).toHaveAttribute("data-phase", "done");
    await expect(row(page, id)).toHaveAttribute("data-status", body.nodes[id].status);
    await expect(row(page, id).locator(".pg-runrow-time")).toHaveText(fmt(body.nodes[id].elapsed_ms));
  }
});

test("곁줄이 끊기면 '진행을 받지 못했어요' — 짝: 끝나면 보고서로 목록이 채워진다", async ({ page }) => {
  await openWith(page, OK);
  const release = await holdRun(page);
  await page.route(isProgress, (route) => route.abort());
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-runline-note")).toHaveText(/진행을 받지 못했어요/);
  await expect(page.locator(".pg-rail-pill-text")).toContainText("진행을 받지 못했어요");
  const resp = page.waitForResponse((r) => isRun(new URL(r.url())));
  release();
  const body = (await (await resp).json()) as RunBody;
  await openCard(page);
  for (const id of IDS) await expect(row(page, id)).toHaveAttribute("data-status", body.nodes[id].status);
});

test("곁줄이 끝을 알리지 않고 닫혀도 끊긴 것 — '진행을 받지 못했어요'(짝: 위 첫 테스트는 끝을 알려 안내가 없다)", async ({ page }) => {
  await openWith(page, OK);
  const release = await holdRun(page);
  await page.route(isProgress, (route) => route.fulfill({
    status: 200, headers: { "content-type": "text/event-stream" },
    body: sse([{ type: "plan", order: IDS }, { type: "node_start", id: "universe" }]),
  }));
  await page.locator(".pg-run").click();
  await expect(chip(page, "universe")).toHaveAttribute("data-phase", "running");     // 받은 만큼은 그대로 보인다
  await expect(page.locator(".pg-runline-note")).toHaveText(/진행을 받지 못했어요/);
  release();
});

test("실패·막힘: 수익률 실패 → 아래는 막힘(시간 없음 —) · 줄을 누르면 그 노드를 고른다", async ({ page }) => {
  await openWith(page, FAIL);
  const resp = page.waitForResponse((r) => isRun(new URL(r.url())));
  await page.locator(".pg-run").click();
  const body = (await (await resp).json()) as RunBody;
  expect(body.nodes.returns.status).toBe("failed");
  await openCard(page);
  await expect(row(page, "returns")).toHaveAttribute("data-status", "failed");
  await expect(row(page, "returns").locator(".pg-runrow-state")).toHaveText("실패");
  for (const id of ["optimizer", "corr"]) {
    await expect(row(page, id)).toHaveAttribute("data-status", "blocked");
    await expect(row(page, id).locator(".pg-runrow-state")).toHaveText("막힘");
    await expect(row(page, id).locator(".pg-runrow-time")).toHaveText("—");
  }
  await row(page, "corr").locator("button").click();
  await expect(page.locator('.react-flow__node[data-id="corr"]')).toHaveClass(/selected/);
});

test("여기까지 계산: 목록은 계산한 노드(고른 노드와 조상)만", async ({ page }) => {
  await openWith(page, OK);
  await page.locator('.pg-node[data-node-id="returns"]').click({ position: { x: 30, y: 14 } });
  const resp = page.waitForResponse((r) => isRun(new URL(r.url())));
  await page.keyboard.press("Shift+Enter");
  const body = (await (await resp).json()) as RunBody;
  expect(body.partial?.computed).toEqual(["universe", "returns"]);
  await openCard(page);
  expect(await page.locator(".pg-runrow").evaluateAll((els) => els.map((x) => x.getAttribute("data-node-id")))).toEqual(["universe", "returns"]);
});

for (const scheme of ["light", "dark"] as const) {
  test(`실행 줄 대비(${scheme}): 계산 중 칩·알약 · 끝난 뒤 목록 AA`, async ({ page }) => {
    await openWith(page, FAIL);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    const release = await holdRun(page);
    await page.route(isProgress, (route) => route.fulfill({
      status: 200, headers: { "content-type": "text/event-stream" },
      body: sse([{ type: "plan", order: IDS }, { type: "node_start", id: "universe" },
                 { type: "node_done", id: "universe", status: "ok", elapsed_ms: 12 }, { type: "node_start", id: "returns" }, { type: "end" }]),
    }));
    await page.locator(".pg-run").click();
    await expect(chip(page, "returns")).toHaveAttribute("data-phase", "running");
    let a = await page.evaluate<AuditResult>(contrastAudit(".pg-rail-wrap"));
    expect(a.checked).toBeGreaterThanOrEqual(5);
    expect(a.low, `${scheme} 계산 중`).toEqual([]);
    const resp = page.waitForResponse((r) => isRun(new URL(r.url())));
    release();
    await resp;
    await openCard(page);
    a = await page.evaluate<AuditResult>(contrastAudit(".pg-runlist"));
    expect(a.checked).toBeGreaterThanOrEqual(8);
    expect(a.low, `${scheme} 목록`).toEqual([]);
  });
}
