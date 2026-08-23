"use client";

import { useState } from "react";
import { Download, TrendingUp, TrendingDown, Shield, Activity } from "lucide-react";
import { EquityChart, MonthlyHeatmap } from "./EquityChart";
import type { BacktestResult } from "@/entities/backtest/chartModel";

function fmt(v: number, pct = false, decimals = 2) {
  const s = v.toFixed(decimals);
  return pct ? `${v >= 0 ? "+" : ""}${s}%` : s;
}
function fmtKRW(v: number) {
  return `₩${Math.abs(v) >= 1e8 ? `${(v / 1e8).toFixed(1)}억` : v.toLocaleString()}`;
}

interface MetricCardProps {
  label: string;
  value: string;
  trend?: "up" | "down" | "neutral";
  sub?: string;
}
function MetricCard({ label, value, trend, sub }: MetricCardProps) {
  const color = trend === "up" ? "var(--green)" : trend === "down" ? "var(--red)" : "var(--text-primary)";
  return (
    <div className="card-sm flex flex-col gap-1">
      <div className="label">{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "monospace", color }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{sub}</div>}
    </div>
  );
}

interface Props {
  result: BacktestResult;
  strategyName?: string;
}

export function TearSheet({ result, strategyName }: Props) {
  const [tradeTab, setTradeTab] = useState<"log" | "symbols">("log");
  const s = result.result.statistics;
  const trades  = result.result.trades ?? [];
  const symRes  = result.result.symbol_results ?? [];
  const monthly = result.result.monthly_returns ?? [];

  const downloadCsv = () => {
    const keys = trades.length ? Object.keys(trades[0]) : [];
    const rows = [keys.join(","), ...trades.map((t) => keys.map((k) => (t as unknown as Record<string,unknown>)[k] ?? "").join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows], { type: "text/csv" }));
    a.download = `trades_${strategyName ?? "backtest"}.csv`;
    a.click();
  };

  return (
    <div className="flex flex-col gap-5 animate-slide-up">

      {/* ── 핵심 지표 4개 ── */}
      <div>
        <div className="label mb-2">핵심 성과 지표</div>
        <div className="grid grid-cols-4 gap-2">
          <MetricCard
            label="총 수익률"
            value={fmt(s.total_return_pct, true)}
            trend={s.total_return_pct >= 0 ? "up" : "down"}
            sub={`CAGR ${fmt(s.cagr, true)}`}
          />
          <MetricCard
            label="최대 낙폭"
            value={`-${Math.abs(s.max_drawdown_pct).toFixed(2)}%`}
            trend="down"
            sub={`Calmar ${s.calmar_ratio.toFixed(3)}`}
          />
          <MetricCard
            label="샤프 비율"
            value={s.sharpe_ratio.toFixed(3)}
            trend={s.sharpe_ratio >= 1 ? "up" : s.sharpe_ratio >= 0 ? "neutral" : "down"}
            sub={`Sortino ${s.sortino_ratio.toFixed(3)}`}
          />
          <MetricCard
            label="거래 횟수"
            value={String(s.num_trades)}
            trend="neutral"
            sub={`승률 ${fmt(s.win_rate, true, 1)}`}
          />
        </div>
      </div>

      {/* ── 상세 지표 2행 ── */}
      <div className="grid grid-cols-6 gap-2">
        {[
          { label: "수익 계수",   value: s.profit_factor.toFixed(3),       t: s.profit_factor >= 1 ? "up" : "down" },
          { label: "거래당 수익",  value: fmt(s.avg_trade_return, true, 3),  t: "neutral" },
          { label: "총 수수료",    value: fmtKRW(s.total_commission),        t: "neutral" },
          { label: "슬리피지",     value: fmtKRW(s.total_slippage),          t: "neutral" },
          { label: "연간 수익률",  value: fmt(s.cagr, true),                 t: s.cagr >= 0 ? "up" : "down" },
          { label: "순 수익률",    value: fmt(s.total_return_pct, true),      t: s.total_return_pct >= 0 ? "up" : "down" },
        ].map(({ label, value, t }) => (
          <MetricCard key={label} label={label} value={value} trend={t as "up" | "down" | "neutral"} />
        ))}
      </div>

      {/* ── Equity + Drawdown Chart ── */}
      <div className="card-md flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div className="label">자산 추이 · 낙폭</div>
          {result.data_range && (
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              {result.data_range.start} ~ {result.data_range.end}
            </span>
          )}
        </div>
        <EquityChart result={result} height={220} />
      </div>

      {/* ── Monthly heatmap ── */}
      {monthly.length > 0 && (
        <div className="card-md flex flex-col gap-2">
          <div className="label">월별 수익률 (%)</div>
          <MonthlyHeatmap monthly={monthly} />
        </div>
      )}

      {/* ── Trade log / Symbol results ── */}
      <div className="card-md flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex gap-1 p-0.5 rounded" style={{ background: "var(--navy)" }}>
            {(["log", "symbols"] as const).map((t) => (
              <button key={t} onClick={() => setTradeTab(t)}
                className="text-xs px-2.5 py-1 rounded transition-all font-semibold"
                style={{
                  background: tradeTab === t ? "var(--slate)" : "transparent",
                  color: tradeTab === t ? "var(--accent)" : "var(--text-muted)",
                  border: "none", cursor: "pointer",
                }}>
                {t === "log" ? `체결 내역 (${trades.length})` : `종목별 성과 (${symRes.length})`}
              </button>
            ))}
          </div>
          {tradeTab === "log" && trades.length > 0 && (
            <button className="btn-ghost text-xs flex items-center gap-1 py-1 px-2" onClick={downloadCsv}>
              <Download size={11} /> CSV
            </button>
          )}
        </div>

        {tradeTab === "log" && (
          <div className="overflow-x-auto" style={{ maxHeight: 280, overflowY: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  {["날짜","종목","방향","가격","수량","PnL","사유"].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {trades.slice(-50).map((t, i) => (
                  <tr key={i}>
                    <td style={{ fontFamily: "monospace", fontSize: 11 }}>{t.date}</td>
                    <td>{t.ticker}</td>
                    <td>
                      <span className={t.side === "buy" ? "badge-green" : "badge-red"}>
                        {t.side === "buy" ? "매수" : "매도"}
                      </span>
                    </td>
                    <td style={{ fontFamily: "monospace" }}>{t.price.toLocaleString()}</td>
                    <td style={{ fontFamily: "monospace" }}>{t.quantity.toLocaleString()}</td>
                    <td style={{ fontFamily: "monospace", color: t.pnl == null ? "var(--text-muted)" : t.pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                      {t.pnl == null ? "-" : `${t.pnl >= 0 ? "+" : ""}${t.pnl.toLocaleString()}`}
                    </td>
                    <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 11 }}>
                      {t.reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {trades.length === 0 && (
              <div style={{ textAlign: "center", padding: 16, color: "var(--text-muted)", fontSize: 12 }}>체결 내역 없음</div>
            )}
          </div>
        )}

        {tradeTab === "symbols" && (
          <table className="table">
            <thead>
              <tr>
                {["종목","수익률","거래","승률"].map((h) => <th key={h}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {symRes.map((r, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 600 }}>{r.symbol}</td>
                  <td style={{ fontFamily: "monospace", color: r.total_return_pct >= 0 ? "var(--green)" : "var(--red)" }}>
                    {fmt(r.total_return_pct, true)}
                  </td>
                  <td style={{ fontFamily: "monospace" }}>{r.num_trades}</td>
                  <td style={{ fontFamily: "monospace" }}>{fmt(r.win_rate, true, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
