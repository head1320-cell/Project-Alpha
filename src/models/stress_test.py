"""
Stress Testing Module
Historical scenario-based stress tests (FRM curriculum aligned).
"""


class StressTester:
    SCENARIOS = {
        "1987 블랙 먼데이":          {"equity": -0.22, "rates_bps": +150, "fx": +0.05},
        "1997 아시아 외환위기":       {"equity": -0.35, "rates_bps": +500, "fx": +0.30},
        "2000 닷컴 버블 붕괴":        {"equity": -0.40, "rates_bps": -100, "fx": -0.05},
        "2008 글로벌 금융위기":       {"equity": -0.50, "rates_bps": -200, "fx": +0.10},
        "2010 유럽 재정위기":         {"equity": -0.20, "rates_bps": +200, "fx": +0.08},
        "2020 코로나19 팬데믹":       {"equity": -0.34, "rates_bps": -150, "fx": +0.06},
        "Worst Case (Custom)":       {"equity": -0.60, "rates_bps": +300, "fx": +0.20},
    }

    def apply_scenarios(
        self,
        equity_value: float,
        bond_value: float,
        fx_value: float,
        portfolio_beta: float = 1.0,
        modified_duration: float = 7.0,
    ) -> dict:
        """
        Apply each scenario to a multi-asset portfolio and return stress P&L.
        """
        results = {}
        for name, shock in self.SCENARIOS.items():
            eq_loss = equity_value * shock["equity"] * portfolio_beta
            # Bond: Price ≈ -ModDur * ΔRate
            bond_loss = bond_value * (-modified_duration * shock["rates_bps"] / 10000)
            fx_loss = fx_value * shock["fx"]
            total_loss = eq_loss + bond_loss + fx_loss
            results[name] = {
                "equity_loss": round(eq_loss, 0),
                "bond_loss": round(bond_loss, 0),
                "fx_loss": round(fx_loss, 0),
                "total_loss": round(total_loss, 0),
            }
        return results

    def apply_single_asset(
        self,
        portfolio_value: float,
        portfolio_beta: float = 1.0,
    ) -> dict:
        """Simplified equity-only stress test."""
        results = {}
        for name, shock in self.SCENARIOS.items():
            loss = portfolio_value * shock["equity"] * portfolio_beta
            results[name] = round(loss, 0)
        return results
