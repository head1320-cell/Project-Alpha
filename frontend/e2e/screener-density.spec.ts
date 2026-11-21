import { test, expect, type Browser, type Page, type Route } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * 종목 찾기 — 작업 단 · 밀도 · 공용 표 (U1-b · ADR 007 · 계획 `docs/superpowers/plans/2026-11-21-uiux-u1-table-screener.md`)
 * ─────────────────────────────────────────────────────────────────
 * 종목 찾기는 작업 단에 오른 첫 제품 화면이다. 표의 동작(정렬 · 쪽 · 값)은 `screener-table.spec.ts` 가, 요청은 `screener-requests.spec.ts` 가 건다.
 * 여기는 ★밀도가 바뀌어도 지켜져야 하는 것★과 표의 접근성 계약이다(짝으로 항상-통과를 배제):
 *  · `html` 의 속성: 작업 단 · 촘촘(첫 그림 전부터) · 저장값을 따른다 · 손가락 화면은 넉넉 · 다른 화면으로 가면 떨어진다
 *  · 밀도 셋 × 두 테마: ★합성 표시가 보인다★ · 줄 높이 = 토큰 · 누르는 것 24px 이상 · 대비 AA
 *  · 스크롤 없이 다 보이는 줄이 늘었다(옮기기 전 1440 × 900 에서 2줄)
 *  · 표 이름 · ★모든★ 정렬 머리의 `aria-sort` · 단위는 머리에 · 값 없는 칸은 N/A + 표 아래 사유(표의 설명) ↔ 값이 다 있으면 사유 줄이 없다
 *  · 줄 하나만 탭 순서 · 화살표로 줄 이동 · Enter 로 상세 · 막대는 종합점수 열에만
 *  · 좁은 화면: 쪽이 가로로 밀리지 않고 표는 제 상자 안에서 끝 칸까지 민다 · 넓으면 종목 열이 붙는다(좁으면 붙지 않는다)
 */

type Item = Record<string, unknown> & { stock_code: string; corp_name: string; current_price: number | null };
type Result = { items: Item[] };
const STREAM = "**/api/v1/screener/run-advanced-stream";
const rows = (p: Page) => p.locator(".bsc-table tbody tr.bsc-row");
const attrs = (p: Page) => p.evaluate(() => [document.documentElement.getAttribute("data-tier"), document.documentElement.getAttribute("data-density")]);

async function patchStream(page: Page, edit: (r: Result) => void) {
  await page.route(STREAM, async (route: Route) => {
    const res = await route.fetch();
    const out = (await res.text()).split("\n\n").map((part) => {
      const line = part.split("\n").find((l) => l.startsWith("data:"));
      if (!line) return part;
      const obj = JSON.parse(line.slice(5).trim());
      if (obj.type !== "result") return part;
      edit(obj.data as Result);
      return part.replace(line, `data: ${JSON.stringify(obj)}`);
    }).join("\n\n");
    await route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: out });
  });
}
async function open(page: Page) {
  await page.goto("/screener", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".scr-answer .tx-answer-s")).toBeVisible({ timeout: 30_000 });
  await expect(rows(page).first()).toBeVisible();
}
const store = (page: Page, kv: Record<string, string>) => page.addInitScript((o) => { for (const [k, v] of Object.entries(o)) localStorage.setItem(k, v); }, kv);
async function touchPage(browser: Browser, width: number, height: number): Promise<Page> {
  const ctx = await browser.newContext({ hasTouch: true, isMobile: true, viewport: { width, height },
    storageState: { cookies: [], origins: [{ origin: "http://localhost:3000", localStorage: [{ name: "alpha_density", value: "compact" }] }] } });
  return ctx.newPage();
}

test("html 의 속성: 작업 단 · 촘촘(첫 그림 전부터) · 다른 화면으로 가면 떨어지고 돌아오면 다시 붙는다", async ({ page }) => {
  await page.goto("/screener", { waitUntil: "domcontentloaded" });
  expect(await attrs(page), "수화 전에도 붙어 있다(첫 그림 전의 조각)").toEqual(["work", "compact"]);
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  expect(await attrs(page)).toEqual(["work", "compact"]);
  const fade = () => page.locator(".tpage-fade").first().evaluate((e) => getComputedStyle(e).animationName);
  expect(await fade(), "작업 단에는 등장 모션이 없다(ADR 007 §6)").toBe("none");

  await page.locator(".terminal-nav a.nav-item", { hasText: "홈" }).first().click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect.poll(() => attrs(page), "작업 단이 아닌 화면에서는 속성이 없다").toEqual([null, null]);
  await page.locator(".terminal-nav a.nav-item", { hasText: "종목 찾기" }).first().click();
  await expect(page).toHaveURL(/\/screener/);
  await expect.poll(() => attrs(page)).toEqual(["work", "compact"]);

  // 짝 — 같은 겉싸개(`.tpage-fade`)를 쓰는, 단에 오르지 않은 화면의 등장 모션은 그대로다(이 화면에서만 껐다).
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".tpage-fade").first()).toBeAttached({ timeout: 20_000 });
  expect(await fade()).not.toBe("none");
});

test("저장값을 따른다(보통) ↔ 손가락 화면은 저장값이 촘촘이어도 넉넉(짝)", async ({ page, browser }) => {
  await store(page, { alpha_density: "regular" });
  await open(page);
  expect(await attrs(page)).toEqual(["work", "regular"]);
  expect(Math.round(await rows(page).first().evaluate((tr) => tr.getBoundingClientRect().height))).toBe(34);

  const touch = await touchPage(browser, 820, 1180);
  await open(touch);
  expect(await touch.evaluate(() => matchMedia("(pointer: coarse)").matches), "이 맥락이 손가락 화면이어야 시험이 뜻이 있다").toBe(true);
  expect(await attrs(touch)).toEqual(["work", "comfortable"]);
  expect(Math.round(await rows(touch).first().evaluate((tr) => tr.getBoundingClientRect().height))).toBe(44);
  await touch.context().close();
});

const ROW_H = { compact: 28, regular: 34, comfortable: 44 } as const;
for (const density of ["compact", "regular", "comfortable"] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`밀도 ${density} · ${theme}: ★합성 표시가 보인다★ · 줄 ${ROW_H[density]}px · 누르는 것 24px 이상 · 대비 AA`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await store(page, { alpha_density: density, alpha_theme: theme });
      await open(page);
      expect(await attrs(page)).toEqual(["work", density]);
      if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);

      const chip = page.locator('.scr-answer .tx-chip[data-tone="practice"]');
      await expect(chip, "합성 표시는 어떤 밀도에서도 숨기지 않는다").toHaveText("합성 시세");
      await expect(chip).toBeInViewport({ ratio: 1 });
      expect(await chip.evaluate((e) => { const c = getComputedStyle(e); return parseFloat(c.fontSize) >= 11 && c.visibility === "visible" && parseFloat(c.opacity) === 1; }), "글자가 읽히는 크기다").toBe(true);

      expect(Math.round(await rows(page).first().evaluate((tr) => tr.getBoundingClientRect().height)), "줄 높이 = 밀도 토큰").toBe(ROW_H[density]);

      const small = await page.locator(".scr").locator("button, select, input, summary, a").evaluateAll((els) => els
        .map((e) => { const r = e.getBoundingClientRect(); return { t: `${e.tagName.toLowerCase()}.${String(e.className).split(" ")[0]}:${(e.textContent ?? "").trim().slice(0, 12)}`, w: Math.round(r.width), h: Math.round(r.height) }; })
        .filter((x) => x.w > 0 && x.h > 0 && Math.min(x.w, x.h) < 24));
      expect(small, "24px 미만의 조작 요소").toEqual([]);

      const r = await page.evaluate<AuditResult>(contrastAudit(".terminal-main"));
      expect(r.checked).toBeGreaterThan(30);
      expect(r.low, JSON.stringify(r.low.slice(0, 8))).toEqual([]);
    });
  }
}

const fullRows = (page: Page) => page.evaluate(() => {
  const wrap = document.querySelector(".bsc-table-wrap")!.getBoundingClientRect(), head = document.querySelector(".bsc-table thead")!.getBoundingClientRect();
  const bottom = Math.min(window.innerHeight, wrap.bottom);
  return [...document.querySelectorAll(".bsc-table tbody tr.bsc-row")].filter((tr) => { const r = tr.getBoundingClientRect(); return r.top >= head.bottom - 0.5 && r.bottom <= bottom + 0.5; }).length;
});

test("스크롤 없이 다 보이는 줄: 1440 × 900 에서 촘촘 10줄 이상 · 보통 8줄 이상 · 넉넉 5줄 이상(옮기기 전 2줄) — 밀도가 낮을수록 줄이 준다(짝)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const got: Record<string, number> = {};
  for (const density of ["compact", "regular", "comfortable"]) {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await page.evaluate((d) => localStorage.setItem("alpha_density", d), density);
    await open(page);
    expect(await page.evaluate(() => window.scrollY + (document.querySelector(".terminal-main")?.scrollTop ?? 0)), "쪽을 굴리지 않은 채로 센다").toBe(0);
    got[density] = await fullRows(page);
    await expect(page.getByRole("navigation", { name: "결과 쪽" }), `${density}: 쪽 넘김이 굴리지 않고 보인다(표가 남은 높이를 먹는다)`).toBeInViewport({ ratio: 1 });
    expect(await page.locator(".terminal-main").evaluate((m) => m.scrollHeight - m.clientHeight), `${density}: 쪽은 구르지 않는다 — 구르는 것은 표 하나`).toBeLessThanOrEqual(0);
  }
  expect(got.compact, JSON.stringify(got)).toBeGreaterThanOrEqual(10);
  expect(got.regular, JSON.stringify(got)).toBeGreaterThanOrEqual(8);
  expect(got.comfortable, JSON.stringify(got)).toBeGreaterThanOrEqual(5);
  expect(got.compact, "촘촘이 보통보다 많다").toBeGreaterThan(got.regular);
  expect(got.regular, "보통이 넉넉보다 많다").toBeGreaterThan(got.comfortable);
});

test("표 이름 · ★모든★ 정렬 머리의 aria-sort · 단위는 머리에(칸에는 수만)", async ({ page }) => {
  await patchStream(page, (r) => { r.items.forEach((it, i) => { it.market_cap_억 = 1000 + i * 37.4; }); });
  await open(page);
  await expect(page.getByRole("table", { name: "종목 찾기 결과" })).toHaveCount(1);
  const heads = page.locator(".bsc-table thead th");
  const names = (await heads.allTextContents()).map((t) => t.replace(/[▲▼]/g, "").trim());
  expect(names).toEqual(["순위", "관심", "종목", "현재가(원)", "시가총액(억)", "종합점수", "판정"]);
  const sorts = () => heads.evaluateAll((ths) => ths.map((t) => t.getAttribute("aria-sort")));
  expect(await sorts(), "처음: 종합점수 내림차순 — 정렬할 수 있는 다른 머리는 none").toEqual([null, null, null, "none", "none", "descending", null]);
  await heads.nth(4).getByRole("button").click();
  expect(await sorts()).toEqual([null, null, null, "none", "descending", "none", null]);
  await heads.nth(4).getByRole("button").click();
  expect(await sorts()).toEqual([null, null, null, "none", "ascending", "none", null]);
  expect(await heads.evaluateAll((ths) => ths.map((t) => t.getAttribute("scope")))).toEqual(Array(7).fill("col"));

  const first = rows(page).first();
  await expect(first.locator("td").nth(3), "현재가 칸에는 수만(단위는 머리에)").toHaveText(/^[\d,]+$/);
  await expect(first.locator("td").nth(4), "시가총액 칸에는 수만").toHaveText(/^[\d,]+$/);
});

test("값 없는 칸: N/A + 표 아래 사유 줄(표의 설명으로 이어짐) ↔ 값이 다 있으면 사유 줄이 없다(짝)", async ({ page }) => {
  await open(page);
  await expect(page.locator(".scr-results .tx-table-note"), "값이 다 있는 쪽에는 사유 줄이 없다").toHaveCount(0);
  expect(await page.locator(".bsc-table").getAttribute("aria-describedby"), "가리킬 설명이 없으면 속성도 없다").toBeNull();

  await patchStream(page, (r) => { r.items[2].current_price = null; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  await expect(rows(page).nth(2).locator("td").nth(3)).toHaveText("N/A");
  const note = page.locator(".scr-results .tx-table-note");
  await expect(note).toBeVisible();
  await expect(note).toContainText("응답에 값이 없는 칸");
  await expect(note).toContainText("0 이 아닙니다");
  expect(await page.locator(".bsc-table").getAttribute("aria-describedby")).toBe(await note.getAttribute("id"));
});

test("줄 하나만 탭 순서 · ↓ 로 줄 이동 · Enter 로 상세 · 칸 안의 별은 줄을 고르지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });               // 좁은 창 — 상세는 시트로 뜬다
  await open(page);
  const tabbable = () => rows(page).evaluateAll((trs) => trs.filter((tr) => tr.getAttribute("tabindex") === "0").length);
  expect(await tabbable(), "표의 줄 100개 가운데 탭 정지는 하나").toBe(1);
  expect(await rows(page).count()).toBe(100);

  const code = (i: number) => rows(page).nth(i).getAttribute("data-code");
  await rows(page).first().focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  expect(await page.evaluate(() => document.activeElement?.getAttribute("data-code"))).toBe(await code(2));
  expect(await tabbable()).toBe(1);
  await page.keyboard.press("End");
  expect(await page.evaluate(() => document.activeElement?.getAttribute("data-code"))).toBe(await code(99));
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowDown");

  const ring = (sel: string) => page.locator(sel).first().evaluate((e) => { const c = getComputedStyle(e); const probe = document.createElement("span"); probe.style.color = "var(--tx-focus)"; e.appendChild(probe);
    const ink = getComputedStyle(probe).color; probe.remove(); return { style: c.outlineStyle, ink: c.outlineColor === ink }; });
  expect(await ring(".bsc-table tbody tr.bsc-row:focus-visible"), "줄의 초점 고리는 잉크").toEqual({ style: "solid", ink: true });
  await page.getByRole("button", { name: "CSV 내려받기" }).focus();
  await page.keyboard.press("Shift+Tab"); await page.keyboard.press("Tab");
  expect(await ring(".scr .scr-tool:focus-visible"), "이 화면 단추의 초점 고리도 잉크(셸의 옛 강조색이 아니다)").toEqual({ style: "solid", ink: true });

  await rows(page).nth(1).locator(".bsc-fav").click();
  await expect(page.locator("dialog[open]"), "별은 줄을 고르지 않는다").toHaveCount(0);
  await rows(page).nth(1).focus();
  await page.keyboard.press("Enter");
  const sheet = page.locator("dialog.tx-sheet[open]");
  await expect(sheet).toBeVisible();
  await expect(sheet.locator(".tx-sheet-sub")).toContainText((await code(1))!);
});

test("막대는 종합점수 열에만 — 표시 열(값 열)에는 없다", async ({ page }) => {
  const fieldsRes = page.waitForResponse((r) => r.url().includes("/api/v1/screener/fields") && r.status() === 200);
  let items: Item[] = [];
  await patchStream(page, (r) => { items = r.items; });
  await open(page);
  const fields = ((await (await fieldsRes).json()) as { categories: { fields: { id: string; label: string }[] }[] }).categories.flatMap((c) => c.fields);
  const pick = fields.find((f) => !["current_price", "market_cap_억", "composite_score"].includes(f.id) && items.some((it) => typeof it[f.id] === "number" && Number.isFinite(it[f.id] as number)))!;
  await page.evaluate((id) => localStorage.setItem("alpha_screener_cols", JSON.stringify([id])), pick.id);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  const names = (await page.locator(".bsc-table thead th").allTextContents()).map((t) => t.replace(/[▲▼]/g, "").trim());
  const nPick = names.findIndex((n) => n.startsWith(pick.label)), nScore = names.indexOf("종합점수");
  expect(nPick, `표시 열 ${pick.label} 이 머리에 있다: ${names.join(" | ")}`).toBeGreaterThan(0);
  expect(await rows(page).evaluateAll((trs, n) => trs.filter((tr) => tr.children[n].querySelector(".tx-bar-fill")).length, nScore), "종합점수 칸마다 막대").toBe(100);
  expect(await rows(page).evaluateAll((trs, n) => trs.filter((tr) => tr.children[n].querySelector(".tx-bar-fill, .bsc-cell-fill")).length, nPick), "값 열에는 막대가 없다").toBe(0);
  expect(await page.locator(".bsc-table .tx-bar-fill").count(), "막대의 수 = 줄의 수(한 열)").toBe(100);
});

test("같은 열은 같은 소수 자리 — 값의 크기가 섞여 있어도 열 안에서 자릿수가 갈리지 않는다", async ({ page }) => {
  const fieldsRes = page.waitForResponse((r) => r.url().includes("/api/v1/screener/fields") && r.status() === 200);
  let pickId = "";
  // 한 열에 작은 값(12.345)과 큰 값(345.678)을 번갈아 싣는다 — 값마다 자릿수를 정하는 구현이면 두 자리와 0자리가 섞인다.
  await patchStream(page, (r) => { if (pickId) r.items.forEach((it, i) => { it[pickId] = i % 2 ? 12.345 : 345.678; }); });
  await open(page);
  const fields = ((await (await fieldsRes).json()) as { categories: { fields: { id: string; label: string }[] }[] }).categories.flatMap((c) => c.fields);
  const pick = fields.find((f) => !["current_price", "market_cap_억", "composite_score"].includes(f.id))!;
  pickId = pick.id;
  await page.evaluate((id) => localStorage.setItem("alpha_screener_cols", JSON.stringify([id])), pick.id);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  const names = (await page.locator(".bsc-table thead th").allTextContents()).map((t) => t.replace(/[▲▼]/g, "").trim());
  const n = names.findIndex((x) => x.startsWith(pick.label));
  expect(n, `표시 열 ${pick.label}: ${names.join(" | ")}`).toBeGreaterThan(0);
  const texts = await rows(page).evaluateAll((trs, k) => trs.map((tr) => (tr.children[k].textContent ?? "").trim()), n);
  const decimals = new Set(texts.map((x) => (x.split(".")[1] ?? "").length));
  expect([...decimals], `그 열의 소수 자리 수: ${texts.slice(0, 4).join(" · ")}`).toHaveLength(1);
  expect(new Set(texts).size, "짝 — 두 값이 실제로 섞여 있다").toBe(2);
});

const WIDE_COLS = ["per", "pbr", "roe_pct", "roa_pct", "debt_ratio_pct", "dividend_yield_pct", "gap_pct", "intrinsic_value", "gap_score", "roe_score", "stability_score"];
const wrapBox = (page: Page) => page.locator(".bsc-table-wrap").evaluate((w) => { const r = w.getBoundingClientRect(); return { left: r.left, right: r.right, over: w.scrollWidth - w.clientWidth }; });

test("좁은 화면(390): 쪽이 가로로 밀리지 않는다 · 표는 제 상자 안에서 끝 칸까지 민다 · 종목 열은 붙지 않는다", async ({ browser }) => {
  const p = await touchPage(browser, 390, 844);
  await open(p);
  expect(await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), "쪽의 가로 넘침").toBeLessThanOrEqual(0);
  expect(await p.locator(".terminal-main").evaluate((m) => m.scrollWidth - m.clientWidth), "본문의 가로 넘침").toBeLessThanOrEqual(0);
  const before = await wrapBox(p);
  expect(before.over, "짝 — 표가 상자보다 넓다(밀 것이 있다)").toBeGreaterThan(0);
  await p.locator(".bsc-table-wrap").evaluate((w) => { w.scrollLeft = w.scrollWidth; });
  const last = await p.locator(".bsc-table thead th").last().evaluate((t) => t.getBoundingClientRect().right);
  expect(last, "끝 칸(판정)의 오른쪽 끝이 상자 안에 든다").toBeLessThanOrEqual(before.right + 1);
  // 붙지 않는다 = 민 만큼 그대로 따라 움직인다(넓은 화면의 짝 시험에서는 자리가 그대로다).
  await p.locator(".bsc-table-wrap").evaluate((w) => { w.scrollLeft = 0; });
  const nameCell = rows(p).first().locator("td").nth(2);
  const x0 = await nameCell.evaluate((t) => t.getBoundingClientRect().left);
  const moved = await p.locator(".bsc-table-wrap").evaluate((w) => { w.scrollLeft = Math.min(40, w.scrollWidth - w.clientWidth); return w.scrollLeft; });
  expect(moved, "짝 — 실제로 밀었다").toBeGreaterThan(0);
  const x1 = await nameCell.evaluate((t) => t.getBoundingClientRect().left);
  expect(Math.round(x0 - x1), "좁은 화면에서는 종목 열이 함께 밀린다(붙지 않는다)").toBe(Math.round(moved));
  await p.context().close();
});

test("넓은 화면: 열이 많아 가로로 밀어도 종목 열이 붙어 남는다(순위 · 관심 · 종목)", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 800 });
  await store(page, { alpha_screener_cols: JSON.stringify(WIDE_COLS), alpha_density: "comfortable" });
  await patchStream(page, (r) => { r.items.forEach((it, i) => { for (const c of WIDE_COLS) if (typeof it[c] !== "number") it[c] = 10 + i; }); });
  await open(page);
  const box = await wrapBox(page);
  expect(box.over, "짝 — 표가 상자보다 넓다").toBeGreaterThan(100);
  const nameCell = rows(page).first().locator("td").nth(2);
  const x0 = await nameCell.evaluate((t) => t.getBoundingClientRect().left);
  await page.locator(".bsc-table-wrap").evaluate((w) => { w.scrollLeft = 300; });
  const x1 = await nameCell.evaluate((t) => t.getBoundingClientRect().left);
  expect(Math.abs(x1 - x0), "밀어도 종목 칸의 자리가 그대로다").toBeLessThanOrEqual(1);
  const price = await rows(page).first().locator("td").nth(3).evaluate((t) => t.getBoundingClientRect().left);
  expect(price, "짝 — 붙지 않는 칸(현재가)은 밀려 종목 칸 밑으로 들어간다").toBeLessThan(await nameCell.evaluate((t) => t.getBoundingClientRect().right));
  await expect(nameCell.locator(".bsc-name")).toBeVisible();
});
