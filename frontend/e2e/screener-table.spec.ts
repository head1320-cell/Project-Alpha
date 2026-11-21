import * as fs from "node:fs";
import { test, expect, type Page, type Route } from "./fixtures";

/**
 * 종목 찾기 — 결과 표의 동작 (U1-0 얼림 · 계획 `docs/superpowers/plans/2026-11-21-uiux-u1-table-screener.md`)
 * ─────────────────────────────────────────────────────────────────
 * U1 은 이 표를 공용 표(`shared/ui/table`)로 옮기고 촘촘하게 그린다. ★겉모습을 옮기는 일이 표의 동작을 바꾸면 안 된다★ —
 * 그래서 옮기기 전의 표에서 초록인 것을 먼저 건다(특성 시험). 옮긴 뒤에도 그대로 초록이어야 하고, 의도한 변화는 그 조각이
 * 이 파일의 기대를 빨강으로 본 뒤에 고친다(계획 문서에 적은 것만: 값 없는 줄의 자리(U1-b 에서 고침) · 내보낸 파일의 열(U1-e)).
 *
 * 기대값은 화면에서 긁지 않는다 — 가로챈 서버 결과(스트림의 result 사건)에서 ★따로 계산한다★.
 * 순서는 ★다시 읽으며★ 견준다(`expect.poll`) — 정렬을 누른 직후 한 번 읽으면, 쪽이 첫 쪽으로 돌아오기 전의 그림(둘째 쪽의 새 순서)을 읽을 수 있다.
 * 선택자는 계약 클래스(`.bsc-table` · `.bsc-row` · `.bsc-name` · `.scr-code` · `.bsc-fav`)와 표 머리의 글자(열 자리)만 쓴다.
 * 거는 것(짝으로 항상-통과를 배제):
 *  · 줄의 순서 = 서버 결과를 그 열로 정렬한 순서(기본 종합점수 ↓ · 현재가 ↓ ↑ · 종합점수 ↑) · 같은 값은 서버 순서 그대로
 *  · 쪽 크기 100 — 다음 쪽은 101번째부터 · 정렬을 바꾸면 첫 쪽으로 돌아온다
 *  · 줄의 값 = 서버 값(현재가 · 종합점수 소수 한 자리 · 판정 · 종목 코드) ↔ 서버 값을 고치면 그 줄이 따라 바뀐다
 *  · 값이 없는 줄: ★어느 방향에서도 끝★(U1-b 가 바꿨다 — 옮기기 전에는 오름차순에서 맨 앞이었다: 미상을 가장 작은 값처럼 읽게 했다)
 *  · 정렬을 누른 그 순간에 첫 쪽이다(옮기기 전에는 한 그림 동안 다른 쪽의 줄이 비쳤다)
 *  · 관심 별: 누르면 켜지고 이 브라우저에 남는다 · 별을 눌러도 줄이 골라지지 않는다
 *  · 표시 열: 고른 열이 머리에 서고 이 브라우저에 남는다 ↔ 값이 전부 없는 열은 숨긴다
 *  · 내려받은 CSV: 머리 줄의 앞 칸 · 줄 수 = 통과한 종목 수 · 줄의 순서 = 화면의 정렬
 *  · CSV 의 출처 열 다섯(U1-e): 데이터 출처 = 화면의 합성 표시와 같은 서버 게이트(꺼짐 · 읽지 못함의 짝) · 자료 기준 시각 N/A + 사유 ·
 *    계산 시각 = 서버 값 그대로 · ★유니버스 · 조건식은 그 결과를 만든 요청의 것★(새 결과가 오기 전에 내려받아도) · 값 없는 수 칸은 빈칸
 *  · 정렬은 이 브라우저에 남는다(U1-e) ↔ 모르는 열 · 틀린 꼴이면 기본 정렬
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

/** 따로 계산한 순서 — ★값이 없는 줄(유한한 수가 아닌 값)은 어느 방향에서도 끝★ · 같은 값은 서버 순서 그대로(안정 정렬). */
function ordered(items: Item[], col: string, dir: "asc" | "desc"): string[] {
  const k = (it: Item) => { const v = it[col]; return typeof v === "number" && Number.isFinite(v) ? v : null; };
  return items.map((it, i) => ({ it, i, v: k(it) }))
    .sort((a, b) => {
      if (a.v === null || b.v === null) return a.v === null && b.v === null ? a.i - b.i : a.v === null ? 1 : -1;
      return (dir === "desc" ? b.v - a.v : a.v - b.v) || a.i - b.i;
    })
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

test("값이 없는 줄: ★어느 방향에서도 끝★(미상은 가장 작은 값이 아니다) — 0 으로 그리지 않는다", async ({ page }) => {
  const s = await watchStream(page, (r) => { r.items[3].current_price = null; r.items[7].current_price = null; });
  await open(page);
  const items = s.last().items;
  const missing = [items[3].stock_code, items[7].stock_code];
  const nPrice = await colIndex(page, /^현재가/);
  await expect(cell(page, missing[0], nPrice), "값 없음은 0 이 아니다").toHaveText("N/A");

  await head(page, /^현재가/).click();                                   // ↓
  expect(ordered(items, "current_price", "desc").slice(-2), "따로 계산한 순서에서도 값 없는 둘이 끝").toEqual(missing);
  await pager(page).getByRole("button", { name: "다음" }).click();
  await expect.poll(async () => (await codes(page)).slice(-2), "내림차순: 끝").toEqual(missing);

  await head(page, /^현재가/).click();                                   // ↑ — 첫 쪽으로 돌아온다
  await expect(pager(page).locator('[aria-current="page"]')).toHaveText("1");
  const up = ordered(items, "current_price", "asc");
  await expect.poll(() => codes(page), "오름차순의 첫 쪽: 값이 있는 줄부터(값 없는 줄이 앞으로 오지 않는다)").toEqual(up.slice(0, 100));
  expect((await codes(page)).filter((c) => missing.includes(c)), "첫 쪽에 값 없는 줄이 없다").toEqual([]);
  await pager(page).getByRole("button", { name: "다음" }).click();
  await expect.poll(async () => (await codes(page)).slice(-2), "오름차순: 여전히 끝").toEqual(missing);
});

test("정렬을 누른 그 순간에 첫 쪽이다 — 다른 쪽의 줄이 한 그림도 비치지 않는다", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  await pager(page).getByRole("button", { name: "다음" }).click();
  await expect(pager(page).locator('[aria-current="page"]')).toHaveText("2");
  // 누른 뒤 표의 몸이 바뀔 때마다 그 그림의 줄을 적는다 — 한 번이라도 다른 쪽의 줄이 그려졌으면 잡힌다(마지막 그림만 보면 놓친다).
  const shots = await page.evaluate(async () => {
    const body = document.querySelector(".bsc-table tbody")!;
    const read = () => [...body.querySelectorAll("tr.bsc-row")].map((tr) => tr.getAttribute("data-code") ?? "");
    const seen: string[][] = [];
    const mo = new MutationObserver(() => { seen.push(read()); });
    mo.observe(body, { childList: true, subtree: true, attributes: true, characterData: true });
    [...document.querySelectorAll<HTMLButtonElement>(".bsc-table thead button")].find((b) => (b.textContent ?? "").startsWith("현재가"))!.click();
    await new Promise((r) => setTimeout(r, 400));
    mo.disconnect();
    return seen;
  });
  const want = ordered(s.last().items, "current_price", "desc").slice(0, 100);
  expect(shots.length, "짝 — 누른 뒤 표가 실제로 다시 그려졌다").toBeGreaterThan(0);
  expect(shots.filter((x) => JSON.stringify(x) !== JSON.stringify(want)).map((x) => `${x.length}줄 · 첫 줄 ${x[0]}`), "새 정렬의 첫 쪽이 아닌 그림").toEqual([]);
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

/** 내려받은 CSV — 표지(BOM)를 확인하고 머리 줄과 줄로 읽는다(따옴표 · 쉼표 · 줄바꿈을 RFC 4180 대로 푼다). */
function parseCsv(text: string): string[][] {
  const out: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (ch === '"') quoted = false; else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\r" && text[i + 1] === "\n") { row.push(cell); out.push(row); row = []; cell = ""; i++; }
    else cell += ch;
  }
  row.push(cell); out.push(row);
  return out;
}
async function downloadCsv(page: Page): Promise<{ header: string[]; rows: string[][]; name: string }> {
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "CSV 내려받기" }).click();
  const d = await dl;
  const text = fs.readFileSync(await d.path(), "utf8");
  expect(text.charCodeAt(0), "엑셀이 한글을 읽게 하는 표지(BOM)").toBe(0xfeff);
  expect(text.charCodeAt(1), "표지는 한 번만").not.toBe(0xfeff);
  const [header, ...rows] = parseCsv(text.slice(1));
  return { header, rows, name: d.suggestedFilename() };
}
const PROV = ["데이터 출처", "자료 기준 시각", "계산 시각(서버 · 시간대 표기 없음)", "유니버스", "조건식"];
const prov = (header: string[], row: string[], name: string) => row[header.indexOf(name)];

test("내려받은 CSV: 머리 줄의 앞 칸 · 줄 수 = 통과한 종목 수 · 줄의 순서 = 화면의 정렬 · ★줄마다 출처 열 다섯★", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  await head(page, /^현재가/).click();                                   // 화면의 정렬을 바꾼 뒤에 내려받는다
  const want = ordered(s.last().items, "current_price", "desc");
  const { header, rows, name } = await downloadCsv(page);
  expect(header.slice(0, 5), "머리 줄의 앞 칸 — 자리는 그대로").toEqual(["순위", "종목코드", "종목명", "섹터", "현재가"]);
  expect(header, "머리 줄에 종합점수 · 판정이 있다").toEqual(expect.arrayContaining(["종합점수", "판정"]));
  expect(header.slice(-5), "출처 열은 결과 열 뒤에 — 앞 열의 자리를 바꾸지 않는다").toEqual(PROV);
  expect(rows.length, "줄 수 = 결과 전체(쪽과 무관)").toBe(s.last().items.length);
  expect(rows.map((r) => r[1]), "줄의 순서 = 화면의 정렬").toEqual(want);
  expect(rows[0][0]).toBe("1");
  expect(rows.every((r) => r.length === header.length), "모든 줄의 칸 수 = 머리의 칸 수").toBe(true);
  const ts = (s.last() as unknown as { timestamp?: unknown }).timestamp;
  expect(typeof ts === "string" && ts.length > 0, "짝 — 서버가 계산 시각을 준다(빈 값을 견주는 공허한 시험이 아니다)").toBe(true);
  for (const r of rows) {
    expect(r.slice(-5)).toEqual(["합성 시세", "N/A(응답에 자료 기준 시각이 없습니다)", ts, "코스피 200(kospi200)", "조건 없음 · 유동성 게이트 끔"]);
  }
  expect(name, "파일 이름의 유니버스도 그 결과의 것").toMatch(/^screener_kospi200_\d+\.csv$/);
});

test("CSV 의 출처 칸은 그 결과를 만든 요청의 것 — 조건을 넣으면 조건식이 따라 바뀐다 · 시각은 서버 값 그대로(짝)", async ({ page }) => {
  const s = await watchStream(page, (r) => { (r as unknown as { timestamp: string }).timestamp = "2001-02-03T04:05:06.789"; });
  await open(page);
  await page.locator('[data-act="universe"]').selectOption("kosdaq150");
  await page.locator('[data-act="add-factor"]').first().click();
  await page.getByPlaceholder("조건을 단어로 입력하십시오").fill("PER");
  await page.locator(".tfm-row").filter({ has: page.locator('.tfm-row-d:text-is("{PER}")') }).first().click();
  await page.getByRole("button", { name: "입력", exact: true }).click();
  await page.locator('[data-act="cond-op"]').first().selectOption("lte");
  await page.locator('[data-act="cond-val"]').first().fill("12.5");
  await page.locator('[data-act="expert"] summary').click();
  await page.locator('[data-act="gate"]').check();
  // 새 결과가 다 온 뒤에 내려받는다(마지막 요청의 본문에 이 조건이 실렸다)
  await expect.poll(async () => {
    const { header, rows } = await downloadCsv(page);
    return rows.length ? prov(header, rows[0], "조건식") : "";
  }, { timeout: 30_000 }).toMatch(/≤ 12\.5 · 유동성 게이트 켬$/);
  const { header, rows } = await downloadCsv(page);
  const cond = prov(header, rows[0], "조건식");
  expect(cond, "필드는 이름(식별자) · 값은 보낸 값 그대로").toMatch(/^PER\([a-z_0-9]+\) ≤ 12\.5 · 유동성 게이트 켬$/);
  expect(prov(header, rows[0], "유니버스")).toBe("코스닥 150(kosdaq150)");
  expect(prov(header, rows[0], "계산 시각(서버 · 시간대 표기 없음)"), "서버가 준 글자 그대로(바꾸거나 시간대를 붙이지 않는다)").toBe("2001-02-03T04:05:06.789");
});

test("★새 결과가 오기 전에 내려받으면 지금 보이는 결과의 요청을 적는다★ — 화면에서 고치는 중인 조건을 앞 결과에 붙이지 않는다", async ({ page }) => {
  let release: () => void = () => undefined;
  let calls = 0, holding = 0;
  await page.route(STREAM, async (route: Route) => {
    calls += 1;
    if (calls > 1) await new Promise<void>((res) => { release = res; holding += 1; });   // 둘째 요청부터는 풀어 줄 때까지 붙든다
    const res = await route.fetch();
    await route.fulfill({ response: res, body: await res.text() });
  });
  await open(page);
  const before = await downloadCsv(page);
  expect(prov(before.header, before.rows[0], "유니버스")).toBe("코스피 200(kospi200)");

  await page.locator('[data-act="universe"]').selectOption("kosdaq150");
  await expect.poll(() => holding, { timeout: 10_000 }).toBe(1);              // 새 요청이 떠났고 아직 답이 없다
  await expect(rows(page).first(), "앞 결과가 아직 보인다").toBeVisible();
  const during = await downloadCsv(page);
  expect(during.rows.length, "같은 결과").toBe(before.rows.length);
  expect(prov(during.header, during.rows[0], "유니버스"), "보이는 결과를 만든 요청 — 지금 고른 유니버스가 아니다").toBe("코스피 200(kospi200)");
  expect(during.name).toMatch(/^screener_kospi200_/);

  release();                                                                    // 짝 — 새 결과가 오면 새 요청을 적는다
  await expect.poll(async () => { const d = await downloadCsv(page); return prov(d.header, d.rows[0], "유니버스"); }, { timeout: 30_000 }).toBe("코스닥 150(kosdaq150)");
});

test("CSV 의 데이터 출처 = 화면의 합성 표시와 같은 서버 게이트 — 꺼지면 '합성 아님 · 등급 미상' · 읽지 못하면 N/A + 사유(짝)", async ({ page }) => {
  await page.route("**/api/v1/macro/connection-status", (r) => r.fulfill({ json: { mock_allowed: false, real_mode: true, bok_configured: true, fred_configured: true } }));
  await open(page);
  await expect(page.locator('.scr-answer .tx-chip[data-tone="practice"]'), "화면도 합성 표시를 하지 않는다").toHaveCount(0);
  let d = await downloadCsv(page);
  expect(new Set(d.rows.map((r) => prov(d.header, r, "데이터 출처")))).toEqual(new Set(["합성 아님 · 등급 미상"]));

  await page.unroute("**/api/v1/macro/connection-status");
  await page.route("**/api/v1/macro/connection-status", (r) => r.fulfill({ status: 500, json: { detail: "down" } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.scr-answer .tx-chip[data-tone="unknown"]'), "화면이 확인 실패를 말한 뒤에").toHaveText("데이터 출처 확인 실패", { timeout: 15_000 });
  d = await downloadCsv(page);
  expect(prov(d.header, d.rows[0], "데이터 출처")).toBe("N/A(출처 확인 실패)");
});

test("CSV 의 값 없는 수 칸은 빈칸 — 0 · N/A 가 아니다(도구가 결측으로 읽는다) ↔ 값이 있으면 그 수(짝)", async ({ page }) => {
  const s = await watchStream(page, (r) => { r.items[0].current_price = null; });
  await open(page);
  const { header, rows } = await downloadCsv(page);
  const iPrice = header.indexOf("현재가");
  const gone = s.last().items[0].stock_code;
  expect(rows.find((r) => r[1] === gone)![iPrice]).toBe("");
  const other = rows.find((r) => r[1] !== gone)!;
  expect(Number(other[iPrice])).toBe(s.last().items.find((it) => it.stock_code === other[1])!.current_price);
});

test("정렬은 이 브라우저에 남는다 — 다시 열면 그 열 · 그 방향 · 그 순서 ↔ 처음은 종합점수 ↓ 이고 저장값이 없다(짝)", async ({ page }) => {
  const s = await watchStream(page);
  await open(page);
  expect(await page.evaluate(() => localStorage.getItem("alpha_screener_sort"))).toBeNull();
  await expect(page.locator('.bsc-table thead th[aria-sort="descending"]')).toContainText("종합점수");
  await head(page, /^현재가/).click();
  await head(page, /^현재가/).click();                                   // 현재가 ↓ → ↑
  expect(JSON.parse(await page.evaluate(() => localStorage.getItem("alpha_screener_sort") ?? "null"))).toEqual({ col: "current_price", dir: "asc" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.bsc-table thead th[aria-sort="ascending"]')).toContainText("현재가");
  await expect.poll(() => codes(page)).toEqual(ordered(s.last().items, "current_price", "asc").slice(0, 100));
});

test("저장된 정렬이 모르는 열 · 틀린 방향 · 틀린 꼴이면 기본 정렬(종합점수 ↓) — 보이지 않는 열의 순서를 지어내지 않는다", async ({ page }) => {
  const s = await watchStream(page);
  for (const raw of ['{"col":"no_such_col","dir":"asc"}', '{"col":"current_price","dir":"sideways"}', "not json", '["current_price","asc"]']) {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await page.evaluate((v) => localStorage.setItem("alpha_screener_sort", v), raw);
    await open(page);
    await expect(page.locator('.bsc-table thead th[aria-sort="descending"]'), raw).toContainText("종합점수");
    await expect.poll(() => codes(page), raw).toEqual(ordered(s.last().items, "composite_score", "desc").slice(0, 100));
  }
});
