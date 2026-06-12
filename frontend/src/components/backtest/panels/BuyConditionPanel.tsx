"use client";
// 대상 경로: frontend/src/components/backtest/panels/BuyConditionPanel.tsx
//
// 매수조건 화면(빨강). 포트 기본 설정 + 매수 조건 설정(조건식 에디터) + 매수 비중 설정.

import { type Dispatch, type SetStateAction } from "react";
import { Section, SubToggle, QuickStepper, Segmented, Field, GroupedSelect } from "../kit";
import ConditionFormulaEditor, { type Condition } from "../ConditionFormulaEditor";
import OffsetInput from "./OffsetInput";
import LadderEditor from "./LadderEditor";
import type { BacktestStrategy, SortDir } from "../../../lib/backtest/strategy";
import { FILL_PRICE_GROUPS, FILL_PRICE_GROUPS_NO_EXPR } from "../../../lib/backtest/fillPrice";
import { SORT_FIELDS } from "../../../lib/backtest/sortFields";

const selBox: React.CSSProperties = {
  fontSize: 13, color: "var(--text-primary)", border: "1px solid var(--border-strong)",
  borderRadius: "var(--bs-border-radius)", padding: "6px 9px", background: "var(--bg-card)", cursor: "pointer",
};
const dateBox: React.CSSProperties = {
  fontFamily: "var(--bs-font-mono)", fontSize: 13, color: "var(--text-primary)",
  border: "1px solid var(--border-strong)", borderRadius: "var(--bs-border-radius)",
  padding: "6px 9px", background: "var(--bg-card)",
};
const chipBtn: React.CSSProperties = {
  fontSize: 11, color: "var(--text-secondary)", border: "1px solid var(--border-strong)",
  borderRadius: "var(--bs-border-radius)", padding: "5px 9px", background: "var(--bg-card)", cursor: "pointer",
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
        <Field label="투자 기간">
          <input type="date" value={s.startDate} max={s.endDate}
            onChange={(e) => set((x) => ({ ...x, startDate: e.target.value }))} style={dateBox} />
          <span style={{ color: "var(--text-secondary)" }}>~</span>
          <input type="date" value={s.endDate} min={s.startDate}
            onChange={(e) => set((x) => ({ ...x, endDate: e.target.value }))} style={dateBox} />
          <span style={{ display: "flex", gap: 5 }}>
            {([["1년", 1], ["3년", 3], ["5년", 5], ["전체기간", 0]] as const).map(([label, yrs]) => (
              <button key={label} type="button" onClick={() => set((x) => {
                const end = x.endDate || new Date().toISOString().slice(0, 10);
                const start = yrs === 0 ? "2015-01-01"
                  : `${Number(end.slice(0, 4)) - yrs}${end.slice(4)}`;
                return { ...x, startDate: start, endDate: end };
              })} style={chipBtn}>{label}</button>
            ))}
          </span>
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
        <Field label="신호 기준">
          <Segmented value={String(s.signalLag)} onChange={(v) => set((x) => ({ ...x, signalLag: v === "1" ? 1 : 0 }))}
            options={[{ id: "0", label: "당일 종가" }, { id: "1", label: "전일 종가 (젠포트식)" }]} />
          {s.signalLag === 0 && (s.buy.fillType !== "close" || s.sell.fillType !== "close") ? (
            <span style={{ fontSize: 11, color: "#d97706" }}>
              ⚠ 당일 종가로 만든 신호를 시가·전일가에 체결하면 look-ahead — 전일 종가 기준 권장
            </span>
          ) : (
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              젠포트는 전일 종가 기준 선정 → 익일 매매 (체결은 당일 가격)
            </span>
          )}
        </Field>
        <Field label="분봉 정밀 체결">
          <Segmented value={s.intradayFill ? "on" : "off"}
            onChange={(v) => set((x) => ({ ...x, intradayFill: v === "on" }))}
            options={[{ id: "off", label: "일봉 모델" }, { id: "on", label: "분봉 정밀" }]} />
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            적재된 (종목,일자) 분봉으로 매매 시간 윈도 내 지정가·시장가·TWAP 정밀 체결 —
            없는 날은 일봉 폴백 (결과에 적용률 표시)
          </span>
        </Field>
        {s.intradayFill && (
          <Field label="매수 시간">
            <input value={s.buy.timeStart} onChange={(e) => patchBuy({ timeStart: e.target.value })} style={dateBox} placeholder="09:00" />
            <span style={{ color: "var(--text-secondary)" }}>~</span>
            <input value={s.buy.timeEnd} onChange={(e) => patchBuy({ timeEnd: e.target.value })} style={dateBox} placeholder="15:30" />
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>이 윈도 안의 분봉으로만 매수 체결</span>
          </Field>
        )}
      </Section>

      <Section title="매수 조건 설정" hint="팩터·함수 조건식" tone="buy"
        enabled={s.buy.enabled} onToggle={(v) => patchBuy({ enabled: v })}>
        <ConditionFormulaEditor tone="buy" conditions={s.buy.conditions} onChange={(c: Condition[]) => patchBuy({ conditions: c })}
          logicExpr={s.buy.logicExpr} onLogicChange={(v) => patchBuy({ logicExpr: v })} logicDefaultLabel="모두 AND" sideKey="buy" />
        <SubToggle tone="buy" label="펀더멘털 조건 평가" hint="현재 스냅샷 기준 · look-ahead 주의" on={s.buy.allowFundamentals} onChange={(v) => patchBuy({ allowFundamentals: v })} />
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>고급 체결 옵션</div>
          <SubToggle tone="buy" label="분할 매수 (래더)" hint="가격변동 단계별 비중 체결"
            on={s.buy.splitBuy}
            onChange={(v) => patchBuy({ splitBuy: v, ladder: v && s.buy.ladder.length === 0 ? [{ movePct: 0, weightPct: 50 }, { movePct: -2, weightPct: 50 }] : s.buy.ladder })} />
          {s.buy.splitBuy && (
            <LadderEditor side="buy" steps={s.buy.ladder} onChange={(ladder) => patchBuy({ ladder })} />
          )}
          <SubToggle tone="buy" label="돌파 매수" hint="기준가 돌파 시에만 진입" on={s.buy.breakthrough} onChange={(v) => patchBuy({ breakthrough: v })} />
          {s.buy.breakthrough && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingLeft: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>방향</span>
                <Segmented tone="buy" value={s.buy.breakthroughDirection}
                  onChange={(d) => patchBuy({ breakthroughDirection: d })}
                  options={[{ id: "up", label: "상방" }, { id: "both", label: "양방" }]} />
                <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>기준가</span>
                <GroupedSelect value={s.buy.breakthroughBaseType}
                  onChange={(id) => patchBuy({ breakthroughBaseType: id })} groups={FILL_PRICE_GROUPS_NO_EXPR} />
              </div>
              <OffsetInput value={s.buy.breakthroughOffsetPct}
                onChange={(breakthroughOffsetPct) => patchBuy({ breakthroughOffsetPct })} />
              <span style={{ fontSize: 11, color: "#d97706" }}>
                ⚠ 당일 시초가 등 변동성 큰 기준은 불공정 거래 소지에 유의하세요
              </span>
            </div>
          )}
          <Field label="매수 시점">
            <Segmented tone="buy" value={s.buy.buyTiming} onChange={(t) => patchBuy({ buyTiming: t })}
              options={[{ id: "pre_open", label: "장 시작 전" }, { id: "intraday", label: "장중 주문" }]} />
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              장중 주문은 지정가류 매수에서 시가 갭 체결을 배제 (보수적)
            </span>
          </Field>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>TWAP·VWAP 체결은 위 "체결가 유형"에서 선택</div>
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
        <SubToggle tone="buy" label="우선순위식 (일별)" hint="봉마다 식 값으로 매수 순서 결정 — 위 정렬 대신"
          on={s.buy.sortExpr.trim() !== ""} onChange={(on) => patchBuy({ sortExpr: on ? "{종합점수}" : "" })}>
          <input value={s.buy.sortExpr} spellCheck={false}
            onChange={(e) => patchBuy({ sortExpr: e.target.value })}
            placeholder="예: {모멘텀점수} 또는 변화율_기간({종가},{20일})"
            style={{ fontFamily: "var(--bs-font-mono)", fontSize: 12, minWidth: 220, padding: "6px 9px", border: "1px solid var(--border-strong)", borderRadius: "var(--bs-border-radius)", background: "var(--bg-card)", color: "var(--text-primary)" }} />
          <Segmented tone="buy" value={s.buy.sortExprDesc ? "desc" : "asc"}
            onChange={(d) => patchBuy({ sortExprDesc: d === "desc" })}
            options={[{ id: "desc", label: "높은순" }, { id: "asc", label: "낮은순" }]} />
        </SubToggle>
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
        {s.buy.fillType === "expr" && (
          <Field label="기준가 수식">
            <input value={s.buy.fillExpr} spellCheck={false}
              onChange={(e) => patchBuy({ fillExpr: e.target.value })}
              placeholder="예: (과거값({고가},{1일})+과거값({저가},{1일}))/2"
              style={{ fontFamily: "var(--bs-font-mono)", fontSize: 12, minWidth: 280, padding: "7px 10px", border: "1px solid var(--border-strong)", borderRadius: "var(--bs-border-radius)", background: "var(--bg-card)", color: "var(--text-primary)" }} />
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              마지막 봉 값이 기준가 — 당일 종가 포함 식은 look-ahead, 과거값(…) 권장
            </span>
          </Field>
        )}
        <Field label="매수 가격 기준">
          <OffsetInput value={s.buy.fillOffsetPct} onChange={(fillOffsetPct) => patchBuy({ fillOffsetPct })} />
        </Field>
        <SubToggle tone="buy" label="종목당 최대 매수 금액" hint="종목별 투자 한도"
          on={s.buy.maxBuyAmount > 0} onChange={(on) => patchBuy({ maxBuyAmount: on ? 1000 : 0 })}>
          <QuickStepper value={s.buy.maxBuyAmount} onChange={(v) => patchBuy({ maxBuyAmount: v })}
            chips={[1000, 3000, 5000]} unit="만원" min={100} />
        </SubToggle>
        <SubToggle tone="buy" label="1일 최대 매수 종목 수" hint="하루 신규 진입 수 제한"
          on={s.buy.maxBuyPerDay > 0} onChange={(on) => patchBuy({ maxBuyPerDay: on ? 1 : 0 })}>
          <QuickStepper value={s.buy.maxBuyPerDay} onChange={(v) => patchBuy({ maxBuyPerDay: v })} chips={[1, 3, 5]} unit="종목" min={1} />
        </SubToggle>
        <Field label="재매수 방지">
          <QuickStepper value={s.buy.reBuyBlockDays} onChange={(v) => patchBuy({ reBuyBlockDays: v })} chips={[5, 10]} unit="일" min={0} />
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>청산 후 N일(캘린더) 재매수 금지 · 0=미사용</span>
        </Field>
      </Section>

      <Section title="자산배분 옵션" hint="현금 비중 상시 보유" tone="neutral"
        enabled={s.cashReservePct > 0} onToggle={(on) => set((x) => ({ ...x, cashReservePct: on ? 10 : 0 }))}>
        <Field label="현금 비중">
          <QuickStepper value={s.cashReservePct} onChange={(v) => set((x) => ({ ...x, cashReservePct: v }))}
            chips={[10, 20, 30]} unit="%" min={0} max={90} />
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            평가자산의 N%를 현금으로 상시 유지 — 매수 가용액에서 제외
          </span>
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
