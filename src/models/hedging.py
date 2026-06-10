"""
Hedging Simulator
- Equity futures beta hedge (KOSPI 200)
- Duration hedge for fixed income
- Delta hedge for options
"""


class HedgingSimulator:
    KOSPI200_MULTIPLIER = 250_000  # KRW per index point

    def __init__(self, futures_price: float, multiplier: int = None):
        self.futures_price = futures_price
        self.multiplier = multiplier or self.KOSPI200_MULTIPLIER
        self.contract_value = futures_price * self.multiplier

    def equity_futures_hedge(
        self,
        portfolio_value: float,
        current_beta: float,
        target_beta: float = 0.0,
    ) -> dict:
        """
        Number of futures contracts to sell to reach target beta.
        N = (β_target - β_portfolio) * V_P / (F * M)
        """
        beta_change  = target_beta - current_beta
        raw_contracts = (portfolio_value * beta_change) / self.contract_value
        contracts     = round(raw_contracts)  # positive = buy, negative = sell

        var_reduction = (abs(current_beta - target_beta) / current_beta * 100
                         if current_beta != 0 else 0)

        return {
            "current_beta":             current_beta,
            "target_beta":              target_beta,
            "contract_value":           round(self.contract_value, 0),
            "raw_contracts":            round(raw_contracts, 2),
            "contracts_to_trade":       contracts,
            "action":                   "매도 (Short)" if contracts < 0 else "매수 (Long)",
            "expected_var_reduction_pct": round(var_reduction, 1),
            "hedge_notional":           round(abs(contracts) * self.contract_value, 0),
        }

    def duration_hedge(
        self,
        bond_value: float,
        bond_duration: float,
        futures_duration: float,
        futures_price: float,
        multiplier: float = 1.0,
    ) -> dict:
        """
        Duration-based bond hedge.
        N = (D_target - D_portfolio) * V_P / (D_futures * F * M)
        """
        contracts = -(bond_duration * bond_value) / (futures_duration * futures_price * multiplier)
        contracts_rounded = round(contracts)
        return {
            "bond_duration":      bond_duration,
            "futures_duration":   futures_duration,
            "raw_contracts":      round(contracts, 2),
            "contracts_to_sell":  contracts_rounded,
        }

    def delta_hedge(self, option_delta: float, option_lots: int,
                    lot_size: int = 100) -> dict:
        """Number of shares needed to delta-hedge an option position."""
        shares = round(-option_delta * option_lots * lot_size)
        return {
            "option_delta":   option_delta,
            "option_lots":    option_lots,
            "shares_to_trade": shares,
            "action": "매수" if shares > 0 else "매도",
        }
