"""
PIT-Based VaR Backtesting Module
================================
Beyond exceedance-based backtesting: validates the ENTIRE forecasted distribution
using Probability Integral Transforms (PITs).

Reference: FRM Part II, Reading 7 (Iercosan et al., Chapter 4)
  - Kolmogorov-Smirnov (KS) test: max vertical distance between CDF and U[0,1]
  - Anderson-Darling (AD) test:   weighted tail-sensitive GoF test
  - Cramér-von Mises (CvM) test:  mean squared deviation from U[0,1]
  - Berkowitz independence test:   PIT → Φ⁻¹ → AR(1) log-likelihood ratio

Steps:
  1. Obtain rolling VaR distribution forecast (μ_t, σ_t) for each day t
  2. Observe actual P&L_t
  3. Compute PIT_t = Φ((P&L_t - μ_t) / σ_t)  — maps observation to U[0,1]
  4. Test PIT series for uniformity (KS/AD/CvM) and independence (Berkowitz)
"""

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import anderson, kstest, norm


class PITBacktester:
    """
    Probability Integral Transform backtester.

    Validates a VaR model by checking whether the full predicted distribution
    matches realized P&L — not just the tail exceedances.
    """

    def __init__(self, confidence_level: float = 0.99):
        self.cl = confidence_level

    # ─── Step 1-3: Compute PIT values ────────────────────────────────────────

    @staticmethod
    def compute_pit_values(
        actual_pnl: pd.Series,
        forecast_mu: pd.Series,
        forecast_sigma: pd.Series,
    ) -> np.ndarray:
        """
        Convert each (actual, μ, σ) triple into a PIT value via the normal CDF.

        PIT_t = Φ((PnL_t − μ_t) / σ_t)

        If the model perfectly forecasts the distribution, PIT values
        follow U[0,1] and are mutually independent.

        Parameters
        ----------
        actual_pnl : pd.Series
            Realised daily P&L (signed; negative = loss).
        forecast_mu : pd.Series
            Forecasted mean of P&L distribution for each day.
        forecast_sigma : pd.Series
            Forecasted std dev of P&L distribution for each day (must be > 0).

        Returns
        -------
        np.ndarray  PIT values in (0, 1), clipped to [1e-8, 1−1e-8].
        """
        z_scores = (actual_pnl.values - forecast_mu.values) / forecast_sigma.values
        pit_values = norm.cdf(z_scores)
        # Clip to avoid exact 0/1 which breaks log-transforms
        return np.clip(pit_values, 1e-8, 1.0 - 1e-8)

    @staticmethod
    def compute_pit_from_returns(
        returns: pd.Series,
        window: int = 60,
        use_ewma: bool = True,
        ewma_lambda: float = 0.94,
    ) -> np.ndarray:
        """
        Convenience: build rolling forecasts from raw return series,
        then compute PITs.

        Uses expanding/rolling mean + EWMA (or rolling) vol as the forecast.
        """
        mu = returns.rolling(window, min_periods=30).mean()
        if use_ewma:
            sigma = returns.ewm(alpha=1.0 - ewma_lambda, min_periods=30).std()
        else:
            sigma = returns.rolling(window, min_periods=30).std()

        # Align and drop NaNs
        valid = mu.notna() & sigma.notna() & (sigma > 0)
        mu_v = mu[valid]
        sigma_v = sigma[valid]
        ret_v = returns[valid]

        return PITBacktester.compute_pit_values(ret_v, mu_v, sigma_v)

    # ─── Step 4a: Kolmogorov-Smirnov Test ────────────────────────────────────

    @staticmethod
    def ks_test(pit_values: np.ndarray) -> dict:
        """
        KS test: max |F_empirical(x) − F_uniform(x)|.

        The KS statistic D converges to 0 for perfect forecasting.
        Lower D ⇒ better model.  p_value > 0.05 ⇒ cannot reject uniformity.
        """
        stat, p_value = kstest(pit_values, "uniform", args=(0, 1))
        rejected = bool(p_value <= 0.05)
        return {
            "test": "Kolmogorov-Smirnov",
            "statistic": round(float(stat), 6),
            "p_value": round(float(p_value), 6),
            "reject_uniformity": rejected,
            "interpretation": (
                "PIT 분포가 균일분포와 유의하게 다릅니다 → 모델 예측 분포가 부정확"
                if rejected
                else "PIT 분포가 균일분포에 부합합니다 → 예측 분포 적합"
            ),
        }

    # ─── Step 4b: Anderson-Darling Test ──────────────────────────────────────

    @staticmethod
    def ad_test(pit_values: np.ndarray) -> dict:
        """
        Anderson-Darling test: places HIGHER WEIGHT on tail observations,
        making it more sensitive to tail misspecification — the region
        risk managers care about most.

        AD² = −N − (1/N) Σ (2i−1)[ln F(x_i) + ln(1 − F(x_{N+1−i}))]

        Uses scipy's anderson() against the 'norm' distribution after
        transforming PITs → Φ⁻¹(PIT) to get standard normal variables.
        """
        # Transform U[0,1] → N(0,1) for scipy anderson which tests normality
        z_values = norm.ppf(pit_values)
        result = anderson(z_values, dist="norm")

        # Determine significance at 5% level
        # anderson returns critical values at [15%, 10%, 5%, 2.5%, 1%]
        sig_levels = result.significance_level  # [15, 10, 5, 2.5, 1]
        crit_vals = result.critical_values

        reject_5pct = bool(float(result.statistic) > float(crit_vals[2]))  # 5% level

        # Build a readable table of critical values
        critical_table = {
            f"{sl}%": round(float(cv), 4)
            for sl, cv in zip(sig_levels, crit_vals)
        }

        return {
            "test": "Anderson-Darling",
            "statistic": round(float(result.statistic), 6),
            "critical_values": critical_table,
            "reject_uniformity_5pct": reject_5pct,
            "interpretation": (
                "꼬리 영역에서 모델 예측이 부정확합니다 (AD 검정 기각)"
                if reject_5pct
                else "꼬리 영역 포함 전체 분포 예측이 적합합니다 (AD 검정 통과)"
            ),
        }

    # ─── Step 4c: Cramér-von Mises Test ──────────────────────────────────────

    @staticmethod
    def cvm_test(pit_values: np.ndarray) -> dict:
        """
        CvM test: mean squared deviation between empirical and theoretical CDF.

        W² = Σ [F_empirical(x_i) − F_uniform(x_i)]² + 1/(12N)

        Unlike KS (max deviation), CvM considers ALL deviations equally,
        providing a more global measure of fit.
        """
        result = stats.cramervonmises(pit_values, "uniform", args=(0, 1))
        rejected = bool(result.pvalue <= 0.05)
        return {
            "test": "Cramér-von Mises",
            "statistic": round(float(result.statistic), 6),
            "p_value": round(float(result.pvalue), 6),
            "reject_uniformity": rejected,
            "interpretation": (
                "예측 분포의 전반적 적합도가 부족합니다 (CvM 기각)"
                if rejected
                else "예측 분포가 전반적으로 적합합니다 (CvM 통과)"
            ),
        }

    # ─── Step 4d: Berkowitz Independence Test ────────────────────────────────

    @staticmethod
    def berkowitz_independence_test(pit_values: np.ndarray) -> dict:
        """
        Berkowitz (2001) independence test via PIT → Φ⁻¹ → AR(1).

        Transform PITs to standard normal variables, then fit AR(1):
            z_t = ρ * z_{t-1} + ε_t

        Test H₀: ρ = 0 (independence) via likelihood ratio.
        LR = -2 [LL(ρ=0) − LL(ρ_hat)] ~ χ²(1)
        """
        z = norm.ppf(pit_values)
        n = len(z)

        if n < 10:
            return {
                "test": "Berkowitz Independence",
                "statistic": None,
                "p_value": None,
                "independent": None,
                "rho_hat": None,
                "interpretation": "관측치 부족 (최소 10개 필요)",
            }

        # Estimate AR(1) coefficient
        z_lag = z[:-1]
        z_cur = z[1:]
        rho_hat = float(np.corrcoef(z_lag, z_cur)[0, 1])

        # Log-likelihoods
        # Under H₀ (ρ=0): z_t ~ N(0,1) iid
        ll_null = np.sum(norm.logpdf(z_cur, loc=0, scale=1))

        # Under H₁ (ρ=ρ̂): z_t | z_{t-1} ~ N(ρ̂ * z_{t-1}, √(1-ρ̂²))
        sigma_ar = np.sqrt(max(1.0 - rho_hat ** 2, 1e-10))
        ll_alt = np.sum(norm.logpdf(z_cur, loc=rho_hat * z_lag, scale=sigma_ar))

        lr_stat = -2.0 * (ll_null - ll_alt)
        lr_stat = max(lr_stat, 0.0)
        p_value = float(1.0 - stats.chi2.cdf(lr_stat, df=1))

        return {
            "test": "Berkowitz Independence",
            "statistic": round(float(lr_stat), 4),
            "p_value": round(p_value, 6),
            "independent": bool(p_value > 0.05),
            "rho_hat": round(rho_hat, 4),
            "interpretation": (
                f"PIT 값 간 자기상관 감지 (ρ̂={rho_hat:.3f}) → 예외 클러스터링 우려"
                if p_value <= 0.05
                else "PIT 값이 독립적입니다 → 예외 클러스터링 없음"
            ),
        }

    # ─── QQ Plot Data ────────────────────────────────────────────────────────

    @staticmethod
    def qq_plot_data(pit_values: np.ndarray, n_points: int = 100) -> dict:
        """
        Produce data for a QQ plot comparing empirical PIT CDF to U[0,1].

        Returns theoretical quantiles (straight line 0→1) and empirical quantiles.
        A perfect model yields points on the 45° line.
        """
        sorted_pits = np.sort(pit_values)
        n = len(sorted_pits)
        theoretical = (np.arange(1, n + 1) - 0.5) / n

        # Downsample for API response if too many points
        if n > n_points:
            idx = np.linspace(0, n - 1, n_points, dtype=int)
            sorted_pits = sorted_pits[idx]
            theoretical = theoretical[idx]

        return {
            "theoretical": np.round(theoretical, 6).tolist(),
            "empirical": np.round(sorted_pits, 6).tolist(),
        }

    @staticmethod
    def pit_histogram_data(pit_values: np.ndarray, bins: int = 10) -> dict:
        """
        Histogram of PITs for visual inspection.
        A perfect model gives ~equal bar heights (uniform distribution).
        """
        counts, edges = np.histogram(pit_values, bins=bins, range=(0.0, 1.0))
        expected = len(pit_values) / bins
        bin_labels = [
            f"{edges[i]:.1f}-{edges[i + 1]:.1f}" for i in range(len(counts))
        ]
        return {
            "bin_labels": bin_labels,
            "counts": counts.tolist(),
            "expected_count": round(expected, 1),
        }

    # ─── Comprehensive Report ────────────────────────────────────────────────

    def run_full_pit_backtest(
        self,
        returns: pd.Series,
        window: int = 60,
        use_ewma: bool = True,
        ewma_lambda: float = 0.94,
    ) -> dict:
        """
        Run the complete PIT-based backtesting suite:
          1. Compute PIT values from rolling forecasts
          2. KS test (overall distribution fit)
          3. AD test (tail-sensitive fit)
          4. CvM test (global mean-squared deviation)
          5. Berkowitz independence test
          6. QQ plot & histogram data for visualisation

        Returns a comprehensive report dict.
        """
        pit_values = self.compute_pit_from_returns(
            returns, window=window, use_ewma=use_ewma, ewma_lambda=ewma_lambda
        )

        if len(pit_values) < 30:
            return {"error": "PIT 계산에 충분한 데이터가 없습니다 (최소 30 관측치 필요)"}

        ks_result = self.ks_test(pit_values)
        ad_result = self.ad_test(pit_values)
        cvm_result = self.cvm_test(pit_values)
        berk_result = self.berkowitz_independence_test(pit_values)

        # Overall assessment
        tests_passed = sum([
            not ks_result["reject_uniformity"],
            not ad_result["reject_uniformity_5pct"],
            not cvm_result["reject_uniformity"],
            berk_result["independent"] if berk_result["independent"] is not None else True,
        ])

        if tests_passed == 4:
            overall = "PASS"
            overall_msg = "모든 PIT 검정 통과 — 예측 분포가 실현 분포와 잘 일치합니다"
        elif tests_passed >= 3:
            overall = "MARGINAL"
            overall_msg = "대부분의 검정 통과 — 일부 영역에서 모델 개선 여지 있음"
        elif tests_passed >= 2:
            overall = "WEAK"
            overall_msg = "다수 검정 기각 — 모델 재검토 필요"
        else:
            overall = "FAIL"
            overall_msg = "대부분의 검정 기각 — 모델 재구축 권고"

        return {
            "n_observations": int(len(pit_values)),
            "overall_result": overall,
            "overall_message": overall_msg,
            "tests_passed": tests_passed,
            "tests_total": 4,
            "kolmogorov_smirnov": ks_result,
            "anderson_darling": ad_result,
            "cramer_von_mises": cvm_result,
            "berkowitz_independence": berk_result,
            "qq_plot": self.qq_plot_data(pit_values),
            "histogram": self.pit_histogram_data(pit_values),
            "pit_values": np.round(pit_values, 6).tolist(),
        }
