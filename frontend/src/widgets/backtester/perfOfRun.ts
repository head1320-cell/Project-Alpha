/**
 * 백테스트 실행 응답 → `PerfView` (2026-11-09 · 결과 화면 성과 그림 문법 §3.3) — ★옮기기만★: 곡선(원)·벤치마크·서버 `perf` 의 % 낙폭·
 * 기간별·낙폭 사건·연습용 여부. 리밸런싱 날짜·배움 구간·기준일은 이 엔진에 없다(모름 ≠ 0 — 띠는 말하지 않는다).
 */
import type { RunFull } from "@/entities/backtest-run/api";
import type { PerfView } from "@/shared/ui/perf/perfView";

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pts = (v: unknown): (number | null)[] | null => (Array.isArray(v) ? v.map((x) => num(x)) : null);

export function perfViewOfRun(run: RunFull): PerfView {
  const bt = run.result?.backtest;
  const dates = (bt?.equity_dates ?? []).map(String);
  const equity = pts(bt?.equity_curve) ?? [];
  const benchRaw = pts(bt?.benchmark?.curve);
  const perf = run.perf ?? null;
  const pl = run.perf_label ?? null;
  return {
    unit: "krw", dates, equity,
    bench: benchRaw && benchRaw.length === dates.length ? benchRaw : null,
    benchLabel: bt?.benchmark?.label ?? null,
    drawdown: perf ? pts(perf.drawdown_pct) : null,
    rebalances: [], question: "이 조건식이 과거에 어떤 성과를 냈나",
    learnFrom: null, asOf: null,
    practice: pl && typeof pl.data_real === "boolean" ? pl.data_real === false : null,
    perfLabel: pl,
    periods: perf ? perf.periods : null,
    drawdowns: perf ? perf.drawdowns : null,
    figures: [], summary: {}, metrics: null,
    cost: { bps: null, impact: null, nRebalances: null, turnoverAvg: null },
    explain: null,
  };
}
