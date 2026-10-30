import { test, expect, type Page } from "@playwright/test";

/**
 * CF 3부 R1 · 캔버스 고침 — 지우기·우클릭·상자 끌기·되돌리기 (스펙 §8.3 점검의 기존 버그)
 *  ① Delete 키로 선이 붙은 노드를 지우면 ★되돌리기 한 번★에 노드와 선이 함께 돌아온다(예전엔 React Flow 가 선 → 노드 두 번 바꿔 두 단계)
 *  ② 지운 노드가 전략의 비중을 내던 노드면 전략 `output` 을 비우고 경고를 띄운다 · 갈래 뿌리 복제를 지우면 갈래가 사라진다
 *  ③ 여럿 고른 채 우클릭하면 고르기를 지킨다 · Shift 상자로 고른 뒤 우클릭도 노드 메뉴를 연다
 *  ④ 상자 끌기는 되돌리기 한 단계 · 이동량은 격자(11)의 배수 · 묶음 이름 고치기는 이어 친 글자가 한 단계
 *  ⑤ 되돌리기 칸(50)이 다 차도 토스트에 [되돌리기] 가 붙는다
 * 모두 ★보이는 변화 0★ — 캔버스 골든 셋은 그대로여야 한다(canvas-golden.spec).
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const NODES = [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
               n("estimate", "estimate", 660, 0), n("optimizer", "optimizer", 990, 0)];
const EDGES = [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
               e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")];
const CORE = { ...F, nodes: NODES, edges: EDGES };
const HEAD = { x: 30, y: 14 };

type Pt = { x: number; y: number };
type Doc = { nodes: { id: string; position: Pt }[]; edges: { id: string }[]; groups?: { id: string; label: string; members: string[]; output?: string | null }[];
             branches?: { id: string; map: Record<string, string> }[] };

async function open(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("r1_seeded")) return;
      sessionStorage.setItem("r1_seeded", "1");
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
/** 작업 중 문서 — 위치는 정수로(측정 크기의 소수점 흔들림은 동작이 아니다). */
const wip = async (page: Page): Promise<Doc> => JSON.parse(JSON.stringify(
  await page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")),
  (k, v) => (typeof v === "number" && (k === "x" || k === "y") ? Math.round(v) : v)));
const graphOf = (d: Doc) => ({ nodes: d.nodes, edges: d.edges, groups: d.groups ?? [], branches: d.branches ?? [] });
const blank = (page: Page) => page.locator(".react-flow__pane").click({ position: { x: 360, y: 24 } });

async function pick(page: Page, ids: string[]) {
  await blank(page);
  await node(page, ids[0]).click({ position: HEAD });
  for (const id of ids.slice(1)) await node(page, id).click({ position: HEAD, modifiers: ["Control"] });
  await expect(page.locator(".pg-selbar-n")).toHaveText(`${ids.length}개 골랐어요`);
}

test.use({ viewport: { width: 1440, height: 900 } });

// ── ① 지우기 = 되돌리기 한 번 ─────────────────────────────────────────────────

test("R1 · Delete 키 — 선이 붙은 노드를 지우고 Ctrl+Z 한 번이면 노드·선 모두 원래대로 (짝: 그 뒤로 되돌릴 것이 없다)", async ({ page }) => {
  await open(page, CORE);
  await expect(undoBtn(page)).toBeDisabled();                                   // 처음엔 기록이 없다
  const before = graphOf(await wip(page));
  await node(page, "returns").click({ position: HEAD });
  await page.keyboard.press("Delete");
  await expect(node(page, "returns")).toHaveCount(0);
  await expect.poll(async () => (await wip(page)).edges.length).toBe(1);        // 닿은 선 셋이 함께 갔다
  await page.keyboard.press("Control+z");
  await expect.poll(async () => graphOf(await wip(page))).toEqual(before);
  await expect(undoBtn(page)).toBeDisabled();                                   // 짝 — 두 단계였다면 하나가 남는다
});

test("R1 · 여럿 고르고 Delete — 한 번에 되돌린다 · 선만 지워도 한 단계", async ({ page }) => {
  await open(page, CORE);
  const before = graphOf(await wip(page));
  await pick(page, ["returns", "estimate", "optimizer"]);
  await page.keyboard.press("Delete");
  await expect(page.locator(".pg-node")).toHaveCount(1);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => graphOf(await wip(page))).toEqual(before);
  await expect(undoBtn(page)).toBeDisabled();
  // 선 하나만
  await page.locator('.react-flow__edge[data-id="estimate.belief->optimizer.belief"]').click({ force: true });
  await page.keyboard.press("Delete");
  await expect.poll(async () => (await wip(page)).edges.length).toBe(3);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => graphOf(await wip(page))).toEqual(before);
  await expect(undoBtn(page)).toBeDisabled();
});

// ── ② 전략 출력 · 갈래 ────────────────────────────────────────────────────────

const STRAT = { ...CORE, groups: [{ id: "g1", label: "전략 1", kind: "strategy", color: 0, members: NODES.map((x) => x.id), output: "optimizer" }] };

test("R1 · 전략의 비중을 내던 노드를 지우면 output 을 비우고 경고 (짝: 다른 멤버는 그대로)", async ({ page }) => {
  await open(page, STRAT);
  const frame = page.locator('.pg-group[data-group-id="g1"]');
  await expect(frame.locator(".pg-group-warn")).toHaveCount(0);
  await node(page, "estimate").click({ position: HEAD });
  await page.keyboard.press("Delete");
  await expect.poll(async () => (await wip(page)).groups?.[0]?.output).toBe("optimizer");   // 짝
  await expect(frame.locator(".pg-group-warn")).toHaveCount(0);
  await node(page, "optimizer").click({ position: HEAD });
  await page.keyboard.press("Delete");
  await expect.poll(async () => (await wip(page)).groups?.[0]?.output).toBeNull();
  await expect(frame.locator(".pg-group-warn")).toBeVisible();
  await page.keyboard.press("Control+z");                                       // 되돌리면 출력도 돌아온다
  await expect.poll(async () => (await wip(page)).groups?.[0]?.output).toBe("optimizer");
  await expect(frame.locator(".pg-group-warn")).toHaveCount(0);
});

const BRANCHED = {
  ...F,
  nodes: [...NODES, n("estimate_b", "estimate", 660, 330), n("optimizer_b", "optimizer", 990, 330)],
  edges: [...EDGES, e("returns", "returns", "estimate_b", "returns"), e("returns", "returns", "optimizer_b", "returns"),
          e("estimate_b", "belief", "optimizer_b", "belief")],
  branches: [{ id: "br1", label: "갈래 B", root: "estimate_b", of_root: "estimate", map: { estimate_b: "estimate", optimizer_b: "optimizer" } }],
};

test("R1 · 갈래 뿌리 복제를 지우면 갈래 틀이 사라진다 — 다른 복제가 남아 있어도", async ({ page }) => {
  await open(page, BRANCHED);
  await expect(page.locator(".pg-branch")).toHaveCount(1);
  await node(page, "estimate_b").click({ position: HEAD });
  await page.keyboard.press("Delete");
  await expect(node(page, "estimate_b")).toHaveCount(0);
  await expect(node(page, "optimizer_b")).toHaveCount(1);                     // 남은 복제는 보통 노드로 남는다
  await expect(page.locator(".pg-branch")).toHaveCount(0);
  await expect.poll(async () => (await wip(page)).branches ?? []).toEqual([]);
  await page.keyboard.press("Control+z");                                       // 되돌리면 갈래도
  await expect(page.locator(".pg-branch")).toHaveCount(1);
});

test("R1 · (짝) 뿌리가 아닌 복제를 지우면 갈래 틀은 남고 그 복제만 빠진다", async ({ page }) => {
  await open(page, BRANCHED);
  await node(page, "optimizer_b").click({ position: HEAD });
  await page.keyboard.press("Delete");
  await expect(node(page, "optimizer_b")).toHaveCount(0);
  await expect(page.locator(".pg-branch")).toHaveCount(1);
  await expect.poll(async () => (await wip(page)).branches?.[0]?.map).toEqual({ estimate_b: "estimate" });
});

test("R1 · 그림 고정한 노드를 지웠다 되돌리면 고정도 그대로", async ({ page }) => {
  await open(page, CORE);
  await node(page, "returns").click({ button: "right", position: HEAD });
  await page.locator('.pg-ctx-item[data-action="pin"]').click();
  await expect(node(page, "returns")).toHaveClass(/pg-node--pinned/);
  await node(page, "returns").click({ position: HEAD });
  await page.keyboard.press("Delete");
  await page.keyboard.press("Control+z");
  await expect(node(page, "returns")).toHaveClass(/pg-node--pinned/);
});

// ── ③ 우클릭 ─────────────────────────────────────────────────────────────────

test("R1 · 여럿 고른 채 우클릭하면 고르기를 지키고 '고른 노드 비교' 가 보인다 (짝: 밖을 우클릭하면 하나)", async ({ page }) => {
  await open(page, CORE);
  await pick(page, ["universe", "returns", "estimate"]);
  await node(page, "returns").click({ button: "right", position: HEAD });
  await expect(page.locator(".pg-ctx")).toBeVisible();
  await expect(page.locator(".pg-selbar-n")).toHaveText("3개 골랐어요");
  await expect(page.locator('.pg-ctx-item[data-action="compare"]')).toBeVisible();
  await page.keyboard.press("Escape");
  await node(page, "optimizer").click({ button: "right", position: HEAD });
  await expect(page.locator(".pg-ctx")).toBeVisible();
  await expect(page.locator(".pg-selbar-n")).toHaveCount(0);
  await expect(page.locator('.pg-ctx-item[data-action="compare"]')).toHaveCount(0);
});

test("R1 · Shift 상자로 고른 뒤 우클릭해도 노드 메뉴가 열린다", async ({ page }) => {
  await open(page, CORE);
  const a = (await node(page, "universe").boundingBox())!;
  const b = (await node(page, "returns").boundingBox())!;
  await page.keyboard.down("Shift");
  await page.mouse.move(a.x - 20, a.y - 20);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width + 20, b.y + b.height + 20, { steps: 8 });
  await page.mouse.up();
  await page.keyboard.up("Shift");
  await expect(page.locator(".pg-selbar-n")).toHaveText("2개 골랐어요");
  await page.mouse.click(b.x + 30, b.y + 14, { button: "right" });
  await expect(page.locator(".pg-ctx")).toBeVisible();
  await expect(page.locator('.pg-ctx-item[data-action="remove"]')).toBeVisible();
  await expect(page.locator(".pg-selbar-n")).toHaveText("2개 골랐어요");
});

// ── ④ 상자 끌기 · 이름 ────────────────────────────────────────────────────────

const GROUPED = { ...CORE, groups: [{ id: "g1", label: "묶음", members: ["universe", "returns"] }] };

async function dragFrame(page: Page, dx: number, dy: number) {
  const f = (await page.locator('.react-flow__node[data-id="frame:g1"]').boundingBox())!;
  const at = { x: f.x + 8, y: f.y + f.height - 8 };                           // 아래 왼쪽 여백 — 카드 밖, 상자 안
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  await page.mouse.move(at.x + dx / 2, at.y + dy / 2, { steps: 6 });
  await page.mouse.move(at.x + dx, at.y + dy, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(150);
}
const pos = async (page: Page, id: string) => (await wip(page)).nodes.find((x) => x.id === id)!.position;

test("R1 · 상자 끌기는 되돌리기 한 단계 · 멤버는 같은 만큼 · 격자 배수로 (짝: 두 번이면 둘 · 클릭만이면 0)", async ({ page }) => {
  await open(page, GROUPED);
  await expect(undoBtn(page)).toBeDisabled();
  await page.locator('.react-flow__node[data-id="frame:g1"]').click({ position: { x: 8, y: 60 } });   // 클릭만
  await expect(undoBtn(page)).toBeDisabled();
  const u0 = await pos(page, "universe");
  const r0 = await pos(page, "returns");
  const before = graphOf(await wip(page));
  await dragFrame(page, 140, 90);
  const u1 = await pos(page, "universe");
  const r1 = await pos(page, "returns");
  const dx = u1.x - u0.x, dy = u1.y - u0.y;
  expect(dx !== 0 || dy !== 0).toBe(true);
  expect([dx % 11, dy % 11].map(Math.abs)).toEqual([0, 0]);
  expect([r1.x - r0.x, r1.y - r0.y]).toEqual([dx, dy]);                       // 멤버가 같은 만큼
  expect(await pos(page, "estimate")).toEqual((before.nodes.find((x) => x.id === "estimate"))!.position);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => graphOf(await wip(page))).toEqual(before);
  await expect(undoBtn(page)).toBeDisabled();
  await dragFrame(page, 120, 0);
  await dragFrame(page, 0, 110);
  await page.keyboard.press("Control+z");
  await expect(undoBtn(page)).toBeEnabled();                                   // 짝 — 두 번 끌면 두 단계
  await page.keyboard.press("Control+z");
  await expect.poll(async () => graphOf(await wip(page))).toEqual(before);
});

test("R1 · 묶음 이름을 이어 치면 한 단계 (짝: 0.8초 넘게 쉬고 또 고치면 두 단계)", async ({ page }) => {
  await open(page, GROUPED);
  const label = page.locator('.pg-group[data-group-id="g1"] .pg-group-label');
  await label.click();
  await label.press("End");
  await label.pressSequentially("abc", { delay: 40 });
  await expect.poll(async () => (await wip(page)).groups?.[0]?.label).toBe("묶음abc");
  await page.waitForTimeout(900);
  await label.pressSequentially("d", { delay: 40 });
  await expect.poll(async () => (await wip(page)).groups?.[0]?.label).toBe("묶음abcd");
  await page.locator(".react-flow__pane").click({ position: { x: 360, y: 24 } });
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).groups?.[0]?.label).toBe("묶음abc");
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).groups?.[0]?.label).toBe("묶음");
  await expect(undoBtn(page)).toBeDisabled();
});

// ── ⑤ 기록이 다 차도 [되돌리기] ──────────────────────────────────────────────

test("R1 · 되돌리기 칸 50개가 다 찬 뒤에도 지우기 토스트에 [되돌리기] 가 붙는다", async ({ page }) => {
  await open(page, CORE);
  const box = (await node(page, "universe").boundingBox())!;
  for (let i = 0; i < 52; i++) {                                               // 끌기 한 번 = 한 단계 · 52번이면 칸이 다 찬다
    const y = box.y + 14 + (i % 2 ? 0 : 22);
    await page.mouse.move(box.x + 30, i % 2 ? box.y + 36 : box.y + 14);
    await page.mouse.down();
    await page.mouse.move(box.x + 30, y, { steps: 3 });
    await page.mouse.up();
  }
  await node(page, "optimizer").click({ button: "right", position: HEAD });
  await page.locator('.pg-ctx-item[data-action="remove"]').click();
  await expect(page.locator(".pg-note")).toContainText("지웠어요");
  await expect(page.locator(".pg-note-undo")).toBeVisible();
});
