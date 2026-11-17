"use client";
/**
 * 분봉 결과의 '시장 국면별로 나눠 보기' 절 — 방금 남은 시행의 일별 손익을 국면별로 (설계 2026-11-17 §3 · 구현 계획 §7.3 · K2a)
 * ==========================================================================
 * ★읽기만이다★ — 서버는 시행 줄을 읽고 국면을 계산할 뿐 시행을 남기지 않는다(시행 수 불변). 국면 수는 비어서 시작하고 비어 있으면 보내지 않는다.
 * 지수 목록 · 국면 수 범위는 시장 국면의 상한 문으로만 그린다(화면이 상수를 따로 두지 않는다). 거절 · 없음은 서버 사유 그대로, 실패는 재시도.
 * 시행을 기록하지 못한 실행이면 물을 열쇠가 없다 — 그렇게 적고 묻지 않는다.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { getMarketRegimeLimits, getRegimeSplit, type MarketIndex, type MarketRegimeLimits, type RegimeSplitAnswer } from "@/entities/intraday";
import { RegimeSplitTable } from "@/features/intraday-regime-split";
import { loginHref } from "@/shared/lib/nextPath";
import { Notice, RetryFail, Section } from "@/shared/ui/tx";

const HERE = "/backtest/intraday";
const SUB = "이 시행의 일별 손익을 그날 시가 전에 알던 시장 국면(가장 큰 확률)별로 나눕니다. "
  + "시행을 새로 남기지 않습니다. 관측이며 국면 조건을 넣으면 나아진다는 뜻이 아닙니다.";

type RsForm = { index: MarketIndex; k: string };
type View =
  | { kind: "idle" } | { kind: "pending" }
  | { kind: "fail"; status: number; error: string; again: () => void }
  | { kind: "done"; value: RegimeSplitAnswer };

export function RegimeSplitSection({ trialKey }: { trialKey: string | null | undefined }) {
  return (
    <Section title="시장 국면별로 나눠 보기" sub={SUB}>
      <div className="tj-map itd-rs">
        {trialKey ? <RegimeSplitForm trialKey={trialKey} /> : (
          <p className="itd-why itd-rs-no-trial">이 실행은 시행으로 기록되지 않아 국면별로 나눌 수 없습니다.</p>
        )}
      </div>
    </Section>
  );
}

function RegimeSplitForm({ trialKey }: { trialKey: string }) {
  const limits = useQuery({ queryKey: ["intraday", "market-regime", "limits"], queryFn: async () => {
    const r = await getMarketRegimeLimits();
    if (!r.ok) throw Object.assign(new Error(r.error), { status: r.status });
    return r.value;
  }, staleTime: Infinity, retry: false });
  const [form, setForm] = useState<RsForm>({ index: "KOSPI", k: "" });
  const [view, setView] = useState<View>({ kind: "idle" });
  const set = (patch: Partial<RsForm>) => { setForm({ ...form, ...patch }); setView({ kind: "idle" }); };

  const run = async () => {
    if (!form.k) return;
    setView({ kind: "pending" });
    const r = await getRegimeSplit(trialKey, { index: form.index, k: Number(form.k) });
    setView(r.ok ? { kind: "done", value: r.value } : { kind: "fail", status: r.status, error: r.error, again: () => void run() });
  };

  return (
    <>
      {limits.isPending ? <p className="tx-sec-sub" aria-busy="true">상한 불러오는 중</p> : null}
      {limits.isError ? (
        <RetryFail title="상한 불러오기 실패" onRetry={() => void limits.refetch()}><span data-server>{limits.error.message}</span></RetryFail>
      ) : null}
      {limits.data ? <Fields lim={limits.data} form={form} set={set} pending={view.kind === "pending"} onRun={() => void run()} /> : null}
      {view.kind === "fail" ? <Failure v={view} /> : null}
      {view.kind === "done" ? <RegimeSplitTable a={view.value} /> : null}
    </>
  );
}

function Fields({ lim, form, set, pending, onRun }: {
  lim: MarketRegimeLimits; form: RsForm; set: (p: Partial<RsForm>) => void; pending: boolean; onRun: () => void;
}) {
  const ks = Array.from({ length: lim.k[1] - lim.k[0] + 1 }, (_, i) => String(lim.k[0] + i));
  return (
    <div className="itd-rs-form">
      <div className="tj-fields tj-fields--pair">
        <label className="tj-field"><span className="tj-label">지수<i className="tj-req">필수</i></span>
          <select className="tj-input itd-rs-index" value={form.index} onChange={(e) => set({ index: e.target.value as MarketIndex })}>
            {lim.indexes.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
          </select>
        </label>
        <label className="tj-field"><span className="tj-label">국면 수<i className="tj-req">필수</i></span>
          <select className="tj-input itd-rs-k" value={form.k} onChange={(e) => set({ k: e.target.value })}>
            <option value="">고르십시오</option>
            {ks.map((k) => <option key={k} value={k}>{k}개</option>)}
          </select>
        </label>
      </div>
      <div className="tj-run-row">
        <button type="button" className="tx-btn tx-btn--main itd-rs-run" disabled={!form.k || pending} onClick={onRun}>
          {pending ? "나누는 중" : "국면별로 나누기"}
        </button>
        {!form.k ? <ul className="tj-map-miss itd-rs-problems"><li>국면 수를 고르십시오.</li></ul> : null}
      </div>
    </div>
  );
}

function Failure({ v }: { v: Extract<View, { kind: "fail" }> }) {
  if (v.status === 401) {
    return <Notice tone="danger" title="로그인 세션이 만료됐습니다.">다시 로그인하십시오. <Link href={loginHref(HERE)} className="tj-link">로그인</Link></Notice>;
  }
  if (v.status === 400 || v.status === 404 || v.status === 422) {
    return <Notice tone="danger" title="요청 거절"><span data-server>{v.error}</span></Notice>;
  }
  return <RetryFail title="요청 실패" onRetry={v.again}><span data-server>{v.error}</span></RetryFail>;
}
