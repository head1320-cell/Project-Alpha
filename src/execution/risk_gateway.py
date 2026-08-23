"""
Risk Gateway — Pre-Trade 2-Tier Risk Checks
=================================================
모든 주문은 다음 2단계 검증을 통과해야 함:

Tier 1: Static Rules (빠른 거부)
  ① 시장 시간 (09:00-15:30 KST)
  ② Daily Turnover Limit (자본의 200%)
  ③ Position Size Limit (전략당 자본의 30%)
  ④ Universe Whitelist (등록 종목만)
  ⑤ Min Order Value (1만원 미만 거부)

Tier 2: Dynamic Rules (Stage 12 통합)
  ⑥ Buying Power (Stage 12 BuyingPowerValidator)
  ⑦ Market Impact Warning (Stage 12 MarketImpactModel)
  ⑧ Regime-Adaptive Mode (Stage 9 risk_score)
  ⑨ Drawdown Circuit Breaker (-5% 일중, -10% 누적)
  ⑩ Concentration Risk (단일 종목 자본의 20% 이상)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# 한국 시장 시간
KST = ZoneInfo("Asia/Seoul")
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RiskLimits:
    """기관급 안전 한도. 초기값은 보수적으로."""
    # Tier 1
    daily_turnover_pct:         float = 2.0    # 자본의 200%
    position_size_max_pct:      float = 0.30   # 단일 전략 30%
    min_order_value_krw:        float = 10_000

    # Tier 2
    concentration_limit_pct:    float = 0.20   # 단일 종목 20%
    daily_loss_limit_pct:       float = 0.05   # 일중 -5% 발생 시 차단
    cumulative_dd_limit_pct:    float = 0.10   # 누적 -10% 발생 시 차단
    market_impact_warn_bps:     float = 50     # 50bp 초과 시 경고
    market_impact_reject_bps:   float = 200    # 200bp 초과 시 거부
    regime_defensive_max_value: float = 0.5    # PANIC 시 매수 주문 50% 한도


@dataclass
class RiskCheckResult:
    """위험 검증 결과."""
    check_id:        str
    approved:        bool
    rejected_reason: str | None = None
    warnings:        list = field(default_factory=list)
    adjustments:     dict = field(default_factory=dict)
    tier_failures:   list = field(default_factory=list)
    checks_passed:   list = field(default_factory=list)
    metadata:        dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# RiskGateway
# ═══════════════════════════════════════════════════════════════════════════════

class RiskGateway:
    """
    주문 발주 전 모든 안전 검증을 통과해야 통과.

    Usage:
        gw = RiskGateway(engine, limits=RiskLimits(), universe={"005930", "000660"})

        result = gw.check(
            order={
              "ticker": "005930", "side": "BUY",
              "quantity": 100, "price": 70000, "strategy_id": 1,
            },
            account_state={
              "equity_krw":          100_000_000,
              "cash_krw":            30_000_000,
              "positions":           {...},
              "daily_turnover_krw":  50_000_000,
              "current_drawdown_pct": -0.03,
              "cumulative_dd_pct":   -0.07,
            },
            regime_state={
              "regime": "STAGFLATION",
              "systemic_risk_score": 65,
              "mode": "cautious",
            },
        )

        if result.approved:
            # 발주 진행
            ...
        else:
            # 거부 사유 audit_trail에 기록
            ...
    """

    def __init__(
        self,
        engine=None,
        limits: RiskLimits | None = None,
        universe: set | None = None,
        bypass_market_hours: bool = False,
    ):
        self.engine = engine
        self.limits = limits or RiskLimits()
        self.universe = universe or set()
        self.bypass_market_hours = bypass_market_hours

        # Stage 12 modules (lazy import)
        self._impact_model = None
        self._buying_power = None

    # ═════════════════════════════════════════════════════════════════════
    # 메인 진입점
    # ═════════════════════════════════════════════════════════════════════

    def check(
        self,
        order: dict,
        account_state: dict,
        regime_state: dict | None = None,
    ) -> RiskCheckResult:
        """단일 주문 위험 검증."""
        check_id = f"RGW-{uuid.uuid4().hex[:10]}"
        result = RiskCheckResult(check_id=check_id, approved=True)

        # Tier 1 — Static
        tier1_ok = self._tier1_static_checks(order, account_state, result)

        # Tier 1에서 거부되면 Tier 2 skip
        if not tier1_ok:
            result.approved = False
            return result

        # Tier 2 — Dynamic
        self._tier2_dynamic_checks(order, account_state, regime_state, result)

        if result.tier_failures:
            result.approved = False
            result.rejected_reason = "; ".join(result.tier_failures)

        return result

    # ═════════════════════════════════════════════════════════════════════
    # Tier 1: Static
    # ═════════════════════════════════════════════════════════════════════

    def _tier1_static_checks(self, order, state, result) -> bool:
        """5가지 정적 검증."""
        passed_all = True

        # ① 시장 시간
        if not self.bypass_market_hours:
            if not self._is_market_open():
                result.tier_failures.append("Tier1: 장 외 시간 (09:00-15:30 KST)")
                passed_all = False
            else:
                result.checks_passed.append("market_hours")
        else:
            result.checks_passed.append("market_hours (bypassed)")

        # ② Daily turnover limit
        order_value = order["quantity"] * order["price"]
        daily_turnover = state.get("daily_turnover_krw", 0)
        equity = state.get("equity_krw", 1)
        max_turnover = equity * self.limits.daily_turnover_pct

        if daily_turnover + order_value > max_turnover:
            result.tier_failures.append(
                f"Tier1: Daily turnover 한도 초과 "
                f"({(daily_turnover + order_value)/equity:.1%} > {self.limits.daily_turnover_pct:.0%})"
            )
            passed_all = False
        else:
            result.checks_passed.append("daily_turnover")

        # ③ Position size limit (per strategy)
        if order["side"] == "BUY":
            strategy_id = order.get("strategy_id")
            current_strategy_value = self._strategy_position_value(
                state.get("positions", {}), strategy_id,
            )
            after_buy = current_strategy_value + order_value
            max_position = equity * self.limits.position_size_max_pct
            if after_buy > max_position:
                result.tier_failures.append(
                    f"Tier1: 전략 {strategy_id} position 한도 초과 "
                    f"({after_buy/equity:.1%} > {self.limits.position_size_max_pct:.0%})"
                )
                passed_all = False
            else:
                result.checks_passed.append("position_size")

        # ④ Universe whitelist
        if self.universe and order["ticker"] not in self.universe:
            result.tier_failures.append(
                f"Tier1: 종목 {order['ticker']} universe 미등록"
            )
            passed_all = False
        else:
            result.checks_passed.append("universe")

        # ⑤ Min order value
        if order_value < self.limits.min_order_value_krw:
            result.tier_failures.append(
                f"Tier1: 주문 금액 {order_value:,.0f}원 < 최소 {self.limits.min_order_value_krw:,.0f}원"
            )
            passed_all = False
        else:
            result.checks_passed.append("min_value")

        return passed_all

    # ═════════════════════════════════════════════════════════════════════
    # Tier 2: Dynamic (Stage 12 통합)
    # ═════════════════════════════════════════════════════════════════════

    def _tier2_dynamic_checks(self, order, state, regime_state, result):
        """5가지 동적 검증 (Stage 12 통합)."""

        # ⑥ Buying Power
        if order["side"] == "BUY":
            order_value = order["quantity"] * order["price"]
            available = state.get("cash_krw", 0)
            if order_value > available:
                result.tier_failures.append(
                    f"Tier2: 가용 현금 부족 (필요 {order_value:,.0f} / 보유 {available:,.0f})"
                )
            else:
                result.checks_passed.append("buying_power")

        # ⑦ Market Impact (경고 또는 거부)
        impact_check = self._check_market_impact(order, state)
        if impact_check["status"] == "reject":
            result.tier_failures.append(
                f"Tier2: Market impact {impact_check['impact_bps']:.1f}bp "
                f"> 거부 한도 {self.limits.market_impact_reject_bps}bp"
            )
        elif impact_check["status"] == "warn":
            result.warnings.append(
                f"Market impact 경고: {impact_check['impact_bps']:.1f}bp "
                f"(잠재 비용 ~{impact_check['cost_krw']:,.0f}원)"
            )
            result.metadata["market_impact_bps"] = impact_check["impact_bps"]
            result.checks_passed.append("market_impact (with warning)")
        else:
            result.checks_passed.append("market_impact")

        # ⑧ Regime-Adaptive
        if regime_state:
            regime = regime_state.get("regime", "NORMAL")
            risk_score = regime_state.get("systemic_risk_score", 0) or 0
            mode = regime_state.get("mode", "normal")

            if mode == "defensive" or risk_score >= 70:
                if order["side"] == "BUY":
                    order_value = order["quantity"] * order["price"]
                    equity = state.get("equity_krw", 1)
                    max_in_defensive = equity * self.limits.regime_defensive_max_value
                    current_position_value = sum(
                        p.get("eval_amount", 0)
                        for p in state.get("positions", {}).values()
                    )
                    if current_position_value + order_value > max_in_defensive:
                        result.tier_failures.append(
                            f"Tier2: Defensive mode (risk={risk_score:.0f}) "
                            f"→ 매수 한도 {self.limits.regime_defensive_max_value:.0%} 초과"
                        )
                    else:
                        result.warnings.append(
                            f"Defensive mode (regime={regime}) — 신중한 진입"
                        )
                        result.checks_passed.append("regime_adaptive (defensive)")
                else:
                    result.checks_passed.append("regime_adaptive (sell allowed)")
            else:
                result.checks_passed.append("regime_adaptive")

        # ⑨ Drawdown Circuit Breaker
        intraday_dd = abs(state.get("current_drawdown_pct", 0) or 0)
        cumul_dd = abs(state.get("cumulative_dd_pct", 0) or 0)

        if intraday_dd >= self.limits.daily_loss_limit_pct:
            result.tier_failures.append(
                f"Tier2: 일중 손실 한도 도달 ({intraday_dd:.1%} >= {self.limits.daily_loss_limit_pct:.0%})"
            )
        elif cumul_dd >= self.limits.cumulative_dd_limit_pct:
            result.tier_failures.append(
                f"Tier2: 누적 drawdown 한도 도달 ({cumul_dd:.1%} >= {self.limits.cumulative_dd_limit_pct:.0%})"
            )
        else:
            result.checks_passed.append("circuit_breaker")

        # ⑩ Concentration Risk
        if order["side"] == "BUY":
            ticker = order["ticker"]
            order_value = order["quantity"] * order["price"]
            current_ticker_value = state.get("positions", {}).get(ticker, {}).get("eval_amount", 0)
            equity = state.get("equity_krw", 1)
            new_ticker_pct = (current_ticker_value + order_value) / equity
            if new_ticker_pct > self.limits.concentration_limit_pct:
                result.tier_failures.append(
                    f"Tier2: 종목 집중도 한도 ({ticker}: "
                    f"{new_ticker_pct:.1%} > {self.limits.concentration_limit_pct:.0%})"
                )
            else:
                result.checks_passed.append("concentration")

    # ═════════════════════════════════════════════════════════════════════
    # Helpers
    # ═════════════════════════════════════════════════════════════════════

    @staticmethod
    def _is_market_open() -> bool:
        """현재 한국 시장 개장 중인지."""
        now = datetime.now(KST)
        # 주말 제외
        if now.weekday() >= 5:
            return False
        # 시간 체크
        t = now.time()
        return MARKET_OPEN <= t <= MARKET_CLOSE

    @staticmethod
    def _strategy_position_value(positions: dict, strategy_id) -> float:
        """특정 전략의 현재 포지션 평가액."""
        total = 0
        for p in positions.values():
            if p.get("strategy_id") == strategy_id:
                total += p.get("eval_amount", 0)
        return total

    def _check_market_impact(self, order, state) -> dict:
        """Stage 12 MarketImpactModel로 영향 추정."""
        try:
            if self._impact_model is None:
                from src.engine.market_impact import MarketImpactModel
                self._impact_model = MarketImpactModel()

            adv_krw = state.get("ticker_adv_krw", {}).get(
                order["ticker"], 50_000_000_000
            )
            volatility = state.get("ticker_volatility", {}).get(
                order["ticker"], 0.018
            )
            order_value = order["quantity"] * order["price"]

            est = self._impact_model.estimate_impact(
                order_value_krw=order_value,
                adv_krw=adv_krw,
                daily_volatility=volatility,
                asset_class="kospi_mid",
                side=order["side"],
            )

            impact_bps = est.total_impact_bps
            cost_krw = est.estimated_cost_krw

            if impact_bps >= self.limits.market_impact_reject_bps:
                return {"status": "reject", "impact_bps": impact_bps, "cost_krw": cost_krw}
            elif impact_bps >= self.limits.market_impact_warn_bps:
                return {"status": "warn", "impact_bps": impact_bps, "cost_krw": cost_krw}
            return {"status": "ok", "impact_bps": impact_bps, "cost_krw": cost_krw}
        except Exception as e:
            logger.warning(f"Market impact 추정 실패: {e}")
            return {"status": "ok", "impact_bps": 0, "cost_krw": 0}
