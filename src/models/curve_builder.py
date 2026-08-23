"""
Cheapest Funding Curve Builder
================================
Constructs optimal zero-coupon yield curve (ZCYC) by comparing
direct KRW funding vs synthetic (USD SOFR + CRS Basis) funding.

R_opt(t) = min(R_direct(t), R_synthetic(t))

Features:
  - Mock market data generator for KOFR, KRW IRS, USD SOFR, CRS Basis
  - Cheapest funding algorithm per tenor
  - Cubic spline interpolation for arbitrary maturity T
  - Curve object with rate(), discount_factor(), forward_rate() methods
"""


import numpy as np
from scipy.interpolate import CubicSpline

# ═══════════════════════════════════════════════════════════════════════════════
# Market Data (Mock Generator)
# ═══════════════════════════════════════════════════════════════════════════════

# Standard tenors in years
TENORS = [1/12, 3/12, 6/12, 1.0, 2.0, 3.0, 5.0]
TENOR_LABELS = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y"]


def generate_mock_market_data(
    kofr_base: float = 3.50,
    irs_spread: float = 0.15,
    sofr_base: float = 4.50,
    crs_basis: float = -0.30,
    seed: int | None = 42,
) -> dict:
    """
    Generate realistic mock market data for Korean funding markets.

    Returns dict with tenor-indexed rates for:
      - KOFR (overnight rate, term structure proxy)
      - KRW IRS (swap rates)
      - USD SOFR (term structure)
      - CRS Basis (cross-currency swap basis)
    """
    if seed is not None:
        np.random.seed(seed)

    n = len(TENORS)
    noise = np.random.normal(0, 0.03, n)

    # KOFR term structure (upward sloping from overnight)
    kofr = np.array([
        kofr_base - 0.05,           # 1M: slightly below base
        kofr_base,                   # 3M: at base
        kofr_base + 0.08,           # 6M
        kofr_base + 0.15,           # 1Y
        kofr_base + 0.25,           # 2Y
        kofr_base + 0.30,           # 3Y
        kofr_base + 0.35,           # 5Y
    ]) + noise * 0.5

    # KRW IRS (slightly above KOFR due to credit/liquidity)
    krw_irs = kofr + irs_spread + np.abs(noise) * 0.3

    # USD SOFR term structure
    sofr = np.array([
        sofr_base - 0.10,
        sofr_base,
        sofr_base + 0.05,
        sofr_base + 0.10,
        sofr_base + 0.08,
        sofr_base + 0.05,
        sofr_base - 0.05,           # Inversion at long end
    ]) + noise * 0.3

    # CRS Basis (typically negative for KRW, widens at longer tenors)
    crs = np.array([
        crs_basis + 0.05,
        crs_basis,
        crs_basis - 0.05,
        crs_basis - 0.10,
        crs_basis - 0.15,
        crs_basis - 0.18,
        crs_basis - 0.20,
    ]) + noise * 0.2

    return {
        "tenors": TENORS,
        "tenor_labels": TENOR_LABELS,
        "kofr": [round(float(r), 4) for r in kofr],
        "krw_irs": [round(float(r), 4) for r in krw_irs],
        "usd_sofr": [round(float(r), 4) for r in sofr],
        "crs_basis": [round(float(r), 4) for r in crs],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Cheapest Funding Algorithm
# ═══════════════════════════════════════════════════════════════════════════════

def compute_cheapest_funding(market_data: dict) -> dict:
    """
    For each tenor, compare direct vs synthetic funding
    and select the cheapest rate.

    Direct:    R_direct(t) = KRW IRS(t)
    Synthetic: R_synthetic(t) = USD SOFR(t) + CRS Basis(t)
    Optimal:   R_opt(t) = min(R_direct, R_synthetic)
    """
    tenors = market_data["tenors"]
    krw_irs = np.array(market_data["krw_irs"])
    sofr = np.array(market_data["usd_sofr"])
    crs = np.array(market_data["crs_basis"])

    direct = krw_irs
    synthetic = sofr + crs
    optimal = np.minimum(direct, synthetic)

    results = []
    for i, t in enumerate(tenors):
        source = "Direct (KRW IRS)" if direct[i] <= synthetic[i] else "Synthetic (SOFR+CRS)"
        saving = abs(float(direct[i] - synthetic[i]))
        results.append({
            "tenor": market_data["tenor_labels"][i],
            "tenor_years": t,
            "direct_rate": round(float(direct[i]), 4),
            "synthetic_rate": round(float(synthetic[i]), 4),
            "optimal_rate": round(float(optimal[i]), 4),
            "source": source,
            "saving_bps": round(saving * 100, 1),
        })

    return {
        "details": results,
        "tenors": tenors,
        "direct_curve": [round(float(r), 4) for r in direct],
        "synthetic_curve": [round(float(r), 4) for r in synthetic],
        "optimal_curve": [round(float(r), 4) for r in optimal],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Interpolated Curve Object
# ═══════════════════════════════════════════════════════════════════════════════

class FundingCurve:
    """
    Cubic-spline interpolated zero-coupon yield curve.

    Methods:
      rate(T)            -> continuous zero rate at maturity T
      discount_factor(T) -> e^{-r(T)*T}
      forward_rate(T1,T2)-> instantaneous forward between T1 and T2
    """

    def __init__(self, tenors: list[float], rates: list[float]):
        self.tenors = np.array(tenors)
        self.rates = np.array(rates) / 100  # Convert from % to decimal
        self._spline = CubicSpline(
            self.tenors, self.rates, bc_type="natural", extrapolate=True,
        )

    def rate(self, T: float) -> float:
        """Zero rate at maturity T (decimal, e.g. 0.035 = 3.5%)."""
        return float(np.clip(self._spline(T), 0.0, 0.20))

    def discount_factor(self, T: float) -> float:
        """Discount factor: exp(-r(T) * T)."""
        return float(np.exp(-self.rate(T) * T))

    def forward_rate(self, T1: float, T2: float) -> float:
        """
        Continuously compounded forward rate between T1 and T2.
        f(T1,T2) = [r(T2)*T2 - r(T1)*T1] / (T2 - T1)
        """
        if T2 <= T1:
            return self.rate(T1)
        r1, r2 = self.rate(T1), self.rate(T2)
        return float((r2 * T2 - r1 * T1) / (T2 - T1))

    def to_dict(self, n_points: int = 50) -> dict:
        """Serialize curve for API/plotting."""
        t_fine = np.linspace(
            float(self.tenors[0]), float(self.tenors[-1]), n_points,
        )
        rates_fine = [round(float(self._spline(t)) * 100, 4) for t in t_fine]
        return {
            "tenors": [round(float(t), 4) for t in t_fine],
            "rates_pct": rates_fine,
            "pillar_tenors": [float(t) for t in self.tenors],
            "pillar_rates_pct": [round(float(r) * 100, 4) for r in self.rates],
        }


def build_optimal_curve(market_data: dict | None = None) -> tuple:
    """
    Build the cheapest funding curve from market data.

    Returns (FundingCurve, cheapest_funding_details).
    """
    if market_data is None:
        market_data = generate_mock_market_data()

    cf = compute_cheapest_funding(market_data)
    curve = FundingCurve(cf["tenors"], cf["optimal_curve"])
    return curve, cf
