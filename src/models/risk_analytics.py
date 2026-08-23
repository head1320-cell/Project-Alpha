"""
Advanced Risk Analytics
========================
Institutional-grade risk tools.

Features:
  - Holding-Period scaled VaR and ES (sqrt-T rule)
  - Monte Carlo GBM path simulation (spaghetti plot data)
  - Rolling Sharpe Ratio & Rolling Correlation
  - Detailed drawdown analysis (duration, recovery)
"""


import numpy as np
import pandas as pd
from scipy.stats import norm

# ═══════════════════════════════════════════════════════════════════════════════
# Holding-Period Scaled VaR & ES
# ═══════════════════════════════════════════════════════════════════════════════

def holding_period_var_es(
    returns: pd.Series,
    holding_periods: list[int] = None,
    confidence_levels: list[float] = None,
    portfolio_value: float = 100_000_000,
    method: str = "parametric",
) -> dict:
    """
    Compute VaR and ES scaled by holding period using sqrt(T) rule.

    VaR(T) = VaR(1D) * sqrt(T)
    ES(T)  = ES(1D)  * sqrt(T)

    Methods: 'parametric' (Gaussian) or 'historical'.
    """
    if confidence_levels is None:
        confidence_levels = [0.95, 0.99]
    if holding_periods is None:
        holding_periods = [1, 5, 10, 20]
    mu = float(returns.mean())
    sigma = float(returns.std())
    results = []

    for cl in confidence_levels:
        for T in holding_periods:
            sqrt_t = np.sqrt(T)

            if method == "parametric":
                z = norm.ppf(cl)
                var_1d = z * sigma - mu
                alpha = 1 - cl
                z_alpha = norm.ppf(alpha)
                es_1d = -mu + sigma * norm.pdf(z_alpha) / alpha
            else:
                var_1d = float(-np.percentile(returns, (1 - cl) * 100))
                tail = returns[returns <= -var_1d]
                es_1d = float(-tail.mean()) if len(tail) > 0 else var_1d

            var_t = max(var_1d * sqrt_t, 0)
            es_t = max(es_1d * sqrt_t, 0)

            results.append({
                "confidence_level": cl,
                "holding_period_days": T,
                "var_pct": round(var_t * 100, 4),
                "es_pct": round(es_t * 100, 4),
                "var_amount": round(var_t * portfolio_value, 0),
                "es_amount": round(es_t * portfolio_value, 0),
                "method": method,
            })

    return {
        "results": results,
        "daily_stats": {
            "mean_return": round(mu * 100, 6),
            "daily_volatility": round(sigma * 100, 4),
            "annual_volatility": round(sigma * np.sqrt(252) * 100, 2),
            "n_observations": len(returns),
        },
        "portfolio_value": portfolio_value,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Monte Carlo Path Simulation (GBM)
# ═══════════════════════════════════════════════════════════════════════════════

def mc_path_simulation(
    returns: pd.Series,
    n_paths: int = 500,
    n_days: int = 252,
    initial_price: float = 100.0,
    seed: int = 42,
) -> dict:
    """
    Simulate future price paths using Geometric Brownian Motion.

    dS/S = mu*dt + sigma*dW

    Returns path data for spaghetti plot + worst 5% paths highlighted.
    """
    np.random.seed(seed)
    mu = float(returns.mean())
    sigma = float(returns.std())

    dt = 1.0
    paths = np.zeros((n_paths, n_days + 1))
    paths[:, 0] = initial_price

    for i in range(n_paths):
        z = np.random.standard_normal(n_days)
        for t in range(1, n_days + 1):
            paths[i, t] = paths[i, t - 1] * np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z[t - 1])

    # Final prices
    final_prices = paths[:, -1]
    worst_5pct_threshold = np.percentile(final_prices, 5)
    worst_mask = final_prices <= worst_5pct_threshold
    median_path_idx = int(np.argsort(final_prices)[n_paths // 2])

    # Sample paths for visualization (max 100 for performance)
    sample_n = min(100, n_paths)
    sample_indices = np.random.choice(n_paths, sample_n, replace=False)

    sampled_paths = []
    for idx in sample_indices:
        is_worst = bool(worst_mask[idx])
        sampled_paths.append({
            "path_id": int(idx),
            "values": [round(float(v), 2) for v in paths[idx]],
            "is_worst_5pct": is_worst,
            "final_price": round(float(paths[idx, -1]), 2),
        })

    # Median path
    median_path = [round(float(v), 2) for v in paths[median_path_idx]]

    # Percentile bands
    p5 = [round(float(v), 2) for v in np.percentile(paths, 5, axis=0)]
    p25 = [round(float(v), 2) for v in np.percentile(paths, 25, axis=0)]
    p50 = [round(float(v), 2) for v in np.percentile(paths, 50, axis=0)]
    p75 = [round(float(v), 2) for v in np.percentile(paths, 75, axis=0)]
    p95 = [round(float(v), 2) for v in np.percentile(paths, 95, axis=0)]

    return {
        "n_paths": n_paths,
        "n_days": n_days,
        "initial_price": initial_price,
        "sampled_paths": sampled_paths,
        "median_path": median_path,
        "percentile_bands": {
            "p5": p5, "p25": p25, "p50": p50, "p75": p75, "p95": p95,
        },
        "final_price_stats": {
            "mean": round(float(final_prices.mean()), 2),
            "median": round(float(np.median(final_prices)), 2),
            "p5": round(float(np.percentile(final_prices, 5)), 2),
            "p95": round(float(np.percentile(final_prices, 95)), 2),
            "worst": round(float(final_prices.min()), 2),
            "best": round(float(final_prices.max()), 2),
        },
        "gbm_params": {
            "mu_daily": round(mu, 6),
            "sigma_daily": round(sigma, 6),
            "mu_annual": round(mu * 252, 4),
            "sigma_annual": round(sigma * np.sqrt(252), 4),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Rolling Statistics
# ═══════════════════════════════════════════════════════════════════════════════

def rolling_sharpe(
    returns: pd.Series,
    window: int = 252,
    risk_free_rate: float = 0.03,
) -> dict:
    """Compute rolling Sharpe ratio over a window."""
    daily_rf = (1 + risk_free_rate) ** (1 / 252) - 1
    excess = returns - daily_rf

    rolling_mean = excess.rolling(window).mean()
    rolling_std = returns.rolling(window).std()
    rolling_sh = (rolling_mean / rolling_std * np.sqrt(252)).dropna()

    dates = rolling_sh.index.strftime("%Y-%m-%d").tolist() \
        if hasattr(rolling_sh.index, "strftime") else list(range(len(rolling_sh)))

    return {
        "dates": dates,
        "values": [round(float(v), 4) for v in rolling_sh.values],
        "window": window,
        "current": round(float(rolling_sh.iloc[-1]), 4) if len(rolling_sh) > 0 else 0,
        "mean": round(float(rolling_sh.mean()), 4),
        "min": round(float(rolling_sh.min()), 4),
        "max": round(float(rolling_sh.max()), 4),
    }


def rolling_correlation(
    returns_a: pd.Series,
    returns_b: pd.Series,
    window: int = 60,
) -> dict:
    """Compute rolling correlation between two return series."""
    aligned = pd.DataFrame({"a": returns_a, "b": returns_b}).dropna()
    roll_corr = aligned["a"].rolling(window).corr(aligned["b"]).dropna()

    dates = roll_corr.index.strftime("%Y-%m-%d").tolist() \
        if hasattr(roll_corr.index, "strftime") else list(range(len(roll_corr)))

    return {
        "dates": dates,
        "values": [round(float(v), 4) for v in roll_corr.values],
        "window": window,
        "current": round(float(roll_corr.iloc[-1]), 4) if len(roll_corr) > 0 else 0,
        "mean": round(float(roll_corr.mean()), 4),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Detailed Drawdown Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def drawdown_analysis(equity_curve: pd.Series) -> dict:
    """
    Detailed drawdown statistics: each drawdown event with
    depth, duration, and recovery time.
    """
    rolling_max = equity_curve.cummax()
    drawdowns = (equity_curve - rolling_max) / rolling_max

    # Identify individual drawdown events
    in_dd = drawdowns < -1e-8
    events = []
    current_start = None
    trough_val = 0
    trough_idx = None

    for i in range(len(drawdowns)):
        if in_dd.iloc[i]:
            if current_start is None:
                current_start = i
                float(rolling_max.iloc[i])
                trough_val = float(drawdowns.iloc[i])
                trough_idx = i
            elif float(drawdowns.iloc[i]) < trough_val:
                trough_val = float(drawdowns.iloc[i])
                trough_idx = i
        else:
            if current_start is not None:
                recovery_idx = i
                duration = trough_idx - current_start
                recovery_time = recovery_idx - trough_idx

                start_date = equity_curve.index[current_start]
                trough_date = equity_curve.index[trough_idx]
                recovery_date = equity_curve.index[recovery_idx]

                events.append({
                    "start_date": str(start_date)[:10],
                    "trough_date": str(trough_date)[:10],
                    "recovery_date": str(recovery_date)[:10],
                    "depth_pct": round(trough_val * 100, 2),
                    "duration_to_trough_days": int(duration),
                    "recovery_days": int(recovery_time),
                    "total_days": int(recovery_idx - current_start),
                })
                current_start = None

    # If still in drawdown at end
    if current_start is not None:
        events.append({
            "start_date": str(equity_curve.index[current_start])[:10],
            "trough_date": str(equity_curve.index[trough_idx])[:10],
            "recovery_date": "ongoing",
            "depth_pct": round(trough_val * 100, 2),
            "duration_to_trough_days": int(trough_idx - current_start),
            "recovery_days": None,
            "total_days": int(len(equity_curve) - 1 - current_start),
        })

    # Sort by depth
    events.sort(key=lambda x: x["depth_pct"])

    # Drawdown series for plotting
    dates = drawdowns.index.strftime("%Y-%m-%d").tolist() \
        if hasattr(drawdowns.index, "strftime") else list(range(len(drawdowns)))

    return {
        "drawdown_series": {
            "dates": dates,
            "values": [round(float(v) * 100, 2) for v in drawdowns.values],
        },
        "events": events[:20],  # Top 20 worst
        "summary": {
            "max_drawdown_pct": round(float(drawdowns.min()) * 100, 2),
            "avg_drawdown_pct": round(float(drawdowns[drawdowns < 0].mean()) * 100, 2)
                if (drawdowns < 0).any() else 0,
            "n_drawdown_events": len(events),
            "avg_duration_days": round(float(np.mean([e["total_days"] for e in events])), 1)
                if events else 0,
            "avg_recovery_days": round(float(np.mean(
                [e["recovery_days"] for e in events if e["recovery_days"] is not None]
            )), 1) if any(e["recovery_days"] is not None for e in events) else None,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Monthly Returns Heatmap Data
# ═══════════════════════════════════════════════════════════════════════════════

def monthly_returns_heatmap(returns: pd.Series) -> dict:
    """
    Compute monthly returns for heatmap visualization.
    Returns a matrix [year x month] of monthly return percentages.
    """
    if not hasattr(returns.index, "year"):
        return {"error": "Returns must have datetime index"}

    monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    monthly_df = pd.DataFrame({
        "year": monthly.index.year,
        "month": monthly.index.month,
        "return_pct": (monthly * 100).round(2),
    })

    # Pivot to year x month matrix
    pivot = monthly_df.pivot(index="year", columns="month", values="return_pct")
    pivot.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    # Annual totals
    annual = returns.resample("YE").apply(lambda x: (1 + x).prod() - 1)
    pivot["Annual"] = (annual.values * 100).round(2) if len(annual) == len(pivot) else np.nan

    return {
        "years": [int(y) for y in pivot.index],
        "months": list(pivot.columns),
        "data": pivot.fillna(0).values.tolist(),
        "raw": pivot.to_dict("index"),
    }
