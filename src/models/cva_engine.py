"""
Credit Valuation Adjustment (CVA) Engine
=========================================
Prices counterparty credit risk for OTC derivatives portfolios.

Reference: FRM Part II, Readings 27, 30, 38, 39

CVA = −Σ DF_i × EE_i × q_i × LGD
  where:
    DF_i  = risk-free discount factor at time i
    EE_i  = expected exposure at midpoint of interval i
    q_i   = marginal default probability during interval i
    LGD   = loss given default (1 − recovery rate)

Components:
  1. Hazard rate extraction from CDS spreads (bootstrap term structure)
  2. Survival & marginal PD term structure
  3. Expected exposure profiles (analytical + simulation)
  4. Unilateral CVA & CVA spread
  5. Bilateral CVA (BCVA) with DVA
  6. Stressed CVA
"""

from dataclasses import dataclass, field

import numpy as np

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Hazard Rate & PD Extraction from CDS Spreads
# ═══════════════════════════════════════════════════════════════════════════════

class CDSHazardRateModel:
    """
    Extract default probabilities from CDS market spreads.

    Approximate method (near-par bonds):
        λ ≈ CDS_spread / (1 − RR)

    Bootstrap method (term structure):
        λ(t₁,t₂) extracted from nested CDS maturities.

    Exact method (from CDS pricing):
        PS_t = e^{−λ·t},  PD_t = PS_{t-1} − PS_t
    """

    def __init__(self, recovery_rate: float = 0.40):
        self.RR = recovery_rate
        self.LGD = 1.0 - recovery_rate

    def approximate_hazard_rate(self, cds_spread_bps: float) -> float:
        """
        Quick approximation: λ ≈ s / (1 − RR)

        Works well for par-valued bonds.
        """
        s = cds_spread_bps / 10_000  # convert bps to decimal
        return s / self.LGD

    def bootstrap_hazard_rates(
        self, cds_spreads: dict[int, float]
    ) -> dict:
        """
        Bootstrap a term structure of hazard rates from CDS spreads.

        Parameters
        ----------
        cds_spreads : dict[int, float]
            Maturity (years) → CDS spread (bps).
            e.g. {1: 50, 3: 80, 5: 120, 10: 150}

        Returns
        -------
        dict with cumulative and forward hazard rates.
        """
        maturities = sorted(cds_spreads.keys())
        cum_hazards = {}
        fwd_hazards = {}

        prev_maturity = 0
        prev_cum_lambda_T = 0.0

        for T in maturities:
            s = cds_spreads[T] / 10_000
            avg_lambda = s / self.LGD
            cum_hazards[T] = round(avg_lambda, 6)

            # Forward hazard rate for the interval (prev_maturity, T)
            cum_lambda_T = avg_lambda * T
            if T > prev_maturity and T != maturities[0]:
                fwd_lambda = (cum_lambda_T - prev_cum_lambda_T) / (T - prev_maturity)
            else:
                fwd_lambda = avg_lambda

            fwd_hazards[f"{prev_maturity}y-{T}y"] = round(fwd_lambda, 6)
            prev_maturity = T
            prev_cum_lambda_T = cum_lambda_T

        return {
            "cumulative_hazard_rates": cum_hazards,
            "forward_hazard_rates": fwd_hazards,
            "recovery_rate": self.RR,
            "lgd": self.LGD,
        }

    def survival_probability(self, hazard_rate: float, t: float) -> float:
        """PS(t) = e^{−λ·t}"""
        return np.exp(-hazard_rate * t)

    def default_probability_by_time(self, hazard_rate: float, t: float) -> float:
        """PD(0,t) = 1 − PS(t) = 1 − e^{−λ·t}"""
        return 1.0 - self.survival_probability(hazard_rate, t)

    def marginal_default_probabilities(
        self, hazard_rate: float, n_years: int, intervals_per_year: int = 1
    ) -> list[dict]:
        """
        Compute survival and marginal PD for each interval.

        q_i = PS(t_{i-1}) − PS(t_i)

        This is the key input for CVA calculation.
        """
        dt = 1.0 / intervals_per_year
        n_intervals = int(n_years * intervals_per_year)
        schedule = []

        for i in range(1, n_intervals + 1):
            t_start = (i - 1) * dt
            t_end = i * dt
            t_mid = (t_start + t_end) / 2

            ps_start = self.survival_probability(hazard_rate, t_start)
            ps_end = self.survival_probability(hazard_rate, t_end)
            marginal_pd = ps_start - ps_end

            schedule.append({
                "interval": i,
                "t_start": round(t_start, 4),
                "t_end": round(t_end, 4),
                "t_mid": round(t_mid, 4),
                "survival_prob": round(ps_end, 6),
                "marginal_pd": round(marginal_pd, 6),
                "cumulative_pd": round(1 - ps_end, 6),
            })

        return schedule


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Expected Exposure Profiles
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExposureProfile:
    """Expected exposure profile for a derivatives position."""
    name: str
    notional: float
    maturity_years: float
    position_type: str = "irs"  # irs, fx_forward, option
    ee_profile: np.ndarray | None = field(default=None, repr=False)

    def generate_ee_profile(
        self, n_intervals: int, volatility: float = 0.02, peak_fraction: float = 0.5
    ) -> np.ndarray:
        """
        Generate a stylised EE profile.

        IRS: hump-shaped (peaks mid-life then declines toward maturity)
        FX Forward: linearly increasing
        Option: front-loaded then decaying
        """
        t = np.linspace(0, 1, n_intervals + 1)[1:]  # exclude t=0

        if self.position_type == "irs":
            # Hump profile: EE = N * σ * √t * (1-t) * scale
            raw = np.sqrt(t) * (1 - t ** 1.5) * volatility * self.notional * 4
        elif self.position_type == "fx_forward":
            # Linearly increasing then dropping to 0 at maturity
            raw = t * (1 - 0.3 * t) * volatility * self.notional * 3
        elif self.position_type == "option":
            # Front-loaded: high early, decaying
            raw = np.exp(-2 * t) * volatility * self.notional * 2
        else:
            raw = np.ones(n_intervals) * volatility * self.notional

        self.ee_profile = np.maximum(raw, 0)
        return self.ee_profile


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CVA Engine
# ═══════════════════════════════════════════════════════════════════════════════

class CVAEngine:
    """
    Computes unilateral CVA, bilateral CVA (BCVA), CVA spread,
    and stressed CVA.

    CVA = −Σ DF_i × EE_i × q_i × LGD

    BCVA = CVA + DVA
    DVA  = +Σ DF_i × ENE_i × q_bank_i × LGD_bank
    """

    def __init__(
        self,
        risk_free_rate: float = 0.03,
        recovery_rate: float = 0.40,
    ):
        self.r = risk_free_rate
        self.RR = recovery_rate
        self.LGD = 1.0 - recovery_rate
        self.hazard_model = CDSHazardRateModel(recovery_rate)

    def discount_factor(self, t: float) -> float:
        """Continuous discount factor: DF(t) = e^{−r·t}"""
        return np.exp(-self.r * t)

    # ─── Unilateral CVA ──────────────────────────────────────────────────────

    def calculate_cva(
        self,
        ee_profile: np.ndarray,
        hazard_rate: float,
        maturity_years: float,
    ) -> dict:
        """
        Unilateral CVA calculation.

        CVA = −Σ DF(t_mid) × EE(t_i) × q_i × LGD

        Parameters
        ----------
        ee_profile : np.ndarray
            Expected exposure at each interval midpoint.
        hazard_rate : float
            Constant hazard rate (from CDS spread / LGD).
        maturity_years : float
            Contract maturity in years.
        """
        n = len(ee_profile)
        maturity_years / n

        pd_schedule = self.hazard_model.marginal_default_probabilities(
            hazard_rate, maturity_years, intervals_per_year=max(1, int(round(n / maturity_years)))
        )

        # Align lengths
        m = min(n, len(pd_schedule))

        cva_components = []
        total_cva = 0.0

        for i in range(m):
            t_mid = pd_schedule[i]["t_mid"]
            df = self.discount_factor(t_mid)
            ee = float(ee_profile[i])
            q = pd_schedule[i]["marginal_pd"]

            component = df * ee * q * self.LGD
            total_cva += component

            cva_components.append({
                "interval": i + 1,
                "t_mid": round(t_mid, 4),
                "df": round(df, 6),
                "ee": round(ee, 0),
                "marginal_pd": round(q, 6),
                "cva_component": round(component, 2),
            })

        return {
            "cva_amount": round(total_cva, 2),
            "cva_bps": round(total_cva / max(ee_profile) * 10_000, 2) if max(ee_profile) > 0 else 0,
            "lgd": self.LGD,
            "hazard_rate": round(hazard_rate, 6),
            "maturity_years": maturity_years,
            "n_intervals": m,
            "components": cva_components,
            "ee_profile": [round(float(e), 0) for e in ee_profile[:m]],
            "pd_schedule": pd_schedule[:m],
        }

    # ─── CVA Spread ──────────────────────────────────────────────────────────

    @staticmethod
    def cva_spread(cva_amount: float, epe: float, maturity_years: float) -> float:
        """
        Approximate CVA as an annual running spread (bps).

        CVA_spread ≈ CVA / (EPE × risky_annuity)
        Simplified: CVA / (EPE × maturity)  in bps
        """
        if epe <= 0 or maturity_years <= 0:
            return 0.0
        spread = cva_amount / (epe * maturity_years)
        return round(spread * 10_000, 2)  # in bps

    # ─── Bilateral CVA (BCVA) ────────────────────────────────────────────────

    def calculate_bcva(
        self,
        ee_profile: np.ndarray,
        ene_profile: np.ndarray,
        counterparty_hazard: float,
        bank_hazard: float,
        maturity_years: float,
        bank_recovery: float = 0.40,
    ) -> dict:
        """
        Bilateral CVA = CVA + DVA.

        CVA = Σ DF × EE  × q_counterparty × LGD_counterparty × PS_bank
        DVA = Σ DF × ENE × q_bank × LGD_bank × PS_counterparty

        BCVA = −CVA + DVA

        DVA is a benefit to the bank (bank's own default risk reduces
        the net cost of counterparty risk).
        """
        n = min(len(ee_profile), len(ene_profile))
        dt = maturity_years / n

        bank_lgd = 1.0 - bank_recovery

        cva_total = 0.0
        dva_total = 0.0

        for i in range(n):
            t_mid = (i + 0.5) * dt
            df = self.discount_factor(t_mid)

            # Survival probabilities
            ps_cpty = self.hazard_model.survival_probability(counterparty_hazard, (i) * dt)
            ps_bank = self.hazard_model.survival_probability(bank_hazard, (i) * dt)

            # Marginal PDs
            ps_cpty_next = self.hazard_model.survival_probability(counterparty_hazard, (i + 1) * dt)
            ps_bank_next = self.hazard_model.survival_probability(bank_hazard, (i + 1) * dt)
            q_cpty = ps_cpty - ps_cpty_next
            q_bank = ps_bank - ps_bank_next

            # CVA component (counterparty defaults, bank survives)
            cva_total += df * float(ee_profile[i]) * q_cpty * self.LGD * ps_bank

            # DVA component (bank defaults, counterparty survives)
            dva_total += df * float(ene_profile[i]) * q_bank * bank_lgd * ps_cpty

        bcva = -cva_total + dva_total

        return {
            "cva_amount": round(cva_total, 2),
            "dva_amount": round(dva_total, 2),
            "bcva_amount": round(bcva, 2),
            "counterparty_hazard": round(counterparty_hazard, 6),
            "bank_hazard": round(bank_hazard, 6),
            "counterparty_lgd": self.LGD,
            "bank_lgd": round(bank_lgd, 4),
            "interpretation": (
                "DVA > CVA → 은행 자체 부도위험이 상대방보다 높음"
                if dva_total > cva_total
                else "CVA > DVA → 상대방 부도위험이 더 높음 (일반적)"
            ),
        }

    # ─── BCVA Spread ─────────────────────────────────────────────────────────

    @staticmethod
    def bcva_spread(
        counterparty_spread_bps: float,
        epe: float,
        bank_spread_bps: float,
        ene: float,
    ) -> dict:
        """
        BCVA as a running spread:
        BCVA_spread = −(s_cpty × EPE) + (s_bank × ENE)
        """
        s_cpty = counterparty_spread_bps / 10_000
        s_bank = bank_spread_bps / 10_000

        cva_spread = s_cpty * epe
        dva_spread = s_bank * ene
        bcva_spread = -cva_spread + dva_spread

        return {
            "cva_spread_annual": round(cva_spread * 10_000, 2),
            "dva_spread_annual": round(dva_spread * 10_000, 2),
            "bcva_spread_annual": round(bcva_spread * 10_000, 2),
            "unit": "bps",
        }

    # ─── Stressed CVA ────────────────────────────────────────────────────────

    def stressed_cva(
        self,
        ee_profile: np.ndarray,
        base_hazard: float,
        maturity_years: float,
        spread_shock_bps: float = 100,
        exposure_shock_pct: float = 0.20,
    ) -> dict:
        """
        Stressed CVA: apply shocks to credit spread and exposure.

        Shock 1: CDS spread widens → higher PD
        Shock 2: Exposure increases (adverse market move)

        Stress loss = CVA_stressed − CVA_base
        """
        # Base CVA
        base = self.calculate_cva(ee_profile, base_hazard, maturity_years)
        base_cva = base["cva_amount"]

        # Shocked hazard rate (spread widening)
        shocked_spread = base_hazard * self.LGD * 10_000 + spread_shock_bps
        shocked_hazard = shocked_spread / 10_000 / self.LGD

        # Shocked exposure
        shocked_ee = ee_profile * (1 + exposure_shock_pct)

        # Stressed CVA
        stressed = self.calculate_cva(shocked_ee, shocked_hazard, maturity_years)
        stressed_cva_val = stressed["cva_amount"]

        stress_loss = stressed_cva_val - base_cva

        return {
            "base_cva": round(base_cva, 2),
            "stressed_cva": round(stressed_cva_val, 2),
            "stress_loss": round(stress_loss, 2),
            "stress_loss_pct": round(stress_loss / base_cva * 100, 2) if base_cva > 0 else 0,
            "shocks_applied": {
                "spread_shock_bps": spread_shock_bps,
                "exposure_shock_pct": round(exposure_shock_pct * 100, 1),
                "base_hazard": round(base_hazard, 6),
                "stressed_hazard": round(shocked_hazard, 6),
            },
        }

    # ─── Comprehensive Report ────────────────────────────────────────────────

    def full_cva_report(
        self,
        notional: float,
        maturity_years: float,
        cds_spread_bps: float,
        position_type: str = "irs",
        volatility: float = 0.02,
        bank_cds_spread_bps: float = 50,
        bank_recovery: float = 0.40,
        spread_shock_bps: float = 100,
        cds_term_structure: dict[int, float] | None = None,
    ) -> dict:
        """
        Full CVA analysis report.

        Generates EE profile, extracts PD from CDS spreads, computes
        unilateral CVA, BCVA, CVA spread, stressed CVA, and optionally
        bootstraps a hazard rate term structure.
        """
        # 1. Generate EE profile
        n_intervals = max(int(maturity_years * 4), 4)  # quarterly
        exposure = ExposureProfile(
            name=f"{position_type.upper()} Position",
            notional=notional,
            maturity_years=maturity_years,
            position_type=position_type,
        )
        ee_profile = exposure.generate_ee_profile(n_intervals, volatility)
        # ENE (mirror of EE for DVA — counterparty's perspective)
        ene_profile = ee_profile * 0.8  # simplified: ENE ≈ 80% of EE

        epe = float(np.mean(ee_profile))  # expected positive exposure (time-avg)

        # 2. Extract hazard rate from CDS spread
        cpty_hazard = self.hazard_model.approximate_hazard_rate(cds_spread_bps)
        bank_hazard = CDSHazardRateModel(bank_recovery).approximate_hazard_rate(bank_cds_spread_bps)

        # 3. Unilateral CVA
        cva_result = self.calculate_cva(ee_profile, cpty_hazard, maturity_years)

        # 4. CVA Spread
        cva_sprd = self.cva_spread(cva_result["cva_amount"], epe, maturity_years)

        # 5. BCVA
        bcva_result = self.calculate_bcva(
            ee_profile, ene_profile,
            cpty_hazard, bank_hazard,
            maturity_years, bank_recovery,
        )

        # 6. BCVA Spread
        ene_avg = float(np.mean(ene_profile))
        bcva_sprd = self.bcva_spread(cds_spread_bps, epe, bank_cds_spread_bps, ene_avg)

        # 7. Stressed CVA
        stress_result = self.stressed_cva(
            ee_profile, cpty_hazard, maturity_years,
            spread_shock_bps=spread_shock_bps,
        )

        # 8. Hazard rate term structure (if provided)
        ts_result = None
        if cds_term_structure:
            ts_result = self.hazard_model.bootstrap_hazard_rates(cds_term_structure)

        # 9. PD summary
        pd_summary = {
            "hazard_rate": round(cpty_hazard, 6),
            "1y_pd": round(self.hazard_model.default_probability_by_time(cpty_hazard, 1), 6),
            "3y_pd": round(self.hazard_model.default_probability_by_time(cpty_hazard, 3), 6),
            "5y_pd": round(self.hazard_model.default_probability_by_time(cpty_hazard, 5), 6),
            "1y_survival": round(self.hazard_model.survival_probability(cpty_hazard, 1), 6),
            "5y_survival": round(self.hazard_model.survival_probability(cpty_hazard, 5), 6),
        }

        return {
            "inputs": {
                "notional": notional,
                "maturity_years": maturity_years,
                "position_type": position_type,
                "cds_spread_bps": cds_spread_bps,
                "recovery_rate": self.RR,
                "lgd": self.LGD,
                "risk_free_rate": self.r,
            },
            "pd_from_cds": pd_summary,
            "hazard_rate_term_structure": ts_result,
            "exposure_profile": {
                "epe": round(epe, 0),
                "peak_ee": round(float(np.max(ee_profile)), 0),
                "ee_values": [round(float(e), 0) for e in ee_profile],
            },
            "unilateral_cva": {
                "cva_amount": cva_result["cva_amount"],
                "cva_pct_of_notional": round(cva_result["cva_amount"] / notional * 100, 4),
                "cva_spread_bps": cva_sprd,
                "n_intervals": cva_result["n_intervals"],
            },
            "bilateral_cva": bcva_result,
            "bcva_spread": bcva_sprd,
            "stressed_cva": stress_result,
        }
