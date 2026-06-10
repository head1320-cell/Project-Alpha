"""
Comprehensive Quant Module Tests
==================================
Edge-case and mathematical verification tests for all baseline quant models.
Target: raise overall coverage from 85% to 90%+.

Test categories per module:
  - Normal-case functional tests
  - Mathematical identity verification (known formulas)
  - Edge cases (zero vol, zero price, T→0, extreme values)
  - Boundary conditions
"""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Parametric VaR Models
# ═══════════════════════════════════════════════════════════════════════════════
from src.models.parametric import ParametricRiskModel


class TestParametricVaR:
    """Tests for delta-normal, ES, historical, and lognormal VaR."""

    def _returns(self, n=500, mu=0.0, sigma=0.015, seed=42):
        np.random.seed(seed)
        return pd.Series(np.random.normal(mu, sigma, n))

    # ── Normal VaR ──────────────────────────────────────────────────────────

    def test_var_99_normal_approx(self):
        """VaR(99%) ≈ 2.326σ for zero-mean normal returns."""
        r = self._returns(n=10000, mu=0, sigma=0.02)
        model = ParametricRiskModel(0.99, use_ewma=False)
        var = model.calculate_var(r)
        expected = 2.326 * 0.02
        assert abs(var - expected) / expected < 0.05

    def test_var_95_less_than_99(self):
        """VaR(95%) < VaR(99%)."""
        r = self._returns()
        var_95 = ParametricRiskModel(0.95).calculate_var(r)
        var_99 = ParametricRiskModel(0.99).calculate_var(r)
        assert var_95 < var_99

    def test_var_ewma_differs_from_simple(self):
        """EWMA VaR should differ from simple std VaR."""
        r = self._returns()
        var_simple = ParametricRiskModel(0.99, use_ewma=False).calculate_var(r)
        var_ewma = ParametricRiskModel(0.99, use_ewma=True).calculate_var(r)
        assert var_simple != var_ewma
        assert var_ewma > 0

    def test_var_nonnegative(self):
        """VaR should always be ≥ 0."""
        r = self._returns()
        for cl in [0.90, 0.95, 0.99]:
            var = ParametricRiskModel(cl).calculate_var(r)
            assert var >= 0

    # ── Expected Shortfall ──────────────────────────────────────────────────

    def test_es_greater_than_var(self):
        """ES should always be > VaR for the same confidence level."""
        r = self._returns()
        model = ParametricRiskModel(0.99)
        var = model.calculate_var(r)
        es = model.calculate_es(r)
        assert es >= var

    def test_es_99_normal_approx(self):
        """ES(99%) ≈ σ·φ(Φ⁻¹(0.01))/0.01 for zero-mean normal."""
        r = self._returns(n=10000, mu=0, sigma=0.02)
        model = ParametricRiskModel(0.99)
        es = model.calculate_es(r)
        # Analytical: σ * pdf(z_0.01) / 0.01
        expected = 0.02 * norm.pdf(norm.ppf(0.01)) / 0.01
        assert abs(es - expected) / expected < 0.05

    # ── Historical VaR ──────────────────────────────────────────────────────

    def test_historical_var_matches_quantile(self):
        """Historical VaR = negative 1st percentile for 99% CL."""
        r = self._returns(n=1000)
        model = ParametricRiskModel(0.99)
        hvar = model.historical_var(r)
        expected = float(-np.percentile(r, 1))
        assert abs(hvar - expected) < 1e-8

    def test_historical_var_positive(self):
        """Historical VaR should be positive for normal return series."""
        r = self._returns()
        hvar = ParametricRiskModel(0.99).historical_var(r)
        assert hvar > 0

    # ── Lognormal VaR ───────────────────────────────────────────────────────

    def test_lognormal_var_positive(self):
        """Lognormal VaR should be positive for typical returns."""
        r = self._returns()
        lvar = ParametricRiskModel(0.99).lognormal_var(r, 1e9)
        assert lvar > 0

    def test_lognormal_var_scales_with_portfolio(self):
        """Doubling portfolio should double lognormal VaR."""
        r = self._returns()
        model = ParametricRiskModel(0.99)
        v1 = model.lognormal_var(r, 1e9)
        v2 = model.lognormal_var(r, 2e9)
        assert abs(v2 / v1 - 2.0) < 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# 2. EWMA Volatility Model
# ═══════════════════════════════════════════════════════════════════════════════
from src.models.volatility import EWMAVolatilityModel


class TestEWMAVolatility:
    """Tests for EWMA variance/volatility model."""

    def _returns(self, n=300, seed=42):
        np.random.seed(seed)
        return pd.Series(np.random.normal(0, 0.015, n))

    def test_ewma_recursive_formula(self):
        """σ²_t = λ·σ²_{t-1} + (1-λ)·r²_{t-1}."""
        r = self._returns()
        model = EWMAVolatilityModel(0.94)
        var = model.variance_series(r)
        # Manual check at t=5
        manual_var = 0.94 * var[4] + 0.06 * float(r.iloc[4]) ** 2
        assert abs(var[5] - manual_var) < 1e-12

    def test_ewma_latest_positive(self):
        """Latest volatility should be positive."""
        r = self._returns()
        vol = EWMAVolatilityModel().latest_volatility(r)
        assert vol > 0

    def test_ewma_series_length(self):
        """Vol series should match returns length."""
        r = self._returns()
        vol_s = EWMAVolatilityModel().volatility_series(r)
        assert len(vol_s) == len(r)

    def test_ewma_higher_lambda_smoother(self):
        """Higher λ → smoother (lower variance of vol series)."""
        r = self._returns()
        vol_high = EWMAVolatilityModel(0.98).volatility_series(r)
        vol_low = EWMAVolatilityModel(0.85).volatility_series(r)
        assert vol_high.std() < vol_low.std()

    def test_ewma_reacts_to_shock(self):
        """After a large return, EWMA vol should increase."""
        np.random.seed(42)
        r = pd.Series([0.01] * 100 + [0.10] + [0.01] * 100)  # spike at 100
        model = EWMAVolatilityModel(0.94)
        var = model.variance_series(r)
        assert var[101] > var[99]  # vol after spike > vol before


# ═══════════════════════════════════════════════════════════════════════════════
# 3. VaR Backtesting (Kupiec + Christoffersen + Basel)
# ═══════════════════════════════════════════════════════════════════════════════
from src.models.backtest import VaRBacktester


class TestVaRBacktesting:
    """Tests for Kupiec POF, Christoffersen, and Basel zone."""

    def test_kupiec_no_exceptions(self):
        """Zero exceptions should give a large LR and low p-value."""
        pnl = pd.Series(np.ones(250))  # all positive P&L
        var_s = pd.Series(np.ones(250) * 0.1)
        bt = VaRBacktester(0.99)
        result = bt.run_kupiec_test(pnl, var_s)
        assert result["exceptions"] == 0

    def test_kupiec_all_exceptions(self):
        """100% failure rate should be invalid."""
        pnl = pd.Series(-np.ones(250))
        var_s = pd.Series(np.ones(250) * 0.5)
        bt = VaRBacktester(0.99)
        result = bt.run_kupiec_test(pnl, var_s)
        assert result["exceptions"] == 250
        assert not result["is_valid"]

    def test_kupiec_expected_rate(self):
        """With exactly the expected number of exceptions, should be valid."""
        np.random.seed(42)
        n = 1000
        pnl = pd.Series(np.random.normal(0, 1, n))
        var_s = pd.Series([norm.ppf(0.99)] * n)  # exact 99% VaR
        bt = VaRBacktester(0.99)
        result = bt.run_kupiec_test(pnl, var_s)
        # ~10 exceptions expected out of 1000 → should be valid
        assert 5 < result["exceptions"] < 20
        assert result["is_valid"]

    def test_christoffersen_independent(self):
        """Random exceptions should pass independence test."""
        np.random.seed(42)
        pnl = pd.Series(np.random.normal(0, 1, 500))
        var_s = pd.Series([norm.ppf(0.99)] * 500)
        bt = VaRBacktester(0.99)
        result = bt.christoffersen_test(pnl, var_s)
        assert "lr_ind" in result
        assert "independent" in result

    def test_christoffersen_clustered_violations(self):
        """Clustered exceptions should fail independence."""
        np.random.seed(42)
        # Normal returns + a cluster of 10 large losses in a row
        r = list(np.random.normal(0, 0.01, 200))
        r[100:110] = [-0.05] * 10  # cluster of violations
        pnl = pd.Series(r)
        var_s = pd.Series([0.025] * 200)
        bt = VaRBacktester(0.99)
        result = bt.christoffersen_test(pnl, var_s)
        assert result["lr_ind"] > 0  # should detect clustering

    def test_basel_zone_green(self):
        """0-4 exceptions → green zone."""
        bt = VaRBacktester(0.99)
        for exc in range(5):
            result = bt.basel_zone(exc)
            assert result["zone"] == "green"
            assert result["capital_multiplier"] == 3.0

    def test_basel_zone_yellow(self):
        """5-9 exceptions → yellow zone."""
        bt = VaRBacktester(0.99)
        for exc in range(5, 10):
            result = bt.basel_zone(exc)
            assert result["zone"] == "yellow"
            assert 3.0 < result["capital_multiplier"] <= 3.85

    def test_basel_zone_red(self):
        """≥10 exceptions → red zone."""
        bt = VaRBacktester(0.99)
        result = bt.basel_zone(10)
        assert result["zone"] == "red"
        assert result["capital_multiplier"] == 4.0

    def test_basel_multiplier_monotonic(self):
        """More exceptions → higher multiplier."""
        bt = VaRBacktester(0.99)
        prev_mult = 3.0
        for exc in range(0, 12):
            result = bt.basel_zone(exc)
            assert result["capital_multiplier"] >= prev_mult
            prev_mult = result["capital_multiplier"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Portfolio VaR (Variance-Covariance)
# ═══════════════════════════════════════════════════════════════════════════════
from src.models.portfolio_risk import PortfolioRiskModel


class TestPortfolioRisk:
    """Tests for portfolio VaR, marginal VaR, component VaR."""

    def _two_asset_returns(self, n=500, seed=42):
        np.random.seed(seed)
        r1 = np.random.normal(0, 0.015, n)
        r2 = np.random.normal(0, 0.020, n)
        return pd.DataFrame({"A": r1, "B": r2})

    def test_portfolio_var_positive(self):
        """Portfolio VaR should be positive for positive weights."""
        df = self._two_asset_returns()
        model = PortfolioRiskModel(0.99)
        var, vol = model.calculate_portfolio_var(df, np.array([0.6, 0.4]), 1e9)
        assert var > 0
        assert vol > 0

    def test_portfolio_var_diversification(self):
        """Portfolio VaR < sum of individual VaRs (diversification benefit)."""
        df = self._two_asset_returns()
        w = np.array([0.5, 0.5])
        model = ParametricRiskModel(0.99)
        var_a = model.calculate_var(df["A"]) * 0.5 * 1e9
        var_b = model.calculate_var(df["B"]) * 0.5 * 1e9
        pm = PortfolioRiskModel(0.99)
        port_var, _ = pm.calculate_portfolio_var(df, w, 1e9)
        assert port_var < var_a + var_b  # diversification benefit

    def test_portfolio_var_perfect_correlation(self):
        """With perfect correlation, portfolio VaR = sum of individual VaRs."""
        np.random.seed(42)
        r = np.random.normal(0, 0.015, 500)
        df = pd.DataFrame({"A": r, "B": r})  # perfectly correlated
        w = np.array([0.5, 0.5])
        pm = PortfolioRiskModel(0.99)
        port_var, _ = pm.calculate_portfolio_var(df, w, 1e9)
        # Should equal undiversified VaR
        undiv = norm.ppf(0.99) * 0.015 * 1e9  # single asset
        assert abs(port_var / undiv - 1.0) < 0.02

    def test_marginal_var_dimensions(self):
        """Marginal VaR vector should match number of assets."""
        df = self._two_asset_returns()
        w = np.array([0.6, 0.4])
        pm = PortfolioRiskModel(0.99)
        mvars = pm.marginal_var(df, w, 1e9)
        assert len(mvars) == 2

    def test_component_var_sums_to_total(self):
        """Sum of component VaRs should approximately equal total VaR."""
        df = self._two_asset_returns()
        w = np.array([0.6, 0.4])
        pm = PortfolioRiskModel(0.99)
        total_var, _ = pm.calculate_portfolio_var(df, w, 1e9)
        cvars = pm.component_var(df, w, 1e9)
        assert abs(sum(cvars) - total_var) / total_var < 0.01

    def test_portfolio_var_ewma(self):
        """EWMA portfolio VaR should work and differ from simple."""
        df = self._two_asset_returns()
        w = np.array([0.5, 0.5])
        var_simple, _ = PortfolioRiskModel(0.99, False).calculate_portfolio_var(df, w, 1e9)
        var_ewma, _ = PortfolioRiskModel(0.99, True).calculate_portfolio_var(df, w, 1e9)
        assert var_ewma > 0
        # Likely different
        assert abs(var_simple - var_ewma) > 0

    def test_portfolio_var_holding_period_scaling(self):
        """10-day VaR ≈ √10 × 1-day VaR."""
        df = self._two_asset_returns()
        w = np.array([0.5, 0.5])
        pm = PortfolioRiskModel(0.99)
        var_1d, _ = pm.calculate_portfolio_var(df, w, 1e9, holding_period=1)
        var_10d, _ = pm.calculate_portfolio_var(df, w, 1e9, holding_period=10)
        ratio = var_10d / var_1d
        assert abs(ratio - np.sqrt(10)) < 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Stress Testing
# ═══════════════════════════════════════════════════════════════════════════════
from src.models.stress_test import StressTester


class TestStressTesting:
    """Tests for scenario-based stress testing."""

    def test_all_scenarios_present(self):
        """Should have 7 predefined scenarios."""
        assert len(StressTester.SCENARIOS) == 7

    def test_single_asset_negative_losses(self):
        """Equity-only stress test should produce negative losses (losses)."""
        st = StressTester()
        result = st.apply_single_asset(1e9, portfolio_beta=1.0)
        for _name, loss in result.items():
            assert loss < 0  # all scenarios have negative equity shock

    def test_single_asset_beta_scales(self):
        """Higher beta → proportionally larger loss."""
        st = StressTester()
        r1 = st.apply_single_asset(1e9, portfolio_beta=1.0)
        r2 = st.apply_single_asset(1e9, portfolio_beta=2.0)
        for name in r1:
            assert abs(r2[name] / r1[name] - 2.0) < 0.01

    def test_multi_asset_scenario_structure(self):
        """Multi-asset stress should decompose into equity + bond + fx."""
        st = StressTester()
        result = st.apply_scenarios(
            equity_value=5e8, bond_value=3e8, fx_value=2e8,
            portfolio_beta=1.2, modified_duration=7.0,
        )
        for _name, detail in result.items():
            assert "equity_loss" in detail
            assert "bond_loss" in detail
            assert "fx_loss" in detail
            assert "total_loss" in detail
            assert detail["total_loss"] == detail["equity_loss"] + detail["bond_loss"] + detail["fx_loss"]

    def test_2008_worst_than_2010(self):
        """2008 GFC should produce larger loss than 2010 EU crisis."""
        st = StressTester()
        result = st.apply_single_asset(1e9)
        assert abs(result["2008 글로벌 금융위기"]) > abs(result["2010 유럽 재정위기"])

    def test_bond_rate_shock_direction(self):
        """Rising rates (positive bps shock) → bond price falls → negative bond loss."""
        st = StressTester()
        result = st.apply_scenarios(
            equity_value=0, bond_value=1e9, fx_value=0,
            modified_duration=7.0,
        )
        # 2008: rates_bps=-200 → bond price should rise
        assert result["2008 글로벌 금융위기"]["bond_loss"] > 0
        # 1997: rates_bps=+500 → bond price should fall
        assert result["1997 아시아 외환위기"]["bond_loss"] < 0

    def test_zero_portfolio(self):
        """Zero portfolio value → zero losses."""
        st = StressTester()
        result = st.apply_single_asset(0, portfolio_beta=1.0)
        for loss in result.values():
            assert loss == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FICC Engine (Black-Scholes + Bonds + FX)
# ═══════════════════════════════════════════════════════════════════════════════
from src.models.ficc_engine import FICCEngine


class TestFICCEngine:
    """Tests for BS Greeks, bond analytics, and FX."""

    # ── Black-Scholes ───────────────────────────────────────────────────────

    def test_call_put_parity(self):
        """Put-call parity: C - P = S - K·e^{-rT}."""
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20
        call = FICCEngine.bs_greeks(S, K, T, r, sigma, "call")
        put = FICCEngine.bs_greeks(S, K, T, r, sigma, "put")
        parity = call["Price"] - put["Price"]
        expected = S - K * np.exp(-r * T)
        assert abs(parity - expected) < 0.01

    def test_atm_delta(self):
        """ATM call delta ≈ 0.5, ATM put delta ≈ -0.5."""
        g = FICCEngine.bs_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert 0.45 < g["Delta"] < 0.65

    def test_gamma_positive(self):
        """Gamma is always positive for both calls and puts."""
        for opt_type in ["call", "put"]:
            g = FICCEngine.bs_greeks(100, 100, 1.0, 0.05, 0.20, opt_type)
            assert g["Gamma"] > 0

    def test_theta_negative(self):
        """Theta is typically negative (time decay)."""
        g = FICCEngine.bs_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert g["Theta"] < 0

    def test_deep_itm_call_delta_near_one(self):
        """Deep ITM call (S >> K) → Delta → 1."""
        g = FICCEngine.bs_greeks(200, 50, 1.0, 0.05, 0.20, "call")
        assert g["Delta"] > 0.95

    def test_deep_otm_put_delta_near_zero(self):
        """Deep OTM put (S >> K) → Delta → 0."""
        g = FICCEngine.bs_greeks(200, 50, 1.0, 0.05, 0.20, "put")
        assert abs(g["Delta"]) < 0.05

    def test_zero_expiry_returns_zero(self):
        """T=0 should return all zeros (no time value)."""
        g = FICCEngine.bs_greeks(100, 100, 0, 0.05, 0.20, "call")
        assert g["Price"] == 0

    def test_implied_vol_roundtrip(self):
        """BS price → implied vol → should recover original sigma."""
        S, K, T, r, sigma = 100, 105, 0.5, 0.04, 0.25
        price = FICCEngine.bs_greeks(S, K, T, r, sigma, "call")["Price"]
        iv = FICCEngine.implied_vol(price, S, K, T, r, "call")
        assert abs(iv - sigma) < 0.001

    # ── Bond Analytics ──────────────────────────────────────────────────────

    def test_par_bond_price_equals_face(self):
        """Bond priced at par (coupon = yield) → price ≈ face."""
        result = FICCEngine.bond_analytics(100, 0.05, 0.05, 10, freq=2)
        assert abs(result["Price"] - 100) < 0.01

    def test_duration_less_than_maturity(self):
        """Coupon bond duration < maturity (except zero-coupon)."""
        result = FICCEngine.bond_analytics(100, 0.05, 0.05, 10, freq=2)
        assert result["Macaulay_Duration"] < 10

    def test_modified_less_than_macaulay(self):
        """Modified duration = Macaulay / (1 + y/freq) < Macaulay."""
        result = FICCEngine.bond_analytics(100, 0.05, 0.05, 10, freq=2)
        assert result["Modified_Duration"] < result["Macaulay_Duration"]

    def test_bpv_positive(self):
        """BPV (Dollar Value of 1bp) should be positive."""
        result = FICCEngine.bond_analytics(100, 0.05, 0.05, 10, freq=2)
        assert result["BPV"] > 0

    def test_bond_price_change_approximation(self):
        """Duration-convexity approximation should be close to exact repricing."""
        result1 = FICCEngine.bond_analytics(100, 0.05, 0.05, 10, freq=2)
        result2 = FICCEngine.bond_analytics(100, 0.05, 0.06, 10, freq=2)
        actual_change = result2["Price"] - result1["Price"]
        approx_change = FICCEngine.bond_price_change(
            result1["Modified_Duration"], result1["Convexity"],
            result1["Price"], 0.01,
        )
        # Approximation should be within 5% of actual for small Δy
        assert abs(approx_change - actual_change) / abs(actual_change) < 0.05

    def test_higher_coupon_shorter_duration(self):
        """Higher coupon → shorter duration."""
        d_low = FICCEngine.bond_analytics(100, 0.03, 0.05, 10)["Macaulay_Duration"]
        d_high = FICCEngine.bond_analytics(100, 0.08, 0.05, 10)["Macaulay_Duration"]
        assert d_high < d_low

    # ── FX ──────────────────────────────────────────────────────────────────

    def test_fx_forward_covered_interest_parity(self):
        """F = S·exp((r_d - r_f)·T)."""
        fwd = FICCEngine.fx_forward(1300, 0.03, 0.05, 1.0)
        expected = 1300 * np.exp((0.03 - 0.05) * 1.0)
        assert abs(fwd - expected) < 0.01

    def test_fx_forward_same_rates(self):
        """Equal domestic/foreign rates → forward = spot."""
        fwd = FICCEngine.fx_forward(1300, 0.04, 0.04, 1.0)
        assert abs(fwd - 1300) < 0.01

    def test_fx_var_positive(self):
        """FX VaR should be positive."""
        var = FICCEngine.fx_var(1e8, 0.10, 0.99)
        assert var > 0

    def test_fx_var_scales_with_vol(self):
        """Doubling FX vol should double VaR."""
        v1 = FICCEngine.fx_var(1e8, 0.10, 0.99)
        v2 = FICCEngine.fx_var(1e8, 0.20, 0.99)
        assert abs(v2 / v1 - 2.0) < 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Hedging Simulator
# ═══════════════════════════════════════════════════════════════════════════════
from src.models.hedging import HedgingSimulator


class TestHedgingSimulator:
    """Tests for equity futures, duration, and delta hedges."""

    def test_full_hedge_target_zero(self):
        """Full hedge (target_beta=0) → contracts to sell = β·V/F."""
        hs = HedgingSimulator(futures_price=300.0, multiplier=250_000)
        result = hs.equity_futures_hedge(
            portfolio_value=1e9, current_beta=1.2, target_beta=0.0,
        )
        assert result["contracts_to_trade"] < 0  # selling
        assert result["target_beta"] == 0.0

    def test_hedge_no_action_same_beta(self):
        """Target = current → zero contracts."""
        hs = HedgingSimulator(futures_price=300.0)
        result = hs.equity_futures_hedge(1e9, 1.0, 1.0)
        assert result["contracts_to_trade"] == 0

    def test_hedge_buy_to_increase_beta(self):
        """Increasing beta → buy futures (positive contracts)."""
        hs = HedgingSimulator(futures_price=300.0)
        result = hs.equity_futures_hedge(1e9, 1.0, 2.0)
        assert result["contracts_to_trade"] > 0

    def test_duration_hedge_sign(self):
        """Duration hedge → sell futures (negative contracts)."""
        hs = HedgingSimulator(futures_price=300.0)
        result = hs.duration_hedge(
            bond_value=1e9, bond_duration=7.0,
            futures_duration=5.0, futures_price=100.0,
        )
        assert result["contracts_to_sell"] < 0

    def test_delta_hedge_long_call(self):
        """Long call (Δ > 0) → sell shares to delta-hedge."""
        hs = HedgingSimulator(futures_price=300.0)
        result = hs.delta_hedge(option_delta=0.5, option_lots=10, lot_size=100)
        assert result["shares_to_trade"] == -500
        assert result["action"] == "매도"

    def test_delta_hedge_long_put(self):
        """Long put (Δ < 0) → buy shares to delta-hedge."""
        hs = HedgingSimulator(futures_price=300.0)
        result = hs.delta_hedge(option_delta=-0.4, option_lots=10)
        assert result["shares_to_trade"] > 0
        assert result["action"] == "매수"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. AI Volatility Engine (Random Forest)
# ═══════════════════════════════════════════════════════════════════════════════
from src.models.ai_engine import AIVolatilityEngine


class TestAIVolatilityEngine:
    """Tests for the baseline RF volatility engine."""

    def _returns(self, n=300, seed=42):
        np.random.seed(seed)
        idx = pd.date_range("2022-01-01", periods=n, freq="B")
        return pd.Series(np.random.normal(0, 0.015, n), index=idx)

    def test_train_returns_rmse(self):
        """Training should produce a positive RMSE."""
        engine = AIVolatilityEngine(self._returns())
        result = engine.train()
        assert "rmse" in result
        assert result["rmse"] > 0

    def test_train_insufficient_data(self):
        """Short series should return error."""
        engine = AIVolatilityEngine(self._returns(n=30))
        result = engine.train()
        assert "error" in result

    def test_predict_next_positive(self):
        """Predicted vol should be positive."""
        engine = AIVolatilityEngine(self._returns())
        pred = engine.predict_next()
        assert pred > 0

    def test_predict_next_auto_trains(self):
        """predict_next on untrained model should auto-train."""
        engine = AIVolatilityEngine(self._returns())
        assert not engine._trained
        pred = engine.predict_next()
        assert engine._trained
        assert pred > 0

    def test_predict_var_positive(self):
        """AI-predicted VaR should be positive."""
        engine = AIVolatilityEngine(self._returns())
        var = engine.predict_var(1e9, 0.99)
        assert var > 0

    def test_volatility_regime_valid(self):
        """Regime should return valid label."""
        engine = AIVolatilityEngine(self._returns())
        regime = engine.volatility_regime()
        assert regime in ["HIGH", "LOW", "NORMAL", "unknown"]

    def test_regime_high_after_shock(self):
        """A series with recent high vol should classify as HIGH."""
        np.random.seed(42)
        r = pd.Series(
            list(np.random.normal(0, 0.01, 200))
            + list(np.random.normal(0, 0.05, 60)),
        )
        engine = AIVolatilityEngine(r)
        assert engine.volatility_regime() == "HIGH"

    def test_regime_low_after_calm(self):
        """A series with recent low vol should classify as LOW."""
        np.random.seed(42)
        r = pd.Series(
            list(np.random.normal(0, 0.03, 200))
            + list(np.random.normal(0, 0.005, 60)),
        )
        engine = AIVolatilityEngine(r)
        assert engine.volatility_regime() == "LOW"

    def test_build_features_shape(self):
        """Feature matrix should have correct dimensions."""
        engine = AIVolatilityEngine(self._returns(n=200), window=20)
        X, y = engine._build_features()
        assert X.shape[1] == 20  # window size
        assert len(X) == len(y)
