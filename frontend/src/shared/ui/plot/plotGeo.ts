/**
 * 작은 그림의 기하 — 눈금·경로 (2026-11-10 · ADR 004 §2.3)
 * ==========================================================================
 * 직접 SVG 로 그리는 작은 그림(캔버스 결과의 프런티어·계단선·수익률 곡선)이 같이 쓰는 순수 함수. React·DOM 을 모른다.
 * 성과 그림의 기하(`shared/ui/perf/perfGeo.ts`)는 "순번 x · 솎기" 가 중심이라 따로 두고, 여기는 "값 x · 값 y" 다.
 */
export type XY = { x: number; y: number };

/** 정의역 [d0, d1] → 치역 [r0, r1]. 폭이 0 이면 가운데(나눗셈 가드). */
export function linScale(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  const span = d1 - d0;
  return span === 0 ? () => (r0 + r1) / 2 : (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** 보기 좋은 눈금 — 간격은 1·2·5×10^k, 양 끝 눈금이 자료를 감싼다. 자료가 한 값이면 그 둘레를 벌린다. */
export function niceTicks(lo: number, hi: number, n = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (hi < lo) [lo, hi] = [hi, lo];
  if (hi === lo) { const pad = Math.abs(lo) * 0.1 || 1; lo -= pad; hi += pad; }
  const raw = (hi - lo) / Math.max(1, n);                        // > 0 (위에서 벌렸다) — log10 가드
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const dec = Math.max(0, -Math.floor(Math.log10(step)));
  const i0 = Math.floor(lo / step + 1e-9), i1 = Math.ceil(hi / step - 1e-9);
  const out: number[] = [];
  for (let i = i0; i <= i1; i++) out.push(Number((i * step).toFixed(dec)));
  return out;
}

/** 눈금 글자의 소수 자리 — 간격이 1 이상이면 0, 아니면 간격이 보일 만큼. */
export function tickDecimals(ticks: number[]): number {
  if (ticks.length < 2) return 0;
  const step = Math.abs(ticks[1] - ticks[0]);
  return step >= 1 || step === 0 ? 0 : Math.min(4, Math.ceil(-Math.log10(step) - 1e-9));
}

/** 점들을 잇는 선. */
export function xyPath(pts: XY[]): string {
  return pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join("");
}

/** 순번 x 의 꺾은선 — 값이 없는 점(null)에서 끊는다(0 으로 잇지 않는다). */
export function gapPath(xs: number[], ys: (number | null)[]): string {
  let d = "", pen = false;
  for (let i = 0; i < xs.length; i++) {
    const y = ys[i];
    if (y === null) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${xs[i].toFixed(1)},${y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** 계단선 — 값이 다음 점까지 이어진 뒤 바뀐다(stepAfter). 값이 없는 점에서 끊는다. */
export function stepPath(xs: number[], ys: (number | null)[]): string {
  let d = "", pen = false;
  for (let i = 0; i < xs.length; i++) {
    const y = ys[i];
    if (y === null) { pen = false; continue; }
    d += pen ? `H${xs[i].toFixed(1)}V${y.toFixed(1)}` : `M${xs[i].toFixed(1)},${y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** 스파크라인의 점 — 유한한 값만 쓴다(모르는 기간은 건너뛴다 · 0 으로 끌어내리지 않는다). 값이 둘 미만이면 null — 선을 지어내지 않는다.
 *  값이 모두 같으면 가운데 가로선(바닥에 붙이면 "가장 낮다"로 읽힌다). `pad` 는 끝 점이 잘리지 않을 여백(px). */
export function sparkPoints(values: ReadonlyArray<number | null | undefined>, w: number, h: number, pad = 3): XY[] | null {
  const v = values.filter((x): x is number => typeof x === "number" && Number.isFinite(x));
  if (v.length < 2) return null;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo;
  return v.map((x, i) => ({ x: pad + (i / (v.length - 1)) * (w - 2 * pad), y: span === 0 ? h / 2 : h - pad - ((x - lo) / span) * (h - 2 * pad) }));
}
