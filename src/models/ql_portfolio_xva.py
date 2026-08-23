"""
Portfolio XVA & PCA Stress Test Engine
========================================
Counterparty credit risk (CVA, EE, PFE) and macro stress testing.

Phase 2: Expected Exposure profiling, CVA calculation
Phase 3: PCA-based yield curve stress test (Shift/Twist/Butterfly)
"""


import numpy as np

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Exposure Simulation & CVA
# ═══════════════════════════════════════════════════════════════════════════════

def simulate_exposure_profile(
    notional: float,
    fixed_rate: float,
    floating_rate: float,
    tenor_years: int,
    vol: float = 0.01,
    n_paths: int = 1000,
    n_obs: int = 40,
    a: float = 0.05,
    seed: int = 42,
) -> dict:
    """
    Simulate future exposure profile for an IRS portfolio.

    Uses Hull-White short-rate model:
      dr(t) = a*(theta(t) - r(t))*dt + sigma*dW(t)

    At each observation date, revalue the swap to get MTM exposure.

    Returns: EE (Expected Exposure), PFE (95%), EPE, time grid.
    """
    np.random.seed(seed)
    dt = tenor_years / n_obs
    times = np.linspace(0, tenor_years, n_obs + 1)[1:]  # exclude t=0

    sigma = vol
    r0 = floating_rate / 100
    fixed = fixed_rate / 100

    # Simulate short rate paths
    rates = np.zeros((n_paths, n_obs))
    rates[:, 0] = r0

    for t in range(1, n_obs):
        dW = np.random.normal(0, np.sqrt(dt), n_paths)
        rates[:, t] = rates[:, t-1] + a * (r0 - rates[:, t-1]) * dt + sigma * dW

    # Compute swap MTM at each observation point
    # Simplified: MTM ≈ Notional * (r_t - fixed) * remaining_annuity
    exposures = np.zeros((n_paths, n_obs))

    for t_idx in range(n_obs):
        remaining_years = tenor_years - times[t_idx]
        if remaining_years <= 0:
            continue
        # Remaining annuity (simplified)
        n_remaining = max(1, int(remaining_years))
        annuity = sum(np.exp(-rates[:, t_idx:t_idx+1] * k)[:, 0]
                      for k in range(1, n_remaining + 1))
        annuity = annuity / n_remaining  # average

        mtm = notional * (rates[:, t_idx] - fixed) * annuity * remaining_years / tenor_years
        exposures[:, t_idx] = mtm

    # Positive exposure only (counterparty risk = max(MTM, 0))
    positive_exposure = np.maximum(exposures, 0)

    # EE: Expected Exposure (mean of positive exposures at each time)
    ee = positive_exposure.mean(axis=0)

    # PFE: Potential Future Exposure (95th percentile)
    pfe_95 = np.percentile(positive_exposure, 95, axis=0)
    pfe_99 = np.percentile(positive_exposure, 99, axis=0)

    # EPE: Expected Positive Exposure (time-weighted average of EE)
    try:
        epe = float(np.trapezoid(ee, times) / tenor_years)
    except AttributeError:
        epe = float(np.trapz(ee, times) / tenor_years)

    # Peak EE and PFE
    peak_ee = float(ee.max())
    peak_pfe = float(pfe_95.max())

    return {
        "times": [round(float(t), 3) for t in times],
        "ee": [round(float(v), 2) for v in ee],
        "pfe_95": [round(float(v), 2) for v in pfe_95],
        "pfe_99": [round(float(v), 2) for v in pfe_99],
        "epe": round(epe, 2),
        "peak_ee": round(peak_ee, 2),
        "peak_pfe_95": round(peak_pfe, 2),
        "notional": notional,
        "tenor_years": tenor_years,
        "n_paths": n_paths,
        "model_params": {"a": a, "sigma": vol, "r0": r0},
    }


def calculate_cva(
    ee_profile: list[float],
    times: list[float],
    hazard_rate: float = 0.02,
    recovery_rate: float = 0.40,
    risk_free_rate: float = 0.035,
) -> dict:
    """
    Calculate Credit Valuation Adjustment.

    CVA = (1 - R) * sum_i [ EE(t_i) * delta_PD(t_i) * DF(t_i) ]

    Where:
      delta_PD(t_i) = Q(t_{i-1}) - Q(t_i)  (marginal default probability)
      Q(t) = exp(-lambda * t)  (survival probability)
      DF(t) = exp(-r * t)  (discount factor)
    """
    lgd = 1 - recovery_rate
    n = len(times)

    cva = 0.0
    cva_components = []

    for i in range(n):
        t = times[i]
        t_prev = times[i - 1] if i > 0 else 0

        # Survival probabilities
        q_prev = np.exp(-hazard_rate * t_prev)
        q_curr = np.exp(-hazard_rate * t)

        # Marginal default probability
        delta_pd = q_prev - q_curr

        # Discount factor
        df = np.exp(-risk_free_rate * t)

        # CVA increment
        increment = lgd * ee_profile[i] * delta_pd * df
        cva += increment

        cva_components.append({
            "time": round(t, 3),
            "ee": round(float(ee_profile[i]), 2),
            "survival_prob": round(float(q_curr), 6),
            "marginal_pd": round(float(delta_pd), 6),
            "discount_factor": round(float(df), 6),
            "cva_increment": round(float(increment), 2),
        })

    # Annualized CVA as spread
    avg_ee = float(np.mean(ee_profile))
    tenor = times[-1] if times else 1
    cva_spread_bps = (cva / avg_ee / tenor * 10000) if avg_ee > 0 else 0

    return {
        "cva_amount": round(float(cva), 2),
        "cva_spread_bps": round(float(cva_spread_bps), 1),
        "loss_given_default": recovery_rate,
        "hazard_rate": hazard_rate,
        "implied_5y_pd": round(float(1 - np.exp(-hazard_rate * 5)) * 100, 2),
        "components": cva_components,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: PCA Yield Curve Stress Test
# ═══════════════════════════════════════════════════════════════════════════════

def extract_pca_components(
    n_tenors: int = 7,
) -> dict:
    """
    Generate stylized PCA components for yield curve stress testing.

    PC1 (Shift):     Parallel shift — all tenors move equally
    PC2 (Twist):     Steepening/flattening — short end vs long end
    PC3 (Butterfly): Curvature — belly vs wings

    In practice these would be extracted from historical rate covariance.
    Here we use the canonical shapes with realistic magnitudes.
    """
    tenors = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0][:n_tenors]

    # PC1: Parallel shift (explains ~80% of variance)
    pc1 = np.ones(n_tenors) / np.sqrt(n_tenors)

    # PC2: Twist (explains ~15%)
    pc2 = np.linspace(-1, 1, n_tenors)
    pc2 = pc2 / np.linalg.norm(pc2)

    # PC3: Butterfly (explains ~5%)
    x = np.linspace(-1, 1, n_tenors)
    pc3 = x**2 - np.mean(x**2)
    pc3 = pc3 / np.linalg.norm(pc3)

    # Typical shock magnitudes (in bps)
    # 1 standard deviation shock
    shock_1sd = {
        "shift": 50,      # 50 bps parallel
        "twist": 30,      # 30 bps steepening
        "butterfly": 15,  # 15 bps curvature
    }

    return {
        "tenors": tenors,
        "pc1_shift": [round(float(v), 4) for v in pc1],
        "pc2_twist": [round(float(v), 4) for v in pc2],
        "pc3_butterfly": [round(float(v), 4) for v in pc3],
        "variance_explained": [80.0, 15.0, 5.0],
        "shock_1sd_bps": shock_1sd,
    }


def apply_pca_stress(
    base_rates_pct: list[float],
    tenors: list[float],
    shift_mult: float = 0.0,
    twist_mult: float = 0.0,
    butterfly_mult: float = 0.0,
) -> dict:
    """
    Apply PCA-based stress to a yield curve.

    Each multiplier is in units of standard deviations.
    E.g., shift_mult=2.0 means a 2-sigma parallel shift.

    Returns: stressed curve + PnL impact on a sample portfolio.
    """
    pca = extract_pca_components(len(tenors))
    pc1 = np.array(pca["pc1_shift"])
    pc2 = np.array(pca["pc2_twist"])
    pc3 = np.array(pca["pc3_butterfly"])
    shocks = pca["shock_1sd_bps"]

    # Total stress in bps
    stress_bps = (
        shift_mult * shocks["shift"] * pc1 +
        twist_mult * shocks["twist"] * pc2 +
        butterfly_mult * shocks["butterfly"] * pc3
    )

    base = np.array(base_rates_pct)
    stressed = base + stress_bps / 100  # Convert bps to %

    return {
        "tenors": tenors,
        "base_rates_pct": [round(float(r), 4) for r in base],
        "stressed_rates_pct": [round(float(r), 4) for r in stressed],
        "stress_bps": [round(float(s), 1) for s in stress_bps],
        "multipliers": {
            "shift": shift_mult,
            "twist": twist_mult,
            "butterfly": butterfly_mult,
        },
    }


def portfolio_stress_pnl(
    base_rates_pct: list[float],
    tenors: list[float],
    shift_mult: float,
    twist_mult: float,
    butterfly_mult: float,
    portfolio_dv01: float = 100000,
    portfolio_convexity: float = 5000,
) -> dict:
    """
    Estimate portfolio PnL under PCA stress scenario.

    Uses duration + convexity approximation:
      dP ≈ -DV01 * dR + 0.5 * Convexity * dR^2

    Where dR is the average rate change weighted by DV01 distribution.
    """
    stress = apply_pca_stress(base_rates_pct, tenors,
                               shift_mult, twist_mult, butterfly_mult)

    stress_bps = np.array(stress["stress_bps"])

    # Weighted average rate change (assumes equal DV01 across curve)
    avg_stress_bps = float(np.mean(stress_bps))
    avg_stress_bps / 10000  # decimal

    # Duration PnL
    duration_pnl = -portfolio_dv01 * avg_stress_bps
    # Convexity PnL
    convexity_pnl = 0.5 * portfolio_convexity * (avg_stress_bps ** 2) / 100
    # Total
    total_pnl = duration_pnl + convexity_pnl

    # Per-component attribution
    pca = extract_pca_components(len(tenors))
    shift_bps = float(shift_mult * pca["shock_1sd_bps"]["shift"] * np.mean(pca["pc1_shift"]))
    twist_bps = float(twist_mult * pca["shock_1sd_bps"]["twist"] * np.mean(pca["pc2_twist"]))
    butterfly_bps = float(butterfly_mult * pca["shock_1sd_bps"]["butterfly"] * np.mean(pca["pc3_butterfly"]))

    return {
        "total_pnl": round(total_pnl, 0),
        "duration_pnl": round(duration_pnl, 0),
        "convexity_pnl": round(convexity_pnl, 0),
        "avg_stress_bps": round(avg_stress_bps, 1),
        "stress_curve": stress,
        "pnl_attribution": {
            "shift_pnl": round(-portfolio_dv01 * shift_bps, 0),
            "twist_pnl": round(-portfolio_dv01 * twist_bps, 0),
            "butterfly_pnl": round(-portfolio_dv01 * butterfly_bps, 0),
        },
        "portfolio_params": {
            "dv01": portfolio_dv01,
            "convexity": portfolio_convexity,
        },
    }
