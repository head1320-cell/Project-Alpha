import { test, expect, type Page } from "@playwright/test";
import { defaultAriaLabelConfig } from "@xyflow/system";
import type { NodeCatalogEntry } from "../src/entities/portfolio-graph/types";
import { ARIA_KO } from "../src/entities/portfolio-graph/aria";

/**
 * CF 3부 R6 · 한국어 aria + 키보드가 말한 대로 (스펙 §8.3 결정 6 · 2026-10-31 결정 셋)
 *  ① React Flow 의 영어 기본 문장(설명문 · Controls 묶음 · 선 이름 · 화살표 안내)이 남지 않는다 — 12 열쇠 모두 한국어
 *  ② 노드 이름 = 번호 · 이름 · 상태 · 확인할 곳 — 상태 말은 카드에 보이는 말과 한 구현 · 번호는 카드 배지 · 상자·선도 이름이 있다
 *  ③ 키보드: 초점 둔 노드·선 Enter = 누르기와 같음 · 화살표는 한 칸 · 연달아 누르면 되돌리기 한 단계 · 읽어 주는 말은 방향만(좌표 없음) ·
 *     정렬선 붙이기는 마우스 끌기에만 · 카드 안 입력 칸의 Enter 는 고르지 않음
 * 이름은 `getByRole(…, { name })` 으로 — Chromium 이 계산한 접근 이름을 잰다(실제 화면 읽기 프로그램은 시험하지 않음).
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
const UR = "universe.universe->returns.universe";
const RE = "returns.returns->estimate.returns";
const EO = "estimate.belief->optimizer.belief";
const RF_ENGLISH = /Press |Edge from|Control Panel|Moved selected|New position|Mini Map|Zoom In|Zoom Out|Fit View/;

type Doc = { nodes: { id: string; position: { x: number; y: number } }[]; edges: { id: string }[] };

async function open(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("r6_seeded")) return;
      sessionStorage.setItem("r6_seeded", "1");
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
const wrap = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"]`);
const card = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const wire = (page: Page, id: string) => page.locator(`.react-flow__edge[data-id="${id}"]`);
const undoBtn = (page: Page) => page.getByRole("button", { name: "되돌리기 (Ctrl+Z)" });
const pos = async (page: Page, id: string) =>
  page.evaluate((k) => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}").nodes.find((x: { id: string }) => x.id === k).position, id);
const catalog = async (page: Page): Promise<NodeCatalogEntry[]> => (await (await page.request.get(`${API}/allocation/graph/node-types`)).json()).nodes;
/** 카드의 번호 배지 + 카탈로그 쉬운 이름 — 이름의 앞부분은 화면에 보이는 것과 같아야 한다. */
async function head(page: Page, cat: NodeCatalogEntry[], id: string, type: string) {
  const num = (await card(page, id).locator(".pg-node-num").textContent())?.trim();
  return `노드 ${num}. ${cat.find((c) => c.type === type)!.plain_label}`;
}
async function compute(page: Page) {
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 90_000 });
  await expect(page.locator(".pg-node--stale")).toHaveCount(0);
}

test.use({ viewport: { width: 1440, height: 900 } });

// ── ① 영어 기본 문장 ─────────────────────────────────────────────────────────

test("R6 · 한국어 문장 표가 React Flow 열쇠 12개를 모두 덮는다 — 빠진 열쇠는 영어로 돌아온다", () => {
  expect(Object.keys(ARIA_KO).sort()).toEqual(Object.keys(defaultAriaLabelConfig).sort());
  for (const [k, v] of Object.entries(ARIA_KO)) {
    const text = typeof v === "function" ? (v as (p: { direction: string; x: number; y: number }) => string)({ direction: "right", x: 330, y: 0 }) : String(v);
    expect(text, k).toMatch(/[가-힣]/);
    expect(text, k).not.toMatch(RF_ENGLISH);
  }
  // 읽어 주는 말은 방향만 — React Flow 가 넘기는 좌표는 옮기기 전 자리라 말하지 않는다
  const live = ARIA_KO["node.a11yDescription.ariaLiveMessage"]!;
  for (const [d, word] of [["up", "위로"], ["down", "아래로"], ["left", "왼쪽으로"], ["right", "오른쪽으로"]] as const) {
    const s = live({ direction: d, x: 330, y: 0 });
    expect(s).toContain(word);
    expect(s).not.toMatch(/\d/);
  }
});

test("R6 · 화면에 React Flow 영어가 남지 않는다 — 설명문 둘 · Controls 묶음 · 선 이름", async ({ page }) => {
  await open(page, CORE);
  const texts = await page.evaluate(() => [...document.querySelectorAll('[id^="react-flow__node-desc"],[id^="react-flow__edge-desc"]')].map((d) => d.textContent ?? ""));
  expect(texts.length).toBe(2);
  for (const t of texts) { expect(t).toMatch(/[가-힣]/); expect(t).not.toMatch(RF_ENGLISH); }
  await expect(page.locator(".react-flow__controls")).not.toHaveAttribute("aria-label", /Control Panel/);
  const wires = await page.locator(".react-flow__edge").evaluateAll((els) => els.map((x) => x.getAttribute("aria-label") ?? ""));
  expect(wires.length).toBe(4);
  for (const w of wires) expect(w).not.toMatch(RF_ENGLISH);
});

// ── ② 이름 ──────────────────────────────────────────────────────────────────

test("R6 · 노드 이름 = 번호 · 이름 · 상태 — 계산 전 → 완료 → 하류만 예전 결과 (짝: 위쪽은 완료 그대로)", async ({ page }) => {
  test.setTimeout(150_000);
  await open(page, CORE);
  const cat = await catalog(page);
  const H = { u: await head(page, cat, "universe", "universe"), o: await head(page, cat, "optimizer", "optimizer") };
  expect(H.u).toBe("노드 1. 종목 고르기");                                    // 배지 번호가 흐름 순서다
  await expect(page.getByRole("group", { name: `${H.u} · 계산 전`, exact: true })).toBeVisible();
  await expect(page.getByRole("group", { name: `${H.o} · 계산 전`, exact: true })).toBeVisible();
  await compute(page);
  await expect(page.getByRole("group", { name: `${H.u} · 완료`, exact: true })).toBeVisible();
  await expect(page.getByRole("group", { name: `${H.o} · 완료`, exact: true })).toBeVisible();
  // 비중 계산으로 가는 선 하나를 끊으면 그 노드만 예전 결과(카드와 같은 말)
  await wire(page, EO).dispatchEvent("click");
  await page.keyboard.press("Delete");
  await expect(card(page, "optimizer")).toHaveClass(/pg-node--stale/);
  await expect(page.getByRole("group", { name: `${H.o} · 예전 결과`, exact: true })).toBeVisible();
  await expect(page.getByRole("group", { name: `${H.u} · 완료`, exact: true })).toBeVisible();
});

test("R6 · 설정 문제가 있으면 '설정을 확인할 곳 N곳' (짝: 문제 없는 노드는 그 말이 없다)", async ({ page }) => {
  const doc = { ...CORE, nodes: CORE.nodes.map((x) => (x.id === "returns" ? { ...x, params: { lookback_years: -3 } } : x)) };
  const v = await (await page.request.post(`${API}/allocation/graph/validate`, { data: doc })).json();
  const k = (v.errors as { node_id?: string; code: string }[]).filter((x) => x.node_id === "returns" && x.code !== "missing_input").length;
  expect(k).toBeGreaterThan(0);                                              // 문제가 정말 있어야 이 시험이 무언가를 잰다
  await open(page, doc);
  const cat = await catalog(page);
  const R = await head(page, cat, "returns", "returns");
  const U = await head(page, cat, "universe", "universe");
  await expect(page.getByRole("group", { name: `${R} · 계산 전 · 설정을 확인할 곳 ${k}곳`, exact: true })).toBeVisible();
  await expect(page.getByRole("group", { name: `${U} · 계산 전`, exact: true })).toBeVisible();
});

test("R6 · 묶음 상자 이름 — 펼침·접힘(상자 머리의 말 '묶음' 그대로) · 선 이름 — 번호 → 번호 · 값 (짝: 접힌 상자에 걸린 선)", async ({ page }) => {
  await open(page, { ...CORE, groups: [{ id: "g1", label: "묶음", members: ["universe", "returns"] }] });
  await expect(wrap(page, "frame:g1")).toHaveAttribute("aria-label", "묶음 ‘묶음’ · 노드 2개 · 펼침");
  await expect(wire(page, UR)).toHaveAttribute("aria-label", "선 1. 종목 고르기 → 2. 수익률 불러오기 · 종목");
  await page.locator('.pg-group-toggle[aria-label="묶음 접기"]').first().click();
  await expect(wrap(page, "frame:g1")).toHaveAttribute("aria-label", "묶음 ‘묶음’ · 노드 2개 · 접힘");
  // 접힌 상자에서 나가는 선은 대리 선 — 실제 끝이 숨었다고 말한다
  await expect(wire(page, RE)).toHaveAttribute("aria-label", "선 2. 수익률 불러오기 → 3. 기대 수익 추정 · 수익률 · 접힌 상자에 걸린 선");
});

// ── ③ 키보드 ─────────────────────────────────────────────────────────────────

test("R6 · 노드에 초점 + Enter = 누르기 · 화살표 한 칸 · 읽어 주는 말은 방향만 · 연달아 세 번은 되돌리기 한 번", async ({ page }) => {
  await open(page, CORE);
  await wrap(page, "returns").focus();
  await page.keyboard.press("Enter");
  await expect(card(page, "returns")).toHaveClass(/pg-node--selected/);
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await pos(page, "returns")).x).toBe(330 + 3 * 11);
  const live = page.locator('[id^="react-flow__aria-live"]');
  await expect(live).toHaveText("고른 노드를 오른쪽으로 옮겼어요.");
  await expect(undoBtn(page)).toBeEnabled();
  await undoBtn(page).click();
  await expect.poll(async () => (await pos(page, "returns")).x).toBe(330);
  await expect(undoBtn(page)).toBeDisabled();
});

test("R6 · (짝) 묶음 시간이 지난 뒤 또 누르면 되돌리기 두 단계", async ({ page }) => {
  await open(page, CORE);
  await wrap(page, "returns").focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(1_100);
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await pos(page, "returns")).x).toBe(352);
  await expect(undoBtn(page)).toBeEnabled();
  await undoBtn(page).click();
  await expect.poll(async () => (await pos(page, "returns")).x).toBe(341);
  await expect(undoBtn(page)).toBeEnabled();
});

test("R6 · 줄이 맞은 노드도 화살표 한 칸이면 한 칸 간다 — 끌기용 정렬선에 붙어 되돌아가지 않는다", async ({ page }) => {
  await open(page, CORE);                                                    // 네 카드의 윗변이 모두 y 0 에 맞아 있다
  await wrap(page, "returns").focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowDown");
  await expect.poll(async () => (await pos(page, "returns")).y).toBe(11);
  await page.keyboard.press("ArrowDown");
  await expect.poll(async () => (await pos(page, "returns")).y).toBe(22);
});

test("R6 · 선에 초점 + Enter = 선 누르기(도구줄 · '선' 탭) · Esc 풀기 · Delete 는 R2 토스트", async ({ page }) => {
  await open(page, CORE);
  await wire(page, UR).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".pg-edge-tb")).toBeVisible();
  await expect(page.locator('.pg-tab[data-tab="wire"]')).toHaveClass(/\bon\b/);
  await page.keyboard.press("Escape");
  await expect(page.locator(".pg-edge-tb")).toHaveCount(0);
  await wire(page, UR).focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Delete");
  await expect(page.locator(".pg-note")).toHaveText(/^선 1개를 끊었어요\.\s*되돌리기/);
});

test("R6 · 노드에 초점 + Enter 는 노드 누르기와 같다 — 고른 선이 풀린다 (짝: React Flow 고르기만으로는 선 도구줄이 남는다)", async ({ page }) => {
  await open(page, CORE);
  await wire(page, UR).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".pg-edge-tb")).toBeVisible();
  await wrap(page, "estimate").focus();
  await page.keyboard.press("Enter");
  await expect(card(page, "estimate")).toHaveClass(/pg-node--selected/);
  await expect(page.locator(".pg-edge-tb")).toHaveCount(0);
});

test("R6 · (짝) 카드 안 입력 칸의 Enter 는 노드를 고르지 않는다", async ({ page }) => {
  await open(page, CORE);
  // 카드 안 입력 칸은 가까이 확대했을 때만 보인다
  for (let i = 0; i < 12 && (await page.locator(".pg-canvas").getAttribute("data-zoom")) !== "near"; i++) {
    await page.locator(".react-flow__controls-zoomin").click();
    await page.waitForTimeout(120);
  }
  const field = card(page, "returns").locator(".pg-cw-select, .pg-cw-range").first();
  await expect(field).toBeVisible();
  await field.focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(300);
  await expect(card(page, "returns")).not.toHaveClass(/pg-node--selected/);
  // 짝의 짝 — 감싸개에 초점이면 고른다(가드가 모두를 막는 것이 아니다)
  await wrap(page, "returns").focus();
  await page.keyboard.press("Enter");
  await expect(card(page, "returns")).toHaveClass(/pg-node--selected/);
});
