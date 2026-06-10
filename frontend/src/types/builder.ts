/** Builder TypeScript Types — ported from KIS strategy_builder/frontend */

export type IndicatorCategory =
  | "moving_average" | "oscillator" | "trend"
  | "volume" | "volatility" | "misc" | "candlestick";

export interface IndicatorParam {
  name: string; type: "number" | "string";
  default: number | string; min?: number; max?: number; step?: number;
  description?: string;
}
export interface IndicatorOutput { id: string; name: string }
export interface IndicatorDefinition {
  id: string; name: string; nameKo: string;
  category: IndicatorCategory; description: string;
  params: IndicatorParam[]; outputs: IndicatorOutput[];
  defaultOutput: string; leanUnsupported?: boolean;
}

export interface BuilderIndicator {
  id: string; indicatorId: string;
  alias: string; displayName?: string;
  params: Record<string, number | string>; output: string;
}

export type ConditionOperator =
  | "greater_than" | "less_than" | "greater_equal"
  | "less_equal" | "cross_above" | "cross_below" | "equals";

export type ConditionOperandType = "indicator" | "value" | "price" | "fundamental";
export interface ConditionOperand {
  type: ConditionOperandType;
  indicatorAlias?: string; indicatorOutput?: string;
  value?: number; priceField?: "close" | "open" | "high" | "low";
  fundamentalField?: string;  // PER, ROE 등 (백테스트 시 종목 펀더멘털로 평가)
}

export interface BuilderCondition {
  id: string; left: ConditionOperand;
  operator: ConditionOperator; right: ConditionOperand;
  isCandlestick?: boolean; candlestickAlias?: string;
  candlestickSignal?: string;
}

export interface BuilderConditionGroup {
  logic: "AND" | "OR"; conditions: BuilderCondition[];
}

export interface BuilderMetadata {
  id: string; name: string; description: string;
  category: string; tags: string[]; author: string;
}

export interface RiskManagement {
  stopLoss:     { enabled: boolean; percent: number };
  takeProfit:   { enabled: boolean; percent: number };
  trailingStop: { enabled: boolean; percent: number };
}

export interface BuilderState {
  metadata: BuilderMetadata;
  indicators: BuilderIndicator[];
  entry: BuilderConditionGroup;
  exit: BuilderConditionGroup;
  risk: RiskManagement;
}
