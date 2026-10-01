import { test, expect, type Page } from "@playwright/test";

/**
 * BT4 · 링크 = 관계 — 선을 누르면 무엇이·어디서 어디로·무엇에 쓰이려고 흐르는지 말한다.
 * 거는 것(짝으로 항상-표시·항상-침묵을 배제):
 *  · 선 탭: 흐르는 값의 쉬운 이름 · 두 노드(누르면 고름) · 서버 역할(짝: 역할을 확인하지 못한 포트는 그 줄이 없다)
 *  · 끊으면: 필수 입력이면 받는 노드부터 하류 수를 말하고, 끊기는 되돌리기 한 번
 *  · 사이에 넣기: 같은 타입을 받아 같은 타입을 내는 노드만 · 넣으면 노드 +1 · 선 +1(하나 떼고 둘 잇기)
 *  · 믿을 수 있나요: 계산 전엔 지어내지 않고, 계산 뒤 연습용 흐름엔 칩(짝: 연습용이 아닌 흐름엔 없다)
 *  · 끄는 동안 이을 수 있는 포트만 또렷하고(짝: 타입이 다른 포트는 흐림) · 잘못 놓으면 사유를 말하고 선 수는 그대로
 *  · 끌지 않고 잇기: "어디서 받을까요" 목록은 이 타입을 내는 노드만(짝: 다른 타입 노드는 없다) · 고르면 선 하나
 *  · 팔레트에서 끌어 선 위에 놓으면 끼워진다(짝: 끼울 수 없는 종류는 그 자리에 놓이고 선은 그대로)
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const TICKERS = ["005930", "000660", "035420"];
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const CORE = [n("universe", "universe", 0, 140, { tickers: TICKERS }), n("returns", "returns", 230, 140),
              n("estimate", "estimate", 460, 20), n("optimizer", "optimizer", 690, 140)];
const CORE_EDGES = [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
                    e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")];
const WITH_RISK = { ...F, nodes: [...CORE, n("risk", "risk", 920, 140)], edges: [...CORE_EDGES, e("optimizer", "weights", "risk", "weights")] };
const RISK_LOOSE = { ...F, nodes: [...CORE, n("risk", "risk", 920, 300)], edges: CORE_EDGES };

type Doc = { nodes: { id: string; type: string }[]; edges: { source: string; source_port: string; target: string; target_port: string }[] };

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("bt4_seeded")) return;
      sessionStorage.setItem("bt4_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      localStorage.setItem("alpha_pg_left_tab", "add");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-palette")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".react-flow__edge")).not.toHaveCount(0);
  await expect(page.locator(".pg-node").first()).toBeVisible();
}
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const edges = (page: Page) => page.locator(".react-flow__edge");
const wireSel = (id: string) => `.react-flow__edge[data-testid="rf__edge-${id}"]`;

/** 선 위의 한 점(화면 좌표) — 곡선 길이의 `t` 지점. 가운데는 선 요약이 덮을 수 있어 비껴 잡는다. */
async function wirePoint(page: Page, id: string, t = 0.3) {
  return page.locator(`${wireSel(id)} path.react-flow__edge-path`).evaluate((el, tt) => {
    const p = el as SVGPathElement;
    const pt = p.getPointAtLength(p.getTotalLength() * tt);
    const m = p.getScreenCTM()!;
    return { x: pt.x * m.a + pt.y * m.c + m.e, y: pt.x * m.b + pt.y * m.d + m.f };
  }, t);
}
async function clickWire(page: Page, id: string) {
  // 초점 이동(fitView)이 애니메이션 중이면 점이 움직인다 — 두 번 같은 자리가 나올 때까지 기다린다.
  let p = await wirePoint(page, id);
  for (let i = 0; i < 20; i++) {
    await page.waitForTimeout(100);
    const q = await wirePoint(page, id);
    if (Math.abs(q.x - p.x) < 0.5 && Math.abs(q.y - p.y) < 0.5) break;
    p = q;
  }
  await page.mouse.click(p.x, p.y);
  await expect(page.locator(".pg-wire-sheet")).toBeVisible();
}
const row = (page: Page, r: string) => page.locator(`.pg-wire-row[data-row="${r}"]`);

test("선 탭: 흐르는 값 · 두 노드 · 서버 역할 — 역할을 확인하지 못한 포트는 그 줄이 없다(짝)", async ({ page }) => {
  await openWith(page, WITH_RISK);
  const cat = await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json();
  const role = cat.nodes.find((c: { type: string }) => c.type === "optimizer").inputs.find((p: { name: string }) => p.name === "returns").role;
  expect(role).toBeTruthy();

  await clickWire(page, "returns.returns->optimizer.returns");
  await expect(page.locator('.pg-tab[data-tab="wire"]')).toHaveAttribute("aria-selected", "true");
  await expect(row(page, "what").locator(".pg-wire-type-name")).toHaveText(cat.port_plain.Returns);
  await expect(row(page, "role")).toContainText(role);
  await expect(row(page, "trust")).toContainText("계산하면");                                  // 계산 전엔 출처를 지어내지 않는다
  // 받는 노드 이름을 누르면 그 노드가 골라진다
  await row(page, "route").locator(".pg-wire-node").nth(1).click();
  await expect(page.locator('.react-flow__node[data-id="optimizer"]')).toHaveClass(/selected/);

  // ★짝★ 추정 노드의 수익률 입력은 역할을 확인하지 못했다 — 줄이 없다(지어내지 않는다)
  expect(cat.nodes.find((c: { type: string }) => c.type === "estimate").inputs.find((p: { name: string }) => p.name === "returns").role).toBeFalsy();
  await clickWire(page, "returns.returns->estimate.returns");
  await expect(row(page, "what")).toBeVisible();
  await expect(row(page, "role")).toHaveCount(0);
});

test("끊으면: 받는 노드부터 하류 수를 말하고, 끊기는 되돌리기 한 번에 돌아온다", async ({ page }) => {
  await openWith(page, WITH_RISK);
  await clickWire(page, "returns.returns->optimizer.returns");
  await expect(row(page, "cut")).toContainText("‘비중 계산’부터 2개 노드가 계산되지 않아요");  // optimizer + risk
  const before = await edges(page).count();
  await page.locator(".pg-wire-cut").click();
  await expect(edges(page)).toHaveCount(before - 1);
  await expect(page.locator(".pg-wire-sheet")).toHaveCount(0);                                   // 끊은 선의 탭은 닫힌다
  expect((await wip(page)).edges.some((x) => x.source === "returns" && x.target === "optimizer")).toBe(false);
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  await expect(edges(page)).toHaveCount(before);
});

test("사이에 넣기: 같은 타입을 받아 내는 노드만 · 넣으면 노드 +1 · 선 +1", async ({ page }) => {
  await openWith(page, WITH_RISK);
  const cat = await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json();
  type P = { type: string };
  const want = cat.nodes.filter((c: { inputs: P[]; outputs: P[] }) => c.inputs.some((p) => p.type === "Weights") && c.outputs.some((p) => p.type === "Weights"))
    .map((c: { type: string }) => c.type).sort();
  await clickWire(page, "optimizer.weights->risk.weights");
  const got = (await page.locator(".pg-wire-insert").evaluateAll((els) => els.map((x) => x.getAttribute("data-kind")))).sort();
  expect(got).toEqual(want);
  expect(got).toContain("exposure_overlay");
  expect(got).not.toContain("risk");                                                             // ★짝★ 비중을 내지 않는 노드는 없다
  const d0 = await wip(page);
  await page.locator('.pg-wire-insert[data-kind="exposure_overlay"]').click();
  await expect(page.locator(".pg-node")).toHaveCount(d0.nodes.length + 1);
  const d1 = await wip(page);
  expect(d1.edges.length).toBe(d0.edges.length + 1);
  const mid = d1.nodes.find((x) => x.type === "exposure_overlay")!.id;
  expect(d1.edges.some((x) => x.source === "optimizer" && x.target === mid)).toBe(true);
  expect(d1.edges.some((x) => x.source === mid && x.target === "risk")).toBe(true);
  expect(d1.edges.some((x) => x.source === "optimizer" && x.target === "risk")).toBe(false);
});

test("믿을 수 있나요: 계산 뒤 연습용 흐름엔 칩 · 연습용이 아닌 흐름엔 없다(짝)", async ({ page }) => {
  await openWith(page, WITH_RISK);
  await page.locator(".pg-run").first().click();
  await expect(page.locator('.pg-node[data-kind="risk"]')).toHaveClass(/pg-node--ok/, { timeout: 60_000 });
  const rep = await (await page.request.post("http://localhost:8000/api/v1/allocation/graph/run", { data: await wip(page) })).json();
  const practice = (id: string) => !!rep.nodes?.[id]?.lineage?.practice;
  expect(practice("returns")).toBe(true);                                                        // mock 수익률은 연습용이다
  expect(practice("universe")).toBe(false);
  await clickWire(page, "returns.returns->optimizer.returns");
  await expect(row(page, "trust").locator(".pg-wire-chip--practice")).toBeVisible();
  await clickWire(page, "universe.universe->returns.universe");
  await expect(row(page, "trust")).toBeVisible();
  await expect(row(page, "trust").locator(".pg-wire-chip--practice")).toHaveCount(0);
});

test("끄는 동안 이을 수 있는 포트만 또렷하다 · 잘못 놓으면 사유를 말하고 선 수는 그대로", async ({ page }) => {
  await openWith(page, RISK_LOOSE);
  const out = page.locator('.react-flow__node[data-id="optimizer"] .react-flow__handle.source[data-handleid="weights"]');
  const good = page.locator('.react-flow__node[data-id="risk"] .react-flow__handle.target[data-handleid="weights"]');
  const bad = page.locator('.react-flow__node[data-id="estimate"] .react-flow__handle.target[data-handleid="returns"]');
  const h = (await out.boundingBox())!;
  const b = (await bad.boundingBox())!;
  await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2);
  await page.mouse.down();
  await page.mouse.move(h.x + 60, h.y + 40, { steps: 6 });
  await expect(page.locator(".pg-port--can")).not.toHaveCount(0);
  await expect(good.locator("xpath=..")).toHaveClass(/pg-port--can/);
  await expect(bad.locator("xpath=..")).toHaveClass(/pg-port--off/);                            // ★짝★ 타입이 다르면 흐림
  const before = await edges(page).count();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 10 });
  await page.mouse.up();
  await expect(page.locator(".pg-note")).toContainText("같은 색 점끼리 이어요");
  await expect(edges(page)).toHaveCount(before);
  await expect(page.locator(".pg-port--can")).toHaveCount(0);                                     // 끝나면 강조도 사라진다
});

test("끌지 않고 잇기: 목록은 이 타입을 내는 노드만(짝) · 고르면 선 하나 · 받지 않음으로 떼기", async ({ page }) => {
  await openWith(page, RISK_LOOSE);
  await page.locator('.react-flow__node[data-id="risk"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  const pick = page.locator('.pg-io-pick[data-port="weights"] select');
  await expect(pick).toBeVisible();
  const labels = await pick.locator("option").allTextContents();
  expect(labels.some((l) => l.includes("비중 계산"))).toBe(true);
  expect(labels.some((l) => l.includes("수익률 불러오기"))).toBe(false);                         // ★짝★ 비중을 내지 않는다
  expect(labels.some((l) => l.includes("종목"))).toBe(false);
  const before = await edges(page).count();
  await pick.selectOption({ label: labels.find((l) => l.includes("비중 계산"))! });
  await expect(edges(page)).toHaveCount(before + 1);
  expect((await wip(page)).edges.some((x) => x.source === "optimizer" && x.target === "risk" && x.target_port === "weights")).toBe(true);
  await pick.selectOption({ index: 0 });
  await expect(edges(page)).toHaveCount(before);
});

test("팔레트에서 끌어 선 위에 놓으면 끼워진다 · 끼울 수 없는 종류는 그 자리에 놓이고 선은 그대로(짝)", async ({ page }) => {
  await openWith(page, WITH_RISK);
  await page.locator('.pg-palette input[aria-label="노드 찾기"]').fill("노출");
  const item = page.locator('.pg-palette-item[data-kind="exposure_overlay"]');
  await expect(item).toBeVisible();
  const at = await wirePoint(page, "optimizer.weights->risk.weights", 0.5);
  const d0 = await wip(page);
  await item.dragTo(page.locator(".react-flow__pane"), { targetPosition: await paneOffset(page, at) });
  await expect(page.locator(".pg-node")).toHaveCount(d0.nodes.length + 1);
  const d1 = await wip(page);
  const mid = d1.nodes.find((x) => x.type === "exposure_overlay")!.id;
  expect(d1.edges.some((x) => x.source === "optimizer" && x.target === mid)).toBe(true);
  expect(d1.edges.some((x) => x.source === mid && x.target === "risk")).toBe(true);

  // ★짝★ 비중을 받아 비중을 내지 않는 종류(위험 나누기)는 선 위에 놓아도 끼우지 않는다
  await page.locator('.pg-palette input[aria-label="노드 찾기"]').fill("위험");
  const risk = page.locator('.pg-palette-item[data-kind="risk"]');
  const at2 = await wirePoint(page, `${mid}.weights->risk.weights`, 0.5);
  const e1 = d1.edges.length;
  await risk.dragTo(page.locator(".react-flow__pane"), { targetPosition: await paneOffset(page, at2) });
  await expect(page.locator(".pg-node")).toHaveCount(d1.nodes.length + 1);
  expect((await wip(page)).edges.length).toBe(e1);
});

async function paneOffset(page: Page, p: { x: number; y: number }) {
  const r = (await page.locator(".react-flow__pane").boundingBox())!;
  return { x: p.x - r.x, y: p.y - r.y };
}
