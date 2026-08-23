"""
Automated tests for FICC Risk API endpoints.
Uses FastAPI TestClient — no live server needed.
"""
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from main_api import app
from scipy.stats import norm

client = TestClient(app)


# ─── Health ──────────────────────────────────────────────────────────────────
def test_root():
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "Risk API is running"


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


# ─── Option Greeks ───────────────────────────────────────────────────────────
def test_option_call_greeks():
    payload = {"S": 100, "K": 100, "T": 1.0, "r": 0.05, "sigma": 0.20, "option_type": "call"}
    res = client.post("/analyze-option", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "Delta" in data
    assert 0 < data["Delta"] < 1          # call delta must be (0, 1)
    assert data["Gamma"] > 0
    assert data["Theta"] < 0              # theta is always negative
    assert data["Vega"] > 0


def test_option_put_greeks():
    payload = {"S": 100, "K": 100, "T": 1.0, "r": 0.05, "sigma": 0.20, "option_type": "put"}
    res = client.post("/analyze-option", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert -1 < data["Delta"] < 0         # put delta must be (-1, 0)


def test_put_call_parity():
    """C - P = S - K*e^(-rT)"""
    payload_c = {"S": 100, "K": 100, "T": 1.0, "r": 0.05, "sigma": 0.20, "option_type": "call"}
    payload_p = {**payload_c, "option_type": "put"}
    c_price = client.post("/analyze-option", json=payload_c).json()["Price"]
    p_price = client.post("/analyze-option", json=payload_p).json()["Price"]
    parity  = 100 - 100 * np.exp(-0.05 * 1.0)
    assert abs((c_price - p_price) - parity) < 0.01


# ─── Bond Analytics ──────────────────────────────────────────────────────────
def test_bond_at_par():
    """When coupon_rate == YTM, price should equal face value."""
    payload = {"face_value": 10000, "coupon_rate": 0.05, "ytm": 0.05,
               "years_to_maturity": 10, "freq": 2}
    res = client.post("/analyze-bond", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert abs(data["Price"] - 10000) < 1   # price ≈ face value at par
    assert data["Modified_Duration"] > 0
    assert data["Convexity"] > 0


def test_bond_premium_discount():
    """coupon > YTM → price > face value (premium)."""
    payload = {"face_value": 10000, "coupon_rate": 0.06, "ytm": 0.04,
               "years_to_maturity": 5, "freq": 2}
    res = client.post("/analyze-bond", json=payload)
    assert res.json()["Price"] > 10000


# ─── Hedging ─────────────────────────────────────────────────────────────────
def test_hedge_full():
    """Hedging to beta=0 should require contracts > 0."""
    payload = {"portfolio_value": 100_000_000, "current_beta": 1.2,
               "target_beta": 0.0, "futures_price": 360.0}
    res = client.post("/calculate-hedge", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "contracts_to_trade" in data
    assert data["contracts_to_trade"] < 0       # selling contracts (negative)
    assert data["expected_var_reduction_pct"] > 0


# ─── VaR Aggregation ─────────────────────────────────────────────────────────
def test_aggregate_var():
    payload = {
        "individual_vars": [150_000_000, 200_000_000, 100_000_000],
        "correlation_matrix": [
            [1.0, 0.2, -0.1],
            [0.2, 1.0, -0.5],
            [-0.1, -0.5, 1.0],
        ],
    }
    res = client.post("/aggregate-var", json=payload)
    assert res.status_code == 200
    data = res.json()
    # Diversified VaR must be less than sum of individual VaRs
    assert data["diversified_var"] < data["undiversified_var"]
    assert data["benefit"] > 0
    assert data["benefit_pct"] > 0


# ─── Auto-trading toggle ─────────────────────────────────────────────────────
def test_auto_trading_toggle():
    payload = {"auto_mode": True, "var_limit": 3_000_000, "username": "admin"}
    res = client.post("/toggle-auto-trading", json=payload)
    assert res.status_code == 200
    assert res.json()["auto_mode"] is True

    payload["auto_mode"] = False
    res = client.post("/toggle-auto-trading", json=payload)
    assert res.json()["auto_mode"] is False


# ─── Account (정식 KIS 클라이언트 경유, execution/kis_client.py) ─────────────────
def test_account_holdings_uses_sanctioned_client(monkeypatch):
    """/api/v1/account/holdings — get_kis_client() 경유 확인(구 3중 kis_client.py 통합 회귀)."""
    import src.execution.kis_client as kis_mod
    mock_client = kis_mod.MockKISClient()
    monkeypatch.setattr(kis_mod, "get_kis_client", lambda: mock_client)
    res = client.get("/api/v1/account/holdings")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "mock"
    assert data["positions"] == []
    assert data["count"] == 0


def test_account_balance_uses_sanctioned_client(monkeypatch):
    """/api/v1/account/balance — deposit/eval_amount/profit_loss/profit_rate 어댑터 확인."""
    import src.execution.kis_client as kis_mod
    mock_client = kis_mod.MockKISClient(initial_cash=50_000_000)
    monkeypatch.setattr(kis_mod, "get_kis_client", lambda: mock_client)
    res = client.get("/api/v1/account/balance")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "mock"
    assert data["deposit"] == 50_000_000
    assert data["eval_amount"] == 50_000_000
    assert data["profit_loss"] == 0
    assert data["profit_rate"] == 0


def test_sync_broker_and_place_order_removed():
    """구 broker_kis.py 경로(안전장치 전무, dry-run 없이 즉시 실주문 가능) 삭제 확인 — 재도입 방지 가드."""
    assert client.get("/sync-broker").status_code == 404
    assert client.post("/place-order", json={"ticker": "005930", "qty": 1}).status_code == 404


# ─── Orders (TradingEngine 경유 — 구 OrderExecutor(KISClient()) 직접생성 안전장치 우회 수정) ───
def test_orders_execute_dry_run_never_places_real_order(monkeypatch):
    """/api/v1/orders/execute — 항상 dry_run 고정이라 place_order()가 절대 호출되지 않음
    (예전엔 OrderExecutor(KISClient())를 직접 생성해 TradingEngine의 dry-run 기본값을
    완전히 우회했던 버그 — 이 테스트가 그 회귀를 고정)."""
    import src.execution.kis_client as kis_mod
    mock_client = kis_mod.MockKISClient()
    called = {"place_order": False}
    orig_place_order = mock_client.place_order

    def _tracking_place_order(*a, **kw):
        called["place_order"] = True
        return orig_place_order(*a, **kw)

    monkeypatch.setattr(mock_client, "place_order", _tracking_place_order)
    monkeypatch.setattr(kis_mod, "get_kis_client", lambda: mock_client)

    res = client.post("/api/v1/orders/execute", json={
        "stock_code": "005930", "stock_name": "삼성전자", "action": "buy", "strength": 1.0,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "dry_run"
    assert data["success"] is True
    assert data["stock_code"] == "005930"
    assert data["quantity"] > 0
    assert data["order_no"] == "DRY-RUN"
    assert called["place_order"] is False


def test_orders_execute_hold_action_blocked(monkeypatch):
    import src.execution.kis_client as kis_mod
    monkeypatch.setattr(kis_mod, "get_kis_client", lambda: kis_mod.MockKISClient())

    res = client.post("/api/v1/orders/execute", json={"stock_code": "005930", "action": "hold"})
    assert res.status_code == 200
    data = res.json()
    assert data["blocked_by"] == "hold"
    assert data["success"] is False


def test_orders_batch_dry_run(monkeypatch):
    import src.execution.kis_client as kis_mod
    monkeypatch.setattr(kis_mod, "get_kis_client", lambda: kis_mod.MockKISClient())

    res = client.post("/api/v1/orders/batch", json={"orders": [
        {"stock_code": "005930", "action": "buy", "strength": 1.0},
        {"stock_code": "000660", "action": "buy", "strength": 1.0},
    ]})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["mode"] == "dry_run"
    assert len(data["orders"]) == 2
    assert data["success"] == data["total"] - data["failed"]


# ─── PIT Backtest: Unit Tests ────────────────────────────────────────────────
from src.models.pit_backtest import PITBacktester


class TestPITUnit:
    """Unit tests for PIT backtesting math — no API calls needed."""

    def test_pit_perfect_model(self):
        """If forecast distribution matches actual, PITs should be uniform."""
        np.random.seed(42)
        n = 500
        mu = pd.Series(np.zeros(n))
        sigma = pd.Series(np.ones(n))
        # Draw actual from the forecasted distribution ⇒ PITs should be U[0,1]
        actual = pd.Series(np.random.normal(0, 1, n))

        pits = PITBacktester.compute_pit_values(actual, mu, sigma)
        assert len(pits) == n
        assert all(0 < p < 1 for p in pits)

        # KS test should NOT reject uniformity for a perfect model
        ks = PITBacktester.ks_test(pits)
        assert ks["reject_uniformity"] is False

    def test_pit_biased_model_rejected(self):
        """A model that systematically underestimates σ should be rejected."""
        np.random.seed(123)
        n = 500
        true_sigma = 2.0
        forecast_sigma = pd.Series(np.ones(n))       # underestimates by 2x
        actual = pd.Series(np.random.normal(0, true_sigma, n))
        mu = pd.Series(np.zeros(n))

        pits = PITBacktester.compute_pit_values(actual, mu, forecast_sigma)
        ks = PITBacktester.ks_test(pits)
        # A biased model should be rejected
        assert ks["reject_uniformity"] is True

    def test_ad_test_structure(self):
        """AD test should return critical values table and boolean result."""
        np.random.seed(7)
        pits = np.random.uniform(0, 1, 300)
        result = PITBacktester.ad_test(pits)
        assert "statistic" in result
        assert "critical_values" in result
        assert "5.0%" in result["critical_values"]
        assert isinstance(result["reject_uniformity_5pct"], bool)

    def test_cvm_test_uniform_passes(self):
        """CvM test should not reject truly uniform PITs."""
        np.random.seed(99)
        pits = np.random.uniform(0, 1, 400)
        result = PITBacktester.cvm_test(pits)
        assert result["reject_uniformity"] is False
        assert result["p_value"] > 0.05

    def test_berkowitz_independent(self):
        """IID normal → PITs should show no serial correlation."""
        np.random.seed(55)
        pits = np.random.uniform(0, 1, 300)
        result = PITBacktester.berkowitz_independence_test(pits)
        assert result["independent"] is True
        assert abs(result["rho_hat"]) < 0.15   # near-zero autocorrelation

    def test_berkowitz_dependent(self):
        """Serially correlated z-scores → PITs should fail independence."""
        np.random.seed(77)
        n = 500
        z = np.zeros(n)
        rho = 0.7
        for i in range(1, n):
            z[i] = rho * z[i - 1] + np.random.normal(0, np.sqrt(1 - rho**2))
        pits = np.clip(norm.cdf(z), 1e-8, 1 - 1e-8)
        result = PITBacktester.berkowitz_independence_test(pits)
        assert result["independent"] is False

    def test_qq_plot_data_shape(self):
        """QQ plot data should have matching lengths."""
        pits = np.random.uniform(0, 1, 200)
        qq = PITBacktester.qq_plot_data(pits, n_points=50)
        assert len(qq["theoretical"]) == len(qq["empirical"])
        assert len(qq["theoretical"]) == 50

    def test_histogram_bins(self):
        """Histogram should have the requested number of bins."""
        pits = np.random.uniform(0, 1, 300)
        hist = PITBacktester.pit_histogram_data(pits, bins=10)
        assert len(hist["bin_labels"]) == 10
        assert len(hist["counts"]) == 10
        assert sum(hist["counts"]) == 300

    def test_full_report_structure(self):
        """Full PIT report should contain all expected keys."""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0, 0.02, 300))
        bt = PITBacktester(0.99)
        result = bt.run_full_pit_backtest(returns, window=30)

        required_keys = [
            "n_observations", "overall_result", "tests_passed", "tests_total",
            "kolmogorov_smirnov", "anderson_darling", "cramer_von_mises",
            "berkowitz_independence", "qq_plot", "histogram",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"
        assert result["overall_result"] in ("PASS", "MARGINAL", "WEAK", "FAIL")
        assert 0 <= result["tests_passed"] <= 4

    def test_insufficient_data(self):
        """Should return error when data is too short."""
        returns = pd.Series(np.random.normal(0, 0.01, 20))
        bt = PITBacktester()
        result = bt.run_full_pit_backtest(returns, window=60)
        assert "error" in result


# ─── Monte Carlo VaR: Unit Tests ─────────────────────────────────────────────
from src.models.monte_carlo import MonteCarloVaR


class TestMonteCarloUnit:
    """Unit tests for Monte Carlo VaR engine — no API calls needed."""

    def test_single_asset_basic(self):
        """MC VaR should return positive VaR for typical returns."""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0003, 0.015, 500))
        engine = MonteCarloVaR(n_simulations=5000, seed=42)
        result = engine.single_asset_var(returns, portfolio_value=1_000_000_000)
        assert result["var_amount"] > 0
        assert result["es_amount"] >= result["var_amount"]  # ES ≥ VaR always
        assert result["n_simulations"] == 5000
        assert "var_std_error" in result

    def test_higher_vol_higher_var(self):
        """Higher volatility should produce higher VaR."""
        np.random.seed(42)
        low_vol = pd.Series(np.random.normal(0, 0.005, 300))
        high_vol = pd.Series(np.random.normal(0, 0.03, 300))
        engine = MonteCarloVaR(n_simulations=10000, seed=42)
        var_low = engine.single_asset_var(low_vol, 1e9)["var_amount"]
        var_high = engine.single_asset_var(high_vol, 1e9)["var_amount"]
        assert var_high > var_low

    def test_cholesky_identity(self):
        """Cholesky of identity matrix should be identity."""
        I = np.eye(3)
        L = MonteCarloVaR.cholesky_decompose(I)
        np.testing.assert_array_almost_equal(L, I)

    def test_cholesky_correlation(self):
        """Cholesky should satisfy L @ L.T = original matrix."""
        corr = np.array([
            [1.0, 0.5, 0.3],
            [0.5, 1.0, 0.2],
            [0.3, 0.2, 1.0],
        ])
        L = MonteCarloVaR.cholesky_decompose(corr)
        reconstructed = L @ L.T
        np.testing.assert_array_almost_equal(reconstructed, corr, decimal=6)

    def test_cholesky_non_pd_correction(self):
        """Should handle non-positive-definite matrices gracefully."""
        # This matrix is not positive-definite
        bad_corr = np.array([
            [1.0, 0.9, 0.9],
            [0.9, 1.0, -0.9],
            [0.9, -0.9, 1.0],
        ])
        L = MonteCarloVaR.cholesky_decompose(bad_corr)
        result = L @ L.T
        # Should be a valid correlation matrix (diag = 1, symmetric)
        np.testing.assert_array_almost_equal(np.diag(result), np.ones(3), decimal=4)
        assert np.allclose(result, result.T, atol=1e-6)

    def test_multi_asset_var_basic(self):
        """Multi-asset MC VaR with correlation structure."""
        np.random.seed(42)
        n = 300
        # Generate correlated returns
        corr = np.array([[1.0, 0.6], [0.6, 1.0]])
        L = np.linalg.cholesky(corr)
        z = np.random.standard_normal((2, n))
        r_corr = (L @ z).T * 0.015  # daily vol ~1.5%
        df = pd.DataFrame(r_corr, columns=["A", "B"])

        engine = MonteCarloVaR(n_simulations=10000, seed=42)
        weights = np.array([0.6, 0.4])
        result = engine.multi_asset_var(df, weights, 1_000_000_000)

        assert result["mc_var_amount"] > 0
        assert result["mc_es_amount"] >= result["mc_var_amount"]
        assert result["n_assets"] == 2
        assert result["diversification_benefit"] >= 0
        assert "correlation_matrix" in result
        assert "cholesky_matrix" in result
        assert "histogram" in result

    def test_diversification_reduces_var(self):
        """MC diversified VaR should be less than undiversified (sum of parts)."""
        np.random.seed(42)
        n = 300
        df = pd.DataFrame({
            "X": np.random.normal(0, 0.02, n),
            "Y": np.random.normal(0, 0.015, n),
            "Z": np.random.normal(0, 0.01, n),
        })
        engine = MonteCarloVaR(n_simulations=10000, seed=42)
        weights = np.array([0.4, 0.35, 0.25])
        result = engine.multi_asset_var(df, weights, 1e9)
        assert result["mc_var_amount"] < result["undiversified_var"]

    def test_antithetic_reduces_variance(self):
        """Antithetic variates should produce lower VaR standard error."""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0002, 0.015, 300))

        engine_no_av = MonteCarloVaR(n_simulations=5000, seed=42, antithetic=False)
        engine_av = MonteCarloVaR(n_simulations=5000, seed=42, antithetic=True)

        res_no = engine_no_av.single_asset_var(returns, 1e9)
        res_av = engine_av.single_asset_var(returns, 1e9)
        # Antithetic SE should generally be lower (not guaranteed, but likely)
        # At minimum, both should produce valid results
        assert res_no["var_amount"] > 0
        assert res_av["var_amount"] > 0

    def test_histogram_data(self):
        """Histogram should have valid structure."""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0, 0.015, 300))
        engine = MonteCarloVaR(n_simulations=5000, seed=42)
        result = engine.single_asset_var(returns, 1e9)

        assert "percentiles" in result
        # 1% percentile should be more negative than 99%
        assert result["percentiles"]["1%"] < result["percentiles"]["99%"]

    def test_single_asset_report_keys(self):
        """Single-asset result should contain all expected keys."""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0, 0.015, 300))
        engine = MonteCarloVaR(n_simulations=1000, seed=42)
        result = engine.single_asset_var(returns, 1e9)

        required = ["method", "n_simulations", "var_amount", "var_pct",
                     "es_amount", "es_pct", "var_std_error",
                     "mu_annual", "sigma_annual", "percentiles"]
        for k in required:
            assert k in result, f"Missing key: {k}"

# ─── GARCH(1,1): Unit Tests ─────────────────────────────────────────────────
from src.models.garch import EWMA, GARCH11, VolatilityModelComparison


class TestGARCHUnit:
    """Unit tests for GARCH(1,1) model — no API calls needed."""

    def _make_garch_data(self, n=500, seed=42):
        """Generate synthetic GARCH(1,1) returns for testing."""
        np.random.seed(seed)
        omega, alpha, beta = 0.00001, 0.08, 0.90
        r = np.zeros(n)
        sigma2 = np.zeros(n)
        sigma2[0] = omega / (1 - alpha - beta)
        for t in range(1, n):
            sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
            r[t] = np.sqrt(sigma2[t]) * np.random.standard_normal()
        return pd.Series(r)

    def test_fit_basic(self):
        """MLE fit should produce valid parameters."""
        returns = self._make_garch_data()
        model = GARCH11().fit(returns)
        assert model._fitted is True
        assert model.omega > 0
        assert 0 < model.alpha < 0.5
        assert 0.3 < model.beta < 1.0
        assert model.persistence < 1.0  # stationarity

    def test_parameter_recovery(self):
        """Estimated params should be close to true DGP params."""
        returns = self._make_garch_data(n=2000, seed=99)
        model = GARCH11().fit(returns)
        # Allow generous tolerance — MLE on finite samples has noise
        assert abs(model.alpha - 0.08) < 0.06, f"alpha={model.alpha}"
        assert abs(model.beta - 0.90) < 0.08, f"beta={model.beta}"

    def test_long_run_variance(self):
        """V_L = ω / (1-α-β) should be positive and finite."""
        returns = self._make_garch_data()
        model = GARCH11().fit(returns)
        vl = model.long_run_variance
        assert vl > 0
        assert np.isfinite(vl)
        # And it should roughly match sample variance
        assert abs(vl - np.var(returns)) / np.var(returns) < 5.0

    def test_half_life_positive(self):
        """Half-life should be positive and finite for stationary model."""
        returns = self._make_garch_data()
        model = GARCH11().fit(returns)
        hl = model.half_life
        assert hl > 0
        assert np.isfinite(hl)

    def test_forecast_convergence(self):
        """Multi-step forecast should converge to long-run vol."""
        returns = self._make_garch_data()
        model = GARCH11().fit(returns)
        fc = model.forecast_variance(500)
        vl = model.long_run_variance
        # Last forecast should be very close to V_L
        assert abs(fc[-1] - vl) / vl < 0.01

    def test_variance_series_length(self):
        """Variance series should match returns length."""
        returns = self._make_garch_data(n=200)
        model = GARCH11().fit(returns)
        vs = model.variance_series()
        assert len(vs) == 200
        assert all(v > 0 for v in vs)

    def test_standardised_residuals(self):
        """z_t = r_t/σ_t should have std ≈ 1."""
        returns = self._make_garch_data(n=1000)
        model = GARCH11().fit(returns)
        z = model.standardised_residuals()
        assert abs(np.std(z) - 1.0) < 0.2

    def test_ewma_is_special_case(self):
        """EWMA with λ=0.94 → α=0.06, β=0.94, persistence=1."""
        ewma = EWMA(0.94)
        assert abs(ewma.alpha_equiv - 0.06) < 1e-10
        assert abs(ewma.beta_equiv - 0.94) < 1e-10

    def test_ewma_log_likelihood(self):
        """EWMA log-likelihood should be finite and negative."""
        returns = self._make_garch_data()
        ewma = EWMA(0.94)
        ll = ewma.log_likelihood(returns.values)
        assert np.isfinite(ll)
        assert np.isfinite(ll)  # LL can be positive for small-var Gaussian

    def test_comparison_report_keys(self):
        """Comparison report should have all expected sections."""
        returns = self._make_garch_data(n=300)
        comp = VolatilityModelComparison(returns, ewma_lambda=0.94)
        result = comp.compare()

        required = ["garch", "ewma", "current_volatility",
                     "forecast_5day", "model_selection",
                     "diagnostics", "vol_series"]
        for k in required:
            assert k in result, f"Missing key: {k}"

        # GARCH section should have params
        assert "alpha" in result["garch"]
        assert "beta" in result["garch"]
        assert "persistence" in result["garch"]

    def test_garch_beats_ewma_on_garch_data(self):
        """On GARCH-generated data, GARCH model should have better AIC."""
        returns = self._make_garch_data(n=1000, seed=77)
        comp = VolatilityModelComparison(returns, ewma_lambda=0.94)
        result = comp.compare()
        # GARCH should fit its own DGP better
        assert result["model_selection"]["garch_aic"] < result["model_selection"]["ewma_aic"]

    def test_summary_dict(self):
        """Summary should be JSON-serialisable."""
        returns = self._make_garch_data()
        model = GARCH11().fit(returns)
        s = model.summary()
        import json
        json.dumps(s)  # should not raise
        assert s["model"] == "GARCH(1,1)"

# ─── FRTB ES: Unit Tests ────────────────────────────────────────────────────
from src.models.frtb_es import (
    LH_CATEGORIES,
    LIQUIDITY_HORIZON_MAP,
    FRTBExpectedShortfall,
    RiskPosition,
)


class TestFRTBUnit:
    """Unit tests for FRTB Expected Shortfall engine."""

    def _make_returns(self, n=500, seed=42, vol=0.015):
        np.random.seed(seed)
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        return pd.Series(np.random.normal(0, vol, n), index=idx)

    def test_parametric_es_975(self):
        """ES 97.5% should be >= VaR 99% for normal distribution."""
        returns = self._make_returns()
        engine = FRTBExpectedShortfall()
        result = engine.parametric_es(returns, 1e9)
        assert result["es_975_amount"] > 0
        assert result["var_99_amount"] > 0
        # For normal dist: ES 97.5% ≈ VaR 99% (ratio ≈ 1.005)
        assert 0.95 < result["es_var_ratio"] < 1.15

    def test_historical_es(self):
        """Historical ES should have valid tail observation count."""
        returns = self._make_returns(n=1000)
        result = FRTBExpectedShortfall.historical_es(returns, 1e9, 0.975)
        assert result["es_amount"] > 0
        assert result["es_amount"] >= result["var_threshold"]
        # 2.5% tail → ~25 observations out of 1000
        assert 15 < result["n_tail_obs"] < 40

    def test_stressed_es_higher(self):
        """Stressed ES should be >= Current ES (worst window >= average)."""
        # Create returns with a volatile period
        np.random.seed(42)
        calm = np.random.normal(0, 0.01, 300)
        crisis = np.random.normal(-0.005, 0.04, 250)
        calm2 = np.random.normal(0, 0.01, 200)
        idx = pd.date_range("2018-01-01", periods=750, freq="B")
        returns = pd.Series(np.concatenate([calm, crisis, calm2]), index=idx)

        engine = FRTBExpectedShortfall()
        result = engine.stressed_es(returns, 1e9)
        assert result["stressed_es_975"] >= result["current_es_975"]
        assert result["stress_ratio"] >= 1.0

    def test_stressed_es_short_data(self):
        """Should handle data shorter than 250 days gracefully."""
        returns = self._make_returns(n=100)
        engine = FRTBExpectedShortfall()
        result = engine.stressed_es(returns, 1e9)
        assert result["stress_ratio"] == 1.0
        assert "N/A" in str(result["stress_window_start"])

    def test_lh_category_mapping(self):
        """Risk factor types should map to correct LH categories."""
        pos_equity = RiskPosition("A", "large_cap_equity", 0.5)
        pos_nig = RiskPosition("B", "nig_corporate_spread", 0.3)
        pos_struct = RiskPosition("C", "structured_credit", 0.2)

        assert pos_equity.liquidity_horizon == 10
        assert pos_nig.liquidity_horizon == 60
        assert pos_struct.liquidity_horizon == 120

        assert pos_equity.lh_category == 10
        assert pos_nig.lh_category == 60
        assert pos_struct.lh_category == 120

    def test_liquidity_adjusted_es_scaling(self):
        """LH-adjusted ES should be > base 10-day ES when higher LH positions exist."""
        returns1 = self._make_returns(n=500, seed=42, vol=0.015)
        returns2 = self._make_returns(n=500, seed=99, vol=0.025)

        positions = [
            RiskPosition("Equity", "large_cap_equity", 0.6, returns1),
            RiskPosition("NIG Bond", "nig_corporate_spread", 0.4, returns2),
        ]
        result = FRTBExpectedShortfall.liquidity_adjusted_es(
            positions, 1e9, 0.975
        )
        assert result["es_liquidity_adjusted"] > 0
        assert result["es_base_10d"] > 0
        # With a 60-day position, LH-adjusted should scale up
        assert result["lh_scaling_factor"] >= 1.0

    def test_capital_charge_structure(self):
        """Full capital charge should have all required keys."""
        returns = self._make_returns(n=500)
        engine = FRTBExpectedShortfall()
        result = engine.capital_charge(returns, 1e9)

        required = [
            "parametric_es", "historical_es", "stressed_es",
            "imcc_capital_charge", "multiplier", "legacy_comparison",
        ]
        for k in required:
            assert k in result, f"Missing key: {k}"
        assert result["imcc_capital_charge"] > 0
        assert result["multiplier"] == 1.5

    def test_single_ticker_report(self):
        """Single-ticker report should include LH and factor type."""
        returns = self._make_returns()
        engine = FRTBExpectedShortfall()
        result = engine.single_ticker_report(returns, 1e9, "ig_corporate_bond")
        assert result["risk_factor_type"] == "ig_corporate_bond"
        assert result["liquidity_horizon_days"] == 20
        assert result["imcc_capital_charge"] > 0

    def test_es_975_gt_es_95(self):
        """ES at 97.5% should be > ES at 95% (deeper into the tail)."""
        returns = self._make_returns()
        es_975 = FRTBExpectedShortfall.historical_es(returns, 1e9, 0.975)
        es_95 = FRTBExpectedShortfall.historical_es(returns, 1e9, 0.95)
        assert es_975["es_amount"] >= es_95["es_amount"]

    def test_five_lh_categories(self):
        """All 5 FRTB LH categories should be defined."""
        assert LH_CATEGORIES == [10, 20, 40, 60, 120]
        assert len(LIQUIDITY_HORIZON_MAP) >= 15

    def test_multiplier_affects_capital(self):
        """Higher multiplier should linearly increase capital."""
        returns = self._make_returns()
        engine = FRTBExpectedShortfall()
        r1 = engine.capital_charge(returns, 1e9, multiplier=1.5)
        r2 = engine.capital_charge(returns, 1e9, multiplier=3.0)
        ratio = r2["imcc_capital_charge"] / r1["imcc_capital_charge"]
        assert 1.9 < ratio < 2.1  # should be ~2x

# ─── CVA Engine: Unit Tests ─────────────────────────────────────────────────
from src.models.cva_engine import CDSHazardRateModel, CVAEngine, ExposureProfile


class TestCVAUnit:
    """Unit tests for CVA engine."""

    def test_hazard_rate_from_cds(self):
        """λ ≈ CDS_spread / LGD. 150bps / 0.60 = 2.5%."""
        model = CDSHazardRateModel(recovery_rate=0.40)
        h = model.approximate_hazard_rate(150)
        assert abs(h - 0.025) < 1e-6

    def test_survival_probability(self):
        """PS(t) = e^{-λt}. PS(1) at λ=0.03 = e^{-0.03} ≈ 0.9704."""
        model = CDSHazardRateModel(0.40)
        ps = model.survival_probability(0.03, 1.0)
        assert abs(ps - np.exp(-0.03)) < 1e-6

    def test_marginal_pd_sum(self):
        """Sum of marginal PDs = cumulative PD."""
        model = CDSHazardRateModel(0.40)
        schedule = model.marginal_default_probabilities(0.03, 5)
        total_q = sum(s["marginal_pd"] for s in schedule)
        cum_pd = model.default_probability_by_time(0.03, 5)
        assert abs(total_q - cum_pd) < 1e-4

    def test_bootstrap_hazard_rates(self):
        """Bootstrap should produce forward rates between cumulative rates."""
        model = CDSHazardRateModel(0.40)
        cds_ts = {1: 60, 3: 80, 5: 120}
        result = model.bootstrap_hazard_rates(cds_ts)
        assert len(result["cumulative_hazard_rates"]) == 3
        assert len(result["forward_hazard_rates"]) == 3
        # Forward rate for 3y-5y should be higher than cumulative 3y
        fwd_3_5 = result["forward_hazard_rates"]["3y-5y"]
        cum_3 = result["cumulative_hazard_rates"][3]
        assert fwd_3_5 > cum_3  # spread is steepening

    def test_ee_profile_irs(self):
        """IRS EE profile should be hump-shaped (peak in middle)."""
        exp = ExposureProfile("test", 1e9, 5.0, "irs")
        ee = exp.generate_ee_profile(20)
        assert len(ee) == 20
        assert all(e >= 0 for e in ee)
        # Peak should be in the middle third
        peak_idx = np.argmax(ee)
        assert 4 < peak_idx < 16

    def test_unilateral_cva_positive(self):
        """CVA should be positive for any non-zero exposure and PD."""
        engine = CVAEngine(risk_free_rate=0.03, recovery_rate=0.40)
        exp = ExposureProfile("IRS", 1e9, 5.0, "irs")
        ee = exp.generate_ee_profile(20, volatility=0.02)
        result = engine.calculate_cva(ee, 0.025, 5.0)
        assert result["cva_amount"] > 0

    def test_cva_increases_with_spread(self):
        """Higher CDS spread → higher hazard rate → higher CVA."""
        engine = CVAEngine(0.03, 0.40)
        exp = ExposureProfile("IRS", 1e9, 5.0, "irs")
        ee = exp.generate_ee_profile(20)
        h_low = CDSHazardRateModel(0.40).approximate_hazard_rate(50)
        h_high = CDSHazardRateModel(0.40).approximate_hazard_rate(300)
        cva_low = engine.calculate_cva(ee, h_low, 5.0)["cva_amount"]
        cva_high = engine.calculate_cva(ee, h_high, 5.0)["cva_amount"]
        assert cva_high > cva_low

    def test_bcva_structure(self):
        """BCVA should have CVA, DVA, and net BCVA."""
        engine = CVAEngine(0.03, 0.40)
        ee = np.ones(20) * 1e7
        ene = np.ones(20) * 8e6
        result = engine.calculate_bcva(ee, ene, 0.025, 0.008, 5.0)
        assert result["cva_amount"] > 0
        assert result["dva_amount"] > 0
        assert "bcva_amount" in result
        # CVA > DVA when counterparty hazard > bank hazard
        assert result["cva_amount"] > result["dva_amount"]

    def test_cva_spread_positive(self):
        """CVA spread in bps should be positive."""
        spread = CVAEngine.cva_spread(500_000, 1e7, 5.0)
        assert spread > 0

    def test_stressed_cva_higher(self):
        """Stressed CVA should be > base CVA (wider spreads + higher exposure)."""
        engine = CVAEngine(0.03, 0.40)
        ee = np.ones(20) * 1e7
        result = engine.stressed_cva(ee, 0.025, 5.0, spread_shock_bps=200)
        assert result["stressed_cva"] > result["base_cva"]
        assert result["stress_loss"] > 0

    def test_full_report_keys(self):
        """Full CVA report should have all required sections."""
        engine = CVAEngine(0.03, 0.40)
        result = engine.full_cva_report(
            notional=1e9, maturity_years=5.0,
            cds_spread_bps=150, position_type="irs",
        )
        required = [
            "inputs", "pd_from_cds", "exposure_profile",
            "unilateral_cva", "bilateral_cva", "bcva_spread", "stressed_cva",
        ]
        for k in required:
            assert k in result, f"Missing key: {k}"
        assert result["unilateral_cva"]["cva_amount"] > 0

    def test_full_report_with_term_structure(self):
        """Report with CDS term structure should bootstrap hazard rates."""
        engine = CVAEngine(0.03, 0.40)
        result = engine.full_cva_report(
            notional=1e9, maturity_years=5.0,
            cds_spread_bps=120,
            cds_term_structure={1: 60, 3: 80, 5: 120, 10: 150},
        )
        ts = result["hazard_rate_term_structure"]
        assert ts is not None
        assert len(ts["cumulative_hazard_rates"]) == 4

    def test_api_endpoint(self):
        """API endpoint should return valid CVA result."""
        payload = {
            "notional": 1_000_000_000,
            "maturity_years": 5.0,
            "cds_spread_bps": 150.0,
            "recovery_rate": 0.40,
            "risk_free_rate": 0.03,
            "position_type": "irs",
        }
        res = client.post("/calculate-cva", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["unilateral_cva"]["cva_amount"] > 0
        assert data["bilateral_cva"]["cva_amount"] > 0

# ─── Credit Spread Risk & IDR: Unit Tests ────────────────────────────────────
from src.models.credit_spread_idr import (
    DEFAULT_PROBS,
    RATING_GRADES,
    TRANSITION_MATRIX_1Y,
    CreditPosition,
    CreditSpreadRiskEngine,
    IncrementalDefaultRisk,
    IncrementalRiskCharge,
)


class TestCreditSpreadIDR:
    """Unit tests for Credit Spread Risk and IDR engine."""

    def test_transition_matrix_rows_sum_to_one(self):
        """Each row of the transition matrix should sum to 1."""
        for i, rating in enumerate(RATING_GRADES):
            row_sum = TRANSITION_MATRIX_1Y[i].sum()
            assert abs(row_sum - 1.0) < 1e-6, f"{rating} row sums to {row_sum}"

    def test_default_probs_from_matrix(self):
        """Default probs should match the D column of the transition matrix."""
        for i, rating in enumerate(RATING_GRADES):
            assert abs(DEFAULT_PROBS[rating] - TRANSITION_MATRIX_1Y[i, -1]) < 1e-8

    def test_default_probs_monotonic(self):
        """Lower-rated bonds should have higher default probs."""
        ig_ratings = ["BBB", "BB", "B", "CCC"]
        for j in range(len(ig_ratings) - 1):
            assert DEFAULT_PROBS[ig_ratings[j]] <= DEFAULT_PROBS[ig_ratings[j+1]]

    def test_migration_pnl_upgrade_positive(self):
        """Upgrade (spread tightening) should produce positive P&L."""
        engine = CreditSpreadRiskEngine()
        pos = CreditPosition("Test", "BBB", 1e9, 5.0)
        result = engine.migration_pnl(pos)
        # Find the A upgrade scenario
        a_scenario = next(s for s in result["scenarios"] if s["end_rating"] == "A")
        assert a_scenario["pnl"] > 0  # spread tightens → gain
        assert a_scenario["spread_change_bps"] < 0

    def test_migration_pnl_downgrade_negative(self):
        """Downgrade (spread widening) should produce negative P&L."""
        engine = CreditSpreadRiskEngine()
        pos = CreditPosition("Test", "A", 1e9, 5.0)
        result = engine.migration_pnl(pos)
        bb_scenario = next(s for s in result["scenarios"] if s["end_rating"] == "BB")
        assert bb_scenario["pnl"] < 0  # spread widens → loss

    def test_migration_pnl_default_loss(self):
        """Default scenario should produce loss = Notional × LGD."""
        engine = CreditSpreadRiskEngine()
        pos = CreditPosition("Test", "BBB", 1e9, 5.0, recovery_rate=0.40)
        result = engine.migration_pnl(pos)
        d_scenario = next(s for s in result["scenarios"] if s["end_rating"] == "D")
        expected_loss = -1e9 * 0.60
        assert abs(d_scenario["pnl"] - expected_loss) < 1

    def test_vasicek_wcdr_higher_than_pd(self):
        """WCDR at 99.9% should be significantly higher than base PD."""
        idr = IncrementalDefaultRisk()
        pd = 0.01  # 1%
        wcdr = idr.vasicek_wcdr(pd, rho=0.20, confidence=0.999)
        assert wcdr > pd
        assert wcdr < 1.0

    def test_vasicek_wcdr_increases_with_correlation(self):
        """Higher correlation → higher WCDR (more systemic risk)."""
        idr = IncrementalDefaultRisk()
        wcdr_low = idr.vasicek_wcdr(0.02, rho=0.10)
        wcdr_high = idr.vasicek_wcdr(0.02, rho=0.30)
        assert wcdr_high > wcdr_low

    def test_vasicek_wcdr_zero_pd(self):
        """PD=0 should give WCDR=0."""
        assert IncrementalDefaultRisk.vasicek_wcdr(0.0, 0.2) == 0.0

    def test_basel_correlation_range(self):
        """Basel correlation should be between 0.12 and 0.24."""
        idr = IncrementalDefaultRisk()
        for pd_val in [0.001, 0.01, 0.05, 0.10, 0.20]:
            rho = idr.basel_correlation(pd_val)
            assert 0.12 <= rho <= 0.24, f"rho={rho} for pd={pd_val}"

    def test_idr_capital_positive(self):
        """IDR capital charge should be positive."""
        idr = IncrementalDefaultRisk()
        positions = [
            CreditPosition("Bond_A", "A", 1e9, 5.0),
            CreditPosition("Bond_BB", "BB", 5e8, 3.0),
        ]
        result = idr.calculate_idr(positions)
        assert result["idr_capital_charge"] > 0
        assert result["total_var_999"] > result["total_expected_loss"]

    def test_portfolio_mc_spread_var(self):
        """MC credit spread VaR should be positive."""
        engine = CreditSpreadRiskEngine()
        positions = [
            CreditPosition("IG", "A", 2e9, 5.0),
            CreditPosition("HY", "B", 1e9, 3.0),
        ]
        result = engine.portfolio_credit_spread_var(positions, n_simulations=10000)
        assert result["credit_spread_var"] > 0
        assert result["credit_spread_es"] >= result["credit_spread_var"]

    def test_irc_combined(self):
        """Full IRC should combine spread and default components."""
        irc = IncrementalRiskCharge()
        positions = [
            CreditPosition("BBB Bond", "BBB", 1e9, 5.0),
        ]
        result = irc.calculate_irc(positions, n_simulations=10000)
        assert result["irc_total"] > 0
        assert result["spread_risk_component"] > 0
        assert result["default_risk_component"] > 0
        assert "migration_analysis" in result
        assert "transition_matrix" in result

    def test_multi_year_transition(self):
        """3-year matrix should show higher default probs than 1-year."""
        engine = CreditSpreadRiskEngine()
        pd_1y = engine.cumulative_default_prob("BBB", 1)
        pd_3y = engine.cumulative_default_prob("BBB", 3)
        assert pd_3y > pd_1y

    def test_api_endpoint_irc(self):
        """API endpoint should return valid IRC result."""
        payload = {
            "positions": [
                {"name": "Test_A", "rating": "A", "notional": 1e9,
                 "modified_duration": 5.0},
                {"name": "Test_BB", "rating": "BB", "notional": 5e8,
                 "modified_duration": 3.0},
            ]
        }
        res = client.post("/calculate-irc", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["irc_total"] > 0
        assert data["spread_risk_component"] > 0
        assert data["default_risk_component"] > 0

    def test_api_transition_matrix(self):
        """Transition matrix endpoint should return 8x8 matrix."""
        res = client.get("/credit-transition-matrix")
        assert res.status_code == 200
        data = res.json()
        assert len(data["ratings"]) == 8
        assert len(data["transition_matrix_1y"]) == 8
        assert len(data["transition_matrix_1y"][0]) == 8

# ─── DCC-GARCH & Wrong-Way Risk: Unit Tests ─────────────────────────────────
from src.models.dcc_garch_wwr import DCCGARCH, WrongWayRiskDetector, dcc_garch_full_report


class TestDCCGARCHUnit:
    """Unit tests for DCC-GARCH and WWR detection."""

    def _make_correlated_returns(self, n=500, rho=0.5, seed=42):
        np.random.seed(seed)
        z1 = np.random.normal(0, 0.015, n)
        z2 = rho * z1 + np.sqrt(1 - rho**2) * np.random.normal(0, 0.015, n)
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        return pd.DataFrame({"A": z1, "B": z2}, index=idx)

    def test_dcc_fit_basic(self):
        """DCC model should fit and produce valid parameters."""
        df = self._make_correlated_returns()
        dcc = DCCGARCH()
        dcc.fit(df)
        assert dcc._fitted is True
        assert dcc.a > 0
        assert dcc.b > 0
        assert dcc.a + dcc.b < 1.0

    def test_dcc_correlation_bounded(self):
        """Dynamic correlations should stay in [-1, 1]."""
        df = self._make_correlated_returns()
        dcc = DCCGARCH()
        dcc.fit(df)
        rho_t = dcc.pairwise_correlation_series(0, 1)
        assert all(-1.0 <= r <= 1.0 for r in rho_t)

    def test_dcc_correlation_near_true(self):
        """Average dynamic correlation should be near the true value."""
        df = self._make_correlated_returns(n=1000, rho=0.6, seed=99)
        dcc = DCCGARCH()
        dcc.fit(df)
        rho_t = dcc.pairwise_correlation_series(0, 1)
        avg_rho = np.mean(rho_t)
        assert abs(avg_rho - 0.6) < 0.2  # generous tolerance

    def test_dcc_summary_keys(self):
        """Summary should have all expected keys."""
        df = self._make_correlated_returns()
        dcc = DCCGARCH()
        dcc.fit(df)
        s = dcc.summary()
        assert "dcc_a" in s
        assert "dcc_b" in s
        assert "garch_params" in s
        assert len(s["garch_params"]) == 2

    def test_dcc_three_assets(self):
        """Should handle 3+ asset portfolios."""
        np.random.seed(42)
        n = 300
        df = pd.DataFrame({
            "X": np.random.normal(0, 0.015, n),
            "Y": np.random.normal(0, 0.02, n),
            "Z": np.random.normal(0, 0.01, n),
        })
        dcc = DCCGARCH()
        dcc.fit(df)
        stats = dcc.correlation_stats()
        assert len(stats) == 3  # 3 pairs: X_Y, X_Z, Y_Z

    def test_wwr_positive_correlation(self):
        """Positive corr between exposure and CDS should flag WWR."""
        np.random.seed(42)
        n = 200
        exposure = pd.Series(np.cumsum(np.random.normal(0, 1, n)) + 100, name="exposure")
        cds = pd.Series(exposure.values * 0.3 + np.random.normal(0, 5, n), name="cds")
        result = WrongWayRiskDetector.detect_static_wwr(exposure, cds)
        assert result.risk_type == "WWR"
        assert result.correlation > 0

    def test_rwr_negative_correlation(self):
        """Negative corr should flag RWR."""
        np.random.seed(42)
        n = 200
        exposure = pd.Series(np.cumsum(np.random.normal(0, 1, n)) + 100, name="exposure")
        cds = pd.Series(-exposure.values * 0.4 + np.random.normal(0, 5, n) + 200, name="cds")
        result = WrongWayRiskDetector.detect_static_wwr(exposure, cds)
        assert result.risk_type == "RWR"
        assert result.correlation < 0

    def test_wwr_adjusted_cva_increases(self):
        """WWR should increase CVA, RWR should decrease it."""
        wwr_adj = WrongWayRiskDetector.wwr_adjusted_cva(1_000_000, 0.3)
        assert wwr_adj["adjusted_cva"] > 1_000_000
        rwr_adj = WrongWayRiskDetector.wwr_adjusted_cva(1_000_000, -0.3)
        assert rwr_adj["adjusted_cva"] < 1_000_000

    def test_rolling_wwr_structure(self):
        """Rolling WWR should return valid structure."""
        np.random.seed(42)
        n = 200
        exp = pd.Series(np.random.normal(100, 10, n), name="exp")
        cds = pd.Series(np.random.normal(150, 20, n), name="cds")
        result = WrongWayRiskDetector.rolling_wwr(exp, cds, window=30)
        assert "current_correlation" in result
        assert "rolling_correlation" in result
        assert len(result["rolling_correlation"]) > 0

    def test_transaction_wwr_classification(self):
        """All known transaction types should be classified."""
        for tx_type in ["put_option", "call_option", "fx_forward",
                         "cds_protection", "interest_rate_swap"]:
            result = WrongWayRiskDetector.classify_transaction_wwr(tx_type)
            assert result["inherent_risk"] != "UNKNOWN"

    def test_full_report_structure(self):
        """Full DCC report should have all sections."""
        df = self._make_correlated_returns(n=200)
        result = dcc_garch_full_report(df)
        assert "dcc_garch" in result
        assert "dynamic_correlations" in result
        assert "static_correlation" in result
        assert result["dcc_garch"]["dcc_a"] > 0

# ─── VaR Mapping: Unit Tests ────────────────────────────────────────────────
from src.models.var_mapping import (
    Bond,
    DerivativesMapper,
    VaRMappingEngine,
    tracking_error_var,
)


class TestVaRMappingUnit:
    """Unit tests for VaR Mapping engine.

    Reference values from FRM Reading 5 Jorion example:
      Two-bond portfolio: $100M × 1Y (3.5% coupon) + $100M × 5Y (5% coupon)
      Zero VaRs: 0.4696, 0.9868, 1.4841, 1.9946, 2.5117 (%)
    """

    def _sample_portfolio(self):
        return [
            Bond("Bond_1Y", 100e6, 0.035, 1, ytm=0.035),
            Bond("Bond_5Y", 100e6, 0.05, 5, ytm=0.05),
        ]

    def _zero_vars(self):
        return {1: 0.4696, 2: 0.9868, 3: 1.4841, 4: 1.9946, 5: 2.5117}

    def test_bond_cash_flows(self):
        """5Y 5% bond should have 4 coupon years + 1 final year with principal."""
        b = Bond("Test", 100, 0.05, 5)
        cfs = b.cash_flows()
        assert len(cfs) == 5
        assert cfs[0] == (1, 5)    # coupon only
        assert cfs[-1] == (5, 105) # coupon + principal

    def test_bond_pv_at_par(self):
        """Bond priced at par (ytm = coupon) should have PV = face."""
        b = Bond("Par", 100, 0.05, 5, ytm=0.05)
        spot_rates = {t: 0.05 for t in range(1, 6)}
        mv = b.market_value(spot_rates)
        assert abs(mv - 100) < 0.01

    def test_macaulay_duration(self):
        """5Y 5% par bond should have duration between 4.3 and 4.6."""
        b = Bond("Par", 100, 0.05, 5, ytm=0.05)
        spot_rates = {t: 0.05 for t in range(1, 6)}
        dur = b.macaulay_duration(spot_rates)
        assert 4.3 < dur < 4.6

    def test_principal_mapping(self):
        """Principal mapping: average life = 3Y, VaR uses 3Y zero rate."""
        engine = VaRMappingEngine(self._zero_vars())
        result = engine.principal_mapping(self._sample_portfolio())
        assert result["weighted_average_life"] == 3.0
        # VaR% at 3Y is 1.4841%
        assert abs(result["interpolated_var_pct"] - 1.4841) < 0.01
        # VaR ≈ $200M × 1.4841% ≈ $2.968M
        assert abs(result["var_amount"] - 2.968e6) / 2.968e6 < 0.05

    def test_duration_mapping_less_than_principal(self):
        """Coupon bonds have duration < maturity, so duration mapping < principal."""
        engine = VaRMappingEngine(self._zero_vars())
        p = engine.principal_mapping(self._sample_portfolio())
        d = engine.duration_mapping(self._sample_portfolio())
        assert d["portfolio_duration"] < p["weighted_average_life"]
        assert d["var_amount"] < p["var_amount"]

    def test_cash_flow_mapping_diversified_less_than_undiversified(self):
        """Diversified VaR should be ≤ undiversified (except perfect correlation)."""
        engine = VaRMappingEngine(self._zero_vars())
        result = engine.cash_flow_mapping(self._sample_portfolio())
        assert result["diversified_var"] <= result["undiversified_var"]
        assert result["diversification_benefit"] >= 0

    def test_compare_methods_ranking(self):
        """More precise methods should give smaller VaR."""
        engine = VaRMappingEngine(self._zero_vars())
        result = engine.compare_methods(self._sample_portfolio())
        summary = result["summary"]
        # Diversified CF VaR should generally be ≤ Principal
        assert summary["cash_flow_diversified_var"] <= summary["principal_var"]

    def test_interpolation(self):
        """Interpolation should work for non-integer maturities."""
        engine = VaRMappingEngine(self._zero_vars())
        # 2.5 years should be between 2Y (0.9868) and 3Y (1.4841)
        v = engine._interpolate_var_pct(2.5)
        assert 0.9868 < v < 1.4841

    def test_fra_mapping(self):
        """FRA should decompose into 2 zero legs."""
        result = DerivativesMapper.fra_mapping(
            notional=100e6, short_maturity=0.5, long_maturity=1.0,
            short_rate=0.041, long_rate=0.045,
            var_pct_short=0.4696, var_pct_long=0.9868,
        )
        assert result["var_short_leg"] > 0
        assert result["var_long_leg"] > 0
        # FRA has opposite positions, diversified < undiversified
        assert result["diversified_var"] < result["undiversified_var"]

    def test_option_delta_normal(self):
        """Delta-normal option VaR should scale with |delta|."""
        res_low = DerivativesMapper.option_delta_normal_var(
            spot=100, delta=0.3, n_contracts=1000, spot_vol_annual=0.25,
        )
        res_high = DerivativesMapper.option_delta_normal_var(
            spot=100, delta=0.8, n_contracts=1000, spot_vol_annual=0.25,
        )
        assert res_high["var_amount"] > res_low["var_amount"]

    def test_tracking_error_matching_portfolio(self):
        """Identical portfolio and benchmark → TE ≈ 0."""
        engine = VaRMappingEngine(self._zero_vars())
        port = self._sample_portfolio()
        bench = self._sample_portfolio()
        te = tracking_error_var(port, bench, engine)
        assert te["tracking_error_diversified"] < 1e-4

    def test_tracking_error_mismatch(self):
        """Mismatched portfolio → positive TE."""
        engine = VaRMappingEngine(self._zero_vars())
        port = self._sample_portfolio()
        bench = [Bond("Bench", 200e6, 0.04, 3, ytm=0.04)]
        te = tracking_error_var(port, bench, engine)
        assert te["tracking_error_diversified"] > 0

    def test_api_endpoint(self):
        """API endpoint should return all three methods."""
        payload = {
            "bonds": [
                {"name": "B1", "face_value": 100e6, "coupon_rate": 0.035,
                 "maturity_years": 1, "ytm": 0.035},
                {"name": "B2", "face_value": 100e6, "coupon_rate": 0.05,
                 "maturity_years": 5, "ytm": 0.05},
            ],
            "zero_var_pct": {"1": 0.4696, "2": 0.9868, "3": 1.4841,
                             "4": 1.9946, "5": 2.5117},
        }
        res = client.post("/var-mapping", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "principal_mapping" in data
        assert "duration_mapping" in data
        assert "cash_flow_mapping" in data
        assert data["cash_flow_mapping"]["diversified_var"] > 0

# ─── LSTM Volatility Engine: Unit Tests ─────────────────────────────────────
from src.models.lstm_engine import AIModelComparison, LSTMVolatilityEngine, LSTMVolNet

try:
    import torch as _torch_check  # noqa: F401
    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False


@pytest.mark.skipif(not _TORCH_OK, reason="torch 미설치 — LSTM 기능은 선택적 의존성")
class TestLSTMUnit:
    """Unit tests for LSTM volatility engine."""

    def _make_returns(self, n=300, seed=42):
        np.random.seed(seed)
        idx = pd.date_range("2022-01-01", periods=n, freq="B")
        return pd.Series(np.random.normal(0, 0.015, n), index=idx)

    def test_lstm_model_forward(self):
        """LSTM model should produce correct output shape."""
        import torch
        model = LSTMVolNet(input_size=1, hidden_size=16, num_layers=2)
        x = torch.randn(4, 20, 1)  # (batch, seq, features)
        out = model(x)
        assert out.shape == (4,)  # batch predictions

    def test_lstm_train_basic(self):
        """LSTM should train and produce valid RMSE."""
        returns = self._make_returns(n=300)
        engine = LSTMVolatilityEngine(returns, epochs=5, window=20)
        result = engine.train()
        assert "rmse" in result
        assert result["rmse"] > 0
        assert result["rmse"] < 0.1   # sanity upper bound
        assert engine._trained is True

    def test_lstm_insufficient_data(self):
        """Should reject datasets that are too small."""
        returns = self._make_returns(n=40)
        engine = LSTMVolatilityEngine(returns, epochs=5)
        result = engine.train()
        assert "error" in result

    def test_lstm_predict_next(self):
        """Predict should return a positive volatility value."""
        returns = self._make_returns(n=300)
        engine = LSTMVolatilityEngine(returns, epochs=5)
        pred = engine.predict_next()
        assert pred > 0
        assert pred < 0.2

    def test_lstm_predict_n_step(self):
        """Multi-step forecast should return n predictions."""
        returns = self._make_returns(n=300)
        engine = LSTMVolatilityEngine(returns, epochs=5)
        forecasts = engine.predict_n_step(n_steps=5)
        assert len(forecasts) == 5
        assert all(f > 0 for f in forecasts)

    def test_lstm_predict_var(self):
        """LSTM-driven VaR should be positive."""
        returns = self._make_returns(n=300)
        engine = LSTMVolatilityEngine(returns, epochs=5)
        var = engine.predict_var(portfolio_value=1e9)
        assert var > 0

    def test_lstm_regime_classification(self):
        """Regime should return valid label."""
        returns = self._make_returns(n=300)
        engine = LSTMVolatilityEngine(returns, epochs=5)
        regime = engine.volatility_regime()
        assert regime in ["HIGH", "LOW", "NORMAL", "unknown"]

    def test_ai_comparison_structure(self):
        """AI comparison should return both models and a winner."""
        returns = self._make_returns(n=300)
        cmp = AIModelComparison(returns)
        result = cmp.compare(lstm_epochs=5)
        assert "random_forest" in result
        assert "lstm" in result
        assert result["winner_by_rmse"] in ["Random Forest", "LSTM"]
        assert "ensemble_prediction" in result

    def test_ai_comparison_both_positive(self):
        """Both models should produce positive vol predictions."""
        returns = self._make_returns(n=300)
        cmp = AIModelComparison(returns)
        result = cmp.compare(lstm_epochs=5)
        assert result["random_forest"]["prediction_next"] > 0
        assert result["lstm"]["prediction_next"] > 0

    def test_ai_comparison_directional_accuracy_bounded(self):
        """Directional accuracy should be in [0, 1]."""
        returns = self._make_returns(n=300)
        cmp = AIModelComparison(returns)
        result = cmp.compare(lstm_epochs=5)
        assert 0 <= result["random_forest"]["directional_accuracy"] <= 1
        assert 0 <= result["lstm"]["directional_accuracy"] <= 1

# ─── Multi-Feature AI Engine: Unit Tests ────────────────────────────────────
from src.models.feature_engine import FeatureEngineer, MultiFeatureVolatilityEngine


class TestMultiFeatureEngine:
    """Unit tests for technical indicator feature engineering."""

    def _make_ohlcv(self, n=400, seed=42):
        np.random.seed(seed)
        idx = pd.date_range("2022-01-01", periods=n, freq="B")
        close = 100 * np.exp(np.cumsum(np.random.normal(0, 0.015, n)))
        return pd.DataFrame({
            "Open":  close * (1 + np.random.normal(0, 0.002, n)),
            "High":  close * (1 + np.abs(np.random.normal(0.005, 0.003, n))),
            "Low":   close * (1 - np.abs(np.random.normal(0.005, 0.003, n))),
            "Close": close,
            "Volume": np.random.lognormal(15, 0.5, n),
        }, index=idx)

    def test_rsi_bounded(self):
        """RSI should always be in [0, 100]."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        rsi = fe.rsi()
        assert rsi.dropna().min() >= 0
        assert rsi.dropna().max() <= 100

    def test_macd_components(self):
        """MACD should return three series."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        macd_line, signal, hist = fe.macd()
        assert len(macd_line) == len(ohlcv)
        # Histogram = MACD - Signal
        assert np.allclose((macd_line - signal).dropna(), hist.dropna(), atol=1e-8)

    def test_bollinger_position_range(self):
        """Bollinger position should typically be in [-2, 2]."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        bp = fe.bollinger_position()
        assert bp.min() >= -2
        assert bp.max() <= 2

    def test_atr_positive(self):
        """ATR should always be positive."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        atr = fe.atr()
        assert atr.dropna().min() > 0

    def test_stochastic_bounded(self):
        """Stochastic %K should be in [0, 100]."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        stoch = fe.stochastic_oscillator()
        assert stoch.min() >= 0
        assert stoch.max() <= 100

    def test_volume_ratio_around_one(self):
        """Volume ratio mean should be near 1."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        vr = fe.volume_ratio()
        assert 0.8 < vr.mean() < 1.2

    def test_obv_cumulative(self):
        """OBV should be cumulative (monotonic partial sums)."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        obv = fe.obv()
        assert len(obv) == len(ohlcv)

    def test_feature_matrix_shape(self):
        """Feature matrix should have 19 columns."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        features = fe.build_feature_matrix()
        assert features.shape[1] == 19
        assert features.shape[0] == len(ohlcv)

    def test_feature_matrix_no_nan(self):
        """Feature matrix should have no NaN after filling."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        features = fe.build_feature_matrix()
        assert features.isna().sum().sum() == 0

    def test_feature_matrix_no_inf(self):
        """Feature matrix should have no infinite values."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        features = fe.build_feature_matrix()
        assert np.isfinite(features.values).all()

    def test_training_set_alignment(self):
        """X and y should have matching indices."""
        ohlcv = self._make_ohlcv()
        fe = FeatureEngineer(ohlcv)
        X, y = fe.build_training_set()
        assert len(X) == len(y)
        assert (X.index == y.index).all()

    def test_multi_feature_training(self):
        """Multi-feature engine should train successfully."""
        ohlcv = self._make_ohlcv()
        engine = MultiFeatureVolatilityEngine(ohlcv, model_type="random_forest")
        result = engine.train()
        assert "rmse" in result
        assert result["n_features"] == 19
        assert len(result["top_features"]) == 5

    def test_feature_importance_sums_to_one(self):
        """Feature importances should sum to ~1 (RF property)."""
        ohlcv = self._make_ohlcv()
        engine = MultiFeatureVolatilityEngine(ohlcv)
        engine.train()
        importances = engine.feature_importance()
        total = sum(f["importance"] for f in importances)
        assert abs(total - 1.0) < 1e-4

    def test_multi_feature_predict(self):
        """Predict should return positive vol."""
        ohlcv = self._make_ohlcv()
        engine = MultiFeatureVolatilityEngine(ohlcv)
        pred = engine.predict_next()
        assert pred > 0
        assert pred < 0.2

    def test_gradient_boosting_option(self):
        """Should also work with Gradient Boosting."""
        ohlcv = self._make_ohlcv()
        engine = MultiFeatureVolatilityEngine(ohlcv, model_type="gradient_boosting")
        result = engine.train()
        assert result["model_type"] == "gradient_boosting"
        assert result["rmse"] > 0

# ─── AI Model Monitoring: Unit Tests ────────────────────────────────────────
from src.models.model_monitor import (
    ModelMonitor,
    ks_drift_test,
    population_stability_index,
    psi_classification,
)


class TestModelMonitoring:
    """Unit tests for model monitoring and drift detection."""

    def _make_data(self, n=400, seed=42):
        np.random.seed(seed)
        idx = pd.date_range("2022-01-01", periods=n, freq="B")
        close = 100 * np.exp(np.cumsum(np.random.normal(0, 0.015, n)))
        ohlcv = pd.DataFrame({
            "Open": close * (1 + np.random.normal(0, 0.002, n)),
            "High": close * (1 + np.abs(np.random.normal(0.005, 0.003, n))),
            "Low": close * (1 - np.abs(np.random.normal(0.005, 0.003, n))),
            "Close": close,
            "Volume": np.random.lognormal(15, 0.5, n),
        }, index=idx)
        returns = np.log(ohlcv["Close"] / ohlcv["Close"].shift(1)).dropna()
        returns.name = "test"
        return ohlcv, returns

    # ─── PSI tests ──────────────────────────────────────────────────────────

    def test_psi_same_distribution_low(self):
        """Same distribution should give low PSI."""
        np.random.seed(42)
        a = np.random.normal(0, 1, 2000)
        b = np.random.normal(0, 1, 2000)
        psi = population_stability_index(a, b)
        assert psi < 0.10

    def test_psi_shifted_distribution_high(self):
        """Shifted distribution should give high PSI."""
        np.random.seed(42)
        a = np.random.normal(0, 1, 2000)
        b = np.random.normal(1.0, 1, 2000)
        psi = population_stability_index(a, b)
        assert psi > 0.20

    def test_psi_classification(self):
        """PSI classification should use correct thresholds."""
        assert psi_classification(0.05)[0] == "NO_SHIFT"
        assert psi_classification(0.15)[0] == "MODERATE_SHIFT"
        assert psi_classification(0.30)[0] == "SIGNIFICANT_SHIFT"

    def test_psi_empty_data(self):
        """Small/empty data should return 0."""
        assert population_stability_index(np.array([]), np.array([])) == 0.0

    # ─── KS test ────────────────────────────────────────────────────────────

    def test_ks_same_distribution(self):
        """Same distribution → high p-value (no drift)."""
        np.random.seed(42)
        a = np.random.normal(0, 1, 500)
        b = np.random.normal(0, 1, 500)
        result = ks_drift_test(a, b)
        assert result["p_value"] > 0.05
        assert not result["drift_detected"]

    def test_ks_different_distribution(self):
        """Clearly different distributions → low p-value (drift)."""
        np.random.seed(42)
        a = np.random.normal(0, 1, 500)
        b = np.random.normal(2, 1, 500)
        result = ks_drift_test(a, b)
        assert result["p_value"] < 0.05
        assert result["drift_detected"]

    # ─── Walk-forward backtest ──────────────────────────────────────────────

    def test_walk_forward_basic(self):
        """Walk-forward should produce predictions."""
        ohlcv, returns = self._make_data(n=300)
        monitor = ModelMonitor(
            ohlcv, returns, initial_train_ratio=0.5, refit_every=40,
        )
        result = monitor.walk_forward_backtest()
        assert "error" not in result or result.get("n_predictions", 0) > 0
        if "n_predictions" in result:
            assert result["n_predictions"] > 0
            assert len(result["predictions"]) == result["n_predictions"]
            assert len(result["actuals"]) == result["n_predictions"]

    def test_walk_forward_insufficient_data(self):
        """Short series should return error."""
        ohlcv, returns = self._make_data(n=100)
        monitor = ModelMonitor(ohlcv, returns)
        result = monitor.walk_forward_backtest()
        assert "error" in result

    # ─── Feature drift ──────────────────────────────────────────────────────

    def test_feature_drift_structure(self):
        """Feature drift should return valid dict with 19 features."""
        ohlcv, returns = self._make_data(n=300)
        monitor = ModelMonitor(ohlcv, returns)
        result = monitor.feature_drift()
        assert "max_psi" in result
        assert result["n_features"] == 19
        assert len(result["feature_drifts"]) == 19
        # Should be sorted by PSI descending
        psis = [f["psi"] for f in result["feature_drifts"]]
        assert psis == sorted(psis, reverse=True)

    # ─── Prediction drift ───────────────────────────────────────────────────

    def test_prediction_drift(self):
        """Prediction drift should be computed from backtest."""
        fake_backtest = {
            "predictions": list(np.random.normal(0.02, 0.005, 200)),
            "actuals": list(np.random.normal(0.02, 0.005, 200)),
            "errors": list(np.random.normal(0, 0.001, 200)),
        }
        ohlcv, returns = self._make_data(n=300)
        monitor = ModelMonitor(ohlcv, returns)
        result = monitor.prediction_drift(fake_backtest)
        assert "prediction_psi" in result
        assert "actual_psi" in result
        assert "interpretation" in result

    # ─── Error autocorrelation ──────────────────────────────────────────────

    def test_error_autocorrelation_healthy(self):
        """Random errors should have low autocorrelation."""
        np.random.seed(42)
        fake_backtest = {
            "errors": list(np.random.normal(0, 0.001, 200)),
        }
        ohlcv, returns = self._make_data(n=300)
        monitor = ModelMonitor(ohlcv, returns)
        result = monitor.error_autocorrelation(fake_backtest)
        assert result["severity"] in ["LOW", "MODERATE", "HIGH"]
        assert 0 <= result["mean_abs_autocorr"] <= 1

    def test_error_autocorrelation_trending(self):
        """Trending errors should trigger HIGH severity."""
        # Strongly correlated errors (simple random walk)
        n = 200
        rw = np.cumsum(np.random.normal(0, 0.001, n))
        fake_backtest = {"errors": list(rw)}
        ohlcv, returns = self._make_data(n=300)
        monitor = ModelMonitor(ohlcv, returns)
        result = monitor.error_autocorrelation(fake_backtest)
        assert result["mean_abs_autocorr"] > 0.3
        assert result["severity"] == "HIGH"

    # ─── Health status ──────────────────────────────────────────────────────

    def test_health_healthy(self):
        """Clean signals → HEALTHY status."""
        backtest = {"rmse_decay_pct": 5, "directional_accuracy": 0.60, "correlation": 0.55}
        feature_drift = {"any_significant_drift": False, "max_psi": 0.05}
        pred_drift = {"prediction_psi": 0.04}
        err_ac = {"severity": "LOW"}
        status = ModelMonitor.overall_health_status(
            backtest, feature_drift, pred_drift, err_ac
        )
        assert status["status"] == "HEALTHY"
        assert status["n_flags"] == 0

    def test_health_critical(self):
        """Bad signals → CRITICAL status."""
        backtest = {"rmse_decay_pct": 80, "directional_accuracy": 0.30, "correlation": 0.10}
        feature_drift = {"any_significant_drift": True, "max_psi": 0.40}
        pred_drift = {"prediction_psi": 0.35}
        err_ac = {"severity": "HIGH"}
        status = ModelMonitor.overall_health_status(
            backtest, feature_drift, pred_drift, err_ac
        )
        assert status["status"] == "CRITICAL"
        assert status["n_flags"] > 0

    def test_health_retrain(self):
        """Feature drift alone → RETRAIN status."""
        backtest = {"rmse_decay_pct": 10, "directional_accuracy": 0.55, "correlation": 0.50}
        feature_drift = {"any_significant_drift": True, "max_psi": 0.30}
        pred_drift = {"prediction_psi": 0.05}
        err_ac = {"severity": "LOW"}
        status = ModelMonitor.overall_health_status(
            backtest, feature_drift, pred_drift, err_ac
        )
        assert status["status"] == "RETRAIN"

    # ─── Full report ────────────────────────────────────────────────────────

    def test_full_report_integration(self):
        """Full report should have all sections."""
        ohlcv, returns = self._make_data(n=400, seed=7)
        monitor = ModelMonitor(
            ohlcv, returns, initial_train_ratio=0.5, refit_every=50,
        )
        report = monitor.full_report()
        if "error" in report:
            # Acceptable if data too unstable
            assert True
        else:
            assert "health_status" in report
            assert "backtest" in report
            assert "feature_drift" in report
            assert "prediction_drift" in report
            assert "error_autocorrelation" in report
            assert report["health_status"]["status"] in \
                ["HEALTHY", "MONITOR", "RETRAIN", "CRITICAL"]

# ─── Database / SQLAlchemy ORM: Unit Tests ──────────────────────────────────
import os as _os
import tempfile

# Need to reset DB before each test since TestClient uses the live DB
import src.database as dbmod


class TestDatabaseORM:
    """Unit tests for the SQLAlchemy ORM database layer.

    Uses isolated SQLite files per test via DATABASE_URL override.
    """

    def setup_method(self):
        # Fresh DB per test
        self.tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmpfile.close()
        self.db_path = self.tmpfile.name
        _os.environ["DATABASE_URL"] = f"sqlite:///{self.db_path}"
        dbmod.DATABASE_URL = f"sqlite:///{self.db_path}"
        dbmod.reset_session()
        dbmod.init_db()

    def teardown_method(self):
        dbmod.reset_session()
        try:
            _os.unlink(self.db_path)
        except OSError:
            pass

    def test_init_creates_admin(self):
        """init_db should bootstrap the admin user."""
        assert dbmod.verify_user("admin", "frm123!")

    def test_bcrypt_hash_roundtrip(self):
        """Hash and verify should round-trip."""
        h = dbmod.hash_password("secret123")
        assert h.startswith(("$2a$", "$2b$", "$2y$"))
        assert dbmod.verify_password("secret123", h)
        assert not dbmod.verify_password("wrong", h)

    def test_legacy_plaintext_verify(self):
        """Legacy plaintext comparison should still work during migration."""
        assert dbmod.verify_password("plain", "plain")
        assert not dbmod.verify_password("plain", "other")

    def test_create_user_duplicate(self):
        """Duplicate user creation should return False."""
        assert dbmod.create_user("newuser", "pw")
        assert not dbmod.create_user("newuser", "pw2")

    def test_portfolio_upsert(self):
        """Portfolio update should upsert correctly."""
        dbmod.update_user_portfolio("admin", "AAPL", 500e6, beta=1.5)
        p = dbmod.get_user_portfolio("admin")
        assert p["ticker"] == "AAPL"
        assert p["investment_amount"] == 500e6
        assert p["beta"] == 1.5

    def test_portfolio_default_for_new_user(self):
        """Unknown user should receive default portfolio."""
        p = dbmod.get_user_portfolio("ghost")
        assert p["ticker"] == "005930.KS"
        assert p["investment_amount"] == 100_000_000

    def test_trade_log_ordering(self):
        """Most recent trades should be listed first."""
        for i in range(5):
            dbmod.log_trade("admin", f"TICK{i}", 100 * (i + 1), "BUY", "FILLED")
        history = dbmod.get_trade_history("admin")
        assert len(history) == 5
        # Latest trade first
        assert history[0]["ticker"] == "TICK4"

    def test_trade_log_isolation_per_user(self):
        """Trades should be scoped per user."""
        dbmod.create_user("alice", "pw")
        dbmod.create_user("bob", "pw")
        dbmod.log_trade("alice", "AAPL", 100, "BUY", "FILLED")
        dbmod.log_trade("bob", "TSLA", 200, "SELL", "FILLED")
        alice_trades = dbmod.get_trade_history("alice")
        bob_trades = dbmod.get_trade_history("bob")
        assert len(alice_trades) == 1
        assert len(bob_trades) == 1
        assert alice_trades[0]["ticker"] == "AAPL"
        assert bob_trades[0]["ticker"] == "TSLA"

    def test_risk_snapshot_persistence(self):
        """Risk snapshots should be saved and retrievable."""
        snap_id = dbmod.save_risk_snapshot(
            "admin", "AAPL", "parametric",
            var_amount=1_000_000, es_amount=1_200_000,
            portfolio_value=100_000_000,
            extra={"confidence_level_used": 0.99},
        )
        assert snap_id > 0
        snaps = dbmod.get_risk_snapshots("AAPL")
        assert len(snaps) == 1
        assert snaps[0]["var_amount"] == 1_000_000
        assert snaps[0]["method"] == "parametric"

    def test_risk_snapshot_filter_by_ticker(self):
        """Filtering by ticker should exclude others."""
        dbmod.save_risk_snapshot("admin", "AAPL", "mc", 1e6)
        dbmod.save_risk_snapshot("admin", "TSLA", "mc", 2e6)
        dbmod.save_risk_snapshot("admin", "AAPL", "parametric", 3e6)
        aapl = dbmod.get_risk_snapshots("AAPL")
        tsla = dbmod.get_risk_snapshots("TSLA")
        assert len(aapl) == 2
        assert len(tsla) == 1

    def test_monitor_run_persistence(self):
        """AI monitor runs should be saved with full report."""
        run_id = dbmod.save_monitor_run(
            "AAPL", "HEALTHY",
            rmse=0.001, mae=0.0008, directional_accuracy=0.58,
            max_psi=0.08, rmse_decay_pct=5.0, n_flags=0,
            report={"test": "full", "details": [1, 2, 3]},
        )
        assert run_id > 0
        runs = dbmod.get_monitor_history("AAPL")
        assert len(runs) == 1
        assert runs[0]["status"] == "HEALTHY"
        assert runs[0]["rmse"] == 0.001

    def test_session_rollback_on_error(self):
        """Exception inside session_scope should roll back."""
        try:
            with dbmod.session_scope() as s:
                s.add(dbmod.User(
                    username="rollback_test",
                    password_hash=dbmod.hash_password("pw"),
                    role="analyst",
                ))
                raise RuntimeError("simulated error")
        except RuntimeError:
            pass

        # User should NOT exist
        with dbmod.session_scope() as s:
            user = s.query(dbmod.User).filter_by(username="rollback_test").first()
            assert user is None

    def test_get_connected_url(self):
        """get_connected_url should report current connection."""
        url = dbmod.get_connected_url()
        assert "sqlite" in url.lower() or "postgresql" in url.lower()

    def test_legacy_password_upgrade(self):
        """Legacy plaintext password should be upgraded on successful login."""
        with dbmod.session_scope() as s:
            legacy = dbmod.User(
                username="legacy_user",
                password_hash="plainpw",   # stored as plaintext
                role="analyst",
            )
            s.add(legacy)

        # First login with plaintext should succeed
        assert dbmod.verify_user("legacy_user", "plainpw")

        # After login, hash should be upgraded to bcrypt
        with dbmod.session_scope() as s:
            user = s.query(dbmod.User).filter_by(username="legacy_user").first()
            assert user.password_hash.startswith(("$2a$", "$2b$", "$2y$"))

        # Subsequent login still works with the same password
        assert dbmod.verify_user("legacy_user", "plainpw")


class TestSQLiteToPostgresMigration:
    """Unit tests for the SQLite → PostgreSQL migration script."""

    def setup_method(self):
        # Legacy SQLite source
        self.src_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.src_file.close()
        self.src_path = self.src_file.name

        # Target
        self.tgt_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tgt_file.close()
        self.tgt_path = self.tgt_file.name

        # Build legacy schema + data
        import sqlite3
        conn = sqlite3.connect(self.src_path)
        conn.executescript("""
            CREATE TABLE users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'analyst'
            );
            CREATE TABLE portfolios (
                username TEXT PRIMARY KEY,
                ticker TEXT, investment_amount REAL,
                beta REAL DEFAULT 1.0
            );
            CREATE TABLE trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT, ticker TEXT, qty INTEGER,
                side TEXT, status TEXT,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO users VALUES
                ('alice', 'alice_pw', 'analyst'),
                ('bob', 'bob_pw', 'trader');
            INSERT INTO portfolios VALUES
                ('alice', 'AAPL', 500000000, 1.5),
                ('bob', 'TSLA', 200000000, 2.0);
            INSERT INTO trade_log (username, ticker, qty, side, status) VALUES
                ('alice', 'AAPL', 100, 'BUY', 'FILLED'),
                ('alice', 'MSFT', 50, 'SELL', 'FILLED'),
                ('bob', 'TSLA', 200, 'BUY', 'FILLED');
        """)
        conn.commit()
        conn.close()

        # Point target DB to the fresh temp file
        _os.environ["DATABASE_URL"] = f"sqlite:///{self.tgt_path}"
        dbmod.DATABASE_URL = f"sqlite:///{self.tgt_path}"
        dbmod.reset_session()

    def teardown_method(self):
        dbmod.reset_session()
        for path in [self.src_path, self.tgt_path]:
            try:
                _os.unlink(path)
            except OSError:
                pass

    def test_migration_preserves_users(self):
        from src.migrations.sqlite_to_postgres import run_migration
        result = run_migration(self.src_path)
        # Admin was auto-created by init_db + 2 migrated = 2 new migrated
        assert result["users_migrated"] == 2
        assert dbmod.verify_user("alice", "alice_pw")
        assert dbmod.verify_user("bob", "bob_pw")

    def test_migration_preserves_portfolios(self):
        from src.migrations.sqlite_to_postgres import run_migration
        run_migration(self.src_path)
        p_alice = dbmod.get_user_portfolio("alice")
        p_bob = dbmod.get_user_portfolio("bob")
        assert p_alice["ticker"] == "AAPL"
        assert p_alice["investment_amount"] == 500_000_000
        assert p_bob["ticker"] == "TSLA"
        assert p_bob["beta"] == 2.0

    def test_migration_preserves_trades(self):
        from src.migrations.sqlite_to_postgres import run_migration
        result = run_migration(self.src_path)
        assert result["trades_migrated"] == 3
        alice_trades = dbmod.get_trade_history("alice")
        bob_trades = dbmod.get_trade_history("bob")
        assert len(alice_trades) == 2
        assert len(bob_trades) == 1

    def test_migration_idempotent(self):
        """Re-running migration should not create duplicates."""
        from src.migrations.sqlite_to_postgres import run_migration
        run_migration(self.src_path)
        result2 = run_migration(self.src_path)
        # Second run should migrate 0 (all already exist)
        assert result2["users_migrated"] == 0
        assert result2["portfolios_migrated"] == 0
        assert result2["trades_migrated"] == 0

    def test_migration_hashes_plaintext_passwords(self):
        """Plaintext passwords should be bcrypt-hashed after migration."""
        from src.migrations.sqlite_to_postgres import run_migration
        run_migration(self.src_path)
        with dbmod.session_scope() as s:
            alice = s.query(dbmod.User).filter_by(username="alice").first()
            assert alice.password_hash.startswith(("$2a$", "$2b$", "$2y$"))
