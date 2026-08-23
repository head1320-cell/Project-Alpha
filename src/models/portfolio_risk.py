"""
Portfolio-level VaR using variance-covariance (delta-normal) method.
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

from src.models.volatility import EWMAVolatilityModel


class PortfolioRiskModel:
    def __init__(self, confidence_level: float = 0.99, use_ewma: bool = False):
        self.cl = confidence_level
        self.use_ewma = use_ewma
        self.ewma = EWMAVolatilityModel()

    def calculate_portfolio_var(
        self,
        returns_df: pd.DataFrame,
        weights: np.ndarray,
        portfolio_value: float,
        holding_period: int = 1,
    ):
        """
        Variance-covariance portfolio VaR.
        Returns (var_amount, portfolio_vol).
        """
        if self.use_ewma:
            sigmas = np.array([self.ewma.latest_volatility(returns_df[c])
                                for c in returns_df.columns])
            corr = returns_df.corr().values
            cov = np.outer(sigmas, sigmas) * corr
        else:
            cov = returns_df.cov().values

        port_var_daily = float(weights @ cov @ weights)
        port_vol = np.sqrt(port_var_daily) * np.sqrt(holding_period)
        z = norm.ppf(self.cl)
        var_pct = z * port_vol
        var_amount = var_pct * portfolio_value
        return float(var_amount), float(port_vol)

    def marginal_var(self, returns_df: pd.DataFrame, weights: np.ndarray,
                     portfolio_value: float):
        """Marginal VaR for each asset."""
        cov = returns_df.cov().values
        port_var = float(weights @ cov @ weights)
        port_vol = np.sqrt(port_var)
        z = norm.ppf(self.cl)
        marginal = (cov @ weights) / port_vol * z * portfolio_value
        return marginal

    def component_var(self, returns_df: pd.DataFrame, weights: np.ndarray,
                      portfolio_value: float):
        """Component VaR = weight * marginal VaR."""
        mvars = self.marginal_var(returns_df, weights, portfolio_value)
        return weights * mvars
