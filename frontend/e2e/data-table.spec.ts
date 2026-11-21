import { test, expect, type Locator, type Page } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * 공용 표 `DataTable` — 견본(`/dev/ui` 의 '공용 표' 절)에서 건다 (U1-a · ADR 007 §5 · 계획 `docs/superpowers/plans/2026-11-21-uiux-u1-table-screener.md`)
 * ─────────────────────────────────────────────────────────────────
 * 견본의 줄은 손으로 적은 일곱 줄이다(쪽 크기 5). 기대값은 그 일곱 줄에서 손으로 계산했다 — 화면에서 긁지 않는다.
 * 거는 것(짝으로 항상-통과를 배제):
 *  · 표에 이름이 있다 · 머리 칸은 `scope="col"` · 글자를 숨긴 동작 열에도 이름이 있다
 *  · 정렬 표시: 정렬 중인 열만 방향 · 정렬할 수 있는 다른 열은 none · 정렬할 수 없는 열에는 속성이 없다(한 머리에만 다는 구현을 배제)
 *  · ★값이 없는 줄은 어느 방향에서도 끝★ · 칸의 글자는 `N/A`(0 이 아니다) · 사유는 표의 설명으로 이어져 있다
 *  · 자판: 표의 줄 가운데 ★하나만★ 탭 순서에 있다 · ↑ ↓ Home End 가 초점을 옮긴다 · Enter · Space 가 고른다 · 칸 안의 단추는 줄을 고르지 않는다
 *  · 밀도 셋의 줄 높이 · 칸 여백 · 글자 = 토큰 값 ↔ 속성이 없는 상자는 넉넉(기본값) · 수 칸은 오른쪽 + 고정폭 숫자
 *  · 누르는 것은 어떤 밀도에서도 24px 이상 · 초점 고리는 잉크 2px · 전환 없음 · 대비 AA(라이트 · 다크)
 *  · 쪽 넘김: 이름 · 지금 쪽 · 둘째 쪽의 줄 · 고른 줄은 쪽을 넘어도 그 줄이다
 */

const box = (page: Page, density: string | null, dark = false) =>
  page.locator(`#table .devui-tb-box${density ? `[data-density="${density}"]` : ":not([data-density])"}${dark ? ".dark" : ":not(.dark)"}`);
const rowsOf = (b: Locator) => b.locator("table.tx-table tbody tr");
const codesOf = (b: Locator) => rowsOf(b).evaluateAll((trs) => trs.map((tr) => tr.getAttribute("data-row") ?? ""));
const th = (b: Locator, name: string) => b.locator("table.tx-table thead th", { hasText: name });

const BY_SCORE = ["000660", "005930", "005380", "035420", "051910", "068270", "035720"];      // 종합점수 ↓
const BY_PER_DESC = ["068270", "035420", "051910", "005930", "005380", "000660", "035720"];   // PER ↓ — 값 없는 둘(000660 · 035720)이 끝
const BY_PER_ASC = ["005380", "005930", "051910", "035420", "068270", "000660", "035720"];    // PER ↑ — 값 없는 둘이 여전히 끝

async function open(page: Page) {
  await page.goto("/dev/ui#table", { waitUntil: "domcontentloaded" });
  await expect(box(page, "compact").locator("table.tx-table")).toBeVisible({ timeout: 20_000 });
  await page.waitForFunction(() => { const el = document.querySelector("#table"); return !!el && Object.keys(el).some((k) => k.startsWith("__reactFiber")); }, undefined, { timeout: 20_000 });
}

test("표에 이름이 있다 · 머리 칸은 scope=col · 글자를 숨긴 동작 열에도 이름이 있다", async ({ page }) => {
  await open(page);
  const b = box(page, "compact");
  await expect(b.getByRole("table", { name: "공용 표 견본" })).toHaveCount(1);
  const heads = b.locator("table.tx-table thead th");
  expect(await heads.evaluateAll((ths) => ths.map((t) => t.getAttribute("scope"))), "머리 칸마다 scope").toEqual(Array(7).fill("col"));
  expect((await heads.allTextContents()).map((t) => t.replace(/[▲▼]/g, "").trim())).toEqual(["순위", "관심", "종목", "현재가(원)", "PER(배)", "종합점수", "판정"]);
  await expect(th(b, "관심").locator(".tx-sr"), "보이지 않는 머리 글자는 낭독기용").toHaveText("관심");
});

test("정렬 표시: 정렬 중인 열만 방향 · 다른 정렬 열은 none · 정렬할 수 없는 열에는 속성이 없다", async ({ page }) => {
  await open(page);
  const b = box(page, "compact");
  const sorts = () => b.locator("table.tx-table thead th").evaluateAll((ths) => ths.map((t) => t.getAttribute("aria-sort")));
  expect(await sorts(), "처음: 종합점수 내림차순").toEqual([null, null, null, "none", "none", "descending", null]);
  await th(b, "PER(배)").getByRole("button").click();
  expect(await sorts()).toEqual([null, null, null, "none", "descending", "none", null]);
  await th(b, "PER(배)").getByRole("button").click();
  expect(await sorts()).toEqual([null, null, null, "none", "ascending", "none", null]);
  await expect(th(b, "PER(배)").getByRole("button"), "화살표는 이름에 들지 않는다(방향은 aria-sort 가 말한다)").toHaveAccessibleName("PER(배)");
});

test("★값이 없는 줄은 어느 방향에서도 끝★ · 칸의 글자는 N/A(0 이 아니다) · 사유는 표의 설명으로 이어져 있다", async ({ page }) => {
  await open(page);
  const b = box(page, "compact");
  const all = async () => {
    const first = await codesOf(b);
    await b.getByRole("navigation", { name: "공용 표 견본 쪽" }).getByRole("button", { name: "다음" }).click();
    const second = await codesOf(b);
    await b.getByRole("navigation", { name: "공용 표 견본 쪽" }).getByRole("button", { name: "이전" }).click();
    return [...first, ...second];
  };
  expect(await all(), "처음: 종합점수 내림차순").toEqual(BY_SCORE);
  await th(b, "PER(배)").getByRole("button").click();
  expect(await all(), "PER ↓").toEqual(BY_PER_DESC);
  await th(b, "PER(배)").getByRole("button").click();
  expect(await all(), "PER ↑ — 값 없는 줄이 앞으로 오지 않는다").toEqual(BY_PER_ASC);

  await b.getByRole("navigation", { name: "공용 표 견본 쪽" }).getByRole("button", { name: "다음" }).click();
  const naCell = b.locator('table.tx-table tbody tr[data-row="000660"] td').nth(4);
  await expect(naCell).toHaveText("N/A");
  const table = b.locator("table.tx-table");
  const noteId = await table.getAttribute("aria-describedby");
  expect(noteId, "표가 설명을 가리킨다").toBeTruthy();
  await expect(b.locator(`[id="${noteId}"]`)).toBeVisible();
  await expect(b.locator(`[id="${noteId}"]`)).toContainText("0 이 아닙니다");
});

test("자판: 줄 하나만 탭 순서에 있다 · ↑ ↓ Home End 가 초점을 옮긴다 · Enter · Space 가 고른다", async ({ page }) => {
  await open(page);
  const b = box(page, "compact");
  const tabbable = () => rowsOf(b).evaluateAll((trs) => trs.filter((tr) => tr.getAttribute("tabindex") === "0").map((tr) => tr.getAttribute("data-row")));
  const focused = () => page.evaluate(() => document.activeElement?.getAttribute("data-row") ?? null);
  const current = () => rowsOf(b).evaluateAll((trs) => trs.filter((tr) => tr.getAttribute("aria-current") === "true").map((tr) => tr.getAttribute("data-row")));
  expect(await tabbable(), "처음: 첫 줄 하나만").toEqual([BY_SCORE[0]]);
  expect(await rowsOf(b).evaluateAll((trs) => trs.map((tr) => tr.getAttribute("tabindex"))), "나머지는 -1(초점은 받되 탭 순서에는 없다)").toEqual(["0", "-1", "-1", "-1", "-1"]);

  await rowsOf(b).first().focus();
  await page.keyboard.press("ArrowDown");
  expect(await focused()).toBe(BY_SCORE[1]);
  expect(await tabbable(), "탭 순서의 줄이 초점을 따라온다").toEqual([BY_SCORE[1]]);
  await page.keyboard.press("End");
  expect(await focused()).toBe(BY_SCORE[4]);
  await page.keyboard.press("ArrowDown");
  expect(await focused(), "끝에서 멈춘다").toBe(BY_SCORE[4]);
  await page.keyboard.press("Home");
  expect(await focused()).toBe(BY_SCORE[0]);
  expect(await current(), "초점만 옮겼다 — 고르지 않았다").toEqual([]);

  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  expect(await current()).toEqual([BY_SCORE[1]]);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press(" ");
  expect(await current(), "Space 도 고른다 · 고른 줄은 하나").toEqual([BY_SCORE[2]]);
  await expect(b.locator(".devui-tb-picked")).toHaveText(`고른 줄: ${BY_SCORE[2]}`);
});

test("칸 안의 단추는 줄을 고르지 않는다(누르기 · Enter 모두) ↔ 줄을 누르면 고른다(짝)", async ({ page }) => {
  await open(page);
  const b = box(page, "compact");
  const current = () => rowsOf(b).evaluateAll((trs) => trs.filter((tr) => tr.getAttribute("aria-current") === "true").map((tr) => tr.getAttribute("data-row")));
  const star = rowsOf(b).first().getByRole("button");
  await expect(star).toHaveAttribute("aria-pressed", "false");
  await star.click();
  await expect(star).toHaveAttribute("aria-pressed", "true");
  await star.focus();
  await page.keyboard.press("Enter");
  await expect(star).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("ArrowDown");
  expect(await page.evaluate(() => document.activeElement?.tagName), "단추에서 누른 ↓ 는 줄 초점을 옮기지 않는다").toBe("BUTTON");
  expect(await current(), "단추는 줄을 고르지 않는다").toEqual([]);

  await rowsOf(b).nth(3).locator("td").nth(2).click();
  expect(await current()).toEqual([BY_SCORE[3]]);
});

const DENSITY = { compact: { row: 28, cell: 8, td: 12, th: 11 }, regular: { row: 34, cell: 12, td: 13, th: 12 }, comfortable: { row: 44, cell: 16, td: 14, th: 13 } } as const;
const measure = (b: Locator) => b.locator("table.tx-table").evaluate((t) => {
  const td = t.querySelector("tbody td.num") as HTMLElement, name = t.querySelectorAll("tbody td")[2] as HTMLElement, head = t.querySelector("thead th.num") as HTMLElement;
  const c = getComputedStyle(td), h = getComputedStyle(head);
  return { row: Math.round((t.querySelector("tbody tr") as HTMLElement).getBoundingClientRect().height), headRow: Math.round(head.getBoundingClientRect().height),
    cell: parseFloat(getComputedStyle(name).paddingLeft), td: parseFloat(c.fontSize), th: parseFloat(h.fontSize), align: c.textAlign, nums: c.fontVariantNumeric, headAlign: h.textAlign,
    sticky: h.position, family: c.fontFamily === getComputedStyle(name).fontFamily };
});

for (const [density, want] of Object.entries(DENSITY)) {
  test(`밀도 ${density}: 줄 ${want.row}px · 칸 여백 ${want.cell}px · 글자 ${want.td}/${want.th}px · 수 칸은 오른쪽 + 고정폭 숫자 · 머리 고정`, async ({ page }) => {
    await open(page);
    const m = await measure(box(page, density));
    expect(m).toEqual({ row: want.row, headRow: want.row, cell: want.cell, td: want.td, th: want.th, align: "right", nums: "tabular-nums", headAlign: "right", sticky: "sticky", family: true });
  });
}

test("짝: 속성이 없는 상자는 넉넉(기본값) — 밀도는 속성이 정한다", async ({ page }) => {
  await open(page);
  const m = await measure(box(page, null));
  expect([m.row, m.cell, m.td, m.th]).toEqual([44, 16, 14, 13]);
  // 단 밖의 전역 `.num` 은 고정폭 글꼴이다(옛 규칙) — 공용 표의 수 칸은 단 밖에서도 본문 글꼴의 고정폭 숫자여야 한다(결정 D3 · 표의 규칙이지 단의 규칙이 아니다).
  expect([m.align, m.nums, m.sticky, m.family], "단 밖에서도 수 칸은 오른쪽 + 본문 글꼴의 고정폭 숫자 · 머리는 붙는다").toEqual(["right", "tabular-nums", "sticky", true]);
  const c = await measure(box(page, "compact"));
  expect(c.row, "짝 — 촘촘은 실제로 더 낮다").toBeLessThan(m.row);
});

test("누르는 것은 어떤 밀도에서도 24px 이상(정렬 머리 · 칸 안 단추 · 쪽 넘김)", async ({ page }) => {
  await open(page);
  for (const density of ["compact", "regular", "comfortable"]) {
    const small = await box(page, density).locator("table.tx-table button, nav button").evaluateAll((els) => els
      .map((e) => { const r = e.getBoundingClientRect(); return { t: (e.textContent ?? "").trim() || e.getAttribute("aria-label") || "?", w: Math.round(r.width), h: Math.round(r.height) }; })
      .filter((x) => x.w > 0 && Math.min(x.w, x.h) < 24));
    expect(small, `${density}: 24px 미만`).toEqual([]);
    expect(await box(page, density).locator("table.tx-table button, nav button").count(), "짝 — 잰 단추가 있다").toBeGreaterThan(8);
  }
});

test("초점 고리는 잉크 2px · 전환 없음(줄 · 정렬 머리) · 고른 줄은 줄 전체의 바탕", async ({ page }) => {
  await open(page);
  const b = box(page, "compact");
  const ring = (l: Locator) => l.evaluate((e) => { const c = getComputedStyle(e); const probe = document.createElement("span"); probe.style.color = "var(--tx-focus)"; e.appendChild(probe);
    const ink = getComputedStyle(probe).color; probe.remove(); return { style: c.outlineStyle, width: c.outlineWidth, ink: c.outlineColor === ink, dur: c.transitionDuration }; });
  await rowsOf(b).first().focus();
  await page.keyboard.press("ArrowDown");                                // 자판으로 옮긴 초점 → :focus-visible
  expect(await ring(rowsOf(b).nth(1))).toEqual({ style: "solid", width: "2px", ink: true, dur: "0s" });
  expect((await ring(rowsOf(b).nth(2))).style, "짝 — 초점이 없는 줄에는 고리가 없다").toBe("none");

  await page.keyboard.press("Enter");
  const bg = (l: Locator) => l.evaluateAll((tds) => tds.map((td) => getComputedStyle(td).backgroundColor));
  const picked = await bg(rowsOf(b).nth(1).locator("td")), plain = await bg(rowsOf(b).nth(3).locator("td"));
  expect(new Set(picked).size, "고른 줄의 칸은 모두 같은 바탕").toBe(1);
  expect(picked[0], "고른 줄의 바탕은 다른 줄과 다르다").not.toBe(plain[0]);

  const btn = th(b, "현재가(원)").getByRole("button");
  await btn.focus();
  await page.keyboard.press("Shift+Tab"); await page.keyboard.press("Tab");
  expect(await ring(btn)).toEqual({ style: "solid", width: "2px", ink: true, dur: "0s" });
});

for (const dark of [false, true]) {
  test(`대비 AA — ${dark ? "다크" : "라이트"} 촘촘(고른 줄 포함)`, async ({ page }) => {
    await open(page);
    const b = box(page, "compact", dark);
    await rowsOf(b).nth(1).locator("td").nth(2).click();                 // 고른 줄의 바탕 위에서도 잰다
    await b.evaluate((e) => e.setAttribute("data-audit", "1"));
    const r = await page.evaluate<AuditResult>(contrastAudit('#table .devui-tb-box[data-audit="1"]'));
    expect(r.checked).toBeGreaterThan(20);
    expect(r.low, JSON.stringify(r.low.slice(0, 6))).toEqual([]);
  });
}

test("쪽 넘김: 이름 · 지금 쪽 · 둘째 쪽의 줄과 순위 · 줄의 범위 글자", async ({ page }) => {
  await open(page);
  const b = box(page, "compact");
  const nav = b.getByRole("navigation", { name: "공용 표 견본 쪽" });
  await expect(nav.locator('[aria-current="page"]')).toHaveText("1");
  await expect(nav.getByRole("button", { name: "이전" })).toBeDisabled();
  await expect(nav).toContainText("1 ~ 5 / 7");
  await nav.getByRole("button", { name: "다음" }).click();
  await expect(nav.locator('[aria-current="page"]')).toHaveText("2");
  expect(await codesOf(b)).toEqual(BY_SCORE.slice(5));
  await expect(rowsOf(b).first().locator("td").first(), "순위는 쪽을 넘어 이어진다").toHaveText("6");
  await expect(nav.getByRole("button", { name: "다음" })).toBeDisabled();
  await expect(nav).toContainText("6 ~ 7 / 7");
});
