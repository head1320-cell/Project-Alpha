/**
 * 봉 그림의 좌표 — 순수 함수 (G4 · 구현 계획 §5 · §5.7 · ADR 004 손그림 SVG)
 * ==========================================================================
 * 그리지 않고 셈만 한다 — 그래서 E2E 가 손 계산과 그대로 견준다(`e2e/intraday-bars.spec.ts`).
 *   · 가로는 ★봉 순서★ 축이다(HTS 관례) — 거래가 없던 분은 봉이 없어 축에서 빠진다.
 *   · 가격 눈금은 넘기지 않는 왼쪽 축(`CANDLE_AXIS` px · 따로 그린 SVG)에 있고, 봉 그림은 그 오른쪽의 넘기는 틀 안에 있다 —
 *     그래서 봉의 x 는 ★그림(넘기는 SVG)의 원점★에서 잰다. 칸 = (보이는 폭 − 오른쪽 여백) ÷ 봉 수, 다만 최소 칸보다 좁히지 않는다
 *     (그때는 그림이 틀보다 넓어지고 틀 안에서 옆으로 넘긴다 · 페이지는 넘치지 않는다 · 아래 '하루 전체' 띠가 어디를 보는지 말한다).
 *   · 세로 가격 범위 = 그날 저가 · 고가 · ★체결가★의 최소 ~ 최대 ± 5% 여백 — 슬리피지로 봉 밖에 난 체결가도 그림 안에 든다.
 *     범위가 0 이면 나누지 않고 가운데 한 줄에 놓는다.
 *   · 거래량은 아래 띠 — 최대 거래량에 맞춘 높이 · 모두 0 이면 높이 0(나누지 않는다).
 *   · 체결 표식은 같은 봉 · 같은 방향끼리 묶는다(수를 센다). 체결가 눈금은 몸통 밖 — 매수는 왼쪽 · 매도는 오른쪽(몸통을 가로지르면 상자그림으로 읽힌다).
 *     봉에 없는 시각의 체결은 그리지 않고 따로 돌려준다(`unplaced`).
 *   · 시각 눈금은 1 · 2 · 5 · 10 · 15 · 30 · 60분 가운데 글자가 겹치지 않는 가장 작은 간격의 배수인 분에만 — 빠진 분 때문에 붙은 글자는 뺀다.
 * 차트 라이브러리를 들이지 않는다(경계 규칙).
 */
export type CandleBar = { time: string; open: number; high: number; low: number; close: number; volume: number };
export type CandleFill = { time: string; side: "buy" | "sell"; quantity: number; price: number; label: string };
export type CandleDir = "up" | "down" | "flat";
export type CandleShape = {
  i: number; x: number; dir: CandleDir;
  body: { top: number; bottom: number }; wick: { top: number; bottom: number }; vol: { top: number; bottom: number };
};
/** 같은 봉 · 같은 방향의 체결 묶음. `tip` 은 세모의 꼭짓점(매수 ▲ 는 저가 아래 · 매도 ▼ 는 고가 위) · `ticks` 는 체결가 자리(겹치면 하나) ·
 *  `tickX` 는 그 눈금의 가로 끝 둘(매수는 몸통 왼쪽 · 매도는 오른쪽). */
export type CandleMark = { i: number; side: "buy" | "sell"; x: number; tip: number; ticks: number[]; tickX: [number, number]; fills: CandleFill[] };
export type CandleLayout = {
  /** 넘기지 않는 가격 축의 폭 */ axisW: number;
  /** 보이는 그림 폭(틀 폭 − 축 폭) */ viewW: number;
  /** 그림(넘기는 SVG)의 폭 — 보이는 폭보다 크면 틀 안에서 넘긴다 */ plotW: number;
  height: number; slot: number; bodyW: number; stub: number;
  price: { top: number; bottom: number; lo: number; hi: number };
  vol: { top: number; bottom: number; max: number };
  candles: CandleShape[]; marks: CandleMark[]; unplaced: CandleFill[];
  priceTicks: { value: number; y: number }[]; timeTicks: { i: number; x: number; label: string }[];
};

/** 넘기지 않는 왼쪽 가격 축의 폭(px) — 그림 아래 '하루 전체' 띠도 이만큼 비우고 그림 밑에 맞춘다(CSS 와 같은 값). */
export const CANDLE_AXIS = 64;
export const CANDLE_PAD = { right: 12, top: 12, bottom: 24 } as const;
/** 봉 칸의 최소 폭(px) — 몸통 5px(테두리 1.25 × 2 + 안 2.5)이라야 빈 몸통(양봉)과 채운 몸통(음봉)이 모양으로 갈린다. */
export const CANDLE_MIN_SLOT = 9;
const BODY_SHARE = 0.6;       // 칸에서 몸통이 차지하는 몫
const VOL_SHARE = 0.22;       // 그림 높이에서 거래량 띠의 몫
const GAP = 8;                // 가격 그림과 거래량 띠 사이
const MARK_GAP = 3;           // 세모 꼭짓점과 봉 끝 사이
const PRICE_PAD = 0.05;       // 가격 범위 위아래 여백
const TIME_LABEL_PX = 56;     // 시각 글자 하나가 차지하는 폭(겹치지 않게)
const STUB_MIN = 2, STUB_MAX = 10;
const TIME_STEPS = [1, 2, 5, 10, 15, 30, 60] as const;

/** 눈금 간격 — 1 · 2 · 5 × 10ⁿ 가운데 범위를 대략 `target` 칸으로 나누는 값. 원 단위라 1 보다 작게 하지 않는다. */
export function niceStep(span: number, target = 5): number {
  if (!(span > 0)) return 1;
  const raw = span / target;
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return Math.max(1, (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p);
}

/** 시각 눈금의 분 간격 — 1분에 봉 하나로 보아 `간격 × 칸 ≥ 56px` 인 가장 작은 값(없으면 60). */
export function timeStep(slot: number): number {
  return TIME_STEPS.find((m) => m * slot >= TIME_LABEL_PX) ?? 60;
}

function minuteOf(time: string): number | null {
  const m = /^(\d\d):(\d\d)/.exec(time);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

export function candleLayout({ bars, fills, width, height, minSlot = CANDLE_MIN_SLOT }: {
  bars: CandleBar[]; fills: CandleFill[];
  /** 그림 틀의 폭(축 포함) */ width: number; height: number; minSlot?: number;
}): CandleLayout {
  const { right: R, top: T, bottom: B } = CANDLE_PAD;
  const n = bars.length;
  const viewW = Math.max(0, width - CANDLE_AXIS);
  const avail = Math.max(0, viewW - R);
  const slot = n > 0 ? Math.max(minSlot, avail / n) : 0;
  const plotW = n > 0 ? slot * n + R : viewW;
  const bodyW = Math.max(1, Math.floor(slot * BODY_SHARE));
  const stub = Math.min(STUB_MAX, Math.max(STUB_MIN, Math.floor(slot - bodyW - 1)));
  const inner = Math.max(0, height - T - B);
  const volH = Math.round(inner * VOL_SHARE);
  const priceTop = T, priceBottom = T + inner - volH - GAP;
  const volTop = priceBottom + GAP, volBottom = T + inner;

  const prices = [...bars.flatMap((b) => [b.high, b.low]), ...fills.map((f) => f.price)].filter((p) => Number.isFinite(p));
  const lo0 = prices.length ? Math.min(...prices) : 0, hi0 = prices.length ? Math.max(...prices) : 0;
  const pad = (hi0 - lo0) * PRICE_PAD;
  const lo = lo0 - pad, hi = hi0 + pad;
  const y = (p: number) => (hi > lo ? priceTop + ((hi - p) / (hi - lo)) * (priceBottom - priceTop) : (priceTop + priceBottom) / 2);
  const xOf = (i: number) => (i + 0.5) * slot;
  const maxV = Math.max(0, ...bars.map((b) => (Number.isFinite(b.volume) ? b.volume : 0)));

  const candles: CandleShape[] = bars.map((b, i) => {
    const dir: CandleDir = b.close > b.open ? "up" : b.close < b.open ? "down" : "flat";
    const volTopAt = maxV > 0 ? volBottom - (Math.max(0, b.volume) / maxV) * (volBottom - volTop) : volBottom;
    return { i, x: xOf(i), dir, body: { top: y(Math.max(b.open, b.close)), bottom: y(Math.min(b.open, b.close)) },
             wick: { top: y(b.high), bottom: y(b.low) }, vol: { top: volTopAt, bottom: volBottom } };
  });

  const half = bodyW / 2;
  const at = new Map<string, number>();
  bars.forEach((b, i) => { if (!at.has(b.time)) at.set(b.time, i); });
  const groups = new Map<string, CandleMark>();
  const unplaced: CandleFill[] = [];
  for (const f of fills) {
    const i = at.get(f.time);
    if (i === undefined) { unplaced.push(f); continue; }
    const key = `${i}|${f.side}`;
    let mark = groups.get(key);
    if (!mark) {
      const c = candles[i];
      const tickX: [number, number] = f.side === "buy" ? [c.x - half - 1 - stub, c.x - half - 1] : [c.x + half + 1, c.x + half + 1 + stub];
      mark = { i, side: f.side, x: c.x, tip: f.side === "buy" ? c.wick.bottom + MARK_GAP : c.wick.top - MARK_GAP, ticks: [], tickX, fills: [] };
      groups.set(key, mark);
    }
    mark.fills.push(f);
    const ty = y(f.price);
    if (!mark.ticks.includes(ty)) mark.ticks.push(ty);
  }

  const step = niceStep(hi0 - lo0);
  const priceTicks: { value: number; y: number }[] = [];
  if (prices.length && hi > lo) {
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) priceTicks.push({ value: v, y: y(v) });
  } else if (prices.length) {
    priceTicks.push({ value: lo0, y: y(lo0) });
  }

  const every = slot > 0 ? timeStep(slot) : 1;
  const timeTicks: { i: number; x: number; label: string }[] = [];
  bars.forEach((b, i) => {
    const m = minuteOf(b.time);
    if (m === null || m % every !== 0) return;
    const last = timeTicks[timeTicks.length - 1];
    if (last && xOf(i) - last.x < TIME_LABEL_PX) return;                   // 빠진 분 때문에 붙은 글자는 뺀다
    timeTicks.push({ i, x: xOf(i), label: b.time.slice(0, 5) });
  });

  return { axisW: CANDLE_AXIS, viewW, plotW, height, slot, bodyW, stub, price: { top: priceTop, bottom: priceBottom, lo, hi },
           vol: { top: volTop, bottom: volBottom, max: maxV }, candles, marks: [...groups.values()], unplaced, priceTicks, timeTicks };
}

/** '하루 전체' 띠 — 보이는 그림 폭(`viewW`)에 하루의 종가 선과 체결 자리를 줄여 그린다. 봉 i 의 자리 = (i + 0.5) × 칸 ÷ 그림 폭 × 띠 폭
 *  (보이는 구간 창 `overviewWindow` 와 같은 비례 — 창 안의 봉이 그림에 보이는 봉이다). 세로는 종가의 최소 ~ 최대(범위 0 이면 가운데). */
export function overviewLayout({ layout, bars, fills, height }: { layout: CandleLayout; bars: CandleBar[]; fills: CandleFill[]; height: number }) {
  const width = layout.viewW;
  const top = 4, bottom = Math.max(top, height - 4);
  const scale = layout.plotW > 0 ? width / layout.plotW : 0;
  const xs = bars.map((_, i) => (i + 0.5) * layout.slot * scale);
  const closes = bars.map((b) => b.close).filter((c) => Number.isFinite(c));
  const lo = closes.length ? Math.min(...closes) : 0, hi = closes.length ? Math.max(...closes) : 0;
  const ys = bars.map((b) => (hi > lo ? top + ((hi - b.close) / (hi - lo)) * (bottom - top) : (top + bottom) / 2));
  const at = new Map<string, number>();
  bars.forEach((b, i) => { if (!at.has(b.time)) at.set(b.time, i); });
  const ticks = fills.flatMap((f) => { const i = at.get(f.time); return i === undefined ? [] : [{ x: xs[i], side: f.side }]; });
  return { width, height, top, bottom, xs, ys, ticks };
}

/** 보이는 구간 창 — 틀의 넘긴 자리(`scrollLeft`)와 보이는 폭을 띠 폭으로 줄인 것. */
export function overviewWindow({ scrollLeft, clientWidth, plotW, stripW }: { scrollLeft: number; clientWidth: number; plotW: number; stripW: number }) {
  if (!(plotW > 0)) return { x: 0, w: stripW };
  const x = (Math.max(0, scrollLeft) / plotW) * stripW;
  return { x, w: Math.min(stripW - x, (clientWidth / plotW) * stripW) };
}

/** 지금 보이는 봉의 처음 · 끝(조금이라도 보이면 든다). */
export function visibleRange({ scrollLeft, clientWidth, slot, n }: { scrollLeft: number; clientWidth: number; slot: number; n: number }) {
  if (n <= 0 || !(slot > 0)) return { first: 0, last: -1 };
  const first = Math.min(n - 1, Math.max(0, Math.floor(scrollLeft / slot)));
  const last = Math.min(n - 1, Math.max(first, Math.ceil((scrollLeft + clientWidth) / slot) - 1));
  return { first, last };
}

/** 띠에서 누른 자리(x) → 그 자리의 봉 번호(가운데로 옮길 봉). */
export function barAtStrip({ x, stripW, plotW, slot, n }: { x: number; stripW: number; plotW: number; slot: number; n: number }): number {
  if (n <= 0 || !(stripW > 0) || !(slot > 0)) return 0;
  return Math.min(n - 1, Math.max(0, Math.floor(((x / stripW) * plotW) / slot)));
}
