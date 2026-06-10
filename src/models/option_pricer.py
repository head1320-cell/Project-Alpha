"""
Smile-Aware Option Pricer
===========================
Black-76 / Extended BSM pricer with dynamic r(T), q(T), sigma(K,T).

Features:
  - Black-76 forward-based pricing (FICC standard)
  - Generalized BSM with continuous dividend yield q
  - 7 Greeks: Delta, Gamma, Theta, Vega, Rho, Vanna, Volga
  - Vanna/Volga computed via finite-difference on the smile
  - Scenario surface: price as function of (S, T)
"""


import numpy as np
from scipy.stats import norm

# ═══════════════════════════════════════════════════════════════════════════════
# Black-76 / Generalized BSM
# ═══════════════════════════════════════════════════════════════════════════════

def _d1d2(S: float, K: float, r: float, q: float, sigma: float, T: float):
    """Compute d1 and d2 for BSM/Black-76."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0, 0.0
    sqrt_t = np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return float(d1), float(d2)


def price_european(
    S: float, K: float, T: float,
    r: float, q: float, sigma: float,
    option_type: str = "call",
) -> float:
    """
    Generalized Black-Scholes-Merton price.

    For Black-76 forward pricing: set q such that F = S*exp((r-q)*T)
    is the observed forward price, i.e. q = r - ln(F/S)/T.

    Args:
        S: spot price
        K: strike price
        T: time to expiry (years)
        r: risk-free rate (continuous, decimal)
        q: continuous dividend yield / foreign rate (decimal)
        sigma: implied volatility (decimal)
        option_type: 'call' or 'put'
    """
    if T <= 0:
        # At expiry: intrinsic value
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    d1, d2 = _d1d2(S, K, r, q, sigma, T)
    df_r = np.exp(-r * T)
    df_q = np.exp(-q * T)

    if option_type == "call":
        return float(S * df_q * norm.cdf(d1) - K * df_r * norm.cdf(d2))
    else:
        return float(K * df_r * norm.cdf(-d2) - S * df_q * norm.cdf(-d1))


# ═══════════════════════════════════════════════════════════════════════════════
# Analytical Greeks
# ═══════════════════════════════════════════════════════════════════════════════

def greeks_european(
    S: float, K: float, T: float,
    r: float, q: float, sigma: float,
    option_type: str = "call",
) -> dict:
    """
    Compute 5 core Greeks + Vanna + Volga.

    Core: Delta, Gamma, Theta, Vega, Rho
    Smile: Vanna (d(Delta)/d(sigma)), Volga (d(Vega)/d(sigma))

    Vanna and Volga are computed analytically from BSM closed-forms.
    """
    if T <= 0 or sigma <= 0:
        return {
            "price": max(S - K, 0) if option_type == "call" else max(K - S, 0),
            "delta": 1.0 if option_type == "call" and S > K else
                     -1.0 if option_type == "put" and K > S else 0.0,
            "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0,
            "vanna": 0.0, "volga": 0.0,
        }

    d1, d2 = _d1d2(S, K, r, q, sigma, T)
    sqrt_t = np.sqrt(T)
    df_r = np.exp(-r * T)
    df_q = np.exp(-q * T)
    n_d1 = norm.pdf(d1)   # Standard normal density at d1

    # Price
    price = price_european(S, K, T, r, q, sigma, option_type)

    # Gamma (same for call and put)
    gamma = df_q * n_d1 / (S * sigma * sqrt_t)

    # Vega (per 1% vol move = multiply by 0.01)
    vega_abs = S * df_q * n_d1 * sqrt_t   # absolute vega
    vega_pct = vega_abs / 100               # per 1% vol change

    if option_type == "call":
        delta = df_q * norm.cdf(d1)
        theta = (-(S * sigma * df_q * n_d1) / (2 * sqrt_t)
                 + q * S * df_q * norm.cdf(d1)
                 - r * K * df_r * norm.cdf(d2)) / 365
        rho = K * T * df_r * norm.cdf(d2) / 100
    else:
        delta = df_q * (norm.cdf(d1) - 1)
        theta = (-(S * sigma * df_q * n_d1) / (2 * sqrt_t)
                 - q * S * df_q * norm.cdf(-d1)
                 + r * K * df_r * norm.cdf(-d2)) / 365
        rho = -K * T * df_r * norm.cdf(-d2) / 100

    # ── Vanna: d(Delta)/d(sigma) = -e^{-qT} * n(d1) * d2 / sigma ────
    vanna = -df_q * n_d1 * d2 / sigma

    # ── Volga: d(Vega)/d(sigma) = Vega * d1 * d2 / sigma ─────────────
    volga = vega_abs * d1 * d2 / sigma

    return {
        "price": round(float(price), 6),
        "delta": round(float(delta), 6),
        "gamma": round(float(gamma), 8),
        "theta": round(float(theta), 6),
        "vega": round(float(vega_pct), 6),
        "rho": round(float(rho), 6),
        "vanna": round(float(vanna), 6),
        "volga": round(float(volga), 6),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Full Pricing with Dynamic Parameters
# ═══════════════════════════════════════════════════════════════════════════════

def price_with_surface(
    S: float, K: float, T: float,
    curve=None,
    vol_surface=None,
    q: float = 0.0,
    option_type: str = "call",
    fallback_r: float = 0.035,
    fallback_sigma: float = 0.20,
) -> dict:
    """
    Price option using full curve + vol surface infrastructure.

    Args:
        curve: FundingCurve object (provides r(T))
        vol_surface: VolSurface object (provides sigma(K,T))
        q: continuous dividend yield
    """
    # Extract r from curve
    if curve is not None:
        r = curve.rate(T)
    else:
        r = fallback_r

    # Extract sigma from vol surface
    if vol_surface is not None:
        sigma = vol_surface.vol_at_strike(K, S, r, q)
    else:
        sigma = fallback_sigma

    # Compute price and Greeks
    result = greeks_european(S, K, T, r, q, sigma, option_type)

    # Add parameter transparency
    result["applied_params"] = {
        "r_pct": round(r * 100, 4),
        "q_pct": round(q * 100, 4),
        "sigma_pct": round(sigma * 100, 4),
        "T_years": round(T, 4),
        "S": S,
        "K": K,
        "type": option_type.upper(),
    }

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Surface: Price as f(S, T)
# ═══════════════════════════════════════════════════════════════════════════════

def price_scenario_surface(
    K: float,
    r: float,
    q: float,
    sigma: float,
    option_type: str = "call",
    s_range: tuple = (0.7, 1.3),
    t_range: tuple = (0.05, 2.0),
    n_s: int = 30,
    n_t: int = 20,
    ref_spot: float = 100.0,
) -> dict:
    """
    Generate 3D surface of option price as function of spot and time.

    Returns data for Plotly Surface plot.
    """
    spots = np.linspace(ref_spot * s_range[0], ref_spot * s_range[1], n_s)
    times = np.linspace(t_range[0], t_range[1], n_t)

    z = []
    for t in times:
        row = []
        for s in spots:
            p = price_european(s, K, t, r, q, sigma, option_type)
            row.append(round(float(p), 4))
        z.append(row)

    return {
        "spots": [round(float(s), 2) for s in spots],
        "times": [round(float(t), 3) for t in times],
        "prices": z,
        "params": {
            "K": K, "r_pct": round(r * 100, 4),
            "q_pct": round(q * 100, 4), "sigma_pct": round(sigma * 100, 4),
            "type": option_type.upper(),
        },
    }
