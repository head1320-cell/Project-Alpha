"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// PolicyBacktest — 정책 walk-forward(OOS) 백테스트 (AAS 로드맵 07, 신뢰도 키스톤)
//   현재 포트폴리오·모델·뷰·제약을 그대로 시점 밖으로 재현. 각 리밸런싱 가중치는 과거
//   데이터로만 산출(look-ahead 없음), 리밸런싱마다 회전율 비용 차감. OOS 자산곡선 vs
//   벤치마크 · 낙폭 · 지표표 · 회전율 · 시점별 비중. mock/OOS/비용 정직 배지.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis, Legend,
} from "recharts";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { TIP_STYLE } from "@/shared/ui/chartStyle";
import { allocationApi, type AllocationBacktestResult } from "@/entities/allocation/api";
import { useChartAnimation } from "@/shared/ui/chartStyle";

const fmt = (v: number | null | undefined, s = "", d = 2) =>
  v == null || !Number.isFinite(v) ? "—" : `${v.toLocaleString("ko-KR", { maximumFractionDigits: d })}${s}`;

// ═══════════════════════════════════════════════════════════════════════════════
// ★이 파일이 마지막 남은 하드코딩 차트였다 (A6-C)★
// A4-X3 가 parts.tsx 의 툴팁·마커를 토큰으로 바꿨지만, 정책 백테스트는 parts.tsx 를
// 거치지 않고 Recharts 를 직접 쓰기 때문에 그 스윕에 잡히지 않았다. 남아 있던 값들:
//   #16a34a  — S1b-2 가 zinc-50 위 3.16:1 로 측정해 `--chart-up` 에서 이미 퇴출한 색.
//              같은 값이 여기서는 KPI **글자색**이었다(글자는 4.5:1 이 필요하다).
//   #dc2626 · #1200ff · #999 · #eee · #a5b4fc · rgba(220,38,38,.12)
//              — 전부 라이트 전용. 다크에서 격자와 벤치마크선이 배경에 묻는다.
//   Tooltip contentStyle={{fontSize:11}} — 배경 지정이 없어 Recharts 기본 흰 상자.
//              다크에서 글자는 #fafafa 로 뒤집히므로 A4-X3 이 고친 1.04:1 이 그대로다.
// 축 눈금 8~9px 은 SVG 속성이라 어떤 CSS 규칙도 닿지 않는다 — A5 가 SankeyNode 에서
// 겪은 것과 같은 자리라서 소스에서 올린다.
// ═══════════════════════════════════════════════════════════════════════════════
const col = (v: number | null | undefined) =>
  (v == null ? undefined : v >= 0 ? "var(--chart-up)" : "var(--chart-down)");
const AXIS_TICK = { fontSize: 11 };
const GRID = "var(--border)";

export function PolicyBacktest() {
  const anim = useChartAnimation();
  const { holdings, model, views, constraints } = useAllocation();
  const [rebalance, setRebalance] = useState<"M" | "Q">("M");
  const [windowMode, setWindowMode] = useState<"expanding" | "rolling">("expanding");
  const [windowDays, setWindowDays] = useState(252);
  const [costBps, setCostBps] = useState(10);

  const mut = useMutation<AllocationBacktestResult>({
    mutationFn: () => allocationApi.backtest({
      tickers: holdings.map((h) => h.code),
      model, views, constraints,
      benchmark: "KOSPI", rebalance,
      window_days: windowMode === "rolling" ? windowDays : null,
      cost_bps: costBps,
    }),
  });
  const res = mut.data;
  const ok = res && !res.error;

  const label = (c: string) => res?.labels?.[c] || c;
  const equity = ok && res.equity_curve
    ? res.equity_curve.map((v, i) => ({
        i, date: res.dates?.[i] ?? String(i),
        strat: +(v * 100).toFixed(2),
        bench: res.bench_curve?.[i] != null ? +(res.bench_curve[i] * 100).toFixed(2) : null,
        dd: res.drawdown_curve?.[i] ?? null,
      }))
    : [];
  const turns = ok && res.rebalances ? res.rebalances.map((r) => ({ date: r.date, turnover: r.turnover_pct })) : [];

  const isMock = res?.coverage?.source === "mock";
  const canRun = holdings.length >= 2;

  return (
    <div className="as-bt">
      <div className="as-bt-controls">
        <label className="as-tm-set"><span>리밸런싱</span>
          <select value={rebalance} onChange={(e) => setRebalance(e.target.value as "M" | "Q")}>
            <option value="M">월간</option><option value="Q">분기</option>
          </select>
        </label>
        <label className="as-tm-set"><span>학습 윈도우</span>
          <select value={windowMode} onChange={(e) => setWindowMode(e.target.value as "expanding" | "rolling")}>
            <option value="expanding">확장(전체 과거)</option><option value="rolling">롤링(고정 길이)</option>
          </select>
        </label>
        {windowMode === "rolling" && (
          <label className="as-tm-set"><span>롤링 일수</span>
            <input className="as-tm-num" type="number" min={63} max={1260} step={21}
              value={windowDays} onChange={(e) => setWindowDays(Math.max(63, +e.target.value || 252))} />
          </label>
        )}
        <label className="as-tm-set"><span>거래비용(bp)</span>
          <input className="as-tm-num" type="number" min={0} max={100} step={1}
            value={costBps} onChange={(e) => setCostBps(Math.max(0, Math.min(100, +e.target.value || 0)))} />
        </label>
        <button className="as-fb-apply" disabled={!canRun || mut.isPending} onClick={() => mut.mutate()}>
          {mut.isPending ? "백테스트 중…" : "정책 백테스트 실행 →"}
        </button>
      </div>

      {!canRun && <div className="as-empty">01 CONSTRUCT에서 자산을 2개 이상 담으면 정책을 OOS로 검증할 수 있습니다.</div>}
      {mut.isError && <div className="as-err">백테스트 실패 — 연결을 확인하고 재시도하세요.</div>}
      {res?.error && <div className="as-err">{res.message}</div>}

      {ok && (
        <>
          <div className="as-bt-badges">
            <span className={`as-bt-badge ${isMock ? "mock" : "real"}`}>{isMock ? "MOCK 데이터" : "실데이터"}</span>
            <span className="as-bt-badge ok">OOS · look-ahead 없음</span>
            <span className="as-bt-badge">{res.config?.window} · {rebalance === "M" ? "월간" : "분기"} · 비용 {res.config?.cost_bps}bp</span>
            <span className="num">{res.n_rebalances}회 리밸런싱 · 평균 회전율 {fmt(res.turnover_avg_pct, "%", 1)}</span>
          </div>

          {/* ★분포 무가정 예측 구간 (M2-C)★ 적중률은 이론 하한이 아니라 홀드아웃에서
              센 값이다. 구간이 없으면 숫자 대신 사유를 적는다 — 이 화면의 요점이다. */}
          {res.conformal && (
            <div className="as-bt-cf">
              <div className="as-bt-cf-t">다음 구간 예측 (분포 무가정)</div>
              {res.conformal.available && res.conformal.next_period ? (
                <>
                  <div className="as-bt-cf-row">
                    <span className="as-bt-cf-k">일평균 수익률 {Math.round((1 - res.conformal.alpha) * 100)}% 구간</span>
                    <b className="num">
                      {(res.conformal.next_period.lower * 100).toFixed(3)}% ~{" "}
                      {(res.conformal.next_period.upper * 100).toFixed(3)}%
                    </b>
                    <span className="as-bt-cf-k">점추정</span>
                    <b className="num">{(res.conformal.next_period.point * 100).toFixed(3)}%</b>
                    <span className="as-bt-cf-k">보정 쌍</span>
                    <b className="num">{res.conformal.n_pairs}</b>
                  </div>
                  <div className="as-bt-cf-row">
                    <span className="as-bt-cf-k">실측 적중률</span>
                    {res.conformal.measured_coverage?.available ? (
                      <b className="num">
                        {(res.conformal.measured_coverage.coverage! * 100).toFixed(1)}%
                        {" "}({res.conformal.measured_coverage.hits}/{res.conformal.measured_coverage.n})
                      </b>
                    ) : (
                      <span className="as-bt-cf-na">
                        {res.conformal.measured_coverage?.reason || "적중률을 잴 표본이 없습니다."}
                      </span>
                    )}
                  </div>
                </>
              ) : (
                <div className="as-bt-cf-na">{res.conformal.reason || "구간을 계산할 수 없습니다."}</div>
              )}
              {res.conformal.note && <div className="as-bt-cf-note">{res.conformal.note}</div>}
            </div>
          )}

          {/* 요약 지표 */}
          <div className="as-bt-kpis">
            {([
              ["총수익", res.summary?.total_return_pct, "%", true],
              ["CAGR", res.summary?.cagr_pct, "%", true],
              ["변동성", res.summary?.volatility_pct, "%", false],
              ["Sharpe", res.summary?.sharpe_ratio, "", false],
              ["MDD", res.summary?.max_drawdown_pct, "%", false],
              ["초과수익", res.summary?.active_return_pct, "%", true],
              ["정보비율", res.summary?.information_ratio, "", false],
              ["Sortino", res.summary?.sortino_ratio ?? null, "", false],
              ["Calmar", res.summary?.calmar_ratio ?? null, "", false],
              ["95% CVaR", res.metrics?.cvar_pct ?? null, "%", false],
            ] as [string, number | null | undefined, string, boolean][]).map(([k, v, s, signed]) => (
              <div key={k} className="as-bt-kpi">
                <div className="as-bt-kpi-l">{k}</div>
                <div className="as-bt-kpi-v num" style={{ color: signed ? col(v) : undefined }}>{fmt(v, s)}</div>
              </div>
            ))}
          </div>

          {/* OOS 자산곡선 vs 벤치마크 */}
          <div className="as-bt-card">
            <div className="as-bt-t">OOS 자산곡선 {res.benchmark_label ? `vs ${res.benchmark_label}` : ""} <span className="as-note">시작=100</span></div>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={equity} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="2 3" stroke={GRID} />
                <XAxis dataKey="date" tick={AXIS_TICK} minTickGap={70} />
                <YAxis tick={AXIS_TICK} width={48} />
                <Tooltip formatter={(v: number) => v?.toFixed(1)} contentStyle={TIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line isAnimationActive={anim} type="monotone" dataKey="strat" stroke="var(--t-accent)" dot={false} strokeWidth={1.6} name="정책" />
                {res.bench_curve && <Line isAnimationActive={anim} type="monotone" dataKey="bench" stroke="var(--t-muted)" dot={false} strokeDasharray="4 3" strokeWidth={1.2} name={res.benchmark_label ?? "벤치"} />}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* 낙폭 */}
          {res.drawdown_curve?.some((d) => d < 0) && (
            <div className="as-bt-card">
              <div className="as-bt-t">낙폭 (Underwater)</div>
              <ResponsiveContainer width="100%" height={130}>
                <AreaChart data={equity} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="2 3" stroke={GRID} />
                  <XAxis dataKey="date" tick={AXIS_TICK} minTickGap={70} />
                  <YAxis tick={AXIS_TICK} width={48} />
                  <Tooltip formatter={(v: number) => `${v?.toFixed(1)}%`} contentStyle={TIP_STYLE} />
                  <Area isAnimationActive={anim} type="monotone" dataKey="dd" stroke="var(--chart-down)"
                    fill="var(--chart-down-fill)" strokeWidth={1} name="낙폭" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* 회전율 */}
          {turns.length > 0 && (
            <div className="as-bt-card">
              <div className="as-bt-t">리밸런싱 회전율 (편도)</div>
              <ResponsiveContainer width="100%" height={110}>
                <BarChart data={turns} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="2 3" stroke={GRID} />
                  <XAxis dataKey="date" tick={AXIS_TICK} minTickGap={50} />
                  <YAxis tick={AXIS_TICK} width={44} />
                  <Tooltip formatter={(v: number) => `${v?.toFixed(1)}%`} contentStyle={TIP_STYLE} />
                  <Bar isAnimationActive={anim} dataKey="turnover" fill="var(--cat-4)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* 시점별 비중 (최근 8회) */}
          {res.rebalances && res.rebalances.length > 0 && (
            <div className="as-bt-card">
              <div className="as-bt-t">시점별 비중 <span className="as-note">최근 {Math.min(8, res.rebalances.length)}회</span></div>
              <div className="as-bt-wtbl-wrap">
                <table className="as-bt-wtbl">
                  <thead><tr><th>리밸런싱일</th>{holdings.map((h) => <th key={h.code} className="num">{label(h.code)}</th>)}<th className="num">회전율</th></tr></thead>
                  <tbody>
                    {res.rebalances.slice(-8).reverse().map((r) => (
                      <tr key={r.date}>
                        <td className="num">{r.date}</td>
                        {holdings.map((h) => <td key={h.code} className="num">{r.weights[label(h.code)] != null || r.weights[h.code] != null ? fmt(r.weights[label(h.code)] ?? r.weights[h.code], "%", 1) : "—"}</td>)}
                        <td className="num">{fmt(r.turnover_pct, "%", 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="as-note">
            OOS: 각 리밸런싱 가중치는 그 시점 이전 데이터로만 산출됩니다(look-ahead 없음). 뷰는 사용자의
            지속 테제로 매 시점 적용(미래 데이터 아님). 회전율 비용 반영. {isMock && "현재는 합성(mock) 시세 — 절대 수치는 참고용, 실데이터 적재 후 재실행하세요."}
          </div>
        </>
      )}
    </div>
  );
}
