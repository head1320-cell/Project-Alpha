"""
Parametric VaR Models
- Normal (delta-normal) VaR
- Lognormal VaR
- EWMA-enhanced VaR
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

from src.models.volatility import EWMAVolatilityModel


class ParametricRiskModel:
    def __init__(self, confidence_level: float = 0.99, use_ewma: bool = False):
        self.cl = confidence_level
        self.use_ewma = use_ewma
        self.ewma = EWMAVolatilityModel()

    def calculate_var(self, returns: pd.Series) -> float:
        """Return VaR as a positive fraction (e.g., 0.025 means 2.5% loss)."""
        mu = float(np.mean(returns))
        sigma = (self.ewma.latest_volatility(returns) if self.use_ewma
                 else float(np.std(returns)))
        z = norm.ppf(self.cl)
        return max(z * sigma - mu, 0.0)

    def calculate_es(self, returns: pd.Series) -> float:
        """Expected Shortfall (CVaR) via numerical integration."""
        mu = float(np.mean(returns))
        sigma = (self.ewma.latest_volatility(returns) if self.use_ewma
                 else float(np.std(returns)))
        alpha = 1 - self.cl
        z_alpha = norm.ppf(alpha)
        es = -mu + sigma * norm.pdf(z_alpha) / alpha
        return max(es, 0.0)

    def historical_var(self, returns: pd.Series) -> float:
        """Non-parametric historical simulation VaR."""
        return float(-np.percentile(returns, (1 - self.cl) * 100))

    def lognormal_var(self, returns: pd.Series, portfolio_value: float) -> float:
        """Lognormal VaR based on geometric returns."""
        mu = float(np.mean(returns))
        sigma = float(np.std(returns))
        z = norm.ppf(self.cl)
        lognormal_var_pct = 1 - np.exp(mu - z * sigma)
        return max(lognormal_var_pct * portfolio_value, 0.0)
