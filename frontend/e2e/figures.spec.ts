// 숫자와 작은 지표의 규격 (2026-11-10 · 설계 `2026-11-10-chart-indicator-system-design.md` §3 D)
// ============================================================================================================
// ⑴ ★홀로 선 큰 숫자(≥20px)는 비례폭 숫자★ — `tabular-nums` 는 모든 숫자에 0 의 폭을 줘서 큰 글자에서는 "121" 이 헐거워 보인다.
//    고정폭 숫자는 세로로 줄을 맞춰야 하는 곳(표의 숫자 칸 · 축 눈금)에만 쓴다. 짝: 표의 숫자 칸은 `tabular-nums` 다(항상-통과 배제).
// ⑵ ★스파크라인은 하나★(`shared/ui/plot/Spark.tsx`) — 선 1.5px · 끝 점 하나(지금) · 값이 둘 미만이면 선을 그리지 않는다(지어내지 않는다).
import { expect, test, type Page } from "@playwright/test";
import { freezeCharts } from "./helpers";

/** 보이는 "홀로 선 숫자"(제 글자에 숫자가 있고 ≥20px · 표·그림·입력 칸 밖)의 수와, 그중 고정폭 숫자인 것. */
const figures = (page: Page) => page.evaluate(() => {
  const bad = new Set<string>(); let big = 0;
  for (const el of document.querySelectorAll<HTMLElement>(".terminal-main *, [role=dialog] *")) {
    if (el.closest("table, svg, input, textarea, select")) continue;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || !el.getClientRects().length) continue;
    const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent ?? "").join("").trim();
    if (!own || !/\d/.test(own) || parseFloat(cs.fontSize) < 20) continue;
    big += 1;
    if (cs.fontVariantNumeric.includes("tabular-nums")) bad.add(`${el.tagName.toLowerCase()}.${el.className} ← .${el.parentElement?.className ?? ""} (${cs.fontSize})`);
  }
  return { big, bad: [...bad] };
});

async function expectProportional(page: Page, name: string, { needBig = true } = {}) {
  const f = await figures(page);
  if (needBig) expect(f.big, `${name}: 큰 숫자가 있어야 이 검사가 뜻이 있다`).toBeGreaterThan(0);
  expect(f.bad, `${name}: 홀로 선 큰 숫자는 비례폭 숫자`).toEqual([]);
}

test.beforeEach(async ({ page }) => { await freezeCharts(page); });

test("큰 숫자는 비례폭 — 매크로(개요 · 지표 흐름 창 · 국면 · 추천 · 타이밍) · 짝: 표의 숫자 칸은 고정폭", async ({ page }) => {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".mc")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(2500);
  await expectProportional(page, "개요");
  for (const t of ["regime", "recommend", "timing"]) {
    await page.locator(`#mc-tab-${t}`).click();
    await expect(page.locator(`#mc-panel-${t}`)).toBeVisible();
    await page.waitForTimeout(2000);
    await expectProportional(page, t, { needBig: false });
  }
  // 짝 — 표의 숫자 칸(읽는 줄의 표 쌍둥이)은 세로로 줄을 맞춰야 하므로 고정폭 숫자다
  await page.locator("#mc-tab-correlations").click();
  const twin = page.locator('#mc-panel-correlations .cr[data-chart="avg-corr"] .cr-table');
  await twin.locator("summary").click();
  const cell = twin.locator("tbody td.pg-td-num").first();
  await expect(cell).toBeVisible({ timeout: 30_000 });
  expect(await cell.evaluate((e) => getComputedStyle(e).fontVariantNumeric), "표의 숫자 칸은 tabular-nums").toContain("tabular-nums");
  // 지표 흐름 창의 마지막 값
  await page.locator("#mc-tab-indicators").click();
  await page.locator("#mc-panel-indicators .mc-heat-cell").first().click();
  await expect(page.getByRole("dialog").locator(".mc-modal-latest")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(500);
  await expectProportional(page, "지표 흐름 창");
});

test("큰 숫자는 비례폭 — 기업 · 위험 도구 · 파생", async ({ page }) => {
  await page.goto("/insights?code=005930", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".ci .ci-head h1")).toBeVisible({ timeout: 40_000 });
  for (const s of ["value", "models", "numbers", "money", "risk", "peers", "factors", "ai"]) {
    await page.locator(`.ci-sec[data-sec=${s}]`).evaluate((e) => e.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(500);
  }
  await page.waitForTimeout(1500);
  await expectProportional(page, "기업");
  await page.goto("/risk-tools", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".rk")).toBeVisible({ timeout: 40_000 });
  await page.waitForTimeout(3000);
  await expectProportional(page, "위험 도구");
  await page.goto("/derivatives", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".dv")).toBeVisible({ timeout: 40_000 });
  await page.getByRole("button", { name: "가격 계산하기" }).click();
  await expect(page.locator(".dv-out")).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(600);
  await expectProportional(page, "파생", { needBig: false });
});

/** 스파크라인 svg 들의 표식 — 선 굵기 · 끝 점 수. */
const sparks = (page: Page, sel: string) => page.locator(sel).evaluateAll((els) => els.map((svg) => {
  const line = svg.querySelector("polyline");
  return { w: line ? parseFloat(getComputedStyle(line).strokeWidth) : null, join: line ? getComputedStyle(line).strokeLinejoin : null, ends: svg.querySelectorAll("circle.sp-end").length };
}));

test("스파크라인은 하나 — 매크로 지표 카드 · 기업 요약 카드 · 스튜디오 표: 선 1.5px · 둥근 이음 · 끝 점 하나", async ({ page }) => {
  const check = (name: string, list: Array<{ w: number | null; join: string | null; ends: number }>) => {
    expect(list.length, `${name}: 스파크라인이 있어야 이 검사가 뜻이 있다`).toBeGreaterThan(0);
    expect(list.filter((s) => s.w !== 1.5 || s.join !== "round" || s.ends !== 1), `${name}: 선 1.5px · 둥근 이음 · 끝 점 1`).toEqual([]);
  };
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".mc")).toBeVisible({ timeout: 30_000 });
  await page.locator("#mc-tab-indicators").click();
  await expect(page.locator("#mc-panel-indicators svg.mc-spark polyline").first()).toBeVisible({ timeout: 30_000 });
  check("매크로 지표 카드", await sparks(page, "#mc-panel-indicators svg.mc-spark"));
  await page.goto("/insights?code=005930", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".ci .ci-head h1")).toBeVisible({ timeout: 40_000 });
  await page.locator(".ci-sec[data-sec=money]").evaluate((e) => e.scrollIntoView({ block: "start" }));
  await expect(page.locator(".ci-sumcard svg.ca-spark").first()).toBeVisible({ timeout: 30_000 });
  check("기업 요약 카드", await sparks(page, ".ci-sumcard svg.ca-spark"));
  await page.goto("/macro/neural-sde", { waitUntil: "networkidle" });
  await expect(page.locator(".ms-out .ms-spark").first()).toBeVisible({ timeout: 20_000 });
  check("스튜디오 표", await sparks(page, ".ms-out svg.ms-spark"));
});

// ⑶ ★옆줄 테두리 0★ — 알림·인용 상자를 굵은 왼쪽 색 줄(2px 이상)로 그리지 않는다(전체 1px 테두리 · 옅은 바탕 · 또는 아무것도).
//    상태별 단언은 그 상태에 닿는 스펙에 있다(`macro-case` · `canvas-ai-question` · `portfolio-graph` · `settings`). 여기는 첫 화면 훑기.
//    멀리 보기 줌의 노드 단계 색 띠(글자가 숨는 줌의 유일한 부호)는 첫 화면에 없다.
test("옆줄 테두리 0 — 첫 화면 열 곳에 굵은 왼쪽·오른쪽 색 줄이 없다", async ({ page }) => {
  const found: string[] = [];
  for (const r of ["/dashboard", "/screener", "/backtest", "/macro", "/macro/tsfm-latent", "/insights?code=005930", "/risk-tools", "/admin/data", "/derivatives", "/allocation"]) {
    await page.goto(r, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3500);
    const hits = await page.evaluate(() => {
      const out = new Set<string>();
      for (const el of document.querySelectorAll<HTMLElement>(".terminal-main *")) {
        const cs = getComputedStyle(el), rect = el.getBoundingClientRect();
        if (cs.display === "none" || cs.visibility === "hidden" || rect.width <= 24 || rect.height <= 0) continue;
        const l = parseFloat(cs.borderLeftWidth), rt = parseFloat(cs.borderRightWidth), t = parseFloat(cs.borderTopWidth);
        if ((l >= 2 && cs.borderLeftStyle !== "none" && t < 2) || (rt >= 2 && cs.borderRightStyle !== "none" && t < 2)) out.add(`${el.tagName.toLowerCase()}.${el.className} (왼 ${l} · 오 ${rt})`);
      }
      return [...out];
    });
    for (const h of hits) found.push(`${r}: ${h}`);
  }
  expect(found, "굵은 옆줄 테두리").toEqual([]);
});
