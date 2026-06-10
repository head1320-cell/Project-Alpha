"use client";
// 대상 경로: frontend/src/components/backtest/panels/BuyConditionPanel.tsx
//
// 매수조건 화면(빨강). 포트 기본 설정 + 매수 조건 설정(조건식 에디터) + 매수 비중 설정.

import { type Dispatch, type SetStateAction } from "react";
import { Section, SubToggle, QuickStepper, Segmented, Field, GroupedSelect } from "../kit";
import ConditionFormulaEditor, { type Condition } from "../ConditionFormulaEditor";
import type { BacktestStrategy } from "../../../lib/backtest/strategy";
import { FILL_PRICE_GROUPS } from "../../../lib/backtest/fillPrice";

export default function BuyConditionPanel({ s, set }: {
  s: BacktestStrategy; set: Dispatch<SetStateAction<BacktestStrategy>>;
}) {
  const patchBuy = (p: Partial<BacktestStrategy["buy"]>) => set((x) => ({ ...x, buy: { ...x.buy, ...p } }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

      <Section title="포트 기본 설정" hint="투자금·기간·비용" tone="neutral" enabled onToggle={() => {}}>
        <Field label="투자 금액">
          <QuickStepper value={s.capital} onChange={(v) => set((x) => ({ ...x, capital: v }))} chips={[1000, 5000]} unit="만원" min={0} />
        </Field>
        <Field label="수수료율">
          <QuickStepper value={s.feePct} onChange={(v) => set((x) => ({ ...x, feePct: v }))} unit="%" min={0} />
        </Field>
        <Field label="슬리피지">
          <QuickStepper value={s.slippagePct} onChange={(v) => set((x) => ({ ...x, slippagePct: v }))} unit="%" min={0} />
        </Field>
      </Section>

      <Section title="매수 조건 설정" hint="팩터·함수 조건식" tone="buy"
        enabled={s.buy.enabled} onToggle={(v) => patchBuy({ enabled: v })}>
        <ConditionFormulaEditor tone="buy" conditions={s.buy.conditions} onChange={(c: Condition[]) => patchBuy({ conditions: c })} />
        <SubToggle tone="buy" label="펀더멘털 조건 평가" hint="현재 스냅샷 기준 · look-ahead 주의" on={s.buy.allowFundamentals} onChange={(v) => patchBuy({ allowFundamentals: v })} />
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>고급 체결 옵션</div>
          <SubToggle tone="buy" label="분할 매수" hint="장중·장전 분할 진입" on={s.buy.splitBuy} onChange={(v) => patchBuy({ splitBuy: v })} />
          <SubToggle tone="buy" label="돌파 매수" hint="상방/양방 돌파 시 진입" on={s.buy.breakthrough} onChange={(v) => patchBuy({ breakthrough: v })} />
          <SubToggle tone="buy" label="TWAP 매수" hint="시간 분산 평균 체결" on={s.buy.twapBuy} onChange={(v) => patchBuy({ twapBuy: v })} />
        </div>
      </Section>

      <Section title="매수 비중 설정" hint="종목당 비중·보유 수" tone="buy" enabled onToggle={() => {}}>
        <Field label="비중 방식">
          <Segmented tone="buy" value={s.buy.weightMode} onChange={(v) => patchBuy({ weightMode: v })}
            options={[{ id: "equal", label: "균등 비중" }, { id: "atr", label: "ATR 비중" }]} />
        </Field>
        <Field label="종목당 비중">
          <QuickStepper value={s.buy.weightPct} onChange={(v) => patchBuy({ weightPct: v })} chips={[1, 5, 10]} unit="%" min={0} max={100} />
        </Field>
        <Field label="대상 종목 수">
          <Segmented tone="buy" value={s.buy.limitType} onChange={(v) => patchBuy({ limitType: v })}
            options={[{ id: "MAX", label: "전체" }, { id: "LIMIT", label: "제한" }]} />
          {s.buy.limitType === "LIMIT" && (
            <QuickStepper value={s.buy.maxStocks} onChange={(v) => patchBuy({ maxStocks: v })} chips={[5, 10, 20]} unit="종목" min={1} />
          )}
        </Field>
        <Field label="체결가 유형">
          <GroupedSelect value={s.buy.fillType} onChange={(id) => patchBuy({ fillType: id })} groups={FILL_PRICE_GROUPS} />
        </Field>
        <Field label="재매수 방지">
          <QuickStepper value={s.buy.reBuyBlockDays} onChange={(v) => patchBuy({ reBuyBlockDays: v })} chips={[5, 10]} unit="일" min={0} />
        </Field>
      </Section>

    </div>
  );
}
