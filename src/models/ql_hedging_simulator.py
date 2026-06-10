"""
Dynamic Delta Hedging Simulator
=================================
Simulates a trading desk's delta hedging P&L over time.

Features:
  - Time-shifting engine (day-by-day evaluation)
  - Daily rebalancing with spot price injection
  - Friction costs (commission + slippage)
  - PnL Attribution: Theta vs Gamma vs Vega vs Transaction costs
  - Hedging error analysis
"""


import numpy as np
from scipy.stats import norm


def _bs_price(S, K, T, r, q, sigma, option_type="call"):
    """Quick BSM price."""
    if T <= 0:
        return max(S - K, 0) if option_type == "call" else max(K - S, 0)
    d1 = (np.log(S/K) + (r - q + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    if option_type == "call":
        return S*np.exp(-q*T)*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*np.exp(-q*T)*norm.cdf(-d1)


def _bs_delta(S, K, T, r, q, sigma, option_type="call"):
    """BSM delta."""
    if T <= 0:
        return 1.0 if (option_type == "call" and S > K) else \
               -1.0 if (option_type == "put" and K > S) else 0.0
    d1 = (np.log(S/K) + (r - q + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    if option_type == "call":
        return np.exp(-q*T) * norm.cdf(d1)
    return np.exp(-q*T) * (norm.cdf(d1) - 1)


def _bs_gamma(S, K, T, r, q, sigma):
    """BSM gamma."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (np.log(S/K) + (r - q + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    return np.exp(-q*T) * norm.pdf(d1) / (S * sigma * np.sqrt(T))


def _bs_theta(S, K, T, r, q, sigma, option_type="call"):
    """BSM theta (per day)."""
    if T <= 0:
        return 0.0
    d1 = (np.log(S/K) + (r - q + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    term1 = -S * sigma * np.exp(-q*T) * norm.pdf(d1) / (2*np.sqrt(T))
    if option_type == "call":
        return (term1 + q*S*np.exp(-q*T)*norm.cdf(d1) - r*K*np.exp(-r*T)*norm.cdf(d2)) / 365
    return (term1 - q*S*np.exp(-q*T)*norm.cdf(-d1) + r*K*np.exp(-r*T)*norm.cdf(-d2)) / 365


def simulate_delta_hedge(
    spot_prices: list[float],
    K: float,
    T: float,
    r: float,
    q: float = 0.0,
    sigma: float = 0.20,
    option_type: str = "call",
    position_size: float = 1.0,
    commission_pct: float = 0.001,
    slippage_pct: float = 0.0005,
    rebalance_freq: int = 1,
) -> dict:
    """
    Simulate dynamic delta hedging over a series of spot prices.

    Args:
        spot_prices: daily spot price series (entry to maturity)
        K: strike price
        T: original time to maturity (years)
        r: risk-free rate
        q: dividend yield
        sigma: implied volatility used for hedging
        option_type: 'call' or 'put'
        position_size: number of options sold (negative = short)
        commission_pct: per-trade commission
        slippage_pct: per-trade slippage
        rebalance_freq: rebalance every N days (1 = daily)

    Returns:
        Detailed daily P&L, Greeks trajectory, hedging error, attribution.
    """
    n_days = len(spot_prices)
    dt = T / max(n_days - 1, 1)

    # Initialize
    initial_price = _bs_price(spot_prices[0], K, T, r, q, sigma, option_type)
    initial_price * position_size  # Premium received (if short)

    # Daily tracking
    daily_records = []
    cumulative_hedge_pnl = 0.0
    cumulative_costs = 0.0
    current_shares = 0.0
    -initial_price * position_size  # Short option: receive premium

    # PnL attribution accumulators
    theta_pnl = 0.0
    gamma_pnl = 0.0
    unexplained_pnl = 0.0
    prev_opt_val = 0.0  # 전일 옵션가 (day 0에서 초기화, day>0에서 PnL 계산에 사용)

    for day in range(n_days):
        S = spot_prices[day]
        remaining_T = max(T - day * dt, 0.0)

        # Compute option value and Greeks
        opt_val = _bs_price(S, K, remaining_T, r, q, sigma, option_type)
        delta = _bs_delta(S, K, remaining_T, r, q, sigma, option_type)
        gamma = _bs_gamma(S, K, remaining_T, r, q, sigma)
        theta = _bs_theta(S, K, remaining_T, r, q, sigma, option_type)

        # Target hedge position
        target_shares = -delta * position_size

        # Rebalance check
        should_rebalance = (day == 0) or (day % rebalance_freq == 0) or (day == n_days - 1)
        trade_shares = 0.0
        trade_cost = 0.0

        if should_rebalance:
            trade_shares = target_shares - current_shares
            trade_notional = abs(trade_shares * S)
            trade_cost = trade_notional * (commission_pct + slippage_pct)
            current_shares = target_shares
            cumulative_costs += trade_cost

        # Daily PnL components
        if day > 0:
            dS = spot_prices[day] - spot_prices[day - 1]
            # Hedge PnL: shares held * price change
            hedge_daily = current_shares * dS if day > 0 else 0
            # Option PnL: change in option value (we are short)
            option_daily = -(opt_val - prev_opt_val) * position_size
            # Net PnL
            net_daily = hedge_daily + option_daily - trade_cost

            # PnL Attribution (Taylor expansion)
            # dV ≈ Delta*dS + 0.5*Gamma*dS^2 + Theta*dt
            theta_component = theta * position_size
            gamma_component = 0.5 * gamma * dS**2 * position_size
            delta * dS * position_size
            residual = net_daily - (theta_component + gamma_component)

            theta_pnl += theta_component
            gamma_pnl += gamma_component
            unexplained_pnl += residual
            cumulative_hedge_pnl += net_daily
        else:
            hedge_daily = 0
            option_daily = 0
            net_daily = 0

        prev_opt_val = opt_val

        daily_records.append({
            "day": day,
            "spot": round(S, 2),
            "remaining_T": round(remaining_T, 4),
            "option_value": round(opt_val, 4),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "shares_held": round(current_shares, 2),
            "trade_shares": round(trade_shares, 2),
            "trade_cost": round(trade_cost, 4),
            "daily_pnl": round(net_daily, 4),
            "cumulative_pnl": round(cumulative_hedge_pnl, 4),
        })

    # Final settlement
    final_S = spot_prices[-1]
    if option_type == "call":
        intrinsic = max(final_S - K, 0)
    else:
        intrinsic = max(K - final_S, 0)

    final_option_payout = intrinsic * position_size
    total_pnl = initial_price * position_size - final_option_payout + cumulative_hedge_pnl - cumulative_costs

    # Hedging error
    hedging_error = total_pnl

    return {
        "initial_premium": round(initial_price * position_size, 4),
        "final_payout": round(final_option_payout, 4),
        "hedge_pnl": round(cumulative_hedge_pnl, 4),
        "total_costs": round(cumulative_costs, 4),
        "total_pnl": round(total_pnl, 4),
        "hedging_error": round(hedging_error, 4),
        "pnl_attribution": {
            "premium_received": round(initial_price * position_size, 4),
            "theta_pnl": round(theta_pnl, 4),
            "gamma_pnl": round(gamma_pnl, 4),
            "unexplained": round(unexplained_pnl, 4),
            "transaction_costs": round(-cumulative_costs, 4),
            "option_payout": round(-final_option_payout, 4),
        },
        "daily_records": daily_records,
        "params": {
            "K": K, "T": T, "r": r, "q": q, "sigma": sigma,
            "option_type": option_type, "position_size": position_size,
            "n_days": n_days, "rebalance_freq": rebalance_freq,
        },
    }
