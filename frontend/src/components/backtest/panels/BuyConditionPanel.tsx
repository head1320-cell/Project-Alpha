"use client";
// 대상 경로: frontend/src/components/backtest/panels/BuyConditionPanel.tsx
//
// 매수조건 화면(빨강). 포트 기본 설정 + 매수 조건 설정(조건식 에디터) + 매수 비중 설정.

import { type Dispatch, type SetStateAction } from "react";
import { Section, SubToggle, QuickStepper, Segmented, Field, GroupedSelect } from "../kit";
import ConditionFormulaEditor, { type Condition } from "../ConditionFormulaEditor";
import type { BacktestStrategy, SortDir } from "../../../lib/backtest/strategy";
import { FILL_PRICE_GROUPS } from "../../../lib/backtest/fillPrice";
import { SORT_FIELDS } from "../../../lib/backtest/sortFields";

const selBox: React.CSSProperties = {
  fontSize: 13, color: "var(--text-primary)", border: "1px solid var(--border-strong)",
  borderRadius: "var(--bs-border-radius)", padding: "6px 9px", background: "var(--bg-card)", cursor: "pointer",
};

export default function BuyConditionPanel({ s, set }: {
  s: BacktestStrategy; set: Dispatch<SetStateAction<BacktestStrategy>>;
}) {
  const patchBuy = (p: Partial<BacktestStrategy["buy"]>) => set((x) => ({ ...x, buy: { ...x.buy, ...p } }));
  const patchMt = (p: Partial<BacktestStrategy["marketTiming"]>) =>
    set((x) => ({ ...x, marketTiming: { ...x.marketTiming, ...p } }));

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
        <Field label="리밸런싱 주기">
          <Segmented value={s.rebalancePeriod} onChange={(v) => set((x) => ({ ...x, rebalancePeriod: v }))}
            options={[{ id: "daily", label: "매일" }, { id: "weekly", label: "매주" }, { id: "monthly", label: "매월" }]} />
          {s.rebalancePeriod !== "daily" && (
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              신규 매수는 {s.rebalancePeriod === "weekly" ? "주" : "월"} 첫 거래일에만 · 청산룰은 매일 평가
            </span>
          )}
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
        <Field label="매수 우선순위">
          <select value={s.buy.primarySort.expr} style={selBox}
            onChange={(e) => patchBuy({ primarySort: { ...s.buy.primarySort, expr: e.target.value } })}>
            {SORT_FIELDS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
          <Segmented tone="buy" value={s.buy.primarySort.dir}
            onChange={(dir: SortDir) => patchBuy({ primarySort: { ...s.buy.primarySort, dir } })}
            options={[{ id: "DESC", label: "높은순" }, { id: "ASC", label: "낮은순" }]} />
        </Field>
        <Field label="2차 정렬">
          <select value={s.buy.secondarySort?.expr ?? ""} style={selBox}
            onChange={(e) => patchBuy({ secondarySort: e.target.value ? { expr: e.target.value, dir: s.buy.secondarySort?.dir ?? "DESC" } : undefined })}>
            <option value="">사용 안 함</option>
            {SORT_FIELDS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
          {s.buy.secondarySort && (
            <Segmented tone="buy" value={s.buy.secondarySort.dir}
              onChange={(dir: SortDir) => patchBuy({ secondarySort: { expr: s.buy.secondarySort!.expr, dir } })}
              options={[{ id: "DESC", label: "높은순" }, { id: "ASC", label: "낮은순" }]} />
          )}
        </Field>
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

      <Section title="마켓타이밍" hint="지수 조건 포트폴리오 게이트" tone="neutral"
        enabled={s.marketTiming.on} onToggle={(on) => patchMt({ on })}>
        <Field label="기준 지수">
          <Segmented value={s.marketTiming.index} onChange={(index) => patchMt({ index })}
            options={[{ id: "KOSPI", label: "코스피" }, { id: "KOSDAQ", label: "코스닥" }]} />
        </Field>
        <Field label="조건 위반 시">
          <Segmented value={s.marketTiming.mode} onChange={(mode) => patchMt({ mode })}
            options={[{ id: "block_buy", label: "신규 매수 차단" }, { id: "exit_all", label: "전량 청산" }]} />
        </Field>
        <ConditionFormulaEditor tone="neutral" conditions={s.marketTiming.conditions}
          onChange={(c: Condition[]) => patchMt({ conditions: c })} />
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          지수 봉에 평가 (전부 충족 시 ON) — 평균모멘텀스코어·변화율_기간 등 가격 함수 권장, 평가 불가 조건은 무시
        </div>
      </Section>

    </div>
  );
}
