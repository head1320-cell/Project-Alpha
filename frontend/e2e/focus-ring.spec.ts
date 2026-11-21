import { test, expect, type Page } from "./fixtures";

/**
 * 늦는 초점 고리 — 접근성 P0-2 (ADR 007 §6 "초점 고리는 전환 없이 즉시" · 결정 D4)
 * ─────────────────────────────────────────────────────────────────
 * `transition: all` 은 색 · 바탕만이 아니라 ★초점 고리(outline)까지★ 전환에 태운다 — 자판 초점이 간 뒤 고리가 0.1초에 걸쳐 자란다.
 * 여섯 규칙을 실제로 바뀌는 속성만으로 고친다(글자로는 `tests/test_frontend_style_ratchet.py` 의 래칫이 0 으로 건다).
 * 이 스펙은 ★동작★을 건다 — 초점이 갈 때 outline 계열 속성에 전환이 한 번도 돌지 않는다.
 *  · 재는 법: 문서에 `transitionrun` 기록기를 달고 자판으로 초점을 옮긴다. 시간을 재지 않으므로(기계가 느려도) 같은 답이다.
 *  · 짝 ①: 고리는 실제로 그려진다(없는 고리는 늦지도 않는다) · 짝 ②: 기록기는 살아 있다 — 마우스를 올리면 색 · 바탕의 전환이 잡힌다.
 *  · 화면에 늘 있는 둘(`.tbt-mode` · `.mc-tab`)은 그 요소로, 상태가 있어야 뜨는 넷은 같은 클래스의 단추를 본문에 심어 그 ★규칙★을 본다.
 *  · 짝 ③(심은 넷): 고친 뒤에도 ★뜻한 전환은 남는다★ — 마우스를 올리면(실행 단추는 끄면) 그 규칙이 바꾸는 속성에 전환이 돈다.
 *    전환을 통째로 지워도 위의 단정은 통과하므로, 이 짝이 '고리만 빼고 그대로'를 건다.
 */

const OUTLINE = /^outline/;

/** 문서에 전환 기록기를 단다 — `[요소의 클래스, 속성 이름]`. */
const record = (page: Page) => page.evaluate(() => {
  const w = window as unknown as { __tr?: [string, string][] };
  w.__tr = [];
  document.addEventListener("transitionrun", (e) => { w.__tr!.push([String((e.target as HTMLElement).className), (e as TransitionEvent).propertyName]); }, true);
});
const runs = (page: Page, cls: string) => page.evaluate((c) => ((window as unknown as { __tr: [string, string][] }).__tr).filter(([k]) => k.split(/\s+/).includes(c)).map(([, p]) => p), cls);
const reset = (page: Page) => page.evaluate(() => { (window as unknown as { __tr: unknown[] }).__tr.length = 0; });

/** 본문에서 선택자에 맞는 요소에 Tab 으로 닿는다(셸은 지나친다). */
async function tabTo(page: Page, sel: string, max = 90): Promise<number> {
  for (let i = 1; i <= max; i++) {
    await page.keyboard.press("Tab");
    if (await page.evaluate((s) => { const el = document.activeElement; return !!el && el.matches(s) && !el.closest(".terminal-header, .terminal-sidebar"); }, sel)) return i;
  }
  return 0;
}

/** React 가 붙은 뒤인가 — 붙기 전에 심은 요소는 붙는 과정에서 지워질 수 있다(서버가 보낸 HTML 만으로도 화면은 보인다). */
const hydrated = (page: Page, sel: string) => page.waitForFunction((s) => {
  const el = document.querySelector(s);
  return !!el && Object.keys(el).some((k) => k.startsWith("__reactFiber"));
}, sel, { timeout: 20_000 });

const ring = (page: Page) => page.evaluate(() => {
  const cs = getComputedStyle(document.activeElement as HTMLElement);
  return { style: cs.outlineStyle, width: parseFloat(cs.outlineWidth), prop: cs.transitionProperty };
});

for (const [route, sel, cls, ready] of [
  ["/backtest", ".bte .tbt-mode", "tbt-mode", ".bte"],
  ["/macro", ".mc .mc-tabs .mc-tab", "mc-tab", ".mc .mc-tabs .mc-tab"],
] as const) {
  test(`${route} ${sel}: 자판 초점이 가도 outline 에 전환이 돌지 않는다(짝: 고리는 그려진다 · 마우스를 올리면 전환이 잡힌다)`, async ({ page }) => {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page.locator(ready).first()).toBeVisible({ timeout: 20_000 });
    await hydrated(page, ready);
    await record(page);
    expect(await tabTo(page, sel), `${sel} 에 Tab 으로 닿는다`).toBeGreaterThan(0);
    await page.waitForTimeout(250);                                   // 전환이 있었다면 그 사이에 시작 사건이 온다
    const r = await ring(page);
    expect(r.style, "짝 ① — 고리가 그려진다").not.toBe("none");
    expect(r.width).toBeGreaterThanOrEqual(2);
    expect((await runs(page, cls)).filter((p) => OUTLINE.test(p)), "초점 때 outline 에 돈 전환").toEqual([]);
    expect(r.prop.split(",").map((s) => s.trim()), "모든 속성에 거는 전환이 아니다").not.toContain("all");

    // 짝 ② — 기록기가 죽어 있지 않다: 초점을 치우고 마우스를 올리면 색 · 바탕의 전환이 잡힌다(그래서 위의 [] 가 '못 본 것'이 아니다).
    await page.evaluate(() => (document.activeElement as HTMLElement).blur());
    await reset(page);
    await page.locator(sel).filter({ hasNot: page.locator(":scope.active, :scope.on, :scope[aria-expanded='true']") }).last().hover();
    await expect.poll(async () => (await runs(page, cls)).length, { message: "마우스를 올리면 전환이 시작된다" }).toBeGreaterThan(0);
    expect((await runs(page, cls)).filter((p) => OUTLINE.test(p))).toEqual([]);
  });
}

// 상태가 있어야 뜨는 넷 — 같은 클래스의 단추를 본문에 심어 그 규칙을 본다(저장한 전략 · 넘겨받은 종목 · 실행 실패 · 지표 카드).
// 넷째 · 다섯째 칸: 그 규칙의 상태를 바꾸는 법과, 그때 전환이 돌아야 하는 속성(고치기 전에 잰 값 — 2026-11-20).
for (const [route, cls, ready, how, prop] of [
  ["/backtest", "tbt-saved-del", ".bte", "hover", "color"],
  ["/backtest", "tscreener-handoff-clear", ".bte", "hover", "color"],
  ["/backtest", "brun-btn", ".bte", "disable", "opacity"],
  ["/macro", "mc-ind", ".mc", "hover", "background-color"],
] as const) {
  test(`.${cls} 의 규칙: 초점이 가도 outline 에 전환이 돌지 않는다 · 모든 속성에 거는 전환이 아니다(짝: 고리는 그려진다 · ${prop} 전환은 남는다)`, async ({ page }) => {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page.locator(ready).first()).toBeVisible({ timeout: 20_000 });
    await hydrated(page, ready);
    await page.evaluate((c) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = c; b.textContent = "심은 단추"; b.id = "__probe";
      document.querySelector(".terminal-main")!.prepend(b);
    }, cls);
    await expect(page.locator("#__probe"), "심은 단추가 남아 있다").toHaveCount(1);
    await record(page);
    expect(await tabTo(page, "#__probe"), "심은 단추에 Tab 으로 닿는다").toBeGreaterThan(0);
    await page.waitForTimeout(250);
    const r = await ring(page);
    expect(r.style, "짝 — 고리가 그려진다").not.toBe("none");
    expect(r.width).toBeGreaterThanOrEqual(2);
    expect((await runs(page, cls)).filter((p) => OUTLINE.test(p)), "초점 때 outline 에 돈 전환").toEqual([]);
    expect(r.prop.split(",").map((s) => s.trim()), "모든 속성에 거는 전환이 아니다").not.toContain("all");

    // 짝 ③ — 뜻한 전환은 남는다(전환을 통째로 지운 구현을 배제한다).
    await page.evaluate(() => (document.activeElement as HTMLElement).blur());
    await page.mouse.move(2, 700);
    await page.waitForTimeout(250);
    await reset(page);
    if (how === "hover") await page.locator("#__probe").hover();
    else await page.evaluate(() => { (document.getElementById("__probe") as HTMLButtonElement).disabled = true; });
    await expect.poll(async () => await runs(page, cls), { message: `${how} 때 ${prop} 에 전환이 돈다` }).toContain(prop);
    expect((await runs(page, cls)).filter((p) => OUTLINE.test(p)), "그때도 outline 에는 돌지 않는다").toEqual([]);
  });
}
