/**
 * Client-side YAML generator.
 * BuilderState → .kis.yaml string without calling the backend.
 */

import type {
  BuilderState, BuilderCondition, BuilderConditionGroup, ConditionOperand,
} from "@/types/builder";

const OP_MAP: Record<string, string> = {
  greater_than:  "greater_than",
  less_than:     "less_than",
  greater_equal: "greater_equal",
  less_equal:    "less_equal",
  cross_above:   "cross_above",
  cross_below:   "cross_below",
  equals:        "equals",
};

function indent(s: string, n: number): string {
  const pad = " ".repeat(n);
  return s.split("\n").map((l) => (l ? pad + l : l)).join("\n");
}

function operandToYaml(op: ConditionOperand): { indicator?: string; compare_to?: string | number; value?: number } {
  if (op.type === "price")     return { indicator: op.priceField ?? "close" };
  if (op.type === "indicator") return { indicator: op.indicatorAlias };
  return { value: op.value ?? 0 };
}

function conditionToYaml(c: BuilderCondition): string {
  if (c.isCandlestick) {
    const sig = c.candlestickSignal ?? "detected";
    return `- candlestick: ${c.candlestickAlias}\n  signal: ${sig}`;
  }
  const left  = operandToYaml(c.left);
  const right = operandToYaml(c.right);
  const op    = OP_MAP[c.operator] ?? c.operator;

  let yaml = `- indicator: ${left.indicator ?? "close"}\n  operator: ${op}`;

  if (c.right.type === "indicator") {
    yaml += `\n  compare_to: ${c.right.indicatorAlias}`;
    if (c.right.indicatorOutput && c.right.indicatorOutput !== "value")
      yaml += `\n  compare_output: ${c.right.indicatorOutput}`;
  } else if (c.right.type === "price") {
    yaml += `\n  compare_to: ${c.right.priceField ?? "close"}`;
  } else {
    yaml += `\n  value: ${c.right.value ?? 0}`;
  }

  if (c.left.indicatorOutput && c.left.indicatorOutput !== "value")
    yaml += `\n  output: ${c.left.indicatorOutput}`;

  return yaml;
}

function conditionGroupToYaml(g: BuilderConditionGroup, sectionName: string): string {
  const conds = g.conditions.map((c) => indent(conditionToYaml(c), 4)).join("\n");
  return `${sectionName}:\n  logic: ${g.logic}\n  conditions:\n${conds}`;
}

export function builderStateToYaml(state: BuilderState): string {
  const { metadata, indicators, entry, exit, risk } = state;

  // Metadata
  const meta = [
    `version: "1.0"`,
    ``,
    `metadata:`,
    `  name: "${metadata.name}"`,
    `  description: "${metadata.description}"`,
    `  author: "${metadata.author}"`,
    `  tags: [${metadata.tags.map((t) => `"${t}"`).join(", ")}]`,
    ``,
    `strategy:`,
    `  id: ${metadata.id}`,
    `  category: ${metadata.category}`,
  ];

  // Indicators
  const indLines: string[] = ["  indicators:"];
  const candleLines: string[] = [];
  for (const ind of indicators) {
    const isCandlestick = ind.params && Object.keys(ind.params).length === 0
      && !["sma","ema","rsi","macd","bollinger","atr"].includes(ind.indicatorId);
    // Simple check: if output is "value" and no params → likely candlestick
    const couldBeCandlestick =
      Object.keys(ind.params).length === 0 &&
      ind.output === "value" &&
      !ind.indicatorId.match(/^(sma|ema|rsi|macd|atr|cci|adx|stoch|boll|wma|dema|tema|hma|kama|obv|vwap|mfi|roc|mom)/i);

    if (couldBeCandlestick) {
      candleLines.push(`    - id: ${ind.indicatorId}`);
      if (ind.alias !== ind.indicatorId)
        candleLines.push(`      alias: ${ind.alias}`);
    } else {
      indLines.push(`    - id: ${ind.indicatorId}`);
      if (ind.displayName) indLines.push(`      name: "${ind.displayName}"`);
      indLines.push(`      alias: ${ind.alias}`);
      if (ind.output !== "value") indLines.push(`      output: ${ind.output}`);
      if (Object.keys(ind.params).length) {
        indLines.push(`      params:`);
        for (const [k, v] of Object.entries(ind.params))
          indLines.push(`        ${k}: ${v}`);
      }
    }
  }

  const indSection = indLines.join("\n");
  const csSection = candleLines.length
    ? "\n  candlesticks:\n" + candleLines.join("\n")
    : "";

  // Conditions
  const entrySection = indent(conditionGroupToYaml(entry, "entry"), 2);
  const exitSection  = indent(conditionGroupToYaml(exit,  "exit"),  2);

  // Risk
  const riskLines: string[] = ["risk:"];
  if (risk.stopLoss.enabled)
    riskLines.push(`  stop_loss:\n    enabled: true\n    percent: ${risk.stopLoss.percent}`);
  if (risk.takeProfit.enabled)
    riskLines.push(`  take_profit:\n    enabled: true\n    percent: ${risk.takeProfit.percent}`);
  if (risk.trailingStop.enabled)
    riskLines.push(`  trailing_stop:\n    enabled: true\n    percent: ${risk.trailingStop.percent}`);

  return [
    meta.join("\n"),
    indSection,
    csSection,
    entrySection,
    exitSection,
    ``,
    riskLines.join("\n"),
  ].filter(Boolean).join("\n") + "\n";
}

/** Generate Python code preview from BuilderState */
export function builderStateToPython(state: BuilderState): string {
  const { metadata, indicators, entry, exit, risk } = state;

  const inds = indicators
    .map((i) => {
      const params = Object.entries(i.params)
        .map(([k, v]) => `${k}=${v}`)
        .join(", ");
      return `    ${i.alias} = self.register_indicator("${i.indicatorId}", ${params})`;
    })
    .join("\n");

  const mkCond = (c: BuilderCondition): string => {
    if (c.isCandlestick) return `detect_pattern("${c.candlestickAlias}") == "${c.candlestickSignal}"`;
    const l = c.left.type === "indicator" ? c.left.indicatorAlias : `data.${c.left.priceField ?? "Close"}`;
    const r = c.right.type === "indicator" ? c.right.indicatorAlias
            : c.right.type === "price"     ? `data.${c.right.priceField ?? "Close"}`
            : String(c.right.value ?? 0);
    const opMap: Record<string, string> = {
      greater_than: ">", less_than: "<", greater_equal: ">=",
      less_equal: "<=", equals: "==", cross_above: "> prev", cross_below: "< prev",
    };
    return `${l} ${opMap[c.operator] ?? c.operator} ${r}`;
  };

  const entryConds = entry.conditions.map(mkCond).join(` ${entry.logic} `);
  const exitConds  = exit.conditions.map(mkCond).join(` ${exit.logic} `);

  return `# Strategy: ${metadata.name}
# Generated by FICC Quant Platform

class ${metadata.id.replace(/[^a-zA-Z0-9]/g, "_")}Strategy(BaseStrategy):
    name = "${metadata.name}"
    required_days = 100

    def initialize(self):
${inds || "        pass"}

    def generate_signal(self, stock_code, stock_name):
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty:
            return Signal(stock_code, stock_name, Action.HOLD, 0, "데이터 없음")

        # Entry
        if ${entryConds || "False"}:
            return Signal(stock_code, stock_name, Action.BUY, 0.8, "진입 조건 충족")

        # Exit
        if ${exitConds || "False"}:
            return Signal(stock_code, stock_name, Action.SELL, 0.8, "청산 조건 충족")

        return Signal(stock_code, stock_name, Action.HOLD, 0, "조건 미충족")
`;
}
