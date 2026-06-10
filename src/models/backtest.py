"""
VaR Backtesting Module
- Kupiec POF (Proportion of Failures) Test
- Christoffersen Conditional Coverage Test
- Basel penalty zone classification
"""
import numpy as np
import pandas as pd
from scipy.stats import chi2


class VaRBacktester:
    def __init__(self, confidence_level: float = 0.99):
        self.cl = confidence_level
        self.p = 1 - confidence_level  # expected failure rate

    def run_kupiec_test(self, actual_pnl: pd.Series, var_series: pd.Series) -> dict:
        """
        Kupiec POF Test.
        actual_pnl: signed P&L (negative = loss)
        var_series: positive VaR amounts
        """
        exceptions = actual_pnl < -var_series.abs()
        N = int(exceptions.sum())
        T = len(actual_pnl)
        expected_N = round(T * self.p, 1)

        if N == 0:
            lr_pof = -2 * T * np.log(1 - self.p)
        else:
            p_hat = N / T
            lr_pof = -2 * (
                (T - N) * np.log(1 - self.p) + N * np.log(self.p)
            ) + 2 * (
                (T - N) * np.log(1 - p_hat) + N * np.log(p_hat)
            )

        p_value = float(1 - chi2.cdf(lr_pof, df=1))
        is_valid = p_value > 0.05

        return {
            "total_days": T,
            "exceptions": N,
            "expected_exceptions": expected_N,
            "failure_rate": round(N / T * 100, 2),
            "lr_pof": round(lr_pof, 4),
            "p_value": round(p_value, 4),
            "is_valid": is_valid,
            "exception_series": exceptions,
        }

    def basel_zone(self, exceptions: int, total_days: int = 250) -> dict:
        """Classify Basel penalty zone (green / yellow / red)."""
        if exceptions <= 4:
            zone, multiplier_add = "green", 0.0
        elif exceptions <= 9:
            add_map = {5: 0.40, 6: 0.50, 7: 0.65, 8: 0.75, 9: 0.85}
            zone, multiplier_add = "yellow", add_map.get(exceptions, 0.85)
        else:
            zone, multiplier_add = "red", 1.00
        return {
            "zone": zone,
            "capital_multiplier": 3.0 + multiplier_add,
            "multiplier_add": multiplier_add,
        }

    def christoffersen_test(self, actual_pnl: pd.Series, var_series: pd.Series) -> dict:
        """Independence test (clustering check)."""
        exc = (actual_pnl < -var_series.abs()).astype(int).values
        T01 = sum((exc[i] == 0 and exc[i + 1] == 1) for i in range(len(exc) - 1))
        T11 = sum((exc[i] == 1 and exc[i + 1] == 1) for i in range(len(exc) - 1))
        T00 = sum((exc[i] == 0 and exc[i + 1] == 0) for i in range(len(exc) - 1))
        T10 = sum((exc[i] == 1 and exc[i + 1] == 0) for i in range(len(exc) - 1))

        pi01 = T01 / (T00 + T01) if (T00 + T01) > 0 else 0
        pi11 = T11 / (T10 + T11) if (T10 + T11) > 0 else 0
        pi = (T01 + T11) / (T00 + T01 + T10 + T11)

        def safe_log(x):
            return np.log(x) if x > 0 else 0

        lr_ind = -2 * (
            (T00 + T10) * safe_log(1 - pi) + (T01 + T11) * safe_log(pi)
        ) + 2 * (
            T00 * safe_log(1 - pi01) + T01 * safe_log(pi01)
            + T10 * safe_log(1 - pi11) + T11 * safe_log(pi11)
        )
        p_ind = float(1 - chi2.cdf(lr_ind, df=1))
        return {"lr_ind": round(lr_ind, 4), "p_value_ind": round(p_ind, 4),
                "independent": p_ind > 0.05}
