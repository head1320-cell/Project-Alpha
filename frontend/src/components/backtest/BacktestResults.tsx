"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// BacktestResults — 전용 백테스트 결과 워크스페이스 (스펙 §5, 고정 URL·새로고침 가능)
//   Header / Overview(지표) / Performance(자산곡선·낙폭·월간) / Trades / Symbols.
//   엔진이 실제 반환한 데이터만 렌더(없는 지표는 생략) · real/mock/PIT 배지 정직 표기.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { backtestRunApi, type RunFull } from "@/lib/backtestRunApi";
import type { BacktestStatistics, BacktestTrade, MonthlyReturn, SymbolPerf } from "@/lib/screenerApi";

type Stat = keyof BacktestStatistics;
interface MetricDef { k: Stat; label: string; tip: string; suffix?: string; digits?: number; signed?: boolean }
const METRICS: MetricDef[] = [
  { k: "total_return_pct", label: "총수익률", tip: "기간 전체 누적 수익률", suffix: "%", signed: true },
  { k: "cagr", label: "CAGR", tip: "연평균 복리 성장률", suffix: "%", signed: true },
  { k: "max_drawdown_pct", label: "최대낙폭(MDD)", tip: "고점 대비 최대 하락폭", suffix: "%" },
  { k: "volatility_pct", label: "변동성(연)", tip: "연율화 표준편차", suffix: "%" },
  { k: "sharpe_ratio", label: "Sharpe", tip: "무위험 대비 위험조정수익 (초과수익/변동성)", digits: 2 },
  { k: "sortino_ratio", label: "Sortino", tip: "하방위험 기준 위험조정수익", digits: 2 },
  { k: "calmar_ratio", label: "Calmar", tip: "CAGR / |MDD|", digits: 2 },
  { k: "win_rate", label: "승률", tip: "이익 거래 비율", suffix: "%" },
  { k: "profit_factor", label: "손익비(PF)", tip: "총이익 / 총손실", digits: 2 },
  { k: "num_trades", label: "거래수", tip: "총 체결(라운드트립) 수", digits: 0 },
  { k: "var_pct", label: "95% VaR", tip: "95% 신뢰수준 최대손실 추정", suffix: "%" },
  { k: "cvar_pct", label: "95% CVaR", tip: "VaR 초과 시 평균손실(꼬리)", suffix: "%" },
  { k: "total_commission", label: "수수료", tip: "누적 수수료(원)", digits: 0 },
  { k: "total_slippage", label: "슬리피지", tip: "누적 슬리피지(원)", digits: 0 },
];

const num = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? null : v);
const fmtStat = (v: number | null | undefined, m: MetricDef) => {
  const n = num(v);
  if (n == null) return "—";
  const s = m.suffix ?? "";
  const sign = m.signed && n >= 0 ? "+" : "";
  return `${sign}${n.toLocaleString("ko-KR", { maximumFractionDigits: m.digits ?? 1 })}${s}`;
};
const col = (v: number | null | undefined) => (num(v) == null ? undefined : (v as number) >= 0 ? "#16a34a" : "#dc2626");

export function BacktestResults({ runId }: { runId: string }) {
  const router = useRouter();
  const q = useQuery({ queryKey: ["btrun", "full", runId], queryFn: () => backtestRunApi.get(runId) });

  if (q.isLoading) return <div className="brun-shell"><div className="brun-loading">결과 불러오는 중…</div></div>;
  if (q.isError || !q.data) return <div className="brun-shell"><div className="brun-err">결과를 찾을 수 없습니다.
    <button className="brun-btn" onClick={() => router.push("/backtest")}>← 편집기로</button></div></div>;

  const run = q.data;
  if (run.status !== "completed" || !run.result) {
    return <div className="brun-shell"><div className="brun-err">
      이 실행은 {run.status} 상태입니다 — 완료된 결과가 없습니다.
      <button className="brun-btn" onClick={() => router.push(`/backtest/runs/${runId}/loading`)}>진행 상황 보기</button>
    </div></div>;
  }
  return <ResultsBody runId={runId} run={run} router={router} />;
}

function ResultsBody({ runId, run, router }: { runId: string; run: RunFull; router: ReturnType<typeof useRouter> }) {
  const res = run.result!;
  const bt = res.backtest;
  const stats = bt.statistics as BacktestStatistics;
  const cfg = (run.input_snapshot ?? {}) as Record<string, unknown>;
  const isMock = run.is_mock_data === true || !res.data_source?.fully_real;

  const equity = useMemo(() => (bt.equity_curve || []).map((v, i) => ({
    i, date: bt.equity_dates?.[i] ?? String(i), equity: v,
    bench: bt.benchmark?.curve?.[i] ?? null, dd: bt.drawdown_curve?.[i] ?? null,
  })), [bt]);
  const monthly = useMemo(() => (bt.monthly_returns || []).map((m, i) =>
    typeof m === "number" ? { month: String(i), return_pct: m } : (m as MonthlyReturn)), [bt.monthly_returns]);
  const roundTrips = bt.round_trips && bt.round_trips.length ? bt.round_trips : bt.trades || [];

  const retry = async () => { try { const r = await backtestRunApi.retry(runId); router.push(`/backtest/runs/${r.run_id}/loading`); } catch { /* ignore */ } };

  return (
    <div className="brun-shell brun-results">
      {/* Header */}
      <header className="brun-rhead">
        <div>
          <div className="brun-crumb num">BACKTEST RESULT · {runId}</div>
          <h1 className="brun-title">{run.strategy_name}</h1>
          <div className="brun-rmeta num">
            {String(cfg.universe ?? "—")} · {String(cfg.start_date ?? "")}~{String(cfg.end_date ?? "")}
            {bt.benchmark?.label ? ` · 벤치 ${bt.benchmark.label}` : ""} · 엔진 {run.engine_version ?? "—"}
          </div>
        </div>
        <div className="brun-rhead-r">
          <span className={`brun-badge ${isMock ? "mock" : "real"}`}>{isMock ? "MOCK 데이터" : "실데이터"}</span>
          <span className={`brun-badge ${run.is_pit_verified ? "real" : "warn"}`}>{run.is_pit_verified ? "PIT 검증" : "PIT 미검증"}</span>
          <button className="brun-btn" onClick={retry}>동일 설정 재실행</button>
          <button className="brun-btn primary" onClick={() => router.push("/backtest")}>← 편집기로</button>
        </div>
      </header>
      {isMock && <div className="brun-mocknote">합성(mock) 데이터 기준 결과입니다 — 수치는 참고용. 실데이터는 GCP 적재 후 자동 반영됩니다.</div>}

      {/* Overview */}
      <section className="brun-card">
        <div className="brun-card-t">개요 지표 <span className="brun-note">데이터 없는 지표는 표시하지 않음</span></div>
        <div className="brun-kpis">
          {METRICS.filter((m) => num(stats[m.k] as number) != null).map((m) => (
            <div key={m.k} className="brun-kpi" title={m.tip}>
              <div className="brun-kpi-l">{m.label}</div>
              <div className="brun-kpi-v num" style={{ color: m.signed ? col(stats[m.k] as number) : undefined }}>
                {fmtStat(stats[m.k] as number, m)}
              </div>
            </div>
          ))}
        </div>
        {stats.eod_liquidated ? <div className="brun-note">기간종료 청산 {stats.eod_liquidated}종목 — 마지막 거래일 종가로 실현.</div> : null}
      </section>

      {/* Performance */}
      {equity.length > 1 && (
        <section className="brun-card">
          <div className="brun-card-t">자산곡선 {bt.benchmark ? "vs 벤치마크" : ""}</div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={equity} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="2 3" stroke="#eee" />
              <XAxis dataKey="date" tick={{ fontSize: 9 }} minTickGap={60} />
              <YAxis tick={{ fontSize: 9 }} width={48} />
              <Tooltip formatter={(v: number) => v?.toLocaleString("ko-KR")} labelStyle={{ fontSize: 10 }} contentStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="equity" stroke="#1200ff" dot={false} strokeWidth={1.6} name="전략" />
              {bt.benchmark && <Line type="monotone" dataKey="bench" stroke="#999" dot={false} strokeDasharray="4 3" strokeWidth={1.2} name={bt.benchmark.label} />}
            </LineChart>
          </ResponsiveContainer>
          {bt.benchmark && (
            <div className="brun-benchrow num">
              벤치 {bt.benchmark.total_return_pct?.toFixed(1)}% · 초과 <b style={{ color: col(bt.benchmark.excess_return_pct) }}>{bt.benchmark.excess_return_pct?.toFixed(1)}%</b>
              · β {bt.benchmark.beta?.toFixed(2)} · α {bt.benchmark.alpha_pct?.toFixed(1)}%
            </div>
          )}
        </section>
      )}

      {bt.drawdown_curve?.some((d) => d < 0) && (
        <section className="brun-card">
          <div className="brun-card-t">낙폭 (Underwater)</div>
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={equity} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="2 3" stroke="#eee" />
              <XAxis dataKey="date" tick={{ fontSize: 9 }} minTickGap={60} />
              <YAxis tick={{ fontSize: 9 }} width={48} />
              <Tooltip formatter={(v: number) => `${v?.toFixed(1)}%`} contentStyle={{ fontSize: 11 }} />
              <Area type="monotone" dataKey="dd" stroke="#dc2626" fill="rgba(220,38,38,.12)" strokeWidth={1} name="낙폭" />
            </AreaChart>
          </ResponsiveContainer>
        </section>
      )}

      {monthly.length > 0 && (
        <section className="brun-card">
          <div className="brun-card-t">월별 수익률</div>
          <ResponsiveContainer width="100%" height={130}>
            <BarChart data={monthly} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="2 3" stroke="#eee" />
              <XAxis dataKey="month" tick={{ fontSize: 8 }} minTickGap={20} />
              <YAxis tick={{ fontSize: 9 }} width={40} />
              <Tooltip formatter={(v: number) => `${v?.toFixed(2)}%`} contentStyle={{ fontSize: 11 }} />
              <Bar dataKey="return_pct">
                {monthly.map((m, i) => <Cell key={i} fill={m.return_pct >= 0 ? "#16a34a" : "#dc2626"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* Symbols */}
      {bt.symbol_results && bt.symbol_results.length > 0 && <SymbolTable rows={bt.symbol_results} />}

      {/* Trades */}
      {roundTrips.length > 0 && <TradesTable trades={roundTrips} />}
    </div>
  );
}

function SymbolTable({ rows }: { rows: SymbolPerf[] }) {
  const sorted = [...rows].sort((a, b) => (b.contribution_pct ?? b.total_return_pct) - (a.contribution_pct ?? a.total_return_pct));
  return (
    <section className="brun-card">
      <div className="brun-card-t">종목별 성과 <span className="brun-note">{rows.length}종목 · 기여도순</span></div>
      <div className="brun-tablewrap">
        <table className="brun-table">
          <thead><tr><th>종목</th><th>수익률</th><th>실현손익</th><th>거래</th><th>승률</th><th>보유일</th><th>기여도</th></tr></thead>
          <tbody>
            {sorted.slice(0, 40).map((r) => (
              <tr key={r.symbol}>
                <td>{r.corp_name || r.symbol}<span className="brun-code num">{r.symbol}</span></td>
                <td className="num" style={{ color: col(r.total_return_pct) }}>{r.total_return_pct?.toFixed(1)}%</td>
                <td className="num">{r.realized_pnl != null ? Math.round(r.realized_pnl).toLocaleString("ko-KR") : "—"}</td>
                <td className="num">{r.round_trips ?? r.num_trades}</td>
                <td className="num">{r.win_rate?.toFixed(0)}%</td>
                <td className="num">{r.avg_hold_days != null ? Math.round(r.avg_hold_days) : "—"}</td>
                <td className="num" style={{ color: col(r.contribution_pct) }}>{r.contribution_pct != null ? `${r.contribution_pct.toFixed(1)}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TradesTable({ trades }: { trades: BacktestTrade[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="brun-card">
      <div className="brun-card-t">거래 로그 <span className="brun-note">{trades.length}건 · 행 클릭 = 상세</span></div>
      <div className="brun-tablewrap">
        <table className="brun-table">
          <thead><tr><th>종목</th><th>진입일</th><th>청산일</th><th>진입가</th><th>청산가</th><th>수익률</th><th>사유</th></tr></thead>
          <tbody>
            {trades.slice(0, 200).map((t, i) => (
              <React.Fragment key={i}>
                <tr className="brun-trow" onClick={() => setOpen(open === i ? null : i)}>
                  <td>{t.corp_name || t.stock_code}</td>
                  <td className="num">{t.entry_date ?? "—"}</td>
                  <td className="num">{t.exit_date ?? "—"}</td>
                  <td className="num">{t.entry_price?.toLocaleString("ko-KR") ?? "—"}</td>
                  <td className="num">{t.exit_price?.toLocaleString("ko-KR") ?? "—"}</td>
                  <td className="num" style={{ color: col(t.return_pct) }}>{t.return_pct != null ? `${t.return_pct >= 0 ? "+" : ""}${t.return_pct.toFixed(1)}%` : "—"}</td>
                  <td className="brun-reason">{t.reason ?? "—"}</td>
                </tr>
                {open === i && (
                  <tr className="brun-tdetail"><td colSpan={7}>
                    <span>수량 {t.quantity?.toLocaleString("ko-KR") ?? "—"}</span>
                    <span>손익 {t.pnl != null ? Math.round(t.pnl).toLocaleString("ko-KR") : "—"}</span>
                    <span>종목코드 {t.stock_code ?? "—"}</span>
                    {t.reason && <span>청산사유 {t.reason}</span>}
                  </td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
