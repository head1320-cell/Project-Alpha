import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, trackErrors, uniq, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BU8a · 첫 화면(/) — 히어로 · 스튜디오 둘러보기 · 도구 허브 · 리서치 경로 (계획 "BU8 상세" · ADR-003)
// ─────────────────────────────────────────────────────────────────────────────
// 사용자 결정: 히어로 = 서버가 지금 내는 답 한 문장 · 노란 연습용 띠는 영구 제거 · 히어로·스튜디오·리서치 경로만 남기고 나머지 삭제 ·
// ★포트폴리오 설계 스튜디오가 메인 도구라는 것을 실제 화면으로 설명★ · 모션·그래픽 강화.
// 거는 것(짝으로 항상-통과·항상-침묵을 배제):
//  · 히어로 답 = 서버 국면의 번역(응답을 바꾸면 문장이 바뀐다) · 실패는 alert + 다시 시도 · 연습용 칩은 connection-status 로만
//  · 히어로 그림(개정 2): 스튜디오 기본 흐름 — 노드 이름은 서버 카탈로그의 쉬운 이름 · 선은 실제로 이어지는 포트끼리(타입이 맞다) ·
//    관문 이름·순서는 서버 관문 목록 그대로 · 처음 열면 선이 그려지고 값이 흐른다(감속 모션이면 그려 둔 채 멈춤)
//  · 근거 짚기: '어디서 왔는지·무엇으로 쟀는지·언제 기준인지' 를 누르면 답 카드의 그 칩이 짚인다(짝: 다른 칩은 아니다)
//  · 바탕: 포인터를 따라 점이 밝아진다(짝: 감속 모션이면 따라오지 않는다) · 도구 허브는 어두운 띠 · 경로 끝은 파란 마무리 카드
//  · 스튜디오 둘러보기: 가운데 온 단계가 그 부위를 비추고 확대한다(짝: 다른 단계는 다른 부위·다른 확대) · 단계 단추로도 고른다 ·
//    실제 화면 이미지가 불러와진다 + 연습용 캡션
//  · 도구 허브: 다섯 도구 + 가운데 스튜디오 = 링크 6 · 선 5개가 화면에 들어오면 그려진다(짝: 들어오기 전엔 안 그려짐) ·
//    도구마다 실제 캔버스 노드 이름(서버 카탈로그 plain_label 과 같다)
//  · 리서치 경로 7단(참인 순서) · 저장소 용어는 닫힌 자세히 안에만 · 화면에 들어오면 선이 그려진다
//  · 지운 띠(노란 띠·약속·출처·질문·시작하기·바닥)가 없다 · 보이는 글: em-dash·합니다체·영어 대문자 소제목·툴팁 0
//  · 라이트/다크 AA · 390/1280/1440 가로 넘침 0 · 감속 모션이면 숨는 것 없이 처음부터 다 보인다 · 스크롤을 가로채지 않는다
// ═══════════════════════════════════════════════════════════════════════════════

const TOOLS: [string, string, string][] = [
  ["종목 찾기", "/screener", "조건으로 종목 거르기"], ["백테스트", "/backtest", "조건으로 골라 사고팔아 보기"],
  ["매크로 분석", "/macro", "경기 국면 불러오기"], ["기업 분석", "/insights", "적정가 매기기"], ["위험 점검", "/risk-tools", "상황에 넣어 보기"],
];
const MODE: Record<string, string> = { NORMAL: "보통", CAUTIOUS: "조심", DEFENSIVE: "방어" };
type Regime = { recommended_mode: string; stress_score: number };

const live = (p: Page) => p.locator(".ld-live");
const answer = (p: Page) => p.locator(".ld-live .tx-answer-s");

async function open(page: Page) {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".ld")).toBeVisible({ timeout: 20_000 });
}
/** 히어로의 `data-focus` 가 바뀐 기록 — 처음부터 남긴다(되풀이 단언은 저절로 지워진 뒤에 통과해 버리므로 기록으로 본다). */
async function recordFocus(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __focus: (string | null)[] };
    w.__focus = [];
    new MutationObserver((ms) => { for (const m of ms) w.__focus.push((m.target as Element).getAttribute("data-focus")); })
      .observe(document, { subtree: true, attributes: true, attributeFilter: ["data-focus"] });
  });
}
const focusLog = (page: Page) => page.evaluate(() => (window as unknown as { __focus: (string | null)[] }).__focus);
/** 흐르는 점이 '움직이며 보이는' 상태인가 — 숨었거나(display none) 멈춘 채 투명하면 아니다. */
const pktMoving = (page: Page) => page.locator(".ld-cv-pkt").first().evaluate((e) => {
  const st = getComputedStyle(e);
  return st.display !== "none" && (st.animationName !== "none" || parseFloat(st.opacity) > 0);
});

async function patchRegime(page: Page, edit: (b: Regime) => void) {
  await page.route("**/api/v1/macro/regime", async (route: Route) => {
    const res = await route.fetch();
    const b = (await res.json()) as Regime;
    edit(b);
    await route.fulfill({ response: res, json: b });
  });
}

test("히어로: 답 문장 = 서버 국면의 번역 — 응답을 DEFENSIVE 로 바꾸면 '방어'(짝) · 모르는 값이면 잰 값만", async ({ page }) => {
  const sink = trackErrors(page);
  const seen = page.waitForResponse((r) => r.url().endsWith("/api/v1/macro/regime"));
  await open(page);
  const body = (await (await seen).json()) as Regime;
  await expect(answer(page)).toHaveText(`지금 경제 흐름은 ‘${MODE[body.recommended_mode]}’ 단계예요`, { timeout: 20_000 });
  await expect(live(page)).toContainText("지금 서버가 내는 답");

  await patchRegime(page, (b) => { b.recommended_mode = "DEFENSIVE"; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(answer(page)).toHaveText("지금 경제 흐름은 ‘방어’ 단계예요", { timeout: 20_000 });

  await page.unroute("**/api/v1/macro/regime");
  await patchRegime(page, (b) => { b.recommended_mode = "SOMETHING_NEW"; b.stress_score = 41.4; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(answer(page)).toHaveText("지금 시장 스트레스는 41/100이에요", { timeout: 20_000 });
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
});

test("★히어로: 국면 실패는 alert + 다시 시도★ — 풀고 누르면 문장이 뜬다 · 정상이면 alert 없음(짝)", async ({ page }) => {
  await open(page);
  await expect(answer(page)).toBeVisible({ timeout: 20_000 });
  await expect(live(page).locator("[role='alert']")).toHaveCount(0);

  await page.route("**/api/v1/macro/regime", (r) => r.fulfill({ status: 500, json: { detail: "x" } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  const alert = live(page).locator("[role='alert']");
  await expect(alert).toContainText("매크로 분석을 불러오지 못했어요", { timeout: 20_000 });
  await expect(answer(page)).toHaveCount(0);
  await page.unroute("**/api/v1/macro/regime");
  await live(page).locator("button", { hasText: "다시 시도" }).click();
  await expect(answer(page)).toBeVisible({ timeout: 20_000 });
  await expect(alert).toHaveCount(0);
});

test("히어로: 연습용 칩은 connection-status 로만 — mock 이면 있고 · 실데이터 응답이면 없다(짝)", async ({ page }) => {
  const chip = (tone: string) => page.locator(`.ld-live .tx-chip[data-tone="${tone}"]`);
  const cs = page.waitForResponse((r) => r.url().endsWith("/api/v1/macro/connection-status"));
  await open(page);
  const st = (await (await cs).json()) as { mock_allowed: boolean; bok_configured: boolean };
  expect(st.mock_allowed && !st.bok_configured, "이 환경은 mock 이다").toBe(true);
  await expect(chip("practice")).toHaveText("연습용 데이터", { timeout: 20_000 });

  await page.route("**/api/v1/macro/connection-status", (r) => r.fulfill({ json: { mock_allowed: false, real_mode: true, bok_configured: true, fred_configured: true } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(answer(page)).toBeVisible({ timeout: 20_000 });
  await expect(chip("ok")).toHaveText("한국은행 실데이터");
  await expect(chip("practice")).toHaveCount(0);
});

test("히어로: 주 단추는 하나(포트폴리오 설계 시작) · 보조는 홈으로 · 머리 줄에 로그인", async ({ page }) => {
  await open(page);
  const hero = page.locator(".ld-hero");
  await expect(hero.locator("h1")).toBeVisible();
  const main = hero.locator(".tx-btn--main");
  await expect(main).toHaveCount(1);
  await expect(main).toHaveText("포트폴리오 설계 시작");
  await expect(main).toHaveAttribute("href", "/allocation");
  await expect(hero.locator(".ld-hero-cta .tx-btn--sub")).toHaveText("홈으로");
  await expect(hero.locator(".ld-hero-cta .tx-btn--sub")).toHaveAttribute("href", "/dashboard");
  await expect(page.locator(".ld-head a.ld-login")).toHaveAttribute("href", "/login");
});

type CatNode = { type: string; plain_label?: string; inputs?: { type: string }[]; outputs?: { type: string }[] };
async function catalog(request: import("@playwright/test").APIRequestContext) {
  const cat = await (await request.get("/api/backend/api/v1/allocation/graph/node-types")).json();
  return { nodes: (Array.isArray(cat) ? cat : cat.nodes) as CatNode[], gates: (cat.gates ?? []) as { key: string; label: string }[] };
}

test("★히어로 그림: 스튜디오 기본 흐름 — 노드 이름 = 서버 카탈로그 · 선은 실제로 이어지는 포트끼리 · 관문 = 서버 관문 목록 순서 그대로★", async ({ page, request }) => {
  await open(page);
  const { nodes, gates } = await catalog(request);
  const byType = new Map(nodes.map((n) => [n.type, n]));
  const cv = page.locator(".ld-hero .ld-cv");
  await expect(cv).toBeVisible();
  const drawn = await cv.locator(".ld-cv-node").evaluateAll((els) => els.map((e) => [e.getAttribute("data-node"), e.querySelector(".ld-cv-t")?.textContent]));
  expect(drawn.length, "노드가 비면 이 검사는 아무것도 지키지 못한다").toBeGreaterThanOrEqual(5);
  for (const [type, label] of drawn) {
    const n = byType.get(type ?? "");
    expect(n, `카탈로그에 '${type}' 노드가 있다`).toBeTruthy();
    expect(label, `${type} 의 이름은 카탈로그 쉬운 이름`).toBe(n!.plain_label);
  }
  // 선은 지어낸 관계가 아니다 — 보내는 노드의 출력과 받는 노드의 입력에 같은 타입이 실제로 있다.
  const wires = await cv.locator(".ld-cv-wire").evaluateAll((els) => els.map((e) => [e.getAttribute("data-from"), e.getAttribute("data-to"), e.getAttribute("data-t")]));
  expect(wires.length).toBeGreaterThanOrEqual(5);
  for (const [from, to, t] of wires) {
    expect((byType.get(from ?? "")?.outputs ?? []).map((p) => p.type), `${from} 가 ${t} 를 낸다`).toContain(t);
    expect((byType.get(to ?? "")?.inputs ?? []).map((p) => p.type), `${to} 가 ${t} 를 받는다`).toContain(t);
  }
  const g = await cv.locator(".ld-cv-gate").evaluateAll((els) => els.map((e) => [e.getAttribute("data-gate"), e.getAttribute("data-label")]));
  expect(g).toEqual(gates.map((x) => [x.key, x.label]));
  // 그림 안에 숫자(성과처럼 보이는 값)를 그리지 않는다.
  expect(await cv.evaluate((e) => e.textContent ?? "")).not.toMatch(/\d/);
});

test("★근거 짚기: 누르면 답 카드의 그 칩을 짚는다 · 짝: 다른 칩은 짚지 않는다 · 다른 단추면 옮겨 간다★", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });   // 처음 한 번 저절로 짚는 차례를 끄고 손으로만 본다
  await open(page);
  await expect(answer(page)).toBeVisible({ timeout: 20_000 });
  const hero = page.locator(".ld-hero");
  const chip = (k: string) => page.locator(`.ld-live .tx-chip[data-ev="${k}"]`);
  await expect(chip("source")).toHaveCount(1);
  await expect(chip("model")).toHaveCount(1);
  const ring = (k: string) => chip(k).evaluate((e) => getComputedStyle(e).boxShadow);
  const base = await ring("source");
  await expect(hero).not.toHaveAttribute("data-focus");

  const btn = (k: string) => page.locator(`.ld-ev-btn[data-ev="${k}"]`);
  await expect(page.locator(".ld-ev-btn")).toHaveCount(3);
  await btn("source").click();
  await expect(hero).toHaveAttribute("data-focus", "source");
  await expect(btn("source")).toHaveAttribute("aria-pressed", "true");
  expect(await ring("source"), "짚은 칩은 테두리가 생긴다").not.toBe(base);
  expect(await ring("model"), "짝: 다른 칩은 그대로").toBe(base);
  await expect(page.locator(".ld-ev-d")).toContainText("연습용");

  await btn("model").click();
  await expect(hero).toHaveAttribute("data-focus", "model");
  await expect(btn("source")).toHaveAttribute("aria-pressed", "false");
  expect(await ring("model")).not.toBe(base);
  expect(await ring("source")).toBe(base);
});

test("히어로 바탕: 포인터를 따라 점이 밝아진다 · 짝: 감속 모션이면 따라오지 않는다", async ({ page }) => {
  await open(page);
  const hero = page.locator(".ld-hero");
  const box = (await hero.boundingBox())!;
  await page.mouse.move(box.x + 200, box.y + 160);
  await page.mouse.move(box.x + 260, box.y + 200);
  await expect(hero).toHaveAttribute("data-ptr");
  expect(await hero.evaluate((e) => e.style.getPropertyValue("--mx"))).toMatch(/px$/);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".ld")).toBeVisible();
  await page.mouse.move(box.x + 220, box.y + 180);
  await page.mouse.move(box.x + 300, box.y + 220);
  await page.waitForTimeout(300);
  await expect(hero).not.toHaveAttribute("data-ptr");
});

test("히어로 움직임: 처음 열면 선이 그려지고 값이 흐르고, 근거를 한 번 차례로 짚고 멈춘다 · 짝: 감속 모션이면 그려 둔 채 흐르는 점이 없다", async ({ page }) => {
  await recordFocus(page);
  await open(page);
  const wires = page.locator(".ld-cv-wire");
  await expect.poll(() => wires.evaluateAll((els) => Math.max(...els.map((e) => parseFloat(getComputedStyle(e).strokeDashoffset)))),
    { timeout: 8_000 }).toBeLessThan(0.02);
  await expect.poll(() => page.locator(".ld-cv-pkt").first().evaluate((e) => parseFloat(getComputedStyle(e).opacity)), { timeout: 8_000 }).toBeGreaterThan(0.5);
  expect(await pktMoving(page)).toBe(true);
  // 처음 한 번만 저절로 짚는다: 출처 → 잰 모형 → 기준 시각 → 놓음(되풀이하지 않는다).
  await expect.poll(() => focusLog(page), { timeout: 12_000 }).toEqual(["source", "model", "asof", null]);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".ld")).toBeVisible();
  expect(await pktMoving(page), "감속 모션에서 흐르는 점").toBe(false);
  expect(await wires.first().evaluate((e) => parseFloat(getComputedStyle(e).strokeDashoffset))).toBeLessThan(0.02);
});

test("띠마다 다른 결: 도구 허브는 어두운 띠 · 짝: 스튜디오 띠는 밝다 · 경로 끝은 파란 마무리 카드에 주 단추", async ({ page }) => {
  await open(page);
  const lum = (sel: string) => page.locator(sel).first().evaluate((e) => {
    const m = getComputedStyle(e).backgroundColor.match(/\d+(\.\d+)?/g)!.map(Number);
    const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(m[0]) + 0.7152 * f(m[1]) + 0.0722 * f(m[2]);
  });
  expect(await lum(".ld-band--ink"), "허브 띠는 어둡다").toBeLessThan(0.05);
  expect(await lum(".ld-studio"), "짝: 스튜디오 띠는 밝다").toBeGreaterThan(0.8);
  await expect(page.locator(".ld-band--ink .ld-hub")).toHaveCount(1);
  const end = page.locator(".ld-path .ld-end");
  await expect(end.locator(".ld-end-t")).toBeVisible();
  await expect(end.locator(".tx-btn--main")).toHaveText("포트폴리오 설계 시작");
  expect(await lum(".ld-end"), "마무리 카드는 진한 파랑").toBeLessThan(0.2);
});

/** 스튜디오 둘러보기의 n 번째 단계를 화면 가운데로 — IntersectionObserver 가 그 단계를 고르게 한다. */
async function centerStep(page: Page, n: number) {
  await page.locator(`.ld-tour-step[data-step="${n}"]`).evaluate((el) => el.scrollIntoView({ block: "center" }));
}
const tourActive = (p: Page) => p.locator(".ld-tour").getAttribute("data-active");
const zoomOf = (p: Page) => p.locator(".ld-tour-zoom").evaluate((e) => getComputedStyle(e).transform);

test("★지운 띠가 없다 — 노란 연습용 띠·약속·출처·질문·시작하기·바닥 · 예시 수치 덱★ · 짝: 연습용 여부는 히어로 답의 칩이 말한다", async ({ page }) => {
  await open(page);
  await expect(page.locator(".ld-top, .lp-topbar")).toHaveCount(0);
  await expect(page.locator(".ld-promise, .ld-checks, .ld-src, .ld-faq, .ld-start, .ld-foot, .lp-deck")).toHaveCount(0);
  await expect(page.locator(".ld")).not.toContainText(/KIS_USE_MOCK|dry_run|예시 수치|Sharpe|\+24\.6%|1,539|\b181\b/);
  await expect(page.locator(".ld main > section")).toHaveCount(4);
  await expect(page.locator('.ld-live .tx-chip[data-tone="practice"]')).toHaveText("연습용 데이터", { timeout: 20_000 });
});

test("★스튜디오 둘러보기: 가운데 온 단계가 그 부위를 비추고 다가간다 · 짝: 다른 단계는 다른 부위·다른 확대★", async ({ page }) => {
  await open(page);
  await expect(page.locator(".ld-tour-step")).toHaveCount(4);
  await expect(page.locator(".ld-spot")).toHaveCount(4);
  expect(await tourActive(page), "아직 단계에 닿지 않았으면 한눈에").toBe("0");
  await expect(page.locator(".ld-spot[data-on]")).toHaveCount(0);
  const overview = await zoomOf(page);

  await centerStep(page, 2);
  await expect.poll(() => tourActive(page)).toBe("2");
  await expect(page.locator(".ld-spot[data-on]")).toHaveCount(1);
  await expect(page.locator('.ld-spot[data-spot="2"]')).toHaveAttribute("data-on");
  await expect.poll(() => page.locator('.ld-spot[data-spot="2"]').evaluate((e) => parseFloat(getComputedStyle(e).opacity))).toBeGreaterThan(0.95);
  expect(await page.locator('.ld-spot[data-spot="1"]').evaluate((e) => parseFloat(getComputedStyle(e).opacity))).toBeLessThan(0.05);
  await expect(page.locator('.ld-tour-step[data-step="2"] .ld-tour-btn')).toHaveAttribute("aria-pressed", "true");
  const z2 = await zoomOf(page);
  expect(z2, "단계에 닿으면 화면이 그 부위로 다가간다").not.toBe(overview);

  await centerStep(page, 3);
  await expect.poll(() => tourActive(page)).toBe("3");
  await expect(page.locator('.ld-spot[data-spot="3"]')).toHaveAttribute("data-on");
  await expect(page.locator('.ld-spot[data-spot="2"]')).not.toHaveAttribute("data-on");
  await expect.poll(() => zoomOf(page)).not.toBe(z2);
});

test("스튜디오 둘러보기: 단계 제목은 단추라 눌러서(키보드로도) 고른다 · 실제 화면이 불러와지고 연습용 캡션이 붙는다", async ({ page }) => {
  await open(page);
  const btn = page.locator('.ld-tour-step[data-step="4"] .ld-tour-btn');
  await btn.focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => tourActive(page)).toBe("4");
  await expect(page.locator('.ld-spot[data-spot="4"]')).toHaveAttribute("data-on");

  const img = page.locator(".ld-tour-zoom img.ld-shot-light");
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((e) => (e as HTMLImageElement).complete && (e as HTMLImageElement).naturalWidth), { timeout: 20_000 }).toBeGreaterThan(0);
  expect((await img.getAttribute("alt"))?.length ?? 0, "그림 설명(alt)").toBeGreaterThan(20);
  await expect(page.locator(".ld-tour-zoom img.ld-shot-dark")).toBeHidden();
  await expect(page.locator(".ld-tour .ld-shot-cap")).toContainText("연습용");
});

test("★도구 허브: 다섯 도구 + 가운데 스튜디오 = 링크 6 · 도구마다 실제 캔버스 노드 이름(서버 카탈로그와 같다)★", async ({ page, request }) => {
  await open(page);
  const core = page.locator(".ld-hub-core");
  await expect(core).toHaveAttribute("href", "/allocation");
  await expect(core.locator(".ld-mod-t")).toHaveText("포트폴리오 설계");
  await expect(page.locator(".ld-mod")).toHaveCount(6);
  const got = await page.locator(".ld-hub-tool").evaluateAll((els) => els.map((e) => [
    e.querySelector(".ld-mod-t")?.textContent, e.getAttribute("href"), e.querySelector(".ld-hub-node b")?.textContent]));
  expect(got).toEqual(TOOLS);
  // 노드 이름은 지어낸 말이 아니다 — 서버 노드 카탈로그의 쉬운 이름에 그대로 있다.
  const cat = await (await request.get("/api/backend/api/v1/allocation/graph/node-types")).json();
  const nodes = (Array.isArray(cat) ? cat : cat.nodes) as { plain_label?: string }[];
  const labels = new Set(nodes.map((n) => n.plain_label));
  for (const [, , node] of TOOLS) expect(labels.has(node), `캔버스에 '${node}' 노드가 있다`).toBe(true);
});

test("★도구 허브: 선 다섯이 화면에 들어오면 그려진다 · 짝: 들어오기 전에는 그려지지 않았다★", async ({ page }) => {
  await open(page);
  const hub = page.locator(".ld-hub");
  await expect(page.locator(".ld-hub-line")).toHaveCount(5);
  await expect(hub).toHaveAttribute("data-arm");
  await expect(hub).not.toHaveAttribute("data-in");
  const before = await page.locator(".ld-hub-line").first().evaluate((e) => parseFloat(getComputedStyle(e).strokeDashoffset));
  expect(before, "아직 화면 밖이면 선이 그려지지 않았다").toBeGreaterThan(0.9);
  await hub.scrollIntoViewIfNeeded();
  await expect(hub).toHaveAttribute("data-in");
  await expect.poll(() => page.locator(".ld-hub-line").evaluateAll((els) => Math.max(...els.map((e) => parseFloat(getComputedStyle(e).strokeDashoffset)))),
    { timeout: 8_000 }).toBeLessThan(0.02);
});

test("리서치 경로: 일곱 단계가 순서대로 · 화면에 들어오면 선이 그려진다 · 저장소 용어는 닫힌 자세히 안에만(짝: 열면 보인다)", async ({ page }) => {
  await open(page);
  const steps = page.locator(".ld-step");
  await expect(steps).toHaveCount(7);
  const ns = await steps.locator(".ld-step-n").allInnerTexts();
  expect(ns.map((x) => x.trim())).toEqual(["1", "2", "3", "4", "5", "6", "7"]);
  const ol = page.locator(".ld-steps");
  await expect(ol).not.toHaveAttribute("data-in");
  await ol.scrollIntoViewIfNeeded();
  await expect(ol).toHaveAttribute("data-in");
  await expect.poll(() => steps.last().evaluate((e) => parseFloat(getComputedStyle(e).opacity)), { timeout: 8_000 }).toBeGreaterThan(0.95);

  const band = page.locator(".ld-path");
  const rec = band.locator("details.ld-rec");
  expect(await rec.evaluate((e) => (e as HTMLDetailsElement).open), "처음에는 닫혀 있다").toBe(false);
  const ids = ["snapshot_id", "name@version", "pack_id@해시", "run_id"];
  const closed = await band.innerText();
  for (const id of ids) expect(closed, `${id} 는 보이는 글에 없다`).not.toContain(id);
  await rec.locator("summary").click();
  const opened = await band.innerText();
  for (const id of ids) expect(opened, `${id} 는 자세히 안에 그대로 있다`).toContain(id);
  await expect(band).not.toContainText("LIVE");
  await expect(band.locator(".ld-end .tx-btn--main")).toHaveText("포트폴리오 설계 시작");
});

test("★보이는 글: em-dash 0 · 합니다체 0 · 영어 대문자 소제목 0 · 툴팁 0★", async ({ page }) => {
  await open(page);
  await expect(answer(page)).toBeVisible({ timeout: 20_000 });
  const root = page.locator(".ld");
  // 닫힌 자세히(질문 답·기록 목록)도 펼쳐서 함께 읽는다 — 닫혀 있으면 innerText 에 들어오지 않는다.
  await root.locator("details").evaluateAll((ds) => ds.forEach((d) => { (d as HTMLDetailsElement).open = true; }));
  const text = await root.innerText();
  expect(text, "보이는 글에 em-dash").not.toContain("—");
  expect(text.match(/[가-힣](습니다|합니다|입니다)[.\s]/g) ?? [], "해요체로 쓴다").toEqual([]);
  const heads = await root.locator("h1, h2, h3").allInnerTexts();
  for (const h of heads) expect(h, `소제목에 영어 대문자: ${h}`).not.toMatch(/[A-Z]{3,}/);
  await expect(root.locator("[title]")).toHaveCount(0);
  await expect(root).not.toContainText(/RESEARCH MODULES|THREE INVARIANTS|EVIDENCE PATH|DATA SOURCES|ENFORCED/);
});

for (const theme of ["light", "dark"] as const) {
  test(`첫 화면 대비 AA (${theme}) · 다크를 고르면 첫 화면도 다크`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await open(page);
    expect(await page.evaluate(() => document.documentElement.classList.contains("dark")), "테마를 따른다").toBe(theme === "dark");
    await expect(answer(page)).toBeVisible({ timeout: 20_000 });
    const shot = page.locator(".ld-tour-zoom");
    await expect(shot.locator(theme === "dark" ? "img.ld-shot-dark" : "img.ld-shot-light")).toBeVisible();
    await expect(shot.locator(theme === "dark" ? "img.ld-shot-light" : "img.ld-shot-dark")).toBeHidden();
    const r = await page.evaluate<AuditResult>(contrastAudit(".ld"));
    expect(r.checked).toBeGreaterThan(40);
    expect(r.low, JSON.stringify(r.low)).toEqual([]);
    if (theme === "dark") expect(r.bright, "다크인데 밝은 판").toEqual([]);
  });
}

test("★감속 모션이면 숨는 것 없이 처음부터 다 보이고, 움직임 없이 바로 바뀐다★", async ({ page }) => {
  await recordFocus(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page);
  const els = await page.locator(".ld-line > span, .ld-rise, .ld-cv, .ld-cv-node, .ld-stage-card, .ld-h2, .ld-tour-frame, .ld-hub-tool, .ld-hub-core, .ld-step").all();
  expect(els.length, "검사 대상이 비면 이 테스트는 아무것도 지키지 못한다").toBeGreaterThan(15);
  for (const el of els) {
    const op = await el.evaluate((e) => parseFloat(getComputedStyle(e).opacity));
    expect(op, "감속 모션에서 투명한 요소가 있으면 안 된다").toBeGreaterThan(0.9);
  }
  // 화면에 들어오기 전에도 선은 그려져 있고 흐르는 점은 없다.
  expect(await page.locator(".ld-hub-line").first().evaluate((e) => parseFloat(getComputedStyle(e).strokeDashoffset))).toBeLessThan(0.02);
  await expect(page.locator(".ld-hub-flow").first()).toBeHidden();
  expect(await page.locator(".ld-tour-zoom").evaluate((e) => getComputedStyle(e).transitionDuration)).toBe("0s");
  // 히어로 그림도 그려 둔 채로 · 근거 짚기는 저절로 돌지 않는다(손으로 누를 때만).
  expect(await page.locator(".ld-cv-wire").first().evaluate((e) => parseFloat(getComputedStyle(e).strokeDashoffset))).toBeLessThan(0.02);
  // 저절로 짚는 차례(처음 연 뒤 2.6~7.4초)가 지나도록 기다린 뒤, 한 번이라도 짚었는지 기록으로 본다.
  await page.waitForTimeout(8_500);
  expect(await focusLog(page), "감속 모션에서 저절로 짚었다").toEqual([]);
});

test("스크롤을 가로채지 않는다", async ({ page }) => {
  await open(page);
  await page.evaluate(() => window.scrollTo(0, 900));
  await page.waitForTimeout(350);
  expect(await page.evaluate(() => window.scrollY), "스크롤이 취소되거나 되돌려지면 안 된다").toBeGreaterThan(400);
  const snap = await page.evaluate(() =>
    getComputedStyle(document.documentElement).scrollSnapType + "|" + getComputedStyle(document.body).scrollSnapType);
  expect(snap).toMatch(/none\|none/);
});

for (const [w, h] of [[390, 844], [1280, 900], [1440, 900]] as [number, number][]) {
  test(`첫 화면 ${w}px: 가로 넘침 없이 띠가 모두 있다`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await open(page);
    await expect(answer(page)).toBeVisible({ timeout: 20_000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `가로 넘침 @${w}`).toBeLessThanOrEqual(1);
    await expect(page.locator(".ld-mod")).toHaveCount(6);
    await expect(page.locator(".ld-step")).toHaveCount(7);
    await expect(page.locator(".ld-tour-step")).toHaveCount(4);
    // 좁은 폭에서도 실제 화면(스튜디오)은 단계 글과 함께 보인다.
    await centerStep(page, 2);
    await expect(page.locator(".ld-tour-frame")).toBeInViewport();
    if (w === 390) {
      // 390: 히어로 제목과 주 단추가 첫 화면에 보인다.
      const btn = await page.locator(".ld-hero .tx-btn--main").boundingBox();
      expect(btn).not.toBeNull();
      expect(btn!.y + btn!.height).toBeLessThan(h);
    }
  });
}

test("BL4: 예전 리서치 단계 링크는 캔버스로 곧장 간다 — 리다이렉트를 거치지 않고, 그 화면이 하던 일을 안내한다", async ({ page }) => {
  await open(page);
  const hrefs = await page.locator(".ld-path a").evaluateAll(
    (els) => [...new Set(els.map((e) => e.getAttribute("href") ?? "").filter((h) => h.startsWith("/allocation")))]);
  expect(hrefs.filter((h) => /^\/allocation\/[a-z]/.test(h)), hrefs.join(", ")).toEqual([]);
  const legacy = hrefs.filter((h) => h.includes("from="));
  // 바닥 링크를 지운 뒤로는 리서치 경로의 다섯 단계 링크만 남는다(macro·timing·stress·optimize·journal).
  expect(legacy.length, hrefs.join(", ")).toBeGreaterThanOrEqual(5);
  for (const h of legacy) {
    const res = await page.goto(h, { waitUntil: "domcontentloaded" });
    expect(res?.status(), h).toBe(200);
    await expect(page.locator(".pg-legacy"), h).toBeVisible({ timeout: 30_000 });
  }
});
