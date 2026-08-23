"""
Volatility Surface & Implied Yield Engine
============================================
FICC desk-grade vol surface construction.

Features:
  - ATM / 25-Delta Risk Reversal / 25-Delta Butterfly quote input
  - Malz model for smile interpolation
  - Multi-tenor surface construction with 2D interpolation
  - GARCH(1,1) fallback for historical vol estimation
  - Implied yield (q) extraction via CIP/forward price
"""


import numpy as np
from scipy.interpolate import RectBivariateSpline
from scipy.stats import norm

# ═══════════════════════════════════════════════════════════════════════════════
# Malz Volatility Smile Model
# ═══════════════════════════════════════════════════════════════════════════════

class MalzSmile:
    """
    Reconstruct volatility smile from ATM, 25-Delta RR, 25-Delta BF quotes.

    Malz (1997) parameterization:
      sigma(delta) = ATM + 2*RR*(delta - 0.5) + 16*BF*(delta - 0.5)^2

    Where delta is the Black-Scholes delta of the option (0 to 1 for calls).
    """

    def __init__(self, atm: float, rr_25: float, bf_25: float, T: float = 1.0):
        """
        Args:
            atm: ATM implied volatility (decimal, e.g. 0.15 = 15%)
            rr_25: 25-delta risk reversal (decimal)
            bf_25: 25-delta butterfly (decimal, always positive)
            T: time to expiry in years
        """
        self.atm = atm
        self.rr = rr_25
        self.bf = bf_25
        self.T = T

        # Derived: 25-delta call and put vols
        self.sigma_25c = atm + 0.5 * rr_25 + bf_25
        self.sigma_25p = atm - 0.5 * rr_25 + bf_25

    def vol_at_delta(self, delta: float) -> float:
        """
        Implied vol for a given Black-Scholes delta.
        delta in [0, 1] for calls.
        """
        d = np.clip(delta, 0.01, 0.99)
        return self.atm + 2 * self.rr * (d - 0.5) + 16 * self.bf * (d - 0.5) ** 2

    def vol_at_strike(self, K: float, S: float, r: float, q: float = 0.0) -> float:
        """
        Implied vol for a given strike K.
        Uses Newton-Raphson to find delta corresponding to K,
        then evaluates the smile at that delta.
        """
        # Initial guess: ATM delta
        delta = 0.5
        for _ in range(20):
            sigma = self.vol_at_delta(delta)
            if sigma <= 0 or self.T <= 0:
                return self.atm
            d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * self.T) / (sigma * np.sqrt(self.T))
            new_delta = norm.cdf(d1)
            if abs(new_delta - delta) < 1e-6:
                break
            delta = new_delta
        return self.vol_at_delta(delta)

    def smile_curve(self, n_points: int = 50) -> dict:
        """Generate smile curve data for plotting."""
        deltas = np.linspace(0.05, 0.95, n_points)
        vols = [self.vol_at_delta(d) * 100 for d in deltas]
        return {
            "deltas": [round(float(d), 4) for d in deltas],
            "vols_pct": [round(float(v), 4) for v in vols],
            "atm_pct": round(self.atm * 100, 4),
            "sigma_25c_pct": round(self.sigma_25c * 100, 4),
            "sigma_25p_pct": round(self.sigma_25p * 100, 4),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-Tenor Volatility Surface
# ═══════════════════════════════════════════════════════════════════════════════

class VolSurface:
    """
    2D volatility surface: sigma(K, T) or sigma(delta, T).

    Built from multiple MalzSmile objects at different tenors.
    Uses RectBivariateSpline for smooth interpolation.
    """

    def __init__(self, smiles: list[dict]):
        """
        Args:
            smiles: list of {"T": float, "atm": float, "rr": float, "bf": float}
        """
        self.smiles = sorted(smiles, key=lambda s: s["T"])
        self._smile_objects = {
            s["T"]: MalzSmile(s["atm"], s["rr"], s["bf"], s["T"])
            for s in self.smiles
        }

        # Build spline grid
        tenors = [s["T"] for s in self.smiles]
        deltas = np.linspace(0.05, 0.95, 19)

        z_grid = np.zeros((len(tenors), len(deltas)))
        for i, t in enumerate(tenors):
            smile = self._smile_objects[t]
            for j, d in enumerate(deltas):
                z_grid[i, j] = smile.vol_at_delta(d)

        if len(tenors) >= 2:
            self._spline = RectBivariateSpline(tenors, deltas, z_grid, kx=1, ky=3)
        else:
            self._spline = None
        self._tenors = tenors
        self._deltas = deltas

    def vol(self, delta: float, T: float) -> float:
        """Implied volatility at (delta, T)."""
        if self._spline is not None:
            T_clipped = np.clip(T, self._tenors[0], self._tenors[-1])
            d_clipped = np.clip(delta, 0.05, 0.95)
            return float(np.clip(self._spline(T_clipped, d_clipped)[0, 0], 0.01, 2.0))

        # Single tenor fallback
        t_key = self._tenors[0]
        return self._smile_objects[t_key].vol_at_delta(delta)

    def vol_at_strike(self, K: float, S: float, T: float, r: float, q: float = 0.0) -> float:
        """Implied vol at specific strike using Newton-Raphson delta mapping."""
        closest_t = min(self._tenors, key=lambda t: abs(t - T))
        smile = self._smile_objects[closest_t]
        return smile.vol_at_strike(K, S, r, q)

    def surface_data(self, n_deltas: int = 20, n_tenors: int = 20) -> dict:
        """Generate 3D surface data for plotting."""
        deltas = np.linspace(0.10, 0.90, n_deltas)
        tenors = np.linspace(self._tenors[0], self._tenors[-1], n_tenors) \
            if len(self._tenors) > 1 else [self._tenors[0]]

        z = []
        for t in tenors:
            row = [round(self.vol(d, t) * 100, 3) for d in deltas]
            z.append(row)

        return {
            "deltas": [round(float(d), 3) for d in deltas],
            "tenors": [round(float(t), 3) for t in tenors],
            "vols_pct": z,
        }


def generate_mock_vol_quotes(
    atm_base: float = 0.18,
    seed: int = 42,
) -> list[dict]:
    """Generate mock ATM/RR/BF vol quotes for multiple tenors."""
    np.random.seed(seed)
    tenors = [1/12, 3/12, 6/12, 1.0, 2.0]
    labels = ["1M", "3M", "6M", "1Y", "2Y"]

    quotes = []
    for _i, (t, label) in enumerate(zip(tenors, labels)):
        # Term structure of vol: short-term higher, mean-reverts
        term_adj = 0.03 * np.exp(-0.5 * t) + np.random.normal(0, 0.005)
        atm = atm_base + term_adj
        rr = -0.015 + np.random.normal(0, 0.003)     # Typical negative skew
        bf = 0.008 + np.random.normal(0, 0.002)       # Always positive

        quotes.append({
            "tenor_label": label,
            "T": round(t, 4),
            "atm": round(float(atm), 4),
            "rr": round(float(rr), 4),
            "bf": round(float(abs(bf)), 4),
        })

    return quotes


# ═══════════════════════════════════════════════════════════════════════════════
# GARCH(1,1) Fallback Volatility
# ═══════════════════════════════════════════════════════════════════════════════

def garch_volatility_forecast(
    returns: np.ndarray,
    omega: float = 0.00001,
    alpha: float = 0.10,
    beta: float = 0.85,
    n_forecast: int = 20,
) -> dict:
    """
    Simple GARCH(1,1) volatility forecast.

    sigma^2_t = omega + alpha * r^2_{t-1} + beta * sigma^2_{t-1}

    Used as fallback when market vol quotes are unavailable.
    """
    n = len(returns)
    if n < 30:
        return {"error": "Need at least 30 observations"}

    # Fit conditional variance
    var = np.zeros(n)
    var[0] = float(np.var(returns))

    for t in range(1, n):
        var[t] = omega + alpha * returns[t - 1]**2 + beta * var[t - 1]

    # Forecast
    forecast_var = np.zeros(n_forecast)
    forecast_var[0] = omega + alpha * returns[-1]**2 + beta * var[-1]
    for t in range(1, n_forecast):
        forecast_var[t] = omega + (alpha + beta) * forecast_var[t - 1]

    # Long-run variance
    long_run_var = omega / (1 - alpha - beta) if (alpha + beta) < 1 else var[-1]

    current_vol = float(np.sqrt(var[-1]))
    forecast_vol = [round(float(np.sqrt(v)), 6) for v in forecast_var]
    annualized = round(current_vol * np.sqrt(252) * 100, 2)

    return {
        "current_daily_vol": round(current_vol, 6),
        "annualized_vol_pct": annualized,
        "long_run_vol_pct": round(float(np.sqrt(long_run_var)) * np.sqrt(252) * 100, 2),
        "forecast_daily_vol": forecast_vol,
        "persistence": round(float(alpha + beta), 4),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Implied Yield (q) from CIP / Forward Price
# ═══════════════════════════════════════════════════════════════════════════════

def implied_yield_from_forward(
    spot: float,
    forward: float,
    r: float,
    T: float,
) -> float:
    """
    Extract continuous dividend/foreign rate q from spot-forward parity.

    F = S * exp((r - q) * T)
    q = r - ln(F/S) / T
    """
    if T <= 0 or spot <= 0 or forward <= 0:
        return 0.0
    return float(r - np.log(forward / spot) / T)


def implied_yield_from_options(
    call_price: float,
    put_price: float,
    S: float,
    K: float,
    r: float,
    T: float,
) -> float:
    """
    Extract q from put-call parity.

    C - P = S*exp(-q*T) - K*exp(-r*T)
    q = -ln((C - P + K*exp(-r*T)) / S) / T
    """
    if T <= 0 or S <= 0:
        return 0.0
    x = call_price - put_price + K * np.exp(-r * T)
    if x <= 0:
        return 0.0
    return float(-np.log(x / S) / T)
