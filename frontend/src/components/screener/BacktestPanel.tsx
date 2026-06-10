"use client";

import { useState, useEffect } from "react";
import { TrendingUp, Play, Loader2, BarChart3, AlertCircle } from "lucide-react";
import {
  backtestBridgeApi,
  type FilterGroupNode, type ScreenToBacktestResult,
} from "@/lib/screenerApi";

// ═══════════════════════════════════════════════════════════════════════════════
// BacktestPanel — 스크리너 필터 → 원클릭 백테스트 (FilterStack 하단)
// ═══════════════════════════════════════════════════════════════════════════════

export function BacktestPanel({ group, universe, liquidityFloor }: {
  group: FilterGroupNode;
  universe: string;
  liquidityFloor: string;
}) {
  const [strategies, setStrategies] = useState<Array<{ id: string; label: string }>>([]);
  const [strategy, setStrategy] = useState("GoldenCross");
  const [period, setPeriod] = useState<"1y" | "2y" | "3y">("2y");
  const [maxTickers, setMaxTickers] = useState(10);
  const [result, setResult] = useState<ScreenToBacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    backtestBridgeApi.strategies().then(d => setStrategies(d.strategies)).catch(() => {});
  }, []);

  const periodToDates = (p: string) => {
    const end = new Date();
    const start = new Date();
    start.setFullYear(end.getFullYear() - (p === "1y" ? 1 : p === "2y" ? 2 : 3));
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    return { start_date: fmt(start), end_date: fmt(end) };
  };

  const run = async () => {
    setLoading(true); setErr(null); setResult(null);
    try {
      const { start_date, end_date } = periodToDates(period);
      const r = await backtestBridgeApi.screenToBacktest({
        universe, filter_ast: group, liquidity_floor: liquidityFloor,
        max_tickers: maxTickers, strategy_name: strategy, start_date, end_date,
      });
      if (r.error) setErr(r.message || "백테스트 실패");
      else setResult(r);
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  };

  const stat = result?.backtest?.statistics;
  const pos = (v: number | undefined) => (v ?? 0) >= 0;

  return (
    <div className="card-md p-4" style={{ borderLeft: "3px solid #1200ff" }}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="bar-icon" style={{ background: "#eceaff", color: "#1200ff", width: 22, height: 22, borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <TrendingUp size={13} />
          </span>
          <span className="text-sm font-bold text-primary">통과 종목 백테스트</span>
          <span className="text-[10px] text-secondary">스크리닝 → 전략 검증 원클릭</span>
        </div>
        <button onClick={run} disabled={loading || !group.conditions.length}
          className="text-[11px] px-3 py-1.5 rounded-md text-white flex items-center gap-1.5 disabled:opacity-50"
          style={{ background: "#1200ff" }}>
          {loading ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} 백테스트 실행
        </button>
      </div>

      {/* 설정 */}
      <div className="flex gap-3 flex-wrap mb-3">
        <div>
          <label className="text-[9px] uppercase tracking-wider text-secondary block mb-1">전략</label>
          <select value={strategy} onChange={e => setStrategy(e.target.value)}
            className="text-[11px] border border-default rounded-md px-2 py-1.5 bg-white" style={{ minWidth: 110 }}>
            {strategies.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[9px] uppercase tracking-wider text-secondary block mb-1">기간</label>
          <div className="flex gap-1">
            {(["1y", "2y", "3y"] as const).map(p => (
              <button key={p} onClick={() => setPeriod(p)}
                className={`text-[11px] px-2.5 py-1.5 rounded-md border transition ${period === p ? "bg-primary text-white border-primary" : "border-default text-secondary"}`}>
                {p === "1y" ? "1년" : p === "2y" ? "2년" : "3년"}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="text-[9px] uppercase tracking-wider text-secondary block mb-1">종목 수 (상위 {maxTickers})</label>
          <input type="range" min="3" max="20" value={maxTickers}
            onChange={e => setMaxTickers(parseInt(e.target.value))}
            className="w-28" style={{ accentColor: "#1200ff" }} />
        </div>
      </div>

      {!result && !err && (
        <div className="text-[11px] text-secondary">현재 필터를 통과한 상위 종목으로 선택 전략을 백테스트합니다.</div>
      )}

      {err && (
        <div className="text-[11px] flex items-center gap-1.5" style={{ color: "#dc2626" }}>
          <AlertCircle size={12} /> {err}
        </div>
      )}

      {result && stat && (
        <div className="animate-fade-in">
          {/* 핵심 지표 */}
          <div className="grid grid-cols-4 gap-2 mb-3">
            {[
              { label: "총수익률", value: `${stat.total_return_pct}%`, good: pos(stat.total_return_pct) },
              { label: "CAGR", value: `${stat.cagr}%`, good: pos(stat.cagr) },
              { label: "샤프", value: stat.sharpe_ratio, good: (stat.sharpe_ratio ?? 0) >= 1 },
              { label: "MDD", value: `-${Math.abs(stat.max_drawdown_pct)}%`, good: Math.abs(stat.max_drawdown_pct) < 20 },
            ].map(m => (
              <div key={m.label} className="bg-light rounded-lg p-2 text-center">
                <div className="text-[9px] text-secondary uppercase tracking-wider">{m.label}</div>
                <div className="text-sm font-mono font-bold" style={{ color: m.good ? "#16a34a" : "#dc2626" }}>{m.value}</div>
              </div>
            ))}
          </div>

          {/* 자산곡선 (간이 SVG) */}
          {result.backtest.equity_curve?.length > 1 && (
            <EquitySparkline curve={result.backtest.equity_curve} />
          )}

          {/* 보조 지표 */}
          <div className="flex gap-3 flex-wrap mt-2 text-[10px] text-secondary">
            <span>소르티노 <b className="font-mono text-primary">{stat.sortino_ratio}</b></span>
            <span>거래 <b className="font-mono text-primary">{stat.num_trades}회</b></span>
            <span>승률 <b className="font-mono text-primary">{stat.win_rate}%</b></span>
            <span>수수료 <b className="font-mono text-primary">{(stat.total_commission / 10000).toFixed(0)}만</b></span>
          </div>

          {/* 종목 + 데이터 출처 */}
          <div className="mt-2.5 pt-2.5 border-t border-default flex items-center justify-between flex-wrap gap-2">
            <div className="text-[10px] text-secondary">
              {result.backtest_config.strategy} · {result.backtest_config.period} · {result.screened_count}종목
            </div>
            <span className="text-[9px] px-2 py-0.5 rounded-full font-bold"
              style={{ background: result.data_source.fully_real ? "#dcfce7" : "#fef3c7", color: result.data_source.fully_real ? "#15803d" : "#a16207" }}>
              {result.data_source.fully_real ? "✓ 실데이터" : "mock 데이터"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function EquitySparkline({ curve }: { curve: number[] }) {
  const W = 600, H = 60;
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
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 60 }} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
      <polygon points={`0,${H} ${pts} ${W},${H}`} fill={color} opacity="0.07" />
    </svg>
  );
}
