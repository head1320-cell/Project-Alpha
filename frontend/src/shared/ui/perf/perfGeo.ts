/**
 * 성과 그림의 기하 도우미 — PerfCurve(곡선 하나)와 PerfCompare(둘 겹쳐 보기)가 같이 쓴다 (2026-11-09 · 성과 그림 문법 ③ §3.2)
 * ==========================================================================
 * 자리(세로축·끝값 라벨) · 글자 폭 어림 · 솎기(양 끝·최고·최저·낙폭 바닥은 반드시) · 선·면 경로(값이 null 인 날은 끊는다).
 * PerfCurve 에서 옮기기만 했다 — 동작 불변(캔버스·결과 화면 E2E 가 지킨다).
 */
import type { PerfPoint } from "./perfView";

export const L_MIN = 46;      // 세로축 글자 자리(최소 — 라벨이 길면 넓힌다 · 원 단위 "9,983만원")
export const R_MIN = 58;      // 오른쪽 끝 값 라벨 자리(최소)
export const TOP = 10;
/** 글자 폭 어림(11px 글꼴) — 한글 11px · 쉼표·점 3.5px · 그 밖 6.3px. 자리를 라벨에 맞추려고 잰다(잘리지 않게). */
export const textW = (s: string) => [...s].reduce((w, ch) => w + (/[가-힣]/.test(ch) ? 11 : /[,.]/.test(ch) ? 3.5 : 6.3), 0);
export const STRIP_H = 14;
export const XLAB_H = 16;
export const GAP = 8;

export const day = (s: string) => Date.parse(s.slice(0, 10));
export const days = (a: string, b: string) => Math.max(0, Math.round((day(b) - day(a)) / 86_400_000));

/** 솎기 — 폭에 맞춰 고르게, ★양 끝·최고점·최저점·낙폭 바닥★은 반드시. */
export function pickIndexes(n: number, maxPts: number, must: number[]): number[] {
  const set = new Set<number>();
  if (n <= maxPts) for (let i = 0; i < n; i++) set.add(i);
  else { const step = (n - 1) / (maxPts - 1); for (let i = 0; i < maxPts; i++) set.add(Math.round(i * step)); }
  for (const m of must) if (m >= 0 && m < n) set.add(m);
  return [...set].sort((a, b) => a - b);
}

export function argExt(vals: PerfPoint[], pick: "max" | "min"): number {
  let best = -1;
  for (let i = 0; i < vals.length; i++) {
    const v = vals[i];
    if (v === null) continue;
    if (best < 0 || (pick === "max" ? v > (vals[best] as number) : v < (vals[best] as number))) best = i;
  }
  return best;
}

/** 선 경로 — 값이 null 인 날은 끊는다(0 으로 잇지 않는다). */
export function linePath(idx: number[], vals: PerfPoint[], x: (i: number) => number, y: (v: number) => number): string {
  let d = "";
  let pen = false;
  for (const i of idx) {
    const v = vals[i];
    if (v === null) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** 면 경로 — 이어진 구간마다 기준선으로 닫는다. */
export function areaPath(idx: number[], vals: PerfPoint[], x: (i: number) => number, y: (v: number) => number, y0: number): string {
  let d = "";
  let run: number[] = [];
  const flush = () => {
    if (run.length) {
      d += `M${x(run[0]).toFixed(1)} ${y0.toFixed(1)}`;
      for (const i of run) d += `L${x(i).toFixed(1)} ${y(vals[i] as number).toFixed(1)}`;
      d += `L${x(run[run.length - 1]).toFixed(1)} ${y0.toFixed(1)}Z`;
    }
    run = [];
  };
  for (const i of idx) { if (vals[i] === null) flush(); else run.push(i); }
  flush();
  return d;
}
