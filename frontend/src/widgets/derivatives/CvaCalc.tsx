"use client";
// 신용 위험(CVA) — `/calculate-cva`. 상대방이 부도날 위험을 값으로 친 것.
// ★노출 곡선(새 그림)은 서버 `exposure_profile.ee_values` 그대로★ — 다만 그 모양은 시장에서 잰 값이 아니라 상품 종류마다 정한 모양(양식화)이라
// 가정 칩으로 말한다(엔진 `_ee_profile` 주석 · 캔버스 `cva_calc` 의 "양식화" 표시와 같은 사실).
// 덜 쓰는 칸은 "더 넣기"에 접어 두지만, 접어도 요청 본문에는 늘 모든 칸을 보낸다(기본값 = 서버 기본값).
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { api, type CvaOut } from "@/shared/api/legacyApi";
import { Chips, Segmented } from "@/shared/ui/tx";
import { won as wonK } from "@/shared/lib/krFormat";
import { CalcFail, Fig, NumField, StaleNote, parse, useCalc, type Raw } from "./parts";

type Pos = "irs" | "fx_forward" | "option";
type Body = {
  notional: number; maturity_years: number; cds_spread_bps: number; recovery_rate: number; risk_free_rate: number; position_type: Pos;
  volatility: number; bank_cds_spread_bps: number; bank_recovery: number; spread_shock_bps: number;
};
const POS_KO: Record<Pos, string> = { irs: "금리 스왑", fx_forward: "통화 선도", option: "옵션" };

export function CvaCalc() {
  const [raw, setRaw] = useState<Raw>({ notional: "1000000000", T: "5", cds: "150", rec: "40", rf: "3", vol: "2", bank: "50", bankRec: "40", shock: "100" });
  const [pos, setPos] = useState<Pos>("irs");
  const [bad, setBad] = useState(false);
  const calc = useCalc<Body, CvaOut>((b) => api.cva(b));
  const set = (k: string) => (v: string) => setRaw((p) => ({ ...p, [k]: v }));
  const keys = Object.keys(raw);
  const v = Object.fromEntries(keys.map((k) => [k, parse(raw[k])])) as Record<string, number | null>;
  const miss = (k: string) => calc.tried && v[k] == null;
  const key = { ...raw, pos };

  function run() {
    if (keys.some((k) => v[k] == null)) { setBad(false); calc.run(key, null); return; }
    const x = v as Record<string, number>;
    if (!(x.notional > 0 && x.T > 0 && x.cds >= 0 && x.rec >= 0 && x.rec < 100 && x.bankRec >= 0 && x.bankRec < 100)) { setBad(true); calc.run(key, null); return; }
    setBad(false);
    calc.run(key, {
      notional: x.notional, maturity_years: x.T, cds_spread_bps: x.cds, recovery_rate: x.rec / 100, risk_free_rate: x.rf / 100, position_type: pos,
      volatility: x.vol / 100, bank_cds_spread_bps: x.bank, bank_recovery: x.bankRec / 100, spread_shock_bps: x.shock,
    });
  }
  const c = calc.m.data;
  const ran = calc.m.variables;

  return (
    <div className="dv-calc" data-calc="cva">
      <section className="tx-sec dv-form">
        <h2 className="tx-sec-t">신용 위험 값 넣기</h2>
        <p className="tx-sec-sub">거래 상대방이 부도날 위험을 돈으로 치면 얼마인지(신용가치조정, CVA) 계산해요. 넣은 값이 모두 가정이에요.</p>
        <div className="dv-kind"><span className="dv-field-l">상품 종류</span>
          <Segmented label="상품 종류" value={pos} onChange={setPos} options={(Object.keys(POS_KO) as Pos[]).map((p) => ({ value: p, label: POS_KO[p] }))} />
        </div>
        <div className="dv-grid">
          <NumField id="dv-ntl" label="명목 금액" unit="원" value={raw.notional} onChange={set("notional")} missing={miss("notional")} hint={v.notional != null ? `${wonK(v.notional)}이에요` : undefined} />
          <NumField id="dv-cT" label="만기" unit="년" value={raw.T} onChange={set("T")} missing={miss("T")} />
          <NumField id="dv-cds" label="상대방 CDS 스프레드" unit="bp" value={raw.cds} onChange={set("cds")} missing={miss("cds")} hint="부도 보험료(1bp = 0.01%p)" />
          <NumField id="dv-rec" label="상대방 회수율" unit="%" value={raw.rec} onChange={set("rec")} missing={miss("rec")} hint="부도가 나도 돌려받는 비율" />
        </div>
        <details className="dv-more">
          <summary>더 넣기(금리 · 변동성 · 우리 쪽 신용 · 충격)</summary>
          <div className="dv-grid">
            <NumField id="dv-rf" label="무위험 금리(연)" unit="%" value={raw.rf} onChange={set("rf")} missing={miss("rf")} />
            <NumField id="dv-vol" label="노출 변동성(연)" unit="%" value={raw.vol} onChange={set("vol")} missing={miss("vol")} />
            <NumField id="dv-bank" label="우리 CDS 스프레드" unit="bp" value={raw.bank} onChange={set("bank")} missing={miss("bank")} />
            <NumField id="dv-bankRec" label="우리 회수율" unit="%" value={raw.bankRec} onChange={set("bankRec")} missing={miss("bankRec")} />
            <NumField id="dv-shock" label="스트레스 스프레드 충격" unit="bp" value={raw.shock} onChange={set("shock")} missing={miss("shock")} />
          </div>
        </details>
        {bad && <p className="dv-bad" role="alert">명목 금액·만기는 0보다 크고, 회수율은 0% 이상 100% 미만이어야 계산할 수 있어요.</p>}
        <button type="button" className="tx-btn tx-btn--main dv-go" onClick={run} disabled={calc.m.isPending}>
          {calc.m.isPending ? "계산하는 중이에요" : "신용 위험 계산하기"}
        </button>
      </section>

      {calc.m.isError ? <CalcFail what="신용 위험" error={calc.m.error} onRetry={run} /> : null}
      {c && ran ? (
        <section className="tx-sec dv-out" aria-live="polite">
          {calc.stale(key) && <StaleNote onRerun={run} />}
          <p className="dv-ans">상대방이 부도날 위험을 값으로 치면 <b>{wonK(c.unilateral_cva.cva_amount)}</b>이에요(명목의 {c.unilateral_cva.cva_pct_of_notional}%).</p>
          <Chips items={[
            { label: "노출 곡선은 시장에서 잰 값이 아니라 상품 종류마다 정한 모양이에요", tone: "assumed" },
            { label: "부도 확률은 넣은 CDS 스프레드에서 나왔어요", tone: "assumed" },
          ]} />
          <dl className="dv-figs" data-testid="cva-figs">
            <Fig k="cva" label="일방 CVA" value={wonK(c.unilateral_cva.cva_amount)} why="상대방 부도만 셀 때 거래 가치에서 빼야 할 금액이에요." />
            <Fig k="dva" label="DVA" value={wonK(c.bilateral_cva.dva_amount)} why="우리가 부도날 가능성 때문에 생기는 반대쪽 조정이에요." />
            <Fig k="bcva" label="양방 CVA(DVA − CVA)" value={wonK(c.bilateral_cva.bcva_amount)} why={<>서버가 DVA − CVA 로 계산해요. 음수면 거래 가치에서 그만큼 빼요. <span data-server>{c.bilateral_cva.interpretation}</span></>} />
            <Fig k="stressed" label="스트레스 CVA" value={wonK(c.stressed_cva.stressed_cva)} why={`스프레드가 ${ran.spread_shock_bps}bp 넓어지고 노출이 ${c.stressed_cva.shocks_applied.exposure_shock_pct}% 커지면 ${c.stressed_cva.stress_loss_pct}% 늘어요.`} />
            <Fig k="pd5" label={`${ran.maturity_years >= 5 ? "5" : "1"}년 안에 부도날 확률`} value={`${((ran.maturity_years >= 5 ? c.pd_from_cds["5y_pd"] : c.pd_from_cds["1y_pd"]) * 100).toFixed(2)}%`} why="CDS 스프레드와 회수율로 거꾸로 푼 값이에요." />
          </dl>
          <ExposureCurve ee={c.exposure_profile.ee_values} T={ran.maturity_years} epe={c.exposure_profile.epe} peak={c.exposure_profile.peak_ee} pos={ran.position_type} />
        </section>
      ) : null}
    </div>
  );
}

function ExposureCurve({ ee, T, epe, peak, pos }: { ee: number[]; T: number; epe: number; peak: number; pos: Pos }) {
  const pts = ee.map((y, i) => ({ t: Number(((T * (i + 1)) / ee.length).toFixed(3)), y }));
  return (
    <div className="dv-chart" data-testid="cva-curve" data-points={ee.length}>
      <h3 className="dv-h3">시간에 따라 얼마나 물려 있나요(기대 노출)</h3>
      <p className="dv-note">상대방이 그 시점에 부도나면 잃을 수 있는 금액의 기대값이에요. {POS_KO[pos]} 모양으로 {ee.length}개 시점을 계산했어요. 가장 클 때 {wonK(peak)}, 평균 {wonK(epe)}이에요.</p>
      <div className="dv-chart-box" role="img" aria-label={`기대 노출 곡선 ${ee.length}개 점. 가장 클 때 ${wonK(peak)}, 평균 ${wonK(epe)}`}>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={pts} margin={{ top: 12, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke="var(--tx-line)" vertical={false} />
            <XAxis dataKey="t" type="number" domain={[0, T]} tick={{ fill: "var(--tx-sub)", fontSize: 12 }} tickFormatter={(x: number) => `${x}년`} />
            <YAxis tick={{ fill: "var(--tx-sub)", fontSize: 12 }} width={64} tickFormatter={(x: number) => wonK(x).replace("원", "")} />
            <ReferenceLine y={epe} stroke="var(--tx-mute)" strokeDasharray="4 4" />
            <Line dataKey="y" type="monotone" stroke="var(--tx-blue)" strokeWidth={2.5} dot={{ r: 2.5, fill: "var(--tx-blue)", strokeWidth: 0 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="dv-keys"><span><i className="dv-key-line" aria-hidden />기대 노출</span><span><i className="dv-key-s" aria-hidden />평균(EPE) {wonK(epe)}</span></p>
    </div>
  );
}
