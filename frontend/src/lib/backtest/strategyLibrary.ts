// 전략 저장/불러오기(v2) + 빌트인 템플릿 — 젠포트식 BacktestStrategy 전체를 보관.
// 구 strategyStorage(alpha_saved_strategies)는 이전 설정 모양이라 키를 분리(v2).

import type { Condition } from "../../components/backtest/ConditionFormulaEditor";
import type { BacktestStrategy } from "./strategy";

export interface SavedBacktestStrategy {
  id: string;
  name: string;
  savedAt: string;
  strategy: BacktestStrategy;
}

const KEY = "alpha_bt_strategies_v2";
const MAX = 30;

export function listSavedStrategies(): SavedBacktestStrategy[] {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function saveBacktestStrategy(strategy: BacktestStrategy): SavedBacktestStrategy {
  const list = listSavedStrategies();
  const item: SavedBacktestStrategy = {
    id: `bts_${Date.now()}`,
    name: (strategy.name || "").trim() || `전략 ${list.length + 1}`,
    savedAt: new Date().toISOString(),
    strategy,
  };
  list.unshift(item);
  localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX)));
  return item;
}

export function deleteSavedStrategy(id: string): void {
  localStorage.setItem(KEY, JSON.stringify(listSavedStrategies().filter((s) => s.id !== id)));
}

/** 저장본을 현재 스키마에 안전 병합 — 이후 필드가 추가돼도 기본값으로 채워짐. */
export function mergeStrategy(base: BacktestStrategy, loaded: Partial<BacktestStrategy> | null | undefined): BacktestStrategy {
  if (!loaded) return base;
  return {
    ...base,
    ...loaded,
    marketTiming: { ...base.marketTiming, ...(loaded.marketTiming ?? {}) },
    buy: { ...base.buy, ...(loaded.buy ?? {}) },
    sell: { ...base.sell, ...(loaded.sell ?? {}) },
    universe: { ...base.universe, ...(loaded.universe ?? {}) },
  };
}

// ─── 빌트인 템플릿 ────────────────────────────────────────────────────────────
export interface StrategyTemplate {
  id: string;
  name: string;
  desc: string;
  apply: (base: BacktestStrategy) => BacktestStrategy;
}

const uid = () => Math.random().toString(36).slice(2, 9);

const cond = (
  factorName: string, factorToken: string, functionId: string,
  params: Record<string, string>, expr: string, op: Condition["op"], rhs: string,
  inner?: { fn: string; params: Record<string, string> },
): Condition => ({
  id: `tpl_${uid()}`,
  factorName, factorToken, functionId, params, expr, op, rhs,
  innerFunctionId: inner?.fn,
  innerParams: inner?.params,
});

const momentumTop5 = (): Condition[] => [
  cond("종가", "{종가}", "rank", { dir: "DESC" },
    "순위(변화율_기간({종가}, 20), 내림차순)", "lte", "5",
    { fn: "pct", params: { n: "20" } }),
];

export const STRATEGY_TEMPLATES: StrategyTemplate[] = [
  {
    id: "momentum_top5",
    name: "모멘텀 상위 5",
    desc: "20일 수익률 횡단면 상위 5종목 매수 · 트레일링 스탑 5%",
    apply: (base) => ({
      ...base,
      name: "모멘텀 상위 5",
      buy: { ...base.buy, conditions: momentumTop5(), maxStocks: 5 },
      sell: { ...base.sell, trailing: { on: true, pct: 5 } },
    }),
  },
  {
    id: "trend_liquidity",
    name: "추세 + 거래대금",
    desc: "평균모멘텀스코어 70↑ 이면서 거래대금 상위 20종목",
    apply: (base) => ({
      ...base,
      name: "추세 + 거래대금",
      buy: {
        ...base.buy,
        conditions: [
          cond("종가", "{종가}", "ams", { n: "20" }, "평균모멘텀스코어({종가}, 20)", "gte", "70"),
          cond("거래대금", "{거래대금}", "rank", { dir: "DESC" }, "순위({거래대금}, 내림차순)", "lte", "20"),
        ],
        maxStocks: 10,
      },
      sell: { ...base.sell, stopLoss: { on: true, pct: 7 } },
    }),
  },
  {
    id: "weekly_momentum",
    name: "주간 리밸런싱 모멘텀",
    desc: "신규 매수는 주 첫 거래일에만 · 20일 수익률 상위 5 · 트레일링 5%",
    apply: (base) => ({
      ...base,
      name: "주간 리밸런싱 모멘텀",
      rebalancePeriod: "weekly",
      buy: { ...base.buy, conditions: momentumTop5(), maxStocks: 5 },
      sell: { ...base.sell, trailing: { on: true, pct: 5 } },
    }),
  },
  {
    id: "defensive_timing",
    name: "마켓타이밍 방어형",
    desc: "코스피 평균모멘텀스코어 50 미만이면 전량 청산 · 모멘텀 상위 5 매수",
    apply: (base) => ({
      ...base,
      name: "마켓타이밍 방어형",
      marketTiming: {
        on: true, index: "KOSPI", mode: "exit_all",
        conditions: [cond("종가", "{종가}", "ams", { n: "20" }, "평균모멘텀스코어({종가}, 20)", "gte", "50")],
      },
      buy: { ...base.buy, conditions: momentumTop5(), maxStocks: 5 },
      sell: { ...base.sell, stopLoss: { on: true, pct: 5 } },
    }),
  },
];
