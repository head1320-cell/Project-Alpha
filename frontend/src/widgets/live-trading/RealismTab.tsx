"use client";
/**
 * 실거래 [현실성 점검] 탭 (ST3c) — "백테스트의 이상적 결과가 현실 조건에서 얼마나 달라지나".
 * ==========================================================================
 * 옛 `/admin/realism`(어두운 조종석 · 계산 전에 MOCK 숫자를 결과처럼 · 유동성 그림은 늘 MOCK · 클라이언트 상수 분배)을 옮겼다.
 * ★[계산하기] 전 요청 0★ → 등록 전략 목록 → 같은 `/realism/backtest` 를 이상(조건 전부 끔)·현실(넷 켬)로 두 번.
 * 숫자는 서버 값만. 한쪽이 실패하면 그쪽 사유만 보이고 견주는 그림은 그리지 않는다.
 * 그림 다섯(옛 화면과 같은 수): 이상과 현실 사이(날짜로 맞춘 두 곡선 + 틈) · 어디서 달라졌나(원화 폭포) ·
 * 현실 조건이 한 일(카드 넷) · 적응 모드 나눔 막대 · 유동성·수용량(틀 + 몰라요 사유).
 */
import Link from "next/link";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Area, ComposedChart, Line, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { multibacktestApi } from "@/entities/multibacktest";
import {
  IDEAL_FLAGS, REAL_FLAGS, RECIPE, erosionKrw, joinByDate, runRealism, type RealismRun, type Side,
} from "@/entities/realism";
import { num, priceWon } from "@/shared/lib/krFormat";
import { PerfLabel } from "@/shared/ui/PerfLabel";
import { Notice, Segmented } from "@/shared/ui/tx";

type Outcome = { kind: "no-strategies" } | { kind: "ran"; names: Record<string, string>; ideal: Side; real: Side };

/** 원 단위 큰 금액 → "88억 1,790만원"(억 아래는 만 단위로 자름). 부호는 따로 붙인다. */
export function eokWon(v: number): string {
  const a = Math.abs(v);
  const eok = Math.floor(a / 1e8); const man = Math.round((a % 1e8) / 1e4);
  if (eok === 0) return `${num(man)}만원`;
  return man ? `${num(eok)}억 ${num(man)}만원` : `${num(eok)}억원`;
}
const signed = (v: number, f: (x: number) => string) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${f(v)}`;
const pct = (v: number | null | undefined) => (v == null ? "몰라요" : signed(v, (x) => `${Math.abs(x).toFixed(2)}%`));

export function RealismTab() {
  const calc = useMutation({
    mutationFn: async (): Promise<Outcome> => {
      const list = await multibacktestApi.strategies(true);
      if (!list.length) return { kind: "no-strategies" };
      const ids = list.map((s) => s.id);
      const [ideal, real] = await Promise.all([runRealism(ids, IDEAL_FLAGS), runRealism(ids, REAL_FLAGS)]);
      return { kind: "ran", names: Object.fromEntries(list.map((s) => [String(s.id), s.name])), ideal, real };
    },
  });
  const o = calc.data;

  return (
    <div className="rl">
      <section className="tx-sec rl-intro" aria-labelledby="rl-h">
        <header className="tx-sec-head"><div>
          <h2 className="tx-sec-t" id="rl-h">현실성 점검</h2>
          <p className="tx-sec-sub">
            등록한 전략 전부를 {RECIPE.start_date} ~ {RECIPE.end_date}, 초기 자본 {eokWon(RECIPE.initial_capital)}, 계층 위험 균형(HRP)·매월
            리밸런싱으로 두 번 계산해요. 한 번은 현실 조건 없이(이상), 한 번은 시장 충격·현금 이자·매수 여력·적응 모드를 넣어서(현실).
          </p>
        </div>
        <div className="tx-sec-aside">
          <button type="button" className="tx-btn tx-btn--main rl-calc" data-act="calc" disabled={calc.isPending}
                  aria-busy={calc.isPending} onClick={() => calc.mutate()}>
            {calc.isPending ? "두 번 계산하는 중이에요" : o ? "다시 계산하기" : "계산하기"}
          </button>
        </div></header>
        {!o && !calc.isError && !calc.isPending ? (
          <div className="tx-sec-body"><p className="tx-sec-sub rl-empty">아직 계산하지 않았어요. 누르기 전에는 서버에 아무것도 묻지 않아요.</p></div>
        ) : null}
      </section>

      {calc.isError ? (
        <Notice tone="danger" title="등록한 전략 목록을 불러오지 못했어요"><span data-server>{calc.error.message}</span></Notice>
      ) : o?.kind === "no-strategies" ? (
        <section className="tx-sec rl-none">
          <p className="lv-strong">등록한 전략이 없어요.</p>
          <p className="tx-sec-sub">백테스트 결과 화면의 [전략으로 등록]으로 실행을 전략으로 올리면 여기서 계산할 수 있어요.</p>
          <Link href="/backtest" className="tx-btn tx-btn--sub">백테스트로 가기</Link>
        </section>
      ) : o?.kind === "ran" ? (
        <Result ideal={o.ideal} real={o.real} names={o.names} />
      ) : null}
    </div>
  );
}

function Result({ ideal, real, names }: { ideal: Side; real: Side; names: Record<string, string> }) {
  if (!ideal.ok || !real.ok) {
    return (
      <div className="rl-fails">
        {!ideal.ok ? <Notice tone="danger" title="이상 쪽(현실 조건 없이)을 계산하지 못했어요"><span data-server>{ideal.reason}</span></Notice> : null}
        {!real.ok ? <Notice tone="danger" title="현실 쪽(현실 조건을 넣고)을 계산하지 못했어요"><span data-server>{real.reason}</span></Notice> : null}
        <p className="tx-sec-sub rl-fails-why">한쪽만 있으면 견줄 수 없어서 그림을 그리지 않았어요.</p>
      </div>
    );
  }
  return <Compared i={ideal.run} r={real.run} names={{ ...names, ...(real.run.strategy_names ?? {}) }} />;
}

function Compared({ i, r, names }: { i: RealismRun; r: RealismRun; names: Record<string, string> }) {
  const ti = i.summary.total_return_pct; const tr = r.summary.total_return_pct;
  const gap = ti != null && tr != null ? tr - ti : null;
  const sentence = ti == null || tr == null
    ? "총수익률 하나를 서버가 주지 않아 견줄 수 없어요."
    : `현실 조건을 넣은 총수익률은 ${pct(tr)}로, 이상적 조건 ${pct(ti)}보다 ${Math.abs(gap ?? 0).toFixed(2)}%p ${gap === 0 ? "같아요" : (gap ?? 0) > 0 ? "높아요" : "낮아요"}.`;
  return (
    <>
      <section className="tx-sec rl-answer" data-sec="answer">
        <p className="rl-ans-s">{sentence}</p>
        <dl className="rl-figs">
          <div><dt>이상 끝 자산</dt><dd>{i.summary.final_equity == null ? "몰라요" : priceWon(i.summary.final_equity)}</dd></div>
          <div><dt>현실 끝 자산</dt><dd>{r.summary.final_equity == null ? "몰라요" : priceWon(r.summary.final_equity)}</dd></div>
          <div><dt>최대 낙폭(이상 · 현실)</dt><dd>{pct(i.summary.max_drawdown_pct)} · {pct(r.summary.max_drawdown_pct)}</dd></div>
          <div><dt>리밸런싱</dt><dd>{r.summary.n_rebalances == null ? "몰라요" : `${num(r.summary.n_rebalances)}번`}</dd></div>
        </dl>
        <div className="rl-label"><PerfLabel value={r.perf_label ?? null} /></div>
        {gap != null && gap > 0 ? (
          <p className="tx-sec-sub rl-note">현실 쪽이 더 높게 나올 수도 있어요. 적응 모드는 비중 자체를 바꿔서 이상과 다른 배분으로 돌아요. 그 몫은 아래 폭포의 나머지에 들어 있어요.</p>
        ) : null}
      </section>
      <GapChart i={i} r={r} />
      <Waterfall i={i} r={r} />
      <WhatItDid r={r} />
      <Capacity names={names} />
    </>
  );
}

// ── ① 이상과 현실 사이 ──────────────────────────────────────────────────────

type Focus = "both" | "ideal" | "real";
function GapChart({ i, r }: { i: RealismRun; r: RealismRun }) {
  const [focus, setFocus] = useState<Focus>("both");
  const { rows, missingReal, missingIdeal } = joinByDate(i.daily_records, r.daily_records);
  const dim = (k: Focus) => (focus === "both" || focus === k ? 1 : 0.25);
  return (
    <section className="tx-sec rl-sec" data-sec="gap" aria-labelledby="rl-gap-h">
      <header className="tx-sec-head"><div>
        <h2 className="tx-sec-t" id="rl-gap-h">이상과 현실 사이</h2>
        <p className="tx-sec-sub">두 자산 곡선을 같은 날짜끼리 맞췄어요. 사이 음영이 현실 조건이 만든 틈이에요.</p>
      </div>
      <div className="tx-sec-aside">
        <Segmented label="강조할 곡선" value={focus} onChange={setFocus}
                   options={[{ value: "both", label: "둘 다" }, { value: "ideal", label: "이상" }, { value: "real", label: "현실" }]} />
      </div></header>
      <div className="tx-sec-body">
        <div className="rl-chart" role="img" aria-label={`이상과 현실 자산 곡선 ${rows.length}일`} data-days={rows.length}>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <XAxis dataKey="date" tick={{ fontSize: 12, fill: "var(--tx-sub)" }} minTickGap={48} />
              <YAxis width={64} tick={{ fontSize: 12, fill: "var(--tx-sub)" }} domain={["auto", "auto"]}
                     tickFormatter={(v: number) => `${Math.round(v / 1e8)}억`} />
              <Area dataKey="band" stroke="none" fill="var(--tx-blue)" fillOpacity={0.12} isAnimationActive={false} />
              <Line dataKey="ideal" name="이상" dot={false} stroke="var(--tx-mute)" strokeWidth={2} strokeDasharray="5 4"
                    strokeOpacity={dim("ideal")} isAnimationActive={false} />
              <Line dataKey="real" name="현실" dot={false} stroke="var(--tx-blue)" strokeWidth={2.5}
                    strokeOpacity={dim("real")} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <ul className="rl-legend">
          <li data-k="ideal"><span aria-hidden className="rl-sw rl-sw--ideal" /> 이상(현실 조건 없이)</li>
          <li data-k="real"><span aria-hidden className="rl-sw rl-sw--real" /> 현실(조건 넣고)</li>
          <li data-k="gap"><span aria-hidden className="rl-sw rl-sw--gap" /> 둘 사이의 틈</li>
        </ul>
        {missingReal || missingIdeal ? (
          <p className="tx-sec-sub rl-missing">한쪽에만 있는 날: 현실 쪽에 없는 날 {num(missingReal)}일 · 이상 쪽에 없는 날 {num(missingIdeal)}일.</p>
        ) : null}
      </div>
    </section>
  );
}

// ── ② 어디서 달라졌나 (원화 폭포) ─────────────────────────────────────────────

const STEP_KO = { ideal: "이상 끝 자산", impact: "시장 충격 비용", cash: "현금 이자", rest: "나머지", real: "현실 끝 자산" } as const;
function Waterfall({ i, r }: { i: RealismRun; r: RealismRun }) {
  const steps = erosionKrw(i, r);
  return (
    <section className="tx-sec rl-sec" data-sec="waterfall" aria-labelledby="rl-wf-h">
      <header className="tx-sec-head"><div>
        <h2 className="tx-sec-t" id="rl-wf-h">어디서 달라졌나</h2>
        <p className="tx-sec-sub">서버가 따로 센 두 금액(시장 충격 비용 · 현금 이자)만 세웠어요. 나머지는 매수 여력·적응 모드·복리가 섞인 몫이라 서버가 나누지 않았어요.</p>
      </div></header>
      <div className="tx-sec-body">
        {!steps ? <p className="tx-sec-sub">끝 자산이나 두 금액 중 하나를 서버가 주지 않아 나눌 수 없어요.</p> : <Bars steps={steps} />}
      </div>
    </section>
  );
}

function Bars({ steps }: { steps: { key: keyof typeof STEP_KO; value: number }[] }) {
  // 막대는 이상 끝 자산을 기준으로 한 누적 위치 — 바닥은 가장 낮은 누적값보다 조금 아래(전체 자산을 0 부터 그리면 차이가 안 보인다).
  let run = 0;
  const spans = steps.map((s) => {
    if (s.key === "ideal" || s.key === "real") { run = s.value; return { ...s, from: 0, to: s.value, total: true }; }
    const from = run; run += s.value; return { ...s, from, to: run, total: false };
  });
  const lo = Math.min(...spans.map((s) => (s.total ? s.to : Math.min(s.from, s.to))));
  const hi = Math.max(...spans.map((s) => Math.max(s.from, s.to)));
  const floor = lo - (hi - lo) * 0.6;
  const x = (v: number) => ((v - floor) / (hi - floor)) * 100;
  return (
    <ol className="rl-wf">
      {spans.map((s) => {
        const a = s.total ? 0 : x(Math.min(s.from, s.to)); const b = x(Math.max(s.from, s.to));
        const dir = s.total ? "total" : s.value > 0 ? "up" : s.value < 0 ? "down" : "flat";
        return (
          <li key={s.key} className="rl-wf-row" data-step={s.key} data-dir={dir} data-value={Math.round(s.value)}>
            <span className="rl-wf-n">{STEP_KO[s.key]}</span>
            <span className="rl-wf-track"><span className="rl-wf-bar" style={{ left: `${a}%`, width: `${Math.max(0.6, b - a)}%` }} /></span>
            <span className="rl-wf-v">{s.total ? eokWon(s.value) : signed(s.value, (v) => eokWon(v))}</span>
          </li>
        );
      })}
    </ol>
  );
}

// ── ③ 현실 조건이 한 일 + 적응 모드 나눔 ──────────────────────────────────────

const MODE_KO: Record<string, string> = { normal: "보통", cautious: "조심", defensive: "방어" };
function WhatItDid({ r }: { r: RealismRun }) {
  const s = r.realism_stats;
  const dist = s.mode_distribution_pct ?? null;
  const known = (v: number | null | undefined, f: (x: number) => string) => (v == null ? "몰라요" : f(v));
  return (
    <section className="tx-sec rl-sec" data-sec="did" aria-labelledby="rl-did-h">
      <header className="tx-sec-head"><div>
        <h2 className="tx-sec-t" id="rl-did-h">현실 조건이 한 일</h2>
        <p className="tx-sec-sub">현실 쪽 계산에서 조건마다 서버가 센 값이에요.</p>
      </div></header>
      <div className="tx-sec-body">
        <ul className="rl-cards">
          <li className="rl-card" data-k="impact"><p className="rl-card-t">시장 충격</p>
            <p className="rl-card-v">{known(s.total_market_impact_cost, (v) => eokWon(v))}</p>
            <p className="rl-card-d">리밸런싱 한 번에 평균 {known(s.avg_market_impact_bps_per_rebalance, (v) => `${v.toFixed(1)}bp`)}. 큰 주문이 값을 미는 몫이에요.</p></li>
          <li className="rl-card" data-k="cash"><p className="rl-card-t">현금 이자</p>
            <p className="rl-card-v">{known(s.total_cash_yield, (v) => eokWon(v))}</p>
            <p className="rl-card-d">놀린 현금에 붙은 이자, 연 {known(s.cash_yield_annualized_pct, (v) => `${v.toFixed(2)}%`)}.</p></li>
          <li className="rl-card" data-k="buying"><p className="rl-card-t">매수 여력</p>
            <p className="rl-card-v">{known(s.total_buying_power_truncations, (v) => `${num(v)}번 줄였어요`)}</p>
            <p className="rl-card-d">리밸런싱 {known(r.summary.n_rebalances, (v) => `${num(v)}번`)} 중 현금이 모자라 사는 양을 줄인 횟수예요.</p></li>
          <li className="rl-card" data-k="adaptive"><p className="rl-card-t">적응 모드</p>
            <p className="rl-card-v">{dist ? `보통 ${dist.normal ?? 0}%` : "몰라요"}</p>
            <p className="rl-card-d">{r.regime_adaptive?.reason ? <span data-server>{r.regime_adaptive.reason}</span> : "적응 모드 근거를 서버가 주지 않았어요."}</p></li>
        </ul>
        {dist ? (
          <div className="rl-modes" role="img" aria-label={`적응 모드 날짜 나눔 ${Object.entries(dist).map(([k, v]) => `${MODE_KO[k] ?? k} ${v}%`).join(", ")}`}>
            <div className="rl-modes-bar">
              {Object.entries(dist).filter(([, v]) => v > 0).map(([k, v]) => <span key={k} className="rl-mode" data-mode={k} style={{ width: `${v}%` }} />)}
            </div>
            <ul className="rl-modes-l">
              {Object.entries(dist).map(([k, v]) => <li key={k} data-mode={k}><span aria-hidden className="rl-mode-sw" data-mode={k} /> {MODE_KO[k] ?? <span data-server>{k}</span>} {v}%</li>)}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}

// ── ④ 유동성·수용량 (틀 + 몰라요) ────────────────────────────────────────────

function Capacity({ names }: { names: Record<string, string> }) {
  const rows = Object.entries(names);
  return (
    <section className="tx-sec rl-sec" data-sec="capacity" aria-labelledby="rl-cap-h">
      <header className="tx-sec-head"><div>
        <h2 className="tx-sec-t" id="rl-cap-h">유동성·수용량</h2>
        <p className="tx-sec-sub">전략마다 시장이 받아 줄 수 있는 돈의 크기예요. 서버가 전략별 수용량을 주지 않았어요. 이번 계산은 용량 제약을 켜지 않았어요.</p>
      </div></header>
      <div className="tx-sec-body">
        <ul className="rl-caps">
          {rows.map(([id, n]) => (
            <li key={id} className="rl-cap" data-id={id}>
              <span className="rl-cap-n">{n}</span>
              <span className="rl-cap-track" aria-hidden />
              <span className="rl-cap-v">수용량 몰라요</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
