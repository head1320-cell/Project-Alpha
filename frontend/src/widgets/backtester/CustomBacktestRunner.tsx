"use client";

import { useState } from "react";
import { backtestBridgeApi, type ScreenToBacktestResult } from "@/shared/api/screenerApi";
import type { BuilderState } from "@/entities/strategy/model";

// ═══════════════════════════════════════════════════════════════════════════════
// CustomBacktestRunner — 빌더 커스텀 전략(BuilderState)을 백테스트
//   기성 전략과 동일한 터미널 결과 레이아웃. spec을 __custom__으로 백엔드 실행.
// ═══════════════════════════════════════════════════════════════════════════════

export default function CustomBacktestRunner({
  spec, onClearCustom,
}: {
  spec: BuilderState;
  onClearCustom: () => void;
}) {
  const [universe, setUniverse] = useState("kospi200");
  const [startDate, setStartDate] = useState("2023-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [maxTickers, setMaxTickers] = useState(10);
  const [capital, setCapital] = useState(100_000_000);
  const [result, setResult] = useState<ScreenToBacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setLoading(true); setErr(null); setResult(null);
    try {
      const r = await backtestBridgeApi.customBacktest({
        universe, max_tickers: maxTickers, spec,
        start_date: startDate, end_date: endDate, initial_capital: capital,
      });
      if (r.error) setErr(r.message || "백테스트 실패");
      else setResult(r);
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  };

  const st = result?.backtest?.statistics;
  const fmt = (v: number | undefined, suffix = "", digits = 1) =>
    v === undefined ? "—" : `${v >= 0 && suffix === "%" ? "+" : ""}${v.toFixed(digits)}${suffix}`;
  const posColor = (v: number | undefined) => ((v ?? 0) >= 0 ? "#16a34a" : "#dc2626");

  // 전략 요약 (지표/조건 개수)
  const nIndicators = spec.indicators?.length ?? 0;
  const nEntry = spec.entry?.conditions?.length ?? 0;
  const nExit = spec.exit?.conditions?.length ?? 0;

  return (
    <div className="tpage-fade">
      <div className="terminal-breadcrumb">Modules / Backtester / <span>Custom Strategy</span></div>
      <div className="flex items-center justify-between" style={{ marginBottom: 8, gap: 16, flexWrap: "wrap" }}>
        <h1 className="terminal-h1" style={{ marginBottom: 0 }}>{spec.metadata?.name || "커스텀 전략"}</h1>
        <button
          onClick={onClearCustom}
          style={{ fontFamily: "var(--t-mono)", fontSize: 11, color: "var(--t-muted)", background: "transparent", border: "1px solid var(--t-border)", borderRadius: 2, padding: "6px 12px", cursor: "pointer" }}
        >
          ← 기성 전략으로
        </button>
      </div>
      <p style={{ color: "var(--t-muted)", fontSize: 13, marginBottom: 28, fontFamily: "var(--t-mono)" }}>
        CUSTOM · 지표 {nIndicators} · 진입조건 {nEntry} · 청산조건 {nExit}
      </p>

      <div className="tbt-grid">
        {/* 설정 패널 */}
        <div className="tbt-config">
          <div className="tbt-group">
            <label className="tbt-label">전략 (빌더에서 설계됨)</label>
            <div style={{ padding: "8px 12px", border: "1px solid var(--t-accent)", borderRadius: 2, background: "rgba(18,0,255,0.04)", fontSize: 13, fontWeight: 500, color: "var(--t-accent)" }}>
              {spec.metadata?.name || "커스텀 전략"}
            </div>
          </div>
          <div className="tbt-group">
            <label className="tbt-label">Asset Universe</label>
            <select className="tbt-input" value={universe} onChange={(e) => setUniverse(e.target.value)}>
              <option value="kospi50">KOSPI 50</option>
              <option value="kospi200">KOSPI 200</option>
              <option value="kosdaq150">KOSDAQ 150</option>
            </select>
          </div>
          <div className="tbt-group">
            <label className="tbt-label">Simulation Period</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input type="text" className="tbt-input" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
              <input type="text" className="tbt-input" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>
          </div>
          <div className="tbt-group">
            <label className="tbt-label">Max Positions ({maxTickers})</label>
            <input type="range" min="3" max="20" value={maxTickers} onChange={(e) => setMaxTickers(+e.target.value)} style={{ accentColor: "#1200ff" }} />
          </div>
          <div className="tbt-group">
            <label className="tbt-label">Initial Capital (₩)</label>
            <input type="text" className="tbt-input" value={capital.toLocaleString()} onChange={(e) => setCapital(Number(e.target.value.replace(/[^0-9]/g, "")) || 0)} />
          </div>
          <button className="tbt-run" onClick={run} disabled={loading}>
            {loading ? "Running Simulation..." : "Run Custom Simulation"}
          </button>
          {loading && (
            <div style={{ fontFamily: "var(--t-mono)", fontSize: 10, color: "var(--t-muted)", marginTop: -8, lineHeight: 1.5 }}>
              커스텀 전략 시뮬레이션 중...<br />최대 ~15초 소요됩니다.
            </div>
          )}

          {st && (
            <div className="tbt-quickstat">
              <div className="tbt-label" style={{ marginBottom: 8 }}>Quick Stats</div>
              TRADES: {st.num_trades}<br />
              WIN RATE: {st.win_rate}%<br />
              SHARPE: {st.sharpe_ratio}
            </div>
          )}
        </div>

        {/* 분석 뷰포트 */}
        <div className="tbt-viewport">
          {err && (
            <div className="tbt-empty" style={{ color: "#dc2626" }}>
              <div>
                <div style={{ fontFamily: "var(--t-mono)", fontSize: 11, marginBottom: 8 }}>[ ERROR ]</div>
                {err}
              </div>
            </div>
          )}
          {!result && !err && !loading && (
            <div className="tbt-empty">
              <div>
                <div style={{ fontFamily: "var(--t-mono)", fontSize: 11, marginBottom: 16 }}>[ CUSTOM_STRATEGY_READY ]</div>
                빌더에서 설계한 전략으로 백테스트를 실행하세요
              </div>
            </div>
          )}
          {loading && (
            <div className="tbt-empty">
              <div>
                <div style={{ fontFamily: "var(--t-mono)", fontSize: 11, marginBottom: 16, color: "var(--t-accent)" }}>[ SIMULATION_RUNNING ]</div>
                <div className="tbt-spinner" />
                <div style={{ marginTop: 16 }}>커스텀 전략 시뮬레이션 중...</div>
              </div>
            </div>
          )}

          {result && st && (
            <div className="animate-fade-in">
              <div className="tbt-stats">
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Total Return</div>
                  <div className="tbt-stat-value" style={{ color: posColor(st.total_return_pct) }}>{fmt(st.total_return_pct, "%")}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">CAGR</div>
                  <div className="tbt-stat-value" style={{ color: posColor(st.cagr) }}>{fmt(st.cagr, "%")}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Sharpe</div>
                  <div className="tbt-stat-value" style={{ color: (st.sharpe_ratio ?? 0) >= 1 ? "#16a34a" : "var(--t-ink)" }}>{fmt(st.sharpe_ratio, "", 2)}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Sortino</div>
                  <div className="tbt-stat-value">{fmt(st.sortino_ratio, "", 2)}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Max DD</div>
                  <div className="tbt-stat-value" style={{ color: "#dc2626" }}>-{Math.abs(st.max_drawdown_pct)}%</div>
                </div>
              </div>

              <div className="tbt-chart">
                <div className="tbt-chart-head">
                  <div className="tbt-chart-title">Equity Curve</div>
                  <div className="tbt-chart-title">{result.backtest_config.period}</div>
                </div>
                <EquityChart curve={result.backtest.equity_curve} />
              </div>

              <div className="tbt-chart">
                <div className="tbt-chart-head">
                  <div className="tbt-chart-title">Constituents ({result.screened_count})</div>
                  <span style={{ fontFamily: "var(--t-mono)", fontSize: 10, padding: "2px 8px", borderRadius: 2, background: result.data_source.fully_real ? "#dcfce7" : "#fafafa", color: result.data_source.fully_real ? "#15803d" : "var(--t-muted)", border: "1px solid var(--t-border)" }}>
                    {result.data_source.fully_real ? "REAL_DATA" : "MOCK_DATA"}
                  </span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {result.screened_tickers.slice(0, 12).map((t) => (
                    <span key={t.stock_code} style={{ fontFamily: "var(--t-mono)", fontSize: 12, padding: "4px 10px", border: "1px solid var(--t-border)", borderRadius: 2 }}>
                      {t.corp_name || t.stock_code}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function EquityChart({ curve }: { curve: number[] }) {
  if (!curve || curve.length < 2) {
    return <div style={{ height: 240, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 11 }}>NO_DATA</div>;
  }
  const W = 1000, H = 240;
  const min = Math.min(...curve), max = Math.max(...curve);
  const range = max - min || 1;
  const pts = curve.map((v, i) => {
    const x = (i / (curve.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const up = curve[curve.length - 1] >= curve[0];
  const color = up ? "#16a34a" : "#dc2626";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 240, borderBottom: "1px solid var(--t-border)", borderLeft: "1px solid var(--t-border)" }} preserveAspectRatio="none">
      <polygon points={`0,${H} ${pts} ${W},${H}`} fill={color} opacity="0.06" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
