"""
Cash Management — 유휴 현금 이자 수익 + 구매력 검증
==========================================================
헤지펀드의 비밀: 100% 풀투자 안 한다. 평소 20-40% 현금 유지.
이 현금은 MMF/단기국채/CD에 들어가 연 3-4% 무위험 수익.

매크로 약세장(STAGFLATION/DEFLATION)에 주식 비중 줄이면 현금 비중이 80%까지 가능.
이때 cash yield가 포트폴리오 방어에 결정적.

구성:
  ① CashYieldCalculator — 일별 이자 수익 계산
     daily_cash_return = cash_ratio × (rf_annual / 252)
     rf_annual은 매크로 데이터의 CD91 또는 KORIBOR3M 사용

  ② BuyingPowerValidator — 동시 매수 시 구매력 초과 방지
     Σ buy_value ≤ available_cash → 초과 시 prorata scaling 또는 priority cutoff

  ③ CashRateProvider — 매크로 데이터에서 무위험금리 PIT-safe 조회
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_RF_ANNUAL = 0.035          # 한국 CD91 평균 ~3.5% (2024-2025)
RF_FLOOR = 0.005                   # 최소 0.5%
RF_CEILING = 0.10                  # 최대 10%


# ═══════════════════════════════════════════════════════════════════════════════
# CashRateProvider
# ═══════════════════════════════════════════════════════════════════════════════

class CashRateProvider:
    """매크로 DB에서 PIT-safe 무위험금리 조회."""

    def __init__(self, engine, default_rf: float = DEFAULT_RF_ANNUAL):
        self.engine = engine
        self.default_rf = default_rf
        self._cache: dict = {}

    def get_rate(self, as_of_date: pd.Timestamp) -> float:
        """as_of_date 기준 PIT-safe 무위험금리."""
        if not self.engine:
            return self.default_rf

        cache_key = str(as_of_date.date()) if hasattr(as_of_date, "date") else str(as_of_date)
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            with self.engine.connect() as conn:
                # CD91 또는 KORIBOR3M 또는 BASE_RATE 우선순위로 조회
                rate = None
                for symbol in ["CD91", "KORIBOR3M", "BASE_RATE", "CMA_RATE", "DGS3MO"]:
                    row = conn.execute(text("""
                        SELECT value FROM macro_global
                        WHERE symbol = :s AND series_date <= :d
                        ORDER BY series_date DESC LIMIT 1
                    """), {"s": symbol, "d": cache_key}).fetchone()
                    if row:
                        val = float(row._mapping["value"])
                        # 단위 정규화: % → decimal
                        if val > 1:
                            val = val / 100.0
                        rate = val
                        break

                if rate is None:
                    rate = self.default_rf

                # 안전 범위 클램프
                rate = max(RF_FLOOR, min(RF_CEILING, rate))

            self._cache[cache_key] = rate
            return rate
        except Exception as e:
            logger.warning(f"Rate fetch failed for {as_of_date}: {e}")
            return self.default_rf

    def daily_rate(self, as_of_date: pd.Timestamp) -> float:
        """연 → 일별 단리 환산."""
        return self.get_rate(as_of_date) / 252


# ═══════════════════════════════════════════════════════════════════════════════
# CashYieldCalculator
# ═══════════════════════════════════════════════════════════════════════════════

class CashYieldCalculator:
    """
    유휴 현금의 일별 이자 수익 계산.

    Usage:
        rate_provider = CashRateProvider(engine)
        calc = CashYieldCalculator(rate_provider)

        # 일별 계산
        cash_ret = calc.daily_yield(
            invested_ratio=0.65,
            as_of_date=pd.Timestamp("2024-06-15"),
        )
        # → cash_ratio (0.35) × (0.035 / 252) ≈ 0.0000486
    """

    def __init__(self, rate_provider: CashRateProvider):
        self.rate_provider = rate_provider

    def daily_yield(
        self,
        invested_ratio: float,
        as_of_date: pd.Timestamp,
        cash_floor: float = 0.0,
    ) -> dict:
        """
        일별 현금 수익률 계산.

        Args:
            invested_ratio:  주식 등 투자된 비중 (0~1)
            as_of_date:      날짜 (PIT-safe)
            cash_floor:      최소 현금 비중 (운영 자금)

        Returns:
            {
              "cash_ratio":       0~1,
              "rf_annual":        무위험금리 (소수),
              "rf_daily":         일별 환산,
              "cash_return_pct":  일별 추가 수익률 (단리),
              "available":        bool,
            }
        """
        invested = max(0.0, min(1.0, invested_ratio))
        cash_ratio = max(cash_floor, 1.0 - invested)

        rf_annual = self.rate_provider.get_rate(as_of_date)
        rf_daily = rf_annual / 252
        cash_return = cash_ratio * rf_daily

        return {
            "cash_ratio":      round(cash_ratio, 4),
            "rf_annual":       round(rf_annual, 5),
            "rf_daily":        round(rf_daily, 8),
            "cash_return_pct": round(cash_return, 8),
            "available":       True,
        }

    def cumulative_yield(
        self,
        invested_ratio_series: pd.Series,
        date_series: pd.Series,
    ) -> dict:
        """
        기간 누적 현금 수익 계산 (백테스트 후처리용).

        Args:
            invested_ratio_series:  일별 투자 비중
            date_series:            일별 날짜

        Returns:
            {
              "n_days": int,
              "avg_cash_ratio": float,
              "avg_rf_annual": float,
              "cumulative_cash_return_pct": float,  # 단리 누적
            }
        """
        if len(invested_ratio_series) != len(date_series):
            return {"available": False, "message": "길이 불일치"}

        daily_returns = []
        rates = []
        cash_ratios = []

        for inv, date in zip(invested_ratio_series, date_series):
            y = self.daily_yield(inv, date)
            daily_returns.append(y["cash_return_pct"])
            rates.append(y["rf_annual"])
            cash_ratios.append(y["cash_ratio"])

        return {
            "available":                    True,
            "n_days":                       len(daily_returns),
            "avg_cash_ratio":               round(float(np.mean(cash_ratios)), 4),
            "avg_rf_annual":                round(float(np.mean(rates)), 5),
            "cumulative_cash_return_pct":   round(float(sum(daily_returns) * 100), 4),
            "annualized_cash_yield_pct":    round(
                float(np.mean(cash_ratios) * np.mean(rates) * 100), 4
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# BuyingPowerValidator
# ═══════════════════════════════════════════════════════════════════════════════

class BuyingPowerValidator:
    """
    멀티 전략 동시 매수 시 구매력 검증.

    핵심 시나리오:
      - 모든 전략이 반등 시그널 발생 (예: 패닉 후 회복)
      - 각 전략 풀매수 → 합산 매수 주문이 가용 현금 초과
      - 증권사 측 주문 거절 → 일부만 체결 → 백테스트와 괴리

    해결책:
      1. 매수 주문 합산 vs 가용 현금 검증
      2. 초과 시 strategy_priority 또는 prorata로 수량 축소
      3. 매도 주문은 자유 (현금 증가)
    """

    @staticmethod
    def validate(
        orders: list[dict],
        available_cash_krw: float,
        strategy_priorities: dict | None = None,
        max_leverage: float = 1.0,
        mode: str = "prorata",   # prorata | priority | strict
    ) -> dict:
        """
        매수 주문 합산 검증 + 필요 시 축소.

        Args:
            orders: [{ticker, side, quantity, price, strategy_id, value_krw?}]
            available_cash_krw: 가용 현금
            strategy_priorities: {strategy_id: priority_score} (0~1, 높을수록 우선)
            max_leverage: 1.0 = no leverage, 1.5 = 50% margin allowed
            mode: 축소 방식

        Returns:
            {
              "validated":     bool,
              "needs_scaling": bool,
              "scaling_factor": float,
              "buy_value_total":     float,
              "sell_value_total":    float,
              "net_buy_value":       float,
              "available_capital":   float,
              "exceeded_by_krw":     float,
              "orders_adjusted":     [...] (축소된 주문)
              "rejected_orders":     [...] (cut된 주문 priority 모드)
            }
        """
        if not orders:
            return {
                "validated":           True,
                "needs_scaling":       False,
                "scaling_factor":      1.0,
                "buy_value_total":     0,
                "sell_value_total":    0,
                "net_buy_value":       0,
                "available_capital":   available_cash_krw,
                "exceeded_by_krw":     0,
                "orders_adjusted":     [],
                "rejected_orders":     [],
            }

        # value_krw 계산
        for o in orders:
            if "value_krw" not in o or o["value_krw"] is None:
                o["value_krw"] = abs(o.get("quantity", 0) * o.get("price", 0))

        buy_orders = [o for o in orders if o.get("side") == "BUY"]
        sell_orders = [o for o in orders if o.get("side") == "SELL"]

        buy_value = sum(o["value_krw"] for o in buy_orders)
        sell_value = sum(o["value_krw"] for o in sell_orders)

        # 사용 가능 자본 = cash + (매도로 들어올 자금) × max_leverage
        # (단순화: 같은 날 매도 대금이 매수 가능 자본에 즉시 가산)
        available_capital = (available_cash_krw + sell_value) * max_leverage

        net_buy = buy_value - sell_value
        exceeded = max(0, buy_value - available_capital)

        if exceeded <= 0:
            # OK, 조정 불필요
            return {
                "validated":           True,
                "needs_scaling":       False,
                "scaling_factor":      1.0,
                "buy_value_total":     round(buy_value, 0),
                "sell_value_total":    round(sell_value, 0),
                "net_buy_value":       round(net_buy, 0),
                "available_capital":   round(available_capital, 0),
                "exceeded_by_krw":     0,
                "orders_adjusted":     orders,
                "rejected_orders":     [],
            }

        # 조정 필요
        scaling_factor = available_capital / buy_value if buy_value > 0 else 0
        adjusted_buys = []
        rejected = []

        if mode == "prorata":
            # 모든 매수 주문에 동일 비율 축소
            for o in buy_orders:
                new_qty = int(o["quantity"] * scaling_factor)
                if new_qty > 0:
                    adj = dict(o)
                    adj["quantity"] = new_qty
                    adj["value_krw"] = new_qty * o["price"]
                    adj["scaled_from"] = o["quantity"]
                    adjusted_buys.append(adj)
                else:
                    rejected.append(o)

        elif mode == "priority":
            # priority 높은 순서로 채우고, 남으면 cut
            prios = strategy_priorities or {}
            sorted_buys = sorted(buy_orders,
                                  key=lambda x: -prios.get(x.get("strategy_id"), 0.5))
            remaining = available_capital
            for o in sorted_buys:
                if remaining >= o["value_krw"]:
                    adjusted_buys.append(o)
                    remaining -= o["value_krw"]
                else:
                    # 부분 체결 가능
                    if remaining > 0:
                        partial_qty = int(remaining / o["price"])
                        if partial_qty > 0:
                            adj = dict(o)
                            adj["quantity"] = partial_qty
                            adj["value_krw"] = partial_qty * o["price"]
                            adj["partial_fill"] = True
                            adjusted_buys.append(adj)
                            remaining = 0
                    else:
                        rejected.append(o)

        elif mode == "strict":
            # 초과면 전체 매수 취소
            rejected = buy_orders
            adjusted_buys = []
            scaling_factor = 0
        else:
            adjusted_buys = buy_orders

        all_adjusted = adjusted_buys + sell_orders

        return {
            "validated":          False,
            "needs_scaling":      True,
            "scaling_factor":     round(scaling_factor, 4),
            "buy_value_total":    round(buy_value, 0),
            "sell_value_total":   round(sell_value, 0),
            "net_buy_value":      round(net_buy, 0),
            "available_capital":  round(available_capital, 0),
            "exceeded_by_krw":    round(exceeded, 0),
            "orders_adjusted":    all_adjusted,
            "rejected_orders":    rejected,
            "mode":               mode,
        }
