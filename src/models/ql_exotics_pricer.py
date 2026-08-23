"""
QuantLib-Based Exotics & ELS Pricer
=====================================
Institutional-grade pricing for American, Barrier, and structured products.

Phase 1: American (FDM), Barrier (Analytic) via QuantLib engines
Phase 2: Multi-asset Step-Down ELS via QuantLib Monte Carlo

Falls back to pure-Python implementations if QuantLib unavailable.
"""


import numpy as np

try:
    import QuantLib as ql
    HAS_QL = True
except ImportError:
    HAS_QL = False


# ═══════════════════════════════════════════════════════════════════════════════
# QuantLib Market Data Wrappers
# ═══════════════════════════════════════════════════════════════════════════════

def _ql_date(year: int, month: int, day: int):
    """Create QL Date."""
    return ql.Date(day, month, year)


def _ql_flat_curve(rate: float, eval_date=None):
    """Create flat yield term structure handle."""
    if eval_date:
        ql.Settings.instance().evaluationDate = eval_date
    return ql.YieldTermStructureHandle(
        ql.FlatForward(0, ql.NullCalendar(), rate, ql.Actual365Fixed())
    )


def _ql_flat_vol(sigma: float):
    """Create flat Black vol term structure handle."""
    return ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(0, ql.NullCalendar(), sigma, ql.Actual365Fixed())
    )


def build_bsm_process(
    S: float, r: float, q: float, sigma: float, eval_date=None,
):
    """
    Build QuantLib BlackScholesMertonProcess from parameters.

    Wraps spot, yield curves, and vol surface into QL Handle objects.
    """
    if not HAS_QL:
        return None

    if eval_date is None:
        eval_date = ql.Date.todaysDate()
    ql.Settings.instance().evaluationDate = eval_date

    spot_handle = ql.QuoteHandle(ql.SimpleQuote(S))
    r_handle = _ql_flat_curve(r, eval_date)
    q_handle = _ql_flat_curve(q, eval_date)
    vol_handle = _ql_flat_vol(sigma)

    return ql.BlackScholesMertonProcess(spot_handle, q_handle, r_handle, vol_handle)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: American Option (FDM Engine)
# ═══════════════════════════════════════════════════════════════════════════════

def price_american_option(
    S: float, K: float, T: float,
    r: float, q: float, sigma: float,
    option_type: str = "put",
    n_steps: int = 200,
) -> dict:
    """
    Price American option using QuantLib FdBlackScholesVanillaEngine.

    Returns price, Greeks, and early exercise premium.
    """
    if HAS_QL:
        return _ql_american(S, K, T, r, q, sigma, option_type, n_steps)
    return _py_american_binomial(S, K, T, r, q, sigma, option_type, n_steps)


def _ql_american(S, K, T, r, q, sigma, option_type, n_steps):
    """QuantLib FDM-based American option pricing."""
    today = ql.Date.todaysDate()
    maturity = today + int(T * 365)

    process = build_bsm_process(S, r, q, sigma, today)

    payoff = ql.PlainVanillaPayoff(
        ql.Option.Put if option_type == "put" else ql.Option.Call, K,
    )
    exercise = ql.AmericanExercise(today, maturity)
    option = ql.VanillaOption(payoff, exercise)

    # FDM engine
    engine = ql.FdBlackScholesVanillaEngine(process, n_steps, n_steps)
    option.setPricingEngine(engine)

    price = float(option.NPV())
    delta = float(option.delta())
    gamma = float(option.gamma())
    theta = float(option.theta()) / 365

    # European comparison for early exercise premium
    eu_exercise = ql.EuropeanExercise(maturity)
    eu_option = ql.VanillaOption(payoff, eu_exercise)
    eu_engine = ql.AnalyticEuropeanEngine(process)
    eu_option.setPricingEngine(eu_engine)
    eu_price = float(eu_option.NPV())

    return {
        "price": round(price, 6),
        "delta": round(delta, 6),
        "gamma": round(gamma, 8),
        "theta_daily": round(theta, 6),
        "european_price": round(eu_price, 6),
        "early_exercise_premium": round(price - eu_price, 6),
        "early_exercise_premium_pct": round((price - eu_price) / eu_price * 100, 2)
            if eu_price > 0 else 0,
        "engine": "QuantLib FdBlackScholesVanillaEngine",
        "params": {"S": S, "K": K, "T": T, "r": r, "q": q, "sigma": sigma,
                   "type": option_type, "n_steps": n_steps},
    }


def _py_american_binomial(S, K, T, r, q, sigma, option_type, n_steps):
    """Pure-Python CRR binomial tree fallback."""
    dt = T / n_steps
    u = np.exp(sigma * np.sqrt(dt))
    d = 1 / u
    p = (np.exp((r - q) * dt) - d) / (u - d)
    disc = np.exp(-r * dt)

    # Build price tree at maturity
    prices = S * u ** np.arange(n_steps, -1, -1) * d ** np.arange(0, n_steps + 1)
    if option_type == "put":
        values = np.maximum(K - prices, 0)
    else:
        values = np.maximum(prices - K, 0)

    # Backward induction with early exercise
    for step in range(n_steps - 1, -1, -1):
        prices = S * u ** np.arange(step, -1, -1) * d ** np.arange(0, step + 1)
        values = disc * (p * values[:-1] + (1 - p) * values[1:])
        if option_type == "put":
            intrinsic = np.maximum(K - prices, 0)
        else:
            intrinsic = np.maximum(prices - K, 0)
        values = np.maximum(values, intrinsic)

    price = float(values[0])

    # European price for comparison
    from src.models.option_pricer import price_european
    eu_price = price_european(S, K, T, r, q, sigma, option_type)

    # Numerical Greeks
    dS = S * 0.01
    p_up = _py_american_binomial_price(S + dS, K, T, r, q, sigma, option_type, n_steps)
    p_dn = _py_american_binomial_price(S - dS, K, T, r, q, sigma, option_type, n_steps)
    delta = (p_up - p_dn) / (2 * dS)
    gamma = (p_up - 2 * price + p_dn) / (dS ** 2)

    dT = 1 / 365
    p_t = _py_american_binomial_price(S, K, T - dT, r, q, sigma, option_type, n_steps)
    theta = (p_t - price)

    return {
        "price": round(price, 6),
        "delta": round(float(delta), 6),
        "gamma": round(float(gamma), 8),
        "theta_daily": round(float(theta), 6),
        "european_price": round(eu_price, 6),
        "early_exercise_premium": round(price - eu_price, 6),
        "early_exercise_premium_pct": round((price - eu_price) / eu_price * 100, 2)
            if eu_price > 0 else 0,
        "engine": "Python CRR Binomial Tree (fallback)",
        "params": {"S": S, "K": K, "T": T, "r": r, "q": q, "sigma": sigma,
                   "type": option_type, "n_steps": n_steps},
    }


def _py_american_binomial_price(S, K, T, r, q, sigma, option_type, n_steps):
    """Helper: compute American price only (no Greeks)."""
    dt = T / n_steps
    u = np.exp(sigma * np.sqrt(dt))
    d = 1 / u
    p = (np.exp((r - q) * dt) - d) / (u - d)
    disc = np.exp(-r * dt)
    prices = S * u ** np.arange(n_steps, -1, -1) * d ** np.arange(0, n_steps + 1)
    values = np.maximum(K - prices, 0) if option_type == "put" \
        else np.maximum(prices - K, 0)
    for step in range(n_steps - 1, -1, -1):
        prices = S * u ** np.arange(step, -1, -1) * d ** np.arange(0, step + 1)
        values = disc * (p * values[:-1] + (1 - p) * values[1:])
        intrinsic = np.maximum(K - prices, 0) if option_type == "put" \
            else np.maximum(prices - K, 0)
        values = np.maximum(values, intrinsic)
    return float(values[0])


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Barrier Option (Analytic Engine)
# ═══════════════════════════════════════════════════════════════════════════════

BARRIER_TYPES = {
    "Down-and-In": "DownIn",
    "Down-and-Out": "DownOut",
    "Up-and-In": "UpIn",
    "Up-and-Out": "UpOut",
}

def price_barrier_option(
    S: float, K: float, T: float,
    r: float, q: float, sigma: float,
    barrier: float,
    barrier_type: str = "Down-and-Out",
    option_type: str = "call",
    rebate: float = 0.0,
) -> dict:
    """
    Price barrier option using QuantLib AnalyticBarrierEngine.
    """
    if HAS_QL:
        return _ql_barrier(S, K, T, r, q, sigma, barrier, barrier_type, option_type, rebate)
    return _py_barrier_mc(S, K, T, r, q, sigma, barrier, barrier_type, option_type, rebate)


def _ql_barrier(S, K, T, r, q, sigma, barrier, barrier_type, option_type, rebate):
    """QuantLib analytic barrier pricing."""
    today = ql.Date.todaysDate()
    maturity = today + int(T * 365)
    process = build_bsm_process(S, r, q, sigma, today)

    bt_map = {
        "Down-and-In": ql.Barrier.DownIn,
        "Down-and-Out": ql.Barrier.DownOut,
        "Up-and-In": ql.Barrier.UpIn,
        "Up-and-Out": ql.Barrier.UpOut,
    }

    payoff = ql.PlainVanillaPayoff(
        ql.Option.Call if option_type == "call" else ql.Option.Put, K,
    )
    exercise = ql.EuropeanExercise(maturity)

    option = ql.BarrierOption(
        bt_map[barrier_type], barrier, rebate, payoff, exercise,
    )
    engine = ql.AnalyticBarrierEngine(process)
    option.setPricingEngine(engine)

    price = float(option.NPV())

    # Vanilla comparison
    vanilla = ql.VanillaOption(payoff, exercise)
    vanilla.setPricingEngine(ql.AnalyticEuropeanEngine(process))
    vanilla_price = float(vanilla.NPV())

    return {
        "price": round(price, 6),
        "vanilla_price": round(vanilla_price, 6),
        "barrier_discount": round((1 - price / vanilla_price) * 100, 2)
            if vanilla_price > 0 else 0,
        "engine": "QuantLib AnalyticBarrierEngine",
        "params": {
            "S": S, "K": K, "T": T, "barrier": barrier,
            "barrier_type": barrier_type, "option_type": option_type,
            "rebate": rebate,
        },
    }


def _py_barrier_mc(S, K, T, r, q, sigma, barrier, barrier_type, option_type, rebate,
                    n_paths=50000, n_steps=252):
    """Monte Carlo barrier option pricing fallback."""
    np.random.seed(42)
    dt = T / n_steps
    paths = np.zeros((n_paths, n_steps + 1))
    paths[:, 0] = S

    for t in range(1, n_steps + 1):
        z = np.random.standard_normal(n_paths)
        paths[:, t] = paths[:, t-1] * np.exp((r - q - 0.5*sigma**2)*dt + sigma*np.sqrt(dt)*z)

    # Check barrier conditions
    if barrier_type == "Down-and-Out":
        knocked = np.any(paths <= barrier, axis=1)
        alive = ~knocked
    elif barrier_type == "Up-and-Out":
        knocked = np.any(paths >= barrier, axis=1)
        alive = ~knocked
    elif barrier_type == "Down-and-In":
        alive = np.any(paths <= barrier, axis=1)
    elif barrier_type == "Up-and-In":
        alive = np.any(paths >= barrier, axis=1)
    else:
        alive = np.ones(n_paths, dtype=bool)

    final = paths[:, -1]
    if option_type == "call":
        payoffs = np.maximum(final - K, 0)
    else:
        payoffs = np.maximum(K - final, 0)

    payoffs[~alive] = rebate
    price = float(np.exp(-r * T) * payoffs.mean())

    # Vanilla for comparison
    vanilla_payoffs = np.maximum(final - K, 0) if option_type == "call" \
        else np.maximum(K - final, 0)
    vanilla_price = float(np.exp(-r * T) * vanilla_payoffs.mean())

    return {
        "price": round(price, 6),
        "vanilla_price": round(vanilla_price, 6),
        "barrier_discount": round((1 - price / vanilla_price) * 100, 2)
            if vanilla_price > 0 else 0,
        "engine": "Python Monte Carlo (fallback)",
        "params": {
            "S": S, "K": K, "T": T, "barrier": barrier,
            "barrier_type": barrier_type, "option_type": option_type,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Korean Step-Down ELS Pricer (Multi-Asset MC)
# ═══════════════════════════════════════════════════════════════════════════════

def price_stepdown_els(
    spots: list[float],
    barriers: list[float] = None,
    knock_in: float = 50,
    coupon_rate: float = 0.08,
    r: float = 0.035,
    q: float = 0.0,
    sigmas: list[float] = None,
    corr_matrix: list[list[float]] | None = None,
    T: float = 3.0,
    n_paths: int = 10000,
    face_value: float = 10000,
    seed: int = 42,
) -> dict:
    """
    Price a Korean-style Step-Down ELS with 3 underlying assets.

    Structure:
      - 6-month evaluation periods (6 total over 3 years)
      - At each period: if min(S_i/S_i0) >= barrier[i]%, auto-call with coupon
      - At maturity: if knock-in triggered AND min(S_i/S_i0) < last barrier,
        principal loss proportional to worst performer
      - Otherwise: full principal + coupon

    Args:
        spots: initial spot prices [S1, S2, S3]
        barriers: auto-call barriers in % [95, 90, 85, 80, 75, 65]
        knock_in: knock-in barrier in %
        coupon_rate: annual coupon rate
        sigmas: volatilities for each asset
        corr_matrix: 3x3 correlation matrix (default: 0.5 pairwise)
    """
    if sigmas is None:
        sigmas = [0.25, 0.3, 0.28]
    if barriers is None:
        barriers = [95, 90, 85, 80, 75, 65]
    np.random.seed(seed)
    n_assets = len(spots)
    n_periods = len(barriers)
    dt = 0.5  # 6-month periods

    # Default correlation
    if corr_matrix is None:
        corr_matrix = np.full((n_assets, n_assets), 0.5)
        np.fill_diagonal(corr_matrix, 1.0)
    else:
        corr_matrix = np.array(corr_matrix)

    # Cholesky decomposition
    L = np.linalg.cholesky(corr_matrix)

    # Time grid: daily steps within each 6-month period
    steps_per_period = 126  # ~6 months of trading days
    total_steps = steps_per_period * n_periods

    # Simulate paths
    paths = np.zeros((n_paths, n_assets, total_steps + 1))
    for a in range(n_assets):
        paths[:, a, 0] = spots[a]

    daily_dt = dt / steps_per_period

    for t in range(1, total_steps + 1):
        z_indep = np.random.standard_normal((n_paths, n_assets))
        z_corr = z_indep @ L.T  # Apply correlation

        for a in range(n_assets):
            s = sigmas[a] if a < len(sigmas) else sigmas[0]
            drift = (r - q - 0.5 * s**2) * daily_dt
            diffusion = s * np.sqrt(daily_dt) * z_corr[:, a]
            paths[:, a, t] = paths[:, a, t-1] * np.exp(drift + diffusion)

    # Evaluate ELS payoff
    payoffs = np.zeros(n_paths)
    autocall_period = np.full(n_paths, -1)  # -1 = no autocall
    knock_in_triggered = np.zeros(n_paths, dtype=bool)

    # Check knock-in: min performance across all assets at any daily step
    for a in range(n_assets):
        min_ratio = paths[:, a, :].min(axis=1) / spots[a] * 100
        knock_in_triggered |= (min_ratio <= knock_in)

    for period in range(n_periods):
        step_idx = (period + 1) * steps_per_period
        barrier_pct = barriers[period]

        # Min performance at evaluation date
        perf = np.ones(n_paths) * 999
        for a in range(n_assets):
            ratio = paths[:, a, step_idx] / spots[a] * 100
            perf = np.minimum(perf, ratio)

        # Auto-call condition: not yet called AND min perf >= barrier
        not_called = autocall_period == -1
        autocall_mask = not_called & (perf >= barrier_pct)

        coupon = face_value * (1 + coupon_rate * (period + 1) * dt)
        payoffs[autocall_mask] = coupon
        autocall_period[autocall_mask] = period + 1

    # Maturity evaluation for non-autocalled paths
    not_called = autocall_period == -1
    final_perf = np.ones(n_paths) * 999
    for a in range(n_assets):
        ratio = paths[:, a, -1] / spots[a] * 100
        final_perf = np.minimum(final_perf, ratio)

    # Case 1: No knock-in OR final perf >= last barrier -> full principal + coupon
    safe = not_called & ((~knock_in_triggered) | (final_perf >= barriers[-1]))
    payoffs[safe] = face_value * (1 + coupon_rate * T)

    # Case 2: Knock-in triggered AND final perf < last barrier -> principal loss
    loss = not_called & knock_in_triggered & (final_perf < barriers[-1])
    payoffs[loss] = face_value * (final_perf[loss] / 100)

    # Discount payoffs
    discount_times = np.where(
        autocall_period > 0,
        autocall_period * dt,
        T,
    )
    pv_payoffs = payoffs * np.exp(-r * discount_times)
    fair_value = float(pv_payoffs.mean())

    # Statistics
    autocall_counts = {}
    for p in range(1, n_periods + 1):
        count = int((autocall_period == p).sum())
        autocall_counts[f"Period {p} ({p*6}M)"] = {
            "count": count,
            "probability": round(count / n_paths * 100, 2),
            "barrier": barriers[p - 1],
        }

    maturity_count = int(not_called.sum())
    ki_count = int(knock_in_triggered.sum())
    loss_count = int(loss.sum())

    return {
        "fair_value": round(fair_value, 2),
        "fair_value_pct": round(fair_value / face_value * 100, 2),
        "face_value": face_value,
        "annual_coupon_pct": round(coupon_rate * 100, 2),
        "autocall_statistics": autocall_counts,
        "maturity_statistics": {
            "reached_maturity": maturity_count,
            "maturity_probability": round(maturity_count / n_paths * 100, 2),
            "knock_in_triggered": ki_count,
            "knock_in_probability": round(ki_count / n_paths * 100, 2),
            "principal_loss_count": loss_count,
            "loss_probability": round(loss_count / n_paths * 100, 2),
        },
        "payoff_statistics": {
            "mean": round(float(payoffs.mean()), 2),
            "median": round(float(np.median(payoffs)), 2),
            "min": round(float(payoffs.min()), 2),
            "max": round(float(payoffs.max()), 2),
            "std": round(float(payoffs.std()), 2),
        },
        "params": {
            "n_assets": n_assets,
            "spots": spots,
            "barriers": barriers,
            "knock_in": knock_in,
            "sigmas": sigmas,
            "n_paths": n_paths,
            "T_years": T,
        },
    }
