"use client";

import { useState } from "react";
import { Zap, Loader2 } from "lucide-react";
import { ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import type { OptimizeResult } from "@/entities/backtest/chartModel";

interface ParamRange {
  name: string;
  label: string;
  min: number;
  max: number;
  step: number;
  current: number;
}

interface Props {
  paramRanges: ParamRange[];
  onOptimize: (ranges: Record<string, { min: number; max: number; step: number }>) => Promise<OptimizeResult | null>;
  onApply?: (params: Record<string, number>) => void;
}

function colorForSharpe(sharpe: number, min: number, max: number): string {
  const range = max - min || 1;
  const norm = Math.max(0, Math.min(1, (sharpe - min) / range));
  // Deep red → amber → green gradient
  if (norm < 0.5) {
    const t = norm * 2;
    return `rgba(${Math.round(255 * (1 - t))}, ${Math.round(183 * t)}, 3, 0.85)`;
  } else {
    const t = (norm - 0.5) * 2;
    return `rgba(${Math.round(255 * (1 - t))}, ${Math.round(183 + 17 * t)}, ${Math.round(3 + 147 * t)}, 0.85)`;
  }
}

export function ParameterOptimizer({ paramRanges, onOptimize, onApply }: Props) {
  const [ranges, setRanges] = useState<Record<string, { min: number; max: number; step: number }>>(() =>
    Object.fromEntries(paramRanges.map((p) => [p.name, { min: p.min, max: p.max, step: p.step }]))
  );
  const [result, setResult]   = useState<OptimizeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");

  // Estimate grid size
  const gridSize = Object.values(ranges).reduce((acc, r) => {
    const steps = Math.floor((r.max - r.min) / r.step) + 1;
    return acc * steps;
  }, 1);

  const run = async () => {
    setLoading(true); setError(""); setResult(null);
    try {
      const res = await onOptimize(ranges);
      if (res) setResult(res);
    } catch (e) {
      setError((e as Error).message);
    }
    setLoading(false);
  };

  const sharpePts = result?.grid ?? [];
  const minSharpe = Math.min(...sharpePts.map((p) => p.sharpe));
  const maxSharpe = Math.max(...sharpePts.map((p) => p.sharpe));

  // For 2-param scatter: use first two params as x/y
  const paramNames = Object.keys(ranges);
  const xParam = paramNames[0] ?? "";
  const yParam = paramNames[1] ?? paramNames[0] ?? "";

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="label">파라미터 최적화 (Grid Search)</div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            예상 조합 수: {gridSize.toLocaleString()}
          </div>
        </div>
        <button className="btn-primary flex items-center gap-1.5 text-xs py-1.5 px-3"
          onClick={run} disabled={loading}>
          {loading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
          최적화 실행
        </button>
      </div>

      {/* Range editors */}
      <div className="flex flex-col gap-3">
        {paramRanges.map((p) => {
          const r = ranges[p.name];
          return (
            <div key={p.name} className="card-sm flex flex-col gap-2">
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{p.label}</div>
              <div className="flex gap-3">
                {(["min", "max", "step"] as const).map((field) => (
                  <div key={field} className="flex flex-col gap-0.5">
                    <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{field}</div>
                    <input
                      className="input text-xs py-1 px-2"
                      style={{ width: 70, fontFamily: "monospace" }}
                      type="number"
                      value={r[field]}
                      step={field === "step" ? 1 : (p.step ?? 1)}
                      onChange={(e) => setRanges({ ...ranges, [p.name]: { ...r, [field]: parseFloat(e.target.value) } })}
                    />
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {error && (
        <div className="text-xs p-2 rounded" style={{ background: "rgba(255,77,109,0.1)", color: "var(--red)" }}>
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="flex flex-col gap-4 animate-slide-up">
          {/* Best params */}
          <div className="card-md flex flex-col gap-3">
            <div className="label">최적 파라미터 (Sharpe 기준)</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(result.best_params).map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5 px-3 py-2 rounded-md"
                     style={{ background: "var(--navy)", border: "1px solid var(--accent)" }}>
                  <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{k}</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "monospace", color: "var(--accent)" }}>{v}</div>
                </div>
              ))}
            </div>
            <div className="flex gap-3">
              {[
                { l: "최적 Sharpe",  v: result.best_sharpe.toFixed(3) },
                { l: "최적 수익률",  v: `${result.best_return >= 0 ? "+" : ""}${result.best_return.toFixed(2)}%` },
                { l: "최적 MDD",     v: `-${Math.abs(result.best_drawdown).toFixed(2)}%` },
              ].map(({ l, v }) => (
                <div key={l} className="flex flex-col gap-0.5">
                  <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{l}</div>
                  <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "monospace", color: "var(--text-primary)" }}>{v}</div>
                </div>
              ))}
            </div>
            {onApply && (
              <button className="btn-primary text-xs self-start"
                onClick={() => onApply(result.best_params)}>
                이 파라미터로 백테스트
              </button>
            )}
          </div>

          {/* Scatter heatmap — visible when ≥ 2 params */}
          {xParam !== yParam && result.grid.length > 0 && (
            <div className="card-md flex flex-col gap-2">
              <div className="label">파라미터 민감도 (Sharpe 기준)</div>
              <ResponsiveContainer width="100%" height={220}>
                <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                  <XAxis dataKey="x" name={xParam} type="number" style={{ fontSize: 10 }} label={{ value: xParam, position: "insideBottom", offset: -4, fontSize: 10, fill: "var(--text-muted)" }} />
                  <YAxis dataKey="y" name={yParam} type="number" style={{ fontSize: 10 }} label={{ value: yParam, angle: -90, position: "insideLeft", fontSize: 10, fill: "var(--text-muted)" }} />
                  <ZAxis dataKey="z" range={[40, 400]} />
                  <Tooltip
                    cursor={false}
                    content={({ payload }) => {
                      if (!payload?.length) return null;
                      const p = payload[0].payload;
                      return (
                        <div className="card-sm" style={{ fontSize: 11, padding: "6px 10px" }}>
                          <div>{xParam}: <strong>{p.x}</strong></div>
                          <div>{yParam}: <strong>{p.y}</strong></div>
                          <div style={{ color: p.z >= 1 ? "var(--green)" : "var(--amber)" }}>
                            Sharpe: <strong>{p.z?.toFixed(3)}</strong>
                          </div>
                        </div>
                      );
                    }}
                  />
                  <Scatter
                    data={result.grid.map((g) => ({
                      x: g.params[xParam] ?? 0,
                      y: g.params[yParam] ?? 0,
                      z: g.sharpe,
                    }))}
                    shape={(props: { cx?: number; cy?: number; payload?: { z: number } }) => {
                      const { cx = 0, cy = 0, payload } = props;
                      return <circle cx={cx} cy={cy} r={6} fill={colorForSharpe(payload?.z ?? 0, minSharpe, maxSharpe)} opacity={0.85} />;
                    }}
                  />
                </ScatterChart>
              </ResponsiveContainer>
              <div style={{ fontSize: 10, color: "var(--text-muted)", textAlign: "center" }}>
                원 크기 = Sharpe 비율 | 색상: 적색(낮음) → 녹색(높음)
              </div>
            </div>
          )}

          {/* Grid table — top 10 */}
          <div className="card-md flex flex-col gap-2">
            <div className="label">상위 결과 (Sharpe 기준)</div>
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    {paramNames.map((p) => <th key={p}>{p}</th>)}
                    <th>Sharpe</th>
                    <th>수익률</th>
                    <th>MDD</th>
                    <th>거래</th>
                  </tr>
                </thead>
                <tbody>
                  {[...result.grid].sort((a, b) => b.sharpe - a.sharpe).slice(0, 10).map((g, i) => (
                    <tr key={i}>
                      {paramNames.map((p) => (
                        <td key={p} style={{ fontFamily: "monospace" }}>{g.params[p]}</td>
                      ))}
                      <td style={{ fontFamily: "monospace", color: g.sharpe >= 1 ? "var(--green)" : g.sharpe >= 0 ? "var(--amber)" : "var(--red)" }}>
                        {g.sharpe.toFixed(3)}
                      </td>
                      <td style={{ fontFamily: "monospace", color: g.return_pct >= 0 ? "var(--green)" : "var(--red)" }}>
                        {g.return_pct >= 0 ? "+" : ""}{g.return_pct.toFixed(2)}%
                      </td>
                      <td style={{ fontFamily: "monospace", color: "var(--red)" }}>
                        -{Math.abs(g.max_drawdown).toFixed(2)}%
                      </td>
                      <td style={{ fontFamily: "monospace" }}>{g.num_trades}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
