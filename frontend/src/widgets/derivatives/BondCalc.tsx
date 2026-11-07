"use client";
// 채권 — `/analyze-bond`(고정금리, 만기 일시 상환). 금리 칸은 %로 넣고 서버에는 소수로 보낸다.
// 숫자 풀이는 서버 값의 정의 그대로다(DV01 = 수익률 0.01%p 변화에 따른 가격 변화 · 수정 듀레이션 = 1%p 당 가격 변화율).
import { useState } from "react";
import { api, type BondOut } from "@/shared/api/legacyApi";
import { Segmented } from "@/shared/ui/tx";
import { CalcFail, Fig, NumField, StaleNote, parse, useCalc, won, type Raw } from "./parts";

type Freq = "1" | "2" | "4";
type Body = { face_value: number; coupon_rate: number; ytm: number; years_to_maturity: number; freq: number };

export function BondCalc() {
  const [raw, setRaw] = useState<Raw>({ face: "10000", coupon: "3.5", ytm: "4", years: "5" });
  const [freq, setFreq] = useState<Freq>("2");
  const [bad, setBad] = useState(false);
  const calc = useCalc<Body, BondOut>((b) => api.bondAnalytics(b));
  const set = (k: string) => (v: string) => setRaw((p) => ({ ...p, [k]: v }));
  const v = { face: parse(raw.face), coupon: parse(raw.coupon), ytm: parse(raw.ytm), years: parse(raw.years) };
  const miss = (k: keyof typeof v) => calc.tried && v[k] == null;
  const key = { ...raw, freq };

  function run() {
    if (Object.values(v).some((x) => x == null)) { setBad(false); calc.run(key, null); return; }
    const { face, coupon, ytm, years } = v as Record<keyof typeof v, number>;
    // 서버 칸이 정수(`years_to_maturity: int`)라 소수 만기는 보내기 전에 막는다 — 반올림해 다른 채권을 계산하지 않는다.
    if (!(face > 0 && years >= 1 && Number.isInteger(years) && coupon >= 0)) { setBad(true); calc.run(key, null); return; }
    setBad(false);
    calc.run(key, { face_value: face, coupon_rate: coupon / 100, ytm: ytm / 100, years_to_maturity: years, freq: Number(freq) });
  }
  const b = calc.m.data;
  const ran = calc.m.variables;

  return (
    <div className="dv-calc" data-calc="bond">
      <section className="tx-sec dv-form">
        <h2 className="tx-sec-t">채권 값 넣기</h2>
        <p className="tx-sec-sub">고정금리 채권의 가격과 금리 민감도를 계산해요. 넣은 값이 모두 가정이에요.</p>
        <div className="dv-grid">
          <NumField id="dv-face" label="액면가" unit="원" value={raw.face} onChange={set("face")} missing={miss("face")} />
          <NumField id="dv-cpn" label="표면금리(연)" unit="%" value={raw.coupon} onChange={set("coupon")} missing={miss("coupon")} hint="채권이 약속한 이자율" />
          <NumField id="dv-ytm" label="만기수익률(연)" unit="%" value={raw.ytm} onChange={set("ytm")} missing={miss("ytm")} hint="지금 시장이 요구하는 수익률" />
          <NumField id="dv-yrs" label="남은 만기" unit="년" value={raw.years} onChange={set("years")} missing={miss("years")} step="1" hint="1 이상의 정수" />
        </div>
        <div className="dv-kind"><span className="dv-field-l">이자를 받는 횟수(1년에)</span>
          <Segmented label="이자를 받는 횟수" value={freq} onChange={setFreq} options={[{ value: "1", label: "1번" }, { value: "2", label: "2번" }, { value: "4", label: "4번" }]} />
        </div>
        {bad && <p className="dv-bad" role="alert">액면가는 0보다 크고, 남은 만기는 1년 이상의 정수여야 계산할 수 있어요.</p>}
        <button type="button" className="tx-btn tx-btn--main dv-go" onClick={run} disabled={calc.m.isPending}>
          {calc.m.isPending ? "계산하는 중이에요" : "채권 계산하기"}
        </button>
      </section>

      {calc.m.isError ? <CalcFail what="채권 값" error={calc.m.error} onRetry={run} /> : null}
      {b && ran ? (
        <section className="tx-sec dv-out" aria-live="polite">
          {calc.stale(key) && <StaleNote onRerun={run} />}
          <p className="dv-ans">이 채권의 가격은 <b>{won(b.Price, 2)}</b>이에요(액면 {won(ran.face_value)}).</p>
          <dl className="dv-figs" data-testid="bond-figs">
            <Fig k="Price" label="가격" value={won(b.Price, 2)} why={b.Price < ran.face_value ? "시장 수익률이 표면금리보다 높아 액면보다 싸게 거래돼요." : b.Price > ran.face_value ? "시장 수익률이 표면금리보다 낮아 액면보다 비싸게 거래돼요." : "시장 수익률과 표면금리가 같아 액면과 같아요."} />
            <Fig k="Macaulay_Duration" label="맥컬리 듀레이션" value={`${b.Macaulay_Duration.toFixed(2)}년`} why="이자와 원금을 받는 시점을 금액으로 가중 평균한 값이에요." />
            <Fig k="Modified_Duration" label="수정 듀레이션" value={b.Modified_Duration.toFixed(2)} why={`수익률이 1%p 오르면 가격이 약 ${b.Modified_Duration.toFixed(2)}% 내려요.`} />
            <Fig k="Convexity" label="볼록성" value={b.Convexity.toFixed(2)} why="수익률이 크게 움직일 때 듀레이션만으로 잰 가격 변화를 바로잡는 정도예요." />
            <Fig k="DV01" label="DV01" value={won(b.DV01, 4)} why={`수익률이 0.01%p 오르면 가격이 약 ${won(b.DV01, 4)} 내려요.`} />
          </dl>
        </section>
      ) : null}
    </div>
  );
}
