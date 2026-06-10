"""
FICC Portfolio Risk Aggregator
Combines VaR from multiple asset classes using correlation matrix.
Portfolio VaR = sqrt(V^T * C * V)
"""
import numpy as np


class FICCRiskAggregator:

    def aggregate_var(
        self, individual_vars: np.ndarray, correlation_matrix: np.ndarray
    ) -> float:
        """
        Diversified portfolio VaR via matrix multiplication.
        individual_vars: 1D array of per-asset VaR amounts
        correlation_matrix: NxN correlation matrix
        """
        var_sq = float(individual_vars @ correlation_matrix @ individual_vars)
        return float(np.sqrt(max(var_sq, 0)))

    def undiversified_var(self, individual_vars: np.ndarray) -> float:
        return float(np.sum(np.abs(individual_vars)))

    def diversification_benefit(
        self, individual_vars: np.ndarray, correlation_matrix: np.ndarray
    ) -> dict:
        undiv = self.undiversified_var(individual_vars)
        div   = self.aggregate_var(individual_vars, correlation_matrix)
        return {
            "undiversified_var": undiv,
            "diversified_var":   div,
            "benefit":           undiv - div,
            "benefit_pct":       round((undiv - div) / undiv * 100, 2) if undiv else 0,
        }
