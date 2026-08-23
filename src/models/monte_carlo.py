"""
Monte Carlo VaR Engine
======================
Full-simulation risk engine using correlated Geometric Brownian Motion paths.

Theory (FRM Part II aligned):
  Single asset:  S_T = S_0 * exp((μ − σ²/2)T + σ√T · Z),  Z ~ N(0,1)
  Multi-asset:   Z_corr = L · Z_iid,  where L = cholesky(Σ_corr)
  VaR_α:         α-th percentile of simulated portfolio loss distribution
  ES_α:          mean of losses beyond VaR_α

Features:
  - Single-asset GBM VaR / ES
  - Multi-asset correlated GBM via Cholesky decomposition
  - Antithetic variates for variance reduction
  - Convergence diagnostics (VaR std error)
  - Full loss distribution for downstream analysis
"""


import numpy as np
import pandas as pd
from scipy.stats import norm


class MonteCarloVaR:
    """
    Monte Carlo VaR engine supporting single- and multi-asset portfolios.

    Parameters
    ----------
    n_simulations : int
        Number of Monte Carlo paths (default 10,000).
    holding_period : int
        VaR holding period in trading days (default 1).
    confidence_level : float
        VaR confidence level (default 0.99).
    seed : int or None
        Random seed for reproducibility.
    antithetic : bool
        Use antithetic variates for variance reduction.
    """

    def __init__(
        self,
        n_simulations: int = 10_000,
        holding_period: int = 1,
        confidence_level: float = 0.99,
        seed: int | None = 42,
        antithetic: bool = True,
    ):
        self.n_sims = n_simulations
        self.T = holding_period
        self.cl = confidence_level
        self.seed = seed
        self.antithetic = antithetic

    # ═══════════════════════════════════════════════════════════════════════════
    # SINGLE ASSET
    # ═══════════════════════════════════════════════════════════════════════════

    def simulate_gbm_single(
        self,
        S0: float,
        mu: float,
        sigma: float,
    ) -> np.ndarray:
        """
        Simulate terminal prices via GBM.

        S_T = S_0 · exp((μ − σ²/2)·T + σ·√T · Z)

        With antithetic variates, each Z is paired with −Z to reduce variance.
        """
        rng = np.random.default_rng(self.seed)
        dt = self.T / 252.0  # convert trading days to years

        if self.antithetic:
            half_n = self.n_sims // 2
            z_half = rng.standard_normal(half_n)
            z = np.concatenate([z_half, -z_half])
        else:
            z = rng.standard_normal(self.n_sims)

        drift = (mu - 0.5 * sigma ** 2) * dt
        diffusion = sigma * np.sqrt(dt) * z
        S_T = S0 * np.exp(drift + diffusion)
        return S_T

    def single_asset_var(
        self,
        returns: pd.Series,
        portfolio_value: float,
        use_ewma: bool = True,
        ewma_lambda: float = 0.94,
    ) -> dict:
        """
        Monte Carlo VaR for a single asset.

        Estimates μ and σ from historical returns, simulates GBM paths,
        then extracts VaR and ES from the simulated P&L distribution.
        """
        mu_annual = float(returns.mean()) * 252

        if use_ewma:
            # EWMA daily vol → annualised
            ewma_var = 0.0
            lam = ewma_lambda
            ret_vals = returns.values
            for r in ret_vals:
                ewma_var = lam * ewma_var + (1 - lam) * r ** 2
            sigma_daily = np.sqrt(ewma_var)
        else:
            sigma_daily = float(returns.std())

        sigma_annual = sigma_daily * np.sqrt(252)

        S0 = portfolio_value
        S_T = self.simulate_gbm_single(S0, mu_annual, sigma_annual)

        # P&L = terminal value − initial value (positive = gain, negative = loss)
        pnl = S_T - S0
        losses = -pnl  # positive = loss

        alpha_pct = (1 - self.cl) * 100
        var_amount = float(np.percentile(losses, 100 - alpha_pct))
        es_amount = float(np.mean(losses[losses >= var_amount]))

        # Convergence diagnostic: standard error of VaR estimate
        var_se = self._var_standard_error(losses, var_amount)

        return {
            "method": "Monte Carlo (GBM)",
            "n_simulations": len(S_T),
            "holding_period_days": self.T,
            "confidence_level": self.cl,
            "mu_annual": round(mu_annual, 6),
            "sigma_annual": round(sigma_annual, 6),
            "var_amount": round(var_amount, 0),
            "var_pct": round(var_amount / portfolio_value, 6),
            "es_amount": round(es_amount, 0),
            "es_pct": round(es_amount / portfolio_value, 6),
            "var_std_error": round(var_se, 0),
            "mean_pnl": round(float(np.mean(pnl)), 0),
            "worst_loss": round(float(np.max(losses)), 0),
            "best_gain": round(float(np.max(pnl)), 0),
            "percentiles": {
                "1%": round(float(np.percentile(pnl, 1)), 0),
                "5%": round(float(np.percentile(pnl, 5)), 0),
                "50%": round(float(np.percentile(pnl, 50)), 0),
                "95%": round(float(np.percentile(pnl, 95)), 0),
                "99%": round(float(np.percentile(pnl, 99)), 0),
            },
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # MULTI-ASSET (Cholesky Decomposition)
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def cholesky_decompose(corr_matrix: np.ndarray) -> np.ndarray:
        """
        Cholesky decomposition of correlation matrix.

        Given Σ = L · Lᵀ, we generate correlated normals: Z_corr = L · Z_iid

        If the matrix is not positive-definite (common with estimated correlations),
        applies nearest-PD correction via eigenvalue flooring.
        """
        try:
            L = np.linalg.cholesky(corr_matrix)
        except np.linalg.LinAlgError:
            # Nearest positive-definite matrix (eigenvalue flooring)
            eigvals, eigvecs = np.linalg.eigh(corr_matrix)
            eigvals = np.maximum(eigvals, 1e-8)
            corr_fixed = eigvecs @ np.diag(eigvals) @ eigvecs.T
            # Re-normalise to correlation matrix (unit diagonal)
            d = np.sqrt(np.diag(corr_fixed))
            corr_fixed = corr_fixed / np.outer(d, d)
            np.fill_diagonal(corr_fixed, 1.0)
            L = np.linalg.cholesky(corr_fixed)
        return L

    def simulate_gbm_multi(
        self,
        mu_vec: np.ndarray,
        sigma_vec: np.ndarray,
        corr_matrix: np.ndarray,
        weights: np.ndarray,
        portfolio_value: float,
    ) -> np.ndarray:
        """
        Simulate correlated multi-asset portfolio returns via GBM + Cholesky.

        Steps:
          1. Generate n_sims × n_assets IID standard normals Z
          2. Apply Cholesky: Z_corr = L · Z  (introduces correlation)
          3. GBM per asset: R_i = (μ_i − σ_i²/2)·dt + σ_i·√dt · Z_corr_i
          4. Portfolio return = Σ w_i · R_i
          5. Portfolio P&L = portfolio_value · portfolio_return

        Returns
        -------
        np.ndarray  Simulated portfolio P&L (n_sims,)
        """
        rng = np.random.default_rng(self.seed)
        n_assets = len(mu_vec)
        dt = self.T / 252.0

        L = self.cholesky_decompose(corr_matrix)

        if self.antithetic:
            half_n = self.n_sims // 2
            Z_iid_half = rng.standard_normal((n_assets, half_n))
            Z_iid = np.concatenate([Z_iid_half, -Z_iid_half], axis=1)
        else:
            Z_iid = rng.standard_normal((n_assets, self.n_sims))

        # L @ Z_iid → (n_assets, n_sims) correlated normals
        Z_corr = L @ Z_iid

        # GBM returns per asset: (n_assets, n_sims)
        drift = (mu_vec - 0.5 * sigma_vec ** 2) * dt
        diffusion = sigma_vec[:, None] * np.sqrt(dt) * Z_corr
        asset_returns = drift[:, None] + diffusion

        # Portfolio returns: (n_sims,)
        port_returns = weights @ asset_returns
        port_pnl = portfolio_value * port_returns
        return port_pnl

    def multi_asset_var(
        self,
        returns_df: pd.DataFrame,
        weights: np.ndarray,
        portfolio_value: float,
        use_ewma: bool = True,
        ewma_lambda: float = 0.94,
    ) -> dict:
        """
        Monte Carlo VaR for a correlated multi-asset portfolio.

        Parameters
        ----------
        returns_df : pd.DataFrame
            Daily log returns, one column per asset.
        weights : np.ndarray
            Portfolio weights (must sum to 1).
        portfolio_value : float
            Total portfolio value.

        Returns
        -------
        dict  Comprehensive MC VaR report.
        """
        n_assets = returns_df.shape[1]
        tickers = list(returns_df.columns)

        # Annualised parameters
        mu_vec = returns_df.mean().values * 252

        if use_ewma:
            sigma_daily = np.array([
                self._ewma_vol(returns_df.iloc[:, i].values, ewma_lambda)
                for i in range(n_assets)
            ])
        else:
            sigma_daily = returns_df.std().values

        sigma_vec = sigma_daily * np.sqrt(252)
        corr_matrix = returns_df.corr().values

        # Simulate
        pnl = self.simulate_gbm_multi(
            mu_vec, sigma_vec, corr_matrix, weights, portfolio_value
        )

        losses = -pnl
        alpha_pct = (1 - self.cl) * 100
        var_amount = float(np.percentile(losses, 100 - alpha_pct))
        tail = losses[losses >= var_amount]
        es_amount = float(np.mean(tail)) if len(tail) > 0 else var_amount

        # Individual asset VaRs for diversification benefit analysis
        z = norm.ppf(self.cl)
        individual_vars = []
        for i in range(n_assets):
            # Parametric individual VaR: |w_i| * P * z * σ_daily * √T
            asset_var = abs(weights[i]) * portfolio_value * z * sigma_daily[i] * np.sqrt(self.T)
            individual_vars.append(float(asset_var))

        undiv_var = sum(individual_vars)
        div_benefit = undiv_var - var_amount
        div_benefit_pct = (div_benefit / undiv_var * 100) if undiv_var > 0 else 0

        var_se = self._var_standard_error(losses, var_amount)

        # Cholesky matrix (lower triangular) for inspection
        L = self.cholesky_decompose(corr_matrix)

        return {
            "method": "Monte Carlo (Multi-Asset GBM + Cholesky)",
            "n_simulations": len(pnl),
            "n_assets": n_assets,
            "tickers": tickers,
            "holding_period_days": self.T,
            "confidence_level": self.cl,
            "portfolio_value": portfolio_value,
            # ── VaR / ES ──
            "mc_var_amount": round(var_amount, 0),
            "mc_var_pct": round(var_amount / portfolio_value, 6),
            "mc_es_amount": round(es_amount, 0),
            "mc_es_pct": round(es_amount / portfolio_value, 6),
            "var_std_error": round(var_se, 0),
            # ── Diversification ──
            "individual_vars": {
                t: round(v, 0) for t, v in zip(tickers, individual_vars)
            },
            "undiversified_var": round(undiv_var, 0),
            "diversification_benefit": round(div_benefit, 0),
            "diversification_benefit_pct": round(div_benefit_pct, 2),
            # ── Per-asset parameters ──
            "asset_params": {
                t: {
                    "weight": round(float(weights[i]), 4),
                    "mu_annual": round(float(mu_vec[i]), 6),
                    "sigma_annual": round(float(sigma_vec[i]), 6),
                }
                for i, t in enumerate(tickers)
            },
            # ── Correlation & Cholesky ──
            "correlation_matrix": {
                tickers[i]: {
                    tickers[j]: round(float(corr_matrix[i, j]), 4)
                    for j in range(n_assets)
                }
                for i in range(n_assets)
            },
            "cholesky_matrix": np.round(L, 4).tolist(),
            # ── Distribution summary ──
            "pnl_stats": {
                "mean": round(float(np.mean(pnl)), 0),
                "std": round(float(np.std(pnl)), 0),
                "skewness": round(float(self._skewness(pnl)), 4),
                "kurtosis": round(float(self._kurtosis(pnl)), 4),
                "worst_loss": round(float(np.max(losses)), 0),
                "best_gain": round(float(np.max(pnl)), 0),
            },
            "percentiles": {
                "1%": round(float(np.percentile(pnl, 1)), 0),
                "5%": round(float(np.percentile(pnl, 5)), 0),
                "25%": round(float(np.percentile(pnl, 25)), 0),
                "50%": round(float(np.percentile(pnl, 50)), 0),
                "75%": round(float(np.percentile(pnl, 75)), 0),
                "95%": round(float(np.percentile(pnl, 95)), 0),
                "99%": round(float(np.percentile(pnl, 99)), 0),
            },
            # ── Histogram data for frontend ──
            "histogram": self._pnl_histogram(pnl, var_amount),
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # CONVERGENCE ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════════

    def convergence_analysis(
        self,
        returns_df: pd.DataFrame,
        weights: np.ndarray,
        portfolio_value: float,
        checkpoints: list[int] = None,
        use_ewma: bool = True,
        ewma_lambda: float = 0.94,
    ) -> list[dict]:
        """
        Run MC VaR at increasing simulation counts to show convergence.

        Returns a list of {n_sims, var_amount, var_se} for plotting.
        """
        if checkpoints is None:
            checkpoints = [500, 1000, 2500, 5000, 10000, 25000, 50000]

        results = []
        for n in checkpoints:
            engine = MonteCarloVaR(
                n_simulations=n,
                holding_period=self.T,
                confidence_level=self.cl,
                seed=self.seed,
                antithetic=self.antithetic,
            )
            if returns_df.shape[1] == 1:
                res = engine.single_asset_var(
                    returns_df.iloc[:, 0], portfolio_value,
                    use_ewma=use_ewma, ewma_lambda=ewma_lambda,
                )
                results.append({
                    "n_simulations": n,
                    "var_amount": res["var_amount"],
                    "var_std_error": res["var_std_error"],
                })
            else:
                res = engine.multi_asset_var(
                    returns_df, weights, portfolio_value,
                    use_ewma=use_ewma, ewma_lambda=ewma_lambda,
                )
                results.append({
                    "n_simulations": n,
                    "var_amount": res["mc_var_amount"],
                    "var_std_error": res["var_std_error"],
                })
        return results

    # ═══════════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _ewma_vol(returns: np.ndarray, lam: float = 0.94) -> float:
        """EWMA daily volatility."""
        var = 0.0
        for r in returns:
            var = lam * var + (1 - lam) * r ** 2
        return np.sqrt(var)

    @staticmethod
    def _var_standard_error(losses: np.ndarray, var_amount: float) -> float:
        """
        Standard error of VaR estimate using kernel density approach.

        SE(VaR) ≈ √(p(1-p) / (n · f(VaR)²))
        where f is estimated from a Gaussian kernel.
        """
        n = len(losses)
        p = np.mean(losses >= var_amount)
        if p <= 0 or p >= 1:
            return 0.0

        # Gaussian kernel density estimate at VaR point
        h = 1.06 * np.std(losses) * n ** (-0.2)  # Silverman bandwidth
        if h == 0:
            return 0.0
        kernel_vals = norm.pdf((losses - var_amount) / h)
        f_var = np.mean(kernel_vals) / h

        if f_var == 0:
            return 0.0
        se = np.sqrt(p * (1 - p) / n) / f_var
        return float(se)

    @staticmethod
    def _skewness(x: np.ndarray) -> float:
        n = len(x)
        m = np.mean(x)
        s = np.std(x, ddof=1)
        if s == 0:
            return 0.0
        return float((n / ((n - 1) * (n - 2))) * np.sum(((x - m) / s) ** 3))

    @staticmethod
    def _kurtosis(x: np.ndarray) -> float:
        """Excess kurtosis (normal = 0)."""
        len(x)
        m = np.mean(x)
        s = np.std(x, ddof=1)
        if s == 0:
            return 0.0
        k4 = np.mean(((x - m) / s) ** 4)
        return float(k4 - 3.0)

    @staticmethod
    def _pnl_histogram(pnl: np.ndarray, var_amount: float, bins: int = 50) -> dict:
        """Generate histogram data for frontend visualisation."""
        counts, edges = np.histogram(pnl, bins=bins)
        bin_centers = [(edges[i] + edges[i + 1]) / 2 for i in range(len(counts))]
        return {
            "bin_centers": [round(float(c), 0) for c in bin_centers],
            "counts": counts.tolist(),
            "var_line": round(float(-var_amount), 0),  # negative because PnL axis
        }
