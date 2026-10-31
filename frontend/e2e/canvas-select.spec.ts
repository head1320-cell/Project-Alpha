import { test, expect, type Page } from "@playwright/test";

/**
 * CF 3부 R2 · 고르기·지우기 쓰기 (스펙 §8.3 결정 2·3)
 *  ① Shift 상자는 카드에 ★닿기만 해도★ 고른다(`SelectionMode.Partial`) — 끌기는 화면 이동 그대로
 *  ② Ctrl+A = 보이는 노드 모두(접힌 상자 안 노드 · 입력 칸 안은 아님 · 들어간 상자면 그 멤버만) · Esc 는 기존 차례(원인 길 → 들어간 상자 → 관문)의 ★맨 끝★에 고르기 풀기 ·
 *     열린 메뉴가 있으면 Esc 는 그 메뉴만 닫는다
 *  ③ 지우면 바로 지우고 토스트로 무엇이 사라졌는지 말한다 — 노드 N · 그중 계산 결과가 있던 것 R · 새로 예전 결과가 된 하류 D(0 이면 말하지 않음) + [되돌리기] 한 번
 *  ④ 명령 찾기 — 모두 고르기 · 고른 노드 N개 지우기(여럿일 때만) · 정렬 · 여럿 우클릭 메뉴에 'N개 지우기'
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const NODES = [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
               n("estimate", "estimate", 660, 0), n("optimizer", "optimizer", 990, 0)];
const EDGES = [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
               e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")];
const CORE = { ...F, nodes: NODES, edges: EDGES };
const FOLDED = { ...CORE, groups: [{ id: "g1", label: "묶음", members: ["universe", "returns"], collapsed: true }] };
const GROUPED = { ...CORE, groups: [{ id: "g1", label: "묶음", members: ["universe", "returns"] }] };
const HEAD = { x: 30, y: 14 };

type Doc = { nodes: { id: string; position: { x: number; y: number } }[]; edges: { id: string }[]; groups?: unknown[]; branches?: unknown[] };

async function open(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("r2_seeded")) return;
      sessionStorage.setItem("r2_seeded", "1");
      for (const k of ["alpha_pg_panels", "alpha_pg_view", "alpha_pg_left_tab"]) localStorage.removeItem(k);
      localStorage.setItem("alpha_pg_welcomed", "1");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(350);
}

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const undoBtn = (page: Page) => page.getByRole("button", { name: "되돌리기 (Ctrl+Z)" });
const selN = (page: Page) => page.locator(".pg-selbar-n");
const picked = (page: Page) => page.locator(".pg-node.pg-node--selected");
const wip = async (page: Page): Promise<Doc> => JSON.parse(JSON.stringify(
  await page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")),
  (k, v) => (typeof v === "number" && (k === "x" || k === "y") ? Math.round(v) : v)));
const graphOf = (d: Doc) => ({ nodes: d.nodes, edges: d.edges, groups: d.groups ?? [], branches: d.branches ?? [] });
const blank = (page: Page) => page.locator(".react-flow__pane").click({ position: { x: 360, y: 24 } });
async function pick(page: Page, ids: string[]) {
  await blank(page);
  await node(page, ids[0]).click({ position: HEAD });
  for (const id of ids.slice(1)) await node(page, id).click({ position: HEAD, modifiers: ["Control"] });
  await expect(selN(page)).toHaveText(`${ids.length}개 골랐어요`);
}
async function shiftBox(page: Page, from: { x: number; y: number }, to: { x: number; y: number }) {
  await page.keyboard.down("Shift");
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 8 });
  await page.mouse.up();
  await page.keyboard.up("Shift");
}
async function compute(page: Page) {
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 90_000 });
  await expect(page.locator(".pg-node--stale")).toHaveCount(0);
}

test.use({ viewport: { width: 1440, height: 900 } });

// ── ① 닿기만 해도 ────────────────────────────────────────────────────────────

test("R2 · Shift 상자가 두 카드의 귀퉁이에만 닿아도 둘 다 고른다 (짝: 닿지 않은 카드는 고르지 않는다)", async ({ page }) => {
  await open(page, CORE);
  const a = (await node(page, "universe").boundingBox())!;
  const b = (await node(page, "returns").boundingBox())!;
  // 상자: universe 오른쪽 끝 30px ~ returns 왼쪽 30px, 위 40px — 어느 카드도 다 들어가지 않는다
  await shiftBox(page, { x: a.x + a.width - 30, y: a.y - 24 }, { x: b.x + 30, y: b.y + 40 });
  await expect(selN(page)).toHaveText("2개 골랐어요");
  await expect(picked(page)).toHaveCount(2);
  await expect(node(page, "estimate")).not.toHaveClass(/pg-node--selected/);
  // 짝 — 카드 사이 빈 곳만 덮으면 아무것도 고르지 않는다
  await blank(page);
  await shiftBox(page, { x: a.x + a.width + 8, y: a.y - 24 }, { x: b.x - 8, y: b.y + 40 });
  await expect(picked(page)).toHaveCount(0);
});

// ── ② Ctrl+A · Esc ───────────────────────────────────────────────────────────

test("R2 · Ctrl+A 는 보이는 노드만 고른다 — 접힌 상자 안 노드는 빼고 (짝: 입력 칸 안에서는 글자를 고른다)", async ({ page }) => {
  await open(page, FOLDED);
  await blank(page);
  await page.keyboard.press("Control+a");
  await expect(selN(page)).toHaveText("2개 골랐어요");
  await expect(node(page, "estimate")).toHaveClass(/pg-node--selected/);
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--selected/);
  await page.keyboard.press("Escape");
  await expect(picked(page)).toHaveCount(0);
  // 짝 — 이름 칸 안의 Ctrl+A 는 캔버스가 가로채지 않는다
  const name = page.locator(".pg-name").first();
  await name.click();
  await page.keyboard.press("Control+a");
  await expect(picked(page)).toHaveCount(0);
  // 짝 — 캔버스 밖 도구줄 단추에 초점이 있으면 브라우저 몫이다
  await page.locator(".pg-run").focus();
  await page.keyboard.press("Control+a");
  await expect(picked(page)).toHaveCount(0);
});

test("R2 · 들어간 상자 안에서 Ctrl+A 는 그 상자 멤버만 · Esc 는 상자 먼저 나가고 다음 Esc 가 고르기를 푼다", async ({ page }) => {
  await open(page, GROUPED);
  await page.locator('.react-flow__node[data-id="frame:g1"]').dblclick({ position: { x: 8, y: 60 } });
  await expect(page.locator(".pg-crumb-root")).toBeVisible();
  await page.keyboard.press("Control+a");
  // 고른 것이 한 상자의 멤버 전부면 고르기 띠 대신 상자가 말한다(기존 동작) — 고른 카드로 센다
  await expect(picked(page)).toHaveCount(2);
  await expect(node(page, "universe")).toHaveClass(/pg-node--selected/);
  await expect(node(page, "returns")).toHaveClass(/pg-node--selected/);
  await expect(node(page, "estimate")).not.toHaveClass(/pg-node--selected/);
  await page.keyboard.press("Escape");                                          // 상자부터 나간다 — 고르기는 그대로
  await expect(page.locator(".pg-crumb-root")).toHaveCount(0);
  await expect(picked(page)).toHaveCount(2);
  await page.keyboard.press("Escape");                                          // 그다음 고르기를 푼다
  await expect(picked(page)).toHaveCount(0);
});

test("R2 · 메뉴가 열린 채 Esc 는 메뉴만 닫는다 — 우클릭 메뉴 · 정렬 메뉴 (고르기는 그대로)", async ({ page }) => {
  await open(page, CORE);
  await pick(page, ["universe", "returns", "estimate"]);
  await node(page, "returns").click({ button: "right", position: HEAD });
  await expect(page.locator(".pg-ctx")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".pg-ctx")).toHaveCount(0);
  await expect(selN(page)).toHaveText("3개 골랐어요");
  await page.locator(".pg-align-open").click();
  await expect(page.locator(".pg-align-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".pg-align-menu")).toHaveCount(0);
  await expect(selN(page)).toHaveText("3개 골랐어요");
  // 증거 관문 카드 — Esc 는 카드만 접는다
  const pill = page.locator(".pg-rail-pill");
  if ((await pill.getAttribute("aria-expanded")) !== "true") await pill.click();
  await expect(pill).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(pill).toHaveAttribute("aria-expanded", "false");
  await expect(selN(page)).toHaveText("3개 골랐어요");
  await page.keyboard.press("Escape");                                          // 메뉴가 없으면 고르기를 푼다
  await expect(picked(page)).toHaveCount(0);
});

test.describe("좁은 폭", () => {
  test.use({ viewport: { width: 1200, height: 860 } });
  test("R2 · '더 보기' 메뉴가 열린 채 Esc 는 메뉴만 닫는다 (고르기는 그대로)", async ({ page }) => {
    await open(page, CORE);
    // 좁은 폭에서는 관문 알약이 빈 곳(360, 24)을 덮는다 — 처음엔 고른 것이 없으니 빈 곳 누르기 없이 고른다
    await node(page, "universe").click({ position: HEAD });
    for (const id of ["returns", "estimate"]) await node(page, id).click({ position: HEAD, modifiers: ["Control"] });
    await expect(selN(page)).toHaveText("3개 골랐어요");
    await page.locator(".pg-more").click();
    await expect(page.locator(".pg-more-menu")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".pg-more-menu")).toHaveCount(0);
    await expect(selN(page)).toHaveText("3개 골랐어요");
  });
});

// ── ③ 지우기 토스트 ──────────────────────────────────────────────────────────

test("R2 · 계산한 뒤 지우면 토스트가 결과·하류를 센다 — [되돌리기] 한 번이면 노드도 결과도 그대로", async ({ page }) => {
  test.setTimeout(150_000);
  await open(page, CORE);
  await compute(page);
  const before = graphOf(await wip(page));
  await node(page, "estimate").click({ position: HEAD });
  await page.keyboard.press("Delete");
  await expect(page.locator(".pg-note")).toHaveText(/노드 1개를 지웠어요 — 그중 1개는 계산 결과가 있었어요 · 하류 노드 1개는 이제 예전 결과예요\./);
  await expect(page.locator(".pg-node--stale")).toHaveCount(1);
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--stale/);
  await page.locator(".pg-note-undo").click();
  await expect.poll(async () => graphOf(await wip(page))).toEqual(before);
  await expect(page.locator(".pg-node--stale")).toHaveCount(0);
  await expect(undoBtn(page)).toBeDisabled();
  // 선만 끊어도 하류를 센다
  await page.locator('.react-flow__edge[data-id="estimate.belief->optimizer.belief"]').click({ force: true });
  await page.keyboard.press("Delete");
  await expect(page.locator(".pg-note")).toHaveText(/선 1개를 끊었어요 — 하류 노드 1개는 이제 예전 결과예요\./);
});

test("R2 · (짝) 이미 예전 결과인 노드는 결과로도 하류로도 세지 않는다", async ({ page }) => {
  test.setTimeout(150_000);
  await open(page, CORE);
  await compute(page);
  // 이 선은 '기대 수익 추정' 카드 뒤로 지나간다 — 좌표 클릭은 카드를 누르므로 선 요소에 바로 누름을 보낸다
  await page.locator('.react-flow__edge[data-id="returns.returns->optimizer.returns"]').dispatchEvent("click");
  await expect(page.locator('.react-flow__edge[data-id="returns.returns->optimizer.returns"]')).toHaveClass(/selected/);
  await page.keyboard.press("Delete");
  await expect(page.locator(".pg-note")).toHaveText(/선 1개를 끊었어요 — 하류 노드 1개는 이제 예전 결과예요\./);
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--stale/);
  await node(page, "optimizer").click({ position: HEAD });                     // 결과는 있지만 예전 결과 — '결과' 로 세지 않는다
  await page.keyboard.press("Delete");
  await expect(page.locator(".pg-note")).toHaveText(/^노드 1개를 지웠어요\.\s*되돌리기/);
  await page.locator(".pg-note-undo").click();
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--stale/);
  await node(page, "estimate").click({ position: HEAD });                      // 하류(optimizer)가 이미 예전 결과 — 하류로 세지 않는다
  await page.keyboard.press("Delete");
  await expect(page.locator(".pg-note")).toHaveText(/^노드 1개를 지웠어요 — 그중 1개는 계산 결과가 있었어요\.\s*되돌리기/);
});

test("R2 · (짝) 계산 전에 지우면 결과·하류를 말하지 않는다 · 여럿이면 그 수", async ({ page }) => {
  await open(page, CORE);
  await pick(page, ["estimate", "optimizer"]);
  await page.keyboard.press("Delete");
  await expect(page.locator(".pg-note")).toHaveText(/^노드 2개를 지웠어요\.\s*되돌리기/);
  await expect(page.locator(".pg-note-undo")).toBeVisible();
  await page.locator(".pg-note-undo").click();
  await expect(page.locator(".pg-node")).toHaveCount(4);
});

// ── ④ 명령 · 여럿 우클릭 ─────────────────────────────────────────────────────

async function palette(page: Page) {
  await page.keyboard.press("Control+k");
  await expect(page.locator("dialog.pg-cmd")).toBeVisible();
  return page.locator(".pg-cmd-item").evaluateAll((els) => els.map((x) => x.getAttribute("data-cmd")));
}

test("R2 · 명령 — 모두 고르기 · 여럿이면 'N개 지우기'(한 단계) · 정렬 (짝: 하나면 'N개 지우기' 없음)", async ({ page }) => {
  await open(page, CORE);
  const before = graphOf(await wip(page));
  await node(page, "estimate").click({ position: HEAD });
  let ids = await palette(page);
  expect(ids).toContain("select-all");
  expect(ids).not.toContain("delete-picked");
  expect(ids).not.toContain("align:left");
  await page.keyboard.press("Escape");
  await pick(page, ["universe", "returns", "estimate"]);
  ids = await palette(page);
  expect(ids).toEqual(expect.arrayContaining(["delete-picked", "align:left", "align:center", "align:top", "align:hspace", "align:vspace"]));
  await expect(page.locator('.pg-cmd-item[data-cmd="delete-picked"]')).toContainText("고른 노드 3개 지우기");
  await page.locator('.pg-cmd-item[data-cmd="delete-picked"]').click();
  await expect(page.locator(".pg-node")).toHaveCount(1);
  await expect(page.locator(".pg-note")).toContainText("노드 3개를 지웠어요");
  await page.keyboard.press("Control+z");
  await expect.poll(async () => graphOf(await wip(page))).toEqual(before);
  await expect(undoBtn(page)).toBeDisabled();
  await blank(page);
  await palette(page);
  await page.locator('.pg-cmd-item[data-cmd="select-all"]').click();
  await expect(selN(page)).toHaveText("4개 골랐어요");
});

test("R2 · 여럿 고른 노드를 우클릭하면 'N개 지우기' (짝: 하나면 그냥 '지우기')", async ({ page }) => {
  await open(page, CORE);
  await pick(page, ["returns", "estimate"]);
  await node(page, "estimate").click({ button: "right", position: HEAD });
  await expect(page.locator('.pg-ctx-item[data-action="remove-picked"]')).toHaveText(/고른 노드 2개 지우기/);
  await expect(page.locator('.pg-ctx-item[data-action="remove"]')).toHaveText(/이 노드만 지우기/);   // 둘이 함께 있으면 무엇을 지우는지 이름이 말한다
  await page.locator('.pg-ctx-item[data-action="remove-picked"]').click();
  await expect(page.locator(".pg-node")).toHaveCount(2);
  await page.keyboard.press("Control+z");
  await expect(page.locator(".pg-node")).toHaveCount(4);
  await blank(page);
  await node(page, "optimizer").click({ button: "right", position: HEAD });
  await expect(page.locator('.pg-ctx-item[data-action="remove-picked"]')).toHaveCount(0);
  await expect(page.locator('.pg-ctx-item[data-action="remove"]')).toHaveText(/^\s*지우기\s*$/);
});
