"use client";

import { useMemo } from "react";
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, ComposedChart,
} from "recharts";
import type { BacktestResult, TradeInfo } from "@/types/backtest";

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmtKRW(v: number) {
  if (v >= 1e8) return `${(v / 1e8).toFixed(1)}억`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}만`;
  return v.toLocaleString();
}

function fmtPct(v: number) { return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`; }

// ── Custom Tooltip ────────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { payload: { value: number; returnPct: number }; name: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  return (
    <div className="card-sm" style={{ minWidth: 160, padding: "8px 12px", background: "var(--slate)", fontSize: 11 }}>
      <div style={{ color: "var(--text-muted)", marginBottom: 4 }}>{label}</div>
      <div style={{ color: "var(--text-primary)", fontFamily: "monospace", fontWeight: 700 }}>
        ₩{fmtKRW(d?.value ?? 0)}
      </div>
      <div style={{ color: d?.returnPct >= 0 ? "var(--green)" : "var(--red)" }}>
        {fmtPct(d?.returnPct ?? 0)}
      </div>
    </div>
  );
}

function DrawdownTooltip({ active, payload, label }: { active?: boolean; payload?: { value: number }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const v = payload[0]?.value ?? 0;
  return (
    <div className="card-sm" style={{ padding: "6px 10px", fontSize: 11, background: "var(--slate)" }}>
      <div style={{ color: "var(--text-muted)" }}>{label}</div>
      <div style={{ color: "var(--red)", fontFamily: "monospace" }}>{fmtPct(v)}</div>
    </div>
  );
}

// ── Buy/Sell Dot ──────────────────────────────────────────────────────────────

function TradeDot(props: { cx?: number; cy?: number; payload?: { isBuy?: boolean; isSell?: boolean } }) {
  const { cx, cy, payload } = props;
  if (!cx || !cy) return null;
  if (payload?.isBuy)  return <circle cx={cx} cy={cy} r={4} fill="var(--green)" stroke="var(--navy)" strokeWidth={1.5} />;
  if (payload?.isSell) return <circle cx={cx} cy={cy} r={4} fill="var(--red)"   stroke="var(--navy)" strokeWidth={1.5} />;
  return null;
}

// ── Main Chart ────────────────────────────────────────────────────────────────

interface Props {
  result: BacktestResult;
  height?: number;
}

export function EquityChart({ result, height = 240 }: Props) {
  const r = result.result;
  const eq = r.equity_curve;
  const dates = r.equity_dates;
  const dd = r.drawdown_curve;
  const trades = r.trades ?? [];

  // Build trade lookup by date
  const tradeByDate = useMemo(() => {
    const m: Record<string, "buy" | "sell"> = {};
    trades.forEach((t) => {
      if (!m[t.date]) m[t.date] = t.side;
    });
    return m;
  }, [trades]);

  // Chart data
  const data = useMemo(() => {
    if (!eq.length || !dates.length) return [];
    const init = eq[0] || 1;
    return dates.map((date, i) => ({
      date,
      value: eq[i] ?? 0,
      returnPct: init ? ((eq[i] - init) / init) * 100 : 0,
      drawdown: (dd[i] ?? 0) * 100,
      isBuy:  tradeByDate[date] === "buy",
      isSell: tradeByDate[date] === "sell",
    }));
  }, [eq, dates, dd, tradeByDate]);

  // Y-axis domain with padding
  const minVal = useMemo(() => Math.min(...eq) * 0.98, [eq]);
  const maxVal = useMemo(() => Math.max(...eq) * 1.02, [eq]);

  if (!data.length) return (
    <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
      차트 데이터 없음
    </div>
  );

  return (
    <div className="flex flex-col gap-2">
      {/* Equity curve */}
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="var(--accent)" stopOpacity={0.15} />
              <stop offset="95%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(45,64,87,0.4)" vertical={false} />
          <XAxis dataKey="date" hide tick={false} />
          <YAxis domain={[minVal, maxVal]} tickFormatter={fmtKRW}
            style={{ fontSize: 10 }} stroke="var(--text-muted)" width={52} />
          <Tooltip content={(p) => <ChartTooltip {...(p as Parameters<typeof ChartTooltip>[0])} />} />
          <Area dataKey="value" stroke="var(--accent)" strokeWidth={1.5}
            fill="url(#eqGrad)" dot={<TradeDot />} activeDot={false} />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Drawdown */}
      <ResponsiveContainer width="100%" height={80}>
        <AreaChart data={data} margin={{ top: 0, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"  stopColor="var(--red)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="var(--red)" stopOpacity={0.03} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(45,64,87,0.4)" vertical={false} />
          <XAxis dataKey="date" hide />
          <YAxis tickFormatter={(v) => `${v.toFixed(0)}%`}
            style={{ fontSize: 10 }} stroke="var(--text-muted)" width={42} />
          <Tooltip content={(p) => <DrawdownTooltip {...(p as Parameters<typeof DrawdownTooltip>[0])} />} />
          <ReferenceLine y={0} stroke="var(--border)" />
          <Area dataKey="drawdown" stroke="var(--red)" strokeWidth={1}
            fill="url(#ddGrad)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex items-center gap-4 justify-center" style={{ fontSize: 10, color: "var(--text-muted)" }}>
        <span className="flex items-center gap-1"><span style={{ width: 20, height: 2, background: "var(--accent)", display: "inline-block" }} />자산 추이</span>
        <span className="flex items-center gap-1"><span style={{ width: 20, height: 2, background: "var(--red)", display: "inline-block" }} />낙폭</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: "var(--green)" }} />매수</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: "var(--red)" }} />매도</span>
      </div>
    </div>
  );
}

// ── Monthly Heatmap ───────────────────────────────────────────────────────────

export function MonthlyHeatmap({ monthly }: { monthly: Array<{ year: number; month: number; return_pct: number }> }) {
  if (!monthly.length) return null;

  const years  = [...new Set(monthly.map((m) => m.year))].sort();
  const months = ["1","2","3","4","5","6","7","8","9","10","11","12"];

  const get = (y: number, m: number) => monthly.find((r) => r.year === y && r.month === m);

  const cellBg = (v: number | undefined) => {
    if (v == null) return "transparent";
    if (v >  10) return "rgba(0,200,150,0.5)";
    if (v >   3) return "rgba(0,200,150,0.25)";
    if (v >   0) return "rgba(0,200,150,0.12)";
    if (v > -3) return "rgba(255,77,109,0.12)";
    if (v > -10) return "rgba(255,77,109,0.25)";
    return "rgba(255,77,109,0.5)";
  };

  return (
    <div className="overflow-x-auto">
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr>
            <th style={{ padding: "4px 8px", color: "var(--text-muted)", textAlign: "left", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", fontSize: 10 }}>연도</th>
            {months.map((m) => <th key={m} style={{ padding: "4px 6px", color: "var(--text-muted)", textAlign: "center", fontWeight: 600, fontSize: 10 }}>{m}월</th>)}
            <th style={{ padding: "4px 8px", color: "var(--text-muted)", textAlign: "right", fontWeight: 600, fontSize: 10 }}>합계</th>
          </tr>
        </thead>
        <tbody>
          {years.map((y) => {
            const yearTotal = monthly.filter((m) => m.year === y).reduce((acc, m) => acc + m.return_pct, 0);
            return (
              <tr key={y}>
                <td style={{ padding: "3px 8px", color: "var(--text-muted)", fontFamily: "monospace" }}>{y}</td>
                {months.map((_, mi) => {
                  const cell = get(y, mi + 1);
                  const v = cell?.return_pct;
                  return (
                    <td key={mi} style={{ padding: "3px 6px", background: cellBg(v), textAlign: "center", fontFamily: "monospace", color: v == null ? "var(--text-muted)" : v >= 0 ? "var(--green)" : "var(--red)", borderRadius: 2 }}>
                      {v == null ? "-" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}`}
                    </td>
                  );
                })}
                <td style={{ padding: "3px 8px", textAlign: "right", fontFamily: "monospace", fontWeight: 700, color: yearTotal >= 0 ? "var(--green)" : "var(--red)" }}>
                  {yearTotal >= 0 ? "+" : ""}{yearTotal.toFixed(1)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
