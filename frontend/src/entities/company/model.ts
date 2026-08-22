// 기업분석 도메인 모델 — 재무 시계열 · 밸류에이션 샌드박스 · 리스크 심화.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

export interface PriceBar { date: string; open: number; high: number; low: number; close: number; volume: number; trading_value?: number }
export interface FinancialHistoryRow { year: string; revenue_억: number | null; operating_profit_억: number | null; net_income_억: number | null; total_assets_억: number | null; total_equity_억: number | null; fcf_억: number | null; roe_pct: number | null; roa_pct: number | null; debt_ratio_pct: number | null; eps: number | null; bps: number | null; dps: number | null }
export interface FinancialHistory { stock_code: string; corp_name: string; sector: string; n_years: number; financials: FinancialHistoryRow[] }
export interface EvaluateOverrides { beta?: number; risk_free_rate?: number; market_premium?: number; terminal_growth?: number; projection_years?: number; market_cap?: number }
export interface SignalResp { stock_code: string; stock_name: string; action: string; strength: number; reason: string; is_actionable: boolean; is_strong: boolean; strategy: string }
export interface NarrativeResp { content: string; model: string; input_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number; cost_krw: number; elapsed_seconds: number; cached: boolean; error?: string | null }
export interface SymbolItem { code: string; name: string; market?: string; sector?: string; listing_date?: string }

// ── 기업분석 심화 (valuation-sandbox / financial-deep / risk-deep) ──
export interface SandboxAssumption { key: string; label: string; value: number; source: string }
export interface FootballBand {
  id: string; label: string; available?: boolean; note?: string;
  lo: number | null; hi: number | null; mid: number | null;
}
export interface CompsRow {
  code: string; name: string; mcap: number | null; per: number | null; pbr: number | null;
  ev_ebitda: number | null; roe: number | null; op_margin: number | null; rev_growth: number | null;
}
export interface ValuationSandbox {
  unified: { value: number; gap_pct: number; verdict: string;
    models: { model: string; value: number; available: boolean; error: string | null }[] };
  assumptions: SandboxAssumption[];
  sensitivity: { ke_axis: number[]; g_axis: number[]; grid: (number | null)[][]; current_price: number };
  defaults: { rf: number; beta: number; erp: number; g: number; years: number };
  football_field: { current_price: number; bands: FootballBand[] };
  comps: { sector?: string; rows: CompsRow[]; median_row: Partial<CompsRow>;
    implied: { per_based: number | null; pbr_based: number | null; ev_ebitda_based: number | null };
    scatter?: { code: string; name: string; upside: number; quality: number; self: boolean }[] };
}

export interface FinancialDeep {
  available: boolean; note?: string;
  qoe: { years: number[]; ni: number[]; ocf: number[]; gap: number[];
    accruals: (number | null)[]; red_flags: { rule: string; severity: string; msg: string }[] };
  nwc: { years: number[]; nwc: number[]; nwc_to_rev_pct: (number | null)[] };
  waterfall: { years: number[]; ocf: number[]; capex: number[]; dividends: number[];
    debt_delta: (number | null)[]; residual: number[]; note: string };
  dupont: { years: number[]; net_margin: (number | null)[]; asset_turnover: (number | null)[];
    leverage: (number | null)[]; roe: (number | null)[] };
  roic_wacc: { roic: number; wacc: number; spread: number; verdict: string; note: string } | null;
}

export interface RiskDeep {
  altman: { z: number | null; zone: string | null;
    components: { id: string; label: string; weight: number; value: number; contribution: number }[] };
  beneish: { available: boolean; note?: string; m_score: number | null; flag: string | null;
    indices: { id: string; label: string; value: number; basis: "real" | "approx" | "neutral" }[] };
  coverage: { years: number[]; interest_coverage: (number | null)[];
    net_debt_to_ebitda: (number | null)[]; note: string };
  rate_stress: { rows: { shock_bp: number; interest_coverage: number | null;
    dcf_value: number | null; unified_value: number | null }[]; note: string };
}
