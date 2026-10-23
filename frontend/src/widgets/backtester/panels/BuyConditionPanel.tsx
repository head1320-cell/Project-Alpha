"use client";
// ① 무엇을 살까 (매수 — 빨강 톤). 매수 조건(조건식 편집기) + 고급 체결 + 매수 비중 + 현금 비중 + ETF 자산배분 + 마켓타이밍.
// BU3: 돈·기간·비용("포트 기본 설정")은 ④ `CapitalPanel` 로 옮겼다. 인라인 style 을 걷고 `bte-*`·kit 클래스로 그린다.
// ★상태·갱신은 그대로★ — 실행 본문이 같은지는 `e2e/backtest-requests.spec.ts` 골든이 건다.

import { type Dispatch, type SetStateAction } from "react";
import { Section, SubToggle, QuickStepper, Segmented, Field, GroupedSelect } from "@/shared/ui/kit";
import ConditionFormulaEditor, { type Condition } from "../ConditionFormulaEditor";
import OffsetInput from "./OffsetInput";
import LadderEditor from "./LadderEditor";
import AssetAllocPanel from "./AssetAllocPanel";
import type { BacktestStrategy, SortDir } from "@/entities/backtest/strategy";
import { FILL_PRICE_GROUPS, FILL_PRICE_GROUPS_NO_EXPR } from "@/entities/backtest/fillPrice";
import { SORT_FIELDS } from "@/entities/backtest/sortFields";

export default function BuyConditionPanel({ s, set }: {
  s: BacktestStrategy; set: Dispatch<SetStateAction<BacktestStrategy>>;
}) {
  const patchBuy = (p: Partial<BacktestStrategy["buy"]>) => set((x) => ({ ...x, buy: { ...x.buy, ...p } }));
  const patchMt = (p: Partial<BacktestStrategy["marketTiming"]>) =>
    set((x) => ({ ...x, marketTiming: { ...x.marketTiming, ...p } }));

  return (
    <div className="bte-col">

      <Section title="살 조건" hint="팩터·함수로 만든 조건식" tone="buy"
        enabled={s.buy.enabled} onToggle={(v) => patchBuy({ enabled: v })}>
        <ConditionFormulaEditor tone="buy" conditions={s.buy.conditions} onChange={(c: Condition[]) => patchBuy({ conditions: c })}
          logicExpr={s.buy.logicExpr} onLogicChange={(v) => patchBuy({ logicExpr: v })} logicDefaultLabel="모두 AND" sideKey="buy" />
        <SubToggle tone="buy" act="buy-fundamentals" label="재무 조건도 평가" hint="지금 스냅샷 기준이라 과거 시점에는 미래 정보가 섞일 수 있어요"
          on={s.buy.allowFundamentals} onChange={(v) => patchBuy({ allowFundamentals: v })} />
        <div className="bte-col">
          <p className="bte-sub-h">고급 체결</p>
          <SubToggle tone="buy" label="나눠 사기 (래더)" hint="가격이 움직일 때마다 비중을 나눠 체결해요"
            on={s.buy.splitBuy}
            onChange={(v) => patchBuy({ splitBuy: v, ladder: v && s.buy.ladder.length === 0 ? [{ movePct: 0, weightPct: 50 }, { movePct: -2, weightPct: 50 }] : s.buy.ladder })} />
          {s.buy.splitBuy && (
            <LadderEditor side="buy" steps={s.buy.ladder} onChange={(ladder) => patchBuy({ ladder })} />
          )}
          <SubToggle tone="buy" label="돌파할 때만 사기" hint="기준가를 넘었을 때만 들어가요" on={s.buy.breakthrough} onChange={(v) => patchBuy({ breakthrough: v })} />
          {s.buy.breakthrough && (
            <div className="bte-col">
              <div className="bte-row">
                <span className="bte-sm">방향</span>
                <Segmented tone="buy" value={s.buy.breakthroughDirection}
                  onChange={(d) => patchBuy({ breakthroughDirection: d })}
                  options={[{ id: "up", label: "위로" }, { id: "both", label: "양쪽" }]} />
                <span className="bte-sm">기준가</span>
                <GroupedSelect value={s.buy.breakthroughBaseType}
                  onChange={(id) => patchBuy({ breakthroughBaseType: id })} groups={FILL_PRICE_GROUPS_NO_EXPR} />
              </div>
              <OffsetInput value={s.buy.breakthroughOffsetPct}
                onChange={(breakthroughOffsetPct) => patchBuy({ breakthroughOffsetPct })} />
              <p className="bte-note bte-note--warn">당일 시초가처럼 크게 흔들리는 기준은 불공정 거래 소지가 있으니 조심하세요.</p>
            </div>
          )}
          <Field label="사는 때">
            <Segmented tone="buy" value={s.buy.buyTiming} onChange={(t) => patchBuy({ buyTiming: t })}
              options={[{ id: "pre_open", label: "장 시작 전" }, { id: "intraday", label: "장중 주문" }]} />
            <p className="bte-note">장중 주문은 지정가로 살 때 시가 갭으로 체결되는 경우를 빼요(보수적).</p>
          </Field>
          <p className="bte-note">TWAP·VWAP 체결은 아래 ‘체결가 유형’에서 골라요.</p>
        </div>
      </Section>

      <Section title="얼마씩 살까" hint="순서 · 종목당 비중 · 보유 수" tone="buy" enabled>
        <Field label="사는 순서">
          <select value={s.buy.primarySort.expr} className="kit-select" aria-label="사는 순서 기준"
            onChange={(e) => patchBuy({ primarySort: { ...s.buy.primarySort, expr: e.target.value } })}>
            {SORT_FIELDS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
          <Segmented tone="buy" value={s.buy.primarySort.dir}
            onChange={(dir: SortDir) => patchBuy({ primarySort: { ...s.buy.primarySort, dir } })}
            options={[{ id: "DESC", label: "높은순" }, { id: "ASC", label: "낮은순" }]} />
        </Field>
        <SubToggle tone="buy" label="순서를 식으로 (매일)" hint="위 순서 대신, 매일 식 값으로 사는 순서를 정해요"
          on={s.buy.sortExpr.trim() !== ""} onChange={(on) => patchBuy({ sortExpr: on ? "{종합점수}" : "" })}>
          <input value={s.buy.sortExpr} spellCheck={false} className="bte-input bte-input--mono bte-input--wide" aria-label="순서 식"
            onChange={(e) => patchBuy({ sortExpr: e.target.value })}
            placeholder="예: {모멘텀점수} 또는 변화율_기간({종가},{20일})" />
          <Segmented tone="buy" value={s.buy.sortExprDesc ? "desc" : "asc"}
            onChange={(d) => patchBuy({ sortExprDesc: d === "desc" })}
            options={[{ id: "desc", label: "높은순" }, { id: "asc", label: "낮은순" }]} />
        </SubToggle>
        <Field label="두 번째 순서">
          <select value={s.buy.secondarySort?.expr ?? ""} className="kit-select" aria-label="두 번째 순서 기준"
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
            options={[{ id: "equal", label: "똑같이" }, { id: "atr", label: "변동성(ATR)에 맞춰" }]} />
        </Field>
        <Field label="종목당 비중">
          <QuickStepper value={s.buy.weightPct} onChange={(v) => patchBuy({ weightPct: v })} chips={[1, 5, 10]} unit="%" min={0} max={100} />
        </Field>
        <Field label="최대 보유 수">
          <QuickStepper value={s.buy.maxStocks} onChange={(v) => patchBuy({ maxStocks: v })} chips={[5, 10, 20]} unit="종목" min={1} max={30} act="max-stocks" />
          <p className="bte-note">동시에 들고 있을 수 있는 종목 수예요. 후보를 몇 종목까지 볼지는 ③ ‘평가 종목 상한’에서 따로 정해요.</p>
        </Field>
        <Field label="체결가 유형">
          <GroupedSelect value={s.buy.fillType} onChange={(id) => patchBuy({ fillType: id })} groups={FILL_PRICE_GROUPS} />
        </Field>
        {s.buy.fillType === "expr" && (
          <Field label="기준가 식">
            <input value={s.buy.fillExpr} spellCheck={false} className="bte-input bte-input--mono bte-input--wide" aria-label="기준가 식"
              onChange={(e) => patchBuy({ fillExpr: e.target.value })}
              placeholder="예: (과거값({고가},{1일})+과거값({저가},{1일}))/2" />
            <p className="bte-note">마지막 봉의 값이 기준가예요. 당일 종가가 들어간 식은 미래 정보를 써요 — 과거값(…)을 권해요.</p>
          </Field>
        )}
        <Field label="사는 가격">
          <OffsetInput value={s.buy.fillOffsetPct} onChange={(fillOffsetPct) => patchBuy({ fillOffsetPct })} />
        </Field>
        <SubToggle tone="buy" label="종목당 최대 금액" hint="한 종목에 넣을 수 있는 한도"
          on={s.buy.maxBuyAmount > 0} onChange={(on) => patchBuy({ maxBuyAmount: on ? 1000 : 0 })}>
          <QuickStepper value={s.buy.maxBuyAmount} onChange={(v) => patchBuy({ maxBuyAmount: v })}
            chips={[1000, 3000, 5000]} unit="만원" min={100} />
        </SubToggle>
        <SubToggle tone="buy" label="하루 최대 새 종목 수" hint="하루에 새로 들어가는 종목 수 제한"
          on={s.buy.maxBuyPerDay > 0} onChange={(on) => patchBuy({ maxBuyPerDay: on ? 1 : 0 })}>
          <QuickStepper value={s.buy.maxBuyPerDay} onChange={(v) => patchBuy({ maxBuyPerDay: v })} chips={[1, 3, 5]} unit="종목" min={1} />
        </SubToggle>
        <Field label="다시 사기까지">
          <QuickStepper value={s.buy.reBuyBlockDays} onChange={(v) => patchBuy({ reBuyBlockDays: v })} chips={[5, 10]} unit="일" min={0} />
          <p className="bte-note">판 뒤 N일(달력 기준) 동안 같은 종목을 다시 사지 않아요. 0이면 쓰지 않아요.</p>
        </Field>
      </Section>

      {!s.assetAlloc.enabled && (
        <Section title="현금 남겨 두기" hint="평가자산 대비 현금을 늘 들고 있어요" tone="neutral"
          enabled={s.cashReservePct > 0} onToggle={(on) => set((x) => ({ ...x, cashReservePct: on ? 10 : 0 }))}>
          <Field label="현금 비중">
            <QuickStepper value={s.cashReservePct} onChange={(v) => set((x) => ({ ...x, cashReservePct: v }))}
              chips={[10, 20, 30]} unit="%" min={0} max={90} />
            <p className="bte-note">평가자산의 N%를 늘 현금으로 두고 살 돈에서 빼요. ETF 자산배분을 켜면 그쪽으로 합쳐져요.</p>
          </Field>
        </Section>
      )}

      <AssetAllocPanel s={s} set={set} />

      <Section title="시장이 나쁠 때 멈추기" hint="지수 조건으로 포트폴리오 전체를 막아요(마켓타이밍)" tone="neutral"
        enabled={s.marketTiming.on} onToggle={(on) => patchMt({ on })}>
        <Field label="기준 지수">
          <Segmented value={s.marketTiming.index} onChange={(index) => patchMt({ index })}
            options={[{ id: "KOSPI", label: "코스피" }, { id: "KOSDAQ", label: "코스닥" }]} />
        </Field>
        <Field label="조건이 깨지면">
          <Segmented value={s.marketTiming.mode} onChange={(mode) => patchMt({ mode })}
            options={[{ id: "block_buy", label: "새로 사지 않기" }, { id: "exit_all", label: "모두 팔기" }]} />
        </Field>
        <ConditionFormulaEditor tone="neutral" conditions={s.marketTiming.conditions}
          onChange={(c: Condition[]) => patchMt({ conditions: c })} />
        <p className="bte-note">
          지수 봉으로 평가해요(모두 맞으면 켬). 평균모멘텀스코어·변화율_기간 같은 가격 함수를 권해요. 평가할 수 없는 조건은 빼고 봐요.
        </p>
      </Section>

    </div>
  );
}
