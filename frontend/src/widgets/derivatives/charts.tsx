"use client";
// 파생상품 계산기의 차트 둘 — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다(recharts 를 첫 화면 JS 에서 뺌 · 2026-11-08 · `e2e/charts-lazy.spec.ts`).
// 본문은 OptionCalc·CvaCalc 에 있던 그대로다. 소비자는 그 파일들이 같은 이름으로 내보내는 것을 쓴다.
import { Area, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { won as wonK } from "@/shared/lib/krFormat";
import { f4, type Kind } from "./OptionCalc";
import { POS_KO, type Pos } from "./CvaCalc";

/** 만기 손익 = 만기 내재가치 − 지금 이론가(옵션 한 개를 사서 만기까지 들고 갈 때). 손익분기 = 행사가 ± 이론가. */
export function Payoff({ kind, K, S, price }: { kind: Kind; K: number; S: number; price: number }) {
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

export function ExposureCurve({ ee, T, epe, peak, pos }: { ee: number[]; T: number; epe: number; peak: number; pos: Pos }) {
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
