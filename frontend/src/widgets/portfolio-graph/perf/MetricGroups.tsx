"use client";
/**
 * 지표 모두 보기 — 여섯 묶음(수익 · 위험 · 위험 대비 수익 · 분포 · 거래·회전 · 비용) (2026-11-09 · 캔버스 성과 그림 문법 §4.4)
 * ★서버 `summary`·`metrics` 그대로★ 못 잰 칸은 "산출 불가" 와 사유(표본 부족·0 분모 — `quant_metrics` 가 None 을 내는 조건) ·
 * 영어 약어는 처음 한 번 풀어 쓴다. 있는 칸만 그린다 — 뷰에 없는 묶음은 통째로 빠진다(지어내지 않는다).
 */
import { fmtNum, fmtPct, fmtSignedPct, type PerfView } from "./perfView";

type Fmt = "spct" | "pct" | "num" | "int" | "bool" | "days";
type Row = [key: string, label: string, fmt: Fmt];

// 세 노드의 서버 키가 조금씩 다르다(7번 `cagr_pct` · 불러오기 `cagr` · 전략 묶음 `annualized_return_pct`·`sharpe_ratio_full`) — 같은 뜻의
// 키를 같은 라벨로 적되 ★있는 키만★ 그린다. 한 뷰에 같은 뜻의 키가 둘 오면(7번은 `sharpe_ratio`(반올림)와 `sharpe_ratio_full`(전정밀도)을
// 함께 싣는다) 같은 라벨은 ★앞의 키만★ 그린다 — 같은 값이 두 줄로 보이지 않게.
const GROUPS: [title: string, rows: Row[]][] = [
  ["수익", [["total_return_pct", "총수익", "spct"], ["cagr_pct", "연 수익률", "spct"], ["cagr", "연 수익률", "spct"], ["annualized_return_pct", "연 수익률", "spct"],
    ["active_return_pct", "벤치마크 대비(연)", "spct"], ["best_period_pct", "가장 좋았던 하루", "spct"], ["worst_period_pct", "가장 나빴던 하루", "spct"]]],
  ["위험", [["volatility_pct", "변동성(연)", "pct"], ["downside_deviation_pct", "하방 변동성", "pct"], ["max_drawdown_pct", "가장 크게 빠진 폭", "pct"],
    ["avg_drawdown_pct", "평균 낙폭", "pct"], ["max_drawdown_days", "가장 오래 잠긴 기간", "days"], ["ulcer_index", "궤양 지수(낙폭의 깊이·길이)", "num"],
    ["var_pct", "VaR(하루 손실 한계 95%)", "pct"], ["cvar_pct", "CVaR(한계를 넘을 때 평균)", "pct"]]],
  ["위험 대비 수익", [["sharpe_ratio", "샤프(초과수익 ÷ 변동성)", "num"], ["sharpe_ratio_full", "샤프(초과수익 ÷ 변동성)", "num"],
    ["sortino_ratio", "소르티노(하방 변동성 기준)", "num"], ["calmar_ratio", "칼마(연 수익 ÷ 최대 낙폭)", "num"],
    ["information_ratio", "정보비율(벤치마크 대비)", "num"], ["omega", "오메가", "num"], ["gain_to_pain", "이익 ÷ 고통", "num"]]],
  ["분포", [["skew", "왜도(한쪽으로 치우침)", "num"], ["kurtosis", "첨도(꼬리 두께)", "num"], ["tail_ratio", "꼬리 비율(좋은 꼬리 ÷나쁜 꼬리)", "num"], ["recovery_factor", "회복 계수", "num"]]],
  ["거래·회전", [["n_rebalances", "리밸런싱 횟수", "int"], ["turnover_avg_pct", "평균 회전율(리밸런싱마다)", "pct"],
    ["num_trades", "거래 수", "int"], ["win_rate", "승률", "pct"], ["profit_factor", "손익비(번 돈 ÷ 잃은 돈)", "num"]]],
];
const NA = "산출 불가";

function cell(v: unknown, fmt: Fmt): { text: string; na: boolean } {
  if (fmt === "bool") return typeof v === "boolean" ? { text: v ? "적용" : "적용 안 함", na: false } : { text: NA, na: true };
  if (typeof v !== "number" || !Number.isFinite(v)) return { text: NA, na: true };
  if (fmt === "spct") return { text: fmtSignedPct(v, 2), na: false };
  if (fmt === "pct") return { text: fmtPct(v, 2), na: false };
  if (fmt === "int") return { text: `${Math.round(v).toLocaleString("ko-KR")}`, na: false };
  if (fmt === "days") return { text: `${Math.round(v)}일`, na: false };
  return { text: fmtNum(v, 2), na: false };
}

export function MetricGroups({ view, open = false, grid = false }: {
  view: PerfView;
  /** 시트에서는 펼쳐진 채로(묶음 여섯이 시트의 한 절) · 패널에서는 접혀서. */
  open?: boolean;
  /** 넓은 자리에서는 묶음을 여러 열로. */
  grid?: boolean;
}) {
  const src: Record<string, unknown> = { ...(view.metrics ?? {}), ...view.summary };
  if (view.cost.nRebalances !== null) src.n_rebalances = view.cost.nRebalances;
  if (view.cost.turnoverAvg !== null) src.turnover_avg_pct = view.cost.turnoverAvg;
  const groups = GROUPS.map(([title, rows]) => {
    const seen = new Set<string>();
    const kept: Row[] = [];
    for (const r of rows) { if (r[0] in src && !seen.has(r[1])) { seen.add(r[1]); kept.push(r); } }
    return [title, kept] as [string, Row[]];
  }).filter(([, rows]) => rows.length);
  const cost: Row[] = [];
  const costSrc: Record<string, unknown> = {};
  if (view.cost.bps !== null) { costSrc.cost_bps = view.cost.bps; cost.push(["cost_bps", "가정한 거래비용(bp, 한 번 사고팔 때)", "num"]); }
  if (view.cost.impact) {
    costSrc.applied = view.cost.impact.applied; cost.push(["applied", "참여율 충격 반영", "bool"]);
    if (view.cost.impact.applied === true) {
      costSrc.mean_bps = view.cost.impact.mean_bps; cost.push(["mean_bps", "충격 평균(bp)", "num"]);
      costSrc.total_cost_pct = view.cost.impact.total_cost_pct; cost.push(["total_cost_pct", "충격 비용 합", "pct"]);
    }
  }
  const all: [string, Row[], Record<string, unknown>][] = [
    ...groups.map(([t, r]) => [t, r, src] as [string, Row[], Record<string, unknown>]),
    ...(cost.length ? [["비용", cost, costSrc] as [string, Row[], Record<string, unknown>]] : []),
  ];
  if (!all.length) return null;
  const naCount = all.reduce((acc, [, rows, s]) => acc + rows.filter(([k, , f]) => cell(s[k], f).na).length, 0);
  const convention = typeof view.summary.convention === "string" ? view.summary.convention : null;
  return (
    <details className={`pf-metrics${grid ? " pf-metrics--grid" : ""}`} open={open || undefined}>
      <summary>지표 모두 보기{naCount ? ` (산출 불가 ${naCount}개)` : ""}</summary>
      <div className="pf-mbody">
        {all.map(([title, rows, s]) => (
          <section key={title} className="pf-mgroup">
            <h4 className="pg-h4">{title}</h4>
            {/* `.pg-kv` 는 안 붙인다 — ".pg-kv 총수익" 이 E2E 계약(BL3 W1 · 요약 숫자 하나)이라 묶음에도 붙이면 둘이 잡힌다. 모양은 같은 규칙(globals.css). */}
            <dl className="pf-mkv">
              {rows.map(([k, label, f]) => {
                const c = cell(s[k], f);
                return <div key={k}><dt>{label}</dt><dd className={c.na ? "pf-na" : undefined}>{c.text}</dd></div>;
              })}
            </dl>
          </section>
        ))}
      </div>
      {naCount > 0 && <p className="pg-note">‘산출 불가’는 표본이 모자라거나 나누는 수가 0 이라 서버가 값을 내지 않은 칸이에요 — 0 이 아니에요.</p>}
      {convention && <p className="pg-note">위험 대비 수익의 관례: {convention}</p>}
    </details>
  );
}
