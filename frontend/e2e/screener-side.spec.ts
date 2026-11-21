import { test, expect, type Page, type Route } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * 종목 찾기 — 줄 상세의 옆 판 (U1-c · 계획 `docs/superpowers/plans/2026-11-21-uiux-u1-table-screener.md`)
 * ─────────────────────────────────────────────────────────────────
 * 옮기기 전에는 줄을 고르면 모달 시트가 떠 뒤의 표가 막혔다 — 줄을 넘기며 견줄 수 없었다(설계 §2.3).
 * 가로 1280px 이상에서는 상세가 ★표 옆 판★(비모달)에 뜬다. 그보다 좁으면 예전의 시트다(`screener.spec.ts` 가 건다).
 * 거는 것(짝으로 항상-통과를 배제):
 *  · 줄을 고르면 옆 판 — 대화상자가 아니다 · 그 줄의 서버 값 · ★표가 살아 있다★(다른 줄 · 정렬 · 관심 별)
 *  · 판이 열려 있으면 ↑ ↓ 로 고른 줄이 따라 바뀐다 ↔ 닫혀 있으면 초점만 옮긴다
 *  · Esc · 닫기 단추로 닫히고 초점이 고른 줄로 돌아온다
 *  · 구분선: 이름 · 값 · ← → Home End 로 폭이 바뀌고(320 ~ 560) 이 브라우저에 남는다
 *  · 문턱: 1280 에서는 판 · 1279 에서는 시트 · 창을 좁히면 시트로, 넓히면 다시 판(고른 줄은 그대로)
 *  · 값이 없으면 N/A + 사유 · 합성 표시가 판에도 있다
 *  · 판이 열려도 쪽은 구르지 않고 표와 판이 겹치지 않는다 · 대비 AA · 누르는 것 24px 이상(라이트 · 다크)
 */

type Item = Record<string, unknown> & { stock_code: string; corp_name: string; current_price: number | null; composite_score: number; sector?: string | null };
type Result = { items: Item[] };
const STREAM = "**/api/v1/screener/run-advanced-stream";
const rows = (p: Page) => p.locator(".bsc-table tbody tr.bsc-row");
const side = (p: Page) => p.locator("aside.scr-side");
const fig = (p: Page, name: string) => side(p).locator(".scr-sheet-fig", { has: p.locator("dt", { hasText: name }) }).locator("dd");
const current = (p: Page) => rows(p).evaluateAll((trs) => trs.filter((tr) => tr.getAttribute("aria-current") === "true").map((tr) => tr.getAttribute("data-code")));
const focused = (p: Page) => p.evaluate(() => document.activeElement?.getAttribute("data-code") ?? null);

async function watchStream(page: Page, edit?: (r: Result) => void): Promise<{ last: () => Result }> {
  let last: Result | null = null;
  await page.route(STREAM, async (route: Route) => {
    const res = await route.fetch();
    const out = (await res.text()).split("\n\n").map((part) => {
      const line = part.split("\n").find((l) => l.startsWith("data:"));
      if (!line) return part;
      const obj = JSON.parse(line.slice(5).trim());
      if (obj.type !== "result") return part;
      edit?.(obj.data as Result);
      last = JSON.parse(JSON.stringify(obj.data)) as Result;
      return part.replace(line, `data: ${JSON.stringify(obj)}`);
    }).join("\n\n");
    await route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: out });
  });
  return { last: () => { if (!last) throw new Error("스트림 결과를 잡지 못했다"); return last; } };
}
async function open(page: Page) {
  await page.goto("/screener", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".scr-answer .tx-answer-s")).toBeVisible({ timeout: 30_000 });
  await expect(rows(page).first()).toBeVisible();
}

test.use({ viewport: { width: 1440, height: 900 } });

test("줄을 고르면 옆 판 — 대화상자가 아니다 · 그 줄의 서버 값 · ★표가 살아 있다★(다른 줄 · 정렬 · 관심 별)", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  await expect(side(page), "고르기 전에는 판이 없다").toHaveCount(0);
  const [a, b] = s.last().items;
  await rows(page).first().locator("td").nth(2).click();
  await expect(side(page)).toBeVisible();
  await expect(page.locator("dialog[open]"), "대화상자(모달)가 아니다").toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "종목 상세" })).toHaveCount(1);
  await expect(side(page).locator(".scr-side-title")).toHaveText(a.corp_name);
  await expect(side(page).locator(".scr-side-sub")).toContainText(a.stock_code);
  await expect(fig(page, "현재가")).toHaveText(`${a.current_price!.toLocaleString("ko-KR")}원`);
  await expect(fig(page, "종합점수")).toHaveText(a.composite_score.toLocaleString("ko-KR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
  await expect(side(page).getByRole("link", { name: "기업 분석 열기" })).toHaveAttribute("href", `/insights?code=${a.stock_code}`);
  await expect(side(page).getByRole("link", { name: "설계에 추가" })).toHaveAttribute("href", `/allocation?tickers=${a.stock_code}`);

  // 표가 살아 있다 — 판이 열린 채로 다른 줄을 고르고 · 정렬하고 · 별을 누른다
  await rows(page).nth(1).locator("td").nth(2).click();
  await expect(side(page).locator(".scr-side-title")).toHaveText(b.corp_name);
  await expect(fig(page, "현재가"), "판의 값도 그 줄의 것이다(머리만 바뀌는 구현을 배제)").toHaveText(`${b.current_price!.toLocaleString("ko-KR")}원`);
  await expect(side(page).getByRole("link", { name: "기업 분석 열기" })).toHaveAttribute("href", `/insights?code=${b.stock_code}`);
  expect(await current(page), "고른 줄은 하나").toEqual([b.stock_code]);
  await page.locator(".bsc-table thead").getByRole("button", { name: /^현재가/ }).click();
  await expect(page.locator(".bsc-table thead th", { hasText: "현재가" })).toHaveAttribute("aria-sort", "descending");
  await expect(side(page).locator(".scr-side-title"), "정렬해도 고른 종목은 그대로다").toHaveText(b.corp_name);
  const star = rows(page).first().locator(".bsc-fav");
  await star.click();
  await expect(star).toHaveAttribute("aria-pressed", "true");
  await expect(side(page).locator(".scr-side-title"), "별은 줄을 고르지 않는다").toHaveText(b.corp_name);
});

test("판이 열려 있으면 ↑ ↓ 로 고른 줄이 따라 바뀐다 ↔ 닫혀 있으면 초점만 옮긴다(짝)", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  const items = s.last().items;
  await rows(page).first().focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  expect(await focused(page)).toBe(items[2].stock_code);
  expect(await current(page), "판이 닫혀 있으면 초점만 옮긴다").toEqual([]);
  await expect(side(page)).toHaveCount(0);

  await page.keyboard.press("Enter");
  await expect(side(page).locator(".scr-side-title")).toHaveText(items[2].corp_name);
  expect(await focused(page), "판이 떠도 초점은 줄에 남는다(표가 살아 있다)").toBe(items[2].stock_code);
  await page.keyboard.press("ArrowDown");
  await expect(side(page).locator(".scr-side-title"), "↓ — 판이 다음 줄로").toHaveText(items[3].corp_name);
  expect(await current(page)).toEqual([items[3].stock_code]);
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");
  await expect(side(page).locator(".scr-side-title"), "↑ ↑").toHaveText(items[1].corp_name);
  await page.keyboard.press("Home");
  await expect(side(page).locator(".scr-side-title")).toHaveText(items[0].corp_name);
  expect(await focused(page)).toBe(items[0].stock_code);
});

test("Esc · 닫기 단추로 닫히고 초점이 고른 줄로 돌아온다", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  const items = s.last().items;
  await rows(page).nth(4).locator("td").nth(2).click();
  await expect(side(page)).toBeVisible();
  await side(page).getByRole("button", { name: "상세 닫기" }).click();
  await expect(side(page)).toHaveCount(0);
  expect(await current(page)).toEqual([]);
  await expect.poll(() => focused(page), "닫기 단추 — 초점이 그 줄로").toBe(items[4].stock_code);

  await page.keyboard.press("Enter");
  await expect(side(page)).toBeVisible();
  await side(page).getByRole("link", { name: "기업 분석 열기" }).focus();      // 초점이 판 안에 있어도 Esc 가 닫는다
  await page.keyboard.press("Escape");
  await expect(side(page)).toHaveCount(0);
  await expect.poll(() => focused(page), "Esc — 초점이 그 줄로").toBe(items[4].stock_code);
  await expect(page).toHaveURL(/\/screener$/);
});

test("구분선: 이름 · 값 · ← → Home End 로 폭이 바뀌고(320 ~ 560) 이 브라우저에 남는다", async ({ page }) => {
  await open(page);
  await rows(page).first().locator("td").nth(2).click();
  const bar = page.getByRole("separator", { name: "상세 판 폭" });
  await expect(bar).toHaveAttribute("aria-orientation", "vertical");
  const now = async () => [Number(await bar.getAttribute("aria-valuenow")), Math.round(await side(page).evaluate((e) => e.getBoundingClientRect().width))];
  expect([await bar.getAttribute("aria-valuemin"), await bar.getAttribute("aria-valuemax")]).toEqual(["320", "560"]);
  expect(await now(), "처음 폭 360").toEqual([360, 360]);
  await bar.focus();
  await page.keyboard.press("ArrowLeft");                                // 판은 구분선의 오른쪽 — ← 가 넓힌다
  expect(await now()).toEqual([376, 376]);
  await page.keyboard.press("ArrowRight"); await page.keyboard.press("ArrowRight");
  expect(await now()).toEqual([344, 344]);
  await page.keyboard.press("End");
  expect(await now()).toEqual([560, 560]);
  await page.keyboard.press("ArrowLeft");
  expect(await now(), "범위를 넘지 않는다").toEqual([560, 560]);
  await page.keyboard.press("Home");
  expect(await now()).toEqual([320, 320]);
  await page.keyboard.press("ArrowLeft"); await page.keyboard.press("ArrowLeft");
  expect(await now()).toEqual([352, 352]);
  expect(await page.evaluate(() => localStorage.getItem("alpha_screener_side_w"))).toBe("352");

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  await rows(page).first().locator("td").nth(2).click();
  expect(await now(), "다시 열어도 그 폭").toEqual([352, 352]);
  // 저장값이 범위 밖 · 수가 아니면 범위 안으로(지어내지 않는다 — 가장 가까운 끝 · 처음 값)
  await page.evaluate(() => localStorage.setItem("alpha_screener_side_w", "9999"));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  await rows(page).first().locator("td").nth(2).click();
  expect(await now()).toEqual([560, 560]);
});

test("문턱 1280: 그 폭에서는 판 · 1px 좁으면 시트 · 창을 좁히면 시트로, 넓히면 다시 판(고른 줄은 그대로)", async ({ page }) => {
  const s = await watchStream(page);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page);
  const first = s.last().items[0];
  await rows(page).first().locator("td").nth(2).click();
  await expect(side(page)).toBeVisible();
  await expect(page.locator("dialog.tx-sheet[open]")).toHaveCount(0);

  await page.setViewportSize({ width: 1279, height: 720 });
  await expect(page.locator("dialog.tx-sheet[open]"), "좁히면 같은 종목의 시트").toBeVisible();
  await expect(page.locator("dialog.tx-sheet[open] .tx-sheet-title")).toHaveText(first.corp_name);
  await expect(side(page)).toHaveCount(0);

  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(side(page).locator(".scr-side-title"), "넓히면 다시 판").toHaveText(first.corp_name);
  await expect(page.locator("dialog[open]")).toHaveCount(0);
});

test("값이 없으면 N/A + 사유(0 · 빈칸 · 줄표가 아니다) · 합성 표시가 판에도 있다", async ({ page }) => {
  await watchStream(page, (r) => { r.items[0].current_price = null; });
  await open(page);
  await rows(page).first().locator("td").nth(2).click();
  await expect(fig(page, "현재가").locator(".tx-unknown-v")).toHaveText("N/A");
  await expect(fig(page, "현재가").locator(".tx-unknown-why")).toHaveText("응답에 값이 없습니다");
  await expect(side(page).locator('.tx-chip[data-tone="practice"]'), "합성 표시").toHaveText("합성 시세");
  await rows(page).nth(1).locator("td").nth(2).click();
  await expect(fig(page, "현재가").locator(".tx-unknown"), "짝 — 값이 있는 줄에는 N/A 가 없다").toHaveCount(0);
});

test("판이 열려도 쪽은 구르지 않고 쪽 넘김이 보인다 · 표와 판이 겹치지 않는다 · 다 보이는 줄 수가 그대로다", async ({ page }) => {
  await open(page);
  const full = () => page.evaluate(() => {
    const wrap = document.querySelector(".bsc-table-wrap")!.getBoundingClientRect(), head = document.querySelector(".bsc-table thead")!.getBoundingClientRect();
    const bottom = Math.min(window.innerHeight, wrap.bottom);
    return [...document.querySelectorAll(".bsc-table tbody tr.bsc-row")].filter((tr) => { const r = tr.getBoundingClientRect(); return r.top >= head.bottom - 0.5 && r.bottom <= bottom + 0.5; }).length;
  });
  const closed = await full();
  await rows(page).nth(2).locator("td").nth(2).click();
  await expect(side(page)).toBeVisible();
  expect(await full(), "판이 열려도 다 보이는 줄 수는 그대로").toBe(closed);
  expect(await page.locator(".terminal-main").evaluate((m) => [m.scrollHeight - m.clientHeight, m.scrollWidth - m.clientWidth]), "쪽은 세로로도 가로로도 구르지 않는다").toEqual([0, 0]);
  await expect(page.getByRole("navigation", { name: "결과 쪽" })).toBeInViewport({ ratio: 1 });
  const box = await page.evaluate(() => { const w = document.querySelector(".bsc-table-wrap")!.getBoundingClientRect(), a = document.querySelector("aside.scr-side")!.getBoundingClientRect(); return { wrapRight: w.right, sideLeft: a.left, sideRight: a.right, vw: window.innerWidth, sideH: a.height }; });
  expect(box.wrapRight, "표 상자는 판의 왼쪽에서 끝난다").toBeLessThanOrEqual(box.sideLeft);
  expect(box.sideRight, "판이 창 안에 든다").toBeLessThanOrEqual(box.vw);
  expect(box.sideH, "판이 표만큼 높다").toBeGreaterThan(200);
});

for (const theme of ["light", "dark"] as const) {
  test(`옆 판 — 대비 AA · 누르는 것 24px 이상 (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    await rows(page).first().locator("td").nth(2).click();
    await expect(side(page)).toBeVisible();
    const r = await page.evaluate<AuditResult>(contrastAudit("aside.scr-side"));
    expect(r.checked).toBeGreaterThan(8);
    expect(r.low, JSON.stringify(r.low.slice(0, 6))).toEqual([]);
    if (theme === "dark") expect(r.bright, "다크에 밝은 판이 없다").toEqual([]);
    const small = await side(page).locator("button, a").evaluateAll((els) => els
      .map((e) => { const b = e.getBoundingClientRect(); return { t: (e.textContent ?? "").trim() || e.getAttribute("aria-label"), w: Math.round(b.width), h: Math.round(b.height) }; })
      .filter((x) => Math.min(x.w, x.h) < 24));
    expect(small).toEqual([]);
  });
}
