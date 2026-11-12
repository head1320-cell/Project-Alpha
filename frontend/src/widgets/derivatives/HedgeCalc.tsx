"use client";
// 선물 헤지 — `/calculate-hedge`(지수 선물로 포트폴리오 베타 맞추기). 서버 방향 글("매도 (Short)")은 한국어로만 옮긴다 — 모르는 글은 그대로.
// ★위험 감소가 null 이면 0% 가 아니라 서버 사유★(β=0 이면 줄일 시장 위험이 없다 — BL3 M).
import { useState } from "react";
import { api, type HedgeOut } from "@/shared/api/legacyApi";
import { won as wonK } from "@/shared/lib/krFormat";
import { CalcFail, Fig, NumField, StaleNote, parse, sgn, useCalc, won, type Raw } from "./parts";

type Body = { portfolio_value: number; current_beta: number; target_beta: number; futures_price: number; multiplier: number };
/** 서버 `action` 의 앞말만 본다 — "매도 (Short)" → 매도. 둘 다 아니면 null(서버 글 그대로 보인다). */
export function actionKo(a: string): "매도" | "매수" | null {
  return a.startsWith("매도") ? "매도" : a.startsWith("매수") ? "매수" : null;
}

export function HedgeCalc() {
  const [raw, setRaw] = useState<Raw>({ pv: "100000000", beta: "1.2", target: "0", fut: "350", mult: "250000" });
  const calc = useCalc<Body, HedgeOut>((b) => api.futuresHedge(b));
  const set = (k: string) => (v: string) => setRaw((p) => ({ ...p, [k]: v }));
  const v = { pv: parse(raw.pv), beta: parse(raw.beta), target: parse(raw.target), fut: parse(raw.fut), mult: parse(raw.mult) };
  const miss = (k: keyof typeof v) => calc.tried && v[k] == null;
  const [bad, setBad] = useState(false);

  function run() {
    if (Object.values(v).some((x) => x == null)) { setBad(false); calc.run(raw, null); return; }
    const { pv, beta, target, fut, mult } = v as Record<keyof typeof v, number>;
    if (!(pv > 0 && fut > 0 && mult > 0 && Number.isInteger(mult))) { setBad(true); calc.run(raw, null); return; }
    setBad(false);
    calc.run(raw, { portfolio_value: pv, current_beta: beta, target_beta: target, futures_price: fut, multiplier: mult });
  }
  const h = calc.m.data;
  const act = h ? actionKo(h.action) : null;
  const n = h ? Math.abs(h.contracts_to_trade) : 0;

  return (
    <div className="dv-calc" data-calc="hedge">
      <section className="tx-sec dv-form">
        <h2 className="tx-sec-t">선물 헤지 입력값</h2>
        <p className="tx-sec-sub">포트폴리오의 시장 민감도(베타)를 목표에 맞추는 데 필요한 지수 선물 매매 계약 수를 계산합니다.</p>
        <div className="dv-grid">
          <NumField id="dv-pv" label="포트폴리오 금액" unit="원" value={raw.pv} onChange={set("pv")} missing={miss("pv")} hint={v.pv != null ? `${wonK(v.pv)}입니다` : undefined} />
          <NumField id="dv-beta" label="현재 베타" value={raw.beta} onChange={set("beta")} missing={miss("beta")} hint="시장 1% 변동 시 포트폴리오 변동률(%)" />
          <NumField id="dv-tgt" label="목표 베타" value={raw.target} onChange={set("target")} missing={miss("target")} hint="0 이면 시장 위험을 모두 덥니다" />
          <NumField id="dv-fut" label="선물 가격" unit="포인트" value={raw.fut} onChange={set("fut")} missing={miss("fut")} />
          <NumField id="dv-mult" label="계약 승수" unit="원" value={raw.mult} onChange={set("mult")} missing={miss("mult")} step="1" hint="1포인트당 금액(코스피200 선물 25만 원)" />
        </div>
        {bad && <p className="dv-bad" role="alert">포트폴리오 금액·선물 가격은 0보다 크고, 계약 승수는 양의 정수여야 계산할 수 있습니다.</p>}
        <button type="button" className="tx-btn tx-btn--main dv-go" onClick={run} disabled={calc.m.isPending}>
          {calc.m.isPending ? "계산 중" : "헤지 계산하기"}
        </button>
      </section>

      {calc.m.isError ? <CalcFail what="헤지 계약 수" error={calc.m.error} onRetry={run} /> : null}
      {h ? (
        <section className="tx-sec dv-out" aria-live="polite" data-action-raw={h.action}>
          {calc.stale(raw) && <StaleNote onRerun={run} />}
          <p className="dv-ans">
            {n === 0 ? <>계약 수가 0이라 거래하지 않습니다. 베타는 {h.current_beta}에서 그대로입니다.</>
              : <>선물 <b>{n}계약을 {act ?? <span data-server>{h.action}</span>}</b>하면 베타가 {h.current_beta}에서 <b>{h.beta_after_rounding.toFixed(2)}</b>로 바뀝니다.</>}
          </p>
          <dl className="dv-figs" data-testid="hedge-figs">
            <Fig k="contracts" label="거래할 계약 수" value={`${n}계약${n && act ? ` ${act}` : ""}`} why={`계산으로는 ${sgn(h.raw_contracts, 2)}계약(음수는 매도)인데, 계약은 정수라 반올림했습니다.`} />
            <Fig k="beta_after" label="헤지 뒤 베타" value={h.beta_after_rounding.toFixed(2)} why={`목표는 ${h.target_beta}였습니다. 반올림 때문에 목표와 다를 수 있습니다.`} />
            <Fig k="reduction" label="시장 위험 감소" value={h.expected_var_reduction_pct == null ? "계산하지 않습니다" : `${h.expected_var_reduction_pct}%`}
              why={h.expected_var_reduction_pct == null ? <span data-server>{h.reduction_reason ?? "서버가 사유를 제공하지 않았습니다."}</span> : <span data-server>{h.reduction_basis}</span>} />
            <Fig k="contract_value" label="계약 한 개 금액" value={won(h.contract_value)} why="선물 가격 × 계약 승수입니다." />
            <Fig k="notional" label="헤지 금액" value={won(h.hedge_notional)} why="거래할 계약 수 × 계약 한 개 금액입니다." />
          </dl>
        </section>
      ) : null}
    </div>
  );
}
