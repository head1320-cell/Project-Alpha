"use client";

import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, ScatterChart, Scatter,
  ZAxis, Cell, RadialBarChart, RadialBar,
} from "recharts";
import {
  Activity, AlertTriangle, RefreshCw, Loader2, TrendingUp, TrendingDown,
  Minus, Globe, Zap, Shield, Gauge,
} from "lucide-react";
import {
  macroApi, type RegimeState, type HeatmapRow, REGIME_COLORS,
  zScoreColor, trendIcon, trendColor, stressColor,
} from "@/entities/macro/api";

/**
 * MacroRadar — Phase 4 통합 매크로 대시보드
 * ─────────────────────────────────────────────
 *  · QuadrantBox      — 4-Quadrant 시각화 + 현재 위치 마커
 *  · YieldCurve       — 3M~30Y 곡선 + 역전 경고
 *  · MacroHeatmap     — 16지표 × Z-Score 히트맵
 *  · StressGauge      — 시장 공포 지수 게이지
 *  · DynamicParamCard — Valuation/KillSwitch 동적 파라미터
 */
export default function MacroRadar() {
  const [state, setState] = useState<RegimeState | null>(null);
  const [heatmap, setHeatmap] = useState<HeatmapRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [regime, heat] = await Promise.all([
        macroApi.regime(),
        macroApi.heatmap(),
      ]);
      setState(regime);
      setHeatmap(heat.indicators);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await macroApi.refresh();
      await load();
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) {
    return (
      <div className="card-md p-12 text-center">
        <Loader2 size={32} className="animate-spin mx-auto mb-3 text-secondary" />
        <div className="text-sm text-secondary">16개 매크로 지표 수집 중...</div>
      </div>
    );
  }

  if (error || !state) {
    return (
      <div className="card-md p-6 text-center" style={{ color: "#dc2626" }}>
        <AlertTriangle size={24} className="mx-auto mb-2" />
        <div className="text-sm">{error || "매크로 데이터 로드 실패"}</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Top: Regime + Stress + Dynamic Params */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-5">
          <QuadrantBox state={state} />
        </div>
        <div className="lg:col-span-4">
          <StressGauge state={state} />
        </div>
        <div className="lg:col-span-3">
          <DynamicParamCard state={state} onRefresh={refresh} refreshing={refreshing} />
        </div>
      </div>

      {/* Middle: Yield Curve + Asset Tilts */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-8">
          <YieldCurveChart state={state} />
        </div>
        <div className="lg:col-span-4">
          <AssetTilts state={state} />
        </div>
      </div>

      {/* Bottom: Heatmap */}
      <MacroHeatmap rows={heatmap} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// QuadrantBox — 4-Quadrant + 현재 위치
// ═══════════════════════════════════════════════════════════════════════════════

function QuadrantBox({ state }: { state: RegimeState }) {
  const c = REGIME_COLORS[state.regime];

  // 4 분면 데이터 — recharts scatter
  const x = state.inflation_axis;
  const y = state.growth_axis;

  return (
    <div className="card-md p-4 h-full">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-bold text-primary flex items-center gap-2">
            <Globe size={14} style={{ color: c.fg }} />
            4-Quadrant Macro Regime
          </h3>
          <p className="text-[10px] text-secondary mt-0.5 font-mono">
            Growth × Inflation 축으로 현재 국면 자동 판별
          </p>
        </div>
        <div
          className="px-3 py-1.5 rounded-full text-sm font-bold"
          style={{ color: c.fg, background: c.bg, border: `1px solid ${c.border}` }}
        >
          {state.regime}
        </div>
      </div>

      <div className="relative" style={{ height: 280 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 20, right: 20, left: 0, bottom: 30 }}>
            <CartesianGrid strokeDasharray="2 2" stroke="#e5e7eb" />
            <XAxis
              type="number"
              dataKey="x"
              domain={[-2, 2]}
              ticks={[-2, -1, 0, 1, 2]}
              tickFormatter={(v: number) => v.toFixed(0)}
              label={{ value: "← 디스인플레이션 | 인플레이션 →", position: "bottom", offset: 12, fontSize: 10 }}
              stroke="#737373"
              style={{ fontSize: 10 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[-2, 2]}
              ticks={[-2, -1, 0, 1, 2]}
              tickFormatter={(v: number) => v.toFixed(0)}
              label={{ value: "↑ 성장 | 수축 ↓", angle: -90, position: "insideLeft", fontSize: 10 }}
              stroke="#737373"
              style={{ fontSize: 10 }}
            />
            <ZAxis type="number" range={[600, 600]} />
            <ReferenceLine x={0} stroke="#9ca3af" strokeWidth={1.5} />
            <ReferenceLine y={0} stroke="#9ca3af" strokeWidth={1.5} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              contentStyle={{ background: "#fff", border: "1px solid #d4d4d8", borderRadius: 6, fontSize: 11 }}
              formatter={(_v: number, name: string) => [`${(_v as number).toFixed(2)}`, name]}
            />
            <Scatter
              data={[{ x, y }]}
              fill={c.fg}
            >
              <Cell stroke="#fff" strokeWidth={3} />
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>

        {/* Quadrant labels */}
        <div className="absolute top-6 left-12 text-[9px] font-bold text-secondary opacity-60">DEFLATION</div>
        <div className="absolute top-6 right-12 text-[9px] font-bold text-secondary opacity-60">REFLATION</div>
        <div className="absolute bottom-12 left-12 text-[9px] font-bold text-secondary opacity-60">STAGFLATION</div>
        <div className="absolute bottom-12 right-12 text-[9px] font-bold text-secondary opacity-60">GOLDILOCKS</div>
      </div>

      <div className="pt-3 border-t border-default text-xs leading-relaxed">
        <div className="font-medium" style={{ color: c.fg }}>{state.description}</div>
        <div className="text-[10px] text-secondary mt-1 font-mono">
          Growth Z: {state.growth_axis.toFixed(2)} · Inflation Z: {state.inflation_axis.toFixed(2)} ·
          신뢰도: {(state.confidence * 100).toFixed(0)}%
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// StressGauge — 0-100 게이지
// ═══════════════════════════════════════════════════════════════════════════════

function StressGauge({ state }: { state: RegimeState }) {
  const score = state.stress_score;
  const color = stressColor(score);
  const components = Object.entries(state.stress_components || {});

  return (
    <div className="card-md p-4 h-full">
      <div className="mb-2">
        <h3 className="text-sm font-bold text-primary flex items-center gap-2">
          <Zap size={14} style={{ color }} />
          Market Stress Index
        </h3>
        <p className="text-[10px] text-secondary mt-0.5 font-mono">
          VIX + Credit + FX + Yield + DXY 통합 0-100
        </p>
      </div>

      <div className="relative" style={{ height: 140 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%"
            cy="65%"
            innerRadius="55%"
            outerRadius="90%"
            startAngle={180}
            endAngle={0}
            data={[{ value: score, fill: color }]}
          >
            <RadialBar background={{ fill: "#f3f4f6" }} dataKey="value" cornerRadius={6} />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div className="mt-6 text-4xl font-bold font-mono" style={{ color }}>
            {score.toFixed(0)}
          </div>
          <div className="text-[10px] text-secondary mt-0.5 font-mono uppercase tracking-wider">
            / 100
          </div>
        </div>
      </div>

      <div className="space-y-1.5 mt-3">
        {components.slice(0, 5).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between text-[10px]">
            <span className="text-secondary uppercase tracking-wider">{k.replace(/_/g, " ")}</span>
            <div className="flex items-center gap-1.5">
              <div className="w-20 h-1 bg-gray-100 rounded overflow-hidden">
                <div className="h-full" style={{ width: `${v}%`, background: stressColor(v as number) }} />
              </div>
              <span className="font-mono" style={{ color: stressColor(v as number), width: 24 }}>
                {(v as number).toFixed(0)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// DynamicParamCard — Valuation/KillSwitch 동적 파라미터
// ═══════════════════════════════════════════════════════════════════════════════

function DynamicParamCard({
  state, onRefresh, refreshing,
}: { state: RegimeState; onRefresh: () => void; refreshing: boolean }) {
  return (
    <div className="card-md p-4 h-full">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-sm font-bold text-primary flex items-center gap-2">
            <Shield size={14} style={{ color: "#8b5cf6" }} />
            동적 파라미터
          </h3>
          <p className="text-[10px] text-secondary mt-0.5 font-mono">
            매크로 → 시스템 자동 주입
          </p>
        </div>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="p-1.5 hover:bg-light rounded transition"
          title="강제 새로고침"
        >
          {refreshing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
        </button>
      </div>

      <div className="space-y-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-secondary mb-0.5">
            Valuation Risk-Free Rate
          </div>
          <div className="text-2xl font-bold font-mono text-primary">
            {state.dynamic_risk_free_rate != null ? (state.dynamic_risk_free_rate * 100).toFixed(2) : "—"}%
          </div>
          <div className="text-[9px] text-secondary mt-0.5">
            국고채 10년물 기반 → RIM/DCF Ke 자동 갱신
          </div>
        </div>

        <div className="pt-2 border-t border-default">
          <div className="text-[10px] uppercase tracking-wider text-secondary mb-0.5">
            Kill Switch DD Threshold
          </div>
          <div className="text-2xl font-bold font-mono" style={{ color: "#dc2626" }}>
            {state.dynamic_kill_dd_threshold != null ? `-${(state.dynamic_kill_dd_threshold * 100).toFixed(2)}` : "—"}%
          </div>
          <div className="text-[9px] text-secondary mt-0.5">
            Stress {state.stress_score.toFixed(0)} → 적응 조정 (높을수록 민감)
          </div>
        </div>

        <div className="pt-2 border-t border-default">
          <div className="text-[10px] uppercase tracking-wider text-secondary mb-0.5">
            권고 모드
          </div>
          <div
            className="text-base font-bold mt-1 px-2 py-1 rounded text-center"
            style={{
              color: state.recommended_mode === "DEFENSIVE" ? "#dc2626" :
                     state.recommended_mode === "CAUTIOUS"  ? "#ea580c" : "#16a34a",
              background: state.recommended_mode === "DEFENSIVE" ? "#fef2f2" :
                          state.recommended_mode === "CAUTIOUS"  ? "#fff7ed" : "#f0fdf4",
            }}
          >
            {state.recommended_mode}
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// YieldCurveChart
// ═══════════════════════════════════════════════════════════════════════════════

function YieldCurveChart({ state }: { state: RegimeState }) {
  const points = state.yield_curve?.points || [];
  const inv = state.yield_inversion;
  const severity = state.inversion_severity;

  return (
    <div className="card-md p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-bold text-primary flex items-center gap-2">
            <Activity size={14} style={{ color: inv ? "#dc2626" : "#0891b2" }} />
            US Treasury Yield Curve
          </h3>
          <p className="text-[10px] text-secondary mt-0.5 font-mono">
            3M ~ 30Y 만기별 수익률 곡선
          </p>
        </div>
        {inv && (
          <div
            className="px-3 py-1 rounded-full text-[10px] font-bold flex items-center gap-1"
            style={{ background: "#fef2f2", color: "#dc2626", border: "1px solid #fecaca" }}
          >
            <AlertTriangle size={11} />
            역전 {severity != null ? `${severity.toFixed(0)}bp` : ""}
          </div>
        )}
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={points} margin={{ top: 8, right: 16, left: -8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="label" stroke="#737373" style={{ fontSize: 10 }} />
          <YAxis
            stroke="#737373"
            style={{ fontSize: 10 }}
            tickFormatter={(v: number) => `${v.toFixed(1)}%`}
          />
          <Tooltip
            contentStyle={{ background: "#fff", border: "1px solid #d4d4d8", borderRadius: 6, fontSize: 11 }}
            formatter={(v: number) => [`${v.toFixed(2)}%`, "Yield"]}
          />
          <Line
            type="monotone"
            dataKey="yield_pct"
            stroke={inv ? "#dc2626" : "#0891b2"}
            strokeWidth={2}
            dot={{ r: 4, fill: inv ? "#dc2626" : "#0891b2" }}
            activeDot={{ r: 6 }}
          />
        </LineChart>
      </ResponsiveContainer>

      <div className="mt-2 pt-2 border-t border-default flex items-center justify-between text-[10px] font-mono">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 flex-grow">
          {points.map(p => (
            <div key={p.label}>
              <span className="text-secondary">{p.label}:</span>
              <span className="text-primary font-bold ml-1">{p.yield_pct.toFixed(2)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// AssetTilts
// ═══════════════════════════════════════════════════════════════════════════════

const TILT_LABELS: Record<string, string> = {
  growth_stocks: "성장주",
  value_stocks: "가치주",
  bonds: "채권",
  commodities: "원자재",
  cash: "현금",
};

const TILT_COLORS: Record<string, string> = {
  "++": "#16a34a",
  "+":  "#65a30d",
  "0":  "#737373",
  "-":  "#ea580c",
  "--": "#dc2626",
};

function AssetTilts({ state }: { state: RegimeState }) {
  const tilts = Object.entries(state.asset_tilts || {});

  return (
    <div className="card-md p-4 h-full">
      <h3 className="text-sm font-bold text-primary flex items-center gap-2 mb-1">
        <Gauge size={14} style={{ color: "#8b5cf6" }} />
        자산군 권고 비중
      </h3>
      <p className="text-[10px] text-secondary mb-3 font-mono">
        {state.regime} 국면 기준
      </p>

      <div className="space-y-2">
        {tilts.map(([asset, tilt]) => (
          <div key={asset} className="flex items-center justify-between p-2 rounded border border-default">
            <span className="text-xs font-medium text-primary">{TILT_LABELS[asset] || asset}</span>
            <div className="flex items-center gap-2">
              <div className="text-xs font-bold font-mono" style={{ color: TILT_COLORS[tilt as string] }}>
                {tilt as string}
              </div>
              <div className="w-12 h-1 bg-gray-100 rounded overflow-hidden">
                <div
                  className="h-full"
                  style={{
                    width: `${["--", "-", "0", "+", "++"].indexOf(tilt as string) * 25 + 10}%`,
                    background: TILT_COLORS[tilt as string],
                  }}
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MacroHeatmap — 16지표 × Z-Score
// ═══════════════════════════════════════════════════════════════════════════════

function MacroHeatmap({ rows }: { rows: HeatmapRow[] }) {
  return (
    <div className="card-md p-4">
      <h3 className="text-sm font-bold text-primary mb-1">
        Macro Indicators Heatmap
      </h3>
      <p className="text-[10px] text-secondary mb-3 font-mono">
        16개 지표 × Z-Score (5년 평균 대비 위치) · 정렬: 극단치 우선
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-default text-secondary">
              <th className="text-left py-2 pr-3">지표</th>
              <th className="text-right py-2 px-2">최근값</th>
              <th className="text-right py-2 px-2">MoM</th>
              <th className="text-right py-2 px-2">YoY</th>
              <th className="text-right py-2 px-2">Z-Score</th>
              <th className="text-right py-2 px-2">%ile</th>
              <th className="text-center py-2 px-2">추세</th>
              <th className="text-right py-2 pl-2">출처</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const zCol = zScoreColor(r.z_score);
              return (
                <tr key={r.indicator} className="border-b border-default hover:bg-light">
                  <td className="py-1.5 pr-3 font-medium text-primary">{r.name}</td>
                  <td className="py-1.5 px-2 text-right font-mono">
                    {r.latest != null ? r.latest.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}
                    <span className="text-[9px] text-secondary ml-0.5">{r.unit}</span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono"
                       style={{ color: r.mom_pct != null && r.mom_pct >= 0 ? "#16a34a" : "#dc2626" }}>
                    {r.mom_pct != null ? `${r.mom_pct >= 0 ? "+" : ""}${r.mom_pct.toFixed(2)}%` : "—"}
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono"
                       style={{ color: r.yoy != null && r.yoy >= 0 ? "#16a34a" : "#dc2626" }}>
                    {r.yoy != null ? `${r.yoy >= 0 ? "+" : ""}${r.yoy.toFixed(2)}` : "—"}
                  </td>
                  <td className="py-1.5 px-2 text-right">
                    <span
                      className="font-mono font-bold inline-block px-1.5 py-0.5 rounded"
                      style={{ color: zCol, background: `${zCol}15` }}
                    >
                      {r.z_score != null ? `${r.z_score >= 0 ? "+" : ""}${r.z_score.toFixed(2)}` : "—"}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-secondary">
                    {r.percentile != null ? `${r.percentile.toFixed(0)}` : "—"}
                  </td>
                  <td className="py-1.5 px-2 text-center font-bold"
                       style={{ color: trendColor(r.trend) }}>
                    {trendIcon(r.trend)}
                  </td>
                  <td className="py-1.5 pl-2 text-right text-[9px] text-secondary font-mono">
                    {r.source}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
