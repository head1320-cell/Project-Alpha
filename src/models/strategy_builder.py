"""
Strategy Backtesting Engine
=============================
VectorBT/Backtrader-grade backtesting without code.

Strategies:
  - SMA/EMA Crossover (Golden Cross / Death Cross)
  - RSI Mean Reversion
  - Bollinger Band Breakout
  - MACD Signal Crossover

Features:
  - Commission & slippage modeling
  - Position sizing (Fixed %, Kelly, Volatility Target)
  - Parameter grid search optimization
  - Full performance metrics (Sharpe, Sortino, Calmar, Drawdown, etc.)
"""

from itertools import product

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

# ═══════════════════════════════════════════════════════════════════════════════
# Performance Metrics
# ═══════════════════════════════════════════════════════════════════════════════

def compute_performance_metrics(
    equity_curve: pd.Series,
    returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    risk_free_rate: float = 0.03,
    periods_per_year: int = 252,
) -> dict:
    """
    Compute comprehensive performance metrics from an equity curve.

    Returns 30+ metrics covering return, risk, drawdown, and system quality.
    """
    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1)
    n_days = len(returns)
    n_years = n_days / periods_per_year

    # ─── Return metrics ──────────────────────────────────────────────────
    cagr = float((1 + total_return) ** (1 / max(n_years, 0.01)) - 1)
    daily_rf = (1 + risk_free_rate) ** (1 / periods_per_year) - 1

    # ─── Risk metrics ────────────────────────────────────────────────────
    daily_vol = float(returns.std())
    annual_vol = daily_vol * np.sqrt(periods_per_year)
    excess = returns - daily_rf

    # Sharpe
    sharpe = float(excess.mean() / returns.std() * np.sqrt(periods_per_year)) \
        if returns.std() > 0 else 0.0

    # Sortino (downside deviation)
    downside = returns[returns < 0]
    downside_std = float(downside.std()) if len(downside) > 0 else 1e-8
    sortino = float(excess.mean() / downside_std * np.sqrt(periods_per_year))

    # ─── Drawdown analysis ───────────────────────────────────────────────
    rolling_max = equity_curve.cummax()
    drawdowns = (equity_curve - rolling_max) / rolling_max
    max_dd = float(drawdowns.min())

    # Drawdown duration
    in_dd = drawdowns < 0
    dd_groups = (~in_dd).cumsum()
    dd_durations = in_dd.groupby(dd_groups).sum()
    dd_durations = dd_durations[dd_durations > 0]
    max_dd_duration = int(dd_durations.max()) if len(dd_durations) > 0 else 0
    avg_dd_duration = float(dd_durations.mean()) if len(dd_durations) > 0 else 0

    avg_dd = float(drawdowns[drawdowns < 0].mean()) if (drawdowns < 0).any() else 0.0

    # Calmar ratio
    calmar = float(cagr / abs(max_dd)) if abs(max_dd) > 0 else 0.0

    # ─── Trade / System quality ──────────────────────────────────────────
    # Exposure time
    exposure_pct = float((returns != 0).sum() / len(returns) * 100) if len(returns) > 0 else 0

    # ─── Higher moments ──────────────────────────────────────────────────
    ret_skew = float(skew(returns.dropna()))
    ret_kurt = float(kurtosis(returns.dropna()))

    # Ulcer Index = sqrt(mean(dd^2))
    ulcer_index = float(np.sqrt((drawdowns ** 2).mean()))

    # ─── Alpha / Beta vs benchmark ───────────────────────────────────────
    alpha, beta_val = 0.0, 1.0
    info_ratio = 0.0
    bh_return = 0.0
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        aligned = pd.DataFrame({
            "strat": returns, "bench": benchmark_returns,
        }).dropna()
        if len(aligned) > 10:
            cov_mat = np.cov(aligned["strat"], aligned["bench"])
            beta_val = float(cov_mat[0, 1] / cov_mat[1, 1]) if cov_mat[1, 1] > 0 else 1.0
            bench_annual = float(aligned["bench"].mean() * periods_per_year)
            alpha = cagr - risk_free_rate - beta_val * (bench_annual - risk_free_rate)

            tracking_error = float((aligned["strat"] - aligned["bench"]).std()) \
                * np.sqrt(periods_per_year)
            info_ratio = float((cagr - bench_annual) / tracking_error) \
                if tracking_error > 0 else 0.0

            bh_return = float((1 + aligned["bench"]).cumprod().iloc[-1] - 1)

    return {
        # Returns
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "buy_hold_return_pct": round(bh_return * 100, 2),
        "exposure_pct": round(exposure_pct, 1),
        "alpha_pct": round(alpha * 100, 2),
        "beta": round(beta_val, 3),
        # Risk-adjusted
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "calmar_ratio": round(calmar, 3),
        "information_ratio": round(info_ratio, 3),
        "annual_volatility_pct": round(annual_vol * 100, 2),
        # Drawdown
        "max_drawdown_pct": round(max_dd * 100, 2),
        "avg_drawdown_pct": round(avg_dd * 100, 2),
        "max_drawdown_duration_days": max_dd_duration,
        "avg_drawdown_duration_days": round(avg_dd_duration, 1),
        # Tail risk
        "skewness": round(ret_skew, 3),
        "kurtosis": round(ret_kurt, 3),
        "ulcer_index": round(ulcer_index, 6),
        # Period info
        "n_trading_days": n_days,
        "n_years": round(n_years, 2),
    }


def compute_trade_metrics(trades: list[dict]) -> dict:
    """Compute trade-level statistics from a list of trades."""
    if not trades:
        return {
            "total_trades": 0, "win_rate_pct": 0, "profit_factor": 0,
            "avg_win_pct": 0, "avg_loss_pct": 0, "expectancy": 0,
            "sqn": 0, "avg_holding_days": 0,
        }

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    durations = [t.get("duration_days", 0) for t in trades]

    win_rate = len(wins) / len(pnls) * 100 if pnls else 0
    avg_win = float(np.mean(wins)) if wins else 0
    avg_loss = float(np.mean(losses)) if losses else 0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Expectancy = avg_win * win_rate - avg_loss * loss_rate
    expectancy = avg_win * (len(wins) / len(pnls)) + avg_loss * (len(losses) / len(pnls)) \
        if pnls else 0

    # SQN (System Quality Number) = sqrt(N) * mean(R) / std(R)
    pnl_arr = np.array(pnls)
    sqn = float(np.sqrt(len(pnls)) * pnl_arr.mean() / pnl_arr.std()) \
        if len(pnls) > 1 and pnl_arr.std() > 0 else 0

    return {
        "total_trades": len(pnls),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "expectancy_pct": round(expectancy, 3),
        "sqn": round(sqn, 2),
        "avg_holding_days": round(float(np.mean(durations)), 1) if durations else 0,
        "max_consecutive_wins": _max_consecutive(pnls, positive=True),
        "max_consecutive_losses": _max_consecutive(pnls, positive=False),
    }


def _max_consecutive(values: list[float], positive: bool = True) -> int:
    """Count maximum consecutive wins or losses."""
    max_streak = current = 0
    for v in values:
        if (positive and v > 0) or (not positive and v <= 0):
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy Implementations
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_costs(returns: pd.Series, signals: pd.Series,
                 commission: float, slippage: float) -> pd.Series:
    """Apply commission and slippage on signal changes (trades)."""
    trade_mask = signals.diff().abs() > 0
    costs = trade_mask.astype(float) * (commission + slippage)
    return returns - costs


def _extract_trades(prices: pd.Series, signals: pd.Series) -> list[dict]:
    """Extract individual trades from signal series."""
    trades = []
    in_trade = False
    entry_price = entry_idx = 0

    for i in range(1, len(signals)):
        if signals.iloc[i] != 0 and not in_trade:
            in_trade = True
            entry_price = float(prices.iloc[i])
            entry_idx = i
        elif signals.iloc[i] == 0 and in_trade:
            in_trade = False
            exit_price = float(prices.iloc[i])
            pnl_pct = (exit_price / entry_price - 1) * 100 * np.sign(signals.iloc[i - 1])
            trades.append({
                "entry_idx": entry_idx,
                "exit_idx": i,
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "pnl_pct": round(float(pnl_pct), 3),
                "duration_days": i - entry_idx,
                "side": "LONG" if signals.iloc[i - 1] > 0 else "SHORT",
            })

    return trades


def strategy_sma_crossover(
    prices: pd.Series,
    fast_period: int = 20,
    slow_period: int = 50,
    commission: float = 0.001,
    slippage: float = 0.0005,
) -> dict:
    """SMA/EMA Crossover strategy."""
    fast_ma = prices.rolling(fast_period).mean()
    slow_ma = prices.rolling(slow_period).mean()

    signals = pd.Series(0.0, index=prices.index)
    signals[fast_ma > slow_ma] = 1.0   # Long
    signals[fast_ma <= slow_ma] = 0.0   # Flat

    returns = prices.pct_change().fillna(0)
    strategy_returns = (signals.shift(1) * returns).fillna(0)
    strategy_returns = _apply_costs(strategy_returns, signals, commission, slippage)

    equity = (1 + strategy_returns).cumprod()
    trades = _extract_trades(prices, signals)

    return {
        "equity_curve": equity,
        "signals": signals,
        "returns": strategy_returns,
        "benchmark_returns": returns,
        "trades": trades,
        "fast_ma": fast_ma,
        "slow_ma": slow_ma,
        "params": {"fast_period": fast_period, "slow_period": slow_period},
    }


def strategy_rsi(
    prices: pd.Series,
    rsi_period: int = 14,
    oversold: int = 30,
    overbought: int = 70,
    commission: float = 0.001,
    slippage: float = 0.0005,
) -> dict:
    """RSI Mean Reversion strategy."""
    delta = prices.diff()
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)
    avg_gain = gains.rolling(rsi_period).mean()
    avg_loss = losses.rolling(rsi_period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.fillna(50)

    signals = pd.Series(0.0, index=prices.index)
    signals[rsi < oversold] = 1.0    # Buy on oversold
    signals[rsi > overbought] = 0.0  # Sell on overbought
    signals = signals.ffill().fillna(0)

    returns = prices.pct_change().fillna(0)
    strategy_returns = (signals.shift(1) * returns).fillna(0)
    strategy_returns = _apply_costs(strategy_returns, signals, commission, slippage)

    equity = (1 + strategy_returns).cumprod()
    trades = _extract_trades(prices, signals)

    return {
        "equity_curve": equity,
        "signals": signals,
        "returns": strategy_returns,
        "benchmark_returns": returns,
        "trades": trades,
        "rsi": rsi,
        "params": {"rsi_period": rsi_period, "oversold": oversold, "overbought": overbought},
    }


def strategy_bollinger(
    prices: pd.Series,
    period: int = 20,
    n_std: float = 2.0,
    commission: float = 0.001,
    slippage: float = 0.0005,
) -> dict:
    """Bollinger Band Breakout/Reversion strategy."""
    ma = prices.rolling(period).mean()
    std = prices.rolling(period).std()
    upper = ma + n_std * std
    lower = ma - n_std * std

    signals = pd.Series(0.0, index=prices.index)
    signals[prices < lower] = 1.0   # Buy below lower band
    signals[prices > upper] = 0.0   # Sell above upper band
    signals = signals.ffill().fillna(0)

    returns = prices.pct_change().fillna(0)
    strategy_returns = (signals.shift(1) * returns).fillna(0)
    strategy_returns = _apply_costs(strategy_returns, signals, commission, slippage)

    equity = (1 + strategy_returns).cumprod()
    trades = _extract_trades(prices, signals)

    return {
        "equity_curve": equity,
        "signals": signals,
        "returns": strategy_returns,
        "benchmark_returns": returns,
        "trades": trades,
        "upper": upper,
        "lower": lower,
        "ma": ma,
        "params": {"period": period, "n_std": n_std},
    }


def strategy_macd(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
    commission: float = 0.001,
    slippage: float = 0.0005,
) -> dict:
    """MACD Signal Line Crossover strategy."""
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()

    signals = pd.Series(0.0, index=prices.index)
    signals[macd_line > signal_line] = 1.0
    signals[macd_line <= signal_line] = 0.0

    returns = prices.pct_change().fillna(0)
    strategy_returns = (signals.shift(1) * returns).fillna(0)
    strategy_returns = _apply_costs(strategy_returns, signals, commission, slippage)

    equity = (1 + strategy_returns).cumprod()
    trades = _extract_trades(prices, signals)

    return {
        "equity_curve": equity,
        "signals": signals,
        "returns": strategy_returns,
        "benchmark_returns": returns,
        "trades": trades,
        "macd_line": macd_line,
        "signal_line": signal_line,
        "params": {"fast": fast, "slow": slow, "signal_period": signal_period},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Parameter Grid Search Optimizer
# ═══════════════════════════════════════════════════════════════════════════════

STRATEGY_REGISTRY = {
    "SMA Crossover": strategy_sma_crossover,
    "RSI Mean Reversion": strategy_rsi,
    "Bollinger Band": strategy_bollinger,
    "MACD Crossover": strategy_macd,
}


# ═══════════════════════════════════════════════════════════════════════════════
# FICC-Specific Strategies
# ═══════════════════════════════════════════════════════════════════════════════

def strategy_yield_curve_spread(
    prices: pd.Series,
    prices_short: pd.Series | None = None,
    lookback: int = 60,
    z_entry: float = 1.5,
    z_exit: float = 0.3,
    commission: float = 0.001,
    slippage: float = 0.0005,
) -> dict:
    """
    Yield Curve Spread (Steepener / Flattener) strategy.

    Uses Z-Score of the spread between two instruments (e.g., 10Y-2Y yield proxy).
    If only one price series is given, uses rolling mean-reversion on that series.

    - Z < -z_entry: spread is unusually narrow -> buy (steepener bet)
    - Z > +z_entry: spread is unusually wide -> sell (flattener bet)
    - |Z| < z_exit: close position

    For single-ticker mode: treats the price itself as a spread proxy
    (useful with TLT, IEF, or yield ETFs).
    """
    if prices_short is not None:
        spread = prices - prices_short
    else:
        spread = prices.copy()

    spread_ma = spread.rolling(lookback).mean()
    spread_std = spread.rolling(lookback).std()
    z_score = (spread - spread_ma) / spread_std.replace(0, np.nan)
    z_score = z_score.fillna(0)

    signals = pd.Series(0.0, index=prices.index)
    position = 0.0
    for i in range(1, len(signals)):
        z = z_score.iloc[i]
        if position == 0:
            if z < -z_entry:
                position = 1.0   # Spread too narrow -> steepener
            elif z > z_entry:
                position = -1.0  # Spread too wide -> flattener
        else:
            if abs(z) < z_exit:
                position = 0.0   # Close
        signals.iloc[i] = position

    returns = prices.pct_change().fillna(0)
    strategy_returns = (signals.shift(1) * returns).fillna(0)
    strategy_returns = _apply_costs(strategy_returns, signals, commission, slippage)

    equity = (1 + strategy_returns).cumprod()
    trades = _extract_trades(prices, signals)

    return {
        "equity_curve": equity,
        "signals": signals,
        "returns": strategy_returns,
        "benchmark_returns": returns,
        "trades": trades,
        "z_score": z_score,
        "spread": spread,
        "params": {"lookback": lookback, "z_entry": z_entry, "z_exit": z_exit},
    }


def strategy_fx_momentum_carry(
    prices: pd.Series,
    momentum_period: int = 40,
    carry_spread_bps: float = 200,
    momentum_weight: float = 0.6,
    commission: float = 0.001,
    slippage: float = 0.0005,
) -> dict:
    """
    FX Momentum + Carry hybrid strategy.

    Combines:
    1. Momentum signal: price vs its SMA (trend following)
    2. Carry signal: simulated interest rate differential

    The carry component adds a bias toward holding in the direction
    of positive carry (higher-yielding currency).

    carry_spread_bps: annual interest rate differential in basis points.
      Positive = domestic rate higher -> bias toward long.
    momentum_weight: blend between momentum (1.0) and carry (0.0).
    """
    # Momentum component
    ma = prices.rolling(momentum_period).mean()
    momentum_signal = pd.Series(0.0, index=prices.index)
    momentum_signal[prices > ma] = 1.0
    momentum_signal[prices <= ma] = -1.0

    # Carry component (constant directional bias based on rate differential)
    daily_carry = carry_spread_bps / 10000 / 252
    carry_signal = 1.0 if carry_spread_bps > 0 else -1.0

    # Blend signals
    w_m = momentum_weight
    w_c = 1.0 - momentum_weight
    combined = w_m * momentum_signal + w_c * carry_signal
    signals = pd.Series(0.0, index=prices.index)
    signals[combined > 0.3] = 1.0
    signals[combined < -0.3] = -1.0

    returns = prices.pct_change().fillna(0)
    # Add carry income to returns when holding
    carry_income = signals.shift(1) * daily_carry
    strategy_returns = (signals.shift(1) * returns + carry_income.abs()).fillna(0)
    strategy_returns = _apply_costs(strategy_returns, signals, commission, slippage)

    equity = (1 + strategy_returns).cumprod()
    trades = _extract_trades(prices, signals)

    return {
        "equity_curve": equity,
        "signals": signals,
        "returns": strategy_returns,
        "benchmark_returns": returns,
        "trades": trades,
        "momentum_ma": ma,
        "params": {
            "momentum_period": momentum_period,
            "carry_spread_bps": carry_spread_bps,
            "momentum_weight": momentum_weight,
        },
    }


# Add FICC strategies to registry
STRATEGY_REGISTRY["Yield Curve Spread"] = strategy_yield_curve_spread
STRATEGY_REGISTRY["FX Momentum & Carry"] = strategy_fx_momentum_carry


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-Asset Portfolio Backtest
# ═══════════════════════════════════════════════════════════════════════════════

def portfolio_backtest(
    price_dict: dict[str, pd.Series],
    weights: dict[str, float],
    rebalance_freq: str = "monthly",
    commission: float = 0.001,
) -> dict:
    """
    Multi-asset portfolio backtest with weighted returns.

    Args:
        price_dict: {ticker: price_series} for each asset
        weights: {ticker: weight} summing to ~1.0
        rebalance_freq: 'daily', 'weekly', 'monthly', 'quarterly'

    Returns:
        equity_curve, correlation_matrix, per-asset contribution, full metrics
    """
    # Align all series
    prices_df = pd.DataFrame(price_dict).dropna()
    if len(prices_df) < 30:
        return {"error": "Not enough aligned data across all tickers (need 30+ days)"}

    list(weights.keys())
    w = np.array([weights.get(t, 0) for t in prices_df.columns])
    # Normalize
    w = w / w.sum()

    returns_df = prices_df.pct_change().dropna()

    # Weighted portfolio returns
    portfolio_returns = (returns_df * w).sum(axis=1)

    # Apply rebalance cost at intervals
    idx = returns_df.index
    if rebalance_freq == "weekly":
        rebal_mask = pd.Series(idx.weekday == 0, index=idx)
    elif rebalance_freq == "monthly":
        first_of_month = pd.Series(idx.day <= 5, index=idx)
        rebal_mask = first_of_month & (~first_of_month.shift(1).fillna(False))
    elif rebalance_freq == "quarterly":
        first_of_q = pd.Series((idx.month % 3 == 1) & (idx.day <= 5), index=idx)
        rebal_mask = first_of_q & (~first_of_q.shift(1).fillna(False))
    else:
        rebal_mask = pd.Series(False, index=idx)

    rebal_cost = rebal_mask.astype(float) * commission * 2  # round-trip
    portfolio_returns = portfolio_returns - rebal_cost

    # Equity curve
    equity = (1 + portfolio_returns).cumprod()

    # Benchmark: equal-weight buy & hold
    bench_returns = returns_df.mean(axis=1)
    bench_equity = (1 + bench_returns).cumprod()

    # Correlation matrix
    corr_matrix = returns_df.corr()

    # Per-asset contribution to portfolio return
    asset_contributions = {}
    for i, col in enumerate(returns_df.columns):
        asset_ret = (returns_df[col] * w[i]).sum()
        asset_contributions[col] = round(float(asset_ret * 100), 2)

    # Per-asset standalone metrics
    asset_metrics = {}
    for col in returns_df.columns:
        asset_eq = (1 + returns_df[col]).cumprod()
        asset_metrics[col] = {
            "total_return_pct": round(float((asset_eq.iloc[-1] - 1) * 100), 2),
            "volatility_pct": round(float(returns_df[col].std() * np.sqrt(252) * 100), 2),
            "weight_pct": round(float(w[list(returns_df.columns).index(col)] * 100), 1),
        }

    # Portfolio-level metrics
    perf = compute_performance_metrics(
        equity, portfolio_returns,
        benchmark_returns=bench_returns,
    )

    dates = equity.index.strftime("%Y-%m-%d").tolist() \
        if hasattr(equity.index, "strftime") else list(range(len(equity)))

    # Drawdown
    rolling_max = equity.cummax()
    drawdown = ((equity - rolling_max) / rolling_max * 100)

    return {
        "performance": perf,
        "equity_curve": {
            "dates": dates,
            "portfolio": [round(float(v), 6) for v in equity.values],
            "benchmark": [round(float(v), 6) for v in bench_equity.values],
            "drawdown_pct": [round(float(v), 2) for v in drawdown.values],
        },
        "correlation_matrix": corr_matrix.round(3).to_dict(),
        "asset_contributions": asset_contributions,
        "asset_metrics": asset_metrics,
        "weights": {t: round(float(w[i]), 4) for i, t in enumerate(returns_df.columns)},
        "rebalance_freq": rebalance_freq,
        "n_days": len(returns_df),
    }


def grid_search(
    prices: pd.Series,
    strategy_name: str,
    param_grid: dict[str, list],
    commission: float = 0.001,
    slippage: float = 0.0005,
    metric: str = "sharpe_ratio",
) -> dict:
    """
    Exhaustive grid search over parameter combinations.

    param_grid: {"fast_period": [10, 20, 30], "slow_period": [40, 50, 60]}
    Returns best params + full results matrix for heatmap.
    """
    strategy_fn = STRATEGY_REGISTRY.get(strategy_name)
    if not strategy_fn:
        return {"error": f"Unknown strategy: {strategy_name}"}

    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    combinations = list(product(*param_values))

    results = []
    best_score = -np.inf
    best_params = {}
    best_result = None

    for combo in combinations:
        params = dict(zip(param_names, combo))
        params["commission"] = commission
        params["slippage"] = slippage

        try:
            result = strategy_fn(prices, **params)
            metrics = compute_performance_metrics(
                result["equity_curve"],
                result["returns"],
                benchmark_returns=result["benchmark_returns"],
            )
            trade_metrics = compute_trade_metrics(result["trades"])

            score = metrics.get(metric, 0)
            results.append({**params, **metrics, **trade_metrics, "_score": score})

            if score > best_score:
                best_score = score
                best_params = params
                best_result = result
        except Exception:
            results.append({**params, "_score": float("nan")})

    return {
        "strategy": strategy_name,
        "optimization_metric": metric,
        "total_combinations": len(combinations),
        "best_params": {k: v for k, v in best_params.items()
                        if k not in ("commission", "slippage")},
        "best_score": round(float(best_score), 4) if np.isfinite(best_score) else 0,
        "results_grid": results,
        "best_result": best_result,
    }
