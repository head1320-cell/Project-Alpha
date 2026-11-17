"use client";
/**
 * '시장 국면별로 나눠 보기' 절 — 시행의 일별 손익을 그날 시가 전에 알던 국면별로(K2a) + 하루 유형 비율(K2b) (설계 2026-11-17 §3 · 구현 계획 §7.3)
 * ==========================================================================
 * 분봉 결과 화면(백테스트 › 분봉 규칙)과 캔버스 '분봉 결과 조회' 판이 ★같은 부품 · 같은 문★을 쓴다(K2c — 캔버스 판은 위젯끼리 들일 수 없어 여기로 내렸다).
 * ★읽기만이다★ — 서버는 시행 줄을 읽고 국면을 계산할 뿐 시행을 남기지 않는다(시행 수 불변). 국면 수는 비어서 시작하고 비어 있으면 보내지 않는다.
 * 지수 목록 · 국면 수 범위는 시장 국면의 상한 문으로만 그린다(화면이 상수를 따로 두지 않는다). 거절 · 없음은 서버 사유 그대로, 실패는 재시도.
 * 물을 시행 열쇠가 없으면 부르는 쪽이 준 문장(`missing`)을 보이고 묻지 않는다.
 * 아래에 '하루 유형 비율'을 둔다 — 같은 지수 · 국면 수 칸을 쓰고, 그 칸이 바뀌면 그 답도 지운다(다른 물음의 답을 남기지 않는다).
 * `level` = 이 절 머리의 단계(화면 2 · 캔버스 판 3) — 하위 절은 한 단계 아래. 다른 시행을 보이면 부르는 쪽이 `key` 로 새로 그린다(앞의 답 · 고른 칸을 남기지 않는다).
 * `narrow` = 좁은 자리(캔버스 판 — 300 ~ 392px)다: 모형 칸의 글이 잘릴 수 있어 고른 모형의 이름 전체를 칸 아래 줄로 다시 적는다.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getMarketRegimeLimits, getRegimeSplit, type MarketIndex, type MarketRegimeLimits, type RegimeSplitAnswer } from "@/entities/intraday";
import { RetryFail, Section } from "@/shared/ui/tx";
import { RegimeDayTypesPart } from "./RegimeDayTypesPart";
import { RegimeRequestFailure } from "./RegimeRequestFailure";
import { RegimeSplitTable } from "./RegimeSplitTable";

const SUB = "이 시행의 일별 손익을 그날 시가 전에 알던 시장 국면(가장 큰 확률)별로 나눕니다. "
  + "시행을 새로 남기지 않습니다. 관측이며 국면 조건을 넣으면 나아진다는 뜻이 아닙니다.";

type RsForm = { index: MarketIndex; k: string };
type View =
  | { kind: "idle" } | { kind: "pending" }
  | { kind: "fail"; status: number; error: string; again: () => void }
  | { kind: "done"; value: RegimeSplitAnswer };

export function RegimeSplitBlock({ trialKey, level, missing, narrow = false }: {
  trialKey: string | null | undefined; level: 2 | 3; missing: string; narrow?: boolean;
}) {
  return (
    <Section title="시장 국면별로 나눠 보기" sub={SUB} level={level}>
      <div className="tj-map itd-rs">
        {trialKey ? <RegimeSplitForm trialKey={trialKey} sub={level === 2 ? 3 : 4} narrow={narrow} /> : (
          <p className="itd-why itd-rs-no-trial">{missing}</p>
        )}
      </div>
    </Section>
  );
}

function RegimeSplitForm({ trialKey, sub, narrow }: { trialKey: string; sub: 3 | 4; narrow: boolean }) {
  const limits = useQuery({ queryKey: ["intraday", "market-regime", "limits"], queryFn: async () => {
    const r = await getMarketRegimeLimits();
    if (!r.ok) throw Object.assign(new Error(r.error), { status: r.status });
    return r.value;
  }, staleTime: Infinity, retry: false });
  const [form, setForm] = useState<RsForm>({ index: "KOSPI", k: "" });
  const [view, setView] = useState<View>({ kind: "idle" });
  const [model, setModel] = useState("");                       // 하루 유형 비율(K2b)의 모형 — 비어서 시작(도구가 고르지 않는다)
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
      {view.kind === "fail" ? <RegimeRequestFailure status={view.status} error={view.error} again={view.again} /> : null}
      {view.kind === "done" ? <RegimeSplitTable a={view.value} /> : null}
      {limits.data ? (
        <RegimeDayTypesPart key={`${form.index}:${form.k}`} trialKey={trialKey} index={form.index} k={form.k} model={model} setModel={setModel}
                            level={sub} narrow={narrow} />
      ) : null}
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
