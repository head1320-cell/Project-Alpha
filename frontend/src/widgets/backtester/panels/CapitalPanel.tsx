"use client";
// ④ 돈·기간·비용 (BU3) — 예전에는 "매수" 화면 맨 위 "포트 기본 설정" 안에 섞여 있었다. 같은 상태(`s`)·같은 갱신을 그대로 옮겼다 —
// 실행 본문이 바이트로 같은지는 `e2e/backtest-requests.spec.ts` 골든이 건다. 분봉 정밀 체결의 "매수 시간" 은 그 스위치 옆이라 함께 왔다.

import { type Dispatch, type SetStateAction } from "react";
import { Section, SubToggle, QuickStepper, Segmented, Field } from "@/shared/ui/kit";
import type { BacktestStrategy } from "@/entities/backtest/strategy";

const REBALANCE_PERIOD_UNIT: Record<Exclude<BacktestStrategy["rebalancePeriod"], "daily">, string> = {
  weekly: "주", monthly: "월", quarterly: "분기", semiannual: "반기", annual: "연",
};

export default function CapitalPanel({ s, set }: {
  s: BacktestStrategy; set: Dispatch<SetStateAction<BacktestStrategy>>;
}) {
  const patchBuy = (p: Partial<BacktestStrategy["buy"]>) => set((x) => ({ ...x, buy: { ...x.buy, ...p } }));

  return (
    <div className="bte-col">
      <Section title="돈과 기간" hint="얼마로 · 언제부터 언제까지" tone="neutral" enabled>
        <Field label="투자 금액">
          <QuickStepper value={s.capital} onChange={(v) => set((x) => ({ ...x, capital: v }))} chips={[1000, 5000]} unit="만원" min={0} act="capital" />
        </Field>
        <Field label="투자 기간">
          <input type="date" className="bte-input bte-input--date" aria-label="시작일" value={s.startDate} max={s.endDate}
            onChange={(e) => set((x) => ({ ...x, startDate: e.target.value }))} />
          <span className="bte-sm">~</span>
          <input type="date" className="bte-input bte-input--date" aria-label="종료일" value={s.endDate} min={s.startDate}
            onChange={(e) => set((x) => ({ ...x, endDate: e.target.value }))} />
          <span className="kit-chips">
            {([["1년", 1], ["3년", 3], ["5년", 5], ["전체 기간", 0]] as const).map(([label, yrs]) => (
              <button key={label} type="button" className="kit-chip" onClick={() => set((x) => {
                const end = x.endDate || new Date().toISOString().slice(0, 10);
                const start = yrs === 0 ? "2015-01-01"
                  : `${Number(end.slice(0, 4)) - yrs}${end.slice(4)}`;
                return { ...x, startDate: start, endDate: end };
              })}>{label}</button>
            ))}
          </span>
        </Field>
      </Section>

      <Section title="거래 비용" hint="수수료 · 슬리피지 · 추가 비용" tone="neutral" enabled>
        <Field label="수수료율">
          <QuickStepper value={s.feePct} onChange={(v) => set((x) => ({ ...x, feePct: v }))} unit="%" min={0} act="fee" />
        </Field>
        <Field label="슬리피지">
          <QuickStepper value={s.slippagePct} onChange={(v) => set((x) => ({ ...x, slippagePct: v }))} unit="%" min={0} />
        </Field>
        {/* ── 누락 비용 옵트인 셋 (AK) ★전부 기본 꺼짐★ — 켜면 백엔드가 `market_rules` 의 같은 요율을 쓴다.
            기본을 켜지 않는 이유는 켜는 순간 저장된 실행들의 뜻이 바뀌기 때문이다. */}
        <div className="bte-col">
          <p className="bte-sub-h">추가 비용 — 기본은 꺼져 있어요</p>
          <SubToggle tone="sell" act="sell-tax" label="증권거래세" hint="팔 때 한 번 0.18% · 수수료보다 커요"
            on={s.chargeSellTax} onChange={(v) => set((x) => ({ ...x, chargeSellTax: v }))} />
          <SubToggle tone="sell" label="호가 스프레드" hint="한 번 거래에 0.025% (스프레드의 절반)"
            on={s.chargeSpread} onChange={(v) => set((x) => ({ ...x, chargeSpread: v }))} />
          <SubToggle tone="sell" label="시장충격" hint="주문 금액 ÷ 거래대금에 비례 · 거래대금이 없으면 몰라요"
            on={s.chargeMarketImpact} onChange={(v) => set((x) => ({ ...x, chargeMarketImpact: v }))} />
          <p className="bte-note">
            {(s.chargeSellTax || s.chargeSpread || s.chargeMarketImpact)
              ? "켠 비용은 실행 준비실과 같은 요율을 써요. 결과의 비용 분해에 하나씩 실려요."
              : "끄면 수수료·슬리피지만 봐요. 0원이라는 뜻이 아니라 재지 않았다는 뜻이고, 결과가 그 사실을 적어요."}
          </p>
          {s.chargeMarketImpact && (
            <p className="bte-note bte-note--warn">
              거래대금이 없는 종목·기간은 시장충격을 0이 아니라 ‘몰라요’로 남겨요. 그만큼 비용이 낮게 잡혀요.
            </p>
          )}
        </div>
      </Section>

      <Section title="언제 다시 맞출까" hint="리밸런싱 · 신호 기준 · 체결 모델" tone="neutral" enabled>
        <Field label="리밸런싱 주기">
          <Segmented act="rebalance" value={s.rebalancePeriod} onChange={(v) => set((x) => ({ ...x, rebalancePeriod: v }))}
            options={[
              { id: "daily", label: "매일" }, { id: "weekly", label: "매주" },
              { id: "monthly", label: "매월" }, { id: "quarterly", label: "분기" },
              { id: "semiannual", label: "반기" }, { id: "annual", label: "연간" },
            ]} />
          {s.rebalancePeriod !== "daily" && (
            <p className="bte-note">
              순위에서 밀린 보유 종목은 {REBALANCE_PERIOD_UNIT[s.rebalancePeriod]} 첫 거래일에만 정리해요. 빈자리 채우기·손익절은 매일 봐요.
            </p>
          )}
        </Field>
        <Field label="신호 기준">
          <Segmented value={String(s.signalLag)} onChange={(v) => set((x) => ({ ...x, signalLag: v === "1" ? 1 : 0 }))}
            options={[{ id: "0", label: "당일 종가" }, { id: "1", label: "전일 종가 기준" }]} />
          {s.signalLag === 0 && (s.buy.fillType !== "close" || s.sell.fillType !== "close") ? (
            <p className="bte-note bte-note--warn">
              당일 종가로 만든 신호를 시가·전일가에 체결하면 미래 정보를 쓰게 돼요(look-ahead). 전일 종가 기준을 권해요.
            </p>
          ) : (
            <p className="bte-note">전일 종가로 종목을 고르고 다음 날 사고팔아요(체결은 그날 가격).</p>
          )}
        </Field>
        <Field label="분봉 정밀 체결">
          <Segmented value={s.intradayFill ? "on" : "off"}
            onChange={(v) => set((x) => ({ ...x, intradayFill: v === "on" }))}
            options={[{ id: "off", label: "일봉 모델" }, { id: "on", label: "분봉 정밀" }]} />
          <p className="bte-note">
            적재된 (종목, 날짜) 분봉으로 매매 시간 안에서 지정가·시장가·TWAP 을 정밀하게 체결해요. 분봉이 없는 날은 일봉으로 계산하고,
            결과에 그 비율을 적어요.
          </p>
        </Field>
        {s.intradayFill && (
          <Field label="매수 시간">
            <input className="bte-input bte-input--time" aria-label="매수 시작 시각" value={s.buy.timeStart}
              onChange={(e) => patchBuy({ timeStart: e.target.value })} placeholder="09:00" />
            <span className="bte-sm">~</span>
            <input className="bte-input bte-input--time" aria-label="매수 끝 시각" value={s.buy.timeEnd}
              onChange={(e) => patchBuy({ timeEnd: e.target.value })} placeholder="15:30" />
            <p className="bte-note">이 시간 안의 분봉으로만 사요.</p>
          </Field>
        )}
      </Section>
    </div>
  );
}
