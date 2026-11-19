import { test, expect } from "./fixtures";
import { trackErrors, uniq } from "./helpers";

// Macro Analysis regression — locks in the healthy state so a future regression (the
// reported "Macro tab throws an error") makes CI go red. Drives all 8 sub-tabs + US toggle.
// BU5a — 탭 이름이 한국어가 됐다. 고르기는 이름이 아니라 안정 id(`#mc-tab-{id}`)로 한다(이름이 다시 바뀌어도 깨지지 않게).
const SUBTABS = ["indicators", "regime", "valuation", "strategies", "recommend", "correlations", "timing", "overview"];

test("Macro: all sub-tabs render with zero page/console/API errors + Korean encoding", async ({ page }) => {
  const sink = trackErrors(page);

  await page.goto("/macro", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);

  // Overview loaded: a known Korean label is visible and correctly encoded (not mojibake).
  await expect(page.getByText("국면", { exact: false }).first()).toBeVisible();
  const banner = await page.locator("body").innerText();
  expect(banner).toContain("시장 스트레스");
  expect(banner).not.toMatch(/�/); // no replacement char (encoding corruption)

  for (const t of SUBTABS) {
    const before = sink.pageErrors.length;
    await page.locator(`#mc-tab-${t}`).click();
    await page.waitForTimeout(1800);
    expect(sink.pageErrors.slice(before), `sub-tab ${t} threw`).toHaveLength(0);
    // the clicked tab became active
    await expect(page.locator(`#mc-tab-${t}.on`)).toBeVisible();
  }

  expect(uniq(sink.api404), "macro API 404s").toEqual([]);
  expect(uniq(sink.pageErrors), "macro page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "macro console errors").toEqual([]);
});

// Hardening regression: a PARTIAL /macro/recommend payload (top/regime dropped — the shape
// real BOK/FRED data can produce when a recommendation can't be fully computed) must render
// an honest unavailable state, NOT crash the tab.
test("Macro: partial recommend payload → honest unavailable state, no crash", async ({ page }) => {
  const sink = trackErrors(page);
  await page.route("**/api/v1/macro/recommend**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ error: false, confidence: 0.2, low_conviction: true, top: null, macro_allocation: null }),
    }),
  );

  await page.goto("/macro", { waitUntil: "networkidle" });
  await page.locator("#mc-tab-recommend").click();
  await page.waitForTimeout(1500);

  await expect(page.getByText(/추천 데이터가 불완전|데이터 미가용|추천 데이터 없음/).first()).toBeVisible();
  expect(uniq(sink.pageErrors), "no crash on partial recommend").toEqual([]);
});

// G7 ① (2026-11-19): 매크로 추천의 해설은 엔진의 규칙 글이다 — 엔진은 LLM 을 부르지 않는다(`tests/test_llm_boundary.py`).
// 화면은 지키지 못할 약속('관리자가 키를 등록하면 AI 해설')을 하지 않고, 서버가 '규칙'이라고 할 때만 규칙 글이라고 적는다.
test("Macro: the recommendation reason says it is the rule narrative and promises no AI key", async ({ page }) => {
  const sink = trackErrors(page);
  const sources: unknown[] = [];
  page.on("response", async (r) => {
    if (!r.url().includes("/api/v1/macro/recommend")) return;
    try { sources.push((await r.json()).narrative_source); } catch { /* 본문 없음 */ }
  });
  await page.goto("/macro", { waitUntil: "networkidle" });
  await page.locator("#mc-tab-recommend").click();
  const card = page.locator(".mc-card", { has: page.locator(".mc-narr") });
  await expect(card.locator(".mc-card-sub")).toHaveText("규칙 기반 해설입니다 · 국면 적합도와 최근 12개월 성과로 지은 글입니다");
  await expect(card.locator(".mc-card-h")).not.toContainText("키를 등록");
  await expect(card.locator(".mc-card-h")).not.toContainText("AI");
  await expect(card.locator(".mc-narr")).not.toBeEmpty();
  expect(sources.length, "추천 응답을 보았다").toBeGreaterThan(0);
  expect(new Set(sources), "서버의 해설 출처").toEqual(new Set(["rule"]));
  expect(uniq(sink.pageErrors)).toEqual([]);
});

// 짝: 서버가 '규칙'이라고 하지 않는 응답(옛 형의 값)에는 규칙 글이라는 이름표를 붙이지 않는다 — 화면이 출처를 지어내지 않는다.
test("Macro: a reason whose source is not the rule gets no rule label", async ({ page }) => {
  await page.route("**/api/v1/macro/recommend**", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ response: res, json: { ...body, narrative_source: "claude" } });
  });
  await page.goto("/macro", { waitUntil: "networkidle" });
  await page.locator("#mc-tab-recommend").click();
  const card = page.locator(".mc-card", { has: page.locator(".mc-narr") });
  await expect(card.locator(".mc-narr")).not.toBeEmpty();
  await expect(card.locator(".mc-card-h")).toHaveText("추천한 까닭");
  await expect(card.locator(".mc-card-sub")).toHaveCount(0);
});
