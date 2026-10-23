import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, minimapOn, type AuditResult } from "./helpers";

/**
 * CF5c · 선택 도구 상자 — 고른 노드째 갈래(사용자 결정 2026-10-22: 전략째 갈래와 같은 규칙)
 *  · 둘 이상 고르고 [갈래] → ★고른 노드만★ 복제 · 뿌리 = 고른 것 중 ★흐름 맨 앞★(고른 순서 아님)
 *  · 들어오는 선은 원본과 같이 · 고른 것끼리의 선은 복제끼리 · ★나가는 선은 잇지 않는다★ · 되돌리기 한 번
 *  · 짝: 한 노드 도구줄 갈래는 지금처럼 하류 전부 · 한 뿌리에 4개까지(다섯째는 사유와 함께 거절) · 명령 찾기 길 · 라이트/다크 AA
 *  · 막대의 단추는 모두 정말 누를 수 있다 — 켠 미니맵(CF5b) 밑에 깔리지 않는다(단추를 더하자 막대가 미니맵까지 닿았다)
 * 기본 사슬: universe → returns → {estimate, optimizer, backtest} · estimate → optimizer · views → optimizer · optimizer → {risk, backtest}.
 */

type Edge = { source: string; source_port: string; target: string; target_port: string };
type Branch = { id: string; label: string; root: string; of_root: string; map: Record<string, string> };
type Doc = { nodes: { id: string; type: string; position: { x: number; y: number } }[]; edges: Edge[]; branches?: Branch[] };

const mod = process.platform === "darwin" ? "Meta" : "Control";
const HEAD = { x: 30, y: 14 };
const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const bar = (page: Page) => page.locator(".pg-selbar");

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}
/** 고른 것을 비우고(빈 곳) 첫째를 누른 뒤 나머지를 Ctrl 로 더한다 — 고른 순서 = ids 순서. */
async function pick(page: Page, ids: string[]) {
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(300);
  await page.locator(".react-flow__pane").click({ position: { x: 350, y: 20 } });
  await node(page, ids[0]).click({ position: HEAD });
  for (const id of ids.slice(1)) await node(page, id).click({ position: HEAD, modifiers: [mod] });
  await expect(bar(page).locator(".pg-selbar-n")).toHaveText(`${ids.length}개 골랐어요`);
  // 막대의 단추는 모두 정말 누를 수 있다 — 떠 있는 판·미니맵(CF5b 기본 켬) 밑에 깔리지 않는다.
  await page.waitForTimeout(200);
  const covered = await bar(page).locator("button").evaluateAll((els) => els.filter((b) => {
    const r = b.getBoundingClientRect();
    return !b.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2));
  }).map((b) => b.textContent?.trim()));
  expect(covered, "막대 단추가 무언가에 가렸다").toEqual([]);
}
/** 복제로 들어오는 선을 원본 이름으로 — 원본으로 들어오는 선과 같아야 한다. */
const into = (doc: Doc, b: Branch, id: string) => doc.edges.filter((e) => e.target === id)
  .map((e) => `${b.map[e.source] ?? e.source}.${e.source_port}->${e.target_port}`).sort();

test("고른 노드째 갈래: 최적화·추정을 고르면 그 둘만 복제 · 뿌리 = 흐름 맨 앞(추정) · 들어오는 선은 원본과 같이 · 나가는 선 없음 · 되돌리기 한 번", async ({ page }) => {
  await openCanvas(page);
  const before = await wip(page);
  await pick(page, ["optimizer", "estimate"]);                      // 고른 것은 문서 순서로 모인다 — 문서·흐름 순서가 다른 경우는 아래 따로
  const btn = bar(page).locator(".pg-selbar-branch");
  await expect(btn).toHaveAttribute("title", /고른 노드만 복제/);
  await btn.click();
  await expect(page.locator(".pg-note")).toContainText("갈래 B");
  await expect(page.locator(".pg-note")).toContainText("노드 2개");
  const doc = await wip(page);
  expect(doc.branches).toHaveLength(1);
  const b = doc.branches![0];
  expect(new Set(Object.values(b.map))).toEqual(new Set(["estimate", "optimizer"]));    // 하류(위험·백테스트)는 넣지 않는다
  expect(b.of_root).toBe("estimate");
  expect(b.map[b.root]).toBe("estimate");
  for (const [c, o] of Object.entries(b.map)) expect(into(doc, b, c), c).toEqual(into(doc, b, o));
  const copies = new Set(Object.keys(b.map));
  const inner = doc.edges.filter((e) => copies.has(e.source) && copies.has(e.target));
  expect(inner.map((e) => `${b.map[e.source]}->${b.map[e.target]}`)).toEqual(["estimate->optimizer"]);   // 고른 것끼리의 선은 복제끼리
  expect(doc.edges.filter((e) => copies.has(e.source) && !copies.has(e.target)), "갈래 밖으로 나가는 선").toEqual([]);
  expect(doc.nodes.length).toBe(before.nodes.length + 2);
  // 갈래 틀은 원본 카드와 겹치지 않는다 — 고른 둘 사이에 낀 '내 생각 넣기'(범위 밖) 밑에 틀 머리가 깔렸다(CF5c PNG 가 찾음).
  await page.waitForTimeout(400);
  const frame = (await page.locator(".pg-branch").boundingBox())!;
  for (const id of before.nodes.map((n) => n.id)) {
    const r = (await page.locator(`.react-flow__node[data-id="${id}"]`).boundingBox())!;
    const apart = r.y + r.height <= frame.y + 1 || r.y >= frame.y + frame.height - 1 || r.x + r.width <= frame.x + 1 || r.x >= frame.x + frame.width - 1;
    expect(apart, `원본 ${id} 와 갈래 틀이 겹친다`).toBe(true);
  }
  // 되돌리기 한 번에 갈래 전·복제 전으로.
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).branches ?? []).toEqual([]);
  const back = await wip(page);
  expect(back.nodes.map((n) => n.id).sort()).toEqual(before.nodes.map((n) => n.id).sort());
  expect(back.edges.length).toBe(before.edges.length);
});

test("뿌리는 문서 순서가 아니라 흐름 맨 앞 — 하류 노드가 문서에 먼저 적힌 흐름", async ({ page }) => {
  const F = { format: "project-alpha.portfolio-graph", version: 1 };
  const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
  const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
  // 문서 순서 = 최적화 · 수익률 · 종목(흐름의 거꾸로).
  const doc = { ...F, nodes: [n("optimizer", "optimizer", 640, 140, { model: "risk_parity" }), n("returns", "returns", 320, 140),
                              n("universe", "universe", 0, 140, { tickers: ["005930", "000660"] })],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns")] };
  await page.addInitScript((d) => {
    try { if (sessionStorage.getItem("cf5c_seeded")) return; sessionStorage.setItem("cf5c_seeded", "1"); sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d)); } catch { /* */ }
  }, doc);
  await openCanvas(page);
  await pick(page, ["returns", "optimizer"]);
  await bar(page).locator(".pg-selbar-branch").click();
  await expect(page.locator(".pg-note")).toContainText("갈래 B");
  const b = (await wip(page)).branches![0];
  expect(b.of_root).toBe("returns");
  expect(b.map[b.root]).toBe("returns");
});

test("짝: 한 노드 도구줄 갈래는 지금처럼 하류 전부 — 고른 노드째 갈래와 범위가 다르다", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click({ position: HEAD });
  await page.locator(".pg-branch-make").click();
  await expect(page.locator(".pg-note")).toBeVisible();
  const b = (await wip(page)).branches![0];
  expect(new Set(Object.values(b.map))).toEqual(new Set(["optimizer", "risk", "backtest"]));
});

test("명령 찾기: 둘 이상 고르면 '고른 노드째 갈래 만들기' — 막대 단추와 같은 범위", async ({ page }) => {
  await openCanvas(page);
  await pick(page, ["risk", "optimizer"]);
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("고른 노드째 갈래");
  await page.keyboard.press("Enter");
  await expect(page.locator(".pg-note")).toContainText("갈래 B");
  const b = (await wip(page)).branches![0];
  expect(new Set(Object.values(b.map))).toEqual(new Set(["optimizer", "risk"]));        // 백테스트는 고르지 않았다
  expect(b.of_root).toBe("optimizer");
});

test("한 뿌리에 4개까지 — 도구줄 갈래와 고른 노드째 갈래가 같은 뿌리(추정)면 한도를 함께 센다 · 다섯째는 사유와 함께 거절", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1800 });
  await openCanvas(page);
  await node(page, "estimate").click({ position: HEAD });
  await page.locator(".pg-branch-make").click();                    // 갈래 B — 추정 + 하류
  await expect(page.locator(".pg-note")).toContainText("갈래 B");
  for (const l of ["C", "D", "E"]) {
    await pick(page, ["estimate", "optimizer"]);
    await bar(page).locator(".pg-selbar-branch").click();
    await expect(page.locator(".pg-note")).toContainText(`갈래 ${l}`);
  }
  const doc = await wip(page);
  expect(doc.branches!.map((b) => b.of_root)).toEqual(["estimate", "estimate", "estimate", "estimate"]);
  await pick(page, ["estimate", "optimizer"]);
  await bar(page).locator(".pg-selbar-branch").click();
  await expect(page.locator(".pg-note")).toContainText("4개까지");
  expect((await wip(page)).branches!.length).toBe(4);
  expect((await wip(page)).nodes.length).toBe(doc.nodes.length);    // 거절은 아무것도 복제하지 않는다
});

test("갈래 안에서 고르면 갈래의 갈래(원본 뿌리에 붙음) · 원본과 갈래를 섞어 고르면 사유와 함께 거절", async ({ page }) => {
  await openCanvas(page);
  await pick(page, ["optimizer", "estimate"]);
  await bar(page).locator(".pg-selbar-branch").click();
  await expect(page.locator(".pg-note")).toContainText("갈래 B");
  const b = (await wip(page)).branches![0];
  const copyOf = (o: string) => Object.entries(b.map).find(([, x]) => x === o)![0];
  // 섞어 고름 — 원본 위험 + 갈래 B 의 최적화 복제. 거절하고 아무것도 복제하지 않는다.
  const n0 = (await wip(page)).nodes.length;
  await pick(page, ["risk", copyOf("optimizer")]);
  await bar(page).locator(".pg-selbar-branch").click();
  await expect(page.locator(".pg-note")).toContainText("섞여");
  // 긴 거절 안내(두 줄)도 왼쪽 아래 확대 단추를 가리지 않는다 — 토스트가 그 단추 위에 얹혀 맞춰 보기를 누를 수 없었다(CF5c 가 찾음).
  const fit = (await page.locator(".react-flow__controls-fitview").boundingBox())!;
  expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest(".react-flow__controls-fitview"),
                             [fit.x + fit.width / 2, fit.y + fit.height / 2]), "토스트가 확대 단추를 가렸다").toBe(true);
  expect((await wip(page)).branches).toHaveLength(1);
  expect((await wip(page)).nodes.length).toBe(n0);
  // 갈래 B 안의 둘 — 원본 뿌리(추정)에 붙는 갈래 C, 범위는 원본 이름으로 같은 둘.
  await pick(page, [copyOf("optimizer"), copyOf("estimate")]);
  await bar(page).locator(".pg-selbar-branch").click();
  await expect(page.locator(".pg-note")).toContainText("갈래 C");
  const c = (await wip(page)).branches![1];
  expect(c.of_root).toBe("estimate");
  expect(new Set(Object.values(c.map))).toEqual(new Set(["estimate", "optimizer"]));
});

test("포트폴리오 노드는 갈래에 넣지 않고 그렇다고 말한다 — 같이 고른 계산 노드만 복제", async ({ page }) => {
  const F = { format: "project-alpha.portfolio-graph", version: 1 };
  const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
  const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
  const doc = { ...F, nodes: [n("universe", "universe", 0, 140, { tickers: ["005930", "000660"] }), n("returns", "returns", 320, 140),
                              n("optimizer", "optimizer", 640, 140, { model: "risk_parity" }), n("pf", "portfolio_combine", 1000, 140)],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns")] };
  await page.addInitScript((d) => {
    try { if (sessionStorage.getItem("cf5c_seeded")) return; sessionStorage.setItem("cf5c_seeded", "1"); sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d)); } catch { /* */ }
  }, doc);
  await openCanvas(page);
  await pick(page, ["pf", "optimizer"]);
  await bar(page).locator(".pg-selbar-branch").click();
  await expect(page.locator(".pg-note")).toContainText("노드 1개");
  await expect(page.locator(".pg-note")).toContainText("포트폴리오 노드는 넣지 않았어요");
  const b = (await wip(page)).branches![0];
  expect(Object.values(b.map)).toEqual(["optimizer"]);
});

test("미니맵을 켜도 고른 노드 막대는 그 밑에 깔리지 않는다 — 단추를 모두 누를 수 있고 갈래가 만들어진다", async ({ page }) => {
  await openCanvas(page);
  await minimapOn(page, true);
  await pick(page, ["optimizer", "estimate"]);                      // pick 이 단추마다 가림을 잰다
  await bar(page).locator(".pg-selbar-branch").click();
  await expect(page.locator(".pg-note")).toContainText("갈래 B");
});

for (const scheme of ["light", "dark"] as const) {
  test(`고른 노드 막대 대비(${scheme}): 갈래 단추를 더해도 AA · 막대가 캔버스 안`, async ({ page }) => {
    await openCanvas(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await pick(page, ["optimizer", "estimate"]);
    await expect(bar(page).locator(".pg-selbar-branch")).toBeVisible();
    const a = await page.evaluate<AuditResult>(contrastAudit(".pg-selbar"));
    expect(a.checked).toBeGreaterThanOrEqual(5);
    expect(a.low, `${scheme} 막대`).toEqual([]);
    const r = (await bar(page).boundingBox())!;
    const c = (await page.locator(".pg-canvas").boundingBox())!;
    expect(r.x).toBeGreaterThanOrEqual(c.x);
    expect(r.x + r.width).toBeLessThanOrEqual(c.x + c.width);
  });
}
