import { test, expect, type Page } from "@playwright/test";

/**
 * BT5 · 영향 — ★바뀐 곳과 그 하류만 낡는다★ (예전엔 설정 하나만 바꿔도 모든 카드가 "예전 결과" 였다)
 * 거는 것(짝으로 항상-낡음·항상-새것을 배제):
 *  · 비중 계산을 바꾸면 그 노드와 하류만 낡고, 상류 카드는 결과를 그대로 둔다
 *  · 도구줄 "예전 결과 n개" 의 n 이 실제 하류 수와 같고, [바뀐 곳만 계산] 이 그 노드들만 다시 계산해 낡음을 지운다
 *  · 위만 다시 계산해도(여기까지 계산) 그 전 값으로 계산한 아래 노드는 계속 낡은 것으로 남는다(서명 사슬)
 *  · 되돌리기로 계산 때 그래프로 돌아가면 낡음이 풀리고, 다시하기로 돌아오면 다시 낡는다
 *  · 영향 줄의 수 = 이 노드 + 하류 · 올리면 그 노드들만 또렷하다
 *  · 내는 것 = 받는 노드 목록(누르면 고름) · 아무도 안 받으면 그렇다고 말한다
 *  · 관문 알약은 지우지 않고 "예전 결과 기준" 이라고 말한다
 */

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
type Doc = { nodes: { id: string; type: string }[]; edges: { source: string; target: string; source_port: string }[] };
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
}
async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
}
function downstream(doc: Doc, from: string): Set<string> {
  const down = new Set([from]);
  for (let grew = true; grew;) {
    grew = false;
    for (const e of doc.edges) if (down.has(e.source) && !down.has(e.target)) { down.add(e.target); grew = true; }
  }
  return down;
}
/** 비중 계산의 방식을 바꾼다(설정 판 기본 칸) — 같은 칸을 다시 고르면 되돌아간다. */
async function setModel(page: Page, label: string) {
  await node(page, "optimizer").click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-basic-field[data-field="model"] .pg-choice', { hasText: label }).click();
}
const isStale = (page: Page, id: string) => node(page, id).evaluate((el) => el.classList.contains("pg-node--stale"));

test("바꾼 노드와 하류만 낡고 상류는 결과를 둔다 · 수가 하류와 같다 · [바뀐 곳만 계산] 이 그것만 지운다", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  const doc = await wip(page);
  const down = downstream(doc, "optimizer");
  const up = doc.nodes.map((n) => n.id).filter((id) => !down.has(id));
  expect(down.size).toBeGreaterThan(1);
  expect(up.length).toBeGreaterThan(1);

  await setModel(page, "흔들림 최소");
  await expect(page.locator(".pg-summary--stale")).toBeVisible();
  await expect(page.locator(".pg-summary--stale")).toHaveAttribute("data-count", String(down.size));
  await expect(page.locator(".pg-summary--stale")).toContainText(`예전 결과 ${down.size}개`);
  for (const id of down) expect(await isStale(page, id), `${id} — 하류는 낡는다`).toBe(true);
  for (const id of up) expect(await isStale(page, id), `${id} — ★짝★ 상류는 낡지 않는다`).toBe(false);
  await expect(node(page, "returns")).toHaveClass(/pg-node--ok/);                      // 상류 카드는 결과 그대로
  await expect(page.locator(".pg-rail-pill")).toContainText("예전 결과 기준");         // 관문은 지우지 않고 그렇다고 말한다

  // 바뀐 곳만 계산 — 낡은 노드만 목표로 하는 부분 계산
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-stale-run").click();
  const url = (await resp).url();
  for (const id of down) expect(url, `${id} 가 목표에 있다`).toContain(id);
  await expect(page.locator(".pg-summary--stale")).toHaveCount(0);
  for (const id of down) expect(await isStale(page, id), `${id} — 다시 계산했다`).toBe(false);
  await expect(page.locator(".pg-summary--partial")).toBeVisible();
});

test("위만 다시 계산해도 그 전 값으로 계산한 아래 노드는 계속 낡았다(서명 사슬)", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  const doc = await wip(page);
  const below = [...downstream(doc, "optimizer")].filter((id) => id !== "optimizer");
  expect(below.length).toBeGreaterThan(0);
  await setModel(page, "흔들림 최소");
  await node(page, "optimizer").click();
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.keyboard.press("Shift+Enter");                                                // 여기까지 계산 — 조상만
  await resp;
  await expect(page.locator(".pg-summary--stale")).toHaveAttribute("data-count", String(below.length));
  expect(await isStale(page, "optimizer"), "다시 계산한 노드는 새것").toBe(false);
  for (const id of below) expect(await isStale(page, id), `${id} — 위가 바뀐 뒤 다시 계산하지 않았다`).toBe(true);
});

test("되돌리기로 계산한 그래프로 돌아가면 낡음이 풀리고, 다시하기로 돌아오면 다시 낡는다(짝)", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  await setModel(page, "흔들림 최소");
  await expect(page.locator(".pg-summary--stale")).toBeVisible();
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  await expect(page.locator(".pg-summary--stale")).toHaveCount(0);
  expect(await isStale(page, "optimizer")).toBe(false);
  await page.keyboard.press("Control+Shift+z");
  await expect(page.locator(".pg-summary--stale")).toBeVisible();
  expect(await isStale(page, "optimizer")).toBe(true);
});

test("영향 줄: 수 = 이 노드 + 하류 · 올리면 그 노드들만 또렷하다 · 내는 것은 받는 노드(누르면 고름)", async ({ page }) => {
  await openCanvas(page);
  const doc = await wip(page);
  const down = downstream(doc, "optimizer");
  await node(page, "optimizer").click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  const impact = page.locator(".pg-impact");
  await expect(impact).toHaveAttribute("data-count", String(down.size));
  await expect(impact).toContainText(`${down.size}개 노드가 다시 계산돼요`);
  await impact.hover();
  for (const n of doc.nodes) {
    const cls = (await page.locator(`.react-flow__node[data-id="${n.id}"]`).getAttribute("class")) ?? "";
    expect(cls.includes("pg-dim"), `${n.id}`).toBe(!down.has(n.id));
  }
  await page.mouse.move(5, 5);
  await expect(page.locator(".react-flow__node.pg-dim")).toHaveCount(0);

  // 내는 것 — 받는 노드 이름. 누르면 그 노드가 골라진다.
  const consumers = doc.edges.filter((e) => e.source === "optimizer").map((e) => e.target);
  expect(consumers.length).toBeGreaterThan(0);
  const gives = page.locator(".pg-gives-node");
  await expect(gives).toHaveCount(consumers.length);
  const first = await gives.first().getAttribute("data-node");
  expect(consumers).toContain(first);
  await gives.first().click();
  await expect(page.locator(`.react-flow__node[data-id="${first}"]`)).toHaveClass(/selected/);
});

test("하류가 없는 노드: 영향 줄은 이 노드만 · 아무도 받지 않는 출력은 그렇다고 말한다(짝)", async ({ page }) => {
  await openCanvas(page);
  const doc = await wip(page);
  const leaf = doc.nodes.find((n) => !doc.edges.some((e) => e.source === n.id)
    && (doc.edges.some((e) => e.target === n.id)))!;
  expect(leaf, "끝 노드가 있어야 한다").toBeTruthy();
  await node(page, leaf.id).click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await expect(page.locator(".pg-impact")).toHaveAttribute("data-count", "1");
  await expect(page.locator(".pg-impact")).toContainText("이 노드만 다시 계산돼요");
  await expect(page.locator(".pg-gives-node")).toHaveCount(0);
  const none = page.locator(".pg-gives-none");
  if (await page.locator(".pg-gives-row").count()) await expect(none.first()).toContainText("아직 아무 노드도 받지 않아요");
});
