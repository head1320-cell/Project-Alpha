"""
Credit Spread Risk & Incremental Default Risk (IDR) Engine
==========================================================
Measures credit-dependent trading book risks per Basel II.5 / FRTB.

Reference: FRM Part II, Readings 18 (FRTB), 28 (Credit VaR), 63 (IRC/IDR)

Components:
  1. Rating Transition Matrix — S&P-based 1Y migration probabilities
  2. Credit Spread Risk — MtM loss from rating migration + spread changes
  3. Credit Spread VaR — Historical simulation of spread-driven P&L
  4. Vasicek WCDR — Worst-case default rate (Gaussian copula, 99.9% VaR)
  5. IDR Capital Charge — 99.9% VaR, 1-year horizon, all defaultable assets
  6. IRC — Incremental Risk Charge (spread risk + default risk combined)

Key concepts:
  - Credit spread risk: mark-to-market change from spread widening/tightening
  - Jump-to-default risk: sudden loss from issuer default → IDR charge
  - IRC assumes constant level of risk: defaulted/downgraded bonds replaced
  - IDR: 99.9% VaR, 1-year time horizon (same as banking book)
  - FRTB replaces IRC with ES-based approach for spread risk
"""

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Rating Transition Matrix (S&P 1981-2020 based)
# ═══════════════════════════════════════════════════════════════════════════════

RATING_GRADES = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "D"]

# 1-Year transition matrix (%) — rows = initial rating, cols = end rating
# Source: S&P Global Ratings (1981–2020 averages), FRM Reading 28 Figure 28.1
TRANSITION_MATRIX_1Y = np.array([
    # AAA     AA      A      BBB     BB      B      CCC     D
    [89.85,  8.94,  0.78,   0.15,  0.10,  0.05,  0.03,  0.10],  # AAA
    [ 0.50, 90.76,  8.08,   0.47,  0.06,  0.05,  0.02,  0.06],  # AA
    [ 0.04,  1.73, 91.96,   5.49,  0.48,  0.15,  0.04,  0.11],  # A
    [ 0.01,  0.11,  3.68,  90.58,  4.22,  0.88,  0.21,  0.31],  # BBB
    [ 0.01,  0.03,  0.14,   5.26, 84.09,  7.91,  1.08,  1.48],  # BB
    [ 0.00,  0.03,  0.10,   0.24,  5.41, 83.49,  5.00,  5.73],  # B
    [ 0.00,  0.00,  0.17,   0.33,  0.81,  9.93, 60.24, 28.52],  # CCC
    [ 0.00,  0.00,  0.00,   0.00,  0.00,  0.00,  0.00,100.00],  # D
]) / 100.0

# Representative credit spreads by rating (bps over risk-free)
CREDIT_SPREADS_BPS: dict[str, float] = {
    "AAA": 30,  "AA": 50,  "A": 80,  "BBB": 150,
    "BB": 300,  "B": 500,  "CCC": 900, "D": 5000,
}

# Representative 1Y default probabilities (from transition matrix)
DEFAULT_PROBS: dict[str, float] = {
    g: TRANSITION_MATRIX_1Y[i, -1] for i, g in enumerate(RATING_GRADES)
}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Data Structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CreditPosition:
    """A credit-sensitive position in the trading book."""
    name: str
    rating: str                  # current credit rating
    notional: float              # face / notional value
    modified_duration: float     # interest rate sensitivity
    recovery_rate: float = 0.40  # assumed RR in default
    liquidity_horizon_months: int = 3  # IRC rebalancing frequency


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Credit Spread Risk Engine
# ═══════════════════════════════════════════════════════════════════════════════

class CreditSpreadRiskEngine:
    """
    Compute mark-to-market changes from credit spread movements
    driven by rating migration.

    ΔP ≈ −ModDur × Notional × Δspread
    """

    def __init__(self):
        self.transition_matrix = TRANSITION_MATRIX_1Y
        self.spreads = CREDIT_SPREADS_BPS

    def rating_index(self, rating: str) -> int:
        return RATING_GRADES.index(rating.upper())

    # ─── Spread change from migration ────────────────────────────────────────

    def migration_pnl(self, position: CreditPosition) -> dict:
        """
        Compute expected P&L for each possible rating migration.

        For each end-state rating j:
          Δspread = spread_j − spread_current
          ΔP = −ModDur × Notional × Δspread / 10000
          Prob = transition_matrix[current][j]
        """
        idx = self.rating_index(position.rating)
        current_spread = self.spreads[position.rating]

        scenarios = []
        for j, end_rating in enumerate(RATING_GRADES):
            if end_rating == "D":
                # Default: loss = Notional × LGD
                pnl = -position.notional * (1 - position.recovery_rate)
            else:
                spread_change = self.spreads[end_rating] - current_spread
                pnl = -position.modified_duration * position.notional * spread_change / 10_000

            prob = self.transition_matrix[idx, j]
            scenarios.append({
                "end_rating": end_rating,
                "probability": round(float(prob), 6),
                "spread_change_bps": round(float(self.spreads.get(end_rating, 0) - current_spread), 1),
                "pnl": round(float(pnl), 0),
                "prob_weighted_pnl": round(float(prob * pnl), 0),
            })

        expected_loss = sum(s["prob_weighted_pnl"] for s in scenarios)
        # Credit spread VaR: 99th percentile loss
        sorted_scenarios = sorted(scenarios, key=lambda s: s["pnl"])
        cumulative_prob = 0.0
        var_99 = 0.0
        for s in sorted_scenarios:
            cumulative_prob += s["probability"]
            if cumulative_prob >= 0.01:  # 1st percentile = 99% VaR
                var_99 = abs(s["pnl"])
                break

        return {
            "position": position.name,
            "current_rating": position.rating,
            "current_spread_bps": current_spread,
            "expected_loss": round(expected_loss, 0),
            "credit_spread_var_99": round(var_99, 0),
            "scenarios": scenarios,
        }

    # ─── Portfolio credit spread VaR ─────────────────────────────────────────

    def portfolio_credit_spread_var(
        self,
        positions: list[CreditPosition],
        n_simulations: int = 50_000,
        confidence: float = 0.999,
        seed: int = 42,
    ) -> dict:
        """
        Monte Carlo credit spread VaR for a portfolio.

        For each simulation:
          1. Sample rating migration for each position (independent)
          2. Compute portfolio P&L
        Extract VaR at the given confidence level.
        """
        rng = np.random.default_rng(seed)
        n_pos = len(positions)
        portfolio_pnl = np.zeros(n_simulations)

        for _p_idx, pos in enumerate(positions):
            r_idx = self.rating_index(pos.rating)
            probs = self.transition_matrix[r_idx]
            current_spread = self.spreads[pos.rating]

            # Sample end-ratings for all simulations at once
            end_ratings = rng.choice(len(RATING_GRADES), size=n_simulations, p=probs)

            for sim in range(n_simulations):
                j = end_ratings[sim]
                end_rating = RATING_GRADES[j]
                if end_rating == "D":
                    pnl = -pos.notional * (1 - pos.recovery_rate)
                else:
                    ds = self.spreads[end_rating] - current_spread
                    pnl = -pos.modified_duration * pos.notional * ds / 10_000
                portfolio_pnl[sim] += pnl

        losses = -portfolio_pnl
        alpha_pct = (1 - confidence) * 100
        var_amount = float(np.percentile(losses, 100 - alpha_pct))
        tail = losses[losses >= var_amount]
        es_amount = float(tail.mean()) if len(tail) > 0 else var_amount

        expected_loss = float(np.mean(losses))

        return {
            "n_positions": n_pos,
            "n_simulations": n_simulations,
            "confidence_level": confidence,
            "credit_spread_var": round(var_amount, 0),
            "credit_spread_es": round(es_amount, 0),
            "expected_loss": round(expected_loss, 0),
            "worst_loss": round(float(np.max(losses)), 0),
            "pnl_std": round(float(np.std(portfolio_pnl)), 0),
        }

    # ─── Multi-year transition matrix ────────────────────────────────────────

    @staticmethod
    def multi_year_transition(n_years: int) -> np.ndarray:
        """
        n-year transition matrix = (1Y matrix)^n

        Accounts for compounding migration probabilities.
        """
        result = TRANSITION_MATRIX_1Y.copy()
        for _ in range(n_years - 1):
            result = result @ TRANSITION_MATRIX_1Y
        return result

    def cumulative_default_prob(self, rating: str, n_years: int) -> float:
        """Cumulative PD over n years from transition matrix."""
        mat = self.multi_year_transition(n_years)
        idx = self.rating_index(rating)
        return float(mat[idx, -1])  # D column


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Vasicek WCDR & IDR
# ═══════════════════════════════════════════════════════════════════════════════

class IncrementalDefaultRisk:
    """
    Incremental Default Risk (IDR) charge.

    IDR = 99.9% VaR, 1-year horizon, for all defaultable trading book assets.

    Uses Vasicek's Gaussian copula model:
      WCDR(T,X) = Φ[ (Φ⁻¹(PD) + √ρ·Φ⁻¹(X)) / √(1−ρ) ]

    Capital = Σ EAD_i × LGD_i × WCDR_i  −  Σ EAD_i × LGD_i × PD_i
              (VaR at 99.9%)               (Expected Loss)
    """

    @staticmethod
    def vasicek_wcdr(
        pd: float,
        rho: float,
        confidence: float = 0.999,
    ) -> float:
        """
        Worst-Case Default Rate at given confidence level.

        WCDR = Φ[ (Φ⁻¹(PD) + √ρ × Φ⁻¹(X)) / √(1 − ρ) ]
        """
        if pd <= 0:
            return 0.0
        if pd >= 1:
            return 1.0

        phi_inv_pd = norm.ppf(pd)
        phi_inv_x = norm.ppf(confidence)

        wcdr = norm.cdf(
            (phi_inv_pd + np.sqrt(rho) * phi_inv_x) / np.sqrt(1 - rho)
        )
        return float(wcdr)

    @staticmethod
    def basel_correlation(pd: float) -> float:
        """
        Basel IRB correlation function for corporate exposures.

        ρ = 0.12 × (1 − e^{−50×PD}) / (1 − e^{−50})
          + 0.24 × [1 − (1 − e^{−50×PD}) / (1 − e^{−50})]
        """
        k = (1 - np.exp(-50 * pd)) / (1 - np.exp(-50))
        return 0.12 * k + 0.24 * (1 - k)

    def calculate_idr(
        self,
        positions: list[CreditPosition],
        correlation_override: float | None = None,
    ) -> dict:
        """
        Calculate IDR capital charge for a portfolio of credit positions.

        IDR = Σ EAD_i × LGD_i × WCDR_i  −  EL
        """
        results = []
        total_var = 0.0
        total_el = 0.0

        for pos in positions:
            pd = DEFAULT_PROBS.get(pos.rating, 0.01)
            lgd = 1.0 - pos.recovery_rate
            ead = pos.notional

            rho = correlation_override if correlation_override else self.basel_correlation(pd)
            wcdr = self.vasicek_wcdr(pd, rho)

            var_i = ead * lgd * wcdr
            el_i = ead * lgd * pd

            total_var += var_i
            total_el += el_i

            results.append({
                "name": pos.name,
                "rating": pos.rating,
                "ead": round(ead, 0),
                "pd": round(pd, 6),
                "lgd": round(lgd, 4),
                "correlation": round(rho, 4),
                "wcdr": round(wcdr, 6),
                "var_contribution": round(var_i, 0),
                "expected_loss": round(el_i, 0),
            })

        idr_charge = total_var - total_el

        return {
            "idr_capital_charge": round(idr_charge, 0),
            "total_var_999": round(total_var, 0),
            "total_expected_loss": round(total_el, 0),
            "confidence_level": 0.999,
            "time_horizon": "1 year",
            "n_positions": len(positions),
            "position_details": results,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. IRC — Incremental Risk Charge (Combined)
# ═══════════════════════════════════════════════════════════════════════════════

class IncrementalRiskCharge:
    """
    IRC = Credit Spread Risk + Jump-to-Default Risk

    Combines:
      - Credit spread VaR from rating migration (CreditMetrics-style)
      - IDR from Vasicek WCDR model
      - Liquidity horizon adjustment (constant level of risk assumption)

    Under constant level of risk: positions that deteriorate are replaced
    at each liquidity horizon boundary.
    """

    def __init__(self):
        self.spread_engine = CreditSpreadRiskEngine()
        self.idr_engine = IncrementalDefaultRisk()

    def calculate_irc(
        self,
        positions: list[CreditPosition],
        n_simulations: int = 50_000,
        seed: int = 42,
    ) -> dict:
        """
        Full IRC calculation.

        Returns:
          - Per-position migration analysis
          - Portfolio credit spread VaR (MC simulation)
          - IDR capital charge (Vasicek WCDR)
          - Combined IRC
          - Liquidity horizon summary
        """
        # 1. Per-position migration analysis
        migration_results = []
        for pos in positions:
            mig = self.spread_engine.migration_pnl(pos)
            migration_results.append(mig)

        # 2. Portfolio credit spread VaR (MC)
        spread_var_result = self.spread_engine.portfolio_credit_spread_var(
            positions, n_simulations=n_simulations, seed=seed,
        )

        # 3. IDR capital charge
        idr_result = self.idr_engine.calculate_idr(positions)

        # 4. Liquidity horizon summary
        lh_groups: dict[int, list] = {}
        for pos in positions:
            lh = pos.liquidity_horizon_months
            if lh not in lh_groups:
                lh_groups[lh] = []
            lh_groups[lh].append(pos.name)

        lh_adjustment = self._liquidity_horizon_scaling(positions)

        # 5. Combined IRC
        # IRC = max(spread_var, IDR_charge) in simplified form
        # More precisely: IRC incorporates both migration and default
        spread_component = spread_var_result["credit_spread_var"]
        default_component = idr_result["idr_capital_charge"]
        irc_total = spread_component + default_component

        # Apply LH scaling
        irc_lh_adjusted = irc_total * lh_adjustment

        return {
            "irc_total": round(irc_total, 0),
            "irc_lh_adjusted": round(irc_lh_adjusted, 0),
            "spread_risk_component": round(spread_component, 0),
            "default_risk_component": round(default_component, 0),
            "lh_scaling_factor": round(lh_adjustment, 4),
            "spread_var_detail": spread_var_result,
            "idr_detail": idr_result,
            "migration_analysis": migration_results,
            "liquidity_horizons": {
                f"{lh}M": names for lh, names in sorted(lh_groups.items())
            },
            "transition_matrix": {
                "ratings": RATING_GRADES,
                "matrix": [[round(float(v), 4) for v in row]
                           for row in TRANSITION_MATRIX_1Y],
            },
        }

    @staticmethod
    def _liquidity_horizon_scaling(positions: list[CreditPosition]) -> float:
        """
        Liquidity horizon adjustment factor.

        Under constant level of risk, positions are rebalanced at LH intervals.
        Shorter LH → less risk → lower scaling.

        Scaling ≈ √(12 / average_LH_months) normalised so 12M = 1.0
        """
        if not positions:
            return 1.0
        total_notional = sum(p.notional for p in positions)
        if total_notional == 0:
            return 1.0
        weighted_lh = sum(
            p.notional * p.liquidity_horizon_months for p in positions
        ) / total_notional
        # √(avg_LH / 12) — longer LH = higher scaling
        return float(np.sqrt(weighted_lh / 12.0))

    # ─── Convenience: single-position analysis ───────────────────────────────

    def single_position_report(
        self,
        name: str,
        rating: str,
        notional: float,
        modified_duration: float,
        recovery_rate: float = 0.40,
    ) -> dict:
        """Quick analysis for a single credit position."""
        pos = CreditPosition(
            name=name, rating=rating, notional=notional,
            modified_duration=modified_duration, recovery_rate=recovery_rate,
        )
        return self.calculate_irc([pos])
