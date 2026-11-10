// 차트 표식 규격 — 모든 차트가 한 체계로 읽힌다 (2026-11-10 · ADR 004 §6 · 설계 `2026-11-10-chart-indicator-system-design.md` §3 A)
// ============================================================================================================
// 규격(`shared/ui/chart/chartSpec.ts`): 격자는 실선(점선은 뜻이 있는 주석선에만) · 선 굵기는 2 또는 1.5(뒤로 물린 선) · 점은 r≥4 + 표면색 고리 2px ·
// 면은 그라데이션이 아닌 단색 물들임 · 막대는 24px 이하.
// ★공허한 통과를 막는다★ — 장면마다 "반드시 있어야 하는 표식"(need)을 적고, 그 표식이 하나도 없으면 빨강이다.
import { test, expect, type Page } from "./fixtures";
import { freezeCharts } from "./helpers";

type Kind = "grid" | "line" | "dot" | "area" | "bar";
interface Marks { charts: number; grid: string[]; line: number[]; dot: Array<{ r: number; ring: number; same: boolean }>; area: string[]; bar: number[] }

/** 뿌리 아래 recharts 그림의 표식(계산된 스타일·속성). 선이 없는 면(`stroke: none`)의 굵기는 세지 않는다. */
const marks = (page: Page, root: string): Promise<Marks> => page.locator(root).first().evaluate((el) => {
  const out = { charts: el.querySelectorAll(".recharts-wrapper").length, grid: [] as string[], line: [] as number[],
    dot: [] as Array<{ r: number; ring: number; same: boolean }>, area: [] as string[], bar: [] as number[] };
  for (const l of el.querySelectorAll(".recharts-cartesian-grid line")) out.grid.push(getComputedStyle(l).strokeDasharray);
  for (const c of el.querySelectorAll(".recharts-line-curve, .recharts-area-curve")) {
    const cs = getComputedStyle(c);
    if (cs.stroke !== "none") out.line.push(parseFloat(cs.strokeWidth));
  }
  for (const d of el.querySelectorAll<SVGCircleElement>(".recharts-line-dots circle")) {
    const cs = getComputedStyle(d);
    out.dot.push({ r: d.r.baseVal.value, ring: parseFloat(cs.strokeWidth), same: cs.stroke === cs.fill });
  }
  for (const a of el.querySelectorAll(".recharts-area-area")) out.area.push(getComputedStyle(a).fill);
  for (const b of el.querySelectorAll(".recharts-bar-rectangle path")) out.bar.push(Math.round(b.getBoundingClientRect().width * 10) / 10);
  return out;
});

function check(name: string, m: Marks, need: Kind[]) {
  expect(m.charts, `${name}: 그림이 있다`).toBeGreaterThan(0);
  for (const k of need) expect(m[k].length, `${name}: ${k} 표식이 있다(공허한 통과 배제)`).toBeGreaterThan(0);
  expect(m.grid.filter((d) => d !== "none"), `${name}: 격자는 실선`).toEqual([]);
  expect(m.line.filter((w) => w !== 2 && w !== 1.5), `${name}: 선 굵기는 2 또는 1.5`).toEqual([]);
  expect(m.dot.filter((d) => d.r < 4 || d.ring !== 2 || d.same), `${name}: 점은 r≥4 + 표면색 고리 2px`).toEqual([]);
  expect(m.area.filter((f) => f.startsWith("url(")), `${name}: 면은 그라데이션이 아니다`).toEqual([]);
  expect(m.bar.filter((w) => w > 24.5), `${name}: 막대는 24px 이하`).toEqual([]);
}

async function openMacro(page: Page, tab?: string) {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".mc")).toBeVisible({ timeout: 30_000 });
  if (tab) await page.locator(`#mc-tab-${tab}`).click();
  await expect(page.locator(`#mc-panel-${tab ?? "overview"} .recharts-wrapper`).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1200);
}

test.beforeEach(async ({ page }) => { await freezeCharts(page); });

test("매크로 — 개요(금리곡선) · 국면(축 쌓기) · 상관 · 타이밍", async ({ page }) => {
  await openMacro(page);
  check("개요", await marks(page, "#mc-panel-overview"), ["grid", "line", "dot"]);
  await openMacro(page, "regime");
  await expect(page.locator("#mc-panel-regime .mc-axstack .recharts-bar-rectangle").first()).toBeVisible({ timeout: 30_000 });
  check("국면", await marks(page, "#mc-panel-regime"), ["line", "bar"]);
  await openMacro(page, "correlations");
  check("상관", await marks(page, "#mc-panel-correlations"), ["grid", "line", "area"]);
  await openMacro(page, "timing");
  check("타이밍", await marks(page, "#mc-panel-timing"), ["grid", "area"]);
});

test("매크로 — 지표 흐름 창", async ({ page }) => {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".mc")).toBeVisible({ timeout: 30_000 });
  await page.locator("#mc-tab-indicators").click();
  await page.locator("#mc-panel-indicators .mc-heat-cell").first().click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.locator(".recharts-area-curve")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(600);
  check("지표 흐름", await marks(page, "[role=dialog]"), ["grid", "line", "area"]);
});

test("스튜디오 — 잠재 요인 · 기간 구조", async ({ page }) => {
  await page.goto("/macro/tsfm-latent", { waitUntil: "networkidle" });
  await expect(page.locator(".ms-viz-factor .recharts-line-curve").first()).toBeVisible({ timeout: 20_000 });
  check("잠재 요인", await marks(page, ".ms-studio"), ["line"]);
  await page.goto("/macro/neural-sde", { waitUntil: "networkidle" });
  await expect(page.locator(".ms-viz-curve .recharts-line-curve")).toHaveCount(3, { timeout: 20_000 });
  check("기간 구조", await marks(page, ".ms-studio"), ["line"]);
});

test("기업 — 주가 · 가치 범위 · 매출과 이익률", async ({ page }) => {
  await page.goto("/insights?code=005930", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".ci .ci-head h1")).toBeVisible({ timeout: 40_000 });
  for (const s of ["value", "models", "numbers", "money", "risk", "peers", "factors", "ai"]) {
    await page.locator(`.ci-sec[data-sec=${s}]`).evaluate((e) => e.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(400);
  }
  await expect(page.locator(".ci-story .recharts-bar-rectangle").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".ci-pv .recharts-line")).toHaveCount(1, { timeout: 40_000 });
  await page.waitForTimeout(800);
  check("기업", await marks(page, ".ci"), ["line", "dot", "bar"]);
});

test("파생 — 만기 손익 · 기대 노출", async ({ page }) => {
  await page.goto("/derivatives", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".dv")).toBeVisible({ timeout: 40_000 });
  await page.getByRole("button", { name: "가격 계산하기" }).click();
  await expect(page.getByTestId("payoff").locator(".recharts-line-curve")).toBeVisible({ timeout: 20_000 });
  check("만기 손익", await marks(page, "[data-testid=payoff]"), ["grid", "line", "area"]);
  await page.goto("/derivatives?tab=cva", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".dv")).toBeVisible({ timeout: 40_000 });
  await page.getByRole("button", { name: "신용 위험 계산하기" }).click();
  await expect(page.getByTestId("cva-curve").locator(".recharts-line-curve")).toBeVisible({ timeout: 20_000 });
  check("기대 노출", await marks(page, "[data-testid=cva-curve]"), ["grid", "line", "dot"]);
});
