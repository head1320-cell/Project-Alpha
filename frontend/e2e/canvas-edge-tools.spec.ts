import { test, expect, type Page } from "@playwright/test";
import type { NodeCatalogEntry } from "../src/entities/portfolio-graph/types";

/**
 * CF 3부 R5 · 선 도구줄 + 선 우클릭 (스펙 §8.3 결정 5 · 2026-10-31 결정 넷)
 *  ① 고른 선 하나에만 도구줄(끊기 · 사이에 넣기 · 꺾는 점 · 묻기) — ★선 가운데 · 카드 위층★(선이 카드 뒤를 지나도 누를 수 있다) · 확대해도 크기 같음 ·
 *     종류 알약과 겹치지 않음 · 접힌 상자의 대리 선에는 없다
 *  ② 사이에 넣기 = 도구줄 아래 작은 목록(선 탭과 같은 후보 — 같은 값을 받아 같은 값을 내는 노드) · 없으면 까닭 한 줄
 *  ③ 끊기 안내 하나로 — 도구줄 · 우클릭 · 선 탭 [선 끊기] · Delete 키가 같은 문장(R2 `deleteNote`)
 *  ④ 우클릭 = 같은 넷 · 사이에 넣기…는 같은 메뉴가 후보 목록 + [뒤로] · 대리 선은 까닭 + [상자 펼치기] · 빈 곳은 빈 곳 메뉴
 */

const API = "http://localhost:8000/api/v1";
const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const NODES = [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
               n("estimate", "estimate", 660, 0), n("optimizer", "optimizer", 990, 0)];
const EDGES = [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
               e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")];
const CORE = { ...F, nodes: NODES, edges: EDGES };
const UR = "universe.universe->returns.universe";        // 종목 — 후보 있음
const RO = "returns.returns->optimizer.returns";          // '기대 수익 추정' 카드 뒤를 지난다
const EO = "estimate.belief->optimizer.belief";           // 기대 수익 — 후보 없음
const HEAD = { x: 30, y: 14 };
type Doc = { nodes: { id: string; type: string }[]; edges: { id: string; source: string; target: string; waypoints?: { x: number; y: number }[] }[];
             groups?: { id: string; collapsed?: boolean }[] };

async function open(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("r5_seeded")) return;
      sessionStorage.setItem("r5_seeded", "1");
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
const tb = (page: Page) => page.locator(".pg-edge-tb");
const btn = (page: Page, action: string) => page.locator(`.pg-edge-tb [data-action="${action}"]`);
const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const undoBtn = (page: Page) => page.getByRole("button", { name: "되돌리기 (Ctrl+Z)" });
const canvas = (page: Page) => page.locator(".pg-canvas");
const wip = async (page: Page): Promise<Doc> => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}"));
const blank = (page: Page) => page.locator(".react-flow__pane").click({ position: { x: 360, y: 24 } });
/** 그린 선 위의 한 점(화면 좌표) — 길이의 t 지점. */
const onWire = (page: Page, id: string, t = 0.5) => page.locator(`.react-flow__edge[data-id="${id}"] path.react-flow__edge-path`).evaluate((el, k) => {
  const g = el as SVGPathElement;
  const q = g.getPointAtLength(g.getTotalLength() * k);
  const m = g.getScreenCTM()!;
  return { x: q.x * m.a + m.e, y: q.y * m.d + m.f };
}, t);
/** 선 고르기 — 카드 뒤를 지나는 선도 있어 선 요소에 바로 누름을 보낸다. */
async function pickWire(page: Page, id: string) {
  await page.locator(`.react-flow__edge[data-id="${id}"]`).dispatchEvent("click");
  await expect(page.locator(`.react-flow__edge[data-id="${id}"]`)).toHaveClass(/selected/);
}
async function zoomTo(page: Page, level: "far" | "mid" | "near") {
  for (let i = 0; i < 16; i++) {
    const z = await canvas(page).getAttribute("data-zoom");
    if (z === level) return;
    const wantIn = level === "near" || (level === "mid" && z === "far");
    await page.locator(wantIn ? ".react-flow__controls-zoomin" : ".react-flow__controls-zoomout").click();
    await page.waitForTimeout(120);
  }
  await expect(canvas(page)).toHaveAttribute("data-zoom", level);
}
const catalog = async (page: Page): Promise<NodeCatalogEntry[]> => (await (await page.request.get(`${API}/allocation/graph/node-types`)).json()).nodes;
/** 시험이 카탈로그에서 직접 센 후보 — 같은 값을 받아 같은 값을 내는 노드. */
const expected = (cat: NodeCatalogEntry[], type: string) =>
  cat.filter((c) => c.inputs.some((i) => i.type === type) && c.outputs.some((o) => o.type === type)).map((c) => c.type).sort();
async function compute(page: Page) {
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 90_000 });
}

test.use({ viewport: { width: 1440, height: 900 } });

test("R5 · 도구줄은 고른 선 하나에만 (짝: 안 고르면 · 빈 곳을 누르면 · 노드를 고르면 없다)", async ({ page }) => {
  await open(page, CORE);
  await expect(tb(page)).toHaveCount(0);
  await pickWire(page, UR);
  await expect(tb(page)).toHaveCount(1);
  await expect(tb(page)).toHaveAttribute("data-edge-id", UR);
  for (const a of ["cut", "insert", "waypoint", "ask"]) await expect(btn(page, a)).toBeVisible();
  await expect(btn(page, "cut")).toHaveText(/끊기/);
  await blank(page);
  await expect(tb(page)).toHaveCount(0);
  await pickWire(page, EO);
  await expect(tb(page)).toHaveAttribute("data-edge-id", EO);
  await node(page, "returns").click({ position: HEAD });
  await expect(tb(page)).toHaveCount(0);
});

test("R5 · 세 확대에서 화면 크기가 같고 종류 알약과 겹치지 않는다", async ({ page }) => {
  await open(page, CORE);
  await pickWire(page, UR);
  const sizes: { w: number; h: number }[] = [];
  for (const lv of ["far", "mid", "near"] as const) {
    await zoomTo(page, lv);
    const b = (await tb(page).boundingBox())!;
    sizes.push({ w: b.width, h: b.height });
  }
  for (const s of sizes) { expect(Math.abs(s.w - sizes[0].w)).toBeLessThanOrEqual(1); expect(Math.abs(s.h - sizes[0].h)).toBeLessThanOrEqual(1); }
  await zoomTo(page, "mid");
  const t = (await tb(page).boundingBox())!;
  const p = (await page.locator(`.pg-wire-type[data-edge-id="${UR}"]`).boundingBox())!;
  expect(t.y + t.height <= p.y || p.y + p.height <= t.y || t.x + t.width <= p.x || p.x + p.width <= t.x, "도구줄과 알약이 겹친다").toBe(true);
});

test("R5 · 카드 뒤를 지나는 선에서도 도구줄이 맨 위 — 누를 수 있다", async ({ page }) => {
  await open(page, CORE);
  await pickWire(page, RO);
  // 도구줄과 '기대 수익 추정' 카드가 실제로 겹치는 칸 — 겹침이 없으면 이 시험은 아무것도 재지 않는다(공허한 통과 금지).
  const b = (await tb(page).boundingBox())!;
  const c = (await page.locator('.react-flow__node[data-id="estimate"]').boundingBox())!;
  const x0 = Math.max(b.x, c.x), x1 = Math.min(b.x + b.width, c.x + c.width);
  const y0 = Math.max(b.y, c.y), y1 = Math.min(b.y + b.height, c.y + c.height);
  expect(x1 - x0 > 20 && y1 - y0 > 6, "도구줄이 카드와 겹치지 않아 층을 잴 수 없다").toBe(true);
  const top = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.closest(".pg-edge-tb") !== null, { x: (x0 + x1) / 2, y: (y0 + y1) / 2 });
  expect(top, "도구줄이 카드 밑에 깔렸다").toBe(true);
  await btn(page, "waypoint").click();
  await expect.poll(async () => ((await wip(page)).edges.find((x) => x.id === RO)?.waypoints ?? []).length).toBe(1);
});

test("R5 · 끊기 — Delete 키·선 탭과 같은 문장 · 한 단계", async ({ page }) => {
  await open(page, CORE);
  await pickWire(page, UR);
  // 도구줄 우클릭은 선 메뉴를 열지 않는다(누름이 선까지 번지지 않음)
  await btn(page, "waypoint").click({ button: "right" });
  await expect(page.locator(".pg-ctx")).toHaveCount(0);
  await btn(page, "cut").click();
  await expect(page.locator(".pg-note")).toHaveText(/^선 1개를 끊었어요\.\s*되돌리기/);
  await expect.poll(async () => (await wip(page)).edges.some((x) => x.id === UR)).toBe(false);
  await expect(page.locator('.pg-tab[data-tab="wire"]')).toHaveCount(0);           // 끊은 선을 다시 고르지 않는다(누름이 선까지 번지지 않음)
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).edges.some((x) => x.id === UR)).toBe(true);
  await expect(undoBtn(page)).toBeDisabled();
  // 선 탭 [선 끊기]도 같은 길·같은 문장
  await pickWire(page, UR);
  await page.locator(".pg-wire-cut").click();
  await expect(page.locator(".pg-note")).toHaveText(/^선 1개를 끊었어요\.\s*되돌리기/);
});

test("R5 · (짝) 계산 뒤 끊으면 하류 수를 말한다", async ({ page }) => {
  test.setTimeout(150_000);
  await open(page, CORE);
  await compute(page);
  await pickWire(page, EO);
  await btn(page, "cut").click();
  await expect(page.locator(".pg-note")).toHaveText(/선 1개를 끊었어요 — 하류 노드 1개는 이제 예전 결과예요\./);
});

test("R5 · 사이에 넣기 — 후보 = 카탈로그에서 센 것 · 고르면 두 선 사이 · 한 단계 (짝: 후보 없는 선은 까닭)", async ({ page }) => {
  await open(page, CORE);
  const cat = await catalog(page);
  await pickWire(page, UR);
  await btn(page, "insert").click();
  const kinds = await page.locator(".pg-edge-tb-list [data-kind]").evaluateAll((els) => els.map((x) => x.getAttribute("data-kind")!).sort());
  expect(kinds).toEqual(expected(cat, "Universe"));
  expect(kinds.length).toBeGreaterThan(0);
  // 목록은 선 글자층(종류 알약)보다 위 — 알약이 목록 밑에 있어야 잴 수 있다(겹침부터 확인 · 공허한 통과 금지)
  const lb = (await page.locator(".pg-edge-tb-list").boundingBox())!;
  const pb = (await page.locator(`.pg-wire-type[data-edge-id="${UR}"]`).boundingBox())!;
  const pc = { x: pb.x + pb.width / 2, y: pb.y + pb.height / 2 };
  expect(pc.x > lb.x && pc.x < lb.x + lb.width && pc.y > lb.y && pc.y < lb.y + lb.height, "알약이 목록 밑에 있지 않아 층을 잴 수 없다").toBe(true);
  // 알약은 누름을 받지 않아(pointer-events: none) elementFromPoint 가 건너뛴다 — 그리는 순서를 재려고 시험 안에서만 켠다.
  const onTop = await page.evaluate(({ x, y, id }) => {
    const pill = document.querySelector<HTMLElement>(`.pg-wire-type[data-edge-id="${id}"]`)!;
    pill.style.pointerEvents = "auto";
    const hit = document.elementFromPoint(x, y)?.closest(".pg-edge-tb-list") !== null;
    pill.style.pointerEvents = "";
    return hit;
  }, { ...pc, id: UR });
  expect(onTop, "종류 알약이 넣기 목록 위에 그려졌다").toBe(true);
  await page.locator(".pg-edge-tb-list [data-kind]").first().click();
  const d = await wip(page);
  const added = d.nodes.find((x) => !NODES.some((m) => m.id === x.id))!;
  expect(added.type).toBe(kinds[0]);
  expect(d.edges.some((x) => x.id === UR)).toBe(false);
  expect(d.edges.some((x) => x.source === "universe" && x.target === added.id)).toBe(true);
  expect(d.edges.some((x) => x.source === added.id && x.target === "returns")).toBe(true);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(4);
  await expect(undoBtn(page)).toBeDisabled();
  // 짝 — 기대 수익(Belief)을 받아 기대 수익을 내는 노드는 없다
  expect(expected(cat, "Belief")).toEqual([]);
  await pickWire(page, EO);
  await btn(page, "insert").click();
  await expect(page.locator(".pg-edge-tb-list [data-kind]")).toHaveCount(0);
  await expect(page.locator(".pg-edge-tb-list")).toContainText("받아");
  await expect(page.locator(".pg-edge-tb-list")).toContainText("노드가 없어요");
});

test("R5 · 꺾는 점 — 그린 선 가운데에 하나 · 한 단계", async ({ page }) => {
  await open(page, CORE);
  await pickWire(page, UR);
  const mid = await onWire(page, UR, 0.5);
  await btn(page, "waypoint").click();
  await expect.poll(async () => ((await wip(page)).edges.find((x) => x.id === UR)?.waypoints ?? []).length).toBe(1);
  const dot = (await page.locator(`.pg-waypoint[data-edge-id="${UR}"]`).boundingBox())!;
  expect(Math.hypot(dot.x + dot.width / 2 - mid.x, dot.y + dot.height / 2 - mid.y)).toBeLessThan(16);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => ((await wip(page)).edges.find((x) => x.id === UR)?.waypoints ?? []).length).toBe(0);
  await expect(undoBtn(page)).toBeDisabled();
});

test("R5 · 도구줄 누름은 선 누르기로 번지지 않는다 — 옮겨 둔 오른쪽 창 탭이 그대로 (짝: 선을 누르면 '선' 탭으로)", async ({ page }) => {
  await open(page, CORE);
  await pickWire(page, UR);
  await expect(page.locator('.pg-tab[data-tab="wire"]')).toHaveClass(/\bon\b/);
  await page.locator('.pg-tab[data-tab="story"]').click();
  await expect(page.locator('.pg-tab[data-tab="story"]')).toHaveClass(/\bon\b/);
  await expect(tb(page)).toBeVisible();                                   // 탭을 옮겨도 선은 고른 채
  await btn(page, "insert").click();                                      // 목록 열기 · 닫기 — 둘 다 선까지 번지면 탭이 '선' 으로 돌아간다
  await expect(page.locator(".pg-edge-tb-list")).toBeVisible();
  await btn(page, "insert").click();
  await expect(page.locator(".pg-edge-tb-list")).toHaveCount(0);
  await btn(page, "waypoint").click();
  await expect.poll(async () => ((await wip(page)).edges.find((x) => x.id === UR)?.waypoints ?? []).length).toBe(1);
  await expect(page.locator('.pg-tab[data-tab="story"]')).toHaveClass(/\bon\b/);
  // 짝 — 선 자체를 누르면 '선' 탭으로(번짐을 재는 길이 살아 있다)
  await pickWire(page, UR);
  await expect(page.locator('.pg-tab[data-tab="wire"]')).toHaveClass(/\bon\b/);
});

test("R5 · 묻기 — 오른쪽 창의 묻기 칸으로 · 로그아웃이면 로그인 안내 · 계산 전이면 계산하라고 (짝: 로그인·계산 뒤면 칸에 초점)", async ({ page }) => {
  test.setTimeout(150_000);
  await open(page, CORE);
  await pickWire(page, UR);
  await btn(page, "ask").click();
  await expect(page.locator(".pg-ask-login")).toBeVisible();
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  const token = (await r.json()).access_token as string;
  await page.evaluate((t) => localStorage.setItem("project-alpha.auth-token", t), token);
  await page.reload();
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await pickWire(page, UR);
  await btn(page, "ask").click();
  await expect(page.locator(".pg-ask")).toContainText("계산한 뒤에 물을 수 있어요");     // 묻기 칸은 계산한 뒤에만 열린다
  await compute(page);
  await pickWire(page, UR);
  await btn(page, "ask").click();
  await expect(page.locator(".pg-ask-text")).toBeFocused();
});

test("R5 · 우클릭 — 같은 넷 · 사이에 넣기…는 후보 + [뒤로] (짝: 빈 곳은 빈 곳 메뉴)", async ({ page }) => {
  await open(page, CORE);
  const cat = await catalog(page);
  const at = await onWire(page, UR, 0.5);
  await page.mouse.click(at.x, at.y, { button: "right" });
  const menu = page.locator('.pg-ctx[aria-label="선 메뉴"]');
  await expect(menu).toBeVisible();
  await expect(page.locator(`.react-flow__edge[data-id="${UR}"]`)).toHaveClass(/selected/);   // 우클릭이 그 선을 고른다
  const acts = () => menu.locator(".pg-ctx-item").evaluateAll((els) => els.map((x) => x.getAttribute("data-action")));
  expect(await acts()).toEqual(["cut", "insert", "waypoint", "ask"]);
  await menu.locator('[data-action="insert"]').click();
  await expect(menu.locator('[data-action="back"]')).toBeVisible();
  expect((await acts()).filter((a) => a!.startsWith("insert:")).map((a) => a!.slice(7)).sort()).toEqual(expected(cat, "Universe"));
  await menu.locator('[data-action="back"]').click();
  expect(await acts()).toEqual(["cut", "insert", "waypoint", "ask"]);
  await page.keyboard.press("Escape");
  // 후보 없는 선 — 사이에 넣기가 꺼지고 까닭을 이름에
  const at2 = await onWire(page, EO, 0.5);
  await page.mouse.click(at2.x, at2.y, { button: "right" });
  await expect(menu.locator('[data-action="insert"]')).toBeDisabled();
  await expect(menu.locator('[data-action="insert"]')).toContainText("노드가 없어요");
  await page.keyboard.press("Escape");
  // 짝 — 빈 곳
  await page.locator(".react-flow__pane").click({ position: { x: 700, y: 640 }, button: "right" });
  await expect(page.locator('.pg-ctx[aria-label="캔버스 메뉴"]')).toBeVisible();
  await expect(page.locator('.pg-ctx [data-action="add-here"]')).toBeVisible();
});

test("R5 · 접힌 상자의 대리 선 — 도구줄 없음 · 우클릭은 까닭 + [상자 펼치기]", async ({ page }) => {
  await open(page, { ...CORE, groups: [{ id: "g1", label: "묶음", members: ["returns", "estimate"], collapsed: true }] });
  await pickWire(page, UR);                                                      // 종목 → 상자의 대리 선
  await expect(tb(page)).toHaveCount(0);
  const at = await onWire(page, UR, 0.5);
  await page.mouse.click(at.x, at.y, { button: "right" });
  const menu = page.locator('.pg-ctx[aria-label="선 메뉴"]');
  await expect(menu.locator('[data-action="proxy-why"]')).toBeDisabled();
  await expect(menu.locator('[data-action="proxy-why"]')).toContainText("상자를 펼치면");
  await expect(menu.locator('[data-action="cut"]')).toHaveCount(0);
  await menu.locator('[data-action="unfold"]').click();
  await expect.poll(async () => (await wip(page)).groups?.[0]?.collapsed ?? false).toBe(false);
  await pickWire(page, UR);
  await expect(tb(page)).toHaveCount(1);                                         // 펼치면 보통 선
});

test.describe("꺾는 점과 겹칠 때", () => {
  test.use({ viewport: { width: 1280, height: 720 } });
  test("R5 · 도구줄이 이 선의 꺾는 점을 덮지 않는다 — 덮을 자리면 알약 아래로 · 점을 끌 수 있다 (짝: 점이 없으면 알약 위)", async ({ page }) => {
    const W = "universe.universe->returns.universe";
    const doc = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930"] }), n("returns", "returns", 660, 220), n("optimizer", "optimizer", 1100, 220)],
                  edges: [{ ...e("universe", "universe", "returns", "universe"), waypoints: [{ x: 440, y: 110 }] }] };
    await open(page, doc);
    await pickWire(page, W);
    const dot = page.locator(`.pg-waypoint[data-edge-id="${W}"]`);
    const b = (await dot.boundingBox())!;
    const hit = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.classList.contains("pg-waypoint") ?? false, { x: b.x + b.width / 2, y: b.y + b.height / 2 });
    expect(hit, "도구줄이 꺾는 점을 덮었다").toBe(true);
    await expect(tb(page)).toHaveAttribute("data-place", "below");
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2 + 40, b.y + b.height / 2 + 60, { steps: 6 });
    await page.mouse.up();
    await expect.poll(async () => (await wip(page)).edges[0].waypoints?.[0]?.y ?? 110).toBeGreaterThan(110);
  });
});

test("R5 · (짝) 꺾는 점이 없는 선은 도구줄이 알약 위", async ({ page }) => {
  await open(page, CORE);
  await pickWire(page, UR);
  await expect(tb(page)).toHaveAttribute("data-place", "above");
});
