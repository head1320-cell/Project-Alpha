import { test, expect, type Page } from "./fixtures";

/**
 * 건너뛰기 링크 — 접근성 P0-1 (ADR 007 결정 D4 · 계획 `docs/superpowers/plans/2026-11-20-uiux-u0-foundation.md`)
 * ─────────────────────────────────────────────────────────────────
 * 자판으로 오는 사람은 화면마다 머리 줄 · 메뉴(걸음 스물 남짓)를 다시 지나야 본문에 닿았다. 셸의 첫 요소로 '본문으로 건너뛰기'를 둔다.
 * 거는 것(짝으로 항상-통과 · 항상-침묵을 배제):
 *  · 첫 Tab 에 초점이 이 링크로 가고 ★그때만★ 보인다(짝: 초점이 없으면 화면 밖 — 그래도 접근성 트리에는 있다)
 *  · Enter → 초점이 본문(`main`)으로 · 주소는 그대로 · 다음 Tab 은 본문 안(짝: 링크를 쓰지 않으면 다음 Tab 은 셸 안)
 *  · 전환 없음(초점이 간 그 프레임에 제자리) · 누르는 크기 24px 이상 · 라이트/다크 글자 대비 AA · 390px 에서 화면 안
 *  · ★셸이 없는 화면(`/` · `/login` · `/c`)에는 없다★(짝: 셸이 있는 화면에는 하나)
 *  · ★본문은 건너뛸 때만 초점을 받는다★(P0-1b) — 평소에는 `tabindex` 가 없어 본문의 빈 곳을 눌러도 초점은 `body` 다.
 *    `tabindex` 를 늘 달아 두면 본문이 클릭 초점을 가로챈다: 초점이 `body` 일 때만 듣는 단축키(캔버스의 Ctrl+A)가 죽는다 — 첫 구현이 그랬고 CI 의 `canvas-select` 가 잡았다.
 *    건너뛴 뒤에는 초점이 떠나거나(`blur`) 본문을 누르면(`pointerdown`) 다시 뗀다.
 * 한계: 자동 검사까지다 — 실제 낭독기로 듣지는 못했다.
 */

const SKIP = ".tx-skip";
const NAME = "본문으로 건너뛰기";

async function open(page: Page, route = "/screener") {
  await page.goto(route, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".terminal-main")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(SKIP)).toHaveCount(1);
  // React 가 붙은 뒤에 누른다 — 붙기 전의 Enter 는 `href="#main"` 으로 가서 주소에 해시가 붙는다(스크립트 없는 길 · 아래 시험이 보는 것은 붙은 뒤의 길).
  await page.waitForFunction(() => { const el = document.querySelector(".tx-skip"); return !!el && Object.keys(el).some((k) => k.startsWith("__reactFiber")); }, undefined, { timeout: 20_000 });
}

const rect = (page: Page) => page.locator(SKIP).evaluate((el) => {
  const r = el.getBoundingClientRect();
  return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, w: r.width, h: r.height, vw: window.innerWidth, vh: window.innerHeight };
});

const active = (page: Page) => page.evaluate(() => {
  const a = document.activeElement as HTMLElement | null;
  return a ? { tag: a.tagName.toLowerCase(), cls: String(a.className), id: a.id, inMain: !!a.closest(".terminal-main"), inShell: !!a.closest(".terminal-header, .terminal-sidebar") } : null;
});

const MAIN = "main.terminal-main";
const tabindex = (page: Page) => page.locator(MAIN).getAttribute("tabindex");

/** 본문 안에서 조작 요소가 아닌 한 점 — 그 점의 요소부터 본문까지 올라가는 길에 초점을 받을 것이 하나도 없다(본문 자신은 따지지 않는다). */
const blankPoint = (page: Page) => page.evaluate(() => {
  const main = document.querySelector(".terminal-main")!;
  const r = main.getBoundingClientRect();
  const hot = "a[href], button, input, select, textarea, label, summary, [tabindex], [contenteditable], [role='button'], [draggable='true']";
  for (let y = Math.max(r.top, 0) + 12; y < Math.min(r.bottom, window.innerHeight) - 4; y += 16) {
    for (let x = r.left + 12; x < r.right - 4; x += 24) {
      const el = document.elementFromPoint(x, y);
      if (!el || el === main || !main.contains(el)) continue;
      let ok = true;
      for (let n: Element | null = el; n && n !== main; n = n.parentElement) if (n.matches(hot)) { ok = false; break; }
      if (ok) return { x, y };
    }
  }
  return null;
});

/** WCAG 상대 휘도 대비 — 링크의 글자색 ↔ 제 바탕색(불투명해야 한다). */
const contrast = (page: Page) => page.locator(SKIP).evaluate((el) => {
  const cs = getComputedStyle(el);
  const p = (s: string) => { const m = s.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/)!; return { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] }; };
  const lum = (c: { r: number; g: number; b: number }) => { const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const fg = p(cs.color), bg = p(cs.backgroundColor);
  const [hi, lo] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return { ratio: (hi + 0.05) / (lo + 0.05), bgAlpha: bg.a, bgLum: lum(bg), fg: cs.color, bg: cs.backgroundColor };
});

test("첫 Tab 에 초점이 건너뛰기 링크로 가고 그때만 보인다(짝: 초점이 없으면 화면 밖 · 접근성 트리에는 있다)", async ({ page }) => {
  await open(page);
  const before = await rect(page);
  expect(before.bottom, "초점 전에는 화면 위로 나가 있다").toBeLessThanOrEqual(0);
  await expect(page.getByRole("link", { name: NAME }), "보이지 않아도 이름으로 닿는다(display:none 이 아니다)").toHaveCount(1);

  await page.keyboard.press("Tab");
  expect((await active(page))?.cls, "첫 Tab 의 초점").toContain("tx-skip");
  const on = await rect(page);            // ★기다리지 않고 바로 잰다★ — 전환이 있으면 아직 화면 밖이다
  expect(on.top, "초점이 가면 화면 안").toBeGreaterThanOrEqual(0);
  expect(on.bottom).toBeLessThanOrEqual(on.vh);
  expect(on.left).toBeGreaterThanOrEqual(0);
  expect(on.right).toBeLessThanOrEqual(on.vw);
  expect(Math.min(on.w, on.h), "누르는 크기 24px 이상").toBeGreaterThanOrEqual(24);
  expect(await page.locator(SKIP).evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return top === el || el.contains(top);
  }), "머리 줄 등 다른 것에 가리지 않는다").toBe(true);

  await page.keyboard.press("Tab");       // 초점이 떠나면 다시 숨는다
  expect((await active(page))?.cls ?? "").not.toContain("tx-skip");
  expect((await rect(page)).bottom).toBeLessThanOrEqual(0);
});

test("Enter → 초점이 본문으로 · 주소는 그대로 · 다음 Tab 은 본문 안(짝: 링크를 쓰지 않으면 다음 Tab 은 셸 안)", async ({ page }) => {
  await open(page);
  const url = page.url();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  const a = await active(page);
  expect(a?.tag, "초점이 본문으로").toBe("main");
  expect(a?.cls).toContain("terminal-main");
  expect(page.url(), "주소에 해시를 달지 않는다").toBe(url);
  await page.keyboard.press("Tab");
  const next = await active(page);
  expect(next?.inMain, "다음 Tab 은 본문 안의 첫 조작 요소").toBe(true);
  expect(next?.tag, "본문 자신에 머물지 않는다").not.toBe("main");

  // 짝 — 건너뛰지 않으면 두 번째 Tab 은 셸(머리 줄)이다. 위의 '본문 안'이 늘 참이 아니라는 것.
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".terminal-main")).toBeVisible({ timeout: 20_000 });
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  const b = await active(page);
  expect(b?.inShell, "건너뛰지 않은 두 번째 Tab 은 셸 안").toBe(true);
  expect(b?.inMain).toBe(false);
});

// ── P0-1b: 본문은 건너뛸 때만 초점을 받는다 ───────────────────────────────────────────

test("평소에는 본문이 초점을 가로채지 않는다 — 본문의 빈 곳을 눌러도 초점은 body 다(짝: 건너뛰면 본문이 초점을 받는다)", async ({ page }) => {
  await open(page);
  expect.soft(await tabindex(page), "평소에는 본문에 tabindex 가 없다").toBeNull();
  const p = await blankPoint(page);
  expect(p, "본문에 조작 요소가 아닌 점이 있다").not.toBeNull();
  await page.mouse.click(p!.x, p!.y);
  expect((await active(page))?.tag, "빈 곳을 누른 뒤의 초점").toBe("body");

  // 짝 — 같은 화면에서 건너뛰면 초점은 본문이다(위의 body 가 '본문은 초점을 못 받는다'여서가 아니다).
  await page.locator(SKIP).focus();
  await page.keyboard.press("Enter");
  expect((await active(page))?.tag, "건너뛰면 본문").toBe("main");
  expect(await tabindex(page), "건너뛴 동안에만 달린다").toBe("-1");
});

test("건너뛴 뒤 초점이 본문을 떠나면 tabindex 를 뗀다 — 그 뒤로는 빈 곳을 눌러도 초점이 body 다", async ({ page }) => {
  await open(page);
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  expect((await active(page))?.tag).toBe("main");
  await page.keyboard.press("Tab");                       // 본문 안의 첫 조작 요소로 — 본문은 초점을 잃는다
  expect((await active(page))?.tag).not.toBe("main");
  expect(await tabindex(page), "초점이 떠나면 뗀다").toBeNull();
  const p = await blankPoint(page);
  expect(p).not.toBeNull();
  await page.mouse.click(p!.x, p!.y);
  expect((await active(page))?.tag, "그 뒤 빈 곳을 누른 초점").toBe("body");
});

test("건너뛴 직후 본문의 빈 곳을 누르면 초점이 본문에 남지 않는다(blur 가 오지 않는 길)", async ({ page }) => {
  await open(page);
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  expect((await active(page))?.tag).toBe("main");
  const p = await blankPoint(page);
  expect(p).not.toBeNull();
  await page.mouse.click(p!.x, p!.y);
  expect((await active(page))?.tag, "건너뛴 직후 빈 곳을 누른 초점").toBe("body");
  expect(await tabindex(page), "누르면 뗀다").toBeNull();
});

test("전환 · 움직임이 없다 — 초점이 간 그 프레임에 제자리다", async ({ page }) => {
  await open(page);
  const t = await page.locator(SKIP).evaluate((el) => { const cs = getComputedStyle(el); return { dur: cs.transitionDuration, anim: cs.animationName }; });
  expect(t.dur.split(",").map((s) => s.trim()).every((s) => s === "0s"), `transition-duration ${t.dur}`).toBe(true);
  expect(t.anim).toBe("none");
});

for (const theme of ["light", "dark"] as const) {
  test(`${theme}: 글자 대비 AA(4.5:1) · 바탕이 불투명하다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(theme === "dark");
    await page.keyboard.press("Tab");
    const c = await contrast(page);
    expect(c.bgAlpha, `바탕 ${c.bg}`).toBe(1);
    expect(c.ratio, `${c.fg} on ${c.bg}`).toBeGreaterThanOrEqual(4.5);
    // 어느 테마에서도 ★밝은 판이 아니다★ — 잉크 채움은 다크에서 밝아지므로 다크는 채우지 않고 잉크 글자 + 잉크 선으로 그린다
    // (다크 검사 `dark-modules.spec` 의 '밝은 판'과 같은 문턱 0.6). 짝: 라이트는 잉크로 채운다(선이 없다).
    expect(c.bgLum, `바탕의 밝기 ${c.bg}`).toBeLessThan(0.6);
    const edge = await page.locator(SKIP).evaluate((el) => getComputedStyle(el).boxShadow);
    if (theme === "dark") expect(edge, "다크는 잉크 선으로 가장자리를 그린다").not.toBe("none");
    else expect(edge, "라이트는 채움 — 선이 없다").toBe("none");
    // 고리는 잉크 2px(결정 D2) — 셸의 옛 초점 색(파랑)에 덮이지 않는다.
    const ink = await page.evaluate(() => { const s = document.createElement("span"); s.style.color = "var(--tx-focus)"; document.body.appendChild(s); const v = getComputedStyle(s).color; s.remove(); return v; });
    const ring = await page.locator(SKIP).evaluate((el) => { const cs = getComputedStyle(el); return { color: cs.outlineColor, width: cs.outlineWidth, style: cs.outlineStyle }; });
    expect(ring).toEqual({ color: ink, width: "2px", style: "solid" });
    // 마우스를 올려도 글자색 · 밑줄이 전역 링크 규칙에 덮이지 않는다(대비가 그대로다).
    await page.locator(SKIP).hover();
    const h = await contrast(page);
    expect(h.fg, "올렸을 때의 글자색").toBe(c.fg);
    expect(await page.locator(SKIP).evaluate((el) => getComputedStyle(el).textDecorationLine)).toBe("none");
  });
}

test("390px: 초점이 가면 화면 안에 다 들어오고 쪽이 가로로 밀리지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await page.keyboard.press("Tab");
  expect((await active(page))?.cls).toContain("tx-skip");
  const r = await rect(page);
  expect(r.left).toBeGreaterThanOrEqual(0);
  expect(r.right).toBeLessThanOrEqual(390);
  expect(r.top).toBeGreaterThanOrEqual(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), "가로 넘침").toBeLessThanOrEqual(0);
});

test("★셸이 없는 화면에는 없다★ — 첫 화면 · 로그인 · 고객 화면(짝: 셸이 있는 화면에는 하나)", async ({ page }) => {
  for (const route of ["/", "/login", "/c"]) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("load");
    await expect(page.locator(".terminal-root"), `${route} 에는 셸이 없다`).toHaveCount(0);
    await expect(page.locator(SKIP), `${route}`).toHaveCount(0);
  }
  await open(page, "/backtest");          // 짝 — 다른 셸 화면에도 하나
  await expect(page.getByRole("link", { name: NAME })).toHaveCount(1);
});
