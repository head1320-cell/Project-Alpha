import { test, expect, type Page } from "@playwright/test";

/**
 * BT7 · 노드 카드·판 다듬기 — 부품 명세 · 고치는 법 · 연습용 표시 · 가까이 포트 이름 · 렌더러 셋
 * 거는 것(짝으로 항상-표시·항상-침묵을 배제):
 *  · 고치는 법: 빠진 입력이 있는 카드에 서버 문장 그대로 + 단추 → 선이 생김 · 빠진 게 없는 카드엔 줄이 없다(짝)
 *  · 연습용 칩은 서버 표시(`kind: "practice"`)만 본다 — 응답에서 표시를 지우면 문구에 "연습용"이 남아도 칩이 없다(짝: 표시가 있으면 칩)
 *  · 가까이 확대에서 포트 이름이 보이고, 보통 확대에서는 숨는다(짝)
 *  · 종목 고르기·내 생각·기대 수익 설정의 자세히 탭에 원시 JSON 이 없다 — 서버 값이 표·목록으로
 *  · 명세 칸의 수 = 서버 explain 의 수(가정·모르는 것·재지 않은 것)
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const LOOSE_OPT = {
  ...F,
  nodes: [n("universe", "universe", 0, 140, { tickers: ["005930", "000660", "035420"] }), n("returns", "returns", 230, 140),
          n("optimizer", "optimizer", 520, 140)],
  edges: [e("universe", "universe", "returns", "universe")],
};
type Trust = { state: string; text: string; kind?: string };
type NodeRes = { status: string; view: Record<string, unknown> | null; explain?: { trust?: Trust[]; unmeasured?: string[] } };
type RunBody = { nodes: Record<string, NodeRes> };
const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const canvas = (page: Page) => page.locator(".pg-canvas");
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as
  Promise<{ edges: { source: string; target: string; target_port: string }[] }>;

async function openWith(page: Page, doc: object | null) {
  if (doc) {
    await page.addInitScript((d) => {
      try {
        if (sessionStorage.getItem("bt7_seeded")) return;
        sessionStorage.setItem("bt7_seeded", "1");
        sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
      } catch { /* */ }
    }, doc);
  }
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
}
async function run(page: Page): Promise<RunBody> {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = (await (await resp).json()) as RunBody;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return body;
}
async function zoomTo(page: Page, level: "far" | "mid" | "near") {
  for (let i = 0; i < 14; i++) {
    const z = await canvas(page).getAttribute("data-zoom");
    if (z === level) return;
    const wantIn = level === "near" || (level === "mid" && z === "far");
    await page.locator(wantIn ? ".react-flow__controls-zoomin" : ".react-flow__controls-zoomout").click();
    await page.waitForTimeout(120);
  }
  await expect(canvas(page)).toHaveAttribute("data-zoom", level);
}

test("고치는 법: 서버 문장 그대로 + 단추 → 빠진 입력이 이어진다 · 빠진 게 없는 카드엔 줄이 없다(짝)", async ({ page }) => {
  const valid = page.waitForResponse((r) => r.url().includes("/allocation/graph/validate"));
  await openWith(page, LOOSE_OPT);
  const v = await (await valid).json();
  const fix = v.procedure.fixes.optimizer;
  expect(fix.action).toBe("connect");                                                    // 수익률이 이미 있다 — 붙이지 않고 잇는다
  const line = node(page, "optimizer").locator(".pg-node-fix");
  await expect(line.locator(".pg-node-fix-text")).toHaveText(fix.text);
  expect(v.errors.some((x: { code: string; node_id: string; fix: string | null }) =>
    x.code === "missing_input" && x.node_id === "optimizer" && x.fix === fix.text)).toBe(true);
  await expect(node(page, "returns").locator(".pg-node-fix")).toHaveCount(0);            // ★짝★
  await expect(node(page, "universe").locator(".pg-node-fix")).toHaveCount(0);
  const next = page.waitForResponse((r) => r.url().includes("/allocation/graph/validate"));
  await line.locator(".pg-node-fix-btn").click();
  await expect.poll(async () => (await wip(page)).edges.some((x) => x.source === "returns" && x.target === "optimizer"
                                                                  && x.target_port === "returns")).toBe(true);
  // 고친 자리는 더 말하지 않는다 — 남은 빠진 입력이 있으면 서버가 그다음 것을 말하고, 카드는 그 문장을 그대로 보인다
  const v2 = await (await next).json();
  const after = v2.procedure.fixes.optimizer;
  if (after) {
    expect(after.attach.every((a: { target_port: string }) => a.target_port !== "returns")).toBe(true);
    await expect(line.locator(".pg-node-fix-text")).toHaveText(after.text);
  } else {
    await expect(node(page, "optimizer").locator(".pg-node-fix")).toHaveCount(0);
  }
});

test("연습용 칩은 서버 표시만 본다 — 표시를 지우면 문구가 남아도 칩이 없다 · 표시가 있으면 칩(짝)", async ({ page }) => {
  await openWith(page, null);
  const body = await run(page);
  const practiceLine = (body.nodes.returns.explain?.trust ?? []).find((t) => t.kind === "practice");
  expect(practiceLine, "mock 수익률은 연습용 표시가 있다").toBeTruthy();
  expect(practiceLine!.text).toContain("연습용");
  const chip = (p: Page) => node(p, "returns").locator(".pg-node-ev .pg-tag", { hasText: "연습용 데이터" });
  await expect(chip(page)).toHaveCount(1);

  // 표시만 지운 응답 — 문구는 그대로 "연습용 …" 이다
  await page.route("**/api/v1/allocation/graph/run**", async (route) => {
    const res = await route.fetch();
    const b = (await res.json()) as RunBody;
    for (const r of Object.values(b.nodes)) for (const t of r.explain?.trust ?? []) delete t.kind;
    await route.fulfill({ response: res, json: b });
  });
  await run(page);
  await expect(chip(page)).toHaveCount(0);
});

test("가까이 확대에서 포트 이름이 보이고, 보통 확대에서는 숨는다(짝)", async ({ page }) => {
  await openWith(page, null);
  const name = node(page, "optimizer").locator(".pg-port--in .pg-port-name").first();
  await zoomTo(page, "mid");
  await page.mouse.move(5, 5);
  await expect(name).toBeHidden();
  await zoomTo(page, "near");
  await page.mouse.move(5, 5);
  await expect(name).toBeVisible();
});

test("종목 고르기·내 생각·기대 수익 설정: 자세히 탭에 원시 JSON 이 없고 서버 값이 표·목록으로 보인다", async ({ page }) => {
  await openWith(page, null);
  const body = await run(page);
  const detail = async (id: string) => {
    await node(page, id).click();
    await page.locator('.pg-tab[data-tab="detail"]').click();
    await expect(page.locator(".pg-result")).toBeVisible();
    await expect(page.locator(".pg-result pre.pg-raw")).toHaveCount(0);
  };
  await detail("universe");
  const tickers = body.nodes.universe.view!.tickers as string[];
  await expect(page.locator(".pg-universe-table tr")).toHaveCount(tickers.length);
  for (const t of tickers) await expect(page.locator(".pg-universe-table")).toContainText(t);

  await detail("views");
  const views = (body.nodes.views.view!.views as unknown[]) ?? [];
  if (views.length) await expect(page.locator(".pg-view-row")).toHaveCount(views.length);
  else await expect(page.locator(".pg-result")).toContainText("적은 생각이 없어요");

  await detail("estimate");
  const settings = body.nodes.estimate.view!.settings as Record<string, unknown>;
  await expect(page.locator(".pg-estimate-table tr")).toHaveCount(Object.keys(settings).length);
});

test("명세 칸의 수 = 서버 explain 의 수 · 계산 전에는 그렇다고만 말한다(짝)", async ({ page }) => {
  await openWith(page, null);
  await node(page, "optimizer").click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await expect(page.locator(".pg-passport")).toContainText("아직 계산 전이에요");
  await expect(page.locator('.pg-passport [data-k="assumed"]')).toHaveCount(0);
  const body = await run(page);
  await node(page, "optimizer").click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  const ex = body.nodes.optimizer.explain!;
  const count = (st: string) => (ex.trust ?? []).filter((t) => t.state === st).length;
  await expect(page.locator('.pg-passport [data-k="assumed"] dd')).toHaveText(`${count("assumed")}개`);
  await expect(page.locator('.pg-passport [data-k="unknown"] dd')).toHaveText(`${count("unknown")}개`);
  await expect(page.locator('.pg-passport [data-k="unmeasured"] dd')).toHaveText(`${(ex.unmeasured ?? []).length}가지`);
  await expect(page.locator('.pg-passport [data-k="stage"] dd')).toHaveText("비중 정하기");
});
