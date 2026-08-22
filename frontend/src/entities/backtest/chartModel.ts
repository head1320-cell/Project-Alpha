/** Backtest types — mirrors KIS backtester/frontend/src/types/backtest.ts */

export interface ParamDefinition {
  default: number;
  min: number;
  max: number;
  step?: number;
  type?: "int" | "float";
  label?: string;
}

export interface PerformanceMetrics {
  basic: {
    total_return: number;      // %
    annual_return: number;     // %
    max_drawdown: number;      // %
    start_equity: number;
    end_equity: number;
  };
  risk: {
    sharpe_ratio: number;
    sortino_ratio: number;
    calmar_ratio: number;
  };
  greeks: { alpha: number; beta: number };
  trading: {
    total_orders: number;
    win_rate: number;
    profit_factor: number;
    avg_trade_return: number;
    total_commission: number;
    total_slippage: number;
  };
}

export interface TradeInfo {
  date: string;
  ticker: string;
  side: "buy" | "sell";
  price: number;
  quantity: number;
  value: number;
  pnl: number | null;
  reason: string;
}

export interface BacktestResult {
  error?: boolean;
  message?: string;
  result: {
    statistics: {
      total_return_pct: number;
      cagr: number;
      sharpe_ratio: number;
      sortino_ratio: number;
      calmar_ratio: number;
      max_drawdown_pct: number;
      num_trades: number;
      win_rate: number;
      profit_factor: number;
      avg_trade_return: number;
      total_commission: number;
      total_slippage: number;
    };
    equity_curve: number[];
    equity_dates: string[];
    drawdown_curve: number[];
    monthly_returns: Array<{ year: number; month: number; return_pct: number }>;
    trades: TradeInfo[];
    symbol_results: Array<{ symbol: string; total_return_pct: number; num_trades: number; win_rate: number }>;
  };
  data_range?: { start: string; end: string };
  cost_analysis?: { total_trades: number; total_commission: number; total_slippage: number };
}

export interface OptimizeResult {
  best_params: Record<string, number>;
  best_sharpe: number;
  best_return: number;
  best_drawdown: number;
  grid: Array<{
    params: Record<string, number>;
    sharpe: number;
    return_pct: number;
    max_drawdown: number;
    num_trades: number;
  }>;
}
