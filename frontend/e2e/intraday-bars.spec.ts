import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";
import { CANDLE_AXIS, CANDLE_MIN_SLOT, CANDLE_PAD, barAtStrip, candleLayout, niceStep, overviewLayout, overviewWindow, timeStep, visibleRange } from "../src/shared/ui/chart/candleGeo";

// ════════════════════════════════════════════════════════════════════════════
// 봉과 체결 — 분봉 결과의 하루 보기 (G4 · 구현 계획 §5 · ADR 004 손그림 SVG)
//  · 좌표는 순수 함수(`candleGeo`)라 손 계산과 그대로 견준다 — 내림 봉 · 범위 0 · 거래량 0 · 봉 밖 체결가 · 같은 봉 묶음 · 봉에 없는 시각 · 최소 칸.
//  · 화면: 손으로 만든 하루(035720 · 봉 넷) — 시가 범위 돌파 1분 · 100만원 · 1틱:
//      09:02 시가 10,070 + 10 = 10,080 에 99주 매수(신호 다음 봉 시가) → 09:03 종가 10,110 − 10 = 10,100 에 매도(장 마감 청산).
//    매수 눈금은 09:02 몸통(10,070 ~ 10,090)의 한가운데 · 매도 눈금은 09:03 몸통(10,090 ~ 10,110)의 한가운데다(손 계산).
//  · 09:00 은 보합(시가 = 종가) — 가로선 하나 · 그 높이는 09:01 양봉의 몸통 아래(시가 10,000)와 같다.
//  · 값은 서버 그대로(읽는 줄 · 표 쌍둥이) · 정합 줄 · 사실 줄 · 라이트 · 다크 AA · 문체 · 390px 넘침 0(틀 안 스크롤).
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";
const HAND = { tickers: "035720", from: "2026-03-02", to: "2026-03-13" };
const SYNTH = { tickers: "005930, 000660", from: "2026-04-01", to: "2026-04-03" };
const HERE = "/backtest/intraday";

const close = (a: number, b: number, d = 0.001) => expect(Math.abs(a - b), `${a} ≈ ${b}`).toBeLessThan(d);

// ── 좌표(순수 · 손 계산) ───────────────────────────────────────────────────────────────

test("좌표: 손으로 계산한 네 봉 · 고정 가격 축 · 몸통 밖 체결가 눈금 · 묶인 체결 · 봉에 없는 체결", () => {
  const bars = [
    { time: "09:00:00", open: 100, high: 110, low: 90, close: 100, volume: 100 },   // 보합
    { time: "09:01:00", open: 100, high: 120, low: 100, close: 120, volume: 200 },  // 양봉
    { time: "09:02:00", open: 120, high: 125, low: 105, close: 110, volume: 0 },    // 음봉 · 거래량 0
    { time: "09:03:00", open: 110, high: 115, low: 110, close: 115, volume: 400 },  // 양봉
  ];
  const fills = [
    { time: "09:01:00", side: "buy" as const, quantity: 10, price: 121, label: "a" },   // 봉 고가 밖(슬리피지)
    { time: "09:01:00", side: "buy" as const, quantity: 5, price: 121, label: "b" },    // 같은 봉 · 같은 방향 → 묶음
    { time: "09:03:00", side: "sell" as const, quantity: 15, price: 112, label: "c" },
    { time: "09:05:00", side: "buy" as const, quantity: 1, price: 100, label: "d" },    // 봉에 없는 시각 → 그리지 않고 센다
  ];
  const g = candleLayout({ bars, fills, width: 400, height: 200 });
  // 가격 축은 넘기지 않는 왼쪽 64px · 보이는 그림 폭 336 · 칸 (336 − 12) ÷ 4 = 81 · 몸통 ⌊81 × 0.6⌋ = 48 · 그림 폭 81 × 4 + 12 = 336(넘치지 않는다)
  expect([CANDLE_AXIS, CANDLE_MIN_SLOT]).toEqual([64, 9]);
  expect(CANDLE_PAD).toEqual({ right: 12, top: 12, bottom: 24 });
  expect([g.axisW, g.viewW, g.plotW, g.slot, g.bodyW]).toEqual([64, 336, 336, 81, 48]);
  expect([g.price.top, g.price.bottom, g.vol.top, g.vol.bottom]).toEqual([12, 132, 140, 176]);
  // 가격 범위 = 저가 · 고가 · 체결가의 최소 ~ 최대(90 ~ 125) ± 5% 여백(1.75) → 88.25 ~ 126.75
  close(g.price.lo, 88.25); close(g.price.hi, 126.75);
  const y = (p: number) => 12 + ((126.75 - p) / 38.5) * 120;
  expect(g.candles.map((c) => c.dir)).toEqual(["flat", "up", "down", "up"]);
  expect(g.candles.map((c) => c.x)).toEqual([40.5, 121.5, 202.5, 283.5]);          // 그림(넘기는 SVG)의 원점에서 — 축 폭을 더하지 않는다
  const want = [[100, 100, 110, 90], [120, 100, 120, 100], [120, 110, 125, 105], [115, 110, 115, 110]];
  g.candles.forEach((c, i) => {
    const [bt, bb, wt, wb] = want[i];
    close(c.body.top, y(bt)); close(c.body.bottom, y(bb)); close(c.wick.top, y(wt)); close(c.wick.bottom, y(wb));
  });
  // 거래량 막대: 띠 아래(176)에서 위로 거래량 ÷ 최대 거래량(400) × 36 — 거래량 0 은 높이 0
  expect(g.candles.map((c) => [c.vol.top, c.vol.bottom])).toEqual([[167, 176], [158, 176], [176, 176], [140, 176]]);
  // 표식: 09:01 매수 둘은 하나로 묶인다(수 2 · 눈금은 한 값) · 매수 ▲ 는 저가 아래 3px · 매도 ▼ 는 고가 위 3px
  expect(g.marks.map((m) => [m.i, m.side, m.x, m.fills.length])).toEqual([[1, "buy", 121.5, 2], [3, "sell", 283.5, 1]]);
  close(g.marks[0].tip, y(100) + 3); close(g.marks[1].tip, y(115) - 3);
  expect(g.marks[0].ticks.length).toBe(1);
  close(g.marks[0].ticks[0], y(121)); close(g.marks[1].ticks[0], y(112));
  // 체결가 눈금은 몸통 밖: 매수는 왼쪽 · 매도는 오른쪽 · 몸통에서 1px 띄우고 길이 = 칸 − 몸통 − 1 을 2 ~ 10 으로 묶은 값(여기서 10)
  expect(g.stub).toBe(10);
  expect(g.marks[0].tickX).toEqual([121.5 - 24 - 1 - 10, 121.5 - 24 - 1]);
  expect(g.marks[1].tickX).toEqual([283.5 + 24 + 1, 283.5 + 24 + 1 + 10]);
  expect(g.unplaced.map((f) => f.label)).toEqual(["d"]);
  // 가격 눈금: 범위 35 → 10 단위 · 90 · 100 · 110 · 120 / 시각 눈금: 칸 81px 이면 1분 간격으로도 56px 를 넘는다 → 봉마다
  expect(niceStep(35)).toBe(10);
  expect(g.priceTicks.map((t) => t.value)).toEqual([90, 100, 110, 120]);
  g.priceTicks.forEach((t) => close(t.y, y(t.value)));
  expect(timeStep(81)).toBe(1);
  expect(g.timeTicks.map((t) => [t.i, t.x, t.label])).toEqual([[0, 40.5, "09:00"], [1, 121.5, "09:01"], [2, 202.5, "09:02"], [3, 283.5, "09:03"]]);
});

test("좌표: 범위 0 · 거래량 0 · 최소 칸 9px 에서 그림이 틀보다 넓어진다 · 시각 눈금은 10분의 배수 · 하루 전체 띠와 보이는 구간", () => {
  const flat = Array.from({ length: 3 }, (_, i) => ({ time: `09:0${i}:00`, open: 100, high: 100, low: 100, close: 100, volume: 0 }));
  const g = candleLayout({ bars: flat, fills: [], width: 400, height: 200 });
  for (const c of g.candles) {
    expect(c.dir).toBe("flat");
    expect([c.body.top, c.wick.top, c.wick.bottom]).toEqual([72, 72, 72]);          // (12 + 132) ÷ 2 — 나누지 않는다
    expect([c.vol.top, c.vol.bottom]).toEqual([176, 176]);
  }
  expect(g.priceTicks).toEqual([{ value: 100, y: 72 }]);

  const time = (i: number) => `${String(9 + Math.floor(i / 60)).padStart(2, "0")}:${String(i % 60).padStart(2, "0")}:00`;
  const many = Array.from({ length: 400 }, (_, i) => ({ time: time(i), open: 100 + (i % 7), high: 108 + (i % 7), low: 98 + (i % 7), close: 104 + (i % 5), volume: 1 + i }));
  const w = candleLayout({ bars: many, fills: [{ time: time(395), side: "sell", quantity: 1, price: 104, label: "z" }], width: 400, height: 200 });
  // 칸 = max(9, 324 ÷ 400) = 9 · 몸통 ⌊5.4⌋ = 5(빈 몸통이 보이는 가장 작은 폭) · 그림 폭 9 × 400 + 12 = 3,612 > 보이는 폭 336
  expect([w.slot, w.bodyW, w.plotW, w.viewW, w.stub]).toEqual([9, 5, 3612, 336, 3]);
  // 시각 눈금: 1 · 2 · 5분은 9px × 분 < 56px → 10분 · 10의 배수인 분에만(09:00 · 09:10 · …) · 글자 사이 90px
  expect(timeStep(9)).toBe(10);
  expect(w.timeTicks.map((t) => t.i)).toEqual(Array.from({ length: 40 }, (_, k) => k * 10));
  expect(w.timeTicks.slice(0, 3).map((t) => t.label)).toEqual(["09:00", "09:10", "09:20"]);
  // 빠진 분 때문에 10분의 배수끼리 붙으면(09:00 · 09:10 · 09:20 이 이웃한 봉) 앞의 글자만 남는다
  const gap = candleLayout({ bars: ["09:00:00", "09:10:00", "09:20:00"].map((t) => ({ time: t, open: 1, high: 2, low: 1, close: 2, volume: 1 })),
                             fills: [], width: 64 + 12 + 27, height: 200 });
  expect(gap.slot).toBe(9);
  expect(gap.timeTicks.map((t) => t.label)).toEqual(["09:00"]);

  // 하루 전체 띠(보이는 폭 336): 봉 i 의 가로 자리 = (i + 0.5) × 칸 ÷ 그림 폭 × 띠 폭 — 보이는 구간 창과 같은 비례
  const ov = overviewLayout({ layout: w, bars: many, fills: [{ time: time(395), side: "sell", quantity: 1, price: 104, label: "z" }], height: 36 });
  expect(ov.width).toBe(336);
  close(ov.xs[0], (0.5 * 9 / 3612) * 336); close(ov.xs[399], (399.5 * 9 / 3612) * 336);
  expect(ov.ticks).toEqual([{ x: ov.xs[395], side: "sell" }]);
  const lo = Math.min(...many.map((b) => b.close)), hi = Math.max(...many.map((b) => b.close));
  expect([lo, hi]).toEqual([104, 108]);
  close(ov.ys[0], ov.top + ((hi - 104) / (hi - lo)) * (ov.bottom - ov.top));      // 0 번 봉 종가 104 = 가장 낮은 값 → 띠의 아래 끝
  close(ov.ys[0], ov.bottom);
  // 보이는 구간 창: 처음(0) · 끝(그림 폭 − 보이는 폭) — 끝에서 창의 오른쪽이 띠의 오른쪽과 같다
  const a = overviewWindow({ scrollLeft: 0, clientWidth: 336, plotW: 3612, stripW: 336 });
  close(a.x, 0); close(a.w, (336 / 3612) * 336);
  const b = overviewWindow({ scrollLeft: 3612 - 336, clientWidth: 336, plotW: 3612, stripW: 336 });
  close(b.x + b.w, 336);
  // 보이는 봉: 처음 0 ~ ⌈336 ÷ 9⌉ − 1 = 37 · 끝 ⌊3,276 ÷ 9⌋ = 364 ~ 399(n − 1 로 묶는다)
  expect(visibleRange({ scrollLeft: 0, clientWidth: 336, slot: 9, n: 400 })).toEqual({ first: 0, last: 37 });
  expect(visibleRange({ scrollLeft: 3276, clientWidth: 336, slot: 9, n: 400 })).toEqual({ first: 364, last: 399 });
  // 띠를 누른 자리 → 그 봉(가운데로 옮길 봉)
  expect(barAtStrip({ x: 0, stripW: 336, plotW: 3612, slot: 9, n: 400 })).toBe(0);
  expect(barAtStrip({ x: 336, stripW: 336, plotW: 3612, slot: 9, n: 400 })).toBe(399);
  expect(barAtStrip({ x: ov.xs[200], stripW: 336, plotW: 3612, slot: 9, n: 400 })).toBe(200);
  expect(candleLayout({ bars: [], fills: [{ time: "09:00:00", side: "buy", quantity: 1, price: 1, label: "x" }], width: 400, height: 200 }).unplaced).toHaveLength(1);
  // 가격 범위는 체결가도 넣는다 — 그날 고가(110)보다 높은 체결가 115 → 범위 100 ~ 115 ± 5%(0.75) → 99.25 ~ 115.75(체결가가 그림 밖으로 나가지 않는다)
  const outside = candleLayout({ bars: [{ time: "09:00:00", open: 100, high: 110, low: 100, close: 105, volume: 1 }],
                                 fills: [{ time: "09:00:00", side: "sell", quantity: 1, price: 115, label: "s" }], width: 400, height: 200 });
  close(outside.price.lo, 99.25); close(outside.price.hi, 115.75);
});

// ── 화면 ─────────────────────────────────────────────────────────────────────────────

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

async function login(page: Page): Promise<void> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
}

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);

async function runWith(page: Page, d: { tickers: string; from: string; to: string }, costs?: { commission: string; market: string; instrument: string }) {
  await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await page.locator(".itd-tickers").fill(d.tickers);
  await page.locator(".itd-from").fill(d.from);
  await page.locator(".itd-to").fill(d.to);
  await field(page, "minutes").fill("1");
  if (costs) {
    await field(page, "commission_bp").fill(costs.commission);
    await field(page, "unknown_market").selectOption(costs.market);
    await field(page, "unknown_instrument").selectOption(costs.instrument);
  }
  const day = page.waitForResponse((r) => /\/intraday\/trials\/[^/]+\/day/.test(r.url()) && r.request().method() === "GET");
  await page.locator(".itd-run").click();
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 30_000 });
  const res = await day;
  expect(res.status()).toBe(200);
  await expect(page.locator(".itd-day .cdl")).toBeVisible();
  return res.json();
}

const attr = async (page: Page, sel: string, name: string) => Number(await page.locator(sel).first().getAttribute(name));

test("손으로 만든 하루: 봉 넷의 모양 · 높이 · 체결 표식 = 손 계산 · 값은 서버 그대로", async ({ page }) => {
  const js = await runWith(page, HAND);
  // 첫 화면은 서버가 고른 첫 거래일 · 그날 첫 체결 종목
  expect([js.date, js.ticker]).toEqual(["2026-03-02", "035720"]);
  await expect(page.locator(".itd-day-date")).toHaveValue("2026-03-02");
  await expect(page.locator(".itd-day-date option")).toHaveCount(10);
  await expect(page.locator(".itd-day-date option").first()).toHaveText("2026-03-02 · 거래 1건");
  await expect(page.locator(".itd-day-ticker")).toHaveValue("035720");

  const c = (t: string) => `.itd-day .cdl-candle[data-time="${t}"]`;
  await expect(page.locator(".itd-day .cdl-candle")).toHaveCount(4);
  // 읽는 줄은 처음에 그날 첫 체결의 봉(09:02)에 선다
  await expect(page.locator(".itd-day .cr-read .cr-head")).toHaveText("09:02");
  for (const [t, dir] of [["09:00:00", "flat"], ["09:01:00", "up"], ["09:02:00", "up"], ["09:03:00", "up"]]) {
    await expect(page.locator(c(t))).toHaveClass(new RegExp(`cdl-${dir}`));
  }
  // 09:01 양봉은 몸통 = 고가 ~ 저가(10,000 ~ 10,060) · 09:02 · 09:03 은 몸통 20 / 꼬리 40 = 절반
  const body = async (t: string) => ({ y: await attr(page, `${c(t)} rect.cdl-body`, "y"), h: await attr(page, `${c(t)} rect.cdl-body`, "height") });
  const wick = async (t: string) => { const a = await attr(page, `${c(t)} .cdl-wick`, "y1"); const b = await attr(page, `${c(t)} .cdl-wick`, "y2"); return Math.abs(b - a); };
  const b1 = await body("09:01:00"), b2 = await body("09:02:00"), b3 = await body("09:03:00");
  close(b1.h, await wick("09:01:00"), 0.01);
  close(b2.h / (await wick("09:02:00")), 0.5, 0.01);
  close(b3.h / (await wick("09:03:00")), 0.5, 0.01);
  close(b2.h, b3.h, 0.01);
  // 09:00 보합은 가로선 하나 — 높이(10,000)는 09:01 몸통의 아래 끝(시가 10,000)과 같다
  await expect(page.locator(`${c("09:00:00")} rect.cdl-body`)).toHaveCount(0);
  close(await attr(page, `${c("09:00:00")} .cdl-flat-line`, "y1"), b1.y + b1.h, 0.01);

  // 표식: 매수 ▲ 09:02 · 매도 ▼ 09:03 — 눈금은 손 계산의 체결가 자리(몸통 한가운데)
  const buy = page.locator('.itd-day .cdl-mark-buy[data-time="09:02:00"]');
  const sell = page.locator('.itd-day .cdl-mark-sell[data-time="09:03:00"]');
  await expect(page.locator(".itd-day .cdl-mark")).toHaveCount(2);
  await expect(buy).toHaveAttribute("data-count", "1");
  await expect(sell).toHaveAttribute("data-count", "1");
  close(Number(await buy.locator(".cdl-tick").getAttribute("y1")), b2.y + b2.h / 2, 0.01);
  close(Number(await sell.locator(".cdl-tick").getAttribute("y1")), b3.y + b3.h / 2, 0.01);
  // 체결가 눈금은 몸통 밖 — 매수는 왼쪽(몸통 왼쪽 끝 − 1px 에서 끝난다) · 매도는 오른쪽(몸통 오른쪽 끝 + 1px 에서 시작한다)
  const bx = await attr(page, `${c("09:02:00")} rect.cdl-body`, "x"), sx = await attr(page, `${c("09:03:00")} rect.cdl-body`, "x");
  const bw = await attr(page, `${c("09:03:00")} rect.cdl-body`, "width");
  close(Number(await buy.locator(".cdl-tick").getAttribute("x2")), bx - 1, 0.01);
  expect(Number(await buy.locator(".cdl-tick").getAttribute("x1"))).toBeLessThan(bx - 1);
  close(Number(await sell.locator(".cdl-tick").getAttribute("x1")), sx + bw + 1, 0.01);
  expect(Number(await sell.locator(".cdl-tick").getAttribute("x2"))).toBeGreaterThan(sx + bw + 1);
  // 범례 · 넘기지 않는 가격 축(눈금 글자는 축 SVG 에만) · 봉 넷은 틀에 다 들어가므로 '하루 전체' 띠와 보이는 구간 글은 없다
  await expect(page.locator(".itd-day .cdl-legend li")).toHaveText(["매수 체결", "매도 체결", "체결가(매수 왼쪽 · 매도 오른쪽 눈금)",
                                                                   "양봉(빈 몸통)", "음봉(채운 몸통)", "보합(가로선)"]);
  await expect(page.locator(".itd-day .cdl-axis .cdl-plabel")).toHaveText(["10,000", "10,050", "10,100"]);
  await expect(page.locator(".itd-day svg.cdl .cdl-plabel")).toHaveCount(0);
  await expect(page.locator(".itd-day .cdl-overview")).toHaveCount(0);
  await expect(page.locator(".itd-day .cdl-range")).toHaveCount(0);
  expect(js.fills).toEqual([
    { time: "09:02:00", side: "buy", quantity: 99, price: 10080, kind: "entry_signal", kind_label: "진입(신호 다음 봉 시가)" },
    { time: "09:03:00", side: "sell", quantity: 99, price: 10100, kind: "session_end", kind_label: "장 마감 청산" },
  ]);

  // 읽는 줄 — 키보드로 옮기고 서버 값 그대로(체결 · 그 봉 거래량 대비 · 왕복의 비용 후 손익)
  const fig = page.locator(".itd-day .cdl-fig");
  await fig.focus();
  await page.keyboard.press("Home");
  await expect(page.locator(".itd-day .cr-read .cr-head")).toHaveText("09:00");
  await expect(page.locator(".itd-day .cr-read")).toContainText("보합");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".itd-day .cr-read .cr-head")).toHaveText("09:02");
  await expect(page.locator(".itd-day .cr-read")).toContainText("매수 99주 10,080원 · 진입(신호 다음 봉 시가) · 그 봉 거래량의 9.9%");
  await page.keyboard.press("End");
  await expect(page.locator(".itd-day .cr-read")).toContainText("매도 99주 10,100원 · 장 마감 청산 · 그 봉 거래량의 9.9%");
  // 이 실행은 수수료율을 비워 두고 시장 구분도 가정하지 않았다 → 수수료 · 매도세 미상 → 그 왕복의 비용 후 손익은 미상(0 이 아니다).
  // 짝(비용 가정을 넣은 하루 → 값)은 아래 시험이 건다.
  expect(js.trades).toHaveLength(1);
  expect(js.trades[0]).toMatchObject({ gross: 1980, fees: null, taxes: null, net: null });
  await expect(page.locator(".itd-day .cr-read")).toContainText("이 왕복 비용 후 손익 미상(수수료 · 매도세 미상)");

  // 표 쌍둥이 = 서버의 봉 전부
  const rows = page.locator(".itd-day .cr-table tbody tr");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(1)).toContainText("10,060");
  // 정합 줄 · 사실 줄 = 서버 문장 그대로
  expect(js.check.status).toBe("same");
  await expect(page.locator(".itd-day .itd-day-check")).toHaveText(js.check.message);
  await expect(page.locator(".itd-day .itd-day-facts li")).toHaveText(js.facts);

  // 다른 날을 고르면 그날을 묻는다
  const again = page.waitForRequest((r) => r.url().includes("/day?") && r.url().includes("date=2026-03-05"));
  await page.locator(".itd-day-date").selectOption("2026-03-05");
  await again;
  await expect(page.locator(".itd-day .cdl-candle")).toHaveCount(4);
  // 다른 날의 읽는 줄은 앞 날에 옮겨 둔 자리(09:03)가 아니라 그날 첫 체결의 봉에서 다시 선다
  await expect(page.locator(".itd-day-date")).toHaveValue("2026-03-05");
  await expect(page.locator(".itd-day .cr-read .cr-head")).toHaveText("09:02");
});

test("서버가 말한 열화 상태를 그대로 보인다: 정합 다름 · 건너뛴 종목 · 다시 그리지 않은 하루 · 봉에 없는 시각의 체결 · 실패 뒤 다시 시도", async ({ page }) => {
  await runWith(page, HAND);
  type Mode = "real" | "different" | "skipped" | "empty" | "unplaced" | "fail";
  let mode: Mode = "real";
  const SAID = { different: "심은 문장: 다시 계산한 값이 남은 값과 다릅니다.", skipped: "심은 문장: 그날 이 종목의 봉이 없습니다.",
                 empty: "심은 문장: 이 하루를 다시 그리지 않았습니다.", fail: "심은 문장: 시행 기록을 읽지 못했습니다." };
  await page.route("**/intraday/trials/*/day*", async (route) => {
    if (mode === "fail") {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: { code: "store_unavailable", reason: SAID.fail } }) });
      return;
    }
    const real = await route.fetch();
    const js = await real.json();
    const none = { bars: null, origin: null, fills: [], trades: [], others: { fills: 0 }, check: null };
    if (mode === "different") js.check = { ...js.check, status: "different", message: SAID.different };
    if (mode === "skipped") Object.assign(js, none, { skipped: { reason: "no_bars", message: SAID.skipped } });
    if (mode === "empty") Object.assign(js, none, { empty: { reason: "not_loaded", message: SAID.empty } });
    if (mode === "unplaced") js.fills = [...js.fills,
      { time: "09:02:00", side: "buy", quantity: 1, price: 10090, kind: "entry_signal", kind_label: "진입(신호 다음 봉 시가)" },   // 같은 봉 · 같은 방향 → 묶음
      { time: "15:30:00", side: "sell", quantity: 1, price: 10000, kind: "session_end", kind_label: "장 마감 청산" }];
    await route.fulfill({ response: real, json: js });
  });
  const pick = async (m: Mode, date: string) => {
    mode = m;
    const done = page.waitForResponse((r) => r.url().includes(`date=${date}`));
    await page.locator(".itd-day-date").selectOption(date);
    await done;
    await expect(page.locator(".itd-day-date")).toHaveValue(date);
  };

  await pick("different", "2026-03-03");                                       // 다르면 그리되 그렇다고 적는다
  await expect(page.locator(".itd-day-checkrow")).toHaveAttribute("data-status", "different");
  await expect(page.locator(".itd-day-chip")).toHaveText("실행 결과와 다름");
  await expect(page.locator(".itd-day-check")).toHaveText(SAID.different);
  await expect(page.locator(".itd-day .cdl-candle")).toHaveCount(4);

  await pick("skipped", "2026-03-04");                                         // 건너뛴 종목: 봉 대신 사유 · 0 으로 그리지 않는다
  await expect(page.locator(".itd-day-skipped")).toHaveText(SAID.skipped);
  await expect(page.locator(".itd-day .cdl")).toHaveCount(0);
  await expect(page.locator(".itd-day-checkrow")).toHaveCount(0);

  await pick("empty", "2026-03-05");                                           // 다시 그리지 않은 하루: 사유만
  await expect(page.locator(".itd-day .tx-notice-t").first()).toHaveText("이 하루를 다시 그리지 않았습니다.");
  await expect(page.locator(".itd-day .tx-notice-b").first()).toHaveText(SAID.empty);
  await expect(page.locator(".itd-day .cdl")).toHaveCount(0);

  await pick("unplaced", "2026-03-06");                                        // 봉에 없는 시각의 체결: 그리지 않되 세고 줄로 적는다
  await expect(page.locator(".itd-day .cdl-mark")).toHaveCount(2);
  // 같은 봉 · 같은 방향의 체결 둘은 표식 하나로 묶고 수를 적는다 — 체결가가 다르면 눈금은 둘
  const both = page.locator('.itd-day .cdl-mark-buy[data-time="09:02:00"]');
  await expect(both).toHaveAttribute("data-count", "2");
  await expect(both.locator(".cdl-count")).toHaveText("×2");
  await expect(both.locator(".cdl-tick")).toHaveCount(2);
  await expect(page.locator('.itd-day .cdl-mark-sell[data-time="09:03:00"] .cdl-count')).toHaveCount(0);
  await expect(page.locator(".itd-day-counts")).toContainText("이 종목의 체결 4건");
  await expect(page.locator(".itd-day-counts")).toContainText("봉에 없는 시각의 체결 1건은 그리지 않았습니다.");
  await expect(page.locator(".itd-day-unplaced")).toHaveText(["15:30 매도 1주 10,000원 · 장 마감 청산"]);

  mode = "fail";                                                               // 기록 장애(503): 다시 시도할 수 있는 실패 · 사유는 서버 문장
  await page.locator(".itd-day-date").selectOption("2026-03-09");
  await expect(page.locator(".tx-notice-t", { hasText: "하루 보기를 불러오지 못했습니다." })).toBeVisible();
  await expect(page.locator(".tx-notice-b", { hasText: SAID.fail })).toBeVisible();
  mode = "real";
  await page.getByRole("button", { name: "재시도" }).click();
  await expect(page.locator(".itd-day .cdl-candle")).toHaveCount(4);
  await expect(page.locator(".itd-day-date")).toHaveValue("2026-03-09");
  await expect(page.locator(".itd-day-unplaced")).toHaveCount(0);
});

test("봉의 모양과 색: 양봉은 빈 몸통 · 음봉은 채운 몸통 · 보합은 가로선 — 가로챈 답의 봉 하나를 음봉으로(합성 분봉에는 음봉이 없다)", async ({ page }) => {
  await runWith(page, HAND);
  await page.route("**/intraday/trials/*/day*", async (route) => {
    const real = await route.fetch();
    const js = await real.json();
    if (js.bars) js.bars.close[1] = 9_990;                                       // 09:01 시가 10,000 → 종가 9,990: 음봉
    await route.fulfill({ response: real, json: js });
  });
  const done = page.waitForResponse((r) => r.url().includes("date=2026-03-04"));
  await page.locator(".itd-day-date").selectOption("2026-03-04");
  await done;
  const c = (t: string) => `.itd-day .cdl-candle[data-time="${t}"]`;
  await expect(page.locator(c("09:01:00"))).toHaveClass(/cdl-down/);
  await expect(page.locator(c("09:02:00"))).toHaveClass(/cdl-up/);
  const look = (sel: string) => page.locator(sel).evaluate((el) => { const cs = getComputedStyle(el); return { fill: cs.fill, stroke: cs.stroke }; });
  const down = await look(`${c("09:01:00")} rect.cdl-body`), up = await look(`${c("09:02:00")} rect.cdl-body`);
  const flat = await look(`${c("09:00:00")} .cdl-flat-line`);
  expect(down.fill, "음봉은 채운 몸통(채움 = 테두리 색)").toBe(down.stroke);
  expect(up.fill, "양봉은 빈 몸통(채움 ≠ 테두리 색)").not.toBe(up.stroke);
  expect(up.stroke, "등락의 색이 다르다").not.toBe(down.stroke);
  expect(flat.stroke, "보합의 가로선은 등락의 색이 아니다").not.toBe(up.stroke);
  expect(flat.stroke).not.toBe(down.stroke);
  // 범례의 글리프는 그림과 같은 규칙으로 칠해진다(범례 = 그림)
  const legendUp = await look(".itd-day .cdl-legend .cdl-up .cdl-body"), legendDown = await look(".itd-day .cdl-legend .cdl-down .cdl-body");
  expect([legendUp, legendDown]).toEqual([up, down]);
  // 읽는 줄도 모양을 글로 말한다
  await page.locator(".itd-day .cdl-fig").focus();
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".itd-day .cr-read .cr-head")).toHaveText("09:01");
  await expect(page.locator(".itd-day .cr-read")).toContainText("모양 음봉");
});

test("비용 가정을 넣은 하루: 매도 표식의 읽는 줄 = 그 왕복의 비용 후 손익(손 계산) · 미상이라 적지 않는다", async ({ page }) => {
  const js = await runWith(page, HAND, { commission: "1.5", market: "KOSPI", instrument: "stock" });
  // 손 계산: 총손익 99 × (10,100 − 10,080) = 1,980 · 수수료 1.5bp × (997,920 + 999,900) = 299.673 · 매도세 20bp × 999,900 = 1,999.8
  //          → 비용 2,299.473 · 비용 후 −319.473 → 화면은 원 단위 반올림 '−319원'
  expect(js.trades).toHaveLength(1);
  const t = js.trades[0];
  expect(t.gross).toBe(1980);
  close(t.fees, 299.673, 1e-6); close(t.taxes, 1999.8, 1e-6); close(t.net, -319.473, 1e-6);
  await page.locator(".itd-day .cdl-fig").focus();
  await page.keyboard.press("End");
  await expect(page.locator(".itd-day .cr-read")).toContainText("매도 99주 10,100원 · 장 마감 청산 · 그 봉 거래량의 9.9% · 이 왕복 비용 후 −319원");
  await expect(page.locator(".itd-day .cr-read")).not.toContainText("미상");
});

for (const theme of ["light", "dark"] as const) {
  test(`봉과 체결: 대비(${theme}) AA · 문체 · 390px 에서 페이지는 넘치지 않고 그림 틀 안에서만 옆으로 넘긴다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await page.setViewportSize({ width: 390, height: 900 });
    const js = await runWith(page, SYNTH);                                   // 합성 하루는 봉이 수백 개 — 칸이 최소 폭에 닿는다
    const a = (await page.evaluate(contrastAudit(".itd-day"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(1);
    expect(a.low, theme).toEqual([]);
    const v = (await page.evaluate(voiceAudit(".itd-day"))) as VoiceResult;
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(over).toBeLessThanOrEqual(0);
    const box = await page.locator(".itd-day .cdl-scroll").evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth }));
    expect(box.sw).toBeGreaterThan(box.cw);
    const times: string[] = js.bars.time;
    const hm = (t: string) => t.slice(0, 5);
    const axisAt = () => page.locator(".itd-day .cdl-axis").evaluate((el) => Math.round(el.getBoundingClientRect().left));
    const labels = await page.locator(".itd-day .cdl-axis .cdl-plabel").allTextContents();
    expect(labels.length).toBeGreaterThan(1);
    const before = await axisAt();
    // 가격 축은 봉 그림의 바로 왼쪽에 같은 높이로 붙어 있다(위에 쌓이지 않는다)
    const ab = await page.locator(".itd-day .cdl-axis").boundingBox(), pb = await page.locator(".itd-day .cdl-scroll").boundingBox();
    expect(ab && pb && Math.abs(ab.y - pb.y) < 1 && Math.abs(ab.x + ab.width - pb.x) < 1, JSON.stringify({ ab, pb })).toBe(true);
    // 그림이 틀보다 넓으면 '하루 전체' 띠와 보이는 구간 글이 선다
    await expect(page.locator(".itd-day .cdl-overview")).toBeVisible();
    const range = page.locator(".itd-day .cdl-range");
    await expect(range).toHaveText(new RegExp(`^보이는 구간 \\d\\d:\\d\\d ~ \\d\\d:\\d\\d \\(하루 ${hm(times[0])} ~ ${hm(times[times.length - 1])}\\)$`));
    // 끝으로 옮기면 그 봉이 보이게 틀이 스크롤된다 — 가격 축은 넘어가지 않고 제자리에 그대로 있다
    await page.locator(".itd-day .cdl-fig").focus();
    await page.keyboard.press("End");
    await expect.poll(() => page.locator(".itd-day .cdl-scroll").evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    expect(await axisAt()).toBe(before);
    await expect(page.locator(".itd-day .cdl-axis .cdl-plabel")).toHaveText(labels);
    await expect(page.locator(".itd-day .cdl-axis .cdl-plabel").first()).toBeInViewport();
    await expect(range).toHaveText(new RegExp(` ~ ${hm(times[times.length - 1])} \\(하루 `));
    await expect(range).not.toHaveText(new RegExp(`^보이는 구간 ${hm(times[0])} ~ `));          // 보이는 구간의 시작도 따라 옮겨졌다
    const win = () => page.locator(".itd-day .cdl-ov-window").evaluate((el) => ({ x: Number(el.getAttribute("x")), w: Number(el.getAttribute("width")) }));
    const strip = await page.locator(".itd-day .cdl-overview").evaluate((el) => Number(el.getAttribute("width")));
    await expect.poll(async () => { const w = await win(); return Math.abs(w.x + w.w - strip) < 1; }).toBe(true);   // 끝: 창의 오른쪽 = 띠의 오른쪽
    // 띠의 왼쪽 끝(0px)을 누르면 하루의 처음으로 돌아간다 — 읽는 줄도 그 봉으로(띠 1px 은 봉 약 2개라 1px 이면 둘째 봉이다)
    await page.locator(".itd-day .cdl-overview").click({ position: { x: 0, y: 10 } });
    await expect.poll(() => page.locator(".itd-day .cdl-scroll").evaluate((el) => el.scrollLeft)).toBe(0);
    await expect(page.locator(".itd-day .cr-read .cr-head")).toHaveText(hm(times[0]));
    await expect.poll(async () => (await win()).x).toBeLessThan(1);
    await expect(range).toHaveText(new RegExp(`^보이는 구간 ${hm(times[0])} ~ `));
    expect(await axisAt()).toBe(before);
    // 바퀴 · 손가락으로도 그림 틀만 옆으로 넘어간다 — 코드로 옮기는 스크롤(키 · 띠)은 `overflow-x: hidden` 에서도 되므로 따로 본다
    // (Chromium 관측 2026-11-19: hidden · clip 은 바퀴 0px · scrollLeft 대입은 된다). 페이지는 옆으로 움직이지 않는다.
    const sb = (await page.locator(".itd-day .cdl-scroll").boundingBox())!;
    await page.mouse.move(sb.x + sb.width / 2, sb.y + sb.height / 2);
    await page.mouse.wheel(240, 0);
    await expect.poll(() => page.locator(".itd-day .cdl-scroll").evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    expect(await page.evaluate(() => document.scrollingElement?.scrollLeft ?? -1)).toBe(0);
    expect(await axisAt()).toBe(before);
  });
}
