"""
VaR Mapping Engine
==================
Maps complex instruments onto primitive risk factors for VaR calculation.

Reference: FRM Part II, Reading 5 — VaR Mapping (Jorion Ch. 11)

Fixed-Income Mapping Methods:
  1. Principal Mapping — simplest; uses only principal cash flow at average life
  2. Duration Mapping — replaces portfolio with zero of matching duration
  3. Cash Flow Mapping — most precise; decomposes into all zero cash flows

Derivatives Mapping:
  - Forward contracts → short T-bill + long foreign bill + long spot FX
  - FRAs → short short-dated zero + long long-dated zero
  - Interest rate swaps → long floating bond + short fixed bond
  - Options → delta × underlying (delta-normal)

Portfolio VaR formulas:
  Undiversified VaR = Σ |x_i| × VaR_i
  Diversified VaR   = √(x' × V × R × V' × x)
    where x = PV cash flow vector, V = diagonal VaR matrix, R = correlation matrix
"""

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Data Structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Bond:
    """Fixed-income position for VaR mapping."""
    name: str
    face_value: float
    coupon_rate: float       # annual, decimal
    maturity_years: int
    ytm: float = 0.0         # if 0, assume priced at par (ytm = coupon)
    frequency: int = 1       # annual coupons

    def cash_flows(self) -> list[tuple[int, float]]:
        """Return list of (year, cash flow) tuples."""
        cfs = []
        coupon = self.face_value * self.coupon_rate
        for t in range(1, self.maturity_years + 1):
            cf = coupon + (self.face_value if t == self.maturity_years else 0)
            cfs.append((t, cf))
        return cfs

    def present_value_cash_flows(self, spot_rates: dict[int, float]) -> list[tuple[int, float]]:
        """PV each cash flow using maturity-specific spot rates."""
        pv_cfs = []
        for t, cf in self.cash_flows():
            r = spot_rates.get(t, self.ytm or self.coupon_rate)
            pv = cf / ((1 + r) ** t)
            pv_cfs.append((t, pv))
        return pv_cfs

    def macaulay_duration(self, spot_rates: dict[int, float]) -> float:
        """Macaulay duration = Σ(t × PV(CF)) / Σ(PV(CF))"""
        pv_cfs = self.present_value_cash_flows(spot_rates)
        numerator = sum(t * pv for t, pv in pv_cfs)
        denominator = sum(pv for _, pv in pv_cfs)
        return numerator / denominator if denominator > 0 else 0

    def market_value(self, spot_rates: dict[int, float]) -> float:
        """Current market value = Σ PV(CF)."""
        return sum(pv for _, pv in self.present_value_cash_flows(spot_rates))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. VaR Mapping Engine
# ═══════════════════════════════════════════════════════════════════════════════

class VaRMappingEngine:
    """
    Maps bond portfolios onto zero-coupon risk factors and computes VaR.

    Expects:
      - zero_var_pct: dict[int, float] — VaR % for each zero maturity
        e.g. {1: 0.4696, 2: 0.9868, 3: 1.4841, 4: 1.9946, 5: 2.5117}
      - zero_correlation: np.ndarray — correlation between zero returns
    """

    def __init__(
        self,
        zero_var_pct: dict[int, float],
        zero_correlation: np.ndarray | None = None,
        spot_rates: dict[int, float] | None = None,
    ):
        self.zero_var_pct = zero_var_pct   # percentage (e.g. 1.4841 means 1.48%)
        self.maturities = sorted(zero_var_pct.keys())

        if zero_correlation is None:
            # Default: decay correlation structure
            n = len(self.maturities)
            self.correlation = np.zeros((n, n))
            for i in range(n):
                for j in range(n):
                    dist = abs(i - j)
                    self.correlation[i, j] = 0.999 ** dist if dist > 0 else 1.0
        else:
            self.correlation = zero_correlation

        self.spot_rates = spot_rates or {t: 0.03 + 0.002 * t for t in self.maturities}

    # ─── Method 1: Principal Mapping ─────────────────────────────────────────

    def principal_mapping(self, bonds: list[Bond]) -> dict:
        """
        Principal Mapping — simplest method.

        Considers only principal (maturity) cash flows at the portfolio's
        average life (weighted by face value).

        VaR = Total MV × VaR%(avg_life)
        """
        total_face = sum(b.face_value for b in bonds)
        weighted_life = sum(b.face_value * b.maturity_years for b in bonds) / total_face

        # Interpolate VaR% at the weighted life
        var_pct = self._interpolate_var_pct(weighted_life)

        # Market value
        total_mv = sum(b.market_value(self.spot_rates) for b in bonds)

        var_amount = total_mv * var_pct / 100

        return {
            "method": "Principal Mapping",
            "description": "원금 상환만 고려 (가장 단순)",
            "weighted_average_life": round(weighted_life, 4),
            "interpolated_var_pct": round(var_pct, 4),
            "total_market_value": round(total_mv, 2),
            "total_face_value": round(total_face, 2),
            "var_amount": round(var_amount, 2),
            "var_pct_of_mv": round(var_amount / total_mv * 100, 4) if total_mv > 0 else 0,
        }

    # ─── Method 2: Duration Mapping ──────────────────────────────────────────

    def duration_mapping(self, bonds: list[Bond]) -> dict:
        """
        Duration Mapping — medium complexity.

        Replaces portfolio with a single zero-coupon bond whose maturity
        equals the portfolio's Macaulay duration.

        VaR = Total MV × VaR%(duration)
        """
        # Portfolio duration = market-value-weighted average of bond durations
        total_mv = 0.0
        mv_weighted_duration = 0.0
        bond_details = []

        for b in bonds:
            mv = b.market_value(self.spot_rates)
            dur = b.macaulay_duration(self.spot_rates)
            total_mv += mv
            mv_weighted_duration += mv * dur
            bond_details.append({
                "name": b.name,
                "market_value": round(mv, 2),
                "duration": round(dur, 4),
            })

        portfolio_duration = mv_weighted_duration / total_mv if total_mv > 0 else 0

        # Interpolate VaR% at the portfolio duration
        var_pct = self._interpolate_var_pct(portfolio_duration)
        var_amount = total_mv * var_pct / 100

        return {
            "method": "Duration Mapping",
            "description": "듀레이션과 동일한 만기의 제로쿠폰으로 대체",
            "portfolio_duration": round(portfolio_duration, 4),
            "interpolated_var_pct": round(var_pct, 4),
            "total_market_value": round(total_mv, 2),
            "var_amount": round(var_amount, 2),
            "var_pct_of_mv": round(var_amount / total_mv * 100, 4) if total_mv > 0 else 0,
            "bond_details": bond_details,
        }

    # ─── Method 3: Cash Flow Mapping ─────────────────────────────────────────

    def cash_flow_mapping(self, bonds: list[Bond]) -> dict:
        """
        Cash Flow Mapping — most precise method.

        Decomposes each bond into its individual cash flows, maps the PV
        of each cash flow to the zero of matching maturity.

        Undiversified VaR = Σ |x_i| × VaR_i   (assumes perfect correlation)
        Diversified VaR   = √(x' × V × R × V' × x)   (matrix form)

        where x = PV cash flow vector, V = diagonal VaR vector,
        R = inter-maturity correlation matrix.
        """
        # Aggregate PV cash flows by maturity
        pv_by_maturity: dict[int, float] = {t: 0.0 for t in self.maturities}

        for b in bonds:
            for t, pv in b.present_value_cash_flows(self.spot_rates):
                if t in pv_by_maturity:
                    pv_by_maturity[t] += pv

        # Build vectors
        x = np.array([pv_by_maturity[t] for t in self.maturities])  # PV CF
        v = np.array([self.zero_var_pct[t] / 100 for t in self.maturities])  # VaR %

        # Individual VaRs (in amount)
        individual_vars = x * v

        # Undiversified VaR (perfect correlation assumption)
        undiversified = float(np.sum(np.abs(individual_vars)))

        # Diversified VaR via matrix algebra
        # VaR_div = √(v_abs' × R × v_abs) where v_abs = |x_i| × v_i
        v_abs = np.abs(individual_vars)
        diversified_sq = float(v_abs @ self.correlation @ v_abs)
        diversified = float(np.sqrt(max(diversified_sq, 0)))

        # Cash flow breakdown
        cf_detail = []
        for i, t in enumerate(self.maturities):
            cf_detail.append({
                "maturity_years": t,
                "pv_cash_flow": round(float(x[i]), 2),
                "zero_var_pct": self.zero_var_pct[t],
                "individual_var": round(float(individual_vars[i]), 4),
            })

        total_mv = float(np.sum(x))

        return {
            "method": "Cash Flow Mapping",
            "description": "모든 현금흐름을 제로 만기별로 분해 (가장 정밀)",
            "undiversified_var": round(undiversified, 4),
            "diversified_var": round(diversified, 4),
            "diversification_benefit": round(undiversified - diversified, 4),
            "diversification_benefit_pct": round(
                (undiversified - diversified) / undiversified * 100, 2
            ) if undiversified > 0 else 0,
            "total_market_value": round(total_mv, 2),
            "cash_flow_breakdown": cf_detail,
            "var_pct_of_mv_diversified": round(
                diversified / total_mv * 100, 4
            ) if total_mv > 0 else 0,
        }

    # ─── Compare All Three Methods ───────────────────────────────────────────

    def compare_methods(self, bonds: list[Bond]) -> dict:
        """Run all three methods and summarize."""
        principal = self.principal_mapping(bonds)
        duration = self.duration_mapping(bonds)
        cash_flow = self.cash_flow_mapping(bonds)

        # Extract VaR amounts
        p_var = principal["var_amount"]
        d_var = duration["var_amount"]
        cf_undiv = cash_flow["undiversified_var"]
        cf_div = cash_flow["diversified_var"]

        return {
            "principal_mapping": principal,
            "duration_mapping": duration,
            "cash_flow_mapping": cash_flow,
            "summary": {
                "principal_var": p_var,
                "duration_var": d_var,
                "cash_flow_undiversified_var": cf_undiv,
                "cash_flow_diversified_var": cf_div,
                "most_conservative": max(p_var, d_var, cf_undiv),
                "most_precise": cf_div,
                "method_ranking_by_precision": [
                    "Cash Flow Mapping (diversified)",
                    "Duration Mapping",
                    "Principal Mapping",
                ],
            },
        }

    # ─── Utility: Interpolate VaR% ───────────────────────────────────────────

    def _interpolate_var_pct(self, target_maturity: float) -> float:
        """Linear interpolation of VaR% at a non-integer maturity."""
        if target_maturity <= self.maturities[0]:
            return self.zero_var_pct[self.maturities[0]]
        if target_maturity >= self.maturities[-1]:
            return self.zero_var_pct[self.maturities[-1]]

        # Find bracketing maturities
        lo, hi = self.maturities[0], self.maturities[-1]
        for i in range(len(self.maturities) - 1):
            if self.maturities[i] <= target_maturity <= self.maturities[i+1]:
                lo, hi = self.maturities[i], self.maturities[i+1]
                break

        var_lo = self.zero_var_pct[lo]
        var_hi = self.zero_var_pct[hi]
        weight = (target_maturity - lo) / (hi - lo) if hi > lo else 0
        return var_lo + weight * (var_hi - var_lo)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Derivatives Mapping (Delta-Normal)
# ═══════════════════════════════════════════════════════════════════════════════

class DerivativesMapper:
    """
    Delta-normal mapping for linear derivatives.

    Decomposes instruments into primitive risk factor exposures,
    then applies the same matrix VaR calculation.
    """

    @staticmethod
    def forward_contract_mapping(
        notional_foreign: float,
        spot_fx: float,
        domestic_rate: float,
        foreign_rate: float,
        maturity_years: float,
        risk_factor_vars: dict[str, float],
        correlation_matrix: np.ndarray,
    ) -> dict:
        """
        FX Forward mapped to 3 risk factors:
          1. Short domestic T-bill (PV of delivery rate K)
          2. Long foreign bill (PV in foreign currency × spot)
          3. Long FX spot position

        Value = S × N × e^(−r_f × T) − K × N × e^(−r_d × T)
        """
        # Present values
        pv_foreign = notional_foreign * np.exp(-foreign_rate * maturity_years) * spot_fx
        pv_domestic = notional_foreign * np.exp(-domestic_rate * maturity_years) * spot_fx

        # Risk factor exposures (all in domestic currency)
        exposures = {
            "domestic_bill_short": -pv_domestic,
            "foreign_bill_long": pv_foreign,
            "fx_spot_long": pv_foreign,
        }

        # Individual VaRs
        vars_per_factor = {
            k: abs(v) * risk_factor_vars.get(k, 0) / 100
            for k, v in exposures.items()
        }

        # Undiversified
        undiversified = sum(vars_per_factor.values())

        # Diversified via matrix math
        v_abs = np.array([abs(exposures[k]) * risk_factor_vars.get(k, 0) / 100
                          for k in ["domestic_bill_short", "foreign_bill_long", "fx_spot_long"]])
        diversified_sq = float(v_abs @ correlation_matrix @ v_abs)
        diversified = float(np.sqrt(max(diversified_sq, 0)))

        return {
            "instrument": "FX Forward",
            "exposures": {k: round(v, 2) for k, v in exposures.items()},
            "individual_vars": {k: round(v, 4) for k, v in vars_per_factor.items()},
            "undiversified_var": round(undiversified, 4),
            "diversified_var": round(diversified, 4),
            "benefit_pct": round((undiversified - diversified) / undiversified * 100, 2)
                           if undiversified > 0 else 0,
        }

    @staticmethod
    def fra_mapping(
        notional: float,
        short_maturity: float,
        long_maturity: float,
        short_rate: float,
        long_rate: float,
        var_pct_short: float,
        var_pct_long: float,
        correlation: float = 0.95,
    ) -> dict:
        """
        Forward Rate Agreement mapped to 2 risk factors:
          - Short position in short-dated zero
          - Long position in long-dated zero

        e.g. 6×12 FRA = borrow for 180 days, invest for 360 days.
        """
        pv_short = notional / (1 + short_rate * short_maturity)
        pv_long = notional / (1 + long_rate * long_maturity)

        var_short = abs(pv_short) * var_pct_short / 100
        var_long = abs(pv_long) * var_pct_long / 100

        undiversified = var_short + var_long

        # 2-asset diversified formula: √(V1² + V2² + 2ρV1V2)
        # For long/short: sign matters. FRA = short + long so:
        # VaR_div = √(V1² + V2² − 2ρV1V2) because positions are opposite
        diversified = float(np.sqrt(
            var_short**2 + var_long**2 - 2 * correlation * var_short * var_long
        ))

        return {
            "instrument": f"FRA {short_maturity*12:.0f}×{long_maturity*12:.0f}",
            "pv_short_leg": round(pv_short, 2),
            "pv_long_leg": round(pv_long, 2),
            "var_short_leg": round(var_short, 4),
            "var_long_leg": round(var_long, 4),
            "undiversified_var": round(undiversified, 4),
            "diversified_var": round(diversified, 4),
        }

    @staticmethod
    def option_delta_normal_var(
        spot: float,
        delta: float,
        n_contracts: float,
        spot_vol_annual: float,
        confidence: float = 0.95,
        horizon_days: int = 1,
    ) -> dict:
        """
        Delta-normal VaR for options.

        VaR_option ≈ |Δ| × S × σ_S × √(T/252) × z_α × N

        Limitations noted: inaccurate over long horizons where delta is unstable.
        """
        z = norm.ppf(confidence)
        var_amount = (
            abs(delta) * spot * spot_vol_annual * np.sqrt(horizon_days / 252)
            * z * n_contracts
        )

        return {
            "instrument": "Option (delta-normal)",
            "delta": delta,
            "spot": spot,
            "contracts": n_contracts,
            "vol_annual": spot_vol_annual,
            "confidence": confidence,
            "horizon_days": horizon_days,
            "var_amount": round(var_amount, 2),
            "caveat": (
                "델타-노말은 단기(1일) 지평선에서만 정확. 장기에는 델타 불안정으로 오차 확대. "
                "옵션은 통상 Taylor 급수(델타-감마)로 매핑 권장."
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Tracking Error VaR (Benchmark-Relative)
# ═══════════════════════════════════════════════════════════════════════════════

def tracking_error_var(
    portfolio_bonds: list[Bond],
    benchmark_bonds: list[Bond],
    engine: VaRMappingEngine,
) -> dict:
    """
    Tracking error VaR = VaR of (portfolio − benchmark) cash flows.

    Smaller when portfolio cash flows closely match benchmark.
    """
    # Aggregate PV cash flows
    port_pv = {t: 0.0 for t in engine.maturities}
    bench_pv = {t: 0.0 for t in engine.maturities}

    for b in portfolio_bonds:
        for t, pv in b.present_value_cash_flows(engine.spot_rates):
            if t in port_pv:
                port_pv[t] += pv

    for b in benchmark_bonds:
        for t, pv in b.present_value_cash_flows(engine.spot_rates):
            if t in bench_pv:
                bench_pv[t] += pv

    # Active positions = portfolio − benchmark
    active = np.array([port_pv[t] - bench_pv[t] for t in engine.maturities])
    v = np.array([engine.zero_var_pct[t] / 100 for t in engine.maturities])

    individual_te = np.abs(active) * v
    te_undiversified = float(np.sum(individual_te))
    te_diversified = float(np.sqrt(individual_te @ engine.correlation @ individual_te))

    return {
        "tracking_error_undiversified": round(te_undiversified, 4),
        "tracking_error_diversified": round(te_diversified, 4),
        "active_pv_by_maturity": {
            str(t): round(float(active[i]), 2)
            for i, t in enumerate(engine.maturities)
        },
        "interpretation": (
            "TE-VaR가 낮을수록 벤치마크를 잘 추적. "
            "현금흐름 매칭 정도가 낮을수록 TE-VaR 증가."
        ),
    }
