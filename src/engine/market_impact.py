"""
Market Impact Model — Square Root Law (Almgren-Chriss)
=========================================================
백테스트의 가장 큰 거짓말: "내가 주문하면 그 가격에 체결된다"
현실: 주문량이 ADV(일일 거래대금)의 1%를 넘어가면 슬리피지가 비선형 증가.

공식 (Almgren-Chriss 2000):
   slippage_bps = α × √(Q / ADV) × σ_daily × 10⁴

  · Q       : 주문 거래대금 (KRW)
  · ADV     : 일일 평균 거래대금 (KRW)
  · σ_daily : 일일 변동성 (예: 0.02 = 2%)
  · α       : 자산군별 calibration constant
              · KOSPI 대형주 (시총 5조 이상)   : 0.4 ~ 0.6
              · KOSPI 중형주 (시총 1~5조)      : 0.8 ~ 1.2
              · KOSPI 소형주 (시총 1조 미만)   : 1.5 ~ 2.5
              · 코스닥 일반                     : 2.0 ~ 3.0

영구 vs 일시 임팩트:
  · 영구 (permanent) : 50% — 호가 영구 이동, 다음 거래에도 영향
  · 일시 (temporary) : 50% — 즉시 회복, 본 거래에만 적용

Cross-Impact (선택):
  같은 섹터 다른 종목 동시 매수 시 추가 충격 발생 (Bouchaud 2018).
  본 구현에서는 단일 종목 임팩트만; 향후 확장 가능.

기존 선형 모델 vs 본 모델 비교:
  주문량 100M원 (대형주, ADV 1T원, σ 1.5%):
    선형 0.05% (=5bp)
    SQRT  0.4×√(0.0001)×0.015×10⁴ = 0.4×0.01×150 = 0.6bp
  주문량 50B원 (소형주, ADV 50B원, σ 4%):
    선형 0.05%   (=5bp)
    SQRT  2.0×√(1.0)×0.04×10⁴ = 800bp = 8% ← 백테스트 거의 무의미
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Asset Class Calibration
# ═══════════════════════════════════════════════════════════════════════════════

# (시가총액 KRW 임계값, α calibration)
ASSET_CLASS_TIERS = {
    "kospi_mega":    (10_000_000_000_000, 0.35),   # 시총 10조원 이상 (삼성/SK하이닉스)
    "kospi_large":   (5_000_000_000_000,  0.50),   # 5조 이상
    "kospi_mid":     (1_000_000_000_000,  0.90),   # 1조 이상
    "kospi_small":   (300_000_000_000,    1.50),   # 3000억 이상
    "kosdaq_large":  (1_000_000_000_000,  1.80),   # 코스닥 1조 이상
    "kosdaq_mid":    (300_000_000_000,    2.40),   # 코스닥 3000억 이상
    "kosdaq_small":  (0,                  3.20),   # 그 외 (취약 자산)
    "etf":           (0,                  0.45),   # ETF (높은 유동성)
}

# 영구/일시 임팩트 비율
PERMANENT_IMPACT_RATIO = 0.5
TEMPORARY_IMPACT_RATIO = 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# MarketImpactModel
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ImpactEstimate:
    """단일 주문의 시장 충격 추정."""
    order_value_krw:        float
    adv_krw:                float
    participation_rate:     float    # Q/ADV
    asset_class:            str
    alpha:                  float
    daily_volatility:       float

    permanent_impact_bps:   float
    temporary_impact_bps:   float
    total_impact_bps:       float
    total_impact_pct:       float    # = bps / 10000

    estimated_cost_krw:     float


class MarketImpactModel:
    """
    Square Root Law 기반 시장 충격 모델.

    Usage:
        model = MarketImpactModel()
        estimate = model.estimate_impact(
            order_value_krw=500_000_000,    # 5억 매수
            adv_krw=100_000_000_000,        # ADV 1000억
            daily_volatility=0.018,         # 일별 σ 1.8%
            asset_class="kospi_mid",
        )

        # 또는 자동 분류
        estimate = model.estimate_with_auto_classify(
            order_value_krw=500_000_000,
            adv_krw=100_000_000_000,
            market_cap_krw=2_500_000_000_000,  # 2.5조
            is_kosdaq=False,
            daily_volatility=0.018,
        )
    """

    def __init__(self, custom_alpha: dict | None = None):
        self.alpha_map = ASSET_CLASS_TIERS.copy()
        if custom_alpha:
            for k, v in custom_alpha.items():
                if k in self.alpha_map:
                    threshold, _ = self.alpha_map[k]
                    self.alpha_map[k] = (threshold, v)

    # ═════════════════════════════════════════════════════════════════════
    # 핵심 계산
    # ═════════════════════════════════════════════════════════════════════

    def estimate_impact(
        self,
        order_value_krw: float,
        adv_krw: float,
        daily_volatility: float,
        asset_class: str = "kospi_mid",
        side: str = "BUY",
    ) -> ImpactEstimate:
        """
        Square Root Law 시장 충격 추정.

        Args:
            order_value_krw:  주문 거래대금 (절대값)
            adv_krw:          일일 평균 거래대금
            daily_volatility: 일별 변동성 (예: 0.018)
            asset_class:      ASSET_CLASS_TIERS 키
            side:             BUY | SELL (대칭이지만 SELL이 약간 더 저렴)
        """
        order_value_krw = abs(order_value_krw)

        if adv_krw <= 0 or order_value_krw <= 0:
            return self._empty_estimate(order_value_krw, adv_krw, asset_class)

        alpha = self.alpha_map.get(asset_class, (0, 1.0))[1]

        # Participation rate (Q/ADV)
        participation = order_value_krw / adv_krw

        # Square root law: slippage_bps = α × √(Q/ADV) × σ × 10⁴
        # (variance-based formulation)
        total_bps = alpha * math.sqrt(participation) * daily_volatility * 10_000

        # SELL 측은 매도 압력으로 약 10% 저렴 (실증 결과)
        if side == "SELL":
            total_bps *= 0.9

        permanent_bps = total_bps * PERMANENT_IMPACT_RATIO
        temporary_bps = total_bps * TEMPORARY_IMPACT_RATIO
        total_pct = total_bps / 10_000

        return ImpactEstimate(
            order_value_krw=order_value_krw,
            adv_krw=adv_krw,
            participation_rate=round(participation, 6),
            asset_class=asset_class,
            alpha=alpha,
            daily_volatility=daily_volatility,
            permanent_impact_bps=round(permanent_bps, 2),
            temporary_impact_bps=round(temporary_bps, 2),
            total_impact_bps=round(total_bps, 2),
            total_impact_pct=round(total_pct, 6),
            estimated_cost_krw=round(order_value_krw * total_pct, 0),
        )

    def estimate_with_auto_classify(
        self,
        order_value_krw: float,
        adv_krw: float,
        market_cap_krw: float,
        daily_volatility: float,
        is_kosdaq: bool = False,
        is_etf: bool = False,
        side: str = "BUY",
    ) -> ImpactEstimate:
        """자산 분류를 시총/시장으로 자동 결정."""
        asset_class = self.classify_asset(market_cap_krw, is_kosdaq, is_etf)
        return self.estimate_impact(
            order_value_krw, adv_krw, daily_volatility, asset_class, side
        )

    @staticmethod
    def classify_asset(market_cap_krw: float, is_kosdaq: bool = False,
                        is_etf: bool = False) -> str:
        """시총/시장 → asset_class."""
        if is_etf:
            return "etf"
        if is_kosdaq:
            if market_cap_krw >= 1_000_000_000_000:
                return "kosdaq_large"
            elif market_cap_krw >= 300_000_000_000:
                return "kosdaq_mid"
            else:
                return "kosdaq_small"
        else:
            # KOSPI
            if market_cap_krw >= 10_000_000_000_000:
                return "kospi_mega"
            elif market_cap_krw >= 5_000_000_000_000:
                return "kospi_large"
            elif market_cap_krw >= 1_000_000_000_000:
                return "kospi_mid"
            else:
                return "kospi_small"

    # ═════════════════════════════════════════════════════════════════════
    # 포트폴리오 수준 충격 (멀티 주문 합산)
    # ═════════════════════════════════════════════════════════════════════

    def estimate_portfolio_impact(
        self,
        orders: list[dict],
        portfolio_equity: float,
    ) -> dict:
        """
        멀티 주문의 총 시장 충격 추정.

        Args:
            orders: [{ticker, value_krw, adv_krw, volatility, asset_class, side}]
            portfolio_equity: 포트폴리오 자산 (cost%/equity 환산용)

        Returns:
            {
              "total_cost_krw": float,
              "total_cost_pct": float,
              "weighted_avg_impact_bps": float,
              "by_order": [ImpactEstimate, ...],
            }
        """
        if not orders:
            return self._empty_portfolio_response(portfolio_equity)

        estimates = []
        total_cost = 0.0
        total_value = 0.0

        for order in orders:
            est = self.estimate_impact(
                order_value_krw=order.get("value_krw", 0),
                adv_krw=order.get("adv_krw", 0),
                daily_volatility=order.get("volatility", 0.02),
                asset_class=order.get("asset_class", "kospi_mid"),
                side=order.get("side", "BUY"),
            )
            estimates.append({
                "ticker":              order.get("ticker"),
                "side":                order.get("side"),
                "order_value_krw":     est.order_value_krw,
                "participation_rate":  est.participation_rate,
                "asset_class":         est.asset_class,
                "total_impact_bps":    est.total_impact_bps,
                "estimated_cost_krw":  est.estimated_cost_krw,
            })
            total_cost += est.estimated_cost_krw
            total_value += est.order_value_krw

        wavg_bps = (total_cost / total_value * 10_000) if total_value > 0 else 0
        total_cost_pct = (total_cost / portfolio_equity * 100) if portfolio_equity > 0 else 0

        return {
            "available":               True,
            "n_orders":                len(orders),
            "total_order_value_krw":   round(total_value, 0),
            "total_cost_krw":          round(total_cost, 0),
            "total_cost_pct":          round(total_cost_pct, 4),
            "weighted_avg_impact_bps": round(wavg_bps, 2),
            "by_order":                estimates,
        }

    # ═════════════════════════════════════════════════════════════════════
    # 백테스트용 간이 — turnover 기반
    # ═════════════════════════════════════════════════════════════════════

    @staticmethod
    def turnover_based_impact(
        turnover_pct: float,
        portfolio_equity: float,
        avg_adv_krw: float = 50_000_000_000,    # KOSPI 평균 약 500억
        avg_volatility: float = 0.018,
        weighted_alpha: float = 0.7,            # 포트폴리오 가중 α (대형주 위주)
    ) -> dict:
        """
        포트폴리오 수준 turnover로부터 평균 임팩트 추정.

        멀티 전략 백테스트에서 일별 turnover로 빠른 추정에 사용.
        """
        if turnover_pct <= 0 or portfolio_equity <= 0:
            return {"impact_bps": 0, "cost_krw": 0, "cost_pct": 0}

        # 일별 거래량 = turnover × portfolio_equity
        order_value = (turnover_pct / 100) * portfolio_equity
        if order_value <= 0 or avg_adv_krw <= 0:
            return {"impact_bps": 0, "cost_krw": 0, "cost_pct": 0}

        participation = order_value / avg_adv_krw
        impact_bps = weighted_alpha * math.sqrt(participation) * avg_volatility * 10_000
        cost_pct = impact_bps / 10_000
        cost_krw = order_value * cost_pct

        return {
            "impact_bps":     round(impact_bps, 2),
            "cost_pct":       round(cost_pct, 6),
            "cost_krw":       round(cost_krw, 0),
            "participation":  round(participation, 6),
            "order_value":    round(order_value, 0),
        }

    # ═════════════════════════════════════════════════════════════════════
    # Helpers
    # ═════════════════════════════════════════════════════════════════════

    @staticmethod
    def _empty_estimate(order_value, adv, asset_class) -> ImpactEstimate:
        return ImpactEstimate(
            order_value_krw=order_value, adv_krw=adv,
            participation_rate=0, asset_class=asset_class,
            alpha=0, daily_volatility=0,
            permanent_impact_bps=0, temporary_impact_bps=0,
            total_impact_bps=0, total_impact_pct=0,
            estimated_cost_krw=0,
        )

    @staticmethod
    def _empty_portfolio_response(equity) -> dict:
        return {
            "available": True, "n_orders": 0,
            "total_order_value_krw": 0,
            "total_cost_krw": 0, "total_cost_pct": 0,
            "weighted_avg_impact_bps": 0,
            "by_order": [],
        }
