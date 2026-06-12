"use client";
// 대상 경로: frontend/src/components/backtest/panels/SellConditionPanel.tsx
//
// 매도조건 화면(파랑). 목표가/손절가·트레일링 + 보유 기간 + 조건 매도(에디터) + 종목 청산 + 매도 시간.

import { type Dispatch, type SetStateAction } from "react";
import { Section, SubToggle, QuickStepper, Segmented, Field, GroupedSelect } from "../kit";
import ConditionFormulaEditor, { type Condition } from "../ConditionFormulaEditor";
import type { BacktestStrategy } from "../../../lib/backtest/strategy";
import { FILL_PRICE_GROUPS } from "../../../lib/backtest/fillPrice";

const timeBox: React.CSSProperties = {
  fontFamily: "var(--bs-font-mono)", fontSize: 13, color: "var(--text-primary)",
  border: "1px solid var(--border-strong)", borderRadius: "var(--bs-border-radius)",
  padding: "6px 11px", background: "var(--bg-card)", width: 84, textAlign: "center",
};

/** 분봉/틱 데이터가 있어야 의미 있는 설정 — 일봉 백테스트엔 반영되지 않음을 정직하게 표시 */
function IntradayOnly({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <div style={{ opacity: 0.45, pointerEvents: "none" }} aria-disabled>{children}</div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 5 }}>
        ⏳ 분봉 데이터 연동 시 활성 — 현재 일봉 백테스트에는 반영되지 않습니다
      </div>
    </div>
  );
}

export default function SellConditionPanel({ s, set }: {
  s: BacktestStrategy; set: Dispatch<SetStateAction<BacktestStrategy>>;
}) {
  const v = s.sell;
  const patch = (p: Partial<BacktestStrategy["sell"]>) => set((x) => ({ ...x, sell: { ...x.sell, ...p } }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

      <Section title="목표가 / 손절가" hint="익절·손절·트레일링" tone="sell"
        enabled={v.takeProfit.on || v.stopLoss.on || v.trailing.on}
        onToggle={(on) => patch({ takeProfit: { ...v.takeProfit, on }, stopLoss: { ...v.stopLoss, on }, trailing: { ...v.trailing, on: on && v.trailing.on } })}>
        <Field label="매도 주문 방법">
          <IntradayOnly>
            <Segmented tone="sell" value={v.orderType} onChange={(t) => patch({ orderType: t })}
              options={[{ id: "FIX", label: "지정가" }, { id: "MARKET", label: "시장가" }]} />
          </IntradayOnly>
        </Field>
        <Field label="체결가 유형">
          <GroupedSelect value={v.fillType} onChange={(id) => patch({ fillType: id })} groups={FILL_PRICE_GROUPS} />
        </Field>
        <SubToggle tone="sell" label="목표가 (익절)" on={v.takeProfit.on} onChange={(on) => patch({ takeProfit: { ...v.takeProfit, on } })}>
          <QuickStepper value={v.takeProfit.pct} onChange={(pct) => patch({ takeProfit: { ...v.takeProfit, pct } })} chips={[5, 10, 20]} unit="%" min={0} />
        </SubToggle>
        <SubToggle tone="sell" label="손절가" on={v.stopLoss.on} onChange={(on) => patch({ stopLoss: { ...v.stopLoss, on } })}>
          <QuickStepper value={v.stopLoss.pct} onChange={(pct) => patch({ stopLoss: { ...v.stopLoss, pct } })} chips={[5, 10]} unit="%" min={0} />
        </SubToggle>
        <SubToggle tone="sell" label="드래깅 청산" hint="트레일링 스탑" on={v.trailing.on} onChange={(on) => patch({ trailing: { ...v.trailing, on } })}>
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>고점 대비</span>
          <QuickStepper value={v.trailing.pct} onChange={(pct) => patch({ trailing: { ...v.trailing, pct } })} chips={[1, 3, 5]} unit="%" min={0} />
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>하락 시 청산</span>
        </SubToggle>
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>고급 옵션</div>
          <SubToggle tone="sell" label="분할 매도" hint="신호·손익절 매도에 1회 비중 적용 · 최대 횟수 도달 시 전량" on={v.splitTakeProfit} onChange={(on) => patch({ splitTakeProfit: on })}>
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>1회</span>
            <QuickStepper value={v.splitSellPct} onChange={(pct) => patch({ splitSellPct: pct })} chips={[25, 50]} unit="%" min={1} max={99} />
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>최대</span>
            <QuickStepper value={v.splitSellCount} onChange={(c) => patch({ splitSellCount: c })} chips={[2, 3]} unit="회" min={1} />
          </SubToggle>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>TWAP·VWAP 체결은 위 "체결가 유형"에서 선택</div>
        </div>
      </Section>

      <Section title="보유 기간" hint="최소·최대 보유일" tone="sell"
        enabled={v.holdPeriod.on} onToggle={(on) => patch({ holdPeriod: { ...v.holdPeriod, on } })}>
        <Field label="최소 보유일">
          <QuickStepper value={v.holdPeriod.min} onChange={(min) => patch({ holdPeriod: { ...v.holdPeriod, min } })} chips={[1, 5, 10]} unit="일" min={0} />
        </Field>
        <SubToggle tone="sell" label="만기 보유 매도" hint="최대 보유일 도달 시 청산" on={v.expiryDateSell} onChange={(on) => patch({ expiryDateSell: on, holdPeriod: { ...v.holdPeriod, max: on ? (v.holdPeriod.max ?? 20) : undefined } })}>
          {v.expiryDateSell && (
            <>
              <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>최대</span>
              <QuickStepper value={v.holdPeriod.max ?? 20} onChange={(max) => patch({ holdPeriod: { ...v.holdPeriod, max } })} chips={[10, 20, 60]} unit="일" min={1} />
            </>
          )}
        </SubToggle>
      </Section>

      <Section title="조건 매도" hint="팩터·논리식 기반 청산" tone="sell"
        enabled={v.conditions.length > 0 || true} onToggle={() => {}}>
        <ConditionFormulaEditor tone="sell" conditions={v.conditions} onChange={(c: Condition[]) => patch({ conditions: c })}
          logicExpr={v.logicExpr} onLogicChange={(logicExpr) => patch({ logicExpr })} logicDefaultLabel="하나라도 (OR)" />
      </Section>

      <Section title="종목 청산" hint="장마감·시간 청산" tone="sell"
        enabled={v.liquidate.on} onToggle={(on) => patch({ liquidate: { ...v.liquidate, on } })}>
        <Field label="청산 시점">
          <IntradayOnly>
            <Segmented tone="sell" value={v.liquidate.mode} onChange={(mode) => patch({ liquidate: { ...v.liquidate, mode } })}
              options={[{ id: "close", label: "장마감 동시호가" }, { id: "time", label: "시간 지정" }]} />
          </IntradayOnly>
        </Field>
      </Section>

      <Section title="매도 시간" hint={`${v.timeStart} ~ ${v.timeEnd}`} tone="sell" enabled onToggle={() => {}}>
        <Field label="시간대">
          <IntradayOnly>
            <input value={v.timeStart} onChange={(e) => patch({ timeStart: e.target.value })} style={timeBox} />
            <span style={{ color: "var(--text-secondary)", margin: "0 6px" }}>~</span>
            <input value={v.timeEnd} onChange={(e) => patch({ timeEnd: e.target.value })} style={timeBox} />
          </IntradayOnly>
        </Field>
      </Section>

    </div>
  );
}
