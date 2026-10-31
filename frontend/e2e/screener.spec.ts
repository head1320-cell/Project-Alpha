import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BU2 · 종목 찾기 — 답 한 문장 + 근거 칩 · 실패는 실패로 · 시트 · "설계에 넣기" 다리 (계획 "BU2 상세")
 * 거는 것(짝으로 항상-통과·항상-침묵을 배제):
 *  · 답 = 서버 `total_passed`(스트림 결과를 고치면 문장이 따라 바뀐다) · 0 이면 "없어요"
 *  · ★스트림 실패는 alert + 다시 시도 — 옛 결과 표를 남기지 않는다★ · 정상이면 alert 없음
 *  · 연습용 칩은 서버 게이트(`connection-status`)로만 · "일부만 평가했어요"는 서버 `capped` 로만(짝)
 *  · 전문가 설정은 접혀 있고(게이트·조건식 안 보임) 펼치면 보인다 · 게이트는 꺼짐(요청 골든이 바이트로도 건다)
 *  · 행 → 시트에 그 행의 서버 값 · 기업 분석으로 · Esc 로 닫힘
 *  · [상위 10종목 설계에 넣기] → 표 위 10개 코드 그대로 캔버스 종목 고르기 노드에 · 알 수 없는 코드는 빠지고 메모가 말한다 ·
 *    이름 확인이 실패하면 아무 코드도 싣지 않는다(짝)
 *  · 판정 칩은 중립 · 라이트/다크 AA · 390 가로 넘침 없음
 */

type Item = { stock_code: string; corp_name: string; current_price: number; composite_score: number; verdict: string };
type Result = { total_passed: number; items: Item[]; capped?: boolean; ingested_count?: number; universe_size?: number };

const answer = (p: Page) => p.locator(".scr-answer .tx-answer-s");
const rows = (p: Page) => p.locator(".bsc-table tbody tr.bsc-row");

/** 스트림(SSE) 응답의 result 사건만 고쳐 돌려준다 — 서버 응답의 변형이지 지어낸 응답이 아니다. */
async function patchStream(page: Page, edit: (r: Result) => void) {
  await page.route("**/api/v1/screener/run-advanced-stream", async (route: Route) => {
    const res = await route.fetch();
    const text = await res.text();
    const out = text.split("\n\n").map((part) => {
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
  await expect(page.locator(".scr")).toBeVisible({ timeout: 20_000 });
}
async function settled(page: Page) {
  await expect(answer(page)).toBeVisible({ timeout: 30_000 });
}

test("답 = 서버 total_passed — 137 로 고치면 '137개' · 0 이면 '없어요'(짝)", async ({ page }) => {
  await patchStream(page, (r) => { r.total_passed = 137; });
  await open(page);
  await settled(page);
  await expect(answer(page)).toHaveText("조건에 맞는 종목 137개예요");

  await page.unroute("**/api/v1/screener/run-advanced-stream");
  await patchStream(page, (r) => { r.total_passed = 0; r.items = []; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(answer(page)).toHaveText("조건에 맞는 종목이 없어요", { timeout: 30_000 });
  await expect(rows(page)).toHaveCount(0);
});

test("★스트림 실패는 alert + 다시 시도 — 옛 결과 표를 남기지 않는다★ · 정상이면 alert 없음(짝)", async ({ page }) => {
  await open(page);
  await settled(page);
  await expect(page.locator(".scr [role='alert']")).toHaveCount(0);
  expect(await rows(page).count()).toBeGreaterThan(0);

  await page.route("**/api/v1/screener/run-advanced-stream", (r) => r.fulfill({ status: 500, body: "x" }));
  await page.locator('[data-act="universe"]').selectOption("kosdaq150");           // 새 실행이 실패한다
  const alert = page.locator(".scr-answer-wrap [role='alert']");
  await expect(alert).toContainText("종목을 거르지 못했어요", { timeout: 30_000 });
  await expect(rows(page), "실패했는데 옛 결과가 남아 있다").toHaveCount(0);
  await expect(answer(page)).toHaveCount(0);

  await page.unroute("**/api/v1/screener/run-advanced-stream");
  await alert.locator("button", { hasText: "다시 시도" }).click();
  await expect(answer(page)).toBeVisible({ timeout: 30_000 });
  await expect(alert).toHaveCount(0);
});

test("연습용 칩은 서버 게이트로만 · '일부만 평가했어요'는 서버 capped 로만(짝)", async ({ page }) => {
  const chip = (tone: string, text?: string) => page.locator(`.scr-answer .tx-chip[data-tone="${tone}"]`, text ? { hasText: text } : undefined);
  await patchStream(page, (r) => { r.capped = true; });
  await open(page);
  await settled(page);
  await expect(chip("practice")).toHaveText("연습용 시세");
  await expect(chip("assumed", "일부만 평가했어요")).toHaveCount(1);

  await page.unroute("**/api/v1/screener/run-advanced-stream");
  await patchStream(page, (r) => { r.capped = false; });
  await page.route("**/api/v1/macro/connection-status", (r) => r.fulfill({ json: { mock_allowed: false, real_mode: true, bok_configured: true, fred_configured: true } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await settled(page);
  await expect(chip("practice")).toHaveCount(0);
  await expect(chip("assumed", "일부만 평가했어요")).toHaveCount(0);
});

test("전문가 설정은 접혀 있다 — 게이트·조건식이 안 보이고, 펼치면 보인다 · 게이트는 꺼짐", async ({ page }) => {
  await open(page);
  const ex = page.locator('[data-act="expert"]');
  await expect(ex).toHaveCount(1);
  expect(await ex.evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
  await expect(page.locator('[data-act="gate"]')).toBeHidden();
  await ex.locator("summary").click();
  await expect(page.locator('[data-act="gate"]')).toBeVisible();
  await expect(page.locator('[data-act="gate"]')).not.toBeChecked();
});

test("행 → 시트: 그 행의 서버 값 · 기업 분석으로 · Esc 로 닫힘", async ({ page }) => {
  let result: Result | null = null;
  await patchStream(page, (r) => { result = r; });
  await open(page);
  await settled(page);
  const first = result!.items[0];
  await rows(page).first().click();
  const sheet = page.locator("dialog.tx-sheet[open]");
  await expect(sheet).toBeVisible();
  await expect(sheet.locator(".tx-sheet-title")).toHaveText(first.corp_name);
  await expect(sheet.locator(".tx-sheet-sub")).toContainText(first.stock_code);
  await expect(sheet.locator(".scr-sheet-fig", { has: page.locator("dt", { hasText: "현재가" }) }).locator("dd"))
    .toHaveText(`${first.current_price.toLocaleString("ko-KR")}원`);
  await expect(sheet.locator(".scr-sheet-fig", { has: page.locator("dt", { hasText: "종합점수" }) }).locator("dd"))
    .toHaveText(first.composite_score.toLocaleString("ko-KR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
  await expect(sheet.locator('a', { hasText: "기업 분석 열기" })).toHaveAttribute("href", `/insights?code=${first.stock_code}`);
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog.tx-sheet[open]")).toHaveCount(0);
});

const wipTickers = (page: Page) => page.evaluate(() => {
  const d = JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}") as { nodes?: { type: string; params?: { tickers?: string[] } }[] };
  return d.nodes?.find((n) => n.type === "universe")?.params?.tickers ?? null;
});

test("설계에 넣기: 표 위 10개 코드 그대로 캔버스 종목 고르기 노드로", async ({ page }) => {
  await open(page);
  await settled(page);
  const codes = (await rows(page).evaluateAll((trs) => trs.slice(0, 10).map((tr) => tr.getAttribute("data-code"))));
  expect(codes.every((c) => /^\d{6}$/.test(c ?? ""))).toBe(true);
  await page.locator(".scr-answer a", { hasText: "상위 10종목 설계에 넣기" }).click();
  await expect(page).toHaveURL(new RegExp(`/allocation\\?tickers=${codes.join(",")}$`));
  await expect(page.locator(".pg-file-note")).toContainText(`종목 찾기에서 가져온 ${codes.length}종목으로`, { timeout: 30_000 });
  await expect.poll(() => wipTickers(page)).toEqual(codes);
});

test("짝: 알 수 없는 코드는 빠지고 메모가 말한다 · 이름 확인이 실패하면 아무 코드도 싣지 않는다", async ({ page }) => {
  await page.goto("/allocation?tickers=000270,999999,abc", { waitUntil: "domcontentloaded" });
  // 명단에 없는 코드(999999)와 코드 모양이 아닌 값(abc)은 따로 센다 — 뭉뚱그리지 않는다
  await expect(page.locator(".pg-file-note")).toContainText("알 수 없는 코드 1개 · 코드 모양이 아닌 값 1개는 뺐어요", { timeout: 30_000 });
  await expect.poll(() => wipTickers(page)).toEqual(["000270"]);

  const p2 = await page.context().newPage();
  await p2.route("**/api/v1/allocation/resolve-names", (r) => r.fulfill({ status: 500, body: "x" }));
  await p2.goto("/allocation?tickers=000270,005380", { waitUntil: "domcontentloaded" });
  await expect(p2.locator(".pg-file-note")).toContainText("종목 이름을 확인하지 못해 가져오지 않았어요", { timeout: 30_000 });
  await expect(p2.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  const t = await wipTickers(p2);
  expect(t ?? [], "확인 못 한 코드를 싣지 않는다").not.toContain("005380");
});

test("판정 칩은 중립 — 등락·상태 색이 아니다", async ({ page }) => {
  await open(page);
  await settled(page);
  const chip = rows(page).first().locator(".tx-chip");
  await expect(chip).toHaveAttribute("data-tone", "plain");
});

for (const theme of ["light", "dark"] as const) {
  test(`종목 찾기 대비 AA (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    await settled(page);
    await page.locator('[data-act="expert"] summary').click();
    const r = await page.evaluate<AuditResult>(contrastAudit(".terminal-main"));
    expect(r.checked).toBeGreaterThan(30);
    expect(r.low, JSON.stringify(r.low.slice(0, 8))).toEqual([]);
  });
}

test("390 폭: 본문이 가로로 넘치지 않는다(표는 제 상자 안에서만 가로로 민다)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await settled(page);
  const over = await page.locator(".terminal-main").evaluate((m) => m.scrollWidth - m.clientWidth);
  expect(over).toBeLessThanOrEqual(0);
  await expect(answer(page)).toBeVisible();
});
