"""
Volatility Models
- EWMA (Exponentially Weighted Moving Average) - RiskMetrics standard
- Rolling standard deviation baseline
"""
import numpy as np
import pandas as pd


class EWMAVolatilityModel:
    def __init__(self, lambda_param: float = 0.94):
        """
        :param lambda_param: Decay factor. 0.94 is the RiskMetrics standard for daily data.
        """
        self.lam = lambda_param

    def variance_series(self, returns: pd.Series) -> np.ndarray:
        T = len(returns)
        var = np.zeros(T)
        var[0] = float(np.var(returns))
        for t in range(1, T):
            var[t] = self.lam * var[t - 1] + (1 - self.lam) * float(returns.iloc[t - 1]) ** 2
        return var

    def latest_volatility(self, returns: pd.Series) -> float:
        """Return the most recent forecasted daily volatility (std dev)."""
        return float(np.sqrt(self.variance_series(returns)[-1]))

    def volatility_series(self, returns: pd.Series) -> pd.Series:
        return pd.Series(np.sqrt(self.variance_series(returns)),
                         index=returns.index, name="ewma_vol")
