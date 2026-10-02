"use client";
// ② 언제 팔까 (매도 — 파랑 톤). 목표가/손절가·트레일링 + 보유 기간 + 조건 매도(편집기) + 종목 청산 + 매도 시간.
// BU3: 인라인 style 을 걷고 `bte-*`·kit 클래스로 그린다. 늘 켜진 절의 눌러도 아무 일 없던 스위치를 걷었다.
// ★상태·갱신은 그대로★ — 실행 본문이 같은지는 `e2e/backtest-requests.spec.ts` 골든이 건다.

import { type Dispatch, type SetStateAction } from "react";
import { Section, SubToggle, QuickStepper, Segmented, Field, GroupedSelect } from "@/shared/ui/kit";
import ConditionFormulaEditor, { type Condition } from "../ConditionFormulaEditor";
import OffsetInput from "./OffsetInput";
import LadderEditor from "./LadderEditor";
import type { BacktestStrategy } from "@/entities/backtest/strategy";
import { FILL_PRICE_GROUPS, FILL_PRICE_GROUPS_NO_EXPR } from "@/entities/backtest/fillPrice";

/** 분봉이 있어야 뜻이 있는 설정 — 일봉 백테스트에는 반영되지 않는다는 사실을 보이게 둔다(고칠 수 없게 흐리고 이유를 적는다). */
function IntradayOnly({ children }: { children: React.ReactNode }) {
  return (
    <div className="bte-col">
      <div className="bte-off" aria-disabled>{children}</div>
      <p className="bte-note">④ 돈·기간·비용에서 ‘분봉 정밀 체결’을 켜고 분봉을 적재하면 쓸 수 있어요.</p>
    </div>
  );
}

export default function SellConditionPanel({ s, set }: {
  s: BacktestStrategy; set: Dispatch<SetStateAction<BacktestStrategy>>;
}) {
  const v = s.sell;
  const patch = (p: Partial<BacktestStrategy["sell"]>) => set((x) => ({ ...x, sell: { ...x.sell, ...p } }));

  return (
    <div className="bte-col">

      <Section act="sell-exits" title="목표가와 손절가" hint="이만큼 오르면·내리면 팔아요" tone="sell"
        enabled={v.takeProfit.on || v.stopLoss.on || v.trailing.on}
        onToggle={(on) => patch({ takeProfit: { ...v.takeProfit, on }, stopLoss: { ...v.stopLoss, on }, trailing: { ...v.trailing, on: on && v.trailing.on } })}>
        <Field label="주문 방법">
          <IntradayOnly>
            <Segmented tone="sell" value={v.orderType} onChange={(t) => patch({ orderType: t })}
              options={[{ id: "FIX", label: "지정가" }, { id: "MARKET", label: "시장가" }]} />
          </IntradayOnly>
        </Field>
        <Field label="체결가 유형">
          <GroupedSelect value={v.fillType} onChange={(id) => patch({ fillType: id })} groups={FILL_PRICE_GROUPS} />
        </Field>
        {v.fillType === "expr" && (
          <Field label="기준가 식">
            <input value={v.fillExpr} spellCheck={false} className="bte-input bte-input--mono bte-input--wide" aria-label="기준가 식"
              onChange={(e) => patch({ fillExpr: e.target.value })}
              placeholder="예: 과거값({종가},{1일})*1.02" />
            <p className="bte-note">마지막 봉의 값이 기준가예요. 과거값(…)처럼 전날 기준을 권해요.</p>
          </Field>
        )}
        <Field label="파는 가격">
          <OffsetInput value={v.fillOffsetPct} onChange={(fillOffsetPct) => patch({ fillOffsetPct })} />
        </Field>
        <SubToggle tone="sell" label="목표가 (익절)" on={v.takeProfit.on} onChange={(on) => patch({ takeProfit: { ...v.takeProfit, on } })}>
          <QuickStepper value={v.takeProfit.pct} onChange={(pct) => patch({ takeProfit: { ...v.takeProfit, pct } })} chips={[5, 10, 20]} unit="%" min={0} />
          <span className="bte-sm">오르면 팔아요</span>
        </SubToggle>
        <SubToggle tone="sell" act="stop-loss" label="손절가" on={v.stopLoss.on} onChange={(on) => patch({ stopLoss: { ...v.stopLoss, on } })}>
          <QuickStepper value={v.stopLoss.pct} onChange={(pct) => patch({ stopLoss: { ...v.stopLoss, pct } })} chips={[5, 10]} unit="%" min={0} act="stop-loss-pct" />
          <span className="bte-sm">내리면 팔아요</span>
        </SubToggle>
        <SubToggle tone="sell" label="고점에서 밀리면 팔기" hint="트레일링 스탑" on={v.trailing.on} onChange={(on) => patch({ trailing: { ...v.trailing, on } })}>
          <span className="bte-sm">고점보다</span>
          <QuickStepper value={v.trailing.pct} onChange={(pct) => patch({ trailing: { ...v.trailing, pct } })} chips={[1, 3, 5]} unit="%" min={0} />
          <span className="bte-sm">내리면 팔아요</span>
        </SubToggle>
        <div className="bte-col">
          <p className="bte-sub-h">고급</p>
          <SubToggle tone="sell" label="나눠 팔기 (래더)" hint="가격이 움직일 때마다 비중을 나눠 팔아요 — 신호 매도에 적용"
            on={v.splitTakeProfit}
            onChange={(on) => patch({ splitTakeProfit: on, ladder: on && v.ladder.length === 0 ? [{ movePct: 0, weightPct: 50 }, { movePct: 2, weightPct: 50 }] : v.ladder })} />
          {v.splitTakeProfit && (
            <LadderEditor side="sell" steps={v.ladder} onChange={(ladder) => patch({ ladder })} />
          )}
          <p className="bte-note">TWAP·VWAP 체결은 위 ‘체결가 유형’에서 골라요.</p>
        </div>
      </Section>

      <Section title="얼마나 들고 있을까" hint={v.dayTrade ? "당일 매매" : "최소·최대 보유일"} tone="sell"
        enabled={v.holdPeriod.on || v.dayTrade} onToggle={(on) => patch({ holdPeriod: { ...v.holdPeriod, on }, dayTrade: on ? v.dayTrade : false })}>
        <Field label="보유 방식">
          <Segmented tone="sell" value={v.dayTrade ? "day" : "period"}
            onChange={(m) => patch({ dayTrade: m === "day" })}
            options={[{ id: "day", label: "당일 매매" }, { id: "period", label: "기간 정하기" }]} />
          {v.dayTrade && (
            <p className="bte-note">그날 산 것을 같은 날 종가에 모두 팔아요. 사는 체결가를 시가로 두면 시가에 사서 종가에 팔아요.</p>
          )}
        </Field>
        {!v.dayTrade && (<>
        <Field label="최소 보유일">
          <QuickStepper value={v.holdPeriod.min} onChange={(min) => patch({ holdPeriod: { ...v.holdPeriod, min } })} chips={[1, 5, 10]} unit="일" min={0} />
        </Field>
        <SubToggle tone="sell" label="최대 보유일에 팔기" hint="이 날이 되면 팔아요" on={v.expiryDateSell} onChange={(on) => patch({ expiryDateSell: on, holdPeriod: { ...v.holdPeriod, max: on ? (v.holdPeriod.max ?? 20) : undefined } })}>
          {v.expiryDateSell && (
            <>
              <span className="bte-sm">최대</span>
              <QuickStepper value={v.holdPeriod.max ?? 20} onChange={(max) => patch({ holdPeriod: { ...v.holdPeriod, max } })} chips={[10, 20, 60]} unit="일" min={1} />
            </>
          )}
        </SubToggle>
        {v.expiryDateSell && (
          <Field label="만기에 파는 방법">
            <Segmented tone="sell" value={v.expirySellMethod}
              onChange={(m) => patch({ expirySellMethod: m })}
              options={[{ id: "all", label: "한 번에" }, { id: "ladder", label: "나눠서(래더 공유)" }]} />
            {v.expirySellMethod === "ladder" && (
              <p className="bte-note">위 ‘나눠 팔기’ 래더를 써요. 남은 물량은 종가에 모두 팔아요(만기는 반드시 끝나요).</p>
            )}
          </Field>
        )}
        {v.expiryDateSell && (
          <Field label="만기에 파는 가격">
            <GroupedSelect value={v.expiryFillType} onChange={(id) => patch({ expiryFillType: id })} groups={FILL_PRICE_GROUPS_NO_EXPR} />
            <OffsetInput value={v.expiryFillOffsetPct} onChange={(expiryFillOffsetPct) => patch({ expiryFillOffsetPct })} />
            <p className="bte-note">지정가에 닿지 않으면 종가에 팔아요 — 만기 정리는 반드시 끝나요.</p>
          </Field>
        )}
        </>)}
      </Section>

      <Section title="조건으로 팔기" hint="팩터·논리식이 맞으면 팔아요" tone="sell" enabled>
        <ConditionFormulaEditor tone="sell" conditions={v.conditions} onChange={(c: Condition[]) => patch({ conditions: c })}
          logicExpr={v.logicExpr} onLogicChange={(logicExpr) => patch({ logicExpr })} logicDefaultLabel="하나라도 (OR)" sideKey="sell" />
      </Section>

      <Section title="장 마감에 정리하기" hint="장마감·시간 지정 청산" tone="sell"
        enabled={v.liquidate.on} onToggle={(on) => patch({ liquidate: { ...v.liquidate, on } })}>
        <Field label="정리 시점">
          <IntradayOnly>
            <Segmented tone="sell" value={v.liquidate.mode} onChange={(mode) => patch({ liquidate: { ...v.liquidate, mode } })}
              options={[{ id: "close", label: "장마감 동시호가" }, { id: "time", label: "시간 지정" }]} />
          </IntradayOnly>
        </Field>
      </Section>

      <Section title="파는 시간" hint={`${v.timeStart} ~ ${v.timeEnd}`} tone="sell" enabled>
        <Field label="시간대">
          {s.intradayFill ? (
            <>
              <input value={v.timeStart} className="bte-input bte-input--time" aria-label="매도 시작 시각" onChange={(e) => patch({ timeStart: e.target.value })} />
              <span className="bte-sm">~</span>
              <input value={v.timeEnd} className="bte-input bte-input--time" aria-label="매도 끝 시각" onChange={(e) => patch({ timeEnd: e.target.value })} />
              <p className="bte-note">분봉 정밀 체결이 켜져 있어요 — 이 시간 안의 분봉으로만 신호 매도를 체결해요.</p>
            </>
          ) : (
            <IntradayOnly>
              <div className="bte-row">
                <input value={v.timeStart} className="bte-input bte-input--time" aria-label="매도 시작 시각" onChange={(e) => patch({ timeStart: e.target.value })} />
                <span className="bte-sm">~</span>
                <input value={v.timeEnd} className="bte-input bte-input--time" aria-label="매도 끝 시각" onChange={(e) => patch({ timeEnd: e.target.value })} />
              </div>
            </IntradayOnly>
          )}
        </Field>
      </Section>

    </div>
  );
}
