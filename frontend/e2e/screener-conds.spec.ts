import { test, expect, type Browser, type Locator, type Page } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * 종목 찾기 — 조건 영역의 촘촘한 꼴과 접기 (U1-d · 계획 `docs/superpowers/plans/2026-11-21-uiux-u1-table-screener.md`)
 * ─────────────────────────────────────────────────────────────────
 * 옮기기 전에는 조건 영역이 창 높이의 3분의 1(1440 × 900 에서 약 290px)을 차지해 결과 표가 아래로 밀렸다.
 * 조건 조작의 길 · `data-act` 훅 · 요청은 그대로다(`screener-requests.spec.ts` 의 골든이 바이트로 건다). 여기는 꼴과 접기다.
 * 거는 것(짝으로 항상-통과를 배제):
 *  · 조건 영역의 높이가 줄었다 · 그 결과 다 보이는 줄이 더 늘었다
 *  · 접기 단추: 이름 · `aria-expanded` · `aria-controls` · 접으면 한 줄 요약(유니버스 · 시가총액 · 조건 수와 그 글) · 접힌 조작 요소는 초점을 받지 않는다
 *  · 접기는 이 브라우저에 남는다 ↔ 기본은 펼침
 *  · ★접고 펴도 요청이 나가지 않고 조건의 값이 그대로다★(겉모습만 바꾼다) · 펼쳐 둔 전문가 설정도 그대로 펼쳐져 있다
 *  · 접으면 다 보이는 줄이 더 는다
 *  · 조건을 넣고 전문가 설정을 편 상태에서도 누르는 것 24px 이상 · 대비 AA(라이트 · 다크)
 *  · 강조는 잉크다 — 고른 알약 · 켠 스위치가 옛 강조색(파랑)이 아니다
 *  · 좁은 화면: 가로로 밀리지 않고 접기 단추가 다른 조작 요소를 가리지 않는다 · 손가락 화면의 입력 글자는 16px 이상
 *  · 접기 단추는 떠 있다(줄을 하나 더 쓰지 않는다) — 밀도 셋 × 창 폭을 훑어 어느 폭에서도 다른 조작 요소 · 요약 글자를 가리지 않는다
 *  · 자판 초점이 보인다 — 목록 · 펼침 머리 · 값 칸 모두 잉크 2px 실선(값 칸의 초점을 끄지 않는다)
 *  · 분포 막대는 등락의 색(파랑 = 하락)이 아니다 · 채운 주 단추는 조건 영역에 없다(화면의 주 단추는 답 줄 하나)
 */

const rows = (p: Page) => p.locator(".bsc-table tbody tr.bsc-row");
const act = (p: Page, a: string) => p.locator(`[data-act="${a}"]`);
const toggle = (p: Page) => act(p, "conds-toggle");
const SEARCH = "조건을 단어로 입력하십시오";

async function open(page: Page) {
  await page.goto("/screener", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".scr-answer .tx-answer-s")).toBeVisible({ timeout: 30_000 });
  await expect(rows(page).first()).toBeVisible();
}
async function addFactor(page: Page, name: string) {
  await act(page, "add-factor").first().click();
  await page.getByPlaceholder(SEARCH).fill(name);
  await page.locator(".tfm-row").filter({ has: page.locator(`.tfm-row-d:text-is("{${name}}")`) }).first().click();
  await page.getByRole("button", { name: "입력", exact: true }).click();
  await expect(page.getByPlaceholder(SEARCH)).toHaveCount(0);
}
const fullRows = (page: Page) => page.evaluate(() => {
  const wrap = document.querySelector(".bsc-table-wrap")!.getBoundingClientRect(), head = document.querySelector(".bsc-table thead")!.getBoundingClientRect();
  const bottom = Math.min(window.innerHeight, wrap.bottom);
  return [...document.querySelectorAll(".bsc-table tbody tr.bsc-row")].filter((tr) => { const r = tr.getBoundingClientRect(); return r.top >= head.bottom - 0.5 && r.bottom <= bottom + 0.5; }).length;
});
/** 접기 단추의 상자와 겹치는 조작 요소(단추 자신은 뺀다). */
const toggleHits = (page: Page) => page.evaluate(() => {
  const t = document.querySelector('[data-act="conds-toggle"]')!.getBoundingClientRect();
  return [...document.querySelectorAll(".scr-conds :is(select, input, button, summary)")].filter((e) => e.getAttribute("data-act") !== "conds-toggle").filter((e) => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.left < t.right && r.right > t.left && r.top < t.bottom && r.bottom > t.top;
  }).map((e) => `${e.tagName.toLowerCase()}.${e.className}`);
});
const ring = (l: Locator) => l.evaluate((e) => { const s = getComputedStyle(e); return { style: s.outlineStyle, width: s.outlineWidth, color: s.outlineColor }; });
const token = (page: Page, name: string) => page.evaluate((n) => { const s = document.createElement("span"); s.style.color = `var(${n})`; document.body.appendChild(s); const c = getComputedStyle(s).color; s.remove(); return c; }, name);

test.use({ viewport: { width: 1440, height: 900 } });

/** 두 요소의 세로 가운데 차이(px). */
const midGap = (page: Page, a: string, b: string) => page.evaluate(([x, y]) => {
  const m = (sel: string) => { const r = document.querySelector(sel)!.getBoundingClientRect(); return r.top + r.height / 2; };
  return Math.abs(m(x) - m(y));
}, [a, b]);

test("조건 영역이 낮아졌다(옮기기 전 약 290px) · 그 결과 다 보이는 줄이 16줄 이상이다(1440 × 900 · 촘촘 · 조건 없음)", async ({ page }) => {
  await open(page);
  const h = Math.round(await page.locator(".scr-conds").evaluate((e) => e.getBoundingClientRect().height));
  expect(h, "조건 영역의 높이(잰 값 97 — 줄 셋: 유니버스 · 시가총액 / 조건 / 전문가 설정)").toBeLessThanOrEqual(110);
  expect(h, "짝 — 영역이 실제로 그려져 있다").toBeGreaterThan(60);
  expect(await fullRows(page)).toBeGreaterThanOrEqual(16);
  expect(await midGap(page, '[data-act="conds-toggle"]', '[data-act="universe"]'), "접기 단추는 첫 줄과 같은 높이에 떠 있다(줄을 하나 더 쓰지 않는다)").toBeLessThanOrEqual(1);
  for (const a of ["universe", "mcap-preset", "add-factor", "expert"]) await expect(act(page, a).first(), `${a} 은(는) 펼친 채로 보인다`).toBeVisible();
});

test("접기 단추: 이름 · aria-expanded · aria-controls · 접으면 한 줄 요약 · 접힌 조작 요소는 보이지도 초점을 받지도 않는다", async ({ page }) => {
  await open(page);
  const t = toggle(page);
  await expect(t).toHaveAccessibleName("조건 접기");
  await expect(t).toHaveAttribute("aria-expanded", "true");
  const bodyId = await t.getAttribute("aria-controls");
  expect(bodyId, "가리키는 본문이 있다").toBeTruthy();
  await expect(page.locator(`[id="${bodyId}"]`)).toBeVisible();
  await expect(page.locator(".scr-conds-sum"), "펼친 채로는 요약이 없다(같은 것을 두 번 적지 않는다)").toHaveCount(0);

  await t.click();
  await expect(t).toHaveAttribute("aria-expanded", "false");
  await expect(t).toHaveAccessibleName("조건 펴기");
  await expect(page.locator(`[id="${bodyId}"]`)).toBeHidden();
  await expect(page.locator(`[id="${bodyId}"]`), "aria-controls 가 가리키는 본문은 접혀도 그 자리에 있다(숨길 뿐 지우지 않는다)").toHaveCount(1);
  await expect(page.locator(".scr-conds-sum")).toHaveText("유니버스 코스피 200 · 시가총액 전체 · 조건 없음");
  expect(await midGap(page, '[data-act="conds-toggle"]', ".scr-conds-sum"), "접어도 단추와 요약이 같은 높이").toBeLessThanOrEqual(1);
  for (const a of ["universe", "mcap-preset", "add-factor", "expert"]) await expect(act(page, a).first(), `${a} 은(는) 접히면 보이지 않는다`).toBeHidden();
  // 자판으로 걸어도 접힌 조작 요소에 서지 않는다
  await t.focus();
  const seen: string[] = [];
  for (let i = 0; i < 6; i++) { await page.keyboard.press("Tab"); seen.push(await page.evaluate(() => document.activeElement?.getAttribute("data-act") ?? document.activeElement?.className ?? "")); }
  expect(seen.filter((x) => ["universe", "mcap-preset", "add-factor", "expert", "gate"].includes(x)), `걸은 자리: ${seen.join(" → ")}`).toEqual([]);
  expect(Math.round(await page.locator(".scr-conds").evaluate((e) => e.getBoundingClientRect().height)), "접힌 영역은 한 줄").toBeLessThanOrEqual(44);
  // 요약의 글자 상자는 접기 단추 아래로 들어가지 않는다(길면 줄을 바꾼다)
  const edge = await page.evaluate(() => {
    const sum = document.querySelector(".scr-conds-sum")!, t = document.querySelector('[data-act="conds-toggle"]')!.getBoundingClientRect();
    return { text: sum.getBoundingClientRect().right - parseFloat(getComputedStyle(sum).paddingRight), toggle: t.left };
  });
  expect(edge.text, JSON.stringify(edge)).toBeLessThanOrEqual(edge.toggle);
});

test("접기 단추는 떠 있다 — 밀도 셋 × 창 폭(480 ~ 1440)을 훑어 어느 폭에서도 다른 조작 요소를 가리지 않는다", async ({ page }) => {
  for (const density of ["compact", "regular", "comfortable"]) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await page.evaluate((d) => localStorage.setItem("alpha_density", d), density);
    await open(page);
    await expect(page.locator("html")).toHaveAttribute("data-density", density);
    const widths = [480, 600, ...Array.from({ length: 15 }, (_, i) => 680 + i * 30), 1280, 1440];
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      expect(await toggleHits(page), `${density} · ${width}px`).toEqual([]);
    }
    expect(widths.length, "짝 — 훑은 폭이 있다").toBeGreaterThan(15);
  }
});

test("자판 초점이 보인다 — 목록 · 펼침 머리 · 값 칸의 고리는 잉크 2px 실선(짝: 초점이 없으면 고리가 없다)", async ({ page }) => {
  await open(page);
  await addFactor(page, "PER");
  const want = { style: "solid", width: "2px", color: await token(page, "--tx-focus") };
  const custom = page.locator(".scr-mcap-custom > summary");
  expect((await ring(custom)).style, "짝 — 초점이 없는 펼침 머리").toBe("none");
  await toggle(page).focus();
  await page.keyboard.press("Tab");
  await expect(act(page, "universe")).toBeFocused();
  expect(await ring(act(page, "universe")), "목록").toEqual(want);
  for (let i = 0; i < 8 && !(await custom.evaluate((e) => e === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(custom).toBeFocused();
  expect(await ring(custom), "펼침 머리(직접 입력)").toEqual(want);
  const val = act(page, "cond-val").first();
  for (let i = 0; i < 8 && !(await val.evaluate((e) => e === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(val).toBeFocused();
  expect(await ring(val), "값 칸 — 초점을 끄지 않는다").toEqual(want);
});

test("접기는 이 브라우저에 남는다 ↔ 기본은 펼침(짝) · 접으면 다 보이는 줄이 더 는다", async ({ page }) => {
  await open(page);
  expect(await page.evaluate(() => localStorage.getItem("alpha_screener_conds")), "기본: 저장값 없음 = 펼침").toBeNull();
  const openRows = await fullRows(page);
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "false");
  expect(await page.evaluate(() => localStorage.getItem("alpha_screener_conds"))).toBe("closed");
  await expect.poll(() => fullRows(page), "접으면 줄이 더 보인다").toBeGreaterThan(openRows);

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  await expect(toggle(page), "다시 열어도 접혀 있다").toHaveAttribute("aria-expanded", "false");
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
  expect(await page.evaluate(() => localStorage.getItem("alpha_screener_conds")), "펴면 저장값을 지운다").toBeNull();
  await expect(act(page, "universe")).toBeVisible();
});

test("★접고 펴도 요청이 나가지 않고 조건의 값이 그대로다★ · 요약이 조건의 글을 적는다", async ({ page }) => {
  await open(page);
  await act(page, "universe").selectOption("kosdaq150");
  await addFactor(page, "PER");
  await act(page, "cond-op").first().selectOption("lte");
  await act(page, "cond-val").first().fill("12.5");
  await expect(page.locator(".scr-cond-count").first(), "조건이 반영될 때까지 기다린다").toContainText("단독", { timeout: 20_000 });
  await act(page, "expert").locator("summary").click();
  await expect(act(page, "expert")).toHaveAttribute("open", "");
  await page.waitForTimeout(900);                                      // 지연 실행(350 · 450ms)이 다 나간 뒤부터 센다

  const sent: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/api/v1/screener/")) sent.push(`${r.method()} ${new URL(r.url()).pathname}`); });
  const name = (await page.locator(".scr-cond-name").first().innerText()).trim();     // 화면이 적는 조건의 이름(카탈로그의 글자 그대로)
  expect(name.length, "짝 — 조건의 이름이 있다").toBeGreaterThan(0);
  await toggle(page).click();
  await expect(page.locator(".scr-conds-sum")).toHaveText(`유니버스 코스닥 150 · 시가총액 전체 · 조건 1개: ${name} ≤ 12.5`);
  await page.waitForTimeout(900);
  await toggle(page).click();
  await page.waitForTimeout(900);
  expect(sent, "접고 펴는 동안 스크리너로 간 요청").toEqual([]);
  await expect(act(page, "universe")).toHaveValue("kosdaq150");
  await expect(act(page, "cond-op").first()).toHaveValue("lte");
  await expect(act(page, "cond-val").first()).toHaveValue("12.5");
  await expect(act(page, "expert"), "펼쳐 둔 전문가 설정이 그대로 펼쳐져 있다(본문을 지웠다 다시 그리지 않는다)").toHaveAttribute("open", "");

  // 짝 — 감시가 공허하지 않다: 값을 바꾸면 요청이 나간다
  await act(page, "cond-val").first().fill("13");
  await expect.poll(() => sent.length, { timeout: 10_000 }).toBeGreaterThan(0);
});

for (const theme of ["light", "dark"] as const) {
  test(`조건을 넣고 전문가 설정을 편 상태: 누르는 것 24px 이상 · 대비 AA (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    await addFactor(page, "PER");
    await act(page, "cond-val").first().focus();                         // 분포 판이 열린다
    await expect(page.locator(".bsc-hist-panel")).toBeVisible();
    await act(page, "expert").locator("summary").click();
    await act(page, "gate").check();
    await expect(act(page, "expr")).toBeVisible();
    await page.waitForTimeout(400);                                      // 스위치의 바탕 전환(120ms)이 끝난 뒤에 잰다 — 전환 중의 색은 판정이 아니다
    if (theme === "dark") expect(await act(page, "gate").evaluate((e) => getComputedStyle(e).boxShadow), "다크의 켠 스위치는 선으로 가른다").not.toBe("none");
    const small = await page.locator(".scr-conds").locator("button, select, input, summary").evaluateAll((els) => els
      .map((e) => { const r = e.getBoundingClientRect(); return { t: `${e.tagName.toLowerCase()}.${String(e.className).split(" ")[0]}:${(e.textContent ?? "").trim().slice(0, 10)}`, w: Math.round(r.width), h: Math.round(r.height) }; })
      .filter((x) => x.w > 0 && x.h > 0 && Math.min(x.w, x.h) < 24));
    expect(small, "24px 미만의 조작 요소").toEqual([]);
    const r = await page.evaluate<AuditResult>(contrastAudit(".scr-conds"));
    expect(r.checked).toBeGreaterThan(20);
    expect(r.low, JSON.stringify(r.low.slice(0, 8))).toEqual([]);
    if (theme === "dark") expect(r.bright, "다크에 밝은 판이 없다").toEqual([]);
  });
}

test("강조는 잉크다 — 고른 알약의 글자 · 켠 스위치의 바탕이 잉크이고 옛 강조색(파랑)이 아니다", async ({ page }) => {
  await open(page);
  const ink = await token(page, "--tx-ink"), blue = await token(page, "--tx-cta");
  expect(ink, "짝 — 두 값이 실제로 다르다").not.toBe(blue);
  const on = page.locator(".scr-pill--on").first();
  await expect(on).toHaveAttribute("aria-pressed", "true");
  expect(await on.evaluate((e) => getComputedStyle(e).color)).toBe(ink);
  const off = page.locator(".scr-pill:not(.scr-pill--on)").first();
  expect(await off.evaluate((e) => getComputedStyle(e).boxShadow), "짝 — 고르지 않은 알약에는 테가 없다").toBe("none");
  expect(await on.evaluate((e) => getComputedStyle(e).boxShadow), "고른 알약은 테로도 가른다(색만으로 말하지 않는다)").not.toBe("none");
  await act(page, "expert").locator("summary").click();
  const gate = act(page, "gate");
  const offBg = await gate.evaluate((e) => getComputedStyle(e).backgroundColor);
  await gate.check();
  await expect.poll(() => gate.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe(ink);
  expect(offBg, "짝 — 꺼진 스위치의 바탕은 다르다").not.toBe(ink);

  // 분포 막대: 통과한 칸은 짙은 회색 — 등락의 색(파랑 = 하락 · 빨강 = 상승)으로 그리지 않는다
  await addFactor(page, "PER");
  await act(page, "cond-val").first().fill("12.5");
  await expect(page.locator(".bsc-hist-panel")).toBeVisible();
  await expect(page.locator(".bsc-hist rect").first()).toBeAttached({ timeout: 20_000 });
  const fills = await page.locator(".bsc-hist rect").evaluateAll((els) => [...new Set(els.map((e) => getComputedStyle(e).fill))]);
  const banned = await Promise.all(["--tx-blue", "--tx-cta", "--tx-down", "--tx-up"].map((n) => token(page, n)));
  expect(fills.filter((f) => banned.includes(f)), `막대의 색: ${fills.join(" · ")}`).toEqual([]);
  expect(fills, "짝 — 통과한 칸의 색이 실제로 그려졌다").toContain(await token(page, "--tx-sub"));
  // 채운 주 단추는 화면에 하나(답 줄) — 식을 적용하는 단추는 잉크 선 + 잉크 글자다
  const apply = act(page, "expr-run");
  await expect(apply).toBeVisible();
  const look = await apply.evaluate((e) => { const s = getComputedStyle(e); return { bg: s.backgroundColor, color: s.color, shadow: s.boxShadow }; });
  expect(look.color).toBe(ink);
  expect(look.bg, "채우지 않는다").not.toBe(ink);
  expect(look.shadow, "선으로 가른다").not.toBe("none");
});

async function touchPage(browser: Browser, width: number, height: number): Promise<Page> {
  const ctx = await browser.newContext({ hasTouch: true, isMobile: true, viewport: { width, height } });
  return ctx.newPage();
}

test("좁은 손가락 화면(390): 가로로 밀리지 않는다 · 접기 단추가 다른 조작 요소를 가리지 않는다 · 입력 글자는 16px 이상", async ({ browser }) => {
  const p = await touchPage(browser, 390, 844);
  await open(p);
  expect(await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  expect(await p.locator(".terminal-main").evaluate((m) => m.scrollWidth - m.clientWidth)).toBeLessThanOrEqual(0);
  await addFactor(p, "PER");
  const hits = await toggleHits(p);
  expect(hits, "접기 단추와 겹치는 조작 요소").toEqual([]);
  const fonts = await p.locator('.scr-conds :is(select, input:not([type="checkbox"]):not([type="range"]))').evaluateAll((els) => els.filter((e) => e.getBoundingClientRect().width > 0).map((e) => parseFloat(getComputedStyle(e).fontSize)));
  expect(fonts.length, "짝 — 잰 입력이 있다").toBeGreaterThanOrEqual(3);
  expect(Math.min(...fonts), "손가락 화면의 입력 글자(작으면 화면이 확대된다)").toBeGreaterThanOrEqual(16);
  await p.context().close();
});
