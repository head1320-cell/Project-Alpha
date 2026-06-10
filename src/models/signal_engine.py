"""
Multi-Condition Signal Engine
==============================
TradingView-grade signal combiner with advanced exit logic.

Features:
  - Combine 2-3 indicators with AND/OR logic
  - Trailing Stop, Take Profit / Stop Loss, Time-based Exit
  - Vectorized signal generation (no loops where possible)
  - Educational tooltips for each strategy

Indicators supported:
  SMA, EMA, RSI, MACD, Bollinger Band, ATR, Stochastic
"""


import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════════
# Indicator Library
# ═══════════════════════════════════════════════════════════════════════════════

def calc_sma(prices: pd.Series, period: int) -> pd.Series:
    return prices.rolling(period).mean()

def calc_ema(prices: pd.Series, period: int) -> pd.Series:
    return prices.ewm(span=period, adjust=False).mean()

def calc_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gains = delta.where(delta > 0, 0.0).rolling(period).mean()
    losses = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gains / losses.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)

def calc_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_f = prices.ewm(span=fast, adjust=False).mean()
    ema_s = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_f - ema_s
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line

def calc_bollinger(prices: pd.Series, period: int = 20, n_std: float = 2.0):
    ma = prices.rolling(period).mean()
    std = prices.rolling(period).std()
    return ma, ma + n_std * std, ma - n_std * std

def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_stochastic(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    h_max = high.rolling(period).max()
    l_min = low.rolling(period).min()
    return (100 * (close - l_min) / (h_max - l_min).replace(0, np.nan)).fillna(50)


# ═══════════════════════════════════════════════════════════════════════════════
# Condition Evaluator
# ═══════════════════════════════════════════════════════════════════════════════

CONDITION_REGISTRY = {
    "SMA Cross Up":     {"desc": "Fast SMA crosses above Slow SMA (Golden Cross)",
                         "params": ["fast_period", "slow_period"],
                         "tickers": "SPY, QQQ, 005930.KS"},
    "SMA Cross Down":   {"desc": "Fast SMA crosses below Slow SMA (Death Cross)",
                         "params": ["fast_period", "slow_period"],
                         "tickers": "SPY, QQQ, 005930.KS"},
    "RSI Oversold":     {"desc": "RSI drops below threshold — mean reversion buy",
                         "params": ["rsi_period", "rsi_threshold"],
                         "tickers": "Any equity, ETF, or FX pair"},
    "RSI Overbought":   {"desc": "RSI rises above threshold — mean reversion sell",
                         "params": ["rsi_period", "rsi_threshold"],
                         "tickers": "Any equity, ETF, or FX pair"},
    "MACD Bullish":     {"desc": "MACD line crosses above signal line",
                         "params": ["macd_fast", "macd_slow", "macd_signal"],
                         "tickers": "AAPL, NVDA, BTC-USD"},
    "MACD Bearish":     {"desc": "MACD line crosses below signal line",
                         "params": ["macd_fast", "macd_slow", "macd_signal"],
                         "tickers": "AAPL, NVDA, BTC-USD"},
    "Price Above BB":   {"desc": "Price above upper Bollinger Band — breakout / overbought",
                         "params": ["bb_period", "bb_std"],
                         "tickers": "High-vol assets: TSLA, BTC-USD"},
    "Price Below BB":   {"desc": "Price below lower Bollinger Band — oversold reversion",
                         "params": ["bb_period", "bb_std"],
                         "tickers": "High-vol assets: TSLA, BTC-USD"},
    "Price > EMA":      {"desc": "Price above EMA — trend confirmation",
                         "params": ["ema_period"],
                         "tickers": "Any trending asset"},
    "Price < EMA":      {"desc": "Price below EMA — downtrend confirmation",
                         "params": ["ema_period"],
                         "tickers": "Any trending asset"},
}


def evaluate_condition(
    prices: pd.Series,
    condition_name: str,
    params: dict,
    ohlcv: pd.DataFrame | None = None,
) -> pd.Series:
    """
    Evaluate a single condition and return a boolean Series.
    True = condition is met.
    """
    len(prices)
    result = pd.Series(False, index=prices.index)

    if condition_name == "SMA Cross Up":
        fast = calc_sma(prices, params.get("fast_period", 20))
        slow = calc_sma(prices, params.get("slow_period", 50))
        result = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        # Stay true while fast > slow
        result = (fast > slow)

    elif condition_name == "SMA Cross Down":
        fast = calc_sma(prices, params.get("fast_period", 20))
        slow = calc_sma(prices, params.get("slow_period", 50))
        result = (fast < slow)

    elif condition_name == "RSI Oversold":
        rsi = calc_rsi(prices, params.get("rsi_period", 14))
        result = rsi < params.get("rsi_threshold", 30)

    elif condition_name == "RSI Overbought":
        rsi = calc_rsi(prices, params.get("rsi_period", 14))
        result = rsi > params.get("rsi_threshold", 70)

    elif condition_name == "MACD Bullish":
        macd_l, sig_l, _ = calc_macd(
            prices, params.get("macd_fast", 12),
            params.get("macd_slow", 26), params.get("macd_signal", 9),
        )
        result = macd_l > sig_l

    elif condition_name == "MACD Bearish":
        macd_l, sig_l, _ = calc_macd(
            prices, params.get("macd_fast", 12),
            params.get("macd_slow", 26), params.get("macd_signal", 9),
        )
        result = macd_l < sig_l

    elif condition_name == "Price Above BB":
        _, upper, _ = calc_bollinger(
            prices, params.get("bb_period", 20), params.get("bb_std", 2.0),
        )
        result = prices > upper

    elif condition_name == "Price Below BB":
        _, _, lower = calc_bollinger(
            prices, params.get("bb_period", 20), params.get("bb_std", 2.0),
        )
        result = prices < lower

    elif condition_name == "Price > EMA":
        ema = calc_ema(prices, params.get("ema_period", 20))
        result = prices > ema

    elif condition_name == "Price < EMA":
        ema = calc_ema(prices, params.get("ema_period", 20))
        result = prices < ema

    return result.fillna(False)


def combine_conditions(
    prices: pd.Series,
    conditions: list[dict],
    logic: str = "AND",
) -> pd.Series:
    """
    Combine multiple conditions with AND/OR logic.

    conditions: [{"name": "SMA Cross Up", "params": {...}}, ...]
    logic: "AND" or "OR"
    """
    if not conditions:
        return pd.Series(True, index=prices.index)

    signals = []
    for cond in conditions:
        sig = evaluate_condition(prices, cond["name"], cond.get("params", {}))
        signals.append(sig)

    combined = signals[0]
    for sig in signals[1:]:
        if logic == "AND":
            combined = combined & sig
        else:
            combined = combined | sig

    return combined


# ═══════════════════════════════════════════════════════════════════════════════
# Advanced Exit Logic
# ═══════════════════════════════════════════════════════════════════════════════

def apply_advanced_exits(
    prices: pd.Series,
    entry_signals: pd.Series,
    trailing_stop_pct: float | None = None,
    take_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    time_exit_days: int | None = None,
) -> pd.Series:
    """
    Apply advanced exit logic to entry signals.

    Returns: position series (1 = long, 0 = flat)
    """
    position = pd.Series(0.0, index=prices.index)
    in_trade = False
    entry_price = 0.0
    entry_day = 0
    peak_price = 0.0

    for i in range(len(prices)):
        price = float(prices.iloc[i])

        if not in_trade:
            if bool(entry_signals.iloc[i]):
                in_trade = True
                entry_price = price
                peak_price = price
                entry_day = i
                position.iloc[i] = 1.0
        else:
            # Update trailing peak
            if price > peak_price:
                peak_price = price

            exit_triggered = False

            # Trailing stop
            if trailing_stop_pct is not None and trailing_stop_pct > 0:
                drawdown_from_peak = (peak_price - price) / peak_price
                if drawdown_from_peak >= trailing_stop_pct / 100:
                    exit_triggered = True

            # Take profit
            if take_profit_pct is not None and take_profit_pct > 0:
                gain = (price - entry_price) / entry_price
                if gain >= take_profit_pct / 100:
                    exit_triggered = True

            # Stop loss
            if stop_loss_pct is not None and stop_loss_pct > 0:
                loss = (entry_price - price) / entry_price
                if loss >= stop_loss_pct / 100:
                    exit_triggered = True

            # Time exit
            if time_exit_days is not None and time_exit_days > 0:
                if (i - entry_day) >= time_exit_days:
                    exit_triggered = True

            if exit_triggered:
                in_trade = False
                position.iloc[i] = 0.0
            else:
                position.iloc[i] = 1.0

    return position


# ═══════════════════════════════════════════════════════════════════════════════
# Full Multi-Condition Backtest
# ═══════════════════════════════════════════════════════════════════════════════

def multi_condition_backtest(
    prices: pd.Series,
    entry_conditions: list[dict],
    entry_logic: str = "AND",
    exit_conditions: list[dict] | None = None,
    exit_logic: str = "OR",
    trailing_stop_pct: float | None = None,
    take_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    time_exit_days: int | None = None,
    commission: float = 0.001,
    slippage: float = 0.0005,
) -> dict:
    """
    Full multi-condition backtest with advanced exits.

    Entry: combine entry_conditions with entry_logic
    Exit: combine exit_conditions with exit_logic + trailing/TP/SL/time
    """
    # Generate entry signals
    entry_signal = combine_conditions(prices, entry_conditions, entry_logic)

    # Generate exit signals (if defined)
    if exit_conditions:
        exit_signal = combine_conditions(prices, exit_conditions, exit_logic)
        # Entry where entry=True AND exit=False
        raw_signal = entry_signal & (~exit_signal)
    else:
        raw_signal = entry_signal

    # Apply advanced exit logic
    has_advanced = any(x is not None and x > 0 for x in
                       [trailing_stop_pct, take_profit_pct, stop_loss_pct, time_exit_days])

    if has_advanced:
        position = apply_advanced_exits(
            prices, raw_signal,
            trailing_stop_pct=trailing_stop_pct,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            time_exit_days=time_exit_days,
        )
    else:
        position = raw_signal.astype(float)

    # Compute returns
    returns = prices.pct_change().fillna(0)
    strategy_returns = (position.shift(1) * returns).fillna(0)

    # Apply costs on trade entries/exits
    trade_mask = position.diff().abs() > 0
    costs = trade_mask.astype(float) * (commission + slippage)
    strategy_returns = strategy_returns - costs

    equity = (1 + strategy_returns).cumprod()

    # Extract trades
    trades = []
    in_trade = False
    entry_price = entry_idx = 0
    for i in range(1, len(position)):
        if position.iloc[i] == 1 and position.iloc[i - 1] == 0:
            in_trade = True
            entry_price = float(prices.iloc[i])
            entry_idx = i
        elif position.iloc[i] == 0 and position.iloc[i - 1] == 1:
            if in_trade:
                exit_price = float(prices.iloc[i])
                pnl = (exit_price / entry_price - 1) * 100
                trades.append({
                    "entry_idx": entry_idx, "exit_idx": i,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "pnl_pct": round(float(pnl), 3),
                    "duration_days": i - entry_idx,
                    "side": "LONG",
                })
                in_trade = False

    return {
        "equity_curve": equity,
        "position": position,
        "returns": strategy_returns,
        "benchmark_returns": returns,
        "trades": trades,
        "entry_conditions": [c["name"] for c in entry_conditions],
        "exit_conditions": [c["name"] for c in (exit_conditions or [])],
        "exit_params": {
            "trailing_stop_pct": trailing_stop_pct,
            "take_profit_pct": take_profit_pct,
            "stop_loss_pct": stop_loss_pct,
            "time_exit_days": time_exit_days,
        },
    }
