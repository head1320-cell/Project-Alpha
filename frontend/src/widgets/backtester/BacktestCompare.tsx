"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// BacktestCompare — 두 실행 비교 (스펙 §5e)
//   실행 A(현재 run) vs 실행 B(완료된 다른 run 선택) — ★둘 겹쳐 보기★(2026-11-09 · 성과 그림 문법 ③): 두 곡선·차이·해마다 차이·
//   지표 차이는 서버 `POST /api/v1/perf/compare` 가 맞추고 뺀다(캔버스 비교 노드와 같은 함수). 화면은 서식만 · 설정 차이는 문자열 비교.
//   완료·결과 없는 실행은 정직하게 비교 불가 표기.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { backtestRunApi, type RunFull } from "@/entities/backtest-run/api";
import type { BacktestStatistics } from "@/entities/backtest/bridgeModel";
import { perfApi } from "@/entities/perf/api";
import Link from "next/link";
import { PerfLabel } from "@/shared/ui/PerfLabel";
import { CompareYearTable } from "@/shared/ui/perf/CompareYearTable";
import { DrawdownEpisodes } from "@/shared/ui/perf/DrawdownEpisodes";
import { PerfCompare } from "@/shared/ui/perf/PerfCompare";
import { compareViewOf, type MetricDiffRow } from "@/shared/ui/perf/perfView";
import { Notice, PageHead } from "@/shared/ui/tx";

// BU4: ★차이만 말한다★ 예전 `higherBetter` 로 "초록 = B 우위" 를 칠했다 — 어느 쪽이 나은지는 화면이 정할 일이 아니다
// (낙폭이 깊어도 수익이 크면 고르는 사람이 있다 · 금지 표현 "더 나은 전략"). 차이의 색은 부호만 따른다(한국식).
interface Row { k: keyof BacktestStatistics; label: string; suffix?: string; digits?: number; pp?: boolean }
const CMP_METRICS: Row[] = [
  { k: "total_return_pct", label: "총수익률", suffix: "%", pp: true },
  { k: "cagr", label: "연평균 수익률", suffix: "%", pp: true },
  { k: "max_drawdown_pct", label: "최대낙폭", suffix: "%", pp: true },
  { k: "volatility_pct", label: "변동성(연)", suffix: "%", pp: true },
  { k: "sharpe_ratio", label: "샤프 지수", digits: 2 },
  { k: "sortino_ratio", label: "소르티노 지수", digits: 2 },
  { k: "calmar_ratio", label: "칼마 비율", digits: 2 },
  { k: "win_rate", label: "이긴 거래 비율", suffix: "%", pp: true },
  { k: "profit_factor", label: "손익비", digits: 2 },
  { k: "num_trades", label: "거래 수", digits: 0 },
];
/** 답에 싣는 차이 셋 — 이름 뒤 조사까지(받침에 맞게). */
const HEADLINE: Array<{ k: keyof BacktestStatistics; name: string; topic: string }> = [
  { k: "total_return_pct", name: "총수익률", topic: "총수익률은" },
  { k: "max_drawdown_pct", name: "최대 낙폭", topic: "최대 낙폭은" },
  { k: "sharpe_ratio", name: "샤프 지수", topic: "샤프 지수는" },
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
const fmtDelta = (d: number, r: Row) => d === 0 ? "같아요" : `${d > 0 ? "+" : ""}${d.toLocaleString("ko-KR", { maximumFractionDigits: r.digits ?? 1 })}${r.pp ? "%p" : (r.suffix ?? "")}`;
const signColor = (d: number | null) => (d == null || d === 0 ? undefined : d > 0 ? "var(--tx-up-ink)" : "var(--tx-down-ink)");

export function BacktestCompare({ runId }: { runId: string }) {
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

  if (aQ.isLoading) return <div className="tx-page brun-shell rs"><div className="brun-loading">불러오는 중이에요</div></div>;
  if (aQ.isError || !aQ.data) return (
    <div className="tx-page brun-shell rs">
      <div className="brun-err rs-state">
        <Notice tone="warn" title="이 실행을 찾지 못했어요">만료되었거나 잘못된 링크일 수 있어요.</Notice>
        <div className="rs-acts"><Link href="/backtest" className="tx-btn tx-btn--sub">편집기로 돌아가기</Link></div>
      </div>
    </div>
  );
  const a = aQ.data;
  const aComparable = a.status === "completed" && !!a.result;

  return (
    <div className="tpage-fade tx-page brun-shell rs rs-cmp">
      <PageHead title="실행 비교"
        lede={<>A · {a.strategy_name} <span className="rs-id" aria-label="실행 번호">{runId}</span></>}
        actions={<Link href={`/backtest/runs/${runId}/results`} className="tx-btn tx-btn--sub">A 결과로 돌아가기</Link>} />
      {/* ★두 실행의 종류가 같다고 가정하지 않는다★ — 하나는 실데이터, 하나는
          mock 일 수 있고 그때 Δ 는 전략 차이가 아니다(Z3). */}
      <div className="rs-labels"><PerfLabel value={a.perf_label} scope="A" /></div>

      {!aComparable && <Notice tone="warn" title="실행 A 가 끝나지 않아 비교할 수 없어요">지금 상태: {a.status}</Notice>}

      <section className="brun-card rs-card">
        <h2 className="brun-card-t">견줄 실행 B<span className="brun-note">끝난 다른 실행만</span></h2>
        {listQ.isError ? (
          <Notice tone="danger" title="실행 목록을 불러오지 못했어요">서버에 닿지 않았어요. 잠시 뒤 새로 고쳐 주세요.</Notice>
        ) : candidates.length === 0 ? (
          <p className="rs-empty">견줄 수 있는 끝난 실행이 아직 없어요 — 편집기에서 하나 더 실행해 보세요.</p>
        ) : (
          <select className="brun-select" value={bId} onChange={(e) => setBId(e.target.value)} aria-label="견줄 실행 B">
            <option value="">실행 B 고르기</option>
            {candidates.map((r) => (
              <option key={r.run_id} value={r.run_id}>{r.strategy_name} · {r.run_id}</option>
            ))}
          </select>
        )}
      </section>

      {bId && bQ.isLoading && <div className="brun-loading">실행 B 를 불러오는 중이에요</div>}
      {bId && bQ.isError && <Notice tone="danger" title="실행 B 를 불러오지 못했어요">다른 실행을 고르거나 잠시 뒤 다시 골라 주세요.</Notice>}
      {bId && bQ.data && aComparable && <CompareBody a={a} b={bQ.data} />}
    </div>
  );
}

function CompareBody({ a, b }: { a: RunFull; b: RunFull }) {
  const bComparable = b.status === "completed" && !!b.result;
  // ★차이는 서버가 뺀다★ — 두 곡선(원)·지표·해마다 수익을 보내면 날짜 합집합/순번으로 맞춘 곡선(처음 100)·차이(%p)·지표 차이 행이 온다.
  const side = (r: RunFull, label: string) => ({
    label, dates: (r.result?.backtest.equity_dates ?? []).map(String), equity: r.result?.backtest.equity_curve ?? [],
    stats: (r.result?.backtest.statistics ?? null) as Record<string, unknown> | null, periods: r.perf?.periods ?? null,
  });
  const cmpQ = useQuery({
    queryKey: ["perf", "compare", a.run_id, b.run_id],
    queryFn: () => perfApi.compare({ a: side(a, "A"), b: side(b, "B"), base: 100, metrics: "page" }),
    enabled: bComparable, staleTime: 0, retry: 1,
  });

  if (!bComparable) return <Notice tone="warn" title="실행 B 가 끝나지 않아 비교할 수 없어요">지금 상태: {b.status}</Notice>;
  const rows: MetricDiffRow[] | null = cmpQ.data?.rows ?? null;
  const rowOf = (k: keyof BacktestStatistics): MetricDiffRow | null => rows?.find((r) => r.key === k) ?? null;
  const specOf = (k: string): Row => CMP_METRICS.find((r) => r.k === k) ?? { k: k as keyof BacktestStatistics, label: k };
  const view = cmpQ.data
    ? compareViewOf(cmpQ.data, { unit: "base100", labelA: "A", labelB: "B", perfLabelA: a.perf_label ?? null, perfLabelB: b.perf_label ?? null,
                                 question: "두 조건식이 같은 자리에서 어떻게 다른가", drawdownsA: a.perf?.drawdowns ?? null, drawdownsB: b.perf?.drawdowns ?? null })
    : null;
  const retry = <button type="button" className="tx-btn tx-btn--sub" onClick={() => void cmpQ.refetch()}>다시 시도</button>;

  return (
    <>
      {/* ★답 = 서버가 뺀 차이(B − A)만★ 어느 쪽이 낫다고 말하지 않는다. 한쪽 값이 없으면 0 이 아니라 "비교할 수 없어요". */}
      <section className="tx-answer rs-answer" aria-label="한 줄 답">
        <p className="tx-answer-s">B 는 A 와 이만큼 달라요</p>
        {cmpQ.isPending && <p className="rs-diff-wait">차이를 재는 중이에요</p>}
        {cmpQ.isError && <Notice tone="danger" title="차이를 재지 못했어요">{(cmpQ.error as Error).message} {retry}</Notice>}
        {rows && (
          <ul className="rs-diff">
            {HEADLINE.map((h) => {
              const r = rowOf(h.k);
              if (!r || r.diff == null) {
                return <li key={h.k} className="rs-diff-na">{h.topic} 비교할 수 없어요 — {r?.a == null ? "A" : "B"} 에 값이 없어요</li>;
              }
              return (
                <li key={h.k}>
                  <span>{h.name}</span> <b style={{ color: signColor(r.diff) }}>{fmtDelta(r.diff, specOf(h.k))}</b>
                </li>
              );
            })}
          </ul>
        )}
        <div className="brun-cmp-labels">
          <PerfLabel value={a.perf_label} scope="A" />
          <PerfLabel value={b.perf_label} scope="B" />
        </div>
        <p className="rs-why">B 는 {b.strategy_name} · A 는 {a.strategy_name}. 두 실행의 데이터 종류가 다르면 차이는 전략의 차이가 아니에요.</p>
      </section>

      <section className="brun-card rs-card">
        <h2 className="brun-card-t">자산곡선 (시작 = 100)<span className="brun-note">A 는 잉크 · B 는 색 · 아래 띠는 차이(B − A)</span></h2>
        {cmpQ.isPending && <p className="brun-loading">두 곡선을 맞추는 중이에요</p>}
        {cmpQ.isError && <Notice tone="danger" title="두 곡선을 맞추지 못했어요">{(cmpQ.error as Error).message} {retry}</Notice>}
        {view && (
          <>
            <PerfCompare view={view} height={280} />
            <h3 className="pg-h4">해마다 차이</h3>
            <CompareYearTable view={view} />
            <div className="pf-cmp-eps">
              <div><h3 className="pg-h4">A 의 큰 낙폭 사건</h3><DrawdownEpisodes episodes={view.drawdowns?.a ?? null} /></div>
              <div><h3 className="pg-h4">B 의 큰 낙폭 사건</h3><DrawdownEpisodes episodes={view.drawdowns?.b ?? null} /></div>
            </div>
          </>
        )}
      </section>

      <section className="brun-card rs-card">
        <h2 className="brun-card-t">지표 차이<span className="brun-note">차이 = B − A · 서버가 뺀 값 · 색은 부호만(오름 빨강 · 내림 파랑)</span></h2>
        <div className="brun-tablewrap">
          <table className="brun-table brun-cmp">
            <thead><tr><th>지표</th><th>A</th><th>B</th><th>차이</th></tr></thead>
            <tbody>
              {(rows ?? []).filter((r) => r.a != null || r.b != null).map((r) => {
                const spec = specOf(r.key);
                return (
                  <tr key={r.key}>
                    <td>{r.label}</td>
                    <td className="num">{fmt(r.a, spec)}</td>
                    <td className="num">{fmt(r.b, spec)}</td>
                    <td className="num" style={{ color: signColor(r.diff) }}>{r.diff == null ? "비교할 수 없어요" : fmtDelta(r.diff, spec)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="brun-card rs-card">
        <h2 className="brun-card-t">설정 차이<span className="brun-note">다른 값만 굵게</span></h2>
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
