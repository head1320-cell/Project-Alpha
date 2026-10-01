import { test, expect, type Page } from "@playwright/test";

/**
 * BT6 · 부품 — 바꿔 끼우기 · 혼자 쓰는 도구 · 팔레트가 그래프를 안다
 * 거는 것(짝으로 항상-허용·항상-거부를 배제):
 *  · 바꿔 끼우기: 종류만 바뀌고 자리·선 수·이어진 노드는 같다 · 설정은 기본값이라고 말한다 · 되돌리기 한 번 · 바꾼 노드만 낡는다
 *  · 후보가 없는 노드는 고르기 칸 대신 이유 · 우클릭 메뉴 항목도 흐리고 이유를 단다(짝)
 *  · 후보는 모두 같은 단계이고 지금 선의 타입을 받는다(카탈로그로 확인)
 *  · 혼자 도구: 카드에 연결점이 없고 "선 없이" 줄 · 흐름 노드엔 연결점이 있다(짝) · 팔레트에선 흐름 노드 뒤 소제목 아래
 *  · 지금 이을 수 있어요: 고른 노드가 있을 때만(짝: 고르지 않으면 없다) · 모두 그 출력 타입을 받는다 · 누르면 선 하나
 */

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
type Port = { name: string; type: string };
type Entry = { type: string; stage: string; plain_label: string; inputs: Port[]; outputs: Port[] };
type Doc = { nodes: { id: string; type: string; position: { x: number; y: number } }[];
             edges: { source: string; target: string; source_port: string; target_port: string }[] };
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const catalogOf = async (page: Page) =>
  ((await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json()) as { nodes: Entry[] }).nodes;

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
}
async function settingsOf(page: Page, id: string) {
  await node(page, id).click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
}

test("바꿔 끼우기: 종류만 바뀌고 자리·선은 그대로 · 설정은 기본값이라고 말함 · 되돌리기 한 번 · 바꾼 노드만 낡음", async ({ page }) => {
  await openCanvas(page);
  const cat = await catalogOf(page);
  // 계산 뒤에 바꿔야 "바꾼 노드만 낡는다" 를 볼 수 있다
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  const d0 = await wip(page);
  const before = d0.nodes.find((n) => n.id === "risk")!;
  await settingsOf(page, "risk");
  const pick = page.locator(".pg-swap select");
  const offered = await pick.locator("option").evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value).filter(Boolean));
  // 후보는 모두 같은 단계이고 들어오는 비중 선을 받을 수 있다
  const risk = cat.find((c) => c.type === "risk")!;
  for (const k of offered) {
    const c = cat.find((x) => x.type === k)!;
    expect(c.stage, k).toBe(risk.stage);
    expect(c.inputs.some((p) => p.type === "Weights"), k).toBe(true);
  }
  expect(offered).toContain("scenario_stress");
  expect(offered).not.toContain("risk");

  await pick.selectOption("scenario_stress");
  await expect(node(page, "risk")).toHaveAttribute("data-kind", "scenario_stress");
  await expect(page.locator(".pg-note")).toContainText("설정은 기본값이에요");
  const d1 = await wip(page);
  const after = d1.nodes.find((n) => n.id === "risk")!;
  expect(after.type).toBe("scenario_stress");
  expect(after.position).toEqual(before.position);
  expect(d1.edges.length).toBe(d0.edges.length);
  expect(d1.edges.some((e) => e.source === "optimizer" && e.target === "risk" && e.target_port === "weights")).toBe(true);
  await expect(page.locator(".pg-summary--stale")).toHaveAttribute("data-count", "1");   // 바꾼 노드만(하류 없음)

  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  await expect(node(page, "risk")).toHaveAttribute("data-kind", "risk");
  await expect(page.locator(".pg-summary--stale")).toHaveCount(0);
});

test("바꿀 후보가 없으면 고르기 칸 대신 이유 · 우클릭 메뉴도 흐리고 이유(짝: 후보가 있으면 메뉴가 그 칸으로 데려간다)", async ({ page }) => {
  await openCanvas(page);
  await settingsOf(page, "optimizer");
  await expect(page.locator(".pg-swap select")).toHaveCount(0);
  await expect(page.locator(".pg-swap--none")).toContainText("다른 노드가 없어요");
  await node(page, "optimizer").click({ button: "right" });
  const item = page.locator('.pg-ctx-item[data-action="swap"]');
  await expect(item).toBeDisabled();
  await expect(item).toContainText("같은 선을 받는 다른 노드가 없어요");
  await page.keyboard.press("Escape");

  // ★짝★ 후보가 있는 노드 — 메뉴 항목이 살아 있고, 누르면 설정 판의 바꾸기 칸에 초점이 간다
  await node(page, "risk").click({ button: "right" });
  const ok = page.locator('.pg-ctx-item[data-action="swap"]');
  await expect(ok).toBeEnabled();
  await ok.click();
  await expect(page.locator(".pg-swap select")).toBeFocused();
});

test("혼자 쓰는 도구: 연결점 없이 '선 없이' 줄 · 흐름 노드엔 연결점(짝) · 팔레트에선 흐름 노드 뒤 소제목 아래", async ({ page }) => {
  await openCanvas(page);
  const cat = await catalogOf(page);
  const solo = cat.find((c) => c.stage === "check" && !c.inputs.length && !c.outputs.length)!;
  expect(solo, "확인하기 단계에 혼자 도구가 있어야 한다").toBeTruthy();
  const group = page.locator('.pg-palette-group[data-stage="check"]');
  const kinds = await group.locator(".pg-palette-item").evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")));
  const firstSolo = kinds.findIndex((k) => cat.find((c) => c.type === k && !c.inputs.length && !c.outputs.length));
  expect(firstSolo).toBeGreaterThan(0);
  expect(kinds.slice(firstSolo).every((k) => { const c = cat.find((x) => x.type === k)!; return !c.inputs.length && !c.outputs.length; }),
         "혼자 도구 뒤에 흐름 노드가 섞이지 않는다").toBe(true);
  await expect(group.locator(".pg-palette-solo")).toHaveCount(1);

  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await group.locator(`.pg-palette-item[data-kind="${solo.type}"]`).click();
  const card = page.locator(`.pg-node[data-kind="${solo.type}"]`);
  await expect(card).toHaveClass(/pg-node--solo/);
  await expect(card.locator(".pg-node-solo")).toHaveText("선 없이 혼자 계산해요");
  await expect(card.locator(".react-flow__handle")).toHaveCount(0);
  await expect(node(page, "optimizer").locator(".react-flow__handle")).not.toHaveCount(0);   // ★짝★
  await expect(node(page, "optimizer")).not.toHaveClass(/pg-node--solo/);
  // ★짝★ 입력만 없는 노드(종목 고르기 — 내기만 한다)는 혼자 도구가 아니다
  await expect(node(page, "universe")).not.toHaveClass(/pg-node--solo/);
  await expect(node(page, "universe").locator(".react-flow__handle")).not.toHaveCount(0);
});

test("지금 이을 수 있어요: 고른 노드가 있을 때만(짝) · 모두 그 출력 타입을 받음 · 누르면 선 하나", async ({ page }) => {
  await openCanvas(page);
  const cat = await catalogOf(page);
  await expect(page.locator(".pg-palette-next")).toHaveCount(0);                            // ★짝★ 아무것도 고르지 않음
  await node(page, "optimizer").click();
  const strip = page.locator(".pg-palette-next");
  await expect(strip).toBeVisible();
  await expect(strip.locator(".pg-palette-next-h")).toContainText("비중 계산");
  const outs = new Set(cat.find((c) => c.type === "optimizer")!.outputs.map((p) => p.type));
  const kinds = await strip.locator(".pg-palette-next-item").evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")!));
  expect(kinds.length).toBeGreaterThan(0);
  expect(kinds.length).toBeLessThanOrEqual(5);
  for (const k of kinds) expect(cat.find((c) => c.type === k)!.inputs.some((p) => outs.has(p.type)), k).toBe(true);

  const e0 = (await wip(page)).edges.length;
  await strip.locator(".pg-palette-next-item").first().click();
  const d = await wip(page);
  expect(d.edges.length).toBe(e0 + 1);
  const added = d.nodes.find((n) => n.type === kinds[0] && !["risk", "backtest"].includes(n.id))!;
  expect(d.edges.some((e) => e.source === "optimizer" && e.target === added.id)).toBe(true);
  // 새 노드는 자동으로 골라졌을 뿐 — 그 뒤로 사슬을 권하지 않는다
  await expect(strip).toHaveCount(0);
});
