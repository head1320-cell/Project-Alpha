/**
 * 현실성 점검 (ST3c · 실거래 [현실성 점검] 탭) — `/api/v1/realism/backtest` 를 두 번 부른다.
 * ==========================================================================
 * ★이상 = 현실 조건 다섯을 모두 끈 같은 계산★, 현실 = 시장 충격·현금 이자·매수 여력·적응 모드를 켠 계산(용량 제약은 서버 기본 꺼짐).
 * 옛 화면은 이상 쪽을 `/multibacktest/run` 으로 따로 돌렸다 — 그 경로를 지우며 두 엔진의 일별 자산이 같음을
 * `tests/test_realism_ideal_equivalence.py` 가 건다. 옛 MOCK 수치·클라이언트 상수(×1e10·0.55/0.45 분배 등)는 없다.
 * 응답은 서버 그대로 — 빠진 칸은 null(몰라요), 0 으로 메우지 않는다.
 */
import { extractErrorDetail, postJson } from "@/shared/api/apiBase";
import { unavailableReason } from "./unavailable";

/** 화면이 보내는 조리법 — 옛 화면의 요청 상수 그대로(기간·자본·배분·리밸런싱). 전략 id 만 등록 목록에서 온다. */
export const RECIPE = {
  start_date: "2023-01-01", end_date: "2024-12-31", initial_capital: 10_000_000_000,
  allocation_method: "hrp", rebalance_policy: "monthly", macro_overlay_enabled: false,
} as const;
export const IDEAL_FLAGS = {
  enable_market_impact: false, enable_cash_yield: false, enable_buying_power_check: false,
  enable_capacity_constraint: false, enable_regime_adaptive: false,
} as const;
export const REAL_FLAGS = {
  enable_market_impact: true, enable_cash_yield: true, enable_buying_power_check: true, enable_regime_adaptive: true,
} as const;

export type RealismRecord = { date: string; portfolio_equity: number | null; weights?: Record<string, number> | null };
export type RealismStats = {
  total_market_impact_cost?: number | null; total_cash_yield?: number | null;
  total_buying_power_truncations?: number | null; total_capacity_reallocations?: number | null;
  avg_market_impact_bps_per_rebalance?: number | null; cash_yield_annualized_pct?: number | null;
  mode_distribution_pct?: Record<string, number> | null;
};
export type RealismRun = {
  success: true;
  summary: { total_return_pct?: number | null; annualized_return_pct?: number | null; max_drawdown_pct?: number | null;
    final_equity?: number | null; n_rebalances?: number | null; n_trading_days?: number | null };
  realism_stats: RealismStats;
  regime_adaptive?: { enabled?: boolean; basis?: string | null; reason?: string | null } | null;
  daily_records: RealismRecord[];
  strategy_names?: Record<string, string> | null;
  perf_label?: { kind: string; kind_reason?: string | null; data_real: boolean | null; data_reason?: string | null } | null;
  config?: Record<string, unknown> | null;
};
export type Side = { ok: true; run: RealismRun } | { ok: false; reason: string };

/** 한 번 부르기. 서버가 200 + `success:false` 로 답하면 그 `message` 가 사유다(실패로 그린다). */
export async function runRealism(strategyIds: number[], flags: Record<string, boolean>): Promise<Side> {
  try {
    const r = await postJson("/api/v1/realism/backtest", { strategy_ids: strategyIds, ...RECIPE, ...flags });
    const body = await r.json().catch(() => null);
    if (!r.ok) return { ok: false, reason: unavailableReason(body) ?? extractErrorDetail(body, `서버가 ${r.status} 로 답했어요. 사유를 받지 못했어요.`) };
    if (!body?.success) return { ok: false, reason: String(body?.message ?? "서버가 계산하지 못했다고 답했어요. 사유를 받지 못했어요.") };
    return { ok: true, run: body as RealismRun };
  } catch {
    return { ok: false, reason: "서버에 닿지 못했어요." };
  }
}

/** 두 곡선을 ★날짜로★ 맞춘다(옛 화면은 순번으로 맞췄다). 한쪽에만 있는 날은 다른 쪽이 null. */
export type Joined = { date: string; ideal: number | null; real: number | null; band: [number, number] | null };
export function joinByDate(ideal: RealismRecord[], real: RealismRecord[]): { rows: Joined[]; missingReal: number; missingIdeal: number } {
  const a = new Map(ideal.map((r) => [r.date, r.portfolio_equity]));
  const b = new Map(real.map((r) => [r.date, r.portfolio_equity]));
  const dates = [...new Set([...a.keys(), ...b.keys()])].sort();
  let missingReal = 0; let missingIdeal = 0;
  const rows = dates.map((d) => {
    const i = a.get(d) ?? null; const r = b.get(d) ?? null;
    if (i === null) missingIdeal += 1;
    if (r === null) missingReal += 1;
    return { date: d, ideal: i, real: r, band: i !== null && r !== null ? [Math.min(i, r), Math.max(i, r)] as [number, number] : null };
  });
  return { rows, missingReal, missingIdeal };
}

/**
 * 원화 폭포 — 이상 끝 → 시장 충격 비용 → 현금 이자 → 나머지 → 현실 끝. ★서버가 센 두 원화만 따로 세운다★.
 * 나머지 = 현실 끝 − 이상 끝 + 충격 − 이자 (매수 여력·적응 모드·복리가 섞인 몫 — 서버가 나누지 않았다).
 * 끝 값 하나라도 모르면 null(지어내지 않는다). 충격·이자를 모르면 그 단계도 null 이고 나머지를 내지 않는다.
 */
export type Step = { key: "ideal" | "impact" | "cash" | "rest" | "real"; value: number };
export function erosionKrw(ideal: RealismRun, real: RealismRun): Step[] | null {
  const i = ideal.summary.final_equity; const r = real.summary.final_equity;
  const imp = real.realism_stats.total_market_impact_cost; const cash = real.realism_stats.total_cash_yield;
  if (i == null || r == null || imp == null || cash == null) return null;
  return [
    { key: "ideal", value: i }, { key: "impact", value: -Math.abs(imp) }, { key: "cash", value: cash },
    { key: "rest", value: r - i + Math.abs(imp) - cash }, { key: "real", value: r },
  ];
}
