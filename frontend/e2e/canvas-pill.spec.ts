import { test, expect, type Page, type Locator } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BQ Q2 · 진행상황 알약 — 증거 관문 레일이 캔버스 위 가운데 떠 있는 알약이 된다.
 * 거는 것:
 *  · 알약 = 서버 관문 요약 그대로("관문 {확인}/{전체} 확인") + 관문 8개 점(서버 상태 그대로 · 모양도 다르다) · 계산 전이면 "계산하면 관문을 확인해요"
 *  · 기본 접힘(짝: 레일이 보이지 않는다) · 누르면 지금의 레일 전체가 카드로 · Esc·바깥 누르면 접힘 · 펼침 상태는 이 브라우저에
 *  · 새로 막힘·실패가 생기면 한 번 강조(짝: 같은 결과를 다시 계산하면 없음 · 감속 모션이면 없음)
 *  · 알약은 열린 판 사이 가운데 · 선 범례·걸러 보기와 겹치지 않는다(1280·1440) · 캔버스가 창의 75% 이상(1440×900)
 *  · 라이트·다크 AA
 */

const pill = (page: Page) => page.locator(".pg-rail-pill");
type Box = { x: number; y: number; width: number; height: number };
const overlaps = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
const box = async (l: Locator) => (await l.boundingBox())!;
type Gates = { gates: { key: string; state: string }[]; summary: { confirmed: number; total: number } };

/** 강조는 1.4초 뒤 스스로 꺼진다 — "없다" 는 기다려 맞추는 단언(not.toHave…)으로는 못 잰다. 1초 동안 0.1초마다 본 값. */
async function alertSamples(page: Page): Promise<(string | null)[]> {
  const out: (string | null)[] = [];
  for (let i = 0; i < 10; i++) { out.push(await pill(page).getAttribute("data-alert")); await page.waitForTimeout(100); }
  return out;
}

async function openCanvas(page: Page) {
  await page.addInitScript(() => {
    try { if (!sessionStorage.getItem("pg_pill_clean")) { localStorage.removeItem("alpha_pg_panels"); localStorage.removeItem("alpha_pg_rail"); sessionStorage.setItem("pg_pill_clean", "1"); } } catch { /* */ }
  });
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
}
async function run(page: Page): Promise<Gates> {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = await (await resp).json();
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return body.gates as Gates;
}

test("알약(BQ Q2): 계산 전 문구 · 기본 접힘(짝) · 서버 요약·점 그대로 · 펼치면 레일 · Esc·바깥으로 접힘 · 새로고침해도 펼침 유지", async ({ page }) => {
  await openCanvas(page);
  await expect(pill(page)).toContainText("계산하면 관문을 확인해요");
  await expect(pill(page).locator(".pg-rail-dot")).toHaveCount(8);
  await expect(pill(page)).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".pg-rail")).toBeHidden();                  // 짝 — 기본은 접힘
  const g = await run(page);
  await expect(pill(page)).toContainText(`관문 ${g.summary.confirmed}/${g.summary.total} 확인`);
  for (const x of g.gates) await expect(pill(page).locator(`.pg-rail-dot[data-gate="${x.key}"]`), x.key).toHaveClass(new RegExp(`pg-stn--${x.state}\\b`));
  // 모양 — 확인·실패·건너뜀 점은 색만이 아니라 테두리 모양도 다르다
  const styleOf = (k: string) => pill(page).locator(`.pg-rail-dot[data-gate="${k}"] .pg-stn-dot`).evaluate((e) => getComputedStyle(e).borderStyle + "|" + getComputedStyle(e).backgroundImage);
  const skipped = g.gates.find((x) => x.state === "skipped");
  const confirmed = g.gates.find((x) => x.state === "confirmed");
  if (skipped && confirmed) expect(await styleOf(skipped.key)).not.toEqual(await styleOf(confirmed.key));

  await pill(page).click();
  await expect(pill(page)).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".pg-rail")).toBeVisible();
  await expect(page.locator(".pg-rail .pg-stn")).toHaveCount(8);
  await page.keyboard.press("Escape");
  await expect(page.locator(".pg-rail")).toBeHidden();
  await pill(page).click();
  await expect(page.locator(".pg-rail")).toBeVisible();
  // 관문 하나를 열면 Esc 는 그 설명부터 닫는다(카드는 남음)
  await page.locator('.pg-rail .pg-stn[data-gate="cost"] button').click();
  await expect(page.locator(".pg-gate-pop")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".pg-gate-pop")).toHaveCount(0);
  await expect(page.locator(".pg-rail")).toBeVisible();
  await page.reload();
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(pill(page)).toHaveAttribute("aria-expanded", "true");       // 펼침 상태는 이 브라우저에 남는다
  // 바깥(빈 캔버스)을 누르면 접힘
  const cv = await box(page.locator(".react-flow"));
  const p = await page.evaluate(({ x0, y0, w, h }) => {
    for (let y = y0 + h - 120; y > y0 + 200; y -= 17) for (let x = x0 + 20; x < x0 + w - 20; x += 23) {
      const el = document.elementFromPoint(x, y); if (el?.classList.contains("react-flow__pane")) return { x, y };
    }
    return null;
  }, { x0: cv.x, y0: cv.y, w: cv.width, h: cv.height });
  await page.mouse.click(p!.x, p!.y);
  await expect(page.locator(".pg-rail")).toBeHidden();
});

test("알약 강조(BQ Q2): 새로 실패한 관문이 생기면 한 번 · 같은 결과를 다시 계산하면 없음(짝) · 감속 모션이면 없음(짝)", async ({ page }) => {
  await openCanvas(page);
  const g = await run(page);
  const bad = g.gates.some((x) => x.state === "failed");
  test.skip(!bad, "기본 흐름에 실패 관문이 없다");
  await expect(pill(page)).toHaveAttribute("data-alert", "new");
  await page.waitForTimeout(1600);
  await expect(pill(page)).not.toHaveAttribute("data-alert", "new");
  await run(page);                                                     // 같은 결과 — 새로 생긴 실패 없음
  expect(await alertSamples(page), "같은 결과면 강조 없음").not.toContain("new");
  // 감속 모션 — 강조하지 않는다(처음 계산에서도)
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.evaluate(() => sessionStorage.removeItem("alpha_pg_wip"));
  await page.reload();
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await run(page);
  expect(await alertSamples(page), "감속 모션이면 강조 없음").not.toContain("new");
});

for (const w of [1440, 1280] as const) {
  test(`알약 자리(BQ Q2): ${w}px — 열린 판 사이 가운데 · 선 범례·걸러 보기와 안 겹침 · 접으면 가운데가 옮겨 감`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: 900 });
    await openCanvas(page);
    await run(page);
    const pb = await box(pill(page));
    const pl = await box(page.locator(".pg-palette"));
    const sd = await box(page.locator(".pg-side"));
    const mid = pl.x + pl.width + (sd.x - (pl.x + pl.width)) / 2;
    expect(Math.abs(pb.x + pb.width / 2 - mid)).toBeLessThanOrEqual(4);
    for (const sel of [".pg-wire-legend", ".pg-filters-toggle", ".pg-palette", ".pg-side"])
      expect(overlaps(pb, await box(page.locator(sel))), sel).toBe(false);
    // 펼친 카드도 판과 겹치지 않는다
    await pill(page).click();
    const card = await box(page.locator(".pg-rail"));
    expect(overlaps(card, pl) || overlaps(card, sd)).toBe(false);
    await page.keyboard.press("Escape");
    await page.keyboard.press("\\");
    const pb2 = await box(pill(page));
    const cv = await box(page.locator(".pg-canvas"));
    expect(Math.abs(pb2.x + pb2.width / 2 - (cv.x + cv.width / 2)), "집중 모드면 캔버스 가운데").toBeLessThanOrEqual(4);
  });
}

test("넓이(BQ Q2): 1440×900 에서 캔버스가 창의 75% 이상 — 레일 자리가 캔버스로 돌아왔다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCanvas(page);
  await run(page);
  const cv = await box(page.locator(".pg-canvas"));
  const share = (cv.width * cv.height) / (1440 * 900);
  console.log(`캔버스 요소 ${(share * 100).toFixed(1)}%`);
  expect(share).toBeGreaterThanOrEqual(0.75);
  await expect(page.locator(".pg-toolbar + .pg-rail, .pg-toolbar + section.pg-rail")).toHaveCount(0);   // 레일이 한 행을 차지하지 않는다
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비(BQ Q2): ${scheme} — 알약 · 펼친 레일 카드 AA 미달 0`, async ({ page }) => {
    await openCanvas(page);
    await run(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    let audit = await page.evaluate<AuditResult>(contrastAudit(".pg-rail-wrap"));
    expect(audit.checked).toBeGreaterThan(0);
    expect(audit.low, `${scheme} 알약`).toEqual([]);
    await pill(page).click();
    await page.locator('.pg-rail .pg-stn[data-gate="cost"] button').click();
    audit = await page.evaluate<AuditResult>(contrastAudit(".pg-rail-wrap"));
    expect(audit.checked).toBeGreaterThan(20);
    expect(audit.low, `${scheme} 카드`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}

test("알약과 원인 배너(BQ Q2): 원인 따라가기 배너·들어간 상자 빵 부스러기는 알약·범례·걸러 보기와 겹치지 않는다(1280·1440)", async ({ page }) => {
  for (const w of [1280, 1440]) {
    await page.setViewportSize({ width: w, height: 900 });
    await openCanvas(page);
    await page.locator('.pg-node[data-node-id="universe"]').click();
    await page.locator('.pg-tab[data-tab="settings"]').click();
    const tickers = page.locator('.pg-basic-field[data-field="tickers"] input');
    await tickers.fill("005930");
    await tickers.press("Enter");
    await run(page);
    await page.locator('.pg-node[data-node-id="risk"] .pg-cause-btn').click({ force: true });
    const banner = page.locator(".pg-cause-banner");
    await expect(banner).toBeVisible();
    const bb = await box(banner);
    for (const sel of [".pg-rail-pill", ".pg-wire-legend", ".pg-filters-toggle"])
      expect(overlaps(bb, await box(page.locator(sel))), `${w} ${sel}`).toBe(false);
    await page.locator(".pg-cause-root-btn").first().click({ trial: true, timeout: 3_000 });
  }
});

// BQ 마감 — 마지막 스크린샷 점검에서 찾은 것: 긴 요약(전략 둘)에서 1440 도구줄이 두 줄 · 1024 에서 선 범례가 걸러 보기와 겹침·안내가 창 밑으로 잘림 ·
// 390 에서 도구줄 단추·범례가 화면 밖(잘려서 누를 수 없음) · 아래 시트 머리 닫기 단추.
test("마감(BQ): 전략 둘(긴 요약)에서도 1440 도구줄 한 줄 · 계산하기가 첫 줄", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCanvas(page);
  await page.locator(".pg-strat-add").click();
  await page.locator('.pg-strat-item[data-source="tpl:stress"]').click();
  await run(page);
  await expect(page.locator(".pg-summary").first()).toContainText("완료 1");     // 두 자리 수
  const tb = await box(page.locator(".pg-toolbar"));
  expect(tb.height, "한 줄").toBeLessThanOrEqual(60);
});

test("마감(BQ): 1024 — 선 범례·걸러 보기·알약이 서로 안 겹치고 판 안에 · 안내가 판 밑으로 잘리지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await openCanvas(page);
  await run(page);
  const lg = await box(page.locator(".pg-wire-legend"));
  const ft = await box(page.locator(".pg-filters-toggle"));
  const pb = await box(pill(page));
  const pl = await box(page.locator(".pg-palette"));
  const sd = await box(page.locator(".pg-side"));
  expect(overlaps(lg, ft), "범례 × 걸러 보기").toBe(false);
  expect(overlaps(lg, pb) || overlaps(ft, pb), "알약").toBe(false);
  for (const b of [lg, ft, pb]) expect(overlaps(b, pl) || overlaps(b, sd), "판").toBe(false);
  const hint = await box(page.locator(".pg-hint, .pg-welcome").first());
  expect(overlaps(hint, sd) || overlaps(hint, pl), "안내가 판 밑으로").toBe(false);
});

test("마감(BQ): 390 — 도구줄 단추·범례·시트 닫기 단추가 모두 화면 안(누를 수 있다)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openCanvas(page);
  await run(page);
  const out = await page.evaluate(() => [...document.querySelectorAll(".pg-toolbar button, .pg-toolbar input, .pg-wire-legend")]
    .filter((e) => (e as HTMLElement).offsetParent !== null && e.getBoundingClientRect().width > 2)
    .filter((e) => { const r = e.getBoundingClientRect(); return r.right > innerWidth + 0.5 || r.left < -0.5; })
    .map((e) => (e.getAttribute("aria-label") || e.className).toString().slice(0, 40)));
  expect(out, "화면 밖").toEqual([]);
  // 범례 — 걸러 보기·알약과 겹치지 않고, 각 칸은 한 줄(글자 단위로 꺾이지 않는다)
  const lg = await box(page.locator(".pg-wire-legend"));
  expect(overlaps(lg, await box(page.locator(".pg-filters-toggle"))) || overlaps(lg, await box(pill(page)))).toBe(false);
  const keyH = await page.locator(".pg-wire-key").evaluateAll((els) => Math.max(...els.map((e) => e.getBoundingClientRect().height)));
  expect(keyH, "범례 칸이 한 줄").toBeLessThan(24);
  await page.locator('.pg-node[data-node-id="optimizer"]').click();
  const x = await box(page.locator('.pg-side .pg-panel-toggle[data-panel="right"]'));
  expect(x.x + x.width).toBeLessThanOrEqual(390);
  await page.locator('.pg-side .pg-panel-toggle[data-panel="right"]').click({ trial: true, timeout: 3_000 });
});
