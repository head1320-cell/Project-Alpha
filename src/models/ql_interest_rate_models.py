"""
QuantLib Interest Rate Models & Calibration
=============================================
Hull-White 1-Factor model with Levenberg-Marquardt calibration.
SABR volatility interpolation for swaption smile.

Features:
  - Hull-White calibration from swaption vol data
  - Swaption pricing (Jamshidian / Tree engine)
  - SABR alpha/beta/rho/nu parameter estimation
  - IRS (Interest Rate Swap) construction and valuation
"""


import numpy as np

try:
    import QuantLib as ql
    HAS_QL = True
except ImportError:
    HAS_QL = False


# ═══════════════════════════════════════════════════════════════════════════════
# Curve Construction Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def build_ql_curve(
    tenors_years: list[float],
    rates_pct: list[float],
    eval_date=None,
):
    """Build QuantLib ZeroCurve from tenors and rates."""
    if not HAS_QL:
        return None, None

    if eval_date is None:
        eval_date = ql.Date.todaysDate()
    ql.Settings.instance().evaluationDate = eval_date

    dates = [eval_date + ql.Period(int(t * 365), ql.Days) for t in tenors_years]
    rates = [r / 100.0 for r in rates_pct]

    curve = ql.ZeroCurve(dates, rates, ql.Actual365Fixed())
    handle = ql.YieldTermStructureHandle(curve)
    return curve, handle


def build_flat_curve(rate_pct: float, eval_date=None):
    """Build flat yield curve."""
    if not HAS_QL:
        return None, None
    if eval_date is None:
        eval_date = ql.Date.todaysDate()
    ql.Settings.instance().evaluationDate = eval_date

    curve = ql.FlatForward(eval_date, rate_pct / 100.0, ql.Actual365Fixed())
    handle = ql.YieldTermStructureHandle(curve)
    return curve, handle


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1a: Hull-White 1-Factor Model
# ═══════════════════════════════════════════════════════════════════════════════

def calibrate_hull_white(
    curve_handle,
    swaption_vols: list[dict],
    a_init: float = 0.05,
    sigma_init: float = 0.01,
) -> dict:
    """
    Calibrate Hull-White 1-Factor model to swaption volatilities.

    Args:
        curve_handle: ql.YieldTermStructureHandle
        swaption_vols: [{"expiry_years": 1, "tenor_years": 5, "vol_pct": 15.0}, ...]
        a_init: initial mean reversion speed
        sigma_init: initial volatility

    Returns:
        Calibrated a, sigma, and fit quality metrics.
    """
    if not HAS_QL:
        return _py_hull_white_fallback(swaption_vols, a_init, sigma_init)

    ql.Settings.instance().evaluationDate = ql.Date.todaysDate()
    index = ql.Euribor6M(curve_handle)

    model = ql.HullWhite(curve_handle, a_init, sigma_init)
    engine = ql.JamshidianSwaptionEngine(model)

    # Build calibration helpers
    helpers = []
    for sv in swaption_vols:
        expiry = ql.Period(int(sv["expiry_years"] * 12), ql.Months)
        tenor = ql.Period(int(sv["tenor_years"] * 12), ql.Months)
        vol = ql.QuoteHandle(ql.SimpleQuote(sv["vol_pct"] / 100.0))

        helper = ql.SwaptionHelper(
            expiry, tenor, vol, index,
            ql.Period(6, ql.Months), ql.Actual365Fixed(),
            ql.Actual365Fixed(), curve_handle,
        )
        helper.setPricingEngine(engine)
        helpers.append(helper)

    # Calibrate
    optimizer = ql.LevenbergMarquardt(1e-8, 1e-8, 1e-8)
    end_criteria = ql.EndCriteria(1000, 500, 1e-8, 1e-8, 1e-8)

    model.calibrate(helpers, optimizer, end_criteria)

    a = float(model.params()[0])
    sigma = float(model.params()[1])

    # Compute fit errors
    errors = []
    for i, helper in enumerate(helpers):
        model_price = helper.modelValue()
        market_price = helper.marketValue()
        error_pct = abs(model_price - market_price) / market_price * 100 \
            if market_price > 0 else 0
        errors.append({
            "expiry": swaption_vols[i]["expiry_years"],
            "tenor": swaption_vols[i]["tenor_years"],
            "market_vol": swaption_vols[i]["vol_pct"],
            "model_price": round(float(model_price), 6),
            "market_price": round(float(market_price), 6),
            "error_pct": round(float(error_pct), 3),
        })

    avg_error = float(np.mean([e["error_pct"] for e in errors]))

    return {
        "a_mean_reversion": round(a, 6),
        "sigma_volatility": round(sigma, 6),
        "half_life_years": round(np.log(2) / a, 2) if a > 0 else float("inf"),
        "calibration_errors": errors,
        "avg_error_pct": round(avg_error, 3),
        "n_instruments": len(helpers),
        "engine": "QuantLib HullWhite + JamshidianSwaptionEngine",
    }


def _py_hull_white_fallback(swaption_vols, a_init, sigma_init):
    """Pure-Python Hull-White approximation fallback."""
    return {
        "a_mean_reversion": round(a_init, 6),
        "sigma_volatility": round(sigma_init, 6),
        "half_life_years": round(np.log(2) / a_init, 2) if a_init > 0 else 0,
        "calibration_errors": [],
        "avg_error_pct": 0,
        "n_instruments": len(swaption_vols),
        "engine": "Python fallback (no calibration)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1b: SABR Volatility Interpolation
# ═══════════════════════════════════════════════════════════════════════════════

def fit_sabr(
    strikes: list[float],
    vols: list[float],
    forward: float,
    T: float,
    beta: float = 0.5,
) -> dict:
    """
    Fit SABR model parameters (alpha, rho, nu) to market vol smile.

    Uses QuantLib's SABRInterpolation if available, otherwise
    simple least-squares optimization.

    Args:
        strikes: list of strike prices
        vols: list of implied volatilities (decimal)
        forward: forward price/rate
        T: time to expiry
        beta: SABR beta (fixed, typically 0.5 for rates)
    """
    if HAS_QL and len(strikes) >= 3:
        try:
            return _ql_sabr_fit(strikes, vols, forward, T, beta)
        except Exception:
            pass

    return _py_sabr_fit(strikes, vols, forward, T, beta)


def _ql_sabr_fit(strikes, vols, forward, T, beta):
    """QuantLib SABR interpolation."""
    sabr = ql.SABRInterpolation(
        strikes, vols, T, forward, beta,
        0.03, 0.0, 0.5,  # initial alpha, rho, nu
        False, False, False, False,  # fix flags
    )
    sabr.update()

    alpha = float(sabr.alpha())
    rho = float(sabr.rho())
    nu = float(sabr.nu())

    # Generate smooth smile
    k_fine = np.linspace(min(strikes) * 0.9, max(strikes) * 1.1, 50)
    vol_fine = [float(sabr(k, True)) for k in k_fine]

    return {
        "alpha": round(alpha, 6),
        "beta": beta,
        "rho": round(rho, 6),
        "nu": round(nu, 6),
        "smile_strikes": [round(float(k), 4) for k in k_fine],
        "smile_vols_pct": [round(v * 100, 4) for v in vol_fine],
        "engine": "QuantLib SABRInterpolation",
    }


def _py_sabr_fit(strikes, vols, forward, T, beta):
    """Pure-Python SABR calibration via Hagan formula."""
    from scipy.optimize import minimize

    def sabr_vol(K, alpha, rho, nu):
        if abs(K - forward) < 1e-8:
            return alpha / (forward ** (1 - beta))
        FK = forward * K
        z = nu / alpha * (FK ** ((1 - beta) / 2)) * np.log(forward / K)
        x_z = np.log((np.sqrt(1 - 2*rho*z + z**2) + z - rho) / (1 - rho))
        if abs(x_z) < 1e-8:
            x_z = 1.0
        prefix = alpha / (FK ** ((1 - beta) / 2) * (
            1 + ((1 - beta)**2 / 24) * np.log(forward / K)**2
        ))
        return prefix * z / x_z

    def objective(params):
        alpha, rho, nu = params
        if alpha <= 0 or nu <= 0 or abs(rho) >= 1:
            return 1e10
        err = 0
        for k, v in zip(strikes, vols):
            try:
                model_v = sabr_vol(k, alpha, rho, nu)
                err += (model_v - v) ** 2
            except Exception:
                err += 1e6
        return err

    result = minimize(objective, [0.03, -0.2, 0.5],
                       method="Nelder-Mead",
                       options={"maxiter": 5000})

    alpha, rho, nu = result.x

    k_fine = np.linspace(min(strikes) * 0.9, max(strikes) * 1.1, 50)
    vol_fine = [sabr_vol(k, alpha, rho, nu) * 100 for k in k_fine]

    return {
        "alpha": round(float(alpha), 6),
        "beta": beta,
        "rho": round(float(rho), 6),
        "nu": round(float(nu), 6),
        "smile_strikes": [round(float(k), 4) for k in k_fine],
        "smile_vols_pct": [round(float(v), 4) for v in vol_fine],
        "engine": "Python SABR (Hagan formula)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# IRS (Interest Rate Swap) Valuation
# ═══════════════════════════════════════════════════════════════════════════════

def price_irs(
    notional: float,
    fixed_rate_pct: float,
    tenor_years: int,
    curve_rate_pct: float,
    pay_fixed: bool = True,
) -> dict:
    """
    Price a plain vanilla IRS using QuantLib or analytical formula.
    """
    r = curve_rate_pct / 100
    fixed = fixed_rate_pct / 100

    # Analytical approximation: NPV ≈ Notional * (r - fixed) * Annuity
    # Annuity ≈ sum of discount factors
    annuity = sum(np.exp(-r * t) for t in range(1, tenor_years + 1))
    npv = notional * (r - fixed) * annuity
    if not pay_fixed:
        npv = -npv

    dv01 = notional * annuity / 10000  # Dollar value of 1bp

    return {
        "npv": round(float(npv), 2),
        "dv01": round(float(dv01), 2),
        "annuity": round(float(annuity), 6),
        "fixed_rate_pct": fixed_rate_pct,
        "floating_rate_pct": curve_rate_pct,
        "notional": notional,
        "tenor_years": tenor_years,
        "direction": "Pay Fixed" if pay_fixed else "Receive Fixed",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Mock Swaption Vol Data
# ═══════════════════════════════════════════════════════════════════════════════

def generate_swaption_vol_grid() -> list[dict]:
    """Generate mock swaption ATM volatility grid."""
    np.random.seed(42)
    expiries = [0.5, 1.0, 2.0, 3.0, 5.0]
    tenors = [2, 5, 10]

    grid = []
    for exp in expiries:
        for ten in tenors:
            base_vol = 12 + 3 * np.sqrt(exp) + 0.5 * ten
            vol = base_vol + np.random.normal(0, 0.3)
            grid.append({
                "expiry_years": exp,
                "tenor_years": ten,
                "vol_pct": round(float(vol), 2),
            })
    return grid
