// 대상 경로: frontend/src/lib/backtest/strategy.ts
//
// ★키스톤★ — 지금 TerminalBacktester 에 흩어진 useState(stopLoss/takeProfit/maxHoldDays/
// sellDividePct/buyDividePct/maxBuyPerDay…)를 객체 하나로 모은다.
// 아코디언 섹션과 우측 요약 레일이 "같은 상태"를 읽으므로 요약은 거의 공짜로 따라온다.

import type { Condition } from "../../components/backtest/ConditionFormulaEditor";
import { fillPriceLabel } from "./fillPrice";
import { sortFieldLabel } from "./sortFields";

export type SortDir = "DESC" | "ASC";

export interface BuyState {
  enabled: boolean;
  conditions: Condition[];          // 매수 조건식 (A, B, …)
  logicExpr: string;                // 논리 조건식 — 예: "every(A,3) and (B or C)". 비우면 모두 AND
  primarySort: { expr: string; dir: SortDir };
  secondarySort?: { expr: string; dir: SortDir };
  sortExpr: string;                 // 우선순위식 (일별) — 봉마다 식 값으로 매수 순서 정렬. 비우면 미사용
  sortExprDesc: boolean;            // true=식 값 높은순
  limitType: "MAX" | "LIMIT";
  maxStocks: number;                // LIMIT 일 때 종목 수
  weightPct: number;                // 종목당 비중 %
  weightMode: "equal" | "atr";
  fillType: string;                 // 매수 체결가 유형 id (fillPrice.ts — 엔진 fill_price 와 동일)
  fillExpr: string;                 // fillType="expr"일 때의 기준가 산술식
  fillOffsetPct: number;            // 체결 기준가 ± 오프셋% (0=미사용, ≠0이면 지정가 도달 검증)
  maxBuyAmount: number;             // 종목당 최대 매수 금액(만원, 0=무제한)
  reBuyBlockDays: number;           // 재매수 방지: 청산 후 N일(캘린더) 재매수 금지 (0=미사용)
  maxBuyPerDay: number;             // 1일 최대 신규 매수 종목 수 (0=무제한)
  timeStart: string;
  timeEnd: string;
  // 고급 체결(기본 꺼짐) — TWAP은 체결가 유형(fillType)에서 선택
  splitBuy: boolean;        // 분할 매수 (래더) 사용
  ladder: Array<{ movePct: number; weightPct: number }>;  // 가격변동%·비중% 단계 (신호 당일 유효)
  splitBuyPct: number;      // (레거시) 1회 매수 비중 % — 래더 미설정 시 폴백
  splitBuyCount: number;    // (레거시) 최대 분할 횟수
  breakthrough: boolean;    // 돌파매수: 기준가 돌파 시에만 진입
  breakthroughBaseType: string;       // 돌파 기준가 유형 (기본 prev_high=전일 고가)
  breakthroughOffsetPct: number;      // 기준가 ± % 돌파 라인
  breakthroughDirection: "up" | "both";  // 상방 | 양방(하방 낙폭 진입 포함)
  buyTiming: "pre_open" | "intraday"; // 매수 시점: 장 시작 전(시가 가능) | 장중(시가 갭 배제)
  // #4: 펀더멘털 토큰을 조건 평가에 포함(스냅샷·look-ahead 근사). 기본 false.
  allowFundamentals: boolean;
}

export interface SellState {
  enabled: boolean;
  orderType: "FIX" | "MARKET";
  fillType: string;                 // 매도 체결가 유형 id (fillPrice.ts)
  fillExpr: string;                 // fillType="expr"일 때의 기준가 산술식
  fillOffsetPct: number;            // 매도 체결 기준가 ± 오프셋% (신호 매도에 적용)
  expiryFillType: string;           // 보유일 만기 매도 가격 기준 (기본 close)
  expiryFillOffsetPct: number;      // 만기 매도 ±% (미도달 시 종가 폴백 — 반드시 청산)
  takeProfit: { on: boolean; pct: number };
  stopLoss: { on: boolean; pct: number };
  trailing: { on: boolean; pct: number };       // 드래깅 청산
  holdPeriod: { on: boolean; min: number; max?: number };
  dayTrade: boolean;                             // 당일 매매: 당일 진입을 같은 날 종가에 전량 청산
  conditions: Condition[];                       // 조건 매도
  logicExpr: string;                             // 매도 논리 조건식. 비우면 하나라도(OR)
  liquidate: { on: boolean; mode: "close" | "time" };
  timeStart: string;
  timeEnd: string;
  // 고급(기본 꺼짐) — TWAP은 체결가 유형(fillType)에서 선택
  splitTakeProfit: boolean; // 분할 매도 (래더) 사용
  ladder: Array<{ movePct: number; weightPct: number }>;  // 매도 래더 (신호 당일 유효)
  splitSellPct: number;     // (레거시) 1회 매도 비중 %
  splitSellCount: number;   // (레거시) 최대 분할 횟수
  expirySellMethod: "all" | "ladder";  // 보유일 만기: 일괄 | 분할(잔량 종가 청산)
  expiryDateSell: boolean;
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

export interface BasketLeg { ticker: string; name: string; weightPct: number }
export interface AssetAllocState {
  enabled: boolean;
  preset: "neutral" | "aggressive" | "stable" | "custom";
  etfPct: number;          // ETF 슬리브 비중 %
  stockPct: number;        // 주식 슬리브 비중 % (잔여 = 현금)
  basket: BasketLeg[];     // 바스켓 ETF 가중(합 100)
  rebalanceMonths: number; // 리밸런싱 주기 (개월)
  fillType: string;        // ETF 매수 기준가
  offsetPct: number;       // 매수 기준 ± %
}

export interface MarketTimingState {
  on: boolean;
  index: "KOSPI" | "KOSDAQ";        // 기준 지수
  mode: "block_buy" | "exit_all";   // 조건 위반(OFF) 시: 신규 매수 차단 | 전량 청산
  conditions: Condition[];          // 지수 조건식 — 전부 충족 시 ON (가격 함수 권장: ams/pct 등)
}

export interface BacktestStrategy {
  name: string;
  capital: number;         // 투자 금액(만원)
  startDate: string;
  endDate: string;
  feePct: number;
  slippagePct: number;
  rebalancePeriod: "daily" | "weekly" | "monthly";  // 신규 매수일: 매일(기존) | 주·월 첫 거래일
  signalLag: 0 | 1;        // 신호 기준: 0=당일 봉 포함(기존) | 1=전일 봉 기준(젠포트식 — 시가류 체결 정합)
  cashReservePct: number;  // 자산배분(단순 현금): 평가자산 대비 현금 상시 보유 % (0=미사용)
  assetAlloc: AssetAllocState;  // 자산배분 ETF 바스켓
  intradayFill: boolean;   // 하이브리드 체결: 적재된 분봉으로 매매 시간 윈도 내 정밀 체결
  marketTiming: MarketTimingState;
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
        { label: "리밸런싱", value: s.rebalancePeriod === "daily" ? "매일" : s.rebalancePeriod === "weekly" ? "매주" : "매월" },
        { label: "신호 기준", value: s.signalLag === 1 ? "전일 종가 (젠포트식)" : "당일 종가" },
        { label: "분봉 체결", value: s.intradayFill ? "정밀 (적재된 날만)" : "일봉 모델", muted: !s.intradayFill },
      ]},
      { label: "매수 조건", rows: [
        { label: "조건식", value: b.conditions.length ? b.conditions.map((_, i) => String.fromCharCode(65 + i)).join(", ") : "미설정", muted: !b.conditions.length },
        { label: "논리식", value: b.logicExpr.trim() || "모두 AND", muted: !b.logicExpr.trim() },
        { label: "우선순위", value: b.sortExpr.trim()
            ? `식: ${b.sortExpr.trim().slice(0, 24)}${b.sortExpr.trim().length > 24 ? "…" : ""} ${b.sortExprDesc ? "↓" : "↑"}`
            : `${sortFieldLabel(b.primarySort.expr)} ${b.primarySort.dir === "DESC" ? "↓" : "↑"}` },
        { label: "2차 정렬", value: b.secondarySort ? `${sortFieldLabel(b.secondarySort.expr)} ${b.secondarySort.dir === "DESC" ? "↓" : "↑"}` : "사용 안 함", muted: !b.secondarySort },
      ]},
      { label: "매수 비중", rows: [
        { label: "방식", value: b.weightMode === "equal" ? "균등" : "ATR" },
        { label: "종목당", value: `${b.weightPct}%` },
        { label: "대상 수", value: b.limitType === "MAX" ? "전체" : `${b.maxStocks}종목` },
        { label: "1일 최대", value: b.maxBuyPerDay > 0 ? `${b.maxBuyPerDay}종목` : "무제한", muted: b.maxBuyPerDay === 0 },
        { label: "종목당 한도", value: b.maxBuyAmount > 0 ? `${b.maxBuyAmount.toLocaleString()}만원` : "무제한", muted: b.maxBuyAmount === 0 },
        { label: "재매수 방지", value: b.reBuyBlockDays > 0 ? `${b.reBuyBlockDays}일` : "미사용", muted: b.reBuyBlockDays === 0 },
        { label: "체결가", value: `${fillPriceLabel(b.fillType)}${b.fillOffsetPct !== 0 ? ` ${b.fillOffsetPct > 0 ? "+" : ""}${b.fillOffsetPct}%` : ""}` },
        { label: "현금 비중", value: s.cashReservePct > 0 ? `${s.cashReservePct}% 상시 보유` : "미사용", muted: s.cashReservePct === 0 },
        { label: "ETF 자산배분", value: s.assetAlloc.enabled
            ? `ETF ${s.assetAlloc.etfPct}% · 주식 ${s.assetAlloc.stockPct}% (${s.assetAlloc.basket.length}종)`
            : "미사용", muted: !s.assetAlloc.enabled },
      ]},
      { label: "고급 체결", rows: advRows([["분할", b.splitBuy], ["돌파", b.breakthrough]]) },
      { label: "마켓타이밍", rows: [
        { label: "사용", value: s.marketTiming.on
            ? `${s.marketTiming.index} · ${s.marketTiming.mode === "exit_all" ? "전량 청산" : "매수 차단"}`
            : "미사용", muted: !s.marketTiming.on },
        { label: "조건", value: s.marketTiming.conditions.length ? `${s.marketTiming.conditions.length}개` : "없음",
          muted: !s.marketTiming.conditions.length },
      ]},
    ];
  }
  if (tab === "sell") {
    const v = s.sell;
    return [
      { label: "목표가 / 손절가", rows: [
        { label: "주문 방법", value: v.orderType === "MARKET" ? "시장가" : "지정가" },
        { label: "체결가", value: `${fillPriceLabel(v.fillType)}${v.fillOffsetPct !== 0 ? ` ${v.fillOffsetPct > 0 ? "+" : ""}${v.fillOffsetPct}%` : ""}` },
        { label: "목표가", value: v.takeProfit.on ? `${v.takeProfit.pct}% 상승` : "미설정", muted: !v.takeProfit.on },
        { label: "손절가", value: v.stopLoss.on ? `${v.stopLoss.pct}% 하락` : "미설정", muted: !v.stopLoss.on },
        { label: "드래깅 청산", value: v.trailing.on ? `고점 -${v.trailing.pct}%` : "미사용", muted: !v.trailing.on },
      ]},
      { label: "보유 기간", rows: v.dayTrade
        ? [{ label: "방식", value: "당일 매매 (종가 청산)" }]
        : [
          { label: "최소 보유", value: v.holdPeriod.on ? `${v.holdPeriod.min}일` : "미설정", muted: !v.holdPeriod.on },
          { label: "최대 보유", value: v.holdPeriod.max != null ? `${v.holdPeriod.max}일` : "미설정", muted: v.holdPeriod.max == null },
        ]},
      { label: "조건 매도", rows: [
        { label: "조건식", value: v.conditions.length ? v.conditions.map((_, i) => String.fromCharCode(65 + i)).join(", ") : "미사용", muted: !v.conditions.length },
        { label: "논리식", value: v.logicExpr.trim() || "하나라도 (OR)", muted: !v.logicExpr.trim() },
      ]},
      { label: "매도 시간", rows: [{ label: "시간대", value: `${v.timeStart}~${v.timeEnd}` }] },
    ];
  }
  const u = s.universe;
  const TOTAL_TIERS = 6;       // 코스피 중대형/중소형 + 코스닥 대형/중형/소형/초소형
  const TOTAL_SUBSECTORS = 88; // 젠포트 17그룹 → 88 세부업종 (고정)
  const themeSel = u.sectors.filter((x) => x.startsWith("theme:")).length;
  const includeGroups = u.groups.filter((g) => g.mode === "include").length;
  const excludeGroups = u.groups.filter((g) => g.mode === "exclude").length;
  return [
    { label: "매매 대상 종목", rows: [
      { label: "선택한 매매 대상", value: `${u.matched.toLocaleString()} 종목` },
      { label: "전체 종목", value: `${u.totalUniverse.toLocaleString()} 종목`, muted: true },
    ]},
    { label: "기본 설정", rows: [
      { label: "ETF", value: u.etf ? "포함" : "미포함", muted: !u.etf },
      { label: "관리 종목", value: u.managed ? "포함" : "미포함", muted: !u.managed },
      { label: "감리 종목", value: u.supervised ? "포함" : "미포함", muted: !u.supervised },
    ]},
    { label: "유니버스", rows: [
      { label: "시총군", value: u.caps.length >= TOTAL_TIERS ? "전체" : `${u.caps.length}/${TOTAL_TIERS}군`,
        muted: u.caps.length === 0 },
    ]},
    { label: "업종 선택", rows: [
      { label: "포함 업종 수", value: themeSel > 0 ? `${themeSel}개` : "전체", muted: themeSel === 0 },
      { label: "전체 업종 수", value: `${TOTAL_SUBSECTORS}개`, muted: true },
    ]},
    { label: "관심그룹", rows: [
      { label: "매수 대상 종목", value: `${includeGroups}그룹`, muted: includeGroups === 0 },
      { label: "매수 제외 종목", value: `${excludeGroups}그룹`, muted: excludeGroups === 0 },
    ]},
  ];
}

const advRows = (items: [string, boolean][]): SummaryRow[] => {
  const on = items.filter(([, v]) => v).map(([k]) => k);
  return [{ label: "사용", value: on.length ? on.join(", ") : "없음", muted: !on.length }];
};
