"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// BacktestCompare — 두 실행 비교 (스펙 §5e)
//   실행 A(현재 run) vs 실행 B(완료된 다른 run 선택) — 정규화 자산곡선 오버레이 +
//   핵심 지표 델타 표 + 설정/스냅샷 차이. 완료·결과 없는 실행은 정직하게 비교 불가 표기.
//   신규 백엔드 없음: 기존 list()/get()만 사용.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { backtestRunApi, type RunFull } from "@/entities/backtest-run/api";
import type { BacktestStatistics } from "@/entities/backtest/bridgeModel";

interface Row { k: keyof BacktestStatistics; label: string; suffix?: string; digits?: number; higherBetter: boolean }
const CMP_METRICS: Row[] = [
  { k: "total_return_pct", label: "총수익률", suffix: "%", higherBetter: true },
  { k: "cagr", label: "CAGR", suffix: "%", higherBetter: true },
  { k: "max_drawdown_pct", label: "최대낙폭(MDD)", suffix: "%", higherBetter: false },
  { k: "volatility_pct", label: "변동성(연)", suffix: "%", higherBetter: false },
  { k: "sharpe_ratio", label: "Sharpe", digits: 2, higherBetter: true },
  { k: "sortino_ratio", label: "Sortino", digits: 2, higherBetter: true },
  { k: "calmar_ratio", label: "Calmar", digits: 2, higherBetter: true },
  { k: "win_rate", label: "승률", suffix: "%", higherBetter: true },
  { k: "profit_factor", label: "손익비(PF)", digits: 2, higherBetter: true },
  { k: "num_trades", label: "거래수", digits: 0, higherBetter: true },
];
const CFG_ROWS: [string, string][] = [
  ["universe", "유니버스"], ["strategy_name", "전략"], ["start_date", "시작일"], ["end_date", "종료일"],
  ["benchmark", "벤치마크"], ["rebalance_frequency", "리밸런스"], ["initial_capital", "초기자본"],
  ["commission_rate", "수수료(bp)"], ["slippage_rate", "슬리피지(bp)"],
];

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fmt = (v: unknown, r: Row) => {
  const n = num(v); if (n == null) return "—";
  return `${n.toLocaleString("ko-KR", { maximumFractionDigits: r.digits ?? 1 })}${r.suffix ?? ""}`;
};
const normalize = (curve: number[] | undefined) => {
  if (!curve || curve.length === 0 || !curve[0]) return [];
  return curve.map((v) => (v / curve[0]) * 100);
};

export function BacktestCompare({ runId }: { runId: string }) {
  const router = useRouter();
  // 결과 페이지와 같은 이유로 항상 최신 상태를 읽는다(전역 staleTime 24h 회피).
  const aQ = useQuery({
    queryKey: ["btrun", "full", runId], queryFn: () => backtestRunApi.get(runId),
    staleTime: 0, refetchOnMount: "always",
  });
  const listQ = useQuery({ queryKey: ["btrun", "list"], queryFn: () => backtestRunApi.list(), staleTime: 0 });
  const [bId, setBId] = useState<string>("");
  const bQ = useQuery({
    queryKey: ["btrun", "full", bId], queryFn: () => backtestRunApi.get(bId), enabled: !!bId,
    staleTime: 0, refetchOnMount: "always",
  });

  const candidates = useMemo(
    () => (listQ.data?.runs ?? []).filter((r) => r.status === "completed" && r.run_id !== runId),
    [listQ.data, runId],
  );

  if (aQ.isLoading) return <div className="brun-shell"><div className="brun-loading">불러오는 중…</div></div>;
  if (aQ.isError || !aQ.data) return (
    <div className="brun-shell"><div className="brun-err">실행을 찾을 수 없습니다.
      <button className="brun-btn" onClick={() => router.push("/backtest")}>← 편집기로</button></div></div>
  );
  const a = aQ.data;
  const aComparable = a.status === "completed" && !!a.result;

  return (
    <div className="brun-shell">
      <header className="brun-rhead">
        <div>
          <div className="brun-crumb num">BACKTEST COMPARE · {runId}</div>
          <h1 className="brun-title">실행 비교</h1>
          <div className="brun-rmeta num">A: {a.strategy_name}</div>
        </div>
        <div className="brun-rhead-r">
          <button className="brun-btn" onClick={() => router.push(`/backtest/runs/${runId}/results`)}>← 결과로</button>
        </div>
      </header>

      {!aComparable && <div className="brun-mocknote">실행 A가 완료 상태가 아니어서 비교할 수 없습니다 (상태: {a.status}).</div>}

      <section className="brun-card">
        <div className="brun-card-t">실행 B 선택 <span className="brun-note">완료된 다른 실행만</span></div>
        {candidates.length === 0 ? (
          <div className="brun-note">비교할 완료된 다른 실행이 없습니다 — 백테스트를 하나 더 실행하세요.</div>
        ) : (
          <select className="brun-select" value={bId} onChange={(e) => setBId(e.target.value)}>
            <option value="">— 실행 B 선택 —</option>
            {candidates.map((r) => (
              <option key={r.run_id} value={r.run_id}>{r.strategy_name} · {r.run_id}</option>
            ))}
          </select>
        )}
      </section>

      {bId && bQ.isLoading && <div className="brun-loading">실행 B 불러오는 중…</div>}
      {bId && bQ.data && aComparable && <CompareBody a={a} b={bQ.data} />}
    </div>
  );
}

function CompareBody({ a, b }: { a: RunFull; b: RunFull }) {
  const bComparable = b.status === "completed" && !!b.result;
  const overlay = useMemo(() => {
    const ea = normalize(a.result?.backtest.equity_curve);
    const eb = normalize(b.result?.backtest.equity_curve);
    const n = Math.max(ea.length, eb.length);
    return Array.from({ length: n }, (_, i) => ({ i, A: ea[i] ?? null, B: eb[i] ?? null }));
  }, [a, b]);
  const lenMismatch = (a.result?.backtest.equity_curve?.length ?? 0) !== (b.result?.backtest.equity_curve?.length ?? 0);

  if (!bComparable) return <div className="brun-mocknote">실행 B가 완료 상태가 아니어서 비교할 수 없습니다 (상태: {b.status}).</div>;
  const sa = a.result!.backtest.statistics as BacktestStatistics;
  const sb = b.result!.backtest.statistics as BacktestStatistics;

  return (
    <>
      <section className="brun-card">
        <div className="brun-card-t">정규화 자산곡선 (시작=100)</div>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={overlay} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="2 3" stroke="#eee" />
            <XAxis dataKey="i" tick={{ fontSize: 9 }} minTickGap={60} />
            <YAxis tick={{ fontSize: 9 }} width={44} />
            <Tooltip formatter={(v: number) => v?.toFixed(1)} contentStyle={{ fontSize: 11 }} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line type="monotone" dataKey="A" stroke="#1200ff" dot={false} strokeWidth={1.6} name={`A · ${a.strategy_name}`} />
            <Line type="monotone" dataKey="B" stroke="#e11d48" dot={false} strokeWidth={1.4} name={`B · ${b.strategy_name}`} />
          </LineChart>
        </ResponsiveContainer>
        {lenMismatch && <div className="brun-note">두 실행의 기간·길이가 달라 인덱스 기준으로 정렬했습니다 — 절대 비교는 주의.</div>}
      </section>

      <section className="brun-card">
        <div className="brun-card-t">지표 델타 <span className="brun-note">Δ = B − A · 초록 = B 우위</span></div>
        <div className="brun-tablewrap">
          <table className="brun-table brun-cmp">
            <thead><tr><th>지표</th><th>A</th><th>B</th><th>Δ</th></tr></thead>
            <tbody>
              {CMP_METRICS.filter((r) => num(sa[r.k]) != null || num(sb[r.k]) != null).map((r) => {
                const va = num(sa[r.k]); const vb = num(sb[r.k]);
                const d = va != null && vb != null ? vb - va : null;
                const better = d == null ? 0 : (r.higherBetter ? Math.sign(d) : -Math.sign(d));
                const dc = better > 0 ? "#16a34a" : better < 0 ? "#dc2626" : undefined;
                return (
                  <tr key={r.k}>
                    <td>{r.label}</td>
                    <td className="num">{fmt(va, r)}</td>
                    <td className="num">{fmt(vb, r)}</td>
                    <td className="num" style={{ color: dc }}>{d == null ? "—" : `${d >= 0 ? "+" : ""}${d.toLocaleString("ko-KR", { maximumFractionDigits: r.digits ?? 1 })}${r.suffix ?? ""}`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="brun-card">
        <div className="brun-card-t">설정 차이 <span className="brun-note">다른 값만 강조</span></div>
        <div className="brun-tablewrap">
          <table className="brun-table brun-cmp">
            <thead><tr><th>항목</th><th>A</th><th>B</th></tr></thead>
            <tbody>
              {CFG_ROWS.map(([k, label]) => {
                const ca = (a.input_snapshot ?? {})[k]; const cb = (b.input_snapshot ?? {})[k];
                if (ca == null && cb == null) return null;
                const diff = String(ca ?? "—") !== String(cb ?? "—");
                return (
                  <tr key={k} className={diff ? "brun-cmp-diff" : ""}>
                    <td>{label}</td>
                    <td className="num">{ca == null ? "—" : String(ca)}</td>
                    <td className="num">{cb == null ? "—" : String(cb)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
