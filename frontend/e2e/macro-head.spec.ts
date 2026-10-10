import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BU5a · 매크로 분석 머리 — 답 한 문장(서버 값) · 한국어 탭 · 실패는 실패로 (계획 "BU5 상세")
 * BU5a+ · 국면 그림(도넛 2 + 반원) — 같은 서버 값을 모양으로. 이름 "매크로 분석". (계획 "BU5a+")
 * 거는 것(짝으로 항상-통과·항상-침묵을 배제):
 *  · 답 = 서버 국면(한국·미국)의 번역 — 응답을 바꾸면 문장이 따라 바뀐다 · 확률 없으면 "확률 몰라요"(0% 아님) · 미국 없으면 "몰라요"
 *  · 연습용 칩 = connection-status.mock_allowed(홈과 같은 규칙) — 대시보드 출처로 추론하지 않는다(짝)
 *  · 국면 500 → alert + 다시 시도(짝: 정상 alert 0) · 탭 데이터 500 → 그 탭 alert, 다른 탭은 정상 · 한국·미국 비교·국면 궤적 실패가 영원한 "계산 중"이 아니다
 *  · 탭 8 한국어 · 번호 표식 없음 · 머리·탭·스튜디오 줄에 영어 대문자 없음(탭 안쪽은 BU5b) · 스튜디오 줄 한국어 · 주 단추 하나 · AA · 390
 */

type Regime = Record<string, unknown> & { regime: string; regime_probs?: Record<string, number>; markets?: Record<string, Record<string, unknown>> };
const KO: Record<string, string> = { Goldilocks: "골디락스", Reflation: "리플레이션", Stagflation: "스태그플레이션", Disinflation: "디스인플레이션" };
const main = (p: Page) => p.locator(".terminal-main");
const answer = (p: Page) => p.locator(".mc .tx-answer-s");
const fig = (p: Page, label: string) => p.locator(".mc .tx-fig", { has: p.locator("dt", { hasText: label }) }).locator("dd");
const TAB_KO = ["개요", "지표", "국면", "가치", "전략", "추천", "상관", "타이밍"];

async function patch(page: Page, path: string, edit: (b: Regime) => void) {
  await page.route(`**/api/v1/macro/${path}`, async (route: Route) => {
    const res = await route.fetch();
    const b = (await res.json()) as Regime;
    edit(b);
    await route.fulfill({ response: res, json: b });
  });
}
async function open(page: Page) {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".mc, .mc-err")).toBeVisible({ timeout: 30_000 });
}
const krOf = (b: Regime) => (b.markets?.kr ?? b) as Regime;

test("답 = 서버 국면의 번역 — 한국·미국을 바꾸면 문장이 따라 바뀐다(짝: 상수 배제)", async ({ page }) => {
  const seen = page.waitForResponse((r) => r.url().endsWith("/api/v1/macro/regime"));
  await open(page);
  const b = (await (await seen).json()) as Regime;
  const kr = KO[krOf(b).regime] ?? krOf(b).regime;
  await expect(answer(page)).toContainText(`한국은 ‘${kr}’`);

  await patch(page, "regime", (x) => {
    x.regime = "Stagflation";
    if (x.markets?.kr) x.markets.kr.regime = "Stagflation";
    if (x.markets?.us) x.markets.us.regime = "Reflation";
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(answer(page)).toContainText("한국은 ‘스태그플레이션’");
  await expect(answer(page)).toContainText("미국은 ‘리플레이션’");
});

test("확률이 없으면 '확률 몰라요'(0% 아님) · 미국 국면이 없으면 줄은 남고 '몰라요'(짝)", async ({ page }) => {
  await patch(page, "regime", (x) => {
    delete x.regime_probs; delete (x as Record<string, unknown>).confidence;
    if (x.markets?.kr) { delete x.markets.kr.regime_probs; delete x.markets.kr.confidence; }
    if (x.markets) delete x.markets.us;
  });
  await open(page);
  await expect(fig(page, "한국")).toContainText("확률 몰라요");
  await expect(fig(page, "한국")).not.toContainText("0%");
  await expect(fig(page, "미국")).toContainText("몰라요");
  await expect(answer(page)).not.toContainText("미국");
});

test("연습용 칩은 connection-status 로만 — 출처를 추론하지 않는다(짝: mock_allowed false 면 없음)", async ({ page }) => {
  await page.route("**/api/v1/macro/connection-status", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ mock_allowed: true, bok_configured: false, fred_configured: false }) }));
  await open(page);
  await expect(page.locator(".mc .tx-answer")).toContainText("연습용 데이터");
  await page.unroute("**/api/v1/macro/connection-status");
  await page.route("**/api/v1/macro/connection-status", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ mock_allowed: false, bok_configured: true, fred_configured: true }) }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".mc .tx-answer")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".mc .tx-answer")).not.toContainText("연습용");
  await expect(main(page)).not.toContainText("MOCK");
});

test("국면을 불러오지 못하면 alert + 다시 시도 → 풀리면 답(짝: 정상이면 alert 0)", async ({ page }) => {
  let fail = true;
  await page.route("**/api/v1/macro/regime", (r) => fail ? r.fulfill({ status: 500, body: "boom" }) : r.continue());
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  const alerts = main(page).getByRole("alert");
  await expect(alerts.first()).toContainText("매크로 분석을 불러오지 못했어요", { timeout: 30_000 });
  fail = false;
  await main(page).getByRole("button", { name: "다시 시도" }).first().click();
  await expect(answer(page)).toContainText("한국은", { timeout: 30_000 });
  await expect(alerts).toHaveCount(0);
});

test("탭 데이터를 불러오지 못하면 그 탭 안 alert — 다른 탭은 정상(짝)", async ({ page }) => {
  await page.route("**/api/v1/macro/valuation**", (r) => r.fulfill({ status: 500, body: "boom" }));
  await open(page);
  await page.getByRole("tab", { name: "가치" }).click();
  await expect(main(page).getByRole("alert").first()).toContainText("불러오지 못했어요");
  await page.getByRole("tab", { name: "지표" }).click();
  await expect(main(page).getByRole("alert")).toHaveCount(0);
});

test("한국·미국 비교를 못 하면 영원한 '계산 중'이 아니라 실패로 말한다", async ({ page }) => {
  await page.route("**/api/v1/macro/compare-krus", (r) => r.fulfill({ status: 500, body: "boom" }));
  await open(page);
  await expect(main(page)).toContainText("비교를 불러오지 못했어요", { timeout: 30_000 });
  await expect(main(page)).not.toContainText("비교 계산 중");
});

test("국면 궤적을 못 받으면 영원한 '불러오는 중'이 아니라 실패 + 다시 시도 → 풀리면 궤적", async ({ page }) => {
  let fail = true;
  await page.route("**/api/v1/macro/regime-trajectory", (r) => fail ? r.fulfill({ status: 500, body: "boom" }) : r.continue());
  await open(page);
  await page.getByRole("tab", { name: "국면" }).click();
  await expect(main(page).getByRole("alert").first()).toContainText("국면 궤적을 불러오지 못했어요", { timeout: 30_000 });
  await expect(main(page)).not.toContainText("궤적을 불러오는 중이에요");
  fail = false;
  await main(page).getByRole("alert").getByRole("button", { name: "다시 시도" }).click();
  await expect(main(page).getByRole("alert")).toHaveCount(0, { timeout: 30_000 });
});

test("탭 8 한국어 · 번호 표식 없음 · 영어 사분면 대문자 없음 · 로빙 그대로", async ({ page }) => {
  await open(page);
  const tabs = page.locator(".mc-tabs .mc-tab");
  await expect(tabs).toHaveCount(8);
  expect((await tabs.allInnerTexts()).map((t) => t.trim())).toEqual(TAB_KO);
  await expect(page.locator(".mc-tab-n")).toHaveCount(0);
  // BU5a 의 범위(머리·탭 줄·스튜디오 줄)만 본다 — 탭 안쪽 카드의 영어 대문자는 BU5b 가 걷고 그때 이 범위를 넓힌다.
  for (const sel of [".mc-head", ".mc-tabs", ".ms-nav"])
    await expect(page.locator(sel)).not.toContainText(/GOLDILOCKS|STAGFLATION|REFLATION|DISINFLATION|STRESS|NORMAL|CAUTIOUS|DEFENSIVE|COCKPIT|LATENT/);
  await tabs.first().focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
});

test("스튜디오 줄은 한국어 — 개수·현재 표시는 그대로", async ({ page }) => {
  await open(page);
  const items = page.locator(".ms-nav .ms-nav-item");
  await expect(items).toHaveCount(6);
  expect((await items.allInnerTexts()).map((t) => t.trim())).toEqual(["한눈에 보기", "잠재 요인", "기간 구조", "인과 관계", "꼬리 위험", "뷰 만들기"]);
  await expect(page.locator(".ms-nav-item[aria-current=page]")).toHaveCount(1);
});

test("매크로 분석 주 단추는 하나 — [포트폴리오 설계에 넣기]", async ({ page }) => {
  await open(page);
  const mains = page.locator(".mc .tx-btn--main");
  await expect(mains).toHaveCount(1);
  await expect(mains).toContainText("포트폴리오 설계에 넣기");
});

for (const t of ["light", "dark"] as const) {
  test(`매크로 분석 머리 AA — ${t}`, async ({ page }) => {
    await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, t);
    await open(page);
    await page.waitForTimeout(800);
    const r = await page.evaluate<AuditResult>(contrastAudit(".mc-head"));
    expect(r.checked).toBeGreaterThan(5);
    expect(r.low, `${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
    if (t === "dark") expect(r.bright, `${t} 밝은 판`).toEqual([]);
  });
}

test("390 — 매크로 분석 가로 넘침 없음", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const over = await page.evaluate(() => {
    const m = document.querySelector(".terminal-main") as HTMLElement;
    return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
  });
  expect(over).toBeLessThanOrEqual(0);
});

// ── BU5a+ · 국면 그림 — 도넛 2(네 국면 전부) + 스트레스 반원 ────────────────────────────────
const viz = (p: Page) => p.locator(".rv");
const card = (p: Page, m: string) => p.locator(`.rv-card[data-market="${m}"]`);
const tokenRgb = (p: Page, name: string) => p.evaluate((n) => {
  const el = document.createElement("span"); el.style.color = `var(${n})`; document.body.appendChild(el);
  const c = getComputedStyle(el).color; el.remove(); return c;
}, name);

test("제목·메뉴 이름은 '매크로 분석' — '경제 흐름'이라는 화면 이름이 없다", async ({ page }) => {
  await open(page);
  await expect(page.locator("h1")).toHaveText("매크로 분석");
  await expect(page.locator(".terminal-sidebar")).toContainText("매크로 분석");
  await expect(page.locator(".terminal-sidebar")).not.toContainText("경제 흐름");
});

test("도넛 = 서버 국면 확률 네 조각 — 응답을 바꾸면 조각 비와 가운데 글자가 따라 바뀐다(짝: 상수 배제)", async ({ page }) => {
  await patch(page, "regime", (x) => {
    const probs = { Goldilocks: 0.1, Reflation: 0.2, Stagflation: 0.6, Disinflation: 0.1 };
    x.regime = "Stagflation"; x.regime_probs = probs;
    if (x.markets?.kr) { x.markets.kr.regime = "Stagflation"; x.markets.kr.regime_probs = probs; }
  });
  await open(page);
  const segs = card(page, "kr").locator(".rv-donut-seg");
  await expect(segs).toHaveCount(4);
  const sweeps = await segs.evaluateAll((els) => Object.fromEntries(els.map((e) => [e.getAttribute("data-regime"), Number(e.getAttribute("data-sweep"))])));
  expect(sweeps.Stagflation / sweeps.Reflation).toBeCloseTo(3, 1);
  expect(sweeps.Goldilocks / sweeps.Reflation).toBeCloseTo(0.5, 1);
  await expect(card(page, "kr").locator(".rv-donut-c")).toContainText("스태그플레이션");
  await expect(card(page, "kr").locator(".rv-donut-c")).toContainText("60%");
  // 범례는 네 국면 모두 — 지금 국면이 표시된다
  await expect(card(page, "kr").locator(".rv-leg li")).toHaveCount(4);
  await expect(card(page, "kr").locator('.rv-leg li[data-now]')).toHaveAttribute("data-regime", "Stagflation");
});

test("확률이 없으면 빈 고리 + '확률 몰라요'(조각 0 · 0% 없음) · 미국이 없으면 미국 자리에 '몰라요'(짝)", async ({ page }) => {
  await patch(page, "regime", (x) => {
    delete x.regime_probs;
    if (x.markets?.kr) delete x.markets.kr.regime_probs;
    if (x.markets) delete x.markets.us;
  });
  await open(page);
  await expect(card(page, "kr").locator(".rv-donut-seg")).toHaveCount(0);
  await expect(card(page, "kr")).toContainText("확률 몰라요");
  await expect(card(page, "kr").locator(".rv-donut-c")).not.toContainText("0%");
  await expect(card(page, "us")).toContainText("미국 국면을 받지 못했어요");
  await expect(card(page, "us").locator(".rv-donut-seg")).toHaveCount(0);
});

test("국면 네 색은 서로 다르고 등락색(빨강·파랑)과 다르다 · 축 막대는 양·음 모두 같은 중립색", async ({ page }) => {
  await patch(page, "regime", (x) => {
    const kr = (x.markets?.kr ?? x) as Regime; kr.growth_axis = 0.4; kr.inflation_axis = -0.3;
  });
  await open(page);
  const fills = await card(page, "kr").locator(".rv-donut-seg").evaluateAll((els) => els.map((e) => getComputedStyle(e).stroke));
  expect(new Set(fills).size).toBe(4);
  const up = await tokenRgb(page, "--tx-up-ink"), down = await tokenRgb(page, "--tx-down-ink");
  for (const f of fills) { expect(f).not.toBe(up); expect(f).not.toBe(down); }
  const bars = await card(page, "kr").locator(".rv-axis-bar").evaluateAll((els) => els.map((e) => getComputedStyle(e).backgroundColor));
  expect(bars).toHaveLength(2);
  expect(bars[0]).toBe(bars[1]);
  expect(bars[0]).not.toBe(up); expect(bars[0]).not.toBe(down);
});

test("스트레스 반원 = 서버 값 · 구성 막대 = 서버 항목 수 · 값이 달라도 게이지 색은 같다(판정 색 띠 없음)", async ({ page }) => {
  const colorAt = async (score: number) => {
    await page.unroute("**/api/v1/macro/regime");
    await patch(page, "regime", (x) => { x.stress_score = score; x.stress_components = { vix: 30, credit_spread: 70, brand_new_key: 55 }; });
    await page.goto("/macro", { waitUntil: "domcontentloaded" });
    const g = page.locator('.rv-card[data-kind="stress"]');
    await expect(g.locator(".rv-gauge-v")).toHaveText(String(score), { timeout: 30_000 });
    await expect(g.locator(".rv-sc li")).toHaveCount(3);
    await expect(g.locator('.rv-sc li[data-key="brand_new_key"]')).toContainText("brand_new_key");   // 모르는 항목은 서버 이름 그대로
    return g.locator(".rv-gauge-fill").evaluate((e) => getComputedStyle(e).stroke);
  };
  const low = await colorAt(12), high = await colorAt(91);
  expect(low).toBe(high);
});

test("1440 — 한국·미국·스트레스 카드 높이가 같다(짝: 390 한 열에선 국면 카드가 스트레스 카드보다 작다 — 억지로 늘리지 않는다)", async ({ page }) => {
  await open(page);
  const h = async () => Promise.all(["kr", "us"].map((m) => card(page, m).boundingBox()).concat([page.locator('.rv-card[data-kind="stress"]').boundingBox()]));
  const [kr, us, st] = await h();
  expect(kr!.height).toBeGreaterThan(200);
  expect(Math.abs(kr!.height - st!.height)).toBeLessThanOrEqual(1);
  expect(Math.abs(us!.height - st!.height)).toBeLessThanOrEqual(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(400);
  const [kr2, , st2] = await h();
  expect(kr2!.height).toBeLessThan(st2!.height);
});

for (const t of ["light", "dark"] as const) {
  test(`국면 그림 AA — ${t}`, async ({ page }) => {
    await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, t);
    await open(page);
    await expect(viz(page)).toBeVisible();
    await page.waitForTimeout(800);
    const r = await page.evaluate<AuditResult>(contrastAudit(".rv"));
    expect(r.checked).toBeGreaterThan(10);
    expect(r.low, `${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
    if (t === "dark") expect(r.bright, `${t} 밝은 판`).toEqual([]);
  });
}
