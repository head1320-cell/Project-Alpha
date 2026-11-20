import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, type Page } from "./fixtures";

// ════════════════════════════════════════════════════════════════════════════
// 합성 알림의 고정 자리 — 백테스트 › 분봉 규칙 `/backtest/intraday` (★실제 서버★)
// ────────────────────────────────────────────────────────────────────────────
// 알림(`.itd-banner`)은 position: sticky 다. 페이지는 셸 `.terminal-main`(패딩 40px · 640px 이하 20px) 안에서 구르고, Chrome 은 sticky 를
// 스크롤 칸의 패딩 안쪽에서 잰다. 그래서 `top: 8px` 이던 알림은 칸 맨 위에서 48px(좁은 창 24px) 아래에 붙었고, 그 투명한 띠로 굴러 올라간
// 입력 칸 · 절 상자가 알림 위에 비쳤다(1200 × 900 에서 칸 위 64 → 알림 위 112 — 잰 값).
// 거는 것:
//  · 굴려 고정되면 칸 맨 위 → 알림이 8px 이하(640px 이하 4px 이하) · 0 아래로는 내려가지 않는다(머리 줄 밑으로 숨지 않는다)
//  · 그 띠와 알림의 둥근 귀퉁이 뒤는 페이지 바탕색이다(픽셀) · 눌림도 알림이 받는다 — 표지 색(자홍)을 칠한 절이 바로 뒤에 있는데도
//  · 짝: 알림을 숨기면 같은 점에 그 절이 보인다(진공 방지) · 알림 아래로는 절이 그대로 보이고 눌린다 · 알림의 테두리와 면은 그대로 그려진다
//  · 고정 전 배치는 그대로 — 전환 줄 → 알림 16px(블록 흐름) · 28px(두 칸 · 판 탭 — flex) · 알림 → 다음 칸 12px · 띠가 전환 줄을 덮지 않는다
//  · 두 칸 · 판 탭은 셸이 구르지 않는다(고정이 걸릴 수 없다) · 결과 칸을 굴려도 알림은 그 자리
//  · 390px: 가로 넘침은 셸의 구르는 칸에서 잰다(`.terminal-root` 가 overflow hidden 이라 문서 기준으로는 칸 안 넘침이 보이지 않는다 — 짝으로 확인)
// 기대색은 박지 않고 그때의 계산 스타일에서 읽는다 — 띠 색을 한 테마의 값으로 박으면 다른 테마에서 죽는다.
// 데이터는 다른 분봉 스펙과 같은 고정물(seed_bars.py) — 합성 사흘 005930 · 000660(사용자 재현과 같은 입력).
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";
const HERE = "/backtest/intraday";
const SYNTH = { tickers: "005930, 000660", from: "2026-04-01", to: "2026-04-03" };
const TITLE = "합성 분봉: 장치 확인용이며 예측력·수익의 증거가 아닙니다.";
const WITNESS: RGB = [255, 0, 255];          // 띠 뒤 절에 칠하는 표지 — 절(#fff · #1a2029)과 바탕(#f2f4f6 · #0e131b)의 차는 9~14단계뿐이다
const TOL = 8;                               // 채널마다 허용 — 알림 그림자(8% · 18px · +6px)가 띠를 물들이는 양보다 크고 표지와의 차보다 훨씬 작다
const UNDER = "data-e2e-under";

type RGB = [number, number, number];
type Pt = { x: number; y: number };
type Case = { name: string; viewport: { width: number; height: number }; theme: "light" | "dark"; ws: boolean; gap: number };

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

async function open(page: Page, c: Pick<Case, "viewport" | "theme" | "ws">): Promise<void> {
  await page.setViewportSize(c.viewport);
  await page.addInitScript(({ theme, ws }) => {
    try {
      localStorage.setItem("alpha_theme", theme);
      if (ws) localStorage.setItem("ws.intraday.on", "1");          // 판 배치 켬(useWorkspace — "1" 일 때만)
    } catch { /* */ }
  }, { theme: c.theme, ws: c.ws });
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await expect(page.locator("html")).toHaveClass(c.theme === "dark" ? /\bdark\b/ : /^(?!.*\bdark\b).*$/);
}

/** 사용자 재현 그대로 — 종목 · 기간만 넣고 실행한다. 합성 분봉이라 알림이 선다. */
async function runSynth(page: Page): Promise<void> {
  await page.locator(".itd-tickers").fill(SYNTH.tickers);
  await page.locator(".itd-from").fill(SYNTH.from);
  await page.locator(".itd-to").fill(SYNTH.to);
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/simulate") && r.method() === "POST");
  await page.locator(".itd-run").click();
  await sent;
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".itd-banner .tx-notice-t")).toHaveText(TITLE);
  await page.evaluate(async () => { await document.fonts.ready; });
}

const frame = (page: Page) => page.evaluate(() => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r()))));
const scrollMain = async (page: Page, to: { top?: number; by?: number }) => {
  await page.locator(".terminal-main").evaluate((el, t) => {
    if (t.by !== undefined) el.scrollBy({ top: t.by, behavior: "instant" });
    else el.scrollTo({ top: t.top ?? 0, behavior: "instant" });
  }, to);
  await frame(page);
};

/** 구르는 칸(패딩 상자의 위 = 보이는 맨 위)과 알림의 자리. */
type Geo = { mainTop: number; mainLeft: number; scrollTop: number; nTop: number; nBottom: number; nLeft: number; nRight: number };
const geo = (page: Page): Promise<Geo> => page.evaluate(() => {
  const m = document.querySelector<HTMLElement>(".terminal-main")!;
  const mr = m.getBoundingClientRect();
  const n = document.querySelector(".itd-banner .tx-notice")!.getBoundingClientRect();
  return { mainTop: mr.top + m.clientTop, mainLeft: mr.left + m.clientLeft, scrollTop: m.scrollTop, nTop: n.top, nBottom: n.bottom, nLeft: n.left, nRight: n.right };
});

/**
 * 고정 전(맨 위) — 전환 줄 → 알림 `above` px · 알림 → 다음 칸 12px · 전환 줄 아래 선 줄은 전환 줄이 받는다(띠가 덮지 않는다).
 * 값은 고치기 전 빌드에서 잰 것(블록 흐름 16 = 전환 줄 아래 16 과 `.tj > * + *` 12 가 겹친 것 · flex 28 = 16 + 12) — 고쳐도 한 픽셀도 움직이지 않아야 한다.
 */
async function unstuck(page: Page, above: number): Promise<void> {
  await scrollMain(page, { top: 0 });
  const u = await page.evaluate(() => {
    const sub = document.querySelector(".itd > .tx-subnav")!.getBoundingClientRect();
    const banner = document.querySelector(".itd-banner")!;
    const n = banner.querySelector(".tx-notice")!.getBoundingClientRect();
    const next = banner.nextElementSibling!;
    const y = sub.bottom - 0.5;
    const hits = [n.left + 3, (n.left + n.right) / 2, n.right - 3].map((x) => {
      const el = document.elementFromPoint(x, y);
      return { sub: !!el?.closest(".tx-subnav"), banner: !!el?.closest(".itd-banner") };
    });
    return { above: n.top - sub.bottom, below: next.getBoundingClientRect().top - n.bottom, next: String(next.className), hits };
  });
  expect(Math.abs(u.above - above), `전환 줄 → 알림(고정 전) ${JSON.stringify(u)}`).toBeLessThan(0.5);
  expect(Math.abs(u.below - 12), `알림 → 다음 칸(고정 전) ${JSON.stringify(u)}`).toBeLessThan(0.5);
  expect(u.hits.every((h) => h.sub && !h.banner), `전환 줄 아래 선 줄을 전환 줄이 받는다 ${JSON.stringify(u.hits)}`).toBe(true);
}

/**
 * 1400px(사용자 재현) 근처의 절 하나를 골라 그 위가 칸 위 60px 위에 오게 굴린다 — 띠 · 알림 · 알림 아래 30px 뒤에 늘 그 절이 있다
 * (띠가 우연히 절 사이 빈 바탕에 놓여 공허하게 통과하지 않게). 절의 높이는 그 뒤 100px 더 굴러도 고치기 전의 띠(48px) · 알림 · 아래 30px 를
 * 다 덮을 만큼이어야 한다. 고른 절에 표식을 단다.
 */
async function stickOverSection(page: Page): Promise<void> {
  const target = await page.evaluate(([attr]) => {
    const m = document.querySelector<HTMLElement>(".terminal-main")!;
    const top = m.getBoundingClientRect().top + m.clientTop;
    const banner = document.querySelector(".itd-banner")!;
    const need = 160 + 48 + banner.getBoundingClientRect().height + 30 + 10;
    const secs = [...document.querySelectorAll<HTMLElement>(".itd .tx-sec")].filter((s) =>
      (banner.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0 && s.getBoundingClientRect().height >= need);
    if (!secs.length) return null;
    const at = (s: HTMLElement) => s.getBoundingClientRect().top - top + m.scrollTop;   // 칸 안에서의 자리
    const pick = secs.reduce((a, b) => (Math.abs(at(b) - 1400) < Math.abs(at(a) - 1400) ? b : a));
    pick.setAttribute(attr, "");
    return at(pick) + 60;
  }, [UNDER]);
  expect(target, "띠 뒤에 둘 만큼 높은 절").not.toBeNull();
  await scrollMain(page, { top: target! });
}

const underTop = (page: Page) => page.locator(`[${UNDER}]`).evaluate((el) => el.getBoundingClientRect().top);

/** 스크린샷(PNG)을 페이지 안에서 풀어 점마다 색을 읽는다(`canvas-png.spec.ts` 의 방법) — 점은 화면 좌표, origin 은 잘라 찍은 왼쪽 위. */
async function colours(page: Page, png: Buffer, origin: Pt, pts: Pt[]): Promise<RGB[]> {
  return page.evaluate(async ({ b64, origin, pts }) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const g = c.getContext("2d", { willReadFrequently: true })!;
    g.drawImage(img, 0, 0);
    return pts.map((p) => {
      const d = g.getImageData(Math.floor(p.x - origin.x), Math.floor(p.y - origin.y), 1, 1).data;
      return [d[0], d[1], d[2]] as [number, number, number];
    });
  }, { b64: png.toString("base64"), origin, pts });
}

const rgbOf = (css: string): RGB => {
  const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(css);
  if (!m) throw new Error(`색을 읽지 못함: ${css}`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
};
const off = (a: RGB, b: RGB) => Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]), Math.abs(a[2] - b[2]));
/** 기대색에서 TOL 넘게 벗어난 점(처음 몇 개 · 개수). */
function misses(pts: Pt[], got: RGB[], want: RGB): { n: number; first: string[] } {
  const bad = got.map((c, i) => ({ c, p: pts[i] })).filter(({ c }) => off(c, want) > TOL);
  return { n: bad.length, first: bad.slice(0, 4).map(({ c, p }) => `(${p.x.toFixed(1)},${p.y.toFixed(1)})=${c.join(",")}`) };
}

const STUCK: Case[] = [
  { name: "1200 × 900 한 열 · 라이트", viewport: { width: 1200, height: 900 }, theme: "light", ws: false, gap: 8 },
  { name: "1200 × 900 한 열 · 다크", viewport: { width: 1200, height: 900 }, theme: "dark", ws: false, gap: 8 },
  { name: "1200 × 900 판 쌓기", viewport: { width: 1200, height: 900 }, theme: "light", ws: true, gap: 8 },
  { name: "390 × 844", viewport: { width: 390, height: 844 }, theme: "light", ws: false, gap: 4 },
];

for (const c of STUCK) {
  test(`${c.name}: 굴려 고정되면 칸 맨 위 → 알림 ${c.gap}px 이하 · 그 띠와 귀퉁이 뒤는 바탕색이고 알림이 눌림을 받는다(짝: 알림을 숨기면 뒤의 절이 보인다)`, async ({ page }) => {
    await open(page, c);
    await expect(page.locator(".itd")).not.toHaveAttribute("data-split", /.*/);
    if (c.ws) await expect(page.locator(".itd")).toHaveAttribute("data-ws", "stack");
    else await expect(page.locator(".itd")).not.toHaveAttribute("data-ws", /.*/);
    await runSynth(page);

    // ① 고정 전 배치는 그대로(블록 흐름)
    await unstuck(page, 16);

    // ② 굴려 고정 — 더 굴리면 알림은 그 자리, 절만 올라간다(고정됐고 내용이 그 밑으로 지나간다)
    await stickOverSection(page);
    const g0 = await geo(page), s0 = await underTop(page);
    await scrollMain(page, { by: 100 });
    const g = await geo(page), s1 = await underTop(page);
    expect(g.scrollTop - g0.scrollTop, "100px 더 굴렀다").toBeCloseTo(100, 0);
    expect(Math.abs(g.nTop - g0.nTop), `알림은 그 자리 ${JSON.stringify({ g0, g })}`).toBeLessThan(0.5);
    expect(Math.abs(s0 - s1 - 100), "절은 100px 올라갔다").toBeLessThan(0.5);

    // ③ 자리 — 칸 맨 위 → 알림(고치기 전에는 48 · 390 에서 24)
    const gap = g.nTop - g.mainTop;
    expect(gap, `칸 맨 위 → 알림(고정) ${JSON.stringify(g)}`).toBeLessThanOrEqual(c.gap + 0.5);
    expect(gap, `알림이 칸 위로 숨지 않는다 ${JSON.stringify(g)}`).toBeGreaterThanOrEqual(-0.5);

    // 띠(칸 맨 위 ~ 알림)와 둥근 귀퉁이의 점들
    const xs = [g.nLeft + 3, (g.nLeft + g.nRight) / 2, g.nRight - 3];
    const ys = gap >= 3 ? [g.mainTop + 1, g.nTop - 2] : gap >= 1.5 ? [g.mainTop + 0.75] : [];
    const band: Pt[] = ys.flatMap((y) => xs.map((x) => ({ x, y })));
    const notch: Pt[] = [{ x: g.nLeft + 1.5, y: g.nTop + 1.5 }, { x: g.nRight - 1.5, y: g.nTop + 1.5 }];
    const below: Pt = { x: g.nLeft + 3, y: g.nBottom + 30 };

    // ④ 진공 방지 — 그 점들 뒤에 고른 절이 있다 · ⑤ 눌림은 알림이 받는다(가려진 칸이 눌리지 않는다) · 짝: 알림 아래는 절이 받는다
    const probe = await page.evaluate(({ pts, below, attr }) => ({
      behind: pts.map(({ x, y }) => document.elementsFromPoint(x, y).some((el) => el.closest(`[${attr}]`) !== null)),
      hit: pts.map(({ x, y }) => !!document.elementFromPoint(x, y)?.closest(".itd-banner")),
      below: !!document.elementFromPoint(below.x, below.y)?.closest(`[${attr}]`),
    }), { pts: [...band, ...notch], below, attr: UNDER });
    expect(probe.behind.every(Boolean), `띠 · 귀퉁이 뒤에 고른 절이 있다(진공 방지) ${JSON.stringify(probe.behind)}`).toBe(true);
    expect(probe.hit.every(Boolean), `띠 · 귀퉁이의 눌림은 알림이 받는다 ${JSON.stringify(probe.hit)}`).toBe(true);
    expect(probe.below, "알림 아래의 절은 그대로 눌린다").toBe(true);

    // ⑥ 표지 색 · ⑦ 스크린샷 둘(그대로 · 알림만 숨김 — 배치 불변)
    const want = await page.evaluate(() => {
      const n = document.querySelector(".itd-banner .tx-notice")!;
      const cs = getComputedStyle(n);
      return { bg: getComputedStyle(document.querySelector(".terminal-main")!).backgroundColor, face: cs.backgroundColor, shadow: cs.boxShadow };
    });
    const bg = rgbOf(want.bg), face = rgbOf(want.face), ring = rgbOf(want.shadow);
    await page.locator(`[${UNDER}]`).evaluate((el) => { (el as HTMLElement).style.setProperty("background-color", "rgb(255, 0, 255)", "important"); });
    await page.mouse.move(c.viewport.width - 2, c.viewport.height - 2);               // 마우스를 잰 자리 밖으로(누름 뒤 hover 가 그림에 끼지 않게)
    const origin = { x: Math.floor(g.mainLeft), y: Math.floor(g.mainTop) };
    const clip = { ...origin, width: Math.ceil(g.nRight) - origin.x, height: Math.ceil(g.nBottom + 40) - origin.y };
    const shot = () => page.screenshot({ clip, scale: "css", animations: "disabled", caret: "hide" });
    const a = await shot();
    await page.locator(".itd-banner").evaluate((el) => { (el as HTMLElement).style.setProperty("visibility", "hidden"); });
    const b = await shot();
    await page.locator(".itd-banner").evaluate((el) => { (el as HTMLElement).style.removeProperty("visibility"); });

    // ⑧ 픽셀 — 띠의 모든 줄(알림 테두리 줄 앞까지 · 4px 간격) · 귀퉁이 = 바탕 · 테두리 줄 = 테두리 · 알림 면 = 면 · 알림 아래 = 표지
    const rows: number[] = [];
    for (let y = g.mainTop + 0.5; y < g.nTop - 1; y += 1) rows.push(y);
    const cols: number[] = [];
    for (let x = g.nLeft + 1.5; x < g.nRight - 1; x += 4) cols.push(x);
    const bandPx: Pt[] = rows.flatMap((y) => cols.map((x) => ({ x, y })));
    const gutter: Pt = { x: g.mainLeft + 4, y: g.mainTop + 2 };                     // 셸 패딩 열 — 페이지 바탕 그대로인 자리
    const ringPt: Pt[] = gap >= 2 ? [{ x: (g.nLeft + g.nRight) / 2, y: g.nTop - 0.5 }] : [];
    const facePt: Pt = { x: g.nLeft + 6, y: (g.nTop + g.nBottom) / 2 };
    const A = await colours(page, a, origin, [gutter, ...bandPx, ...notch, ...ringPt, facePt, below]);
    const [gutterA] = A;
    const bandA = A.slice(1, 1 + bandPx.length);
    const notchA = A.slice(1 + bandPx.length, 3 + bandPx.length);
    const ringA = A.slice(3 + bandPx.length, 3 + bandPx.length + ringPt.length);
    const [faceA, belowA] = A.slice(-2);
    expect(off(gutterA, bg), `셸 패딩 열의 픽셀 = 계산한 바탕색 ${gutterA} vs ${bg}`).toBeLessThanOrEqual(TOL);
    const mb = misses(bandPx, bandA, bg);
    expect(mb.n, `띠의 픽셀 ${bandPx.length}개 가운데 바탕색이 아닌 것 — ${mb.first.join(" ")} (바탕 ${bg})`).toBe(0);
    const mn = misses(notch, notchA, bg);
    expect(mn.n, `둥근 귀퉁이 뒤가 바탕색이 아니다 — ${mn.first.join(" ")} (바탕 ${bg})`).toBe(0);
    for (const r of ringA) expect(off(r, ring), `알림 윗 테두리 ${r} vs ${ring}`).toBeLessThanOrEqual(TOL);
    expect(off(faceA, face), `알림 면 ${faceA} vs ${face}`).toBeLessThanOrEqual(TOL);
    expect(off(belowA, WITNESS), `알림 아래로는 절(표지 색)이 보인다 ${belowA}`).toBeLessThanOrEqual(TOL);

    // 짝 — 알림을 숨기면 띠 · 귀퉁이 자리에 뒤의 절이 보인다(이 시험이 빈 바탕을 보고 통과하는 것이 아니다)
    const pair: Pt[] = [...rows.flatMap((y) => [{ x: g.nLeft + 3, y }, { x: g.nRight - 3, y }]), ...notch];
    const B = await colours(page, b, origin, pair);
    const mw = misses(pair, B, WITNESS);
    expect(mw.n, `알림을 숨기면 그 자리에 절이 보여야 한다 — ${mw.first.join(" ")}`).toBe(0);

    // ⑩ 좁은 창 — 가로 넘침을 셸의 구르는 칸에서 잰다 · 짝: 넓은 상자를 넣으면 그 검사가 잡는다
    if (c.viewport.width <= 640) {
      const ov = await page.evaluate(() => {
        const m = document.querySelector<HTMLElement>(".terminal-main")!;
        const before = { sw: m.scrollWidth, cw: m.clientWidth, doc: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1 };
        const d = document.createElement("div");
        d.style.cssText = "width: 2000px; height: 1px;";
        m.appendChild(d);
        const caught = m.scrollWidth > m.clientWidth + 1;
        d.remove();
        return { ...before, caught };
      });
      expect(ov.sw, `구르는 칸의 가로 넘침 ${JSON.stringify(ov)}`).toBeLessThanOrEqual(ov.cw + 1);
      expect(ov.doc, "문서의 가로 넘침").toBe(true);
      expect(ov.caught, "짝: 넓은 상자를 넣으면 구르는 칸의 검사가 잡는다").toBe(true);
    }
  });
}

/** 두 칸 · 판 탭 — 페이지가 본문 높이에 맞아 셸이 구르지 않는다. 고정이 걸리지 않으니 알림은 제자리 그대로여야 한다(짝 — 고치기 전에도 통과). */
for (const ws of [false, true]) {
  test(`1280 × 800 ${ws ? "판 탭" : "두 칸"}(짝): 셸이 구르지 않아 알림은 제자리 · 전환 줄 → 알림 28px · 알림 → 다음 칸 12px · 띠가 전환 줄을 덮지 않는다`, async ({ page }) => {
    await open(page, { viewport: { width: 1280, height: 800 }, theme: "light", ws });
    if (ws) await expect(page.locator(".itd")).toHaveAttribute("data-ws", "tabs");
    else await expect(page.locator(".itd")).toHaveAttribute("data-split", "");
    await runSynth(page);
    const main = await page.locator(".terminal-main").evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight }));
    expect(main.sh, `셸이 구르지 않는다 ${JSON.stringify(main)}`).toBeLessThanOrEqual(main.ch + 1);
    await unstuck(page, 28);
    if (!ws) {
      // 결과 칸은 제 스크롤로 구른다 — 알림은 그 자리
      const b0 = (await page.locator(".itd-banner").boundingBox())!;
      await page.locator(".itd-out").evaluate((el) => el.scrollTo({ top: 1600, behavior: "instant" }));
      await frame(page);
      expect(await page.locator(".itd-out").evaluate((el) => el.scrollTop), "결과 칸이 굴렀다").toBeGreaterThan(300);
      const b1 = (await page.locator(".itd-banner").boundingBox())!;
      expect(Math.abs(b1.y - b0.y), "결과 칸을 굴려도 알림은 그 자리").toBeLessThan(0.5);
    }
  });
}
