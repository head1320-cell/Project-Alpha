"""
FRTB Expected Shortfall Engine
===============================
Implements the Fundamental Review of the Trading Book (Basel III)
Internal Models-Based Approach (IMA) for market risk capital.

Reference: FRM Part II, Reading 18 — FRTB (Basel Committee, Dec 2014)

Key changes from Basel I/II.5:
  - VaR 99% → ES 97.5%  (captures tail risk beyond VaR threshold)
  - Stressed VaR add-on → Stressed ES exclusively (250-day stress window)
  - Flat 10-day LH → 5 liquidity horizon categories (10/20/40/60/120 days)
  - Liquidity-adjusted ES via nested IMA waterfall formula

ES 97.5% for normal: µ + 2.338σ  (≈ VaR 99%: µ + 2.326σ)
For fat-tailed distributions, ES 97.5% >> VaR 99%.

Liquidity-adjusted ES (IMA):
  ES_LH = √[ ES₁² + Σⱼ₌₂⁵ ES_j² · (LH_j − LH_{j-1}) / 10 ]

  where ES_j = 10-day ES shocking categories j..5, holding 1..(j-1) constant.

Capital charge:
  IMCC = max(ES_recent, ES_stressed) × multiplier
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm

# ═══════════════════════════════════════════════════════════════════════════════
# FRTB Liquidity Horizon Categories
# ═══════════════════════════════════════════════════════════════════════════════

# Basel FRTB risk factor → LH category mapping (Figure 18.2)
LIQUIDITY_HORIZON_MAP: dict[str, int] = {
    # Category 1: LH = 10 days
    "large_cap_equity":         10,
    "ig_sovereign_bond":        10,
    "major_fx":                 10,
    "interest_rate_major":      10,
    # Category 2: LH = 20 days
    "small_cap_equity":         20,
    "ig_corporate_bond":        20,
    "ig_sovereign_spread":      20,
    "minor_fx":                 20,
    # Category 3: LH = 40 days
    "listed_equity_option":     40,
    "ig_corporate_spread":      40,
    "commodity_energy":         40,
    # Category 4: LH = 60 days
    "nig_corporate_spread":     60,
    "commodity_other":          60,
    "exotic_fx":                60,
    # Category 5: LH = 120 days
    "structured_credit":        120,
    "illiquid_equity":          120,
    "securitisation":           120,
    "correlation_trading":      120,
}

LH_CATEGORIES = [10, 20, 40, 60, 120]  # sorted ascending


@dataclass
class RiskPosition:
    """A single risk position with its factor type and weight."""
    name: str
    risk_factor_type: str       # key into LIQUIDITY_HORIZON_MAP
    weight: float               # portfolio weight or notional fraction
    returns: pd.Series = field(repr=False, default=None)

    @property
    def liquidity_horizon(self) -> int:
        return LIQUIDITY_HORIZON_MAP.get(self.risk_factor_type, 10)

    @property
    def lh_category(self) -> int:
        lh = self.liquidity_horizon
        for cat in LH_CATEGORIES:
            if lh <= cat:
                return cat
        return 120


# ═══════════════════════════════════════════════════════════════════════════════
# Core ES Calculations
# ═══════════════════════════════════════════════════════════════════════════════

class FRTBExpectedShortfall:
    """
    FRTB-aligned Expected Shortfall engine.

    Computes:
      1. ES at 97.5% confidence (replacing VaR 99%)
      2. Stressed ES over a 250-day stress window
      3. Liquidity-adjusted ES via IMA nested waterfall
      4. Regulatory capital charge with multiplier
    """

    FRTB_CONFIDENCE = 0.975   # 97.5% ES replaces 99% VaR
    STRESS_WINDOW = 250       # trading days (≈ 1 year)
    BASE_MULTIPLIER = 1.5     # Basel floor multiplier

    def __init__(self, confidence_level: float = None):
        self.cl = confidence_level or self.FRTB_CONFIDENCE

    # ─── 1. ES 97.5% (Parametric — Normal) ──────────────────────────────────

    def parametric_es(
        self, returns: pd.Series, portfolio_value: float
    ) -> dict:
        """
        Parametric ES at 97.5% under normal distribution.

        ES_α = µ + σ · φ(Φ⁻¹(α)) / (1 − α)

        For 97.5%: ES ≈ µ + 2.338σ  (cf. VaR 99% ≈ µ + 2.326σ)
        """
        mu = float(returns.mean())
        sigma = float(returns.std())
        alpha = 1 - self.cl  # 0.025

        z_alpha = norm.ppf(alpha)
        es_pct = -(mu - sigma * norm.pdf(z_alpha) / alpha)
        es_amount = max(es_pct * portfolio_value, 0)

        # Compare with legacy VaR 99%
        var_99_pct = -(mu - norm.ppf(0.99) * sigma)
        var_99_amount = max(var_99_pct * portfolio_value, 0)

        return {
            "es_975_pct": round(float(es_pct), 6),
            "es_975_amount": round(float(es_amount), 0),
            "var_99_pct": round(float(var_99_pct), 6),
            "var_99_amount": round(float(var_99_amount), 0),
            "es_var_ratio": round(float(es_amount / var_99_amount), 4) if var_99_amount > 0 else 0,
            "mu_daily": round(mu, 8),
            "sigma_daily": round(sigma, 6),
        }

    # ─── 2. ES 97.5% (Historical Simulation) ────────────────────────────────

    @staticmethod
    def historical_es(
        returns: pd.Series,
        portfolio_value: float,
        confidence_level: float = 0.975,
    ) -> dict:
        """
        Non-parametric ES: mean of losses beyond the (1-α) quantile.

        ES = E[Loss | Loss > VaR_α]
        """
        losses = -(returns * portfolio_value)
        alpha_pct = (1 - confidence_level) * 100  # 2.5
        var_threshold = float(np.percentile(losses, 100 - alpha_pct))
        tail_losses = losses[losses >= var_threshold]
        es_amount = float(tail_losses.mean()) if len(tail_losses) > 0 else var_threshold

        return {
            "var_threshold": round(var_threshold, 0),
            "es_amount": round(es_amount, 0),
            "n_tail_obs": int(len(tail_losses)),
            "n_total_obs": int(len(losses)),
            "tail_pct": round(len(tail_losses) / len(losses) * 100, 2),
        }

    # ─── 3. Stressed ES (250-day stress window) ─────────────────────────────

    def stressed_es(
        self,
        returns: pd.Series,
        portfolio_value: float,
        stress_window: int = None,
    ) -> dict:
        """
        Identify the worst 250-day window and compute ES on that period.

        Banks self-select the 250-day window most adverse to their portfolio.
        Here we automate: scan all possible 250-day windows, pick the one
        with the highest ES.
        """
        window = stress_window or self.STRESS_WINDOW
        n = len(returns)
        if n < window:
            return self._stress_fallback(returns, portfolio_value)

        best_es = 0.0
        best_start = 0
        best_end = 0

        # Scan windows (step by 5 for efficiency on large datasets)
        step = max(1, (n - window) // 200)
        for start in range(0, n - window + 1, step):
            window_returns = returns.iloc[start: start + window]
            losses = -(window_returns.values * portfolio_value)

            alpha_pct = (1 - self.cl) * 100
            var_t = float(np.percentile(losses, 100 - alpha_pct))
            tail = losses[losses >= var_t]
            es_val = float(tail.mean()) if len(tail) > 0 else var_t

            if es_val > best_es:
                best_es = es_val
                best_start = start
                best_end = start + window

        # Recompute exact ES on the identified window
        stress_returns = returns.iloc[best_start:best_end]
        stress_losses = -(stress_returns.values * portfolio_value)
        alpha_pct = (1 - self.cl) * 100
        var_t = float(np.percentile(stress_losses, 100 - alpha_pct))
        tail = stress_losses[stress_losses >= var_t]
        stressed_es_val = float(tail.mean()) if len(tail) > 0 else var_t

        # Current-period ES for comparison
        recent_losses = -(returns.values * portfolio_value)
        var_recent = float(np.percentile(recent_losses, 100 - alpha_pct))
        tail_recent = recent_losses[recent_losses >= var_recent]
        current_es = float(tail_recent.mean()) if len(tail_recent) > 0 else var_recent

        stress_dates = (
            stress_returns.index[[0, -1]].strftime("%Y-%m-%d").tolist()
            if hasattr(stress_returns.index, "strftime")
            else [best_start, best_end]
        )

        return {
            "current_es_975": round(current_es, 0),
            "stressed_es_975": round(stressed_es_val, 0),
            "stress_ratio": round(stressed_es_val / current_es, 4) if current_es > 0 else 0,
            "stress_window_start": stress_dates[0],
            "stress_window_end": stress_dates[1],
            "stress_window_days": window,
            "stress_window_vol": round(float(stress_returns.std()) * np.sqrt(252), 4),
            "current_vol": round(float(returns.std()) * np.sqrt(252), 4),
        }

    def _stress_fallback(self, returns, portfolio_value):
        """Fallback when data is shorter than stress window."""
        losses = -(returns.values * portfolio_value)
        alpha_pct = (1 - self.cl) * 100
        var_t = float(np.percentile(losses, 100 - alpha_pct))
        tail = losses[losses >= var_t]
        es_val = float(tail.mean()) if len(tail) > 0 else var_t
        return {
            "current_es_975": round(es_val, 0),
            "stressed_es_975": round(es_val, 0),
            "stress_ratio": 1.0,
            "stress_window_start": "N/A (insufficient data)",
            "stress_window_end": "N/A",
            "stress_window_days": len(returns),
            "stress_window_vol": round(float(returns.std()) * np.sqrt(252), 4),
            "current_vol": round(float(returns.std()) * np.sqrt(252), 4),
        }

    # ─── 4. Liquidity-Adjusted ES (IMA Nested Waterfall) ────────────────────

    @staticmethod
    def liquidity_adjusted_es(
        positions: list[RiskPosition],
        portfolio_value: float,
        confidence_level: float = 0.975,
    ) -> dict:
        """
        FRTB IMA liquidity-adjusted ES via nested waterfall.

        ES_LH = √[ ES₁² + Σⱼ₌₂⁵ ES_j² · (LH_j − LH_{j-1}) / 10 ]

        ES_j = 10-day ES shocking categories j..5, holding 1..(j-1) constant.
        """
        # Group positions by LH category
        cat_positions: dict[int, list[RiskPosition]] = {lh: [] for lh in LH_CATEGORIES}
        for pos in positions:
            cat_positions[pos.lh_category].append(pos)

        # Compute ES_j for each nested shock level
        # ES_j shocks categories j..5, holds 1..(j-1) constant
        es_components = {}
        cat_es_details = {}

        for j_idx, lh_j in enumerate(LH_CATEGORIES):
            # Positions shocked: categories j..5
            shocked_positions = []
            for cat_lh in LH_CATEGORIES[j_idx:]:
                shocked_positions.extend(cat_positions[cat_lh])

            if not shocked_positions:
                es_components[lh_j] = 0.0
                cat_es_details[lh_j] = {"es_10d": 0.0, "n_positions": 0}
                continue

            # Compute 10-day ES for the shocked subset
            combined_returns = pd.Series(dtype=float)
            total_weight = 0.0
            for pos in shocked_positions:
                if pos.returns is not None and len(pos.returns) > 0:
                    if combined_returns.empty:
                        combined_returns = pos.returns * pos.weight
                    else:
                        aligned = pos.returns.reindex(combined_returns.index, fill_value=0)
                        combined_returns = combined_returns + aligned * pos.weight
                    total_weight += pos.weight

            if combined_returns.empty or total_weight == 0:
                es_components[lh_j] = 0.0
                cat_es_details[lh_j] = {"es_10d": 0.0, "n_positions": len(shocked_positions)}
                continue

            # 10-day ES from daily returns (√10 scaling)
            losses = -(combined_returns.values * portfolio_value)
            alpha_pct = (1 - confidence_level) * 100
            var_t = float(np.percentile(losses, 100 - alpha_pct))
            tail = losses[losses >= var_t]
            es_10d = (float(tail.mean()) if len(tail) > 0 else var_t) * np.sqrt(10)

            es_components[lh_j] = es_10d
            cat_es_details[lh_j] = {
                "es_10d": round(es_10d, 0),
                "n_positions": len(shocked_positions),
            }

        # Apply the IMA waterfall formula
        # ES_LH = √[ ES₁² + Σⱼ₌₂⁵ ES_j² · (LH_j − LH_{j-1}) / 10 ]
        es_squared_sum = es_components[10] ** 2  # ES₁ (base)

        for j_idx in range(1, len(LH_CATEGORIES)):
            lh_j = LH_CATEGORIES[j_idx]
            lh_prev = LH_CATEGORIES[j_idx - 1]
            scaling = (lh_j - lh_prev) / 10.0
            es_squared_sum += es_components[lh_j] ** 2 * scaling

        es_liquidity_adjusted = np.sqrt(max(es_squared_sum, 0))

        # Base ES without LH adjustment (all at 10-day)
        es_base_10d = es_components.get(10, 0.0)

        # Position summary by category
        category_summary = {}
        for lh in LH_CATEGORIES:
            pos_list = cat_positions[lh]
            category_summary[f"LH_{lh}d"] = {
                "n_positions": len(pos_list),
                "position_names": [p.name for p in pos_list],
                "risk_factor_types": [p.risk_factor_type for p in pos_list],
                "es_component": cat_es_details[lh],
            }

        return {
            "es_liquidity_adjusted": round(float(es_liquidity_adjusted), 0),
            "es_base_10d": round(float(es_base_10d), 0),
            "lh_scaling_factor": round(
                float(es_liquidity_adjusted / es_base_10d), 4
            ) if es_base_10d > 0 else 0,
            "es_components": {
                f"ES_{lh}d": round(float(es_components[lh]), 0)
                for lh in LH_CATEGORIES
            },
            "category_summary": category_summary,
        }

    # ─── 5. Full FRTB Capital Charge ─────────────────────────────────────────

    def capital_charge(
        self,
        returns: pd.Series,
        portfolio_value: float,
        positions: list[RiskPosition] | None = None,
        multiplier: float = None,
    ) -> dict:
        """
        Full FRTB IMA regulatory capital calculation.

        IMCC = max(ES_recent, ES_stressed) × multiplier

        If positions with LH mapping are provided, applies liquidity adjustment.
        """
        mult = multiplier or self.BASE_MULTIPLIER

        # Parametric ES
        param = self.parametric_es(returns, portfolio_value)

        # Historical ES (current period)
        hist = self.historical_es(returns, portfolio_value, self.cl)

        # Stressed ES
        stressed = self.stressed_es(returns, portfolio_value)

        # Determine ES values
        current_es = stressed["current_es_975"]
        stress_es = stressed["stressed_es_975"]

        # Liquidity adjustment
        if positions:
            lh_result = self.liquidity_adjusted_es(positions, portfolio_value, self.cl)
            lh_factor = lh_result["lh_scaling_factor"]
            # Apply LH scaling to both current and stressed ES
            current_es_lh = current_es * lh_factor if lh_factor > 0 else current_es
            stress_es_lh = stress_es * lh_factor if lh_factor > 0 else stress_es
        else:
            lh_result = None
            lh_factor = 1.0
            current_es_lh = current_es
            stress_es_lh = stress_es

        # IMCC = max(current, stressed) × multiplier
        base_imcc = max(current_es_lh, stress_es_lh)
        capital = base_imcc * mult

        # Basel comparison: old VaR 99% + Stressed VaR
        var_99 = param["var_99_amount"]
        # Rough stressed VaR proxy
        stress_var_ratio = stressed["stress_ratio"]
        old_capital = (var_99 + var_99 * stress_var_ratio) * 3.0  # Basel II.5: 3× (VaR + SVaR)

        return {
            "framework": "FRTB IMA (Internal Models-Based Approach)",
            "confidence_level": self.cl,
            # ── ES Measures ──
            "parametric_es": param,
            "historical_es": hist,
            "stressed_es": stressed,
            # ── Liquidity Adjustment ──
            "liquidity_adjustment": lh_result,
            "lh_scaling_factor": round(lh_factor, 4),
            "current_es_lh_adjusted": round(current_es_lh, 0),
            "stressed_es_lh_adjusted": round(stress_es_lh, 0),
            # ── Capital Charge ──
            "multiplier": mult,
            "imcc_base": round(base_imcc, 0),
            "imcc_capital_charge": round(capital, 0),
            # ── Legacy Comparison ──
            "legacy_comparison": {
                "var_99": round(var_99, 0),
                "basel_ii5_capital": round(old_capital, 0),
                "frtb_capital": round(capital, 0),
                "change_pct": round(
                    (capital - old_capital) / old_capital * 100, 2
                ) if old_capital > 0 else 0,
                "interpretation": (
                    "FRTB 자본이 더 높음 → 꼬리 리스크가 VaR 99%를 초과"
                    if capital > old_capital
                    else "FRTB 자본이 더 낮음 → 현재 포트폴리오의 꼬리가 얇음"
                ),
            },
        }

    # ─── 6. Simplified single-ticker FRTB report ────────────────────────────

    def single_ticker_report(
        self,
        returns: pd.Series,
        portfolio_value: float,
        risk_factor_type: str = "large_cap_equity",
    ) -> dict:
        """
        Simplified FRTB report for a single-ticker analysis.
        Automatically creates a single RiskPosition and runs the full chain.
        """
        pos = RiskPosition(
            name="Single Asset",
            risk_factor_type=risk_factor_type,
            weight=1.0,
            returns=returns,
        )

        result = self.capital_charge(
            returns, portfolio_value, positions=[pos]
        )
        result["risk_factor_type"] = risk_factor_type
        result["liquidity_horizon_days"] = pos.liquidity_horizon
        result["observations"] = len(returns)

        return result
