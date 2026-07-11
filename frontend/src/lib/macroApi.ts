/**
 * Macro API Client — Phase 4
 * ==========================================================================
 */

import { API_BASE } from "@/lib/apiBase";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface MacroSeries {
  indicator: string;
  name: string;
  unit: string;
  source: "BOK" | "FRED" | "MOCK";
  timestamps: string[];
  values: number[];
  latest: number | null;
  prev: number | null;
  yoy: number | null;
  mom_pct: number | null;
  z_score: number | null;
  percentile: number | null;
  mean_5y: number | null;
  std_5y: number | null;
  trend: "up" | "down" | "flat";
  last_update?: string;
}

export interface MacroSnapshot {
  timestamp: string;
  series: Record<string, MacroSeries>;
  count: number;
}

export type Regime = "Goldilocks" | "Reflation" | "Stagflation" | "Disinflation";

export interface YieldCurvePoint {
  label: string;
  years: number;
  yield_pct: number;
  trend: string;
}

export interface AxisComponent {
  key: string; transform: "yoy" | "level"; sign: number; weight: number;
  z: number; z_mom: number | null; blend: number; contribution: number;
}
export interface AxisDetail { score: number; se: number; components: AxisComponent[] }

export interface RegimeState {
  timestamp: string;
  regime: Regime;
  growth_axis: number;
  inflation_axis: number;
  confidence: number;
  // v2: 축 분해(지표별 변환 z·기여 — 'CPI 레벨 σ vs 축' 표시 모순 해소) + 사분면 확률
  axis_detail?: { growth: AxisDetail; inflation: AxisDetail };
  regime_probs?: Record<string, number>;

  stress_score: number;
  stress_components: Record<string, number>;

  yield_curve: { points: YieldCurvePoint[]; spread_2y10y_bp: number | null };
  yield_inversion: boolean;
  inversion_severity: number | null;

  recommended_mode: "NORMAL" | "CAUTIOUS" | "DEFENSIVE";
  asset_tilts: Record<string, string>;
  description: string;

  dynamic_risk_free_rate: number | null;
  dynamic_kill_dd_threshold: number | null;

  market?: "kr" | "us";                                     // 분석 대상 시장
  markets?: { kr: RegimeState; us: RegimeState };           // KR/US 동시 (두 카드용)
}

export interface HeatmapRow {
  indicator: string;
  name: string;
  unit: string;
  source: string;
  latest: number | null;
  mom_pct: number | null;
  yoy: number | null;
  z_score: number | null;
  percentile: number | null;
  trend: string;
}

// ─── API ─────────────────────────────────────────────────────────────────────

export const macroApi = {
  snapshot: async (useCache = true): Promise<MacroSnapshot> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/snapshot?use_cache=${useCache}`);
    if (!r.ok) throw new Error(`Snapshot failed: ${r.status}`);
    return r.json();
  },

  regime: async (): Promise<RegimeState> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/regime`);
    if (!r.ok) throw new Error(`Regime failed: ${r.status}`);
    return r.json();
  },

  yieldCurve: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/yield-curve`);
    if (!r.ok) throw new Error(`Yield curve failed: ${r.status}`);
    return r.json();
  },

  stress: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/stress`);
    if (!r.ok) throw new Error(`Stress failed: ${r.status}`);
    return r.json();
  },

  heatmap: async (): Promise<{ indicators: HeatmapRow[]; count: number; timestamp: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/heatmap`);
    if (!r.ok) throw new Error(`Heatmap failed: ${r.status}`);
    return r.json();
  },

  series: async (indicator: string): Promise<MacroSeries> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/series/${indicator}`);
    if (!r.ok) throw new Error(`Series failed: ${r.status}`);
    return r.json();
  },

  dynamicParams: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/dynamic-params`);
    if (!r.ok) throw new Error(`Dynamic params failed: ${r.status}`);
    return r.json();
  },

  refresh: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/refresh`, { method: "POST" });
    if (!r.ok) throw new Error("Refresh failed");
    return r.json();
  },

  health: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/health`);
    return r.ok ? r.json() : null;
  },
};

// ─── Style helpers ──────────────────────────────────────────────────────────

export const REGIME_COLORS: Record<Regime, { fg: string; bg: string; border: string }> = {
  Goldilocks:  { fg: "#15803d", bg: "#dcfce7", border: "#86efac" },
  Reflation:   { fg: "#a16207", bg: "#fef3c7", border: "#fcd34d" },
  Stagflation: { fg: "#b91c1c", bg: "#fee2e2", border: "#fca5a5" },
  Disinflation: { fg: "#1e40af", bg: "#dbeafe", border: "#93c5fd" },
};

export function zScoreColor(z: number | null): string {
  if (z == null) return "#737373";
  const abs = Math.abs(z);
  if (z > 2)  return "#b91c1c";     // 매우 높음 (빨강)
  if (z > 1)  return "#ea580c";     // 높음
  if (z > 0)  return "#65a30d";     // 약간 위
  if (z > -1) return "#0891b2";     // 약간 아래
  if (z > -2) return "#1d4ed8";     // 낮음
  return "#1e3a8a";                 // 매우 낮음
}

export function trendIcon(trend: string): string {
  return trend === "up" ? "▲" : trend === "down" ? "▼" : "—";
}

export function trendColor(trend: string): string {
  return trend === "up" ? "#16a34a" : trend === "down" ? "#dc2626" : "#737373";
}

export function stressColor(score: number): string {
  if (score >= 80) return "#7f1d1d";
  if (score >= 60) return "#dc2626";
  if (score >= 40) return "#f97316";
  if (score >= 20) return "#16a34a";
  return "#0891b2";
}
