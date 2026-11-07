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

#: ★교정치의 출처 (P9 ②)★ α 와 임계값이 **어디서 왔는가**.
#:
#: 위 표의 수는 하드코딩이고 이 저장소 어디에도 그것을 잰 기록이 없다. 그런데
#: `ImpactEstimate.alpha` 로 나가면 교정된 수처럼 보인다 — CLAUDE.md §4 가
#: 금지하는 "경제 가정을 지어내기" 의 조용한 판본이다. ★수치는 그대로 두고
#: 출처만 적는다★: 등급은 `measured`(저장소에 측정이 있다) · `literature`
#: (문헌 관례) · `unmeasured`(미상) 셋이고, ★근거 없이 `measured` 를 쓰지
#: 않는다★(테스트가 건다). 언젠가 실제로 재면 그때 올린다.
#:
#: `threshold_basis` 가 `nominal_krw` 인 이유: 시총 임계값이 **명목 원화**라
#: 과거에 소급하면 같은 종목이 다른 티어로 밀린다(물가·지수 수준이 다르다).
_UNMEASURED = ("이 저장소에 이 α 를 잰 기록이 없습니다 — Almgren-Chriss √법칙의 "
               "관례적 크기 순서를 따른 값이고, 대형→소형으로 커지는 **순서**는 "
               "유동성 논리와 맞지만 각 수준은 측정치가 아닙니다.")
TIER_PROVENANCE: dict[str, dict] = {
    tier: {"alpha": "unmeasured", "reason": _UNMEASURED,
           "threshold_basis": "nominal_krw"}
    for tier in ASSET_CLASS_TIERS
}

#: 표에 없는 자산군이 왔을 때 쓰는 α. ★표의 값이 아니다★ — 그래서 산출이
#: `alpha_source` 로 그 사실을 말한다(예전에는 조용히 교정치처럼 나갔다).
UNKNOWN_CLASS_ALPHA = 1.0

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

    #: ★이 α 가 어디서 왔는가★ `tier_table`(표) · `fallback_unknown_class`
    #: (표에 없는 자산군) · `unavailable`(계산 불가라 0 — "충격 없음" 이 아니라
    #: **미상**이다). 기본값을 둬 기존 위치 생성 호출을 깨지 않는다.
    alpha_source:           str = "tier_table"


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
        # ★조용히 버리지 않는다 (P9 ②)★ 오타 하나가 아무 말 없이 사라지면
        # 호출자는 자기가 준 교정치로 계산됐다고 믿는다.
        ignored: list[str] = []
        if custom_alpha:
            for k, v in custom_alpha.items():
                if k in self.alpha_map:
                    threshold, _ = self.alpha_map[k]
                    self.alpha_map[k] = (threshold, v)
                else:
                    ignored.append(k)
        self.ignored_custom_alpha: tuple[str, ...] = tuple(ignored)
        if ignored:
            logger.warning(
                "custom_alpha 에 표에 없는 티어가 있어 무시했습니다: %s "
                "(쓸 수 있는 티어: %s)", ignored, sorted(self.alpha_map))

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

        # ★폴백을 교정치로 위장하지 않는다 (P9 ②)★ 수치 동작은 그대로
        # (표에 없으면 α=1.0)이되, 그것이 표의 값이 아님을 산출이 말한다.
        if asset_class in self.alpha_map:
            alpha, alpha_source = self.alpha_map[asset_class][1], "tier_table"
        else:
            alpha, alpha_source = UNKNOWN_CLASS_ALPHA, "fallback_unknown_class"

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
            alpha_source=alpha_source,
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
            # ★0 은 측정이 아니라 미상이다★ 거래대금이나 주문이 0 이면 참여율을
            # 세울 수 없다. "충격이 없다" 로 읽히면 공짜 거래를 제조하게 된다.
            alpha_source="unavailable",
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


# ═══════════════════════════════════════════════════════════════════════════════
# ImpactAssumptions — ★백테스트에 규모를 들여오는 유일한 문★ (P3)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ImpactAssumptions:
    """참여율 충격을 쓰기 위해 **선언해야 하는** 가정.

    ★`portfolio_krw` 에 기본값을 두지 않는 것이 계약이다★ `walk_forward` 의
    `equity` 는 1.0 에서 시작하는 단위 정규화라 KRW notional 이 없다. 참여율에는
    규모가 필요한데, 임의의 기본값을 하나 고르면 **그 하나의 가정이 주 통계를
    5~17% 움직인다** — 정당화할 근거가 없다. 그래서 규모는 묻지 않고 정하지
    않는다. 쓰려면 말해야 한다.

    ★생성자 검증이 침묵 폴백 가드다★ `turnover_based_impact` 는 `avg_adv_krw
    <= 0` 이면 조용히 `{"impact_bps": 0}` 을 돌려준다 — **공짜 거래를
    제조한다**. 그 함수는 `realism_engine`·`instrument_selector` 가 쓰고 있으므로
    건드리지 않고, 이 경계에서 막아 그 경로에 도달할 수 없게 한다.
    """

    portfolio_krw: float
    adv_krw: float = 50_000_000_000.0     # KOSPI 평균 약 500억 (realism_engine 관례)
    volatility: float = 0.018
    alpha: float = 0.7                    # 포트폴리오 가중 α (대형주 위주)

    def __post_init__(self) -> None:
        if not (float(self.portfolio_krw) > 0):
            raise ValueError(
                f"포트폴리오 규모는 양수여야 합니다 — 받은 값 {self.portfolio_krw}. "
                "규모를 모르면 참여율을 모르므로 충격을 지어내지 않습니다.")
        if not (float(self.adv_krw) > 0):
            raise ValueError(
                f"ADV 는 양수여야 합니다 — 받은 값 {self.adv_krw}. "
                "ADV 가 미상이면 충격은 0 이 아니라 ★미상★ 입니다.")
        if float(self.volatility) < 0:
            raise ValueError(f"변동성은 음수일 수 없습니다 — 받은 값 {self.volatility}")
        if float(self.alpha) < 0:
            raise ValueError(f"α 는 음수일 수 없습니다 — 받은 값 {self.alpha}")

    def as_convention(self) -> dict:
        """★가정이 산출과 함께 다닌다★ (P1 `risk_adjusted_ratios`·P2′ `bl_solve` 패턴).

        `impact_bps_resolution` 을 신고하는 이유: `turnover_based_impact` 는
        `round(impact_bps, 2)` 로 0.01bp 해상도를 갖는다. P1 에서 `round(sharpe,
        2)` 가 비용 5~100bps 를 통째로 눈멀게 한 전례가 있으므로, 해상도가 효과
        (규모 간 차이 8.5bp)의 1/850 이라 여기서는 문제가 아니라는 논증이
        **리포트 안에서** 확인 가능해야 한다.
        """
        return {
            "portfolio_krw": float(self.portfolio_krw),
            "adv_krw": float(self.adv_krw),
            "volatility": float(self.volatility),
            "alpha": float(self.alpha),
            # ★가정이 산출과 함께 다닌다 (P9 ②)★ 이 α 는 포트폴리오 가중
            # 대표값이고 티어 표와 같은 출처를 갖는다 — 재 본 적이 없다.
            # 값이 아니라 **등급**을 실어야 소비자가 승격 근거로 오해하지 않는다.
            "alpha_provenance": "unmeasured",
            "alpha_provenance_reason": _UNMEASURED,
            "law": "almgren_chriss_sqrt",
            "adv_basis": "portfolio_average",   # ★종목별 ADV 가 아니다★
            "impact_bps_resolution": 0.01,
        }

    def impact_bps(self, turnover: float, notional_krw: float) -> dict:
        """편도 회전율(분수)과 KRW notional → 충격 추정.

        ★√법칙을 여기서 다시 계산하지 않는다★ 저장소가 이미 가진 모델을 부른다 —
        베끼면 두 벌이 갈라지고, 갈라져도 타입 에러가 나지 않는다(P1·P2′ 에서
        두 번 물린 형태). `turnover_pct` 단위(%)는 `realism_engine` 호출부와
        같게 맞춘다.
        """
        d = MarketImpactModel.turnover_based_impact(
            turnover_pct=float(turnover) * 100.0,
            portfolio_equity=float(notional_krw),
            avg_adv_krw=float(self.adv_krw),
            avg_volatility=float(self.volatility),
            weighted_alpha=float(self.alpha),
        )
        return {
            "impact_bps": float(d.get("impact_bps") or 0.0),
            "participation": float(d.get("participation") or 0.0),
            "cost_pct": float(d.get("cost_pct") or 0.0),
            "order_value_krw": float(d.get("order_value") or 0.0),
        }
