"use client";
// 옵션(블랙-숄즈, 유럽형) — `/analyze-option`. 칸 순서 S·K·σ·r·T 는 계약(`portfolio-graph.spec` 이 `input.input` n번째로 넣는다).
// σ·r 은 %로 넣고 서버에는 소수로 보낸다(20 → 0.2) — 요청 본문 값은 옛 화면과 같다.
// ★만기 손익 그림★은 서버가 준 이론가 하나만 쓰는 산수(만기 손익 = 내재가치 − 이론가)다. 오늘 가치 곡선은 그리지 않는다(서버가 주지 않는다).
import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { api } from "@/shared/api/legacyApi";
import { Segmented } from "@/shared/ui/tx";
import { CalcFail, Fig, NumField, StaleNote, parse, sgn, useCalc, type Raw } from "./parts";

type Kind = "call" | "put";
type Greeks = { Type?: string; Price: number; Delta: number | null; Gamma: number | null; Theta: number | null; Vega: number | null; Rho: number | null; at_expiry?: boolean };
type Body = { S: number; K: number; sigma: number; r: number; T: number; option_type: Kind };

const KO: Record<Kind, string> = { call: "콜(살 권리)", put: "풋(팔 권리)" };
const f4 = (v: number) => `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(4)}`;

export function OptionCalc() {
  const [raw, setRaw] = useState<Raw>({ S: "100", K: "100", sigma: "25", r: "3.5", T: "0.25" });
  const [kind, setKind] = useState<Kind>("call");
  const [bad, setBad] = useState(false);
  const calc = useCalc<Body, Greeks>((b) => api.optionPrice(b) as Promise<Greeks>);
  const set = (k: string) => (v: string) => setRaw((p) => ({ ...p, [k]: v }));
  const v = { S: parse(raw.S), K: parse(raw.K), sigma: parse(raw.sigma), r: parse(raw.r), T: parse(raw.T) };
  const miss = (k: keyof typeof v) => calc.tried && v[k] == null;
  const key = { ...raw, kind };

  function run() {
    if (Object.values(v).some((x) => x == null)) { setBad(false); calc.run(key, null); return; }
    const { S, K, sigma, r, T } = v as Record<keyof typeof v, number>;
    // 서버도 422 로 거절한다(BL3 M2) — 같은 규칙으로 먼저 막아 왕복을 아낀다. 만기 0 은 내재가치로 계산된다.
    if (!(S > 0 && K > 0 && sigma > 0 && T >= 0)) { setBad(true); calc.run(key, null); return; }
    setBad(false);
    calc.run(key, { S, K, sigma: sigma / 100, r: r / 100, T, option_type: kind });
  }
  const g = calc.m.data;
  const ran = calc.m.variables;

  return (
    <div className="dv-calc" data-calc="option">
      <section className="tx-sec dv-form">
        <h2 className="tx-sec-t">옵션 값 넣기</h2>
        <p className="tx-sec-sub">블랙-숄즈 식(유럽형, 만기에만 행사)으로 계산해요. 넣은 값이 모두 가정이에요.</p>
        <div className="dv-kind"><span className="dv-field-l">옵션 종류</span>
          <Segmented label="옵션 종류" value={kind} onChange={setKind} options={[{ value: "call", label: KO.call }, { value: "put", label: KO.put }]} />
        </div>
        <div className="dv-grid">
          <NumField id="dv-S" label="기초자산 가격" unit="원" value={raw.S} onChange={set("S")} missing={miss("S")} />
          <NumField id="dv-K" label="행사가" unit="원" value={raw.K} onChange={set("K")} missing={miss("K")} />
          <NumField id="dv-sig" label="변동성(연)" unit="%" value={raw.sigma} onChange={set("sigma")} missing={miss("sigma")} hint="1년 동안 가격이 흔들리는 정도" />
          <NumField id="dv-r" label="무위험 금리(연)" unit="%" value={raw.r} onChange={set("r")} missing={miss("r")} />
          <NumField id="dv-T" label="남은 만기" unit="년" value={raw.T} onChange={set("T")} missing={miss("T")} hint="3개월이면 0.25" />
        </div>
        {bad && <p className="dv-bad" role="alert">가격·행사가·변동성은 0보다 커야 하고, 만기는 0 이상이어야 계산할 수 있어요.</p>}
        <button type="button" className="tx-btn tx-btn--main dv-go" onClick={run} disabled={calc.m.isPending}>
          {calc.m.isPending ? "계산하는 중이에요" : "가격 계산하기"}
        </button>
      </section>

      {calc.m.isError ? <CalcFail what="옵션 가격" error={calc.m.error} onRetry={run} /> : null}
      {g && ran ? (
        <section className="tx-sec dv-out" aria-live="polite">
          {calc.stale(key) && <StaleNote onRerun={run} />}
          <p className="dv-ans">이 {KO[ran.option_type]} 옵션의 이론가는 <b>{f4(g.Price)}원</b>이에요.</p>
          {g.at_expiry && (
            <p className="dv-note" data-testid="option-expiry">만기예요. 시간 가치는 없고 내재가치만 남아요. 등가격이면 델타는 정의되지 않아요.</p>
          )}
          <dl className="dv-figs" data-testid="option-greeks">
            <Fig k="Price" label="이론가" value={`${f4(g.Price)}원`} why="지금 넣은 값으로 계산한 옵션 한 개의 공정 가격이에요." />
            <Greek k="Delta" label="델타" v={g.Delta} why={(x) => `기초자산이 1원 오르면 옵션 가격이 약 ${sgn(x, 4)}원 움직여요.`} />
            <Greek k="Gamma" label="감마" v={g.Gamma} why={(x) => `기초자산이 1원 오르면 델타가 약 ${sgn(x, 4)}만큼 바뀌어요.`} />
            <Greek k="Theta" label="세타(하루)" v={g.Theta} why={(x) => `하루가 지나면 옵션 가격이 약 ${sgn(x, 4)}원 바뀌어요.`} />
            <Greek k="Vega" label="베가(변동성 1%p)" v={g.Vega} why={(x) => `변동성이 1%p 오르면 옵션 가격이 약 ${sgn(x, 4)}원 바뀌어요.`} />
            <Greek k="Rho" label="로(금리 1%p)" v={g.Rho} why={(x) => `금리가 1%p 오르면 옵션 가격이 약 ${sgn(x, 4)}원 바뀌어요.`} />
          </dl>
          <Payoff kind={ran.option_type} K={ran.K} S={ran.S} price={g.Price} />
        </section>
      ) : null}
    </div>
  );
}

function Greek({ k, label, v, why }: { k: string; label: string; v: number | null; why: (x: number) => string }) {
  return v == null
    ? <Fig k={k} label={label} value="정의되지 않아요" why="만기·등가격처럼 이 값이 수학적으로 정해지지 않는 자리예요." />
    : <Fig k={k} label={label} value={f4(v)} why={why(v)} />;
}

/** 만기 손익 = 만기 내재가치 − 지금 이론가(옵션 한 개를 사서 만기까지 들고 갈 때). 손익분기 = 행사가 ± 이론가. */
function Payoff({ kind, K, S, price }: { kind: Kind; K: number; S: number; price: number }) {
  const be = kind === "call" ? K + price : K - price;
  const lo = Math.max(0, Math.min(S, K) * 0.6), hi = Math.max(S, K, be) * 1.4;
  const pts = Array.from({ length: 61 }, (_, i) => {
    const x = lo + ((hi - lo) * i) / 60;
    const pl = (kind === "call" ? Math.max(x - K, 0) : Math.max(K - x, 0)) - price;
    return { x: Number(x.toFixed(4)), pl: Number(pl.toFixed(4)) };
  });
  return (
    <div className="dv-chart" data-testid="payoff" data-breakeven={be.toFixed(4)}>
      <h3 className="dv-h3">만기에 얼마를 벌거나 잃나요</h3>
      <p className="dv-note">옵션 한 개를 지금 이론가에 사서 만기까지 들고 있을 때예요. 손익분기는 <b className="dv-be">{f4(be)}원</b>(행사가 {kind === "call" ? "+" : "−"} 이론가)이고, 가장 크게 잃는 금액은 이론가 {f4(price)}원이에요.</p>
      <div className="dv-chart-box" role="img" aria-label={`만기 손익 그림. 손익분기 ${f4(be)}원, 최대 손실 ${f4(price)}원`}>
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={pts} margin={{ top: 12, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke="var(--tx-line)" vertical={false} />
            <XAxis dataKey="x" type="number" domain={[lo, hi]} tick={{ fill: "var(--tx-sub)", fontSize: 12 }} tickFormatter={(x: number) => x.toFixed(0)} />
            <YAxis tick={{ fill: "var(--tx-sub)", fontSize: 12 }} width={48} tickFormatter={(x: number) => x.toFixed(0)} />
            <ReferenceLine y={0} stroke="var(--tx-mute)" />
            <ReferenceLine x={be} stroke="var(--tx-ink)" strokeDasharray="4 4" />
            <ReferenceLine x={S} stroke="var(--tx-mute)" strokeDasharray="2 4" />
            <Area dataKey="pl" type="linear" stroke="none" fill="var(--tx-blue)" fillOpacity={0.08} isAnimationActive={false} />
            <Line dataKey="pl" type="linear" stroke="var(--tx-blue)" strokeWidth={2.5} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="dv-keys"><span><i className="dv-key-be" aria-hidden />손익분기 {f4(be)}원</span><span><i className="dv-key-s" aria-hidden />지금 기초자산 {S}원</span></p>
    </div>
  );
}
