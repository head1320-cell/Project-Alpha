import { test, expect, type Page } from "@playwright/test";

/**
 * CF3b1 · 선 모습 — 무엇을 잇는지(필수·선택) · 결과가 지금 것인지(예전 결과) · 계산 중인지(흐름)를 선이 말한다. 계산 0.
 * 거는 것(짝으로 항상-표시·항상-침묵을 배제):
 *  · 굵기: 받는 포트가 필수면 3, 선택이면 1.75 (카탈로그 `required`) — 짝: 같은 캔버스의 두 선이 다르다 · 계산 중인 길이면 +1
 *  · 예전 결과: 비중 계산을 바꾸면 그 노드와 하류로 들어가는 선만 `pg-wire--stale`(흐림) — 짝: 상류의 선은 그대로
 *  · 계산 중: 전체 계산이면 모든 선에 흐르는 점이 선마다 하나, 끝나면 0 — 짝: 여기까지 계산이면 그 길의 선에만
 *    xyflow `animated` 는 쓰지 않는다(그 규칙이 지금 시점 전용 눈금을 대시로 바꿨다) · 선마다 `react-flow__edge-path` 는 여전히 하나
 *  · 감속 모션이면 점은 멈춘다 — 짝: 보통 모션이면 움직인다
 *  · 타입 알약: 멀리에서는 올려도 없다 — 짝: 중간에서는 올리면 보인다
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const DOC = {
  ...F,
  nodes: [n("universe", "universe", 0, 140, { tickers: ["005930", "000660", "035420"] }), n("returns", "returns", 320, 140),
          n("estimate", "estimate", 640, -420), n("views", "views", 640, 700), n("optimizer", "optimizer", 960, 140),
          n("risk", "risk", 1280, 140)],
  edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
          e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief"),
          e("views", "views", "optimizer", "views"), e("optimizer", "weights", "risk", "weights")],
};
const REQ = "returns.returns->optimizer.returns";
const OPT = "views.views->optimizer.views";
const UP = "universe.universe->returns.universe";
const DOWN = "optimizer.weights->risk.weights";

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("cf3b1_seeded")) return;
      sessionStorage.setItem("cf3b1_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".react-flow__edge")).toHaveCount(DOC.edges.length);
  await page.waitForTimeout(400);                                  // 처음 맞춤이 끝난 뒤에
  await page.locator(".react-flow__controls-fitview").click();
}
const wire = (page: Page, id: string) => page.locator(`.react-flow__edge[data-testid="rf__edge-${id}"]`);
const widthOf = (page: Page, id: string) =>
  wire(page, id).locator("path.react-flow__edge-path").evaluate((p) => getComputedStyle(p).strokeWidth);
async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
}
/** 계산 응답을 붙잡아 둔다 — 풀기 전까지 화면은 '계산하는 중'이다. */
async function holdRun(page: Page) {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  // 여기까지 계산은 `/run?targets=` — 글롭이 아니라 경로로 고른다.
  await page.route((u) => u.pathname.endsWith("/allocation/graph/run"), async (route) => { await gate; await route.continue(); });
  return () => release();
}
async function zoomTo(page: Page, level: "far" | "mid") {
  const canvas = page.locator(".pg-canvas");
  for (let i = 0; i < 16; i++) {
    const z = await canvas.getAttribute("data-zoom");
    if (z === level) return;
    await page.locator(level === "mid" && z === "far" ? ".react-flow__controls-zoomin" : ".react-flow__controls-zoomout").click();
    await page.waitForTimeout(120);
  }
  await expect(canvas).toHaveAttribute("data-zoom", level);
}
/** 선 위의 한 점(화면 좌표). */
async function wirePoint(page: Page, id: string, t = 0.3) {
  return wire(page, id).locator("path.react-flow__edge-path").evaluate((el, tt) => {
    const p = el as SVGPathElement;
    const pt = p.getPointAtLength(p.getTotalLength() * tt);
    const m = p.getScreenCTM()!;
    return { x: pt.x * m.a + pt.y * m.c + m.e, y: pt.x * m.b + pt.y * m.d + m.f };
  }, t);
}

test("굵기: 필수 입력으로 가는 선 3 · 선택 입력으로 가는 선 1.75 (카탈로그 required — 짝)", async ({ page }) => {
  await openWith(page, DOC);
  const cat = await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json();
  const inputs = cat.nodes.find((c: { type: string }) => c.type === "optimizer").inputs as { name: string; required?: boolean }[];
  expect(inputs.find((p) => p.name === "returns")?.required).not.toBe(false);
  expect(inputs.find((p) => p.name === "views")?.required).toBe(false);

  expect(await widthOf(page, REQ)).toBe("3px");
  expect(await widthOf(page, DOWN)).toBe("3px");
  expect(await widthOf(page, OPT)).toBe("1.75px");
  await expect(wire(page, REQ)).toHaveClass(/\bpg-wire--req\b/);
  await expect(wire(page, OPT)).toHaveClass(/\bpg-wire--opt\b/);
  await expect(wire(page, OPT)).not.toHaveClass(/\bpg-wire--req\b/);
});

test("예전 결과: 바꾼 노드와 하류로 들어가는 선만 흐려진다 — 짝: 상류의 선은 그대로", async ({ page }) => {
  await openWith(page, DOC);
  await run(page);
  await expect(page.locator(".react-flow__edge.pg-wire--stale")).toHaveCount(0);

  await page.locator('.pg-node[data-node-id="optimizer"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-basic-field[data-field="model"] .pg-choice', { hasText: "흔들림 최소" }).click();
  await expect(page.locator(".pg-summary--stale")).toBeVisible();

  await page.keyboard.press("Escape");                              // 고른 노드를 놓는다 — 고른 노드와 닿지 않은 선은 따로 옅어진다(faint)
  await page.locator(".react-flow__pane").click({ position: { x: 8, y: 8 } });
  await expect(page.locator(".react-flow__edge.pg-edge--faint")).toHaveCount(0);
  for (const id of [REQ, OPT, DOWN, "estimate.belief->optimizer.belief"]) await expect(wire(page, id), id).toHaveClass(/\bpg-wire--stale\b/);
  for (const id of [UP, "returns.returns->estimate.returns"]) await expect(wire(page, id), id).not.toHaveClass(/\bpg-wire--stale\b/);
  // 흐림은 선 전체(불투명도) — 선 색은 그대로라 계산 색 대비 검사와 겹치지 않는다.
  expect(Number(await wire(page, DOWN).evaluate((el) => getComputedStyle(el).opacity))).toBeLessThan(0.6);
  expect(Number(await wire(page, UP).evaluate((el) => getComputedStyle(el).opacity))).toBe(1);
});

test("계산 중: 전체 계산이면 모든 선에 흐르는 점이 하나씩 · 끝나면 0 · xyflow animated 없음 · 눈금은 대시가 되지 않는다", async ({ page }) => {
  await openWith(page, DOC);
  // 지금 시점 전용 눈금을 하나 만든다(응답 계보만 바꾼다).
  await page.route("**/allocation/graph/run", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.nodes.views.lineage = { ...(body.nodes.views.lineage ?? { practice: false }), pit: "forward_only" };
    await route.fulfill({ response: res, json: body });
  });
  await run(page);
  const ticks = wire(page, OPT).locator("path.pg-wire-ticks");
  await expect(ticks).toHaveCount(1);
  const dashBefore = await ticks.evaluate((p) => getComputedStyle(p).strokeDasharray);

  const release = await holdRun(page);
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-run")).toContainText("계산하는 중");
  const edges = page.locator(".react-flow__edge");
  await expect(page.locator(".react-flow__edge path.pg-wire-flowdots")).toHaveCount(DOC.edges.length);
  for (const id of DOC.edges.map((x) => x.id)) {
    await expect(wire(page, id).locator("path.pg-wire-flowdots"), id).toHaveCount(1);
    await expect(wire(page, id).locator("path.react-flow__edge-path"), `${id} — 선마다 한 줄`).toHaveCount(1);
  }
  await expect(page.locator(".react-flow__edge.animated")).toHaveCount(0);
  // 흐르는 점은 정말 움직인다(보통 모션) — 감속 모션 짝은 아래 테스트.
  const dots = wire(page, REQ).locator("path.pg-wire-flowdots");
  expect(await dots.evaluate((p) => getComputedStyle(p).animationName)).not.toBe("none");
  // 계산 중에도 눈금은 눈금이다.
  expect(await ticks.evaluate((p) => getComputedStyle(p).strokeDasharray)).toBe(dashBefore);

  release();
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  await expect(page.locator(".react-flow__edge path.pg-wire-flowdots")).toHaveCount(0);
  expect(await edges.count()).toBe(DOC.edges.length);
});

test("여기까지 계산: 그 길의 선만 흐르고 한 단계 굵다 — 짝: 길 밖의 선은 흐르지 않고 굵기 그대로", async ({ page }) => {
  await openWith(page, DOC);
  const release = await holdRun(page);
  await page.locator('.pg-node[data-node-id="optimizer"]').click();
  await expect(page.locator('.pg-node[data-node-id="optimizer"]')).toHaveClass(/pg-node--selected/);
  await page.locator(".react-flow__pane").focus().catch(() => {});   // 판의 입력 칸이 아니라 캔버스가 키를 받게
  await page.keyboard.press("Shift+Enter");
  await expect(page.locator(".pg-run")).toContainText("계산하는 중");

  await expect(wire(page, REQ).locator("path.pg-wire-flowdots")).toHaveCount(1);
  await expect(wire(page, OPT).locator("path.pg-wire-flowdots")).toHaveCount(1);
  await expect(wire(page, DOWN).locator("path.pg-wire-flowdots")).toHaveCount(0);
  expect(await widthOf(page, REQ)).toBe("4px");
  expect(await widthOf(page, OPT)).toBe("2.75px");
  expect(await widthOf(page, DOWN)).toBe("3px");
  release();
});

test("감속 모션: 흐르는 점은 보이되 멈춰 있다 — 짝은 위(보통 모션이면 움직인다)", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openWith(page, DOC);
  const release = await holdRun(page);
  await page.locator(".pg-run").click();
  const dots = wire(page, REQ).locator("path.pg-wire-flowdots");
  await expect(dots).toHaveCount(1);
  expect(await dots.evaluate((p) => getComputedStyle(p).animationName)).toBe("none");
  release();
});

test("타입 알약: 멀리에서는 올려도 없다 — 짝: 중간에서는 올리면 보인다", async ({ page }) => {
  await openWith(page, DOC);
  await zoomTo(page, "mid");
  let p = await wirePoint(page, REQ);
  await page.mouse.move(p.x, p.y);
  await expect(page.locator(`.pg-wire-type[data-edge-id="${REQ}"]`)).toBeVisible();

  await page.mouse.move(5, 5);
  await zoomTo(page, "far");
  await page.waitForTimeout(300);
  p = await wirePoint(page, REQ);
  await page.mouse.move(p.x, p.y);
  await page.waitForTimeout(200);
  await expect(page.locator(`.pg-wire-type[data-edge-id="${REQ}"]`)).toBeHidden();
});
