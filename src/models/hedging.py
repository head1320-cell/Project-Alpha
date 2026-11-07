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

        # ★계약은 정수다★ (BL3 M5) — 감소율을 목표 β 가 아니라 **반올림 뒤 실제 β** 로 잰다. 예전에는 반올림해 0계약이어도
        # '100% 감소' 라 했고, β=0 이면 0 을 냈다. 이것은 β(시장 위험)의 감소율이다 — 종목 고유의 위험은 그대로다.
        beta_after = current_beta + contracts * self.contract_value / portfolio_value
        if current_beta != 0:
            reduction = round(abs(current_beta - beta_after) / abs(current_beta) * 100, 1)
            reason = None
        else:
            reduction = None
            reason = "지금 β 가 0 이라 줄일 시장 위험이 없어요 — 감소율을 계산하지 않아요."

        return {
            "current_beta":             current_beta,
            "target_beta":              target_beta,
            "contract_value":           round(self.contract_value, 0),
            "raw_contracts":            round(raw_contracts, 2),
            "contracts_to_trade":       contracts,
            "action":                   "매도 (Short)" if contracts < 0 else "매수 (Long)",
            "beta_after_rounding":      beta_after,
            "expected_var_reduction_pct": reduction,
            "reduction_basis":          "반올림한 계약 수로 실제 바뀌는 β 의 감소율(시장 위험만)",
            "reduction_reason":         reason,
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
