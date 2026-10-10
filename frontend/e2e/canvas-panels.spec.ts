import { test, expect, type Page, type Locator } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BQ Q1 · 떠 있는 패널 — 캔버스가 판 뒤까지 넓어지고, 왼쪽 목록·오른쪽 창은 그 위에 떠서 여닫는다.
 * 거는 것:
 *  · 캔버스는 몸통 전체 · 판은 그 위에 떠 있다 · 접으면 그 자리를 캔버스가 쓴다(짝: 범례·확대 단추가 그만큼 옮겨 간다)
 *  · 접기 단추 · 단축키 [ ] \ · 입력 중에는 글자(짝) · 노드를 고르면 오른쪽 창이 열린다 · × 뒤엔 다음 고를 때까지 닫힘 · 집중 모드에선 안 열림(짝)
 *  · 오른쪽 폭 끌기·키보드(300~600) · 이 브라우저에 저장·복원 · 망가진 저장값은 기본값(짝)
 *  · 떠 있는 것(범례·걸러 보기·확대 단추·미니맵·맞춰 보기 결과·우클릭 메뉴)은 열린 판과 겹치지 않는다
 *  · 도구줄 한 줄(1440·1280) · 1024 는 "더 보기"(짝) · 안내는 캔버스 아래 가운데 토스트 · 390px 가로 스크롤 0·아래 시트
 *  · 라이트·다크 AA
 */

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const palette = (page: Page) => page.locator(".pg-palette");
const side = (page: Page) => page.locator(".pg-side");

async function openCanvas(page: Page, clean = true) {
  // 첫 방문에만 비운다 — 새로고침 뒤 복원을 재는 테스트가 있다.
  if (clean) await page.addInitScript(() => {
    try { if (!sessionStorage.getItem("pg_panels_clean")) { localStorage.removeItem("alpha_pg_panels"); sessionStorage.setItem("pg_panels_clean", "1"); } } catch { /* */ }
  });
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
}
async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
}
type Box = { x: number; y: number; width: number; height: number };
const overlaps = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
const box = async (l: Locator) => (await l.boundingBox())!;
/** 판·노드·떠 있는 것에 가리지 않은 빈 캔버스 한 점(화면 좌표). */
async function emptyPoint(page: Page): Promise<{ x: number; y: number }> {
  return page.evaluate(() => {
    const r = document.querySelector(".react-flow")!.getBoundingClientRect();
    for (let y = r.top + 80; y < r.bottom - 80; y += 17)
      for (let x = r.left + 20; x < r.right - 20; x += 23) {
        const el = document.elementFromPoint(x, y);
        if (el?.classList.contains("react-flow__pane")) return { x, y };
      }
    throw new Error("빈 캔버스 자리가 없다");
  });
}
async function clickEmpty(page: Page) { const p = await emptyPoint(page); await page.mouse.click(p.x, p.y); }
/** 우클릭 메뉴로 지운다 — 되돌리기 안내(토스트)가 뜨는 길. */
async function removeViaMenu(page: Page, id: string) {
  await node(page, id).click({ button: "right" });
  await page.locator('.pg-ctx [data-action="remove"]').click();
}

test("떠 있는 패널(BQ Q1): 캔버스는 몸통 전체 · 판은 떠 있고 접으면 그 자리를 캔버스가 쓴다 — 넓이를 잰다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCanvas(page);
  await run(page);
  const body = await box(page.locator(".pg-body"));
  const cv = await box(page.locator(".pg-canvas"));
  expect(Math.abs(cv.width - body.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(cv.height - body.height)).toBeLessThanOrEqual(1);
  const pl = await box(palette(page));
  const sd = await box(side(page));
  expect(overlaps(pl, cv) && overlaps(sd, cv), "판이 캔버스 위에 떠 있다").toBe(true);
  expect(pl.x - cv.x, "가장자리 여백").toBeGreaterThanOrEqual(8);
  expect(cv.x + cv.width - (sd.x + sd.width)).toBeGreaterThanOrEqual(8);
  // 넓이(보고용 수치 + 하한): 캔버스 요소 넓이 / 창 넓이, 판에 가리지 않은 넓이 / 창 넓이.
  const vp = 1440 * 900;
  const canvasShare = (cv.width * cv.height) / vp;
  const openClear = ((sd.x - (pl.x + pl.width)) * cv.height) / vp;
  // 관문 레일(약 150px)이 알약이 되면(Q2) 75% 이상 — 그 하한은 Q2 테스트가 건다. 여기서는 판을 걷어 낸 만큼.
  expect(canvasShare, "캔버스 요소가 창의 70% 이상").toBeGreaterThanOrEqual(0.7);

  const legend0 = await box(page.locator(".pg-wire-legend"));
  const ctrl0 = await box(page.locator(".react-flow__controls"));
  const filt0 = await box(page.locator(".pg-filters-toggle"));
  expect(legend0.x).toBeGreaterThanOrEqual(pl.x + pl.width);
  expect(ctrl0.x).toBeGreaterThanOrEqual(pl.x + pl.width);
  expect(filt0.x + filt0.width).toBeLessThanOrEqual(sd.x);

  await page.locator('.pg-panel-toggle[data-panel="left"]').click();
  await expect(palette(page)).toBeHidden();
  await expect(page.locator(".pg-palette-fab")).toBeVisible();
  await page.locator('.pg-panel-toggle[data-panel="right"]').click();
  await expect(side(page)).toBeHidden();
  await expect(page.locator(".pg-side-fab")).toBeVisible();
  const legend1 = await box(page.locator(".pg-wire-legend"));
  const ctrl1 = await box(page.locator(".react-flow__controls"));
  const filt1 = await box(page.locator(".pg-filters-toggle"));
  expect(legend1.x, "접으면 범례가 왼쪽으로").toBeLessThan(legend0.x - 100);
  expect(ctrl1.x).toBeLessThan(ctrl0.x - 100);
  expect(filt1.x, "접으면 걸러 보기가 오른쪽으로").toBeGreaterThan(filt0.x + 100);
  expect(overlaps(legend1, await box(page.locator(".pg-palette-fab")))).toBe(false);
  expect(overlaps(filt1, await box(page.locator(".pg-side-fab")))).toBe(false);
  const fab = await box(page.locator(".pg-palette-fab"));
  const sfab = await box(page.locator(".pg-side-fab"));
  const closedClear = (cv.width * cv.height) / vp;
  test.info().annotations.push({ type: "넓이", description:
    `캔버스 요소 ${(canvasShare * 100).toFixed(1)}% · 판 열림 때 가리지 않은 넓이 ${(openClear * 100).toFixed(1)}% · 판 닫힘 ${(closedClear * 100).toFixed(1)}% (fab ${fab.width}·${sfab.width}px)` });
  console.log(test.info().annotations.at(-1)?.description);

  // 판 다시 열기 — fab 로
  await page.locator(".pg-palette-fab").click();
  await expect(palette(page)).toBeVisible();
  await expect(page.locator(".pg-palette-fab")).toBeHidden();
  await page.locator(".pg-side-fab").click();
  await expect(side(page)).toBeVisible();
});

test("여닫기 단축키(BQ Q1): [ 왼쪽 · ] 오른쪽 · \\ 집중 — 입력 칸에서는 글자(짝) · 단축키 한 장·명령 찾기에 있다", async ({ page }) => {
  await openCanvas(page);
  await clickEmpty(page);
  await page.keyboard.press("[");
  await expect(palette(page)).toBeHidden();
  await page.keyboard.press("[");
  await expect(palette(page)).toBeVisible();
  await page.keyboard.press("]");
  await expect(side(page)).toBeHidden();
  await page.keyboard.press("]");
  await expect(side(page)).toBeVisible();
  await page.keyboard.press("\\");
  await expect(palette(page)).toBeHidden();
  await expect(side(page)).toBeHidden();
  await page.keyboard.press("\\");
  await expect(palette(page)).toBeVisible();
  await expect(side(page)).toBeVisible();
  // 짝 — 입력 중에는 글자
  const q = palette(page).locator("input").first();
  await q.click();
  await page.keyboard.type("[]\\");
  await expect(q).toHaveValue("[]\\");
  await expect(palette(page)).toBeVisible();
  await expect(side(page)).toBeVisible();
  await q.fill("");
  await clickEmpty(page);
  await page.keyboard.press("?");
  const keys = page.locator(".pg-keys");
  await expect(keys).toContainText("왼쪽 목록 열고 닫기");
  await expect(keys).toContainText("오른쪽 창 열고 닫기");
  await expect(keys).toContainText("집중해서 보기");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+k");
  await page.keyboard.type("오른쪽 창");
  await expect(page.locator(".pg-cmd")).toContainText("오른쪽 창 닫기");
});

test("오른쪽 창(BQ Q1): 노드를 고르면 열리고 · × 뒤엔 다음 고를 때까지 닫힘 · 집중 모드에서는 고르기만(짝) · 머리에 고른 노드", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click();
  await expect(side(page).locator(".pg-side-head")).toContainText("비중 계산");
  await page.locator('.pg-panel-toggle[data-panel="right"]').click();
  await expect(side(page)).toBeHidden();
  await clickEmpty(page);                                           // 고른 것을 풀어도 닫힌 채
  await expect(side(page)).toBeHidden();
  await node(page, "risk").click();
  await expect(side(page)).toBeVisible();
  await expect(side(page).locator(".pg-side-head")).toContainText("흔들림 나눠 보기");
  // 짝 — 집중 모드(\)에서는 골라도 열리지 않는다
  await clickEmpty(page);
  await page.keyboard.press("\\");
  await node(page, "optimizer").click();
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--selected/);
  await expect(side(page)).toBeHidden();
});

test("폭 조절·저장(BQ Q1): 손잡이를 끌거나 ←→ 로 300~600 · 새로고침해도 남는다 · 망가진 저장값은 기본(짝)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCanvas(page);
  const w0 = (await box(side(page))).width;
  expect(w0).toBeGreaterThan(380);
  const h = page.locator(".pg-side-resize");
  await expect(h).toHaveAttribute("role", "separator");
  const hb = await box(h);
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(hb.x + hb.width / 2 - 100, hb.y + hb.height / 2, { steps: 8 });
  await page.mouse.up();
  const w1 = (await box(side(page))).width;
  expect(Math.abs(w1 - (w0 + 100))).toBeLessThanOrEqual(4);
  await h.focus();
  await page.keyboard.press("ArrowLeft");
  expect(Math.abs((await box(side(page))).width - (w1 + 16))).toBeLessThanOrEqual(2);
  for (let i = 0; i < 20; i++) await page.keyboard.press("ArrowLeft");
  expect((await box(side(page))).width).toBeLessThanOrEqual(601);
  await expect(h).toHaveAttribute("aria-valuenow", "600");
  for (let i = 0; i < 30; i++) await page.keyboard.press("ArrowRight");
  expect((await box(side(page))).width).toBeGreaterThanOrEqual(299);
  await expect(h).toHaveAttribute("aria-valuenow", "300");
  await page.keyboard.press("ArrowLeft");                          // 316
  await page.locator('.pg-panel-toggle[data-panel="left"]').click();
  await page.reload();
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(palette(page)).toBeHidden();
  expect(Math.abs((await box(side(page))).width - 316)).toBeLessThanOrEqual(2);
  // 짝 — 망가진 값은 기본값(열림·392)
  await page.evaluate(() => localStorage.setItem("alpha_pg_panels", "{not json"));
  await page.reload();
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(palette(page)).toBeVisible();
  expect(Math.abs((await box(side(page))).width - 392)).toBeLessThanOrEqual(2);
});

test("판을 비켜 선다(BQ Q1): 맞춰 보기의 노드 · 우클릭 메뉴 · 미니맵이 열린 판과 겹치지 않는다 — 고른 노드가 창 밑이면 옮긴다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCanvas(page);
  await run(page);
  const pl = await box(palette(page));
  const sd = await box(side(page));
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(400);
  for (const n of await page.locator(".react-flow__node").all()) {
    if (!(await n.isVisible())) continue;
    const b = await box(n);
    expect(overlaps(b, pl) || overlaps(b, sd), `${await n.getAttribute("data-id")} 가 판 밑`).toBe(false);
  }
  await page.locator('button[aria-label="미니맵"]').click();
  const mm = await box(page.locator(".pg-minimap"));
  expect(overlaps(mm, sd)).toBe(false);
  await page.locator('button[aria-label="미니맵"]').click();
  // 우클릭 — 창 바로 왼쪽을 눌러도 메뉴는 창 밑으로 들어가지 않는다
  const cvb = await box(page.locator(".react-flow"));
  await page.mouse.click(sd.x - 6, cvb.y + cvb.height - 120, { button: "right" });
  const menu = page.locator(".pg-ctx");
  await expect(menu).toBeVisible();
  expect(overlaps(await box(menu), sd)).toBe(false);
  await page.keyboard.press("Escape");
  // 고른 노드가 오른쪽 창 밑이면 보이게 옮긴다(짝: 이미 보이면 움직이지 않는다)
  const vis = await box(node(page, "estimate"));
  await node(page, "estimate").click();
  await page.waitForTimeout(350);
  expect(Math.abs((await box(node(page, "estimate"))).x - vis.x), "보이는 노드는 그대로").toBeLessThanOrEqual(1);
  await page.locator('.pg-panel-toggle[data-panel="right"]').click();
  const empty = await emptyPoint(page);
  const target = await box(node(page, "backtest"));
  await page.mouse.move(empty.x, empty.y); await page.mouse.down();
  await page.mouse.move(empty.x + (sd.x + 60 - target.x), empty.y, { steps: 8 }); await page.mouse.up();
  expect(overlaps(await box(node(page, "backtest")), sd), "끌어서 창 자리 밑으로 보냈다").toBe(true);
  await node(page, "backtest").click();
  await expect(side(page)).toBeVisible();
  await page.waitForTimeout(350);
  expect(overlaps(await box(node(page, "backtest")), await box(side(page))), "고르면 창 밖으로 옮긴다").toBe(false);
});

for (const [w, mode] of [[1440, "full"], [1280, "icons"], [1024, "more"]] as const) {
  test(`도구줄(BQ Q1): ${w}px — 한 줄 · 계산하기가 보인다 · ${mode === "full" ? "서랍 이름까지" : mode === "icons" ? "서랍은 아이콘(이름은 읽힘)" : "서랍은 더 보기로(짝)"}`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: 860 });
    await openCanvas(page);
    await run(page);
    const tb = await box(page.locator(".pg-toolbar"));
    expect(tb.height, "한 줄").toBeLessThanOrEqual(60);
    const runB = await box(page.locator(".pg-run"));
    expect(runB.x + runB.width).toBeLessThanOrEqual(tb.x + tb.width);
    expect(runB.y).toBeGreaterThanOrEqual(tb.y);
    // 결과 요약은 줄이지도 자르지도 않는다 — 실패 수·연습용 표시가 "…" 뒤로 숨으면 안 된다.
    const sum = page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)");
    expect(await sum.evaluate((e) => e.scrollWidth - e.clientWidth), "요약이 잘리지 않는다").toBeLessThanOrEqual(0);
    await expect(sum.locator(".pg-summary-practice")).toBeVisible();
    const drawer = page.locator(".pg-toolbar .pg-drawer-open").first();
    if (mode === "more") {
      await expect(page.locator(".pg-toolbar .pg-more-wrap > .pg-more")).toBeVisible();
      await expect(page.locator(".pg-toolbar .pg-drawers")).toBeHidden();
    } else {
      await expect(page.locator(".pg-toolbar .pg-more-wrap > .pg-more")).toBeHidden();
      await expect(drawer).toBeVisible();
      await expect(drawer).toHaveAccessibleName(/실행실/);
      const label = await box(drawer.locator(".pg-tl"));
      if (mode === "full") expect(label.width).toBeGreaterThan(20);
      else expect(label.width, "이름은 눈에 안 보이고 읽힌다").toBeLessThanOrEqual(1);
    }
  });
}

test("토스트(BQ Q1): 안내는 캔버스 아래 가운데에 떠 있고 판을 가리지 않는다 · 되돌리기 그대로 · 파일 안내도 토스트(닫기)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCanvas(page);
  await removeViaMenu(page, "views");
  const note = page.locator(".pg-toasts .pg-note");
  await expect(note).toBeVisible();
  const nb = await box(note);
  const cv = await box(page.locator(".pg-canvas"));
  const pl = await box(palette(page));
  const sd = await box(side(page));
  expect(nb.y, "캔버스 아래쪽").toBeGreaterThan(cv.y + cv.height * 0.7);
  expect(overlaps(nb, pl) || overlaps(nb, sd)).toBe(false);
  const mid = pl.x + pl.width + (sd.x - (pl.x + pl.width)) / 2;
  expect(Math.abs(nb.x + nb.width / 2 - mid), "열린 판 사이 가운데").toBeLessThanOrEqual(4);
  await expect(page.locator(".pg-toolbar ~ .pg-note, .pg-rail ~ .pg-note")).toHaveCount(0);   // 도구줄 아래 한 줄을 차지하지 않는다
  await note.locator(".pg-note-undo").click();
  await expect(node(page, "views")).toBeVisible();
  // 파일 안내 — 템플릿 불러오기도 토스트 · 닫기 단추로 닫는다(사람이 닫을 때까지 남는 안내)
  await page.locator(".pg-template").first().click();
  const fileNote = page.locator(".pg-toasts .pg-file-note");
  await expect(fileNote).toBeVisible();
  await fileNote.locator(".pg-toast-x").click();
  await expect(page.locator(".pg-file-note")).toHaveCount(0);
});

test("좁은 화면(BQ Q1): 390px — 가로 스크롤 0 · 목록은 겹쳐 뜨는 판 · 고르면 오른쪽 창은 아래 시트", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openCanvas(page);
  const sw = await page.evaluate(() => document.scrollingElement!.scrollWidth - window.innerWidth);
  expect(sw).toBeLessThanOrEqual(0);
  await expect(palette(page)).toBeHidden();                       // 좁으면 닫힌 채 시작
  await expect(side(page)).toBeHidden();
  await page.locator(".pg-palette-fab").click();
  await expect(palette(page)).toBeVisible();
  await page.locator('.pg-panel-toggle[data-panel="left"]').click();
  await expect(palette(page)).toBeHidden();
  await node(page, "universe").click();
  await expect(side(page)).toBeVisible();
  const sb = await box(side(page));
  const bw = (await box(page.locator(".pg-body"))).width;
  expect(sb.y, "아래 시트").toBeGreaterThan(844 * 0.3);
  expect(Math.abs(sb.width - bw), "몸통 폭 전체").toBeLessThanOrEqual(1);
  expect(await page.evaluate(() => document.scrollingElement!.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비(BQ Q1): ${scheme} — 떠 있는 판 머리·접기 단추·fab·토스트·손잡이 AA 미달 0`, async ({ page }) => {
    await openCanvas(page);
    await run(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await removeViaMenu(page, "views");
    await expect(page.locator(".pg-note")).toBeVisible();
    let audit = await page.evaluate<AuditResult>(contrastAudit(".pg-root"));
    expect(audit.checked).toBeGreaterThan(60);
    expect(audit.low, `${scheme} AA 미달(열림)`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
    await page.keyboard.press("\\");
    audit = await page.evaluate<AuditResult>(contrastAudit(".pg-root"));
    expect(audit.low, `${scheme} AA 미달(닫힘)`).toEqual([]);
  });
}

test("판 밑 노드(BQ Q1): 판 밑 노드로 스크롤·초점이 가도 화면이 옆으로 밀리지 않는다(overflow: clip)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await openCanvas(page);
  const tb0 = await box(page.locator(".pg-toolbar"));
  const sd = await box(side(page));
  // 노드 하나를 창 밑으로 끌어다 놓는다
  const empty = await emptyPoint(page);
  const b = await box(node(page, "backtest"));
  await page.mouse.move(empty.x, empty.y); await page.mouse.down();
  await page.mouse.move(empty.x + (sd.x + 80 - b.x), empty.y, { steps: 8 }); await page.mouse.up();
  expect(overlaps(await box(node(page, "backtest")), sd)).toBe(true);
  await node(page, "backtest").evaluate((el) => el.scrollIntoView({ block: "center", inline: "center" }));
  const tb1 = await box(page.locator(".pg-toolbar"));
  expect(tb1.x, "도구줄이 옆으로 밀리지 않았다").toBe(tb0.x);
  const scrolled = await page.evaluate(() => [...document.querySelectorAll(".terminal-main, .pg-root, .pg-body")].map((e) => e.scrollLeft + e.scrollTop));
  expect(scrolled.every((v) => v === 0)).toBe(true);
});

test("연습용 표시(BQ Q1): 결과 요약에 '연습용 데이터' — 연습용 결과가 하나도 없으면 없다(짝)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openCanvas(page);
  const mark = page.locator(".pg-summary .pg-summary-practice");
  await run(page);
  await expect(mark).toBeVisible();                                  // 좁고 창이 닫혀 있어도 누르지 않고 보인다
  // 짝 — 서버가 연습용이라 말하지 않은 결과면 표시하지 않는다(지어내지 않는다).
  await page.route("**/allocation/graph/run", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    for (const r of Object.values(body.nodes as Record<string, { lineage?: { practice?: boolean } }>)) if (r.lineage) r.lineage.practice = false;
    await route.fulfill({ response: res, json: body });
  });
  await run(page);
  await expect(page.locator(".pg-summary")).toContainText("완료");
  await expect(mark).toHaveCount(0);
});
