// 대상 경로: frontend/src/lib/backtest/strategy.ts
//
// ★키스톤★ — 지금 TerminalBacktester 에 흩어진 useState(stopLoss/takeProfit/maxHoldDays/
// sellDividePct/buyDividePct/maxBuyPerDay…)를 객체 하나로 모은다.
// 아코디언 섹션과 우측 요약 레일이 "같은 상태"를 읽으므로 요약은 거의 공짜로 따라온다.

import type { Condition } from "../../components/backtest/ConditionFormulaEditor";

export type SortDir = "DESC" | "ASC";

export interface BuyState {
  enabled: boolean;
  conditions: Condition[];          // 매수 조건식 (A, B, …)
  primarySort: { expr: string; dir: SortDir };
  secondarySort?: { expr: string; dir: SortDir };
  limitType: "MAX" | "LIMIT";
  maxStocks: number;                // LIMIT 일 때 종목 수
  weightPct: number;                // 종목당 비중 %
  weightMode: "equal" | "atr";
  basePrice: { type: string; pct: number };
  reBuyBlockDays: number;
  timeStart: string;
  timeEnd: string;
  // 고급 체결(기본 꺼짐)
  splitBuy: boolean;
  breakthrough: boolean;
  twapBuy: boolean;
  // #4: 펀더멘털 토큰을 조건 평가에 포함(스냅샷·look-ahead 근사). 기본 false.
  allowFundamentals: boolean;
}

export interface SellState {
  enabled: boolean;
  orderType: "FIX" | "MARKET";
  takeProfit: { on: boolean; pct: number };
  stopLoss: { on: boolean; pct: number };
  trailing: { on: boolean; pct: number };       // 드래깅 청산
  holdPeriod: { on: boolean; min: number; max?: number };
  conditions: Condition[];                       // 조건 매도
  liquidate: { on: boolean; mode: "close" | "time" };
  timeStart: string;
  timeEnd: string;
  // 고급(기본 꺼짐)
  splitTakeProfit: boolean;
  expiryDateSell: boolean;
  twapSell: boolean;
}

export interface UniverseState {
  etf: boolean;
  managed: boolean;
  supervised: boolean;
  caps: string[];          // 선택된 시총군 id
  sectors: string[];       // 포함 업종 id (88개 중)
  groups: { id: string; name: string; mode: "none" | "include" | "exclude"; tickers: string[] }[];
  matched: number;         // 실시간 매매 대상 종목 수
  totalUniverse: number;
}

export interface BacktestStrategy {
  name: string;
  capital: number;         // 투자 금액(만원)
  startDate: string;
  endDate: string;
  feePct: number;
  slippagePct: number;
  buy: BuyState;
  sell: SellState;
  universe: UniverseState;
}

// ─────────────────────────────────────────────────────────────
// 요약 레일이 읽는 구조
export type SummaryTab = "buy" | "sell" | "universe";
export interface SummaryRow { label: string; value: string; muted?: boolean }
export interface SummaryGroup { label: string; rows: SummaryRow[] }

const yearsBetween = (a: string, b: string): string => {
  const d = (new Date(b).getTime() - new Date(a).getTime()) / (365.25 * 864e5);
  return isFinite(d) && d > 0 ? `약 ${Math.round(d)}년` : "—";
};

export function buildSummary(s: BacktestStrategy, tab: SummaryTab): SummaryGroup[] {
  if (tab === "buy") {
    const b = s.buy;
    return [
      { label: "포트 기본", rows: [
        { label: "투자금", value: `${s.capital.toLocaleString()}만원` },
        { label: "기간", value: yearsBetween(s.startDate, s.endDate) },
        { label: "수수료", value: `${s.feePct}%` },
      ]},
      { label: "매수 조건", rows: [
        { label: "조건식", value: b.conditions.length ? b.conditions.map((_, i) => String.fromCharCode(65 + i)).join(", ") : "미설정", muted: !b.conditions.length },
        { label: "우선순위", value: `${shortExpr(b.primarySort.expr)} ${b.primarySort.dir === "DESC" ? "↓" : "↑"}` },
      ]},
      { label: "매수 비중", rows: [
        { label: "방식", value: b.weightMode === "equal" ? "균등" : "ATR" },
        { label: "종목당", value: `${b.weightPct}%` },
        { label: "대상 수", value: b.limitType === "MAX" ? "전체" : `${b.maxStocks}종목` },
      ]},
      { label: "고급 체결", rows: advRows([["분할", b.splitBuy], ["돌파", b.breakthrough], ["TWAP", b.twapBuy]]) },
    ];
  }
  if (tab === "sell") {
    const v = s.sell;
    return [
      { label: "목표가 / 손절가", rows: [
        { label: "주문 방법", value: v.orderType === "MARKET" ? "시장가" : "지정가" },
        { label: "목표가", value: v.takeProfit.on ? `${v.takeProfit.pct}% 상승` : "미설정", muted: !v.takeProfit.on },
        { label: "손절가", value: v.stopLoss.on ? `${v.stopLoss.pct}% 하락` : "미설정", muted: !v.stopLoss.on },
        { label: "드래깅 청산", value: v.trailing.on ? `고점 -${v.trailing.pct}%` : "미사용", muted: !v.trailing.on },
      ]},
      { label: "보유 기간", rows: [
        { label: "최소 보유", value: v.holdPeriod.on ? `${v.holdPeriod.min}일` : "미설정", muted: !v.holdPeriod.on },
        { label: "최대 보유", value: v.holdPeriod.max != null ? `${v.holdPeriod.max}일` : "미설정", muted: v.holdPeriod.max == null },
      ]},
      { label: "조건 매도", rows: [
        { label: "조건식", value: v.conditions.length ? v.conditions.map((_, i) => String.fromCharCode(65 + i)).join(", ") : "미사용", muted: !v.conditions.length },
      ]},
      { label: "매도 시간", rows: [{ label: "시간대", value: `${v.timeStart}~${v.timeEnd}` }] },
    ];
  }
  const u = s.universe;
  return [
    { label: "매매 대상 종목", rows: [
      { label: "대상", value: u.matched.toLocaleString() },
      { label: "전체", value: u.totalUniverse.toLocaleString(), muted: true },
    ]},
    { label: "기본 설정", rows: [
      { label: "ETF", value: u.etf ? "포함" : "미포함" },
      { label: "관리·감리", value: (u.managed || u.supervised) ? "일부 포함" : "미포함" },
    ]},
    { label: "유니버스", rows: [{ label: "시총군", value: `${u.caps.length}군` }] },
    { label: "업종", rows: [{ label: "포함 그룹", value: `${u.sectors.length}개` }] },
    { label: "관심그룹", rows: [
      { label: "매수 대상", value: `${u.groups.filter((g) => g.mode === "include").length}그룹` },
      { label: "매수 제외", value: `${u.groups.filter((g) => g.mode === "exclude").length}그룹`, muted: u.groups.every((g) => g.mode !== "exclude") },
    ]},
  ];
}

const advRows = (items: [string, boolean][]): SummaryRow[] => {
  const on = items.filter(([, v]) => v).map(([k]) => k);
  return [{ label: "사용", value: on.length ? on.join(", ") : "없음", muted: !on.length }];
};

const shortExpr = (e: string): string => (e.length > 10 ? e.slice(0, 9) + "…" : e || "—");
