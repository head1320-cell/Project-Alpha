/**
 * 전략 카탈로그 — 전략 실행(백엔드) ↔ 전략 설계(Builder)를 잇는 단일 진실 공급원
 * ===========================================================================
 * 백엔드 run_backtest의 10종 전략 각각을:
 *   - backendId : run_backtest에 넘기는 전략명 (실행)
 *   - label     : 표시명
 *   - builderState : Builder로 로드해 편집 가능한 정의 (설계)
 * 로 연결한다.
 *
 * 이로써 "전략 실행"에서 고른 전략을 "전략 설계"로 가져와 수정하고,
 * 다시 실행으로 돌아가 백테스트하는 유기적 워크플로우가 가능해진다.
 */

import type { BuilderState } from "@/entities/strategy/model";

export interface StrategyCatalogEntry {
  backendId: string;        // run_backtest 전략명
  label: string;            // 표시명
  description: string;
  category: string;
  editable: boolean;        // Builder에서 편집 가능 여부 (false면 실행 전용)
  builderState: BuilderState | null;
}

// 공통 리스크 기본값
const defaultRisk = {
  stopLoss: { enabled: true, percent: 5 },
  takeProfit: { enabled: false, percent: 10 },
  trailingStop: { enabled: false, percent: 3 },
};

function meta(id: string, name: string, description: string, category: string, tags: string[]) {
  return { id, name, description, category, tags, author: "KIS" };
}

export const STRATEGY_CATALOG: StrategyCatalogEntry[] = [
  // ── 1. 골든크로스 ──────────────────────────────────────────────
  {
    backendId: "GoldenCross", label: "골든크로스", category: "추세추종", editable: true,
    description: "단기 이동평균이 장기 이동평균을 상향 돌파 시 매수",
    builderState: {
      metadata: meta("golden_cross", "골든크로스", "단기 MA가 장기 MA를 상향 돌파 시 매수", "trend", ["ma", "crossover"]),
      indicators: [
        { id: "sma_1", indicatorId: "sma", alias: "sma_fast", params: { period: 5 }, output: "value" },
        { id: "sma_2", indicatorId: "sma", alias: "sma_slow", params: { period: 20 }, output: "value" },
      ],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "indicator", indicatorAlias: "sma_fast", indicatorOutput: "value" }, operator: "cross_above", right: { type: "indicator", indicatorAlias: "sma_slow", indicatorOutput: "value" } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "indicator", indicatorAlias: "sma_fast", indicatorOutput: "value" }, operator: "cross_below", right: { type: "indicator", indicatorAlias: "sma_slow", indicatorOutput: "value" } }] },
      risk: defaultRisk,
    },
  },
  // ── 2. 모멘텀 ──────────────────────────────────────────────────
  {
    backendId: "Momentum", label: "모멘텀", category: "추세추종", editable: true,
    description: "N일 수익률(ROC)이 기준 이상이면 매수",
    builderState: {
      metadata: meta("momentum", "모멘텀", "N일 수익률 기준 매수/매도", "momentum", ["momentum", "roc"]),
      indicators: [{ id: "roc_1", indicatorId: "roc", alias: "roc_60", params: { period: 60 }, output: "value" }],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "indicator", indicatorAlias: "roc_60", indicatorOutput: "value" }, operator: "greater_than", right: { type: "value", value: 10 } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "indicator", indicatorAlias: "roc_60", indicatorOutput: "value" }, operator: "less_than", right: { type: "value", value: 0 } }] },
      risk: defaultRisk,
    },
  },
  // ── 3. 52주 신고가 ─────────────────────────────────────────────
  {
    backendId: "Week52High", label: "52주 신고가", category: "돌파", editable: true,
    description: "종가가 252일 최고가에 근접하면 매수 (신고가 돌파)",
    builderState: {
      metadata: meta("week52_high", "52주 신고가", "종가가 252일 최고가 근접 시 매수", "breakout", ["52week", "high", "breakout"]),
      indicators: [{ id: "max_1", indicatorId: "sma", alias: "ma_120", params: { period: 120 }, output: "value" }],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "price", priceField: "close" }, operator: "greater_than", right: { type: "indicator", indicatorAlias: "ma_120", indicatorOutput: "value" } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "price", priceField: "close" }, operator: "less_than", right: { type: "indicator", indicatorAlias: "ma_120", indicatorOutput: "value" } }] },
      risk: { ...defaultRisk, stopLoss: { enabled: true, percent: 8 } },
    },
  },
  // ── 4. 연속 상승/하락 ──────────────────────────────────────────
  {
    backendId: "Consecutive", label: "연속 상승/하락", category: "역추세", editable: true,
    description: "연속 하락 후 반등 시 매수 (단기 과매도 반전)",
    builderState: {
      metadata: meta("consecutive", "연속 상승/하락", "연속 하락 후 반등 매수", "reversal", ["consecutive", "reversal"]),
      indicators: [{ id: "roc_1", indicatorId: "roc", alias: "roc_3", params: { period: 3 }, output: "value" }],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "indicator", indicatorAlias: "roc_3", indicatorOutput: "value" }, operator: "less_than", right: { type: "value", value: -5 } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "indicator", indicatorAlias: "roc_3", indicatorOutput: "value" }, operator: "greater_than", right: { type: "value", value: 3 } }] },
      risk: defaultRisk,
    },
  },
  // ── 5. 이격도 ──────────────────────────────────────────────────
  {
    backendId: "Disparity", label: "이격도", category: "역추세", editable: true,
    description: "주가가 이동평균에서 과도하게 벗어나면 회귀 베팅",
    builderState: {
      metadata: meta("disparity", "이격도", "주가-이동평균 이격 과대 시 매수", "mean_reversion", ["disparity"]),
      indicators: [{ id: "sma_1", indicatorId: "sma", alias: "ma_20", params: { period: 20 }, output: "value" }],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "price", priceField: "close" }, operator: "less_than", right: { type: "indicator", indicatorAlias: "ma_20", indicatorOutput: "value" } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "price", priceField: "close" }, operator: "greater_than", right: { type: "indicator", indicatorAlias: "ma_20", indicatorOutput: "value" } }] },
      risk: defaultRisk,
    },
  },
  // ── 6. 돌파 실패 ───────────────────────────────────────────────
  {
    backendId: "BreakoutFail", label: "돌파 실패", category: "역추세", editable: true,
    description: "고점 돌파 실패 후 하락 반전 시 매도/회피",
    builderState: {
      metadata: meta("breakout_fail", "돌파 실패", "고점 돌파 실패 반전", "reversal", ["breakout", "fail"]),
      indicators: [{ id: "atr_1", indicatorId: "atr", alias: "atr_14", params: { period: 14 }, output: "value" }],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "indicator", indicatorAlias: "atr_14", indicatorOutput: "value" }, operator: "greater_than", right: { type: "value", value: 0 } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "price", priceField: "close" }, operator: "less_than", right: { type: "price", priceField: "open" } }] },
      risk: { ...defaultRisk, stopLoss: { enabled: true, percent: 3 } },
    },
  },
  // ── 7. 강한 종가 ───────────────────────────────────────────────
  {
    backendId: "StrongClose", label: "강한 종가", category: "추세추종", editable: true,
    description: "종가가 당일 고가 근처에서 마감하면 매수 (강세 마감)",
    builderState: {
      metadata: meta("strong_close", "강한 종가", "고가 근처 강세 마감 시 매수", "trend", ["close", "strength"]),
      indicators: [],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "price", priceField: "close" }, operator: "greater_than", right: { type: "price", priceField: "open" } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "price", priceField: "close" }, operator: "less_than", right: { type: "price", priceField: "open" } }] },
      risk: defaultRisk,
    },
  },
  // ── 8. 변동성 확장 ─────────────────────────────────────────────
  {
    backendId: "Volatility", label: "변동성 확장", category: "돌파", editable: true,
    description: "ATR 변동성 확대 + 상승 시 추세 진입",
    builderState: {
      metadata: meta("volatility", "변동성 확장", "ATR 변동성 확대 돌파", "breakout", ["atr", "volatility"]),
      indicators: [{ id: "atr_1", indicatorId: "atr", alias: "atr_14", params: { period: 14 }, output: "value" }],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "price", priceField: "close" }, operator: "greater_than", right: { type: "price", priceField: "open" } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "price", priceField: "close" }, operator: "less_than", right: { type: "price", priceField: "low" } }] },
      risk: { ...defaultRisk, trailingStop: { enabled: true, percent: 5 } },
    },
  },
  // ── 9. 평균회귀 ────────────────────────────────────────────────
  {
    backendId: "MeanReversion", label: "평균회귀", category: "역추세", editable: true,
    description: "과매도 구간에서 평균 회귀를 노린 매수",
    builderState: {
      metadata: meta("mean_reversion", "평균회귀", "과매도 평균 회귀 매수", "mean_reversion", ["reversion"]),
      indicators: [{ id: "sma_1", indicatorId: "sma", alias: "ma_20", params: { period: 20 }, output: "value" }],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "price", priceField: "close" }, operator: "less_than", right: { type: "indicator", indicatorAlias: "ma_20", indicatorOutput: "value" } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "price", priceField: "close" }, operator: "greater_equal", right: { type: "indicator", indicatorAlias: "ma_20", indicatorOutput: "value" } }] },
      risk: defaultRisk,
    },
  },
  // ── 10. 추세 필터 ──────────────────────────────────────────────
  {
    backendId: "TrendFilter", label: "추세 필터", category: "추세추종", editable: true,
    description: "장기 추세 상방일 때만 매수 (추세 추종 필터)",
    builderState: {
      metadata: meta("trend_filter", "추세 필터", "장기 추세 상방 시에만 매수", "trend", ["trend", "filter"]),
      indicators: [{ id: "sma_1", indicatorId: "sma", alias: "ma_120", params: { period: 120 }, output: "value" }],
      entry: { logic: "AND", conditions: [{ id: "entry_1", left: { type: "price", priceField: "close" }, operator: "greater_than", right: { type: "indicator", indicatorAlias: "ma_120", indicatorOutput: "value" } }] },
      exit: { logic: "AND", conditions: [{ id: "exit_1", left: { type: "price", priceField: "close" }, operator: "less_than", right: { type: "indicator", indicatorAlias: "ma_120", indicatorOutput: "value" } }] },
      risk: defaultRisk,
    },
  },
];

// backendId로 카탈로그 조회
export function findStrategy(backendId: string): StrategyCatalogEntry | undefined {
  return STRATEGY_CATALOG.find((s) => s.backendId === backendId);
}

// Builder metadata.id → 카탈로그 (설계 후 실행 연결용)
export function findByBuilderId(builderId: string): StrategyCatalogEntry | undefined {
  return STRATEGY_CATALOG.find((s) => s.builderState?.metadata.id === builderId);
}
