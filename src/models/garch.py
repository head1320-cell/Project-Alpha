"""
GARCH(1,1) Conditional Volatility Model
========================================
Captures volatility clustering and mean-reversion that EWMA cannot.

Model:
    σ²_t = ω + α · r²_{t-1} + β · σ²_{t-1}

    where:
      ω = γ · V_L   (weight on long-run variance)
      α            (reaction coefficient — sensitivity to market shocks)
      β            (persistence coefficient — memory of past variance)
      γ = 1-α-β    (weight on long-run variance)
      V_L = ω/(1-α-β)  (unconditional / long-run variance)

Constraints:
    ω > 0, α ≥ 0, β ≥ 0, α+β < 1 (stationarity)

Special case — EWMA (RiskMetrics):
    ω = 0, α = (1-λ), β = λ  ⇒  no mean-reversion, persistence = 1

Estimation:
    Maximum Likelihood (MLE) assuming r_t | F_{t-1} ~ N(0, σ²_t)
    LL = Σ [-½ ln(2π) - ½ ln(σ²_t) - ½ r²_t / σ²_t]

Reference: FRM Part II — filtered historical simulation relies on GARCH;
           Basel VaR models commonly use GARCH for dynamic volatility.
"""


import numpy as np
import pandas as pd
from scipy.optimize import minimize


class GARCH11:
    """
    GARCH(1,1) model with MLE parameter estimation.

    Attributes (after fit):
        omega, alpha, beta : float  — estimated parameters
        persistence        : float  — α + β (volatility half-life driver)
        long_run_variance  : float  — ω / (1 - α - β)
        log_likelihood     : float  — maximised log-likelihood
        aic, bic           : float  — information criteria
    """

    def __init__(self):
        self.omega: float = 0.0
        self.alpha: float = 0.0
        self.beta: float = 0.0
        self._fitted = False
        self.log_likelihood: float = 0.0
        self.aic: float = 0.0
        self.bic: float = 0.0
        self._returns: np.ndarray | None = None

    # ─── Core recursion ──────────────────────────────────────────────────────

    @staticmethod
    def _variance_recursion(
        params: np.ndarray, returns: np.ndarray
    ) -> np.ndarray:
        """
        Compute conditional variance series given (ω, α, β) and return data.

        σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}

        Initialises σ²_0 with the sample variance (unconditional estimate).
        """
        omega, alpha, beta = params
        T = len(returns)
        sigma2 = np.empty(T)
        sigma2[0] = np.var(returns)  # unconditional seed

        for t in range(1, T):
            sigma2[t] = omega + alpha * returns[t - 1] ** 2 + beta * sigma2[t - 1]
            # Floor to prevent numerical collapse
            if sigma2[t] < 1e-12:
                sigma2[t] = 1e-12

        return sigma2

    # ─── Negative log-likelihood (for minimiser) ─────────────────────────────

    @staticmethod
    def _neg_log_likelihood(params: np.ndarray, returns: np.ndarray) -> float:
        """
        -LL = Σ [½ ln(2π) + ½ ln(σ²_t) + ½ r²_t/σ²_t]

        Returns scalar (to be minimised).
        """
        sigma2 = GARCH11._variance_recursion(params, returns)
        # Guard: any non-positive variance → return large penalty
        if np.any(sigma2 <= 0):
            return 1e10

        ll = -0.5 * np.sum(
            np.log(2 * np.pi) + np.log(sigma2) + returns ** 2 / sigma2
        )
        return -ll  # we minimise negative LL

    # ─── MLE Fitting ─────────────────────────────────────────────────────────

    def fit(self, returns: pd.Series | np.ndarray) -> "GARCH11":
        """
        Estimate (ω, α, β) via MLE with constraints:
          ω > 0, α ≥ 0, β ≥ 0, α+β < 1

        Uses L-BFGS-B with bound constraints and multiple restarts
        to avoid local optima.
        """
        if isinstance(returns, pd.Series):
            r = returns.dropna().values.astype(float)
        else:
            r = np.asarray(returns, dtype=float)

        self._returns = r
        T = len(r)
        sample_var = np.var(r)

        # Starting points (multiple restarts for robustness)
        starts = [
            np.array([sample_var * 0.05, 0.08, 0.88]),  # typical equity
            np.array([sample_var * 0.10, 0.15, 0.75]),   # higher α
            np.array([sample_var * 0.02, 0.05, 0.93]),   # high persistence
        ]

        bounds = [
            (1e-10, sample_var * 10),  # ω
            (1e-6, 0.5),              # α
            (0.3, 0.999),             # β
        ]

        # Stationarity constraint: α + β < 1
        constraints = [
            {"type": "ineq", "fun": lambda p: 0.9999 - p[1] - p[2]},
        ]

        best_result = None
        best_nll = np.inf

        for x0 in starts:
            try:
                result = minimize(
                    self._neg_log_likelihood,
                    x0,
                    args=(r,),
                    method="SLSQP",
                    bounds=bounds,
                    constraints=constraints,
                    options={"maxiter": 500, "ftol": 1e-12},
                )
                if result.fun < best_nll:
                    best_nll = result.fun
                    best_result = result
            except Exception:
                continue

        if best_result is None or not best_result.success:
            # Fallback: use heuristic parameters
            self.omega = sample_var * 0.05
            self.alpha = 0.08
            self.beta = 0.90
        else:
            self.omega = float(best_result.x[0])
            self.alpha = float(best_result.x[1])
            self.beta = float(best_result.x[2])

        self.log_likelihood = float(-best_nll) if best_result else 0.0
        k = 3  # number of parameters
        self.aic = float(-2 * self.log_likelihood + 2 * k)
        self.bic = float(-2 * self.log_likelihood + k * np.log(T))
        self._fitted = True

        return self

    # ─── Properties ──────────────────────────────────────────────────────────

    @property
    def persistence(self) -> float:
        """α + β — measures how long volatility shocks last."""
        return self.alpha + self.beta

    @property
    def long_run_variance(self) -> float:
        """V_L = ω / (1 - α - β) — unconditional variance the process reverts to."""
        gamma = 1.0 - self.persistence
        if gamma <= 0:
            return np.var(self._returns) if self._returns is not None else 0.0
        return self.omega / gamma

    @property
    def long_run_volatility(self) -> float:
        """√V_L — annualisable long-run daily standard deviation."""
        return np.sqrt(self.long_run_variance)

    @property
    def half_life(self) -> float:
        """
        Volatility half-life in days: how quickly σ² reverts halfway to V_L.
        HL = ln(2) / ln(1/persistence)
        """
        p = self.persistence
        if p <= 0 or p >= 1:
            return np.inf
        return np.log(2) / np.log(1.0 / p)

    # ─── Forecasting ─────────────────────────────────────────────────────────

    def variance_series(self, returns: np.ndarray | None = None) -> np.ndarray:
        """Conditional variance series from fitted parameters."""
        if returns is None:
            returns = self._returns
        if returns is None:
            raise ValueError("No return data — call fit() first or pass returns.")
        params = np.array([self.omega, self.alpha, self.beta])
        return self._variance_recursion(params, returns)

    def volatility_series(self, returns: pd.Series | None = None) -> pd.Series:
        """Conditional volatility (daily σ) as a pandas Series."""
        if returns is not None:
            r = returns.dropna()
            sigma2 = self.variance_series(r.values)
            return pd.Series(np.sqrt(sigma2), index=r.index, name="garch_vol")
        sigma2 = self.variance_series()
        return pd.Series(np.sqrt(sigma2), name="garch_vol")

    def latest_volatility(self, returns: pd.Series | None = None) -> float:
        """Most recent daily σ forecast."""
        return float(self.volatility_series(returns).iloc[-1])

    def forecast_variance(self, n_ahead: int = 1) -> np.ndarray:
        """
        Multi-step ahead variance forecast.

        σ²_{t+k} = V_L + (α+β)^k · (σ²_t - V_L)

        Converges to V_L as k → ∞.
        """
        sigma2 = self.variance_series()
        current = sigma2[-1]
        vl = self.long_run_variance
        p = self.persistence

        forecasts = np.empty(n_ahead)
        for k in range(n_ahead):
            forecasts[k] = vl + p ** (k + 1) * (current - vl)
        return forecasts

    def forecast_volatility(self, n_ahead: int = 1) -> np.ndarray:
        """Multi-step ahead volatility (σ) forecast."""
        return np.sqrt(self.forecast_variance(n_ahead))

    # ─── Standardised residuals (for filtered historical sim) ────────────────

    def standardised_residuals(self, returns: pd.Series | None = None) -> np.ndarray:
        """
        z_t = r_t / σ_t

        Should be ~N(0,1) if the model is correct.
        Used as input for filtered historical simulation.
        """
        if returns is not None:
            r = returns.dropna().values
        else:
            r = self._returns
        sigma = np.sqrt(self.variance_series(r))
        return r / sigma

    # ─── Summary report ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return a complete model summary dictionary."""
        return {
            "model": "GARCH(1,1)",
            "omega": round(self.omega, 10),
            "alpha": round(self.alpha, 6),
            "beta": round(self.beta, 6),
            "persistence": round(self.persistence, 6),
            "long_run_variance_daily": round(self.long_run_variance, 10),
            "long_run_vol_daily": round(self.long_run_volatility, 6),
            "long_run_vol_annual": round(self.long_run_volatility * np.sqrt(252), 6),
            "half_life_days": round(self.half_life, 2),
            "log_likelihood": round(self.log_likelihood, 4),
            "aic": round(self.aic, 4),
            "bic": round(self.bic, 4),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# EWMA Model (companion class for head-to-head comparison)
# ═══════════════════════════════════════════════════════════════════════════════

class EWMA:
    """
    EWMA volatility model — the RiskMetrics special case of GARCH.

    σ²_t = λ·σ²_{t-1} + (1-λ)·r²_{t-1}

    Equivalent to GARCH(1,1) with ω=0, α=(1-λ), β=λ.
    No mean-reversion: long-run variance is undefined (persistence = 1).
    """

    def __init__(self, lam: float = 0.94):
        self.lam = lam

    @property
    def alpha_equiv(self) -> float:
        return 1.0 - self.lam

    @property
    def beta_equiv(self) -> float:
        return self.lam

    def variance_series(self, returns: np.ndarray) -> np.ndarray:
        T = len(returns)
        sigma2 = np.empty(T)
        sigma2[0] = np.var(returns)
        for t in range(1, T):
            sigma2[t] = self.lam * sigma2[t - 1] + (1 - self.lam) * returns[t - 1] ** 2
        return sigma2

    def volatility_series(self, returns: pd.Series) -> pd.Series:
        r = returns.dropna()
        sigma2 = self.variance_series(r.values)
        return pd.Series(np.sqrt(sigma2), index=r.index, name="ewma_vol")

    def latest_volatility(self, returns: pd.Series) -> float:
        return float(self.volatility_series(returns).iloc[-1])

    def log_likelihood(self, returns: np.ndarray) -> float:
        """LL under the same Gaussian assumption as GARCH for fair comparison."""
        sigma2 = self.variance_series(returns)
        sigma2 = np.maximum(sigma2, 1e-12)
        return float(-0.5 * np.sum(
            np.log(2 * np.pi) + np.log(sigma2) + returns ** 2 / sigma2
        ))

    def summary(self, returns: np.ndarray) -> dict:
        ll = self.log_likelihood(returns)
        T = len(returns)
        k = 1  # only λ is a parameter
        return {
            "model": f"EWMA (λ={self.lam})",
            "lambda": self.lam,
            "alpha_equiv": round(self.alpha_equiv, 4),
            "beta_equiv": round(self.beta_equiv, 4),
            "persistence": 1.0,
            "long_run_variance_daily": None,
            "long_run_vol_daily": None,
            "long_run_vol_annual": None,
            "half_life_days": float("inf"),
            "log_likelihood": round(ll, 4),
            "aic": round(-2 * ll + 2 * k, 4),
            "bic": round(-2 * ll + k * np.log(T), 4),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Head-to-head comparison engine
# ═══════════════════════════════════════════════════════════════════════════════

class VolatilityModelComparison:
    """
    Compare GARCH(1,1) vs EWMA on the same return series.

    Outputs:
      - Parameter comparison table
      - Information criteria (AIC/BIC) — lower is better
      - Current & forecasted volatility from each model
      - Volatility time series for overlay chart
    """

    def __init__(self, returns: pd.Series, ewma_lambda: float = 0.94):
        self.returns = returns.dropna()
        self.r = self.returns.values.astype(float)
        self.ewma_lambda = ewma_lambda

        # Fit models
        self.garch = GARCH11().fit(self.returns)
        self.ewma = EWMA(ewma_lambda)

    def compare(self) -> dict:
        """Full comparison report."""
        garch_sum = self.garch.summary()
        ewma_sum = self.ewma.summary(self.r)

        garch_vol_series = self.garch.volatility_series(self.returns)
        ewma_vol_series = self.ewma.volatility_series(self.returns)

        # Current volatilities
        garch_current = float(garch_vol_series.iloc[-1])
        ewma_current = float(ewma_vol_series.iloc[-1])

        # 5-day forecast
        garch_forecast = self.garch.forecast_volatility(5)

        # Model selection via AIC/BIC
        garch_aic = garch_sum["aic"]
        ewma_aic = ewma_sum["aic"]
        aic_winner = "GARCH(1,1)" if garch_aic < ewma_aic else f"EWMA(λ={self.ewma_lambda})"

        garch_bic = garch_sum["bic"]
        ewma_bic = ewma_sum["bic"]
        bic_winner = "GARCH(1,1)" if garch_bic < ewma_bic else f"EWMA(λ={self.ewma_lambda})"

        # Standardised residual stats (GARCH model diagnostics)
        z = self.garch.standardised_residuals(self.returns)
        z_mean = float(np.mean(z))
        z_std = float(np.std(z))
        z_skew = float(pd.Series(z).skew())
        z_kurt = float(pd.Series(z).kurtosis())

        return {
            "observations": len(self.r),
            "garch": garch_sum,
            "ewma": ewma_sum,
            "current_volatility": {
                "garch_daily": round(garch_current, 6),
                "garch_annual": round(garch_current * np.sqrt(252), 6),
                "ewma_daily": round(ewma_current, 6),
                "ewma_annual": round(ewma_current * np.sqrt(252), 6),
                "difference_pct": round(
                    (garch_current - ewma_current) / ewma_current * 100
                    if ewma_current > 0 else 0, 2
                ),
            },
            "forecast_5day": {
                "garch_vol": [round(float(v), 6) for v in garch_forecast],
                "mean_reversion_target": round(
                    self.garch.long_run_volatility, 6
                ),
            },
            "model_selection": {
                "aic_winner": aic_winner,
                "bic_winner": bic_winner,
                "garch_aic": round(garch_aic, 2),
                "ewma_aic": round(ewma_aic, 2),
                "garch_bic": round(garch_bic, 2),
                "ewma_bic": round(ewma_bic, 2),
                "interpretation": (
                    "GARCH(1,1)이 AIC/BIC 모두 우수 → 평균회귀 구조가 데이터에 적합"
                    if garch_aic < ewma_aic and garch_bic < ewma_bic
                    else "EWMA가 AIC/BIC 모두 우수 → 단순 모델이 충분"
                    if garch_aic > ewma_aic and garch_bic > ewma_bic
                    else "AIC와 BIC 결과가 다름 → 추가 분석 필요"
                ),
            },
            "diagnostics": {
                "residual_mean": round(z_mean, 4),
                "residual_std": round(z_std, 4),
                "residual_skewness": round(z_skew, 4),
                "residual_excess_kurtosis": round(z_kurt, 4),
                "interpretation": (
                    "잔차가 정규분포에 근접 (good fit)"
                    if abs(z_skew) < 0.5 and abs(z_kurt) < 2
                    else "잔차에 두꺼운 꼬리 존재 → Student-t GARCH 고려"
                    if z_kurt > 2
                    else "잔차에 비대칭성 존재 → GJR-GARCH 고려"
                ),
            },
            # Time series data for charting
            "vol_series": {
                "dates": (
                    self.returns.index.strftime("%Y-%m-%d").tolist()
                    if hasattr(self.returns.index, "strftime")
                    else list(range(len(self.returns)))
                ),
                "garch": [round(float(v), 6) for v in garch_vol_series.values],
                "ewma": [round(float(v), 6) for v in ewma_vol_series.values],
                "returns": [round(float(r), 6) for r in self.r],
            },
        }
