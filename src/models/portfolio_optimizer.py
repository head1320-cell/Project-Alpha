"""
Portfolio Optimizer — Markowitz Efficient Frontier & Ranking
=============================================================
GenPort-grade asset allocation engine.

Features:
  - Markowitz Efficient Frontier via Monte Carlo
  - Max Sharpe Ratio portfolio
  - Min Volatility portfolio
  - Momentum / Volatility ranking filter
  - Efficient frontier scatter plot data
"""


import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════════
# Markowitz Efficient Frontier
# ═══════════════════════════════════════════════════════════════════════════════

def efficient_frontier(
    returns_df: pd.DataFrame,
    n_portfolios: int = 5000,
    risk_free_rate: float = 0.03,
    seed: int = 42,
) -> dict:
    """
    Monte Carlo simulation of the efficient frontier.

    Returns:
      - All simulated portfolios (return, vol, sharpe, weights)
      - Max Sharpe portfolio
      - Min Volatility portfolio
    """
    np.random.seed(seed)
    n_assets = len(returns_df.columns)
    tickers = list(returns_df.columns)

    mean_returns = returns_df.mean() * 252
    cov_matrix = returns_df.cov() * 252

    results = {
        "returns": [], "volatilities": [], "sharpe_ratios": [],
        "weights": [],
    }

    for _ in range(n_portfolios):
        w = np.random.dirichlet(np.ones(n_assets))
        port_return = float(w @ mean_returns.values)
        port_vol = float(np.sqrt(w @ cov_matrix.values @ w))
        sharpe = (port_return - risk_free_rate) / port_vol if port_vol > 0 else 0

        results["returns"].append(round(port_return * 100, 2))
        results["volatilities"].append(round(port_vol * 100, 2))
        results["sharpe_ratios"].append(round(float(sharpe), 4))
        results["weights"].append([round(float(x), 4) for x in w])

    # Find optimal portfolios
    sharpe_arr = np.array(results["sharpe_ratios"])
    vol_arr = np.array(results["volatilities"])

    max_sharpe_idx = int(np.argmax(sharpe_arr))
    min_vol_idx = int(np.argmin(vol_arr))

    max_sharpe_portfolio = {
        "return_pct": results["returns"][max_sharpe_idx],
        "volatility_pct": results["volatilities"][max_sharpe_idx],
        "sharpe_ratio": results["sharpe_ratios"][max_sharpe_idx],
        "weights": dict(zip(tickers, results["weights"][max_sharpe_idx])),
    }

    min_vol_portfolio = {
        "return_pct": results["returns"][min_vol_idx],
        "volatility_pct": results["volatilities"][min_vol_idx],
        "sharpe_ratio": results["sharpe_ratios"][min_vol_idx],
        "weights": dict(zip(tickers, results["weights"][min_vol_idx])),
    }

    return {
        "n_portfolios": n_portfolios,
        "tickers": tickers,
        "frontier": {
            "returns": results["returns"],
            "volatilities": results["volatilities"],
            "sharpe_ratios": results["sharpe_ratios"],
        },
        "max_sharpe": max_sharpe_portfolio,
        "min_volatility": min_vol_portfolio,
        "mean_annual_returns": {t: round(float(v) * 100, 2)
                                 for t, v in mean_returns.items()},
        "correlation_matrix": returns_df.corr().round(4).to_dict(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Momentum Ranking & Filter
# ═══════════════════════════════════════════════════════════════════════════════

def rank_assets(
    returns_df: pd.DataFrame,
    method: str = "momentum_12m",
    top_n: int | None = None,
) -> list[dict]:
    """
    Rank assets by a given metric and optionally filter top N.

    Methods:
      - momentum_12m: 12-month cumulative return
      - momentum_6m: 6-month cumulative return
      - momentum_3m: 3-month cumulative return
      - sharpe: annualized Sharpe ratio
      - inverse_vol: inverse volatility (lower vol = higher rank)
      - sortino: Sortino ratio
    """
    tickers = list(returns_df.columns)
    scores = {}

    for ticker in tickers:
        r = returns_df[ticker].dropna()
        if len(r) < 60:
            scores[ticker] = -999
            continue

        if method == "momentum_12m":
            lookback = min(252, len(r))
            scores[ticker] = float((1 + r.iloc[-lookback:]).prod() - 1)
        elif method == "momentum_6m":
            lookback = min(126, len(r))
            scores[ticker] = float((1 + r.iloc[-lookback:]).prod() - 1)
        elif method == "momentum_3m":
            lookback = min(63, len(r))
            scores[ticker] = float((1 + r.iloc[-lookback:]).prod() - 1)
        elif method == "sharpe":
            ann_ret = float(r.mean() * 252)
            ann_vol = float(r.std() * np.sqrt(252))
            scores[ticker] = ann_ret / ann_vol if ann_vol > 0 else 0
        elif method == "inverse_vol":
            ann_vol = float(r.std() * np.sqrt(252))
            scores[ticker] = -ann_vol  # negative so lower vol ranks higher
        elif method == "sortino":
            downside = r[r < 0]
            ds_std = float(downside.std()) if len(downside) > 0 else 1e-8
            scores[ticker] = float(r.mean() * 252) / (ds_std * np.sqrt(252))
        else:
            scores[ticker] = float(r.mean() * 252)

    # Sort descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    results = []
    for rank, (ticker, score) in enumerate(ranked, 1):
        results.append({
            "rank": rank,
            "ticker": ticker,
            "score": round(score * 100, 2) if "momentum" in method else round(score, 4),
            "selected": rank <= (top_n or len(ranked)),
        })

    return results


def equal_weight_top_n(rankings: list[dict], top_n: int) -> dict[str, float]:
    """Generate equal-weight allocation for top N ranked assets."""
    selected = [r["ticker"] for r in rankings if r["selected"]][:top_n]
    if not selected:
        return {}
    w = round(1.0 / len(selected), 4)
    return {t: w for t in selected}


def inverse_vol_weights(returns_df: pd.DataFrame, tickers: list[str]) -> dict[str, float]:
    """Risk-parity-lite: allocate inversely proportional to volatility."""
    vols = {}
    for t in tickers:
        if t in returns_df.columns:
            vols[t] = float(returns_df[t].std())

    if not vols or all(v == 0 for v in vols.values()):
        return equal_weight_top_n(
            [{"ticker": t, "selected": True} for t in tickers], len(tickers),
        )

    inv_vols = {t: 1.0 / v for t, v in vols.items() if v > 0}
    total = sum(inv_vols.values())
    return {t: round(v / total, 4) for t, v in inv_vols.items()}
