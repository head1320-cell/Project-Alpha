"""
DCC-GARCH Dynamic Correlation & Wrong-Way Risk Engine
=====================================================
Time-varying correlations and counterparty risk dependency detection.

Reference: FRM Part II, Readings 8-9 (Correlation Risk), 38 (WWR)

DCC-GARCH(1,1) — Engle (2002):
  Step 1: Fit univariate GARCH(1,1) per asset → standardised residuals ε_t
  Step 2: Dynamic conditional correlation on ε_t:
    Q_t = (1 − a − b) · Q̄ + a · ε_{t-1} ε'_{t-1} + b · Q_{t-1}
    R_t = diag(Q_t)^{-½} · Q_t · diag(Q_t)^{-½}

Wrong-Way Risk (WWR):
  Positive correlation between exposure and counterparty default probability.
  WWR increases CVA; Right-Way Risk (RWR) decreases it.
  Detection: rolling correlation between portfolio MtM and CDS spreads.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import spearmanr

from src.models.garch import GARCH11

# ═══════════════════════════════════════════════════════════════════════════════
# 1. DCC-GARCH Model
# ═══════════════════════════════════════════════════════════════════════════════

class DCCGARCH:
    """
    Dynamic Conditional Correlation GARCH(1,1).

    Two-step estimation:
      1. Fit univariate GARCH(1,1) to each series → standardised residuals
      2. Estimate DCC parameters (a, b) for time-varying correlation

    Q_t = (1 − a − b) · Q̄ + a · ε_{t-1}·ε'_{t-1} + b · Q_{t-1}
    R_t = diag(Q_t)^{-½} · Q_t · diag(Q_t)^{-½}

    Constraints: a ≥ 0, b ≥ 0, a + b < 1
    """

    def __init__(self):
        self.garch_models: list[GARCH11] = []
        self.a: float = 0.0
        self.b: float = 0.0
        self.Q_bar: np.ndarray | None = None
        self._fitted = False
        self._std_residuals: np.ndarray | None = None
        self._n_assets: int = 0
        self._tickers: list[str] = []

    # ─── Step 1: Univariate GARCH ────────────────────────────────────────────

    def _fit_univariate(self, returns_df: pd.DataFrame) -> np.ndarray:
        """Fit GARCH(1,1) to each column and return standardised residuals."""
        self._n_assets = returns_df.shape[1]
        self._tickers = list(returns_df.columns)
        T = returns_df.shape[0]

        std_resid = np.zeros((T, self._n_assets))
        self.garch_models = []

        for i in range(self._n_assets):
            model = GARCH11().fit(returns_df.iloc[:, i])
            self.garch_models.append(model)

            sigma2 = model.variance_series(returns_df.iloc[:, i].values)
            sigma = np.sqrt(np.maximum(sigma2, 1e-12))
            std_resid[:, i] = returns_df.iloc[:, i].values / sigma

        self._std_residuals = std_resid
        return std_resid

    # ─── Step 2: DCC Estimation ──────────────────────────────────────────────

    def _dcc_neg_loglik(self, params: np.ndarray, eps: np.ndarray) -> float:
        """
        Negative log-likelihood for DCC parameters.

        Q_t = (1-a-b)·Q̄ + a·ε_{t-1}·ε'_{t-1} + b·Q_{t-1}
        R_t = diag(Q_t)^{-½} · Q_t · diag(Q_t)^{-½}

        LL_DCC = -½ Σ [ln|R_t| + ε'_t · R_t⁻¹ · ε_t − ε'_t · ε_t]
        """
        a, b = params
        if a < 0 or b < 0 or a + b >= 0.9999:
            return 1e10

        T, n = eps.shape
        Q_bar = (eps.T @ eps) / T
        Q_t = Q_bar.copy()

        ll = 0.0
        for t in range(1, T):
            Q_t = (1 - a - b) * Q_bar + a * np.outer(eps[t-1], eps[t-1]) + b * Q_t

            # Normalise to correlation
            d = np.sqrt(np.diag(Q_t))
            d = np.maximum(d, 1e-8)
            D_inv = np.diag(1.0 / d)
            R_t = D_inv @ Q_t @ D_inv
            np.fill_diagonal(R_t, 1.0)

            # Log-likelihood contribution
            try:
                sign, logdet = np.linalg.slogdet(R_t)
                if sign <= 0:
                    return 1e10
                R_inv = np.linalg.inv(R_t)
                e = eps[t]
                ll += -0.5 * (logdet + e @ R_inv @ e - e @ e)
            except np.linalg.LinAlgError:
                return 1e10

        return -ll

    def fit(self, returns_df: pd.DataFrame) -> "DCCGARCH":
        """
        Fit the DCC-GARCH model in two steps.

        Parameters
        ----------
        returns_df : pd.DataFrame
            Daily returns with one column per asset.
        """
        # Step 1
        eps = self._fit_univariate(returns_df)

        # Q̄ = unconditional correlation of standardised residuals
        self.Q_bar = (eps.T @ eps) / eps.shape[0]

        # Step 2: optimise DCC parameters
        starts = [
            np.array([0.02, 0.95]),
            np.array([0.05, 0.90]),
            np.array([0.01, 0.97]),
        ]
        bounds = [(1e-6, 0.3), (0.5, 0.999)]
        constraints = [{"type": "ineq", "fun": lambda p: 0.9999 - p[0] - p[1]}]

        best_result = None
        best_nll = np.inf

        for x0 in starts:
            try:
                result = minimize(
                    self._dcc_neg_loglik, x0, args=(eps,),
                    method="SLSQP", bounds=bounds, constraints=constraints,
                    options={"maxiter": 300, "ftol": 1e-10},
                )
                if result.fun < best_nll:
                    best_nll = result.fun
                    best_result = result
            except Exception:
                continue

        if best_result is not None and best_result.success:
            self.a = float(best_result.x[0])
            self.b = float(best_result.x[1])
        else:
            self.a = 0.02
            self.b = 0.95

        self._fitted = True
        return self

    # ─── Dynamic Correlation Series ──────────────────────────────────────────

    def dynamic_correlation_series(self) -> list[np.ndarray]:
        """
        Compute the full time series of conditional correlation matrices R_t.

        Returns list of (n×n) correlation matrices, one per time step.
        """
        if not self._fitted:
            raise ValueError("Model not fitted. Call fit() first.")

        eps = self._std_residuals
        T, n = eps.shape
        a, b = self.a, self.b
        Q_t = self.Q_bar.copy()

        R_series = []
        for t in range(T):
            if t > 0:
                Q_t = (1 - a - b) * self.Q_bar + a * np.outer(eps[t-1], eps[t-1]) + b * Q_t

            d = np.sqrt(np.maximum(np.diag(Q_t), 1e-12))
            D_inv = np.diag(1.0 / d)
            R_t = D_inv @ Q_t @ D_inv
            np.fill_diagonal(R_t, 1.0)
            # Clip to valid correlation range
            R_t = np.clip(R_t, -1.0, 1.0)
            R_series.append(R_t)

        return R_series

    def pairwise_correlation_series(self, i: int = 0, j: int = 1) -> np.ndarray:
        """Extract the (i,j) dynamic correlation over time."""
        R_series = self.dynamic_correlation_series()
        return np.array([R[i, j] for R in R_series])

    # ─── Correlation Statistics ──────────────────────────────────────────────

    def correlation_stats(self) -> dict:
        """Summary statistics of the dynamic correlation structure."""
        R_series = self.dynamic_correlation_series()
        n = self._n_assets

        pair_stats = {}
        for i in range(n):
            for j in range(i+1, n):
                rho = np.array([R[i, j] for R in R_series])
                pair_stats[f"{self._tickers[i]}_vs_{self._tickers[j]}"] = {
                    "mean": round(float(np.mean(rho)), 4),
                    "std": round(float(np.std(rho)), 4),
                    "min": round(float(np.min(rho)), 4),
                    "max": round(float(np.max(rho)), 4),
                    "current": round(float(rho[-1]), 4),
                    "mean_reversion_target": round(float(self.Q_bar[i, j] /
                        np.sqrt(self.Q_bar[i, i] * self.Q_bar[j, j])), 4)
                        if self.Q_bar[i, i] > 0 and self.Q_bar[j, j] > 0 else 0,
                }

        return pair_stats

    # ─── Summary ─────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Full model summary."""
        garch_params = []
        for i, m in enumerate(self.garch_models):
            garch_params.append({
                "ticker": self._tickers[i],
                "alpha": round(m.alpha, 4),
                "beta": round(m.beta, 4),
                "persistence": round(m.persistence, 4),
                "long_run_vol_annual": round(m.long_run_volatility * np.sqrt(252), 4),
            })

        return {
            "model": "DCC-GARCH(1,1)",
            "n_assets": self._n_assets,
            "tickers": self._tickers,
            "dcc_a": round(self.a, 6),
            "dcc_b": round(self.b, 6),
            "dcc_persistence": round(self.a + self.b, 6),
            "garch_params": garch_params,
            "correlation_stats": self.correlation_stats(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Wrong-Way Risk Detection
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WWRResult:
    """Wrong-Way Risk assessment result."""
    pair_name: str
    correlation: float
    p_value: float
    risk_type: str          # "WWR", "RWR", or "NEUTRAL"
    severity: str           # "HIGH", "MODERATE", "LOW"
    description: str


class WrongWayRiskDetector:
    """
    Detect Wrong-Way Risk (WWR) and Right-Way Risk (RWR).

    WWR: positive correlation between exposure and default probability
         → counterparty more likely to default when exposure is high
    RWR: negative correlation → counterparty defaults when exposure is low

    Methods:
      1. Static: Pearson/Spearman correlation between MtM and CDS spreads
      2. Dynamic: rolling correlation via DCC-GARCH or windowed estimation
      3. Regime-based: correlation conditional on stress vs normal periods
    """

    WWR_THRESHOLD = 0.15
    HIGH_WWR_THRESHOLD = 0.40

    # ─── Static WWR Detection ────────────────────────────────────────────────

    @staticmethod
    def detect_static_wwr(
        exposure_series: pd.Series,
        credit_spread_series: pd.Series,
    ) -> WWRResult:
        """
        Test for WWR using Spearman rank correlation between
        portfolio exposure and counterparty CDS spread.

        Positive correlation → WWR (exposure rises when credit deteriorates)
        Negative correlation → RWR
        """
        aligned = pd.concat([exposure_series, credit_spread_series], axis=1).dropna()
        if len(aligned) < 20:
            return WWRResult("N/A", 0.0, 1.0, "NEUTRAL", "LOW",
                             "데이터 부족 (최소 20 관측치 필요)")

        rho, p_val = spearmanr(aligned.iloc[:, 0], aligned.iloc[:, 1])

        if rho > WrongWayRiskDetector.HIGH_WWR_THRESHOLD:
            risk_type, severity = "WWR", "HIGH"
            desc = f"강한 Wrong-Way Risk (ρ={rho:.3f}): 노출과 부도확률이 강하게 동행"
        elif rho > WrongWayRiskDetector.WWR_THRESHOLD:
            risk_type, severity = "WWR", "MODERATE"
            desc = f"보통 수준 Wrong-Way Risk (ρ={rho:.3f}): 노출↑ 시 신용악화 경향"
        elif rho < -WrongWayRiskDetector.HIGH_WWR_THRESHOLD:
            risk_type, severity = "RWR", "HIGH"
            desc = f"강한 Right-Way Risk (ρ={rho:.3f}): 노출↑ 시 신용개선 경향 (유리)"
        elif rho < -WrongWayRiskDetector.WWR_THRESHOLD:
            risk_type, severity = "RWR", "MODERATE"
            desc = f"보통 수준 Right-Way Risk (ρ={rho:.3f})"
        else:
            risk_type, severity = "NEUTRAL", "LOW"
            desc = f"유의한 방향성 없음 (ρ={rho:.3f}): 독립 가정 적절"

        return WWRResult(
            pair_name=f"{exposure_series.name}_vs_{credit_spread_series.name}",
            correlation=round(float(rho), 4),
            p_value=round(float(p_val), 6),
            risk_type=risk_type,
            severity=severity,
            description=desc,
        )

    # ─── Rolling WWR Detection ───────────────────────────────────────────────

    @staticmethod
    def rolling_wwr(
        exposure_series: pd.Series,
        credit_spread_series: pd.Series,
        window: int = 60,
    ) -> dict:
        """
        Time-varying WWR detection via rolling Spearman correlation.

        Returns:
          - Rolling correlation series
          - WWR episodes (periods where ρ > threshold)
          - Regime classification
        """
        aligned = pd.concat([exposure_series, credit_spread_series], axis=1).dropna()
        if len(aligned) < window + 10:
            return {"error": "데이터 부족"}

        exp = aligned.iloc[:, 0]
        cds = aligned.iloc[:, 1]

        rolling_rho = []
        dates = []
        for i in range(window, len(aligned)):
            rho, _ = spearmanr(exp.iloc[i-window:i], cds.iloc[i-window:i])
            rolling_rho.append(float(rho))
            dates.append(str(aligned.index[i]) if hasattr(aligned.index, "strftime") else i)

        rolling_rho = np.array(rolling_rho)

        # Classify episodes
        wwr_episodes = int(np.sum(rolling_rho > WrongWayRiskDetector.WWR_THRESHOLD))
        rwr_episodes = int(np.sum(rolling_rho < -WrongWayRiskDetector.WWR_THRESHOLD))
        total = len(rolling_rho)

        # Current regime
        current_rho = rolling_rho[-1] if len(rolling_rho) > 0 else 0
        if current_rho > WrongWayRiskDetector.HIGH_WWR_THRESHOLD:
            current_regime = "HIGH_WWR"
        elif current_rho > WrongWayRiskDetector.WWR_THRESHOLD:
            current_regime = "MODERATE_WWR"
        elif current_rho < -WrongWayRiskDetector.WWR_THRESHOLD:
            current_regime = "RWR"
        else:
            current_regime = "NEUTRAL"

        return {
            "window": window,
            "n_observations": total,
            "current_correlation": round(float(current_rho), 4),
            "current_regime": current_regime,
            "mean_correlation": round(float(np.mean(rolling_rho)), 4),
            "max_correlation": round(float(np.max(rolling_rho)), 4),
            "min_correlation": round(float(np.min(rolling_rho)), 4),
            "wwr_episodes_pct": round(wwr_episodes / total * 100, 1) if total > 0 else 0,
            "rwr_episodes_pct": round(rwr_episodes / total * 100, 1) if total > 0 else 0,
            "rolling_correlation": [round(float(r), 4) for r in rolling_rho],
            "dates": dates,
        }

    # ─── WWR-Adjusted CVA ────────────────────────────────────────────────────

    @staticmethod
    def wwr_adjusted_cva(
        base_cva: float,
        wwr_correlation: float,
        alpha: float = 1.4,
    ) -> dict:
        """
        Adjust CVA for Wrong-Way Risk.

        CVA_wwr = CVA_base × (1 + α × ρ_wwr)

        where α is the WWR sensitivity parameter (typically 1.0-2.0)
        and ρ_wwr is the exposure-default correlation.

        Positive ρ → CVA increases (WWR)
        Negative ρ → CVA decreases (RWR)
        """
        adjustment = 1.0 + alpha * wwr_correlation
        adjustment = max(adjustment, 0.1)  # floor at 10% of base CVA
        adjusted_cva = base_cva * adjustment

        return {
            "base_cva": round(base_cva, 0),
            "wwr_correlation": round(wwr_correlation, 4),
            "alpha_sensitivity": alpha,
            "adjustment_factor": round(adjustment, 4),
            "adjusted_cva": round(adjusted_cva, 0),
            "cva_change_pct": round((adjustment - 1.0) * 100, 2),
        }

    # ─── Transaction-Specific WWR Analysis ───────────────────────────────────

    @staticmethod
    def classify_transaction_wwr(transaction_type: str) -> dict:
        """
        FRM-aligned WWR classification by transaction type.

        Per Reading 38: different derivatives have inherent WWR/RWR tendencies.
        """
        classifications = {
            "put_option": {
                "inherent_risk": "WWR",
                "explanation": "풋옵션: 기초자산 하락 시 페이오프 증가 + 상대방 부도확률 증가 → WWR",
                "severity": "HIGH",
                "mitigation": "담보 요구, 초과담보, CCP 청산",
            },
            "call_option": {
                "inherent_risk": "RWR",
                "explanation": "콜옵션: 기초자산 상승 시 페이오프 증가 + 상대방 건전성 개선 → RWR",
                "severity": "LOW",
                "mitigation": "일반적으로 우호적 상관관계",
            },
            "fx_forward": {
                "inherent_risk": "WWR",
                "explanation": "FX 선도: 상대방 통화 평가절하 시 노출 증가 + 부도 가능성 증가 → WWR",
                "severity": "MODERATE",
                "mitigation": "통화 담보, 양방향 CSA",
            },
            "cds_protection": {
                "inherent_risk": "WWR",
                "explanation": "CDS 매수: 참조자산과 보장매도자 상관 시 → 양자 동시 부도 위험",
                "severity": "HIGH",
                "mitigation": "보장매도자 분산, 카운터파티 리미트",
            },
            "interest_rate_swap": {
                "inherent_risk": "MODERATE_WWR",
                "explanation": "IRS: 금리 급등 시 고정 수취 포지션 이익 + 상대방 채무부담 증가 → 잠재적 WWR",
                "severity": "MODERATE",
                "mitigation": "변동마진, 일일정산",
            },
            "equity_swap": {
                "inherent_risk": "WWR",
                "explanation": "주식 스왑: 시장 하락 시 노출 변화 + 금융기관 건전성 악화 → 시스템적 WWR",
                "severity": "MODERATE",
                "mitigation": "CCP 청산, 초기 증거금",
            },
        }

        return classifications.get(
            transaction_type,
            {"inherent_risk": "UNKNOWN", "explanation": "분류 불가", "severity": "UNKNOWN", "mitigation": ""}
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Integrated Report
# ═══════════════════════════════════════════════════════════════════════════════

def dcc_garch_full_report(
    returns_df: pd.DataFrame,
    exposure_series: pd.Series | None = None,
    credit_spread_series: pd.Series | None = None,
) -> dict:
    """
    Full DCC-GARCH + WWR analysis report.

    1. Fit DCC-GARCH to multi-asset returns
    2. Extract dynamic correlation time series
    3. If exposure and CDS data provided, detect WWR
    """
    # 1. DCC-GARCH
    dcc = DCCGARCH()
    dcc.fit(returns_df)
    summary = dcc.summary()

    # Pairwise correlation series for charting
    n = returns_df.shape[1]
    tickers = list(returns_df.columns)
    corr_series = {}
    for i in range(n):
        for j in range(i+1, n):
            key = f"{tickers[i]}_vs_{tickers[j]}"
            rho_t = dcc.pairwise_correlation_series(i, j)
            corr_series[key] = [round(float(r), 4) for r in rho_t]

    dates = (
        returns_df.index.strftime("%Y-%m-%d").tolist()
        if hasattr(returns_df.index, "strftime")
        else list(range(len(returns_df)))
    )

    # Static correlation for comparison
    static_corr = returns_df.corr()

    result = {
        "dcc_garch": summary,
        "dynamic_correlations": corr_series,
        "static_correlation": {
            tickers[i]: {
                tickers[j]: round(float(static_corr.iloc[i, j]), 4)
                for j in range(n)
            } for i in range(n)
        },
        "dates": dates,
        "n_observations": len(returns_df),
    }

    # 2. WWR if data provided
    if exposure_series is not None and credit_spread_series is not None:
        detector = WrongWayRiskDetector()
        static_wwr = detector.detect_static_wwr(exposure_series, credit_spread_series)
        rolling_wwr = detector.rolling_wwr(exposure_series, credit_spread_series)

        result["wrong_way_risk"] = {
            "static": {
                "correlation": static_wwr.correlation,
                "p_value": static_wwr.p_value,
                "risk_type": static_wwr.risk_type,
                "severity": static_wwr.severity,
                "description": static_wwr.description,
            },
            "rolling": rolling_wwr,
        }

    return result
