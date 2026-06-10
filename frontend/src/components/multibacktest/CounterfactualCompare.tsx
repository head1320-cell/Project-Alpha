"use client";

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { useMemo, useState } from "react";
import { TrendingUp, Loader2, Play } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface ScenarioResult {
  name: string;
  label: string;
  summary?: any;
  equity_curve?: any[];
}

interface ComparisonRow {
  scenario: string;
  label: string;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  alpha_vs_baseline_pct?: number;
  sharpe_diff_vs_baseline?: number;
}

interface DecisionValues {
  baseline_return_pct?: number;
  macro_overlay_value_pct?: number;
  macro_overlay_value_bp_per_year?: number;
  macro_overlay_description?: string;
  netting_value_pct?: number;
  netting_value_bp_per_year?: number;
  netting_description?: string;
  hrp_vs_inverse_vol_value_pct?: number;
  hrp_vs_inverse_vol_value_bp_per_year?: number;
  hrp_vs_inverse_vol_description?: string;
  vs_equal_weight_value_pct?: number;
  vs_equal_weight_value_bp_per_year?: number;
  vs_equal_weight_description?: string;
}

interface Config {
  strategy_ids: number[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  allocation_method: string;
  rebalance_policy: string;
  commission_rate: number;
  slippage_rate: number;
}

interface Props {
  baseConfig: Config | null;
}

const SCENARIO_COLORS: Record<string, string> = {
  baseline:          "#00e5ff",
  no_macro_overlay:  "#ff9800",
  no_netting:        "#e040fb",
  equal_weight:      "#6b7fa3",
  inverse_vol:       "#ffeb3b",
  hrp_only:          "#69f0ae",
};

const DEFAULT_SCENARIOS = ["baseline", "no_macro_overlay", "no_netting", "equal_weight", "inverse_vol"];

// ═══════════════════════════════════════════════════════════════════════════════

export default function CounterfactualCompare({ baseConfig }: Props) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");

  const runCounterfactual = async () => {
    if (!baseConfig) {
      setError("먼저 통합 백테스트를 실행해주세요.");
      return;
    }
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/multibacktest/counterfactual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_ids: baseConfig.strategy_ids,
          start_date: baseConfig.start_date,
          end_date: baseConfig.end_date,
          initial_capital: baseConfig.initial_capital,
          base_allocation_method: baseConfig.allocation_method,
          base_rebalance_policy: baseConfig.rebalance_policy,
          commission_rate: baseConfig.commission_rate,
          slippage_rate: baseConfig.slippage_rate,
          scenarios: DEFAULT_SCENARIOS,
        }),
      });
      const data = await res.json();
      if (data.available) {
        setResult(data);
      } else {
        setError(data.message || "실행 실패");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  };

  // 차트 데이터 변환
  const chartData = useMemo(() => {
    if (!result?.scenarios) return [];

    const merged: Record<string, any> = {};

    for (const sc of result.scenarios) {
      if (!sc.equity_curve) continue;
      for (const point of sc.equity_curve) {
        if (!merged[point.date]) {
          merged[point.date] = { date: point.date, shortDate: point.date.slice(5) };
        }
        merged[point.date][sc.name] = point.cumulative_return_pct;
      }
    }

    return Object.values(merged).sort((a: any, b: any) =>
      a.date.localeCompare(b.date)
    );
  }, [result]);

  return (
    <div>
      {/* Run button */}
      {!result && (
        <div style={{
          padding: 20, textAlign: "center",
          background: "rgba(18,0,255,0.05)",
          border: "1px dashed #1200ff40",
          borderRadius: 6,
        }}>
          <div style={{ fontSize: 11, color: "#a7c8ff", marginBottom: 10 }}>
            What-If 시나리오 5개를 병렬 실행 — 매크로 끄기, 청산 끄기, 동일 가중, 역변동성 등
          </div>
          <button onClick={runCounterfactual}
                  disabled={running || !baseConfig}
                  style={{
                    padding: "10px 24px",
                    background: baseConfig && !running
                      ? "linear-gradient(135deg, #0d47a1 0%, #1200ff 100%)"
                      : "#1e2d4a",
                    color: "#fff", border: "none", borderRadius: 4,
                    fontSize: 12, fontWeight: 700,
                    cursor: baseConfig && !running ? "pointer" : "not-allowed",
                    opacity: baseConfig && !running ? 1 : 0.5,
                    display: "inline-flex", alignItems: "center", gap: 8,
                  }}>
            {running ? <Loader2 size={13} className="spin" /> : <Play size={13} />}
            {running ? "5개 시나리오 병렬 실행 중..." : "Counterfactual 분석 실행"}
          </button>
          {!baseConfig && (
            <div style={{ marginTop: 8, fontSize: 9, color: "#ff9800" }}>
              먼저 통합 백테스트를 실행해주세요.
            </div>
          )}
        </div>
      )}

      {error && (
        <div style={{ padding: 12, fontSize: 11, color: "#ff5252",
                        background: "rgba(255,82,82,0.1)",
                        border: "1px solid #ff525240", borderRadius: 4,
                        marginBottom: 12 }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Decision Values Cards */}
          <div>
            <div style={{ fontSize: 10, color: "#6b7fa3", fontWeight: 600,
                            textTransform: "uppercase", marginBottom: 6,
                            letterSpacing: "0.05em",
                            display: "flex", justifyContent: "space-between" }}>
              <span>의사결정 가치 정량화 (Baseline - Counterfactual)</span>
              <span style={{ color: "#a7c8ff" }}>
                실행 시간: {result.total_duration_seconds}s
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
              <DecisionCard
                label="매크로 오버레이 가치"
                value={result.decision_values?.macro_overlay_value_pct ?? 0}
                bp={result.decision_values?.macro_overlay_value_bp_per_year ?? 0}
                color="#e040fb"
              />
              <DecisionCard
                label="중앙 청산 가치"
                value={result.decision_values?.netting_value_pct ?? 0}
                bp={result.decision_values?.netting_value_bp_per_year ?? 0}
                color="#ff9800"
              />
              <DecisionCard
                label="HRP 클러스터링 가치"
                value={result.decision_values?.hrp_vs_inverse_vol_value_pct ?? 0}
                bp={result.decision_values?.hrp_vs_inverse_vol_value_bp_per_year ?? 0}
                color="#69f0ae"
              />
              <DecisionCard
                label="전체 시스템 가치"
                value={result.decision_values?.vs_equal_weight_value_pct ?? 0}
                bp={result.decision_values?.vs_equal_weight_value_bp_per_year ?? 0}
                color="#00e5ff"
                highlight
              />
            </div>
          </div>

          {/* Equity curve comparison */}
          <div style={{ background: "#0a0e27", padding: 12,
                          border: "1px solid #1e2d4a", borderRadius: 6 }}>
            <div style={{ fontSize: 10, color: "#6b7fa3", fontWeight: 600,
                            marginBottom: 6, textTransform: "uppercase",
                            letterSpacing: "0.05em" }}>
              누적 수익률 비교 — {result.n_scenarios} 시나리오
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartData} margin={{ top: 5, right: 16, bottom: 5, left: 30 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="#1e2d4a" />
                <XAxis dataKey="shortDate"
                        tick={{ fill: "#6b7fa3", fontSize: 9 }}
                        stroke="#1e2d4a"
                        interval={Math.floor((chartData.length || 1) / 15)} />
                <YAxis tick={{ fill: "#6b7fa3", fontSize: 9 }}
                        stroke="#1e2d4a"
                        tickFormatter={(v) => `${v.toFixed(0)}%`} />
                <Tooltip
                  contentStyle={{ background: "#060a1a", border: "1px solid #1e2d4a",
                                    borderRadius: 4, fontSize: 11 }}
                  labelStyle={{ color: "#e0e8f5", fontWeight: 600 }}
                  formatter={(v: any, name: string) => {
                    const sc = result.scenarios.find((s: any) => s.name === name);
                    return [`${Number(v).toFixed(2)}%`, sc?.label || name];
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 10 }}
                  iconSize={8}
                  formatter={(value: string) => {
                    const sc = result.scenarios.find((s: any) => s.name === value);
                    return sc?.label || value;
                  }}
                />

                {result.scenarios.map((sc: ScenarioResult) => (
                  <Line key={sc.name}
                         type="monotone" dataKey={sc.name}
                         stroke={SCENARIO_COLORS[sc.name] || "#6b7fa3"}
                         strokeWidth={sc.name === "baseline" ? 2.5 : 1.5}
                         strokeDasharray={sc.name === "baseline" ? "0" : "4 4"}
                         dot={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Comparison Table */}
          <div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #1e2d4a" }}>
                  <th style={{ ...thStyle, textAlign: "left" }}>시나리오</th>
                  <th style={thStyle}>Total Return</th>
                  <th style={thStyle}>Sharpe</th>
                  <th style={thStyle}>MDD</th>
                  <th style={thStyle}>vs Baseline</th>
                </tr>
              </thead>
              <tbody>
                {result.comparison_table.map((row: ComparisonRow) => {
                  const isBaseline = row.scenario === "baseline";
                  const alpha = row.alpha_vs_baseline_pct ?? 0;
                  return (
                    <tr key={row.scenario} style={{
                      borderBottom: "1px solid #1e2d4a",
                      background: isBaseline ? "rgba(0,229,255,0.05)" : "transparent",
                    }}>
                      <td style={{ ...tdStyle, textAlign: "left" }}>
                        <span style={{
                          display: "inline-block", width: 10, height: 10,
                          borderRadius: 2, marginRight: 8,
                          background: SCENARIO_COLORS[row.scenario] || "#6b7fa3",
                        }} />
                        <span style={{ fontWeight: isBaseline ? 700 : 500,
                                          color: isBaseline ? "#00e5ff" : "#e0e8f5" }}>
                          {row.label}
                        </span>
                      </td>
                      <td style={{ ...tdStyle, fontFamily: "'Roboto Mono', monospace",
                                      color: row.total_return_pct >= 0 ? "#69f0ae" : "#ff5252",
                                      fontWeight: 700 }}>
                        {row.total_return_pct >= 0 ? "+" : ""}{row.total_return_pct.toFixed(2)}%
                      </td>
                      <td style={{ ...tdStyle, fontFamily: "'Roboto Mono', monospace" }}>
                        {row.sharpe_ratio.toFixed(2)}
                      </td>
                      <td style={{ ...tdStyle, fontFamily: "'Roboto Mono', monospace",
                                      color: "#ff5252" }}>
                        {row.max_drawdown_pct.toFixed(2)}%
                      </td>
                      <td style={{ ...tdStyle, fontFamily: "'Roboto Mono', monospace",
                                      color: alpha >= 0 ? "#69f0ae" : "#ff5252",
                                      fontWeight: 700 }}>
                        {isBaseline ? "(base)" : `${alpha >= 0 ? "+" : ""}${alpha.toFixed(2)}%`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <button onClick={() => { setResult(null); }} style={{
            padding: "6px 14px", marginTop: 4, alignSelf: "center",
            background: "transparent", color: "#a7c8ff",
            border: "1px solid #1e2d4a", borderRadius: 4,
            fontSize: 10, cursor: "pointer",
          }}>
            다시 실행
          </button>
        </div>
      )}
    </div>
  );
}

function DecisionCard({ label, value, bp, color, highlight }: {
  label: string; value: number; bp: number; color: string; highlight?: boolean;
}) {
  const isPositive = value >= 0;
  return (
    <div style={{
      padding: "12px 14px",
      background: highlight
        ? `linear-gradient(135deg, ${color}15, ${color}05)`
        : "#0a0e27",
      border: `1px solid ${highlight ? color + "40" : "#1e2d4a"}`,
      borderRadius: 6,
    }}>
      <div style={{ fontSize: 9, color: "#6b7fa3", fontWeight: 600,
                      textTransform: "uppercase", letterSpacing: "0.05em",
                      marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 700,
                      color: isPositive ? color : "#ff5252",
                      fontFamily: "'Roboto Mono', monospace" }}>
        {isPositive ? "+" : ""}{value.toFixed(2)}%
      </div>
      <div style={{ fontSize: 9, color: "#6b7fa3", marginTop: 2,
                      fontFamily: "'Roboto Mono', monospace" }}>
        {isPositive ? "+" : ""}{bp.toFixed(0)} bp/yr
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: "8px 10px", fontSize: 9, fontWeight: 700, color: "#6b7fa3",
  textTransform: "uppercase", letterSpacing: "0.05em",
  textAlign: "center" as const,
};

const tdStyle: React.CSSProperties = {
  padding: "10px", textAlign: "center" as const, color: "#e0e8f5",
};
