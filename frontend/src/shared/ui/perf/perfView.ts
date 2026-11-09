/**
 * 성과 뷰 — 세 노드(과거로 돌려 보기 · 백테스트 불러오기 · 전략 묶음)의 서버 뷰를 ★한 모양으로 옮기기만★ 한다 (2026-11-09)
 * ==========================================================================
 * 설계 `docs/superpowers/specs/2026-11-09-canvas-performance-viz-design.md`. 여기서는 수를 만들지 않는다 — 곡선·날짜·리밸런싱·기준일·
 * 기간별 수익·낙폭 사건·지표를 서버가 준 그대로 고르고, 없는 것은 `null` 로 둔다(화면이 "없다" 고 말한다). 하는 것은 숫자·단위 서식뿐
 * (ADR-003 §2.6 이 허용하는 클라이언트 일).
 */
import { krAxisTick } from "@/shared/lib/krFormat";
import type { PerfLabelValue } from "@/shared/ui/PerfLabel";

/** 서버 explain 의 모양(캔버스 `NodeExplain` 과 구조가 같다 — shared 는 entities 를 모른다 · 캔버스는 NodeExplain 을 그대로 넘긴다). */
export interface PerfExplain {
  title: string;
  headline?: { label: string; value: number | null; unit: string; text: string } | null;
  facts?: string[];
  trust?: { state: string; text: string; kind?: string }[];
  unmeasured?: string[];
}

type Dict = Record<string, unknown>;
export type PerfPoint = number | null;
/** 세로축 단위 — `x` 처음을 1로 · `krw` 원 · `base100` 처음을 100으로(/macro 전략 곡선 · 비교 화면이 서버에 base 100 으로 청한 곡선). */
export type PerfUnit = "x" | "krw" | "base100";

export interface YearRow { year: number; return_pct: number; max_drawdown_pct: number; n_days: number; partial: boolean }
export interface MonthRow { year: number; month: number; return_pct: number; n_days: number; partial: boolean }
export interface DdEpisode {
  peak_date: string; trough_date: string; recovery_date: string | null; depth_pct: number;
  days_to_trough: number; days_to_recover: number | null;
}
export interface PerfFigure { key: string; label: string; text: string; tone?: "up" | "down" | null }

export interface PerfView {
  /** 세로축 단위 — 7번은 "처음을 1로"(×), 불러오기·전략 묶음은 원. 서버 뷰가 정한 대로. */
  unit: PerfUnit;
  dates: string[];
  equity: PerfPoint[];
  bench: PerfPoint[] | null;
  benchLabel: string | null;
  drawdown: PerfPoint[] | null;
  /** 벤치마크의 낙폭(%) — 스트레스 과거 재생이 준다. 낙폭 패널에 회색 선으로. 없으면 그리지 않는다. */
  benchDrawdown?: PerfPoint[] | null;
  /** 서버가 그림 옆에 적어 달라고 준 글(예: /macro 전략의 "달 라벨은 … 어림이에요"). 띠 범례에 그대로. */
  note?: string | null;
  rebalances: { date: string; turnover_pct: number | null; gross_pct: number | null; net_pct: number | null; impact_bps: number | null }[];
  /** 이 결과가 답하는 질문(전달) — 질문 띠가 적는다. 노드마다 한 문장. */
  question: string;
  /** 수익률 자료의 첫 날 — 곡선 첫 날보다 앞이면 그 사이는 배우기만 한 구간. */
  learnFrom: string | null;
  asOf: string | null;
  /** 합성 데이터인가 — `perf_label.data_real` 가 false 면 true · true 면 false · 모르면 null. */
  practice: boolean | null;
  perfLabel: PerfLabelValue | null;
  periods: { yearly: YearRow[]; monthly: MonthRow[] } | null;
  drawdowns: DdEpisode[] | null;
  figures: PerfFigure[];
  summary: Dict;
  metrics: Dict | null;
  cost: { bps: number | null; impact: Dict | null; nRebalances: number | null; turnoverAvg: number | null };
  explain: PerfExplain | null;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const pts = (v: unknown): PerfPoint[] | null =>
  Array.isArray(v) ? v.map((x) => (typeof x === "number" && Number.isFinite(x) ? x : null)) : null;

// ── 서식 (수를 만들지 않는다 — 보이는 글자만) ──────────────────────────────────
export const fmtSignedPct = (v: number | null, d = 1): string =>
  v === null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(d)}%`;
export const fmtPct = (v: number | null, d = 1): string => (v === null ? "—" : `${v.toFixed(d)}%`);
export const fmtNum = (v: number | null, d = 2): string => (v === null ? "—" : v.toFixed(d));
export const fmtX = (v: number | null): string => (v === null ? "—" : `×${v.toFixed(2)}`);
export function fmtWon(v: number | null): string {
  if (v === null) return "—";
  const a = Math.abs(v);
  const s = v < 0 ? "−" : "";
  if (a >= 1e8) return `${s}${(a / 1e8).toFixed(1)}억원`;
  if (a >= 1e4) return `${s}${Math.round(a / 1e4).toLocaleString("ko-KR")}만원`;
  return `${s}${Math.round(a).toLocaleString("ko-KR")}원`;
}
export const fmtValue = (unit: PerfUnit, v: number | null): string =>
  (unit === "x" ? fmtX(v) : unit === "base100" ? fmtNum(v, 1) : fmtWon(v));
/** 차이(%p) — 부호와 함께. */
export const fmtSignedPp = (v: number | null, d = 1): string =>
  v === null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(d)}%p`;
/** 세로축 눈금 서식 — 원은 한 단위(만·억)로 짧게, 처음을 100으로는 정수, 처음을 1로는 ×. */
export function tickFormatter(unit: PerfUnit, hi: number, lo: number): (v: number) => string {
  if (unit === "krw") return krAxisTick(Math.max(Math.abs(hi), Math.abs(lo)));
  if (unit === "base100") return (v) => fmtNum(v, 0);
  return (v) => fmtX(v);
}
/** 기준선 — 처음을 1로는 1 · 처음을 100으로는 100 · 원은 첫 값. */
export const baselineOf = (unit: PerfUnit, first: number | null): number | null =>
  (unit === "x" ? 1 : unit === "base100" ? 100 : first);
/** 누적 수익률(%) — 곡선의 첫 값 대비. 첫 값이 0 이거나 모르면 null. */
export const cumPct = (first: number | null, v: number | null): number | null =>
  first === null || v === null || first <= 0 ? null : (v / first - 1) * 100;

function practiceOf(pl: PerfLabelValue | null): boolean | null {
  if (!pl || typeof pl.data_real !== "boolean") return null;
  return pl.data_real === false;
}

function periodsOf(v: unknown): PerfView["periods"] {
  const p = v as { yearly?: unknown; monthly?: unknown } | null | undefined;
  if (!p || !Array.isArray(p.yearly) || !Array.isArray(p.monthly)) return null;
  return { yearly: p.yearly as YearRow[], monthly: p.monthly as MonthRow[] };
}

function tone(v: number | null): "up" | "down" | null { return v === null ? null : v >= 0 ? "up" : "down"; }

/** 7번 과거로 돌려 보기(정책 walk-forward · `allocation_backtest.walk_forward`) — 곡선은 "처음을 1로". */
export function perfViewOfBacktest(v: Dict, prov: Dict, explain: PerfExplain | null | undefined): PerfView {
  const s = (v.summary as Dict) ?? {};
  const cov = (v.coverage as Dict) ?? {};
  const cfg = (v.config as Dict) ?? {};
  const pl = (prov.perf_label ?? v.perf_label) as PerfLabelValue | null;
  const dates = Array.isArray(v.dates) ? (v.dates as string[]).map(String) : [];
  const bench = pts(v.bench_curve);
  const active = num(s.active_return_pct);
  const figures: PerfFigure[] = [
    { key: "total", label: "총수익", text: fmtSignedPct(num(s.total_return_pct)), tone: tone(num(s.total_return_pct)) },
    { key: "mdd", label: "가장 크게 빠진 폭", text: fmtPct(num(s.max_drawdown_pct)), tone: num(s.max_drawdown_pct) === null ? null : "down" },
    { key: "sharpe", label: "위험 대비 수익(샤프)", text: fmtNum(num(s.sharpe_ratio)) },
    ...(bench ? [{ key: "active", label: `${str(v.benchmark_label) ?? "벤치마크"} 대비(연)`, text: fmtSignedPct(active), tone: tone(active) }] : []),
  ];
  const learnFrom = str(cov.start);
  return {
    unit: "x", dates, equity: pts(v.equity_curve) ?? [], bench, benchLabel: str(v.benchmark_label),
    drawdown: pts(v.drawdown_curve),
    rebalances: Array.isArray(v.rebalances)
      ? (v.rebalances as Dict[]).map((r) => ({ date: String(r.date ?? ""), turnover_pct: num(r.turnover_pct), gross_pct: num(r.gross_pct),
                                                 net_pct: num(r.net_pct), impact_bps: num(r.impact_bps) })).filter((r) => r.date)
      : [],
    question: "과거에 이 규칙대로 비중을 전달했다면 어땠나",
    learnFrom: learnFrom && dates[0] && learnFrom < dates[0] ? learnFrom : null,
    asOf: str(cov.as_of_effective), practice: practiceOf(pl), perfLabel: pl,
    periods: periodsOf(v.periods), drawdowns: Array.isArray(v.drawdowns) ? (v.drawdowns as DdEpisode[]) : null,
    figures, summary: s, metrics: (v.metrics as Dict | null) ?? null,
    cost: { bps: num(cfg.cost_bps), impact: (v.impact as Dict | null) ?? null, nRebalances: num(v.n_rebalances), turnoverAvg: num(v.turnover_avg_pct) },
    explain: explain ?? null,
  };
}

/** 백테스트 불러오기(BL3 W1 · 저장된 실행) — 곡선은 원. 낙폭은 서버 뷰가 % 로 옮겨 준 `drawdown_pct`(저장된 결과에 있을 때만). */
export function perfViewOfLoad(v: Dict, prov: Dict, explain: PerfExplain | null | undefined): PerfView {
  const s = (v.statistics as Dict) ?? {};
  const eq = (v.equity as { dates?: unknown; values?: unknown }) ?? {};
  const bm = (v.benchmark as Dict | null) ?? null;
  const pl = (prov.perf_label ?? v.perf_label) as PerfLabelValue | null;
  const dates = Array.isArray(eq.dates) ? (eq.dates as unknown[]).map(String) : [];
  const bench = bm ? pts(bm.curve) : null;
  const figures: PerfFigure[] = [
    { key: "total", label: "총수익", text: fmtSignedPct(num(s.total_return_pct)), tone: tone(num(s.total_return_pct)) },
    { key: "mdd", label: "가장 크게 빠진 폭", text: fmtPct(num(s.max_drawdown_pct)), tone: num(s.max_drawdown_pct) === null ? null : "down" },
    { key: "sharpe", label: "위험 대비 수익(샤프)", text: fmtNum(num(s.sharpe_ratio)) },
    ...(bm && num(bm.excess_return_pct) !== null
      ? [{ key: "active", label: `${str(bm.label) ?? "벤치마크"} 대비`, text: fmtSignedPct(num(bm.excess_return_pct)), tone: tone(num(bm.excess_return_pct)) }] : []),
  ];
  return {
    unit: "krw", dates, equity: pts(eq.values) ?? [], bench: bench && bench.length === dates.length ? bench : null,
    benchLabel: bm ? str(bm.label) : null, drawdown: pts(v.drawdown_pct),
    rebalances: [], question: "저장된 조건식 백테스트가 과거에 어떤 성과를 냈나",
    learnFrom: null, asOf: null, practice: practiceOf(pl), perfLabel: pl,
    periods: periodsOf(v.periods), drawdowns: Array.isArray(v.drawdowns) ? (v.drawdowns as DdEpisode[]) : null,
    figures, summary: s, metrics: null,
    cost: { bps: null, impact: null, nRebalances: null, turnoverAvg: null },
    explain: explain ?? null,
  };
}

/** 전략 묶음(BK W5 · `multibacktest_run`) — 곡선은 계좌 금액(원) · 낙폭은 기록마다 `dd`. */
export function perfViewOfStrategy(v: Dict, explain: PerfExplain | null | undefined): PerfView {
  const s = (v.summary as Dict) ?? {};
  const curve = Array.isArray(v.curve) ? (v.curve as Dict[]) : [];
  const pl = (v.perf_label as PerfLabelValue | null) ?? null;
  const annual = num(s.annualized_return_pct);
  const figures: PerfFigure[] = [
    { key: "total", label: "총수익", text: fmtSignedPct(num(s.total_return_pct)), tone: tone(num(s.total_return_pct)) },
    { key: "annual", label: "연 수익률", text: fmtSignedPct(annual), tone: tone(annual) },
    { key: "mdd", label: "가장 크게 빠진 폭", text: fmtPct(num(s.max_drawdown_pct)), tone: num(s.max_drawdown_pct) === null ? null : "down" },
    { key: "sharpe", label: "위험 대비 수익(샤프)", text: num(s.sharpe_ratio_full) === null ? "계산 못 함" : fmtNum(num(s.sharpe_ratio_full)) },
  ];
  return {
    unit: "krw", dates: curve.map((r) => String(r.date ?? "")), equity: curve.map((r) => num(r.equity)),
    bench: null, benchLabel: null, drawdown: curve.map((r) => num(r.dd)),
    rebalances: [], question: "등록된 전략들을 한 계좌처럼 나눠 담았다면 어땠나",
    learnFrom: null, asOf: null, practice: practiceOf(pl), perfLabel: pl,
    periods: periodsOf(v.periods), drawdowns: Array.isArray(v.drawdowns) ? (v.drawdowns as DdEpisode[]) : null,
    figures, summary: s, metrics: null,
    cost: { bps: null, impact: null, nRebalances: num(s.n_rebalances), turnoverAvg: null },
    explain: explain ?? null,
  };
}

// ── 둘 겹쳐 보기 (2026-11-09 · 성과 그림 문법 ③ §3.2) ─────────────────────────
/** 서버 `POST /api/v1/perf/compare` 의 응답 — 비교 화면·현실성 탭이 받고, 캔버스 비교 노드 뷰의 `compare.curves` 도 같은 모양. */
export interface CompareCurves {
  alignment: "date" | "index"; x: string[]; n: number; common: number; missing_a: number; missing_b: number;
  base: number; a: PerfPoint[]; b: PerfPoint[]; diff_pp: PerfPoint[]; note: string | null;
}
export interface YearDiffRow { year: number; a_return_pct: number | null; b_return_pct: number | null; diff_pp: number | null; a_partial: boolean; b_partial: boolean }
export interface MetricDiffRow { key: string; label: string; unit: string; a: number | null; b: number | null; diff: number | null }
export interface CompareResponse { curves: CompareCurves; yearly: YearDiffRow[] | null; rows: MetricDiffRow[] | null }

export interface PerfCompareView {
  unit: PerfUnit;
  /** 서버가 맞춘 x — 날짜(ISO) 또는 "n일째". */
  x: string[];
  alignment: "date" | "index";
  /** 서버가 준 정렬 글(순번으로 맞췄다 · 한쪽에 없는 날이 있다). 없으면 null. */
  note: string | null;
  base: number;
  a: { label: string; values: PerfPoint[] };
  b: { label: string; values: PerfPoint[] };
  /** 차이 = B − A (%p) — 서버가 뺐다. */
  diffPp: PerfPoint[];
  missingA: number;
  missingB: number;
  /** 한쪽이라도 연습용이면 true · 둘 다 실제면 false · 모르면 null. */
  practice: boolean | null;
  perfLabelA: PerfLabelValue | null;
  perfLabelB: PerfLabelValue | null;
  question: string;
  yearly: YearDiffRow[] | null;
  drawdowns: { a: DdEpisode[] | null; b: DdEpisode[] | null } | null;
}

export function compareViewOf(resp: CompareResponse, meta: {
  unit: PerfUnit; labelA: string; labelB: string; perfLabelA?: PerfLabelValue | null; perfLabelB?: PerfLabelValue | null;
  question: string; drawdownsA?: DdEpisode[] | null; drawdownsB?: DdEpisode[] | null;
  /** 라벨 대신 서버가 연습용 여부를 바로 줄 때(캔버스 비교 노드 `compare.mock`). */
  practice?: boolean | null;
}): PerfCompareView {
  const c = resp.curves;
  const pa = practiceOf(meta.perfLabelA ?? null);
  const pb = practiceOf(meta.perfLabelB ?? null);
  const practice = meta.practice !== undefined ? meta.practice
    : pa === true || pb === true ? true : pa === false && pb === false ? false : null;
  return {
    unit: meta.unit, x: c.x.map(String), alignment: c.alignment, note: c.note ?? null, base: c.base,
    a: { label: meta.labelA, values: pts(c.a) ?? [] }, b: { label: meta.labelB, values: pts(c.b) ?? [] },
    diffPp: pts(c.diff_pp) ?? [], missingA: c.missing_a, missingB: c.missing_b, practice,
    perfLabelA: meta.perfLabelA ?? null, perfLabelB: meta.perfLabelB ?? null, question: meta.question,
    yearly: Array.isArray(resp.yearly) ? resp.yearly : null,
    drawdowns: meta.drawdownsA === undefined && meta.drawdownsB === undefined ? null
      : { a: meta.drawdownsA ?? null, b: meta.drawdownsB ?? null },
  };
}

/** 스트레스 과거 재생(`historical_replay`) — 자산곡선은 "처음을 1로"(첫 점 = 1 + 첫날 수익) · 벤치마크 곡선·낙폭 둘 · 낙폭 사건. */
export function perfViewOfStress(r: Dict, prov: Dict): PerfView {
  const pl = (prov.perf_label ?? null) as PerfLabelValue | null;
  const dates = Array.isArray(r.dates) ? (r.dates as string[]).map(String) : [];
  return {
    unit: "x", dates, equity: pts(r.equity_curve) ?? [], bench: pts(r.benchmark_curve), benchLabel: str(r.benchmark_label),
    drawdown: pts(r.portfolio_dd), benchDrawdown: pts(r.benchmark_dd), rebalances: [],
    question: "오늘의 비중을 그 기간에 고정했다면 어땠나", learnFrom: null, asOf: null,
    practice: practiceOf(pl), perfLabel: pl, periods: null,
    drawdowns: Array.isArray(r.drawdowns) ? (r.drawdowns as DdEpisode[]) : null,
    figures: [], summary: {}, metrics: null, cost: { bps: null, impact: null, nRebalances: null, turnoverAvg: null }, explain: null,
  };
}
