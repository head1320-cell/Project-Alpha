import { test, expect, type Page } from "./fixtures";

/**
 * CF 3부 U4 · 유령 끌어 놓기 (스펙 §8.4 결정 4 — 사용자 결정 2026-11-01 "끌어 놓으면 바로 붙이기")
 *  · 붙이는 유령의 ★머리★를 잡아 끌어 놓으면 놓은 자리(격자 11)에 진짜 노드가 붙고, 선은 [붙이기]와 같다 · 되돌리기 한 번.
 *  · 짝: 화면 4px 안의 누름은 아무것도 붙이지 않음 · 끄는 중 Esc 는 취소 · 몸통 위 끌기는 화면 이동 · 잇기만 하는 유령(칩)은 잡을 머리가 없다.
 *  · ★실제 서버★ — 유령은 서버 규칙 추천(`/validate` procedure).
 */
const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const U = n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] });
const R = n("returns", "returns", 320, 0);
const O = n("optimizer", "optimizer", 640, 0, { model: "risk_parity" });
/** 종목 → 수익률 → 비중: next = 기대 수익 추정(붙이는 유령) — canvas-ghost 의 CHAIN 과 같다. */
const CHAIN = { ...F, nodes: [U, R, O], edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns")] };
/** 종목·수익률이 끊김: next = 잇기만(칩). */
const CUT = { ...F, nodes: [U, R], edges: [] as ReturnType<typeof e>[] };

type Doc = { nodes: { id: string; type: string; position: { x: number; y: number } }[]; edges: { source: string; source_port: string; target: string; target_port: string }[] };
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const ghost = (page: Page, kind: string) => page.locator(`.pg-ghost[data-kind="${kind}"]`);
const zoomOf = (page: Page) => page.locator(".react-flow__viewport").evaluate((el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a);
const vp = (page: Page) => page.locator(".react-flow__viewport").evaluate((el) => { const m = new DOMMatrixReadOnly(getComputedStyle(el).transform); return { x: m.e, y: m.f }; });

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("u4_seeded")) return;
      sessionStorage.setItem("u4_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      localStorage.removeItem("alpha_pg_view");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(300);
}
/** 유령 머리 이름 쪽 한 점(칩·이름 — 단추가 아닌 곳). */
async function headPoint(page: Page, kind: string) {
  const b = (await ghost(page, kind).locator(".pg-ghost-name").boundingBox())!;
  return { x: b.x + Math.min(20, b.width / 2), y: b.y + b.height / 2 };
}

test.use({ viewport: { width: 1440, height: 900 } });

test("U4 · 유령 머리를 끌어 놓으면 놓은 자리(격자)에 붙는다 · 선은 [붙이기]와 같다 · 되돌리기 한 번에 원래 (짝: 끄는 동안 그 유령만 따라온다)", async ({ page }) => {
  await openWith(page, CHAIN);
  const g = ghost(page, "estimate");
  await expect(g).toBeVisible();
  const at = { x: Number(await g.getAttribute("data-x")), y: Number(await g.getAttribute("data-y")) };
  const z = await zoomOf(page);
  const p = await headPoint(page, "estimate");
  const d = { x: 88, y: 132 };                                                 // 화면 px
  const g0 = (await g.boundingBox())!;
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x + d.x / 2, p.y + d.y / 2, { steps: 4 });
  await page.mouse.move(p.x + d.x, p.y + d.y, { steps: 4 });
  await expect(g).toHaveClass(/pg-ghost--dragging/);
  const g1 = (await g.boundingBox())!;
  expect(Math.abs(g1.x - g0.x - d.x), "끄는 동안 유령이 손을 따라온다").toBeLessThanOrEqual(2);
  expect(Math.abs(g1.y - g0.y - d.y)).toBeLessThanOrEqual(2);
  await page.mouse.up();
  await expect(page.locator(".pg-note")).toContainText("기대 수익 추정");
  const doc = await wip(page);
  const made = doc.nodes.find((x) => x.type === "estimate")!;
  const want = { x: Math.round((at.x + d.x / z) / 11) * 11, y: Math.round((at.y + d.y / z) / 11) * 11 };
  expect(made.position, `놓은 자리(격자) — 유령 자리 ${JSON.stringify(at)} + ${d.x}/${z.toFixed(3)}`).toEqual(want);
  expect(made.position, "유령이 있던 자리가 아니다").not.toEqual(at);
  // 선은 [붙이기]와 같다 — 추정의 belief → 비중 계산
  expect(doc.edges.some((x) => x.source === made.id && x.source_port === "belief" && x.target === "optimizer" && x.target_port === "belief")).toBe(true);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(3);
  await expect.poll(async () => (await wip(page)).edges.length).toBe(2);
});

test("U4 · 짝 — 짧은 누름은 아무것도 붙이지 않는다 · 끄는 중 Esc 는 취소(유령은 제자리) · 몸통 위 끌기는 화면 이동", async ({ page }) => {
  await openWith(page, CHAIN);
  const g = ghost(page, "estimate");
  const at = { x: Number(await g.getAttribute("data-x")), y: Number(await g.getAttribute("data-y")) };
  // 짧은 누름(2px)
  let p = await headPoint(page, "estimate");
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x + 2, p.y + 1);
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect((await wip(page)).nodes.length, "짧은 누름은 붙이지 않는다").toBe(3);
  await expect(g).toBeVisible();
  // Esc 취소
  p = await headPoint(page, "estimate");
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x + 60, p.y + 80, { steps: 5 });
  await expect(g).toHaveClass(/pg-ghost--dragging/);
  await page.keyboard.press("Escape");
  await expect(g).not.toHaveClass(/pg-ghost--dragging/);
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect((await wip(page)).nodes.length, "Esc 뒤 놓아도 붙이지 않는다").toBe(3);
  expect({ x: Number(await g.getAttribute("data-x")), y: Number(await g.getAttribute("data-y")) }).toEqual(at);
  // 몸통(글 줄) 위 끌기 = 화면 이동(유령은 누름을 가로채지 않는다)
  const t = (await g.locator(".pg-ghost-text").boundingBox())!;
  // 몸통 위 점의 맨 위 요소는 빈 캔버스(pane) ★그 자체★ — 화면층이 pane 안에 있어 closest 로는 몸통도 참이다(변이 G5 가 살아남아 찾음).
  expect(await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.classList.contains("react-flow__pane") ?? false, [t.x + t.width / 2, t.y + t.height / 2] as const),
         "유령 몸통 위 점 = 빈 캔버스").toBe(true);
  // 동작으로: 비중 계산의 출력 포트에서 선을 끌어 유령 몸통 위에 놓으면 빈 곳처럼 빠른 추가가 열린다(몸통이 누름을 잡으면 열리지 않는다)
  const hd = (await page.locator('.react-flow__node[data-id="optimizer"] .react-flow__handle.source[data-handleid="weights"]').boundingBox())!;
  await page.mouse.move(hd.x + hd.width / 2, hd.y + hd.height / 2);
  await page.mouse.down();
  await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2, { steps: 12 });
  await page.mouse.up();
  await expect(page.locator(".pg-quick"), "유령 몸통 위에 놓은 선 = 빈 곳에 놓은 선").toHaveAttribute("data-type", "Weights");
  await page.keyboard.press("Escape");
  await expect(page.locator(".pg-quick")).toHaveCount(0);
  const h = await headPoint(page, "estimate");
  expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest(".pg-ghost-head"), [h.x, h.y] as const), "짝: 머리 위 점 = 유령 머리").toBe(true);
  const v0 = await vp(page);
  await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2);
  await page.mouse.down();
  await page.mouse.move(t.x + t.width / 2 + 70, t.y + t.height / 2 + 40, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  const v1 = await vp(page);
  expect(Math.abs(v1.x - v0.x - 70) + Math.abs(v1.y - v0.y - 40), "몸통 끌기는 화면을 그만큼 옮긴다").toBeLessThanOrEqual(4);
  expect((await wip(page)).nodes.length).toBe(3);
});

test("U4 · 짝 — 잇기만 하는 유령(칩)은 잡을 머리가 없고 끌어도 붙지 않는다", async ({ page }) => {
  await openWith(page, CUT);
  const chip = page.locator(".pg-ghost--connect").first();
  await expect(chip).toBeVisible();
  await expect(chip.locator(".pg-ghost-head")).toHaveCount(0);
  const b = (await chip.locator(".pg-ghost-text").boundingBox())!;
  await page.mouse.move(b.x + 10, b.y + b.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + 90, b.y + 80, { steps: 5 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect((await wip(page)).edges.length, "칩을 끌어도 잇지 않는다").toBe(0);
});

test("U4 · AI 유령도 같은 길 — 머리를 끌어 놓으면 놓은 자리(격자)에 붙고 선은 AI 추천의 attach 그대로 · 되돌리기 한 번", async ({ page }) => {
  // AI 추천 경로는 가로챈다(이 환경의 실제 서버는 Claude 키가 없다 — canvas-ai-suggest 와 같은 대역)
  await page.addInitScript(() => { try { localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"); } catch { /* */ } });
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: { principal: { username: "alice", role: "analyst" }, must_change_password: false, password_changed_at: null } }));
  const RISK = { action: "add", kind: "risk", label: "흔들림 나눠 보기", reason: "비중이 어디에서 흔들리는지 나눠 볼 수 있습니다.",
                 attach: [{ source: "optimizer", source_port: "weights", target: "@new", target_port: "weights" }] };
  await page.route("**/api/v1/assist/canvas/suggest", (r) => r.fulfill({ json: {
    available: true, source: "claude", model: "stub", suggestions: [RISK], rejected: [], cached: false,
    usage: { input_tokens: 1, output_tokens: 1, cost_usd: 0, cost_note: null } } }));
  await openWith(page, CHAIN);
  await page.locator(".pg-ai-ask").click();
  const g = page.locator('.pg-ghost[data-source="claude"][data-kind="risk"]');
  await expect(g).toBeVisible();
  await page.waitForTimeout(400);                                               // 답의 유령 쪽으로 화면을 옮기는 것이 끝나게
  const at = { x: Number(await g.getAttribute("data-x")), y: Number(await g.getAttribute("data-y")) };
  const z = await zoomOf(page);
  const b = (await g.locator(".pg-ghost-name").boundingBox())!;
  const p = { x: b.x + Math.min(20, b.width / 2), y: b.y + b.height / 2 };
  const d = { x: -66, y: 110 };
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x + d.x, p.y + d.y, { steps: 8 });
  await expect(g).toHaveClass(/pg-ghost--dragging/);
  await page.mouse.up();
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(4);
  const doc = await wip(page);
  const made = doc.nodes.find((x) => x.type === "risk")!;
  expect(made.position).toEqual({ x: Math.round((at.x + d.x / z) / 11) * 11, y: Math.round((at.y + d.y / z) / 11) * 11 });
  expect(doc.edges.some((x) => x.source === "optimizer" && x.source_port === "weights" && x.target === made.id && x.target_port === "weights")).toBe(true);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(3);
  await expect.poll(async () => (await wip(page)).edges.length).toBe(2);
});
