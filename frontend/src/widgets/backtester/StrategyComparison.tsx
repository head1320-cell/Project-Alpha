"use client";

import { useState, useEffect } from "react";
import {
  backtestBridgeApi, type ScreenToBacktestResult,
  type FilterGroupNode,
} from "@/shared/api/screenerApi";

// 대형주 유니버스 필터 (기본)
function largeCapFilter(): FilterGroupNode {
  return {
    logic: "AND",
    conditions: [{ field: "per", op: "gt", value: 0, kind: "fundamental" } as never],
    groups: [],
  };
}

interface StrategyResult {
  id: string;
  label: string;
  loading: boolean;
  error?: string;
  stats?: {
    total_return_pct: number;
    cagr: number;
    sharpe_ratio: number;
    sortino_ratio: number;
    calmar_ratio: number;
    max_drawdown_pct: number;
    num_trades: number;
    win_rate: number;
    profit_factor: number;
  };
  equity?: number[];
}

// 비교 지표 정의 (라벨 + 단위 + 높을수록 좋은지)
const METRICS: { key: keyof NonNullable<StrategyResult["stats"]>; label: string; unit: string; higher: boolean }[] = [
  { key: "total_return_pct", label: "총 수익률", unit: "%", higher: true },
  { key: "cagr", label: "CAGR", unit: "%", higher: true },
  { key: "sharpe_ratio", label: "Sharpe", unit: "", higher: true },
  { key: "sortino_ratio", label: "Sortino", unit: "", higher: true },
  { key: "calmar_ratio", label: "Calmar", unit: "", higher: true },
  { key: "max_drawdown_pct", label: "최대낙폭", unit: "%", higher: false },
  { key: "win_rate", label: "승률", unit: "%", higher: true },
  { key: "profit_factor", label: "손익비", unit: "", higher: true },
  { key: "num_trades", label: "거래수", unit: "회", higher: true },
];

const COLORS = ["#1200ff", "#dc2626", "#059669", "#d97706", "#7c3aed"];

export default function StrategyComparison() {
  const [available, setAvailable] = useState<Array<{ id: string; label: string }>>([]);
  const [selected, setSelected] = useState<string[]>(["GoldenCross", "Momentum"]);
  const [universe, setUniverse] = useState("kospi200");
  const [startDate, setStartDate] = useState("2023-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [results, setResults] = useState<StrategyResult[]>([]);
  const [running, setRunning] = useState(false);
  const [sectors, setSectors] = useState<Array<{ id: string; label: string; size: number }>>([]);

  useEffect(() => {
    backtestBridgeApi.strategies().then((d) => setAvailable(d.strategies)).catch(() => {});
    backtestBridgeApi.sectors().then((d) => setSectors(d.sectors)).catch(() => {});
  }, []);

  const toggleStrategy = (id: string) => {
    setSelected((s) => {
      if (s.includes(id)) return s.filter((x) => x !== id);
      if (s.length >= 5) return s; // 최대 5개
      return [...s, id];
    });
  };

  const runComparison = async () => {
    if (selected.length < 2) return;
    setRunning(true);
    const labelOf = (id: string) => available.find((a) => a.id === id)?.label ?? id;
    // 초기 로딩 상태
    setResults(selected.map((id) => ({ id, label: labelOf(id), loading: true })));

    // 순차 실행 (서버 부하 분산) — 동일 유니버스/기간
    const out: StrategyResult[] = [];
    for (const id of selected) {
      try {
        const r: ScreenToBacktestResult = await backtestBridgeApi.screenToBacktest({
          universe, filter_ast: largeCapFilter(), liquidity_floor: "standard",
          max_tickers: 15, strategy_name: id,
          start_date: startDate, end_date: endDate, initial_capital: 100_000_000,
        });
        if (r.error) {
          out.push({ id, label: labelOf(id), loading: false, error: r.message || "실패" });
        } else {
          out.push({
            id, label: labelOf(id), loading: false,
            stats: r.backtest.statistics,
            equity: r.backtest.equity_curve,
          });
        }
      } catch (e) {
        out.push({ id, label: labelOf(id), loading: false, error: (e as Error).message });
      }
      setResults([...out, ...selected.slice(out.length).map((sid) => ({ id: sid, label: labelOf(sid), loading: true }))]);
    }
    setRunning(false);
  };

  // 각 지표별 최고값 찾기 (하이라이트용)
  const bestFor = (key: keyof NonNullable<StrategyResult["stats"]>, higher: boolean): number | null => {
    const vals = results.filter((r) => r.stats).map((r) => r.stats![key]);
    if (!vals.length) return null;
    return higher ? Math.max(...vals) : Math.min(...vals);
  };

  const fmt = (v: number, unit: string) => {
    if (unit === "%") return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
    if (unit === "회") return `${v}`;
    return v.toFixed(2);
  };

  const hasResults = results.some((r) => r.stats);

  return (
    <div className="tpage-fade">
      <div className="terminal-breadcrumb">Modules / Backtester / <span>Strategy Comparison</span></div>
      <h1 className="terminal-h1">Strategy Comparison</h1>

      <div className="tcmp-config">
        <div className="tcmp-config-row">
          <div className="tcmp-field">
            <label>UNIVERSE</label>
            <select className="select" value={universe} onChange={(e) => setUniverse(e.target.value)}>
              <option value="kospi200">KOSPI 200</option>
              <option value="kospi">KOSPI 전체</option>
              <option value="kosdaq150">KOSDAQ 150</option>
              {sectors.length > 0 && (
                <optgroup label="업종·테마">
                  {sectors.map((s) => (
                    <option key={s.id} value={s.id}>{s.label} ({s.size})</option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>
          <div className="tcmp-field">
            <label>시작일</label>
            <input className="input" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div className="tcmp-field">
            <label>종료일</label>
            <input className="input" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
        </div>

        <div className="tcmp-field">
          <label>비교할 전략 선택 (2~5개) · {selected.length}개 선택됨</label>
          <div className="tcmp-strategy-grid">
            {available.map((s) => (
              <label key={s.id} className={`tcmp-strategy-chip${selected.includes(s.id) ? " on" : ""}`}>
                <input type="checkbox" checked={selected.includes(s.id)} onChange={() => toggleStrategy(s.id)} />
                {s.label}
              </label>
            ))}
          </div>
        </div>

        <button className="tbt-run" onClick={runComparison} disabled={running || selected.length < 2}>
          {running ? "비교 실행 중..." : `${selected.length}개 전략 비교 실행`}
        </button>
        {selected.length < 2 && <span className="tcmp-hint">최소 2개 전략을 선택하세요</span>}
      </div>

      {/* 비교 결과 */}
      {(hasResults || running) && (
        <div className="tcmp-results animate-fade-in">
          {/* 자산 곡선 오버레이 */}
          {hasResults && (
            <div className="tbt-chart-box" style={{ marginBottom: 24 }}>
              <div className="tbt-chart-header">
                <div className="tbt-chart-title">Equity Curves (정규화)</div>
                <div className="tcmp-legend">
                  {results.filter((r) => r.equity).map((r, i) => (
                    <span key={r.id} className="tcmp-legend-item">
                      <span className="tcmp-legend-dot" style={{ background: COLORS[i % COLORS.length] }} />
                      {r.label}
                    </span>
                  ))}
                </div>
              </div>
              <ComparisonChart results={results.filter((r) => r.equity)} colors={COLORS} />
            </div>
          )}

          {/* 지표 비교 테이블 */}
          <div className="tcmp-table-box">
            <div className="tbt-chart-title" style={{ marginBottom: 12 }}>지표 비교 (최고값 강조)</div>
            <div className="tcmp-table-scroll">
              <table className="tcmp-table">
                <thead>
                  <tr>
                    <th>지표</th>
                    {results.map((r, i) => (
                      <th key={r.id} className="num">
                        <span className="tcmp-th-dot" style={{ background: COLORS[i % COLORS.length] }} />
                        {r.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {METRICS.map((m) => {
                    const best = bestFor(m.key, m.higher);
                    return (
                      <tr key={m.key}>
                        <td className="tcmp-metric-label">{m.label}</td>
                        {results.map((r) => {
                          if (r.loading) return <td key={r.id} className="num tcmp-loading-cell">···</td>;
                          if (r.error) return <td key={r.id} className="num" style={{ color: "#dc2626" }}>—</td>;
                          const v = r.stats![m.key];
                          const isBest = best !== null && v === best && results.filter((x) => x.stats).length > 1;
                          return (
                            <td key={r.id} className={`num${isBest ? " tcmp-best" : ""}`}>
                              {fmt(v, m.unit)}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// 자산 곡선 오버레이 차트 (정규화: 시작=100)
function ComparisonChart({ results, colors }: { results: StrategyResult[]; colors: string[] }) {
  const W = 800, H = 260, P = 10;
  if (!results.length) return null;

  // 모든 곡선을 시작=100으로 정규화
  const series = results.map((r) => {
    const eq = r.equity!;
    const base = eq[0] || 1;
    return eq.map((v) => (v / base) * 100);
  });
  const allVals = series.flat();
  const minV = Math.min(...allVals, 100), maxV = Math.max(...allVals, 100);
  const range = maxV - minV || 1;

  const pathFor = (vals: number[]) => {
    const n = vals.length;
    return vals.map((v, i) => {
      const x = P + (i / Math.max(n - 1, 1)) * (W - 2 * P);
      const y = H - P - ((v - minV) / range) * (H - 2 * P);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
  };

  // 100 기준선
  const baseY = H - P - ((100 - minV) / range) * (H - 2 * P);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="tcmp-chart" preserveAspectRatio="none">
      <line x1={P} y1={baseY} x2={W - P} y2={baseY} stroke="var(--t-border)" strokeWidth="1" strokeDasharray="4 4" />
      {series.map((vals, i) => (
        <path key={i} d={pathFor(vals)} fill="none" stroke={colors[i % colors.length]} strokeWidth="1.5" />
      ))}
      <text x={P + 2} y={baseY - 4} fontSize="9" fill="var(--t-muted)" fontFamily="var(--t-mono)">100 (시작)</text>
    </svg>
  );
}
