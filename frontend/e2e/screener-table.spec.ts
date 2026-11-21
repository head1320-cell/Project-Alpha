import * as fs from "node:fs";
import { test, expect, type Page, type Route } from "./fixtures";

/**
 * 종목 찾기 — 결과 표의 동작 (U1-0 얼림 · 계획 `docs/superpowers/plans/2026-11-21-uiux-u1-table-screener.md`)
 * ─────────────────────────────────────────────────────────────────
 * U1 은 이 표를 공용 표(`shared/ui/table`)로 옮기고 촘촘하게 그린다. ★겉모습을 옮기는 일이 표의 동작을 바꾸면 안 된다★ —
 * 그래서 옮기기 전의 표에서 초록인 것을 먼저 건다(특성 시험). 옮긴 뒤에도 그대로 초록이어야 하고, 의도한 변화는 그 조각이
 * 이 파일의 기대를 빨강으로 본 뒤에 고친다(계획 문서에 적은 것만: 값 없는 줄의 자리 · 내보낸 파일의 열).
 *
 * 기대값은 화면에서 긁지 않는다 — 가로챈 서버 결과(스트림의 result 사건)에서 ★따로 계산한다★.
 * 순서는 ★다시 읽으며★ 견준다(`expect.poll`) — 정렬을 누른 직후 한 번 읽으면, 쪽이 첫 쪽으로 돌아오기 전의 그림(둘째 쪽의 새 순서)을 읽을 수 있다.
 * 선택자는 계약 클래스(`.bsc-table` · `.bsc-row` · `.bsc-name` · `.scr-code` · `.bsc-fav`)와 표 머리의 글자(열 자리)만 쓴다.
 * 거는 것(짝으로 항상-통과를 배제):
 *  · 줄의 순서 = 서버 결과를 그 열로 정렬한 순서(기본 종합점수 ↓ · 현재가 ↓ ↑ · 종합점수 ↑) · 같은 값은 서버 순서 그대로
 *  · 쪽 크기 100 — 다음 쪽은 101번째부터 · 정렬을 바꾸면 첫 쪽으로 돌아온다
 *  · 줄의 값 = 서버 값(현재가 · 종합점수 소수 한 자리 · 판정 · 종목 코드) ↔ 서버 값을 고치면 그 줄이 따라 바뀐다
 *  · 값이 없는 줄: 내림차순에서는 끝 · ★오름차순에서는 맨 앞(지금의 동작 — U1-b 가 '어느 방향에서도 끝'으로 바꾼다)★
 *  · 관심 별: 누르면 켜지고 이 브라우저에 남는다 · 별을 눌러도 줄이 골라지지 않는다
 *  · 표시 열: 고른 열이 머리에 서고 이 브라우저에 남는다 ↔ 값이 전부 없는 열은 숨긴다
 *  · 내려받은 CSV: 머리 줄의 앞 일곱 칸 · 줄 수 = 통과한 종목 수 · 줄의 순서 = 화면의 정렬
 */

type Item = Record<string, unknown> & { stock_code: string; corp_name: string; current_price: number | null; composite_score: number; verdict: string };
type Result = { total_passed: number; items: Item[] };

const STREAM = "**/api/v1/screener/run-advanced-stream";
const rows = (p: Page) => p.locator(".bsc-table tbody tr.bsc-row");
const codes = (p: Page) => rows(p).evaluateAll((trs) => trs.map((tr) => tr.getAttribute("data-code") ?? ""));
const head = (p: Page, name: RegExp) => p.locator(".bsc-table thead").getByRole("button", { name });
const pager = (p: Page) => p.getByRole("navigation", { name: "결과 쪽" });

/** 스트림의 result 사건을 고쳐 돌려주고(고칠 것이 없으면 그대로) 그 결과를 잡아 둔다 — 서버 응답의 변형이지 지어낸 응답이 아니다. */
async function watchStream(page: Page, edit?: (r: Result) => void): Promise<{ last: () => Result }> {
  let last: Result | null = null;
  await page.route(STREAM, async (route: Route) => {
    const res = await route.fetch();
    const text = await res.text();
    const out = text.split("\n\n").map((part) => {
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

/** 따로 계산한 순서 — 수가 아닌 값은 −∞(지금 화면의 규칙) · 같은 값은 서버 순서 그대로(안정 정렬). */
function ordered(items: Item[], col: string, dir: "asc" | "desc"): string[] {
  const k = (it: Item) => { const v = it[col]; return typeof v === "number" && Number.isFinite(v) ? v : -Infinity; };
  return items.map((it, i) => ({ it, i }))
    .sort((a, b) => { const d = dir === "desc" ? k(b.it) - k(a.it) : k(a.it) - k(b.it); return (Number.isNaN(d) ? 0 : d) || a.i - b.i; })
    .map((x) => x.it.stock_code);
}
/** 머리 글자로 열의 자리(1부터)를 찾는다 — 표의 구조와 무관하게 그 열의 칸을 집는다. */
async function colIndex(page: Page, name: RegExp): Promise<number> {
  const texts = await page.locator(".bsc-table thead th").allTextContents();
  const i = texts.findIndex((t) => name.test(t.trim()));
  expect(i, `머리에 ${name} 열이 있다: ${texts.join(" | ")}`).toBeGreaterThanOrEqual(0);
  return i + 1;
}
const cell = (page: Page, code: string, n: number) => page.locator(`.bsc-table tbody tr.bsc-row[data-code="${code}"] > td:nth-child(${n})`);
const digits = (s: string) => Number(s.replace(/[^\d.-]/g, ""));

test("줄의 순서 = 서버 결과를 그 열로 정렬한 순서 — 기본 종합점수 ↓ · 현재가 ↓ ↑ · 종합점수 ↑ (같은 값은 서버 순서)", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  const items = s.last().items;
  expect(items.length, "짝 — 견줄 줄이 넉넉하다").toBeGreaterThan(20);
  expect(new Set(items.map((it) => it.current_price)).size, "짝 — 현재가가 한 값이 아니다(정렬이 뜻이 있다)").toBeGreaterThan(5);

  await expect.poll(() => codes(page), "기본: 종합점수 내림차순").toEqual(ordered(items, "composite_score", "desc").slice(0, 100));
  await head(page, /^현재가/).click();
  await expect.poll(() => codes(page), "현재가 ↓").toEqual(ordered(items, "current_price", "desc").slice(0, 100));
  await head(page, /^현재가/).click();
  await expect.poll(() => codes(page), "현재가 ↑").toEqual(ordered(items, "current_price", "asc").slice(0, 100));
  await head(page, /^종합점수/).click();
  await expect.poll(() => codes(page), "다른 열을 누르면 그 열의 내림차순부터").toEqual(ordered(items, "composite_score", "desc").slice(0, 100));
  await head(page, /^종합점수/).click();
  await expect.poll(() => codes(page), "종합점수 ↑").toEqual(ordered(items, "composite_score", "asc").slice(0, 100));
  expect(ordered(items, "current_price", "desc"), "짝 — 두 정렬의 순서가 실제로 다르다").not.toEqual(ordered(items, "composite_score", "desc"));
});

test("쪽 크기 100 — 다음 쪽은 101번째부터 · 정렬을 바꾸면 첫 쪽으로", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  const all = ordered(s.last().items, "composite_score", "desc");
  expect(all.length, "짝 — 두 쪽이 되는 결과다").toBeGreaterThan(100);
  await expect(rows(page)).toHaveCount(100);
  await expect(pager(page).locator('[aria-current="page"]')).toHaveText("1");

  await pager(page).getByRole("button", { name: "다음" }).click();
  await expect(pager(page).locator('[aria-current="page"]')).toHaveText("2");
  await expect.poll(() => codes(page), "둘째 쪽").toEqual(all.slice(100, 200));
  expect(await rows(page).first().locator("td").first().innerText(), "순위는 쪽을 넘어 이어진다").toBe("101");

  await head(page, /^현재가/).click();
  await expect(pager(page).locator('[aria-current="page"]')).toHaveText("1");
  await expect.poll(() => codes(page)).toEqual(ordered(s.last().items, "current_price", "desc").slice(0, 100));
});

test("줄의 값 = 서버 값(현재가 · 종합점수 소수 한 자리 · 판정 · 코드) ↔ 서버 값을 고치면 그 줄이 따라 바뀐다", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  const nPrice = await colIndex(page, /^현재가/), nScore = await colIndex(page, /^종합점수/);
  for (const it of s.last().items.slice(0, 5)) {
    const row = page.locator(`.bsc-table tbody tr.bsc-row[data-code="${it.stock_code}"]`);
    await expect(row.locator(".bsc-name")).toHaveText(it.corp_name);
    await expect(row.locator(".scr-code")).toHaveText(it.stock_code);
    expect(digits(await cell(page, it.stock_code, nPrice).innerText()), `${it.corp_name} 현재가`).toBe(it.current_price);
    await expect(cell(page, it.stock_code, nScore)).toHaveText(it.composite_score.toLocaleString("ko-KR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
    await expect(row.locator(".tx-chip")).toHaveText(it.verdict);
  }

  await page.unroute(STREAM);
  // 점수는 첫 쪽에 남는 값으로 고친다(기본 정렬이 종합점수라 낮추면 그 줄이 뒤쪽으로 간다).
  const s2 = await watchStream(page, (r) => { r.items[0].current_price = 1234567; r.items[0].composite_score = 99.94; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  const bent = s2.last().items[0];
  expect(digits(await cell(page, bent.stock_code, nPrice).innerText())).toBe(1234567);
  await expect(cell(page, bent.stock_code, nScore)).toHaveText("99.9");
});

test("값이 없는 줄: 내림차순에서는 끝 · ★오름차순에서는 맨 앞(지금의 동작)★ — 0 으로 그리지 않는다", async ({ page }) => {
  const s = await watchStream(page, (r) => { r.items[3].current_price = null; r.items[7].current_price = null; });
  await open(page);
  const items = s.last().items;
  const missing = [items[3].stock_code, items[7].stock_code];
  const nPrice = await colIndex(page, /^현재가/);
  await expect(cell(page, missing[0], nPrice), "값 없음은 0 이 아니다").toHaveText("N/A");

  await head(page, /^현재가/).click();                                   // ↓
  const down = ordered(items, "current_price", "desc");
  expect(down.slice(-2), "따로 계산한 순서에서도 값 없는 둘이 끝").toEqual(missing);
  await pager(page).getByRole("button", { name: "다음" }).click();
  await expect.poll(async () => (await codes(page)).slice(-2), "내림차순: 끝").toEqual(missing);

  await head(page, /^현재가/).click();                                   // ↑
  await expect.poll(async () => (await codes(page)).slice(0, 2), "오름차순: 맨 앞(지금의 동작 — U1-b 가 끝으로 옮긴다)").toEqual(missing);
});

test("관심 별: 누르면 켜지고 이 브라우저에 남는다 · 별을 눌러도 줄이 골라지지 않는다", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  const first = s.last().items[0];
  const star = rows(page).first().locator(".bsc-fav");
  await expect(star).toHaveAttribute("aria-pressed", "false");
  await expect(star).toHaveAccessibleName(`${first.corp_name} 관심 종목에 넣기`);
  await star.click();
  await expect(star).toHaveAttribute("aria-pressed", "true");
  await expect(star).toHaveAccessibleName(`${first.corp_name} 관심 종목에서 빼기`);
  await expect(page.locator("dialog[open]"), "별은 줄을 고르지 않는다").toHaveCount(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("alpha_screener_favs") ?? "[]"))).toEqual([first.stock_code]);

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first().locator(".bsc-fav")).toHaveAttribute("aria-pressed", "true", { timeout: 30_000 });
  await expect(rows(page).nth(1).locator(".bsc-fav"), "짝 — 누르지 않은 줄은 꺼져 있다").toHaveAttribute("aria-pressed", "false");
});

test("표시 열: 고른 열이 머리에 서고 이 브라우저에 남는다 ↔ 값이 전부 없는 열은 숨긴다(짝)", async ({ page }) => {
  const fieldsRes = page.waitForResponse((r) => r.url().includes("/api/v1/screener/fields") && r.status() === 200);
  const s = await watchStream(page);
  await open(page);
  const catalog = await (await fieldsRes).json() as { categories: { fields: { id: string; label: string }[] }[] };
  const fields = catalog.categories.flatMap((c) => c.fields);
  // 값이 실제로 있는 열 하나를 고른다(지어내지 않는다 — 서버 결과에서 수가 있는 열).
  const pick = fields.find((f) => !["current_price", "market_cap_억", "composite_score"].includes(f.id)
    && s.last().items.some((it) => typeof it[f.id] === "number" && Number.isFinite(it[f.id] as number)));
  expect(pick, "짝 — 값이 있는 표시 열 후보가 있다").toBeTruthy();
  const th = page.locator(".bsc-table thead th", { hasText: new RegExp(`^${pick!.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`) });
  await expect(th).toHaveCount(0);

  await page.getByRole("button", { name: /^표시 열/ }).click();
  await page.getByRole("textbox", { name: "열 찾기" }).fill(pick!.label);
  await page.locator(".bsc-colpicker-item", { hasText: new RegExp(`^${pick!.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`) }).locator("input").check();
  await expect(th).toHaveCount(1);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("alpha_screener_cols") ?? "[]"))).toEqual([pick!.id]);
  const n = await colIndex(page, new RegExp(`^${pick!.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
  const withVal = s.last().items.find((it) => typeof it[pick!.id] === "number" && Number.isFinite(it[pick!.id] as number))!;
  expect(digits(await cell(page, withVal.stock_code, n).innerText()), "그 열의 칸 = 서버 값(화면 자릿수까지)").toBeCloseTo(withVal[pick!.id] as number, 0);

  // 짝 — 같은 열의 값을 서버 결과에서 모두 비우면 그 열은 숨는다(고른 것은 남아 있다).
  await page.unroute(STREAM);
  await watchStream(page, (r) => { for (const it of r.items) it[pick!.id] = null; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  await expect(th, "값이 전부 없는 표시 열은 머리에 없다").toHaveCount(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("alpha_screener_cols") ?? "[]")), "고른 것은 지우지 않는다").toEqual([pick!.id]);
});

test("내려받은 CSV: 머리 줄의 앞 일곱 칸 · 줄 수 = 통과한 종목 수 · 줄의 순서 = 화면의 정렬", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  await head(page, /^현재가/).click();                                   // 화면의 정렬을 바꾼 뒤에 내려받는다
  const want = ordered(s.last().items, "current_price", "desc");
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "CSV 내려받기" }).click();
  const file = await (await dl).path();
  const text = fs.readFileSync(file, "utf8");
  expect(text.charCodeAt(0), "엑셀이 한글을 읽게 하는 표지(BOM)").toBe(0xfeff);
  const lines = text.slice(1).split("\r\n");
  expect(lines[0].split(",").slice(0, 5), "머리 줄의 앞 칸").toEqual(["순위", "종목코드", "종목명", "섹터", "현재가"]);
  expect(lines[0].split(","), "머리 줄에 종합점수 · 판정이 있다").toEqual(expect.arrayContaining(["종합점수", "판정"]));
  expect(lines.length - 1, "줄 수 = 결과 전체(쪽과 무관)").toBe(s.last().items.length);
  expect(lines.slice(1).map((l) => l.split(",")[1]), "줄의 순서 = 화면의 정렬").toEqual(want);
  expect(lines[1].split(",")[0]).toBe("1");
});
