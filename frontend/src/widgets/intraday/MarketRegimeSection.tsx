"use client";
/**
 * 백테스트 › 분봉 규칙의 '시장 국면' 절 — 지수 · 국면 수 · 기간 → 날마다 국면 확률 (설계 2026-11-17 §2 · 구현 계획 §7.1 · K1)
 * ==========================================================================
 * 새 화면이 아니라 같은 화면의 절이다(ADR 006 §7 · 하루 유형 절 아래). ★도구는 국면 수를 고르지 않는다★ — 칸은 비어서 시작하고,
 * 비어 있으면 보내지 않는다. 국면 수 · 지수 · 상한은 서버의 상한 문(`/market-regime/limits`)으로만 그린다(화면이 상수를 따로 두지 않는다).
 * 기간의 처음 값은 규칙 설정 기간 그대로다 — 같은 날들의 국면을 본다. 거절은 서버 사유 그대로, 실패는 재시도.
 * 국면은 이름표다 — 예측이 아니고 뜻을 붙인 이름도 없다(번호와 통계만). 합성 지수(mock)면 맨 위에 서버 사유와 함께 알린다.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import {
  getMarketRegime, getMarketRegimeLimits, type MarketIndex, type MarketRegimeAnswer, type MarketRegimeLimits, type MarketRegimeRefusal,
} from "@/entities/intraday";
import { RegimeBand, RegimeFacts } from "@/features/intraday-market-regime";
import { loginHref } from "@/shared/lib/nextPath";
import { Notice, RetryFail, Section } from "@/shared/ui/tx";

const HERE = "/backtest/intraday";
const SUB = "지수의 20거래일 수익과 실현 변동성이 닮은 날끼리 GMM 으로 묶어 날마다 각 국면에 속할 확률을 보입니다. "
  + "그날의 확률은 전 거래일 종가까지로 계산합니다. 국면은 이름표이며 다음 날을 예측하지 않습니다.";
const ISO = /^\d{4}-\d{2}-\d{2}$/;

type MrForm = { index: MarketIndex; k: string; from: string; to: string };
type View =
  | { kind: "idle" } | { kind: "pending" }
  | { kind: "fail"; status: number; error: string; refusal: MarketRegimeRefusal | null; again: () => void }
  | { kind: "done"; value: MarketRegimeAnswer };

function problemsOf(f: MrForm): string[] {
  const out: string[] = [];
  if (!f.k) out.push("국면 수를 고르십시오.");
  if (!ISO.test(f.from) || !ISO.test(f.to)) out.push("기간의 시작일과 종료일을 넣으십시오.");
  else if (f.from > f.to) out.push("시작일이 종료일보다 늦습니다.");
  return out;
}

export function MarketRegimeSection({ from, to }: { from: string; to: string }) {
  const limits = useQuery({ queryKey: ["intraday", "market-regime", "limits"], queryFn: async () => {
    const r = await getMarketRegimeLimits();
    if (!r.ok) throw Object.assign(new Error(r.error), { status: r.status });
    return r.value;
  }, staleTime: Infinity, retry: false });
  const [form, setForm] = useState<MrForm>({ index: "KOSPI", k: "", from, to });
  const [view, setView] = useState<View>({ kind: "idle" });
  const problems = problemsOf(form);
  const set = (patch: Partial<MrForm>) => setForm({ ...form, ...patch });

  const run = async () => {
    if (problems.length) return;
    setView({ kind: "pending" });
    const r = await getMarketRegime({ index: form.index, k: Number(form.k), from: form.from, to: form.to });
    setView(r.ok ? { kind: "done", value: r.value } : { kind: "fail", status: r.status, error: r.error, refusal: r.refusal, again: () => void run() });
  };

  return (
    <Section title="시장 국면" sub={SUB}>
      <div className="tj-map itd-mr">
        {limits.isPending ? <p className="tx-sec-sub" aria-busy="true">상한 불러오는 중</p> : null}
        {limits.isError ? (
          <RetryFail title="상한 불러오기 실패" onRetry={() => void limits.refetch()}><span data-server>{limits.error.message}</span></RetryFail>
        ) : null}
        {limits.data ? <MrForm lim={limits.data} form={form} set={set} problems={problems} pending={view.kind === "pending"} onRun={() => void run()} /> : null}
        {view.kind === "fail" ? <Failure v={view} /> : null}
        {view.kind === "done" ? <MrResult a={view.value} /> : null}
      </div>
    </Section>
  );
}

function MrForm({ lim, form, set, problems, pending, onRun }: {
  lim: MarketRegimeLimits; form: MrForm; set: (p: Partial<MrForm>) => void; problems: string[]; pending: boolean; onRun: () => void;
}) {
  const ks = Array.from({ length: lim.k[1] - lim.k[0] + 1 }, (_, i) => String(lim.k[0] + i));
  return (
    <div className="itd-mr-form">
      <div className="tj-fields tj-fields--pair">
        <label className="tj-field"><span className="tj-label">지수<i className="tj-req">필수</i></span>
          <select className="tj-input itd-mr-index" value={form.index} onChange={(e) => set({ index: e.target.value as MarketIndex })}>
            {lim.indexes.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
          </select>
        </label>
        <label className="tj-field"><span className="tj-label">국면 수<i className="tj-req">필수</i></span>
          <select className="tj-input itd-mr-k" value={form.k} onChange={(e) => set({ k: e.target.value })}>
            <option value="">고르십시오</option>
            {ks.map((k) => <option key={k} value={k}>{k}개</option>)}
          </select>
        </label>
      </div>
      <div className="tj-fields tj-fields--pair">
        <label className="tj-field"><span className="tj-label">시작일<i className="tj-req">필수</i></span>
          <input className="tj-input itd-mr-from" type="date" value={form.from} max={form.to || undefined} onChange={(e) => set({ from: e.target.value })} /></label>
        <label className="tj-field"><span className="tj-label">종료일<i className="tj-req">필수</i></span>
          <input className="tj-input itd-mr-to" type="date" value={form.to} min={form.from || undefined} onChange={(e) => set({ to: e.target.value })} /></label>
      </div>
      <p className="itd-hint itd-mr-limits">
        {`국면 ${lim.k[0]}~${lim.k[1]}개 · 기간 ${lim.range_days}일까지 · 적합은 달마다 그달 첫 거래일 전 ${lim.fit_days.toLocaleString("ko-KR")}거래일 · `
          + `특징은 ${lim.window}거래일 수익과 실현 변동성 · 난수 시드 ${lim.seeds}개의 평균`}
      </p>
      <div className="tj-run-row">
        <button type="button" className="tx-btn tx-btn--main itd-mr-run" disabled={problems.length > 0 || pending} onClick={onRun}>
          {pending ? "계산 중" : "국면 보기"}
        </button>
        {problems.length ? <ul className="tj-map-miss itd-mr-problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul> : null}
      </div>
    </div>
  );
}

function MrResult({ a }: { a: MarketRegimeAnswer }) {
  return (
    <div className="itd-mr-result" data-index={a.index} data-k={a.k} data-grade={a.grade ?? "unknown"}>
      <p className="itd-mr-head">{a.name} · 국면 {a.k}개 · <span className="itd-mr-range">{a.from} ~ {a.to}</span>{a.grade ? ` · 출처 등급 ${a.grade}` : ""}</p>
      {a.grade === "E0" ? (
        <div className="itd-mr-synth">
          <Notice tone="warn" title="합성 지수 일봉입니다.">
            {a.coverage.reason ? <><span data-server>{a.coverage.reason}</span> </> : null}국면은 장치 확인용이며 시장에 대한 진술이 아닙니다.
          </Notice>
        </div>
      ) : null}
      {a.grade === null && a.grade_reason ? <p className="itd-why itd-mr-grade"><span data-server>{a.grade_reason}</span></p> : null}
      {a.coverage.ok === false && a.grade !== "E0" && a.coverage.reason ? (
        <p className="itd-why itd-mr-coverage"><span data-server>{a.coverage.reason}</span></p>
      ) : null}
      {a.empty ? (
        <div className="itd-mr-empty" data-empty={a.empty.reason}>
          <Notice tone="danger" title="국면을 계산하지 않았습니다."><span data-server>{a.empty.message}</span></Notice>
        </div>
      ) : (
        <>
          <RegimeBand days={a.days} k={a.k} />
          <RegimeFacts a={a} />
        </>
      )}
    </div>
  );
}

function Failure({ v }: { v: Extract<View, { kind: "fail" }> }) {
  if (v.status === 401) {
    return <Notice tone="danger" title="로그인 세션이 만료됐습니다.">다시 로그인하십시오. <Link href={loginHref(HERE)} className="tj-link">로그인</Link></Notice>;
  }
  if (v.status === 400 || v.status === 422) {
    return <Notice tone="danger" title="요청 거절"><span data-server>{v.refusal?.reason ?? v.error}</span></Notice>;
  }
  return <RetryFail title="요청 실패" onRetry={v.again}><span data-server>{v.error}</span></RetryFail>;
}
