// ═══════════════════════════════════════════════════════════════════════════════
// Realism Panel — Types + Mock Data
// Mirrors Stage 11 (/multibacktest/run) + Stage 12 (/realism/backtest) API shape
// ═══════════════════════════════════════════════════════════════════════════════

export interface BacktestSummary {
  total_return_pct: number;
  annualized_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  calmar_ratio: number;
  final_equity: number;
  total_trades: number;
  total_turnover_pct: number;
  n_rebalances: number;
  n_trading_days: number;
  netting_total_savings: number;
}

export interface RealismStats {
  total_market_impact_cost: number;
  total_cash_yield: number;
  total_buying_power_truncations: number;
  total_capacity_reallocations: number;
  cash_yield_annualized_pct: number;
  avg_market_impact_bps_per_rebalance: number;
  regime_mode_days: { normal: number; cautious: number; defensive: number };
  mode_distribution_pct: { normal: number; cautious: number; defensive: number };
  ewma_active_days: number;
  hard_cap_active_days: number;
  breakdown_detected_days: number;
}

export interface DailyRecord {
  date: string;
  portfolio_equity: number;
  cumulative_return: number;
  drawdown_pct: number;
  regime?: string;
  rebalanced?: boolean;
}

export interface BacktestResult {
  success: boolean;
  summary: BacktestSummary;
  daily_records: DailyRecord[];
  realism_stats?: RealismStats;
  n_trading_days: number;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Mock Data (실측값 기반 — 522일 × 3 전략 검증 결과)
// ═══════════════════════════════════════════════════════════════════════════════

const TRADING_DAYS = 522;
const INITIAL_CAPITAL = 10_000_000_000; // 100억

function generateEquityCurve(
  finalReturnPct: number,
  volatility: number,
  regimeChanges: { day: number; regime: string }[],
  seed: number,
): DailyRecord[] {
  // Seeded random
  let s = seed;
  const rand = () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };

  const startDate = new Date("2023-01-01");
  const dailyDrift = Math.pow(1 + finalReturnPct / 100, 1 / TRADING_DAYS) - 1;

  let equity = INITIAL_CAPITAL;
  let maxEq = equity;
  const records: DailyRecord[] = [];

  for (let i = 0; i < TRADING_DAYS; i++) {
    const d = new Date(startDate);
    d.setDate(d.getDate() + Math.floor(i * 1.4));
    const shock = (rand() - 0.5) * volatility;
    const ret = dailyDrift + shock;
    equity *= 1 + ret;
    maxEq = Math.max(maxEq, equity);

    // Regime determination
    let regime = "NORMAL";
    for (const change of regimeChanges) {
      if (i >= change.day) regime = change.regime;
    }

    records.push({
      date: d.toISOString().slice(0, 10),
      portfolio_equity: equity,
      cumulative_return: ((equity / INITIAL_CAPITAL) - 1) * 100,
      drawdown_pct: ((equity / maxEq) - 1) * 100,
      regime,
      rebalanced: i % 22 === 0, // 월별 리밸런싱
    });
  }

  return records;
}

const REGIME_TIMELINE = [
  { day: 0,    regime: "GOLDILOCKS" },
  { day: 95,   regime: "REFLATION" },
  { day: 180,  regime: "STAGFLATION" },
  { day: 230,  regime: "GOLDILOCKS" },
  { day: 340,  regime: "DEFLATION" },
  { day: 380,  regime: "STAGFLATION" },
  { day: 460,  regime: "GOLDILOCKS" },
];

export const MOCK_IDEAL: BacktestResult = {
  success: true,
  n_trading_days: TRADING_DAYS,
  summary: {
    total_return_pct: 77.57,
    annualized_return_pct: 31.94,
    sharpe_ratio: 2.564,
    max_drawdown_pct: -6.27,
    calmar_ratio: 5.10,
    final_equity: INITIAL_CAPITAL * 1.7757,
    total_trades: 1284,
    total_turnover_pct: 432.5,
    n_rebalances: 24,
    n_trading_days: TRADING_DAYS,
    netting_total_savings: 12_340_000,
  },
  daily_records: generateEquityCurve(77.57, 0.018, REGIME_TIMELINE, 42),
};

export const MOCK_REALITY: BacktestResult = {
  success: true,
  n_trading_days: TRADING_DAYS,
  summary: {
    total_return_pct: 65.18, // Eroded by ~12.4%
    annualized_return_pct: 27.13,
    sharpe_ratio: 2.18,
    max_drawdown_pct: -8.42,
    calmar_ratio: 3.22,
    final_equity: INITIAL_CAPITAL * 1.6518,
    total_trades: 1262,
    total_turnover_pct: 412.3,
    n_rebalances: 24,
    n_trading_days: TRADING_DAYS,
    netting_total_savings: 11_980_000,
  },
  daily_records: generateEquityCurve(65.18, 0.020, REGIME_TIMELINE, 42),
  realism_stats: {
    total_market_impact_cost: 87_500_000,    // 8750만원 비용
    total_cash_yield: 28_300_000,             // 2830만원 이자 수익
    total_buying_power_truncations: 9,
    total_capacity_reallocations: 14,
    cash_yield_annualized_pct: 1.41,
    avg_market_impact_bps_per_rebalance: 18.7,
    regime_mode_days: { normal: 462, cautious: 48, defensive: 12 },
    mode_distribution_pct: { normal: 88.5, cautious: 9.2, defensive: 2.3 },
    ewma_active_days: 60,
    hard_cap_active_days: 12,
    breakdown_detected_days: 8,
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// Computed KPIs — Realism Panel core metrics
// ═══════════════════════════════════════════════════════════════════════════════

export interface RealismKPIs {
  fidelityScore: number;          // Realistic CAGR / Ideal CAGR × 100
  totalAlphaErosionPct: number;   // Reality.total - Ideal.total
  annualCashYieldPct: number;
  orderFillProbabilityPct: number; // 100 - (truncations / total_rebalances × 100)
  marketImpactCostKrw: number;
  cashYieldKrw: number;
  capacityReallocs: number;
  defensiveDaysPct: number;
}

export function computeRealismKPIs(
  ideal: BacktestResult, reality: BacktestResult,
): RealismKPIs {
  const rs = reality.realism_stats!;
  return {
    fidelityScore: (reality.summary.annualized_return_pct / ideal.summary.annualized_return_pct) * 100,
    totalAlphaErosionPct: reality.summary.total_return_pct - ideal.summary.total_return_pct,
    annualCashYieldPct: rs.cash_yield_annualized_pct,
    orderFillProbabilityPct: 100 - (rs.total_buying_power_truncations / reality.summary.n_rebalances * 100),
    marketImpactCostKrw: rs.total_market_impact_cost,
    cashYieldKrw: rs.total_cash_yield,
    capacityReallocs: rs.total_capacity_reallocations,
    defensiveDaysPct: rs.mode_distribution_pct.defensive,
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Erosion Waterfall data
// ═══════════════════════════════════════════════════════════════════════════════

export interface WaterfallStep {
  label: string;
  value: number;    // % delta
  cumulative: number;
  kind: "start" | "negative" | "positive" | "end";
}

export function computeErosionWaterfall(
  ideal: BacktestResult, reality: BacktestResult,
): WaterfallStep[] {
  const idealReturn = ideal.summary.total_return_pct;
  const realReturn = reality.summary.total_return_pct;
  const totalErosion = realReturn - idealReturn;
  const rs = reality.realism_stats!;

  // 침식 요인들 (비율로 분해)
  const equity = INITIAL_CAPITAL;
  const marketImpactPct = -(rs.total_market_impact_cost / equity) * 100;
  const cashYieldPct = (rs.total_cash_yield / equity) * 100;

  // 잔여 침식을 capacity + buying_power로 분배
  const residual = totalErosion - marketImpactPct - cashYieldPct;
  const capacityPct = residual * 0.55;       // 추정 배분
  const buyingPowerPct = residual * 0.45;

  let cum = idealReturn;
  return [
    { label: "Ideal Return",     value: idealReturn,    cumulative: idealReturn, kind: "start" },
    { label: "Market Impact",    value: marketImpactPct, cumulative: (cum += marketImpactPct), kind: "negative" },
    { label: "Capacity Cap",     value: capacityPct,    cumulative: (cum += capacityPct),    kind: "negative" },
    { label: "Buying Power",     value: buyingPowerPct, cumulative: (cum += buyingPowerPct), kind: "negative" },
    { label: "Cash Yield",       value: cashYieldPct,   cumulative: (cum += cashYieldPct),   kind: "positive" },
    { label: "Realistic Return", value: realReturn,     cumulative: realReturn,              kind: "end" },
  ];
}

// ═══════════════════════════════════════════════════════════════════════════════
// Liquidity Capacity (per strategy)
// ═══════════════════════════════════════════════════════════════════════════════

export interface StrategyCapacity {
  id: number;
  name: string;
  utilization_pct: number;  // 사용량 / 수용량
  capacity_krw: number;
  used_krw: number;
  adv_pct: number;          // ADV 대비 비중
  status: "safe" | "warning" | "danger";
}

export const MOCK_CAPACITIES: StrategyCapacity[] = [
  { id: 1, name: "Momentum 전략",  utilization_pct: 42, capacity_krw: 80_000_000_000,  used_krw: 33_600_000_000, adv_pct: 2.1, status: "safe" },
  { id: 2, name: "Value 전략",     utilization_pct: 78, capacity_krw: 50_000_000_000,  used_krw: 39_000_000_000, adv_pct: 3.9, status: "warning" },
  { id: 3, name: "Quality 전략",   utilization_pct: 94, capacity_krw: 30_000_000_000,  used_krw: 28_200_000_000, adv_pct: 4.7, status: "danger" },
  { id: 4, name: "Low Vol 전략",   utilization_pct: 35, capacity_krw: 120_000_000_000, used_krw: 42_000_000_000, adv_pct: 1.8, status: "safe" },
];

// 포맷 헬퍼
export const fmtKrw = (v: number): string => {
  const abs = Math.abs(v);
  if (abs >= 100_000_000_000) return `${(v / 100_000_000_000).toFixed(2)}천억`;
  if (abs >= 1_000_000_000)   return `${(v / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000)        return `${(v / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)            return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
};

export const fmtPct = (v: number, decimals = 2, withSign = true): string => {
  const sign = withSign && v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(decimals)}%`;
};
