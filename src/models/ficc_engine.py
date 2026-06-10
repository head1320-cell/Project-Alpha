"""
FICC Quant Engine
- Black-Scholes Option Greeks (Delta, Gamma, Theta, Vega, Rho)
- Fixed Income: Modified Duration, Convexity, BPV, Yield curve mapping
- Currency Forward pricing
"""
import numpy as np
from scipy.stats import norm


class FICCEngine:

    # ─── OPTIONS ────────────────────────────────────────────────────────────
    @staticmethod
    def bs_greeks(
        S: float, K: float, T: float,
        r: float, sigma: float, option_type: str = "call"
    ) -> dict:
        """
        Black-Scholes Greeks for European vanilla options.
        T in years, sigma as decimal (0.2 = 20%).
        """
        if T <= 0 or sigma <= 0 or S <= 0:
            return dict(Price=0, Delta=0, Gamma=0, Theta=0, Vega=0, Rho=0)

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        N = norm.cdf
        n = norm.pdf

        gamma = n(d1) / (S * sigma * np.sqrt(T))
        vega  = S * n(d1) * np.sqrt(T) / 100        # per 1% vol move

        if option_type.lower() == "call":
            price = S * N(d1) - K * np.exp(-r * T) * N(d2)
            delta = N(d1)
            theta = (-(S * sigma * n(d1)) / (2 * np.sqrt(T))
                     - r * K * np.exp(-r * T) * N(d2)) / 365
            rho   = K * T * np.exp(-r * T) * N(d2) / 100
        else:
            price = K * np.exp(-r * T) * N(-d2) - S * N(-d1)
            delta = N(d1) - 1
            theta = (-(S * sigma * n(d1)) / (2 * np.sqrt(T))
                     + r * K * np.exp(-r * T) * N(-d2)) / 365
            rho   = -K * T * np.exp(-r * T) * N(-d2) / 100

        return {
            "Type":  option_type.upper(),
            "Price": round(price, 4),
            "Delta": round(delta, 4),
            "Gamma": round(gamma, 6),
            "Theta": round(theta, 4),   # 1-day time decay
            "Vega":  round(vega, 4),    # per 1% vol
            "Rho":   round(rho, 4),     # per 1% rate
        }

    @staticmethod
    def implied_vol(market_price: float, S: float, K: float,
                    T: float, r: float, option_type: str = "call",
                    tol: float = 1e-6, max_iter: int = 200) -> float:
        """Newton-Raphson implied volatility solver."""
        sigma = 0.20
        for _ in range(max_iter):
            g = FICCEngine.bs_greeks(S, K, T, r, sigma, option_type)
            price = g["Price"]
            vega  = g["Vega"] * 100  # convert back to absolute
            diff  = price - market_price
            if abs(diff) < tol:
                break
            if vega == 0:
                break
            sigma -= diff / vega
            sigma = max(sigma, 1e-6)
        return round(sigma, 6)

    # ─── FIXED INCOME ────────────────────────────────────────────────────────
    @staticmethod
    def bond_analytics(
        face_value: float,
        coupon_rate: float,
        ytm: float,
        years_to_maturity: int,
        freq: int = 2,
    ) -> dict:
        """
        Full bond analytics: Price, Macaulay/Modified Duration, Convexity, BPV.
        """
        periods = years_to_maturity * freq
        coupon  = (coupon_rate / freq) * face_value
        y       = ytm / freq

        price = mac_num = conv_num = 0.0
        for t in range(1, periods + 1):
            cf       = coupon if t < periods else coupon + face_value
            df       = (1 + y) ** t
            pv_cf    = cf / df
            price   += pv_cf
            mac_num += t * pv_cf
            conv_num += t * (t + 1) * pv_cf

        mac_dur  = (mac_num / price) / freq
        mod_dur  = mac_dur / (1 + y)
        convexity = (conv_num / price) / ((1 + y) ** 2) / (freq ** 2)
        bpv       = price * mod_dur * 0.0001   # dollar value of 1bp

        return {
            "Price":             round(price, 4),
            "Macaulay_Duration": round(mac_dur, 4),
            "Modified_Duration": round(mod_dur, 4),
            "Convexity":         round(convexity, 4),
            "BPV":               round(bpv, 4),
            "DV01":              round(bpv, 4),
        }

    @staticmethod
    def bond_price_change(mod_duration: float, convexity: float,
                          price: float, dy: float) -> float:
        """
        Approximate price change for a yield shift dy (decimal).
        ΔP ≈ -D_mod * P * Δy + 0.5 * C * P * (Δy)^2
        """
        return (-mod_duration * price * dy
                + 0.5 * convexity * price * dy ** 2)

    # ─── FX ──────────────────────────────────────────────────────────────────
    @staticmethod
    def fx_forward(spot: float, r_domestic: float,
                   r_foreign: float, T: float) -> float:
        """Interest rate parity forward rate."""
        return spot * np.exp((r_domestic - r_foreign) * T)

    @staticmethod
    def fx_var(position_value: float, fx_vol: float,
               confidence_level: float = 0.99,
               holding_period: int = 1) -> float:
        """Simple normal FX VaR."""
        z = norm.ppf(confidence_level)
        return position_value * fx_vol * np.sqrt(holding_period) * z
