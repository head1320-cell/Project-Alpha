import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// ═══════════════════════════════════════════════════════════════════════════════
// CF 3부 P · 제약 — 보고가 ★무엇이 적용됐고 무엇이 안 됐는지★ 말한다
// ─────────────────────────────────────────────────────────────────────────────
//  P1 · 옵티마이저 결과에 "제약이 어떻게 적용됐나" — 업종 상한이 빠졌으면 '적용 안 됨'(짝: 종목 상한만이면 없음)
//       · 설명(이야기 탭)도 '제약 지킴' 을 확인으로 말하지 않는다 · 기대 수익 추정은 수익률 입력을 쓰지 않는다고 말한다
//  개발 DB 에는 업종 표(`instrument_master`)가 없어 업종 상한이 ★실제로 전부 빠진다★ — 그것이 이 테스트가 보는 상황이다.
// ═══════════════════════════════════════════════════════════════════════════════

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

async function exportDoc(page: Page) {
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  return JSON.parse(readFileSync((await (await dl).path())!, "utf-8"));
}

/** 기본 사슬을 내보내 옵티마이저 제약만 바꿔 다시 싣는다 — 위치·다른 칸은 앱이 만든 그대로. */
async function withConstraints(page: Page, constraints: Record<string, unknown>) {
  const doc = await exportDoc(page);
  const opt = doc.nodes.find((n: { id: string }) => n.id === "optimizer");
  opt.params = { ...opt.params, constraints };
  await page.locator(".pg-import-input").setInputFiles({
    name: "c.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
  await expect(node(page, "optimizer")).toBeVisible();
}

async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
}

test("P1 · 업종 상한이 빠지면 결과가 '적용 안 됨' 이라고 말한다 — 설명도 확인이라 하지 않는다", async ({ page }) => {
  await openCanvas(page);
  await withConstraints(page, { group_caps_pct: { "반도체": 30 }, max_weight_pct: 40 });
  await run(page);
  await node(page, "optimizer").click();
  await tab(page, "detail");
  const rep = page.locator(".pg-side .pg-cons");
  await expect(rep).toBeVisible();
  await expect(rep.locator(".pg-cons-unapplied")).toHaveCount(1);
  await expect(rep.locator(".pg-cons-unapplied")).toContainText("반도체");
  await expect(rep.locator(".pg-cons-head .pg-tag"), "빠진 것이 있으면 '제약 지킴' 이 아니다").not.toHaveText("제약 지킴");

  await tab(page, "story");
  const step = page.locator('.pg-step[data-node-id="optimizer"]');
  await expect(step.locator(".pg-trust")).toContainText("반도체");
  await expect(step.locator(".pg-trust"), "적용된 것만 지켰다고 말한다").toContainText("적용된 제약 안에서");
});

test("P1 · 짝 — 종목 상한만이면 빠진 것이 없다", async ({ page }) => {
  await openCanvas(page);
  await withConstraints(page, { max_weight_pct: 40 });
  await run(page);
  await node(page, "optimizer").click();
  await tab(page, "detail");
  const rep = page.locator(".pg-side .pg-cons");
  await expect(rep).toBeVisible();
  await expect(rep.locator(".pg-cons-unapplied")).toHaveCount(0);
  await expect(rep).toHaveAttribute("data-cons-status", /ok|approx/);
});

test("P1 · 기대 수익 추정은 이어진 수익률을 쓰지 않는다고 말한다", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  await tab(page, "story");
  await expect(page.locator('.pg-step[data-node-id="estimate"]')).toContainText("이어진 수익률은 이 단계에서 쓰지 않아요");
  await expect(page.locator('.pg-step[data-node-id="optimizer"]'), "짝: 옵티마이저 설명에는 없다")
    .not.toContainText("이어진 수익률은");
});

// ═══════════════════════════════════════════════════════════════════════════════
//  P2 · 제약 편집기 — 엔진이 받는 열 가지를 질문 카드로 · 범위는 서버 스키마에서 · 풀 수 없는 조합은 계산 전에 말한다
//  · 기본 칩(한 종목 최대)은 다른 제약을 지우지 않는다 · 공매도 프리셋은 연구용이라고 말한다 · 옛 문서는 그대로 열린다
// ═══════════════════════════════════════════════════════════════════════════════

const field = (page: Page) => page.locator('.pg-basic-field[data-field="constraints"]');
const card = (page: Page, key: string) => field(page).locator(`.pg-cons-card[data-key="${key}"]`);

async function openEditor(page: Page) {
  await node(page, "optimizer").click();
  await tab(page, "settings");
  await expect(field(page)).toBeVisible();
  const more = field(page).locator(".pg-cons-more");
  await expect(more).toBeAttached();
  if (!(await more.evaluate((d) => (d as HTMLDetailsElement).open))) await more.locator("summary").click();
}

async function constraintsOf(page: Page) {
  return (await exportDoc(page)).nodes.find((n: { id: string }) => n.id === "optimizer").params.constraints;
}

test("P2 · 질문 카드 — 칸의 범위는 서버 스키마(ConstraintsInput)에서 온다", async ({ page }) => {
  await openCanvas(page);
  const cat = await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json();
  const opt = cat.nodes.find((n: { type: string }) => n.type === "optimizer");
  const props = opt.params_schema.$defs.ConstraintsInput.properties;
  const lim = (k: string) => {
    const p = props[k];
    const v = (p.anyOf ?? [p]).find((x: { minimum?: number }) => x.minimum !== undefined) ?? p;
    return { min: String(v.minimum), max: String(v.maximum) };
  };
  await openEditor(page);
  for (const k of ["min_weight_pct", "turnover_cap_pct", "beta_min", "beta_max", "cash_min_pct", "cash_max_pct",
                   "gross_max_pct", "net_min_pct", "net_max_pct"]) {
    const input = card(page, k).locator("input[type=number]");
    await expect(input, k).toHaveAttribute("min", lim(k).min);
    await expect(input, k).toHaveAttribute("max", lim(k).max);
  }
  await expect(card(page, "group_caps_pct")).toBeVisible();
});

test("P2 · 풀 수 없는 조합은 계산 전에 말한다 — 짝: 풀 수 있으면 말하지 않는다", async ({ page }) => {
  await openCanvas(page);
  await openEditor(page);
  await field(page).locator(".pg-chip", { hasText: "20%" }).click();       // 20% × 4종목 = 80% < 100%
  await expect(field(page).locator(".pg-cons-check--bad")).toContainText("채울 수 없습니다");
  await field(page).locator(".pg-chip", { hasText: "40%" }).click();
  await expect(field(page).locator(".pg-cons-check--bad")).toHaveCount(0);
});

test("P2 · 한 종목 칩은 다른 제약을 지우지 않는다", async ({ page }) => {
  await openCanvas(page);
  await openEditor(page);
  await card(page, "turnover_cap_pct").locator("input").fill("20");
  await field(page).locator(".pg-chip", { hasText: "30%" }).click();
  expect(await constraintsOf(page)).toEqual({ turnover_cap_pct: 20, max_weight_pct: 30 });
  await field(page).locator(".pg-chip", { hasText: "제한 없음" }).click();
  expect(await constraintsOf(page)).toEqual({ turnover_cap_pct: 20 });
  await card(page, "turnover_cap_pct").locator("input").fill("");
  expect((await exportDoc(page)).nodes.find((n: { id: string }) => n.id === "optimizer").params,
         "다 비우면 칸을 지운다(서버 기본값)").not.toHaveProperty("constraints");
});

test("P2 · 모양 프리셋 — 130/30 · 달러 중립은 공매도라 연구용이라고 말하고, 롱온리는 그것을 걷는다", async ({ page }) => {
  await openCanvas(page);
  await openEditor(page);
  const shape = (label: string) => field(page).locator(".pg-cons-shape", { hasText: label }).click();
  await shape("130/30");
  expect(await constraintsOf(page)).toEqual({ min_weight_pct: -10, gross_max_pct: 160, net_min_pct: 100, net_max_pct: 100 });
  await expect(field(page).locator(".pg-cons-short")).toContainText("연구");
  await expect(field(page).locator(".pg-cons-assumed"), "공매도 폭은 가정").toBeVisible();
  await shape("달러 중립");
  expect(await constraintsOf(page)).toEqual({ min_weight_pct: -20, gross_max_pct: 200, net_min_pct: 0, net_max_pct: 0 });
  await shape("롱온리");
  expect((await exportDoc(page)).nodes.find((n: { id: string }) => n.id === "optimizer").params).not.toHaveProperty("constraints");
  await expect(field(page).locator(".pg-cons-short")).toHaveCount(0);
});

test("P2 · 업종 — 개발 DB 는 업종을 못 읽는다고 말한다 · 짝: 읽으면 업종 칩으로 상한을 건다", async ({ page }) => {
  await openCanvas(page);
  await openEditor(page);
  await expect(card(page, "group_caps_pct").locator(".pg-cons-sectors-none")).toBeVisible();
  await expect(card(page, "group_caps_pct").locator(".pg-cons-sector-chip")).toHaveCount(0);

  // 짝 — 업종 표가 있는 서버라면(확인 응답만 가로챈다 · 판정 규칙은 pytest 가 서버에서 건다)
  await page.route("**/api/v1/allocation/constraints/check", async (r) => {
    const real = await (await r.fetch()).json();
    await r.fulfill({ json: { ...real, sectors_readable: true, group_names: ["반도체", "자동차"],
                              groups: { "005930": "반도체", "000660": "반도체" }, unapplied: [] } });
  });
  await card(page, "turnover_cap_pct").locator("input").fill("30");        // 다시 확인하게
  await card(page, "group_caps_pct").locator(".pg-cons-sector-chip", { hasText: "반도체" }).click();
  await card(page, "group_caps_pct").locator('.pg-cons-cap[data-group="반도체"] input').fill("25");
  expect(await constraintsOf(page)).toEqual({ turnover_cap_pct: 30, group_caps_pct: { "반도체": 25 } });
  await card(page, "group_caps_pct").locator('.pg-cons-cap[data-group="반도체"] .pg-cons-cap-x').click();
  expect(await constraintsOf(page)).toEqual({ turnover_cap_pct: 30 });
});

test("P2 · 옛 문서(한 종목 상한만)는 그대로 열리고 그대로 내보낸다", async ({ page }) => {
  await openCanvas(page);
  await withConstraints(page, { max_weight_pct: 30 });
  await openEditor(page);
  await expect(field(page).locator(".pg-cons-max.on")).toHaveText("30%");
  await expect(field(page).locator(".pg-cons-shape.on"), "공매도 칸이 없으면 롱온리").toHaveText("롱온리");
  expect(await constraintsOf(page)).toEqual({ max_weight_pct: 30 });
});

// 노드 카드(가까이에서 보이는 칸) — 같은 규칙: 한 종목 최대만 바꾸고 나머지는 그대로 · 칩에 없는 값은 요약으로(예전엔 "[object Object]").
const canvasEl = (page: Page) => page.locator(".pg-canvas");
async function zoomNear(page: Page) {
  for (let i = 0; i < 16 && (await canvasEl(page).getAttribute("data-zoom")) !== "near"; i++) {
    await page.locator(".react-flow__controls-zoomin").click();
    await page.waitForTimeout(120);
  }
  await expect(canvasEl(page)).toHaveAttribute("data-zoom", "near");
}
async function centerNode(page: Page, id: string) {
  const r = await page.evaluate((nid) => {
    const nb = document.querySelector(`.react-flow__node[data-id="${nid}"]`)!.getBoundingClientRect();
    const hit = (sel: string) => { const x = document.querySelector<HTMLElement>(sel); return x && x.offsetParent ? x.getBoundingClientRect() : null; };
    const pl = hit(".pg-palette"), sd = hit(".pg-side"), cv = document.querySelector(".react-flow")!.getBoundingClientRect();
    const left = pl ? pl.right : cv.left, right = sd ? sd.left : cv.right;
    let p = null as null | { x: number; y: number };
    for (let y = cv.bottom - 90; y > cv.top + 80 && !p; y -= 17)
      for (let x = cv.left + 20; x < cv.right - 20 && !p; x += 23)
        if (document.elementFromPoint(x, y)?.classList.contains("react-flow__pane")) p = { x, y };
    return { p: p!, dx: (left + right) / 2 - (nb.left + nb.width / 2), dy: cv.top + 130 - nb.top };
  }, id);
  await page.mouse.move(r.p.x, r.p.y); await page.mouse.down();
  await page.mouse.move(r.p.x + r.dx, r.p.y + r.dy, { steps: 8 }); await page.mouse.up();
}

test("P2 · 노드 카드의 제약 고르기도 다른 제약을 지우지 않고, 칩에 없는 값은 요약으로 보인다", async ({ page }) => {
  await openCanvas(page);
  await withConstraints(page, { turnover_cap_pct: 20, max_weight_pct: 25 });
  await zoomNear(page);
  await centerNode(page, "optimizer");
  const sel = node(page, "optimizer").locator('.pg-cw-f[data-field="constraints"] select');
  await expect(sel.locator("option:checked")).toHaveText("직접 정한 값 (한 종목 최대 25% · 회전율 20%)");
  await sel.selectOption({ label: "30%" });
  expect(await constraintsOf(page)).toEqual({ turnover_cap_pct: 20, max_weight_pct: 30 });
  await sel.selectOption({ label: "제한 없음" });
  expect(await constraintsOf(page)).toEqual({ turnover_cap_pct: 20 });
  await expect(sel.locator("option:checked"), "한 종목 최대가 없으면 '제한 없음' 이 켜진다").toHaveText("제한 없음");
});
