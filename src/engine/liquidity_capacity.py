"""
Liquidity Capacity Constraint — 전략별 수용량 한계
=========================================================
HRP는 변동성 낮은 전략에 큰 자본 배분. 그러나 '소형주 가치' 전략에 자본 40% 배분하면
호가창을 다 잡아먹어 자기 알파를 파괴 (capacity-induced alpha decay).

각 전략의 수용량 = 그 전략이 거래하는 종목들의 일일 거래대금에 의해 제약됨.

공식:
  strategy_capacity_krw = Σᵢ (ADVᵢ × max_pct_of_adv × holding_period_days)

대형주 위주 전략: 수십조원 수용 가능
소형주/코스닥 전략: 수백억원 한계

본 모듈 출력은 Stage 10 allocator에 다음과 같이 통합:
  1. HRP 가중치 계산
  2. each strategy: weight × portfolio_value ≤ capacity → OK
  3. 초과하는 전략은 capacity에서 cap → 잔여분 다른 전략에 재분배
  4. 모든 전략이 cap에 도달하면 forced cash buffer
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CapacityConfig:
    """전략별 수용량 산정 파라미터."""
    max_pct_of_adv:       float = 0.05    # 일일 ADV의 5% 한도
    holding_period_days:  int = 5         # 평균 보유 기간
    safety_buffer:        float = 0.7     # 추가 안전 마진 (capacity의 70%만 사용)


# ═══════════════════════════════════════════════════════════════════════════════
# LiquidityCapacityEstimator
# ═══════════════════════════════════════════════════════════════════════════════

class LiquidityCapacityEstimator:
    """
    전략별 수용량 추정.

    Usage:
        estimator = LiquidityCapacityEstimator(engine)

        # 1. 전략별 capacity 추정
        capacities = estimator.estimate_capacities(
            strategy_ids=[1, 2, 3],
            as_of_date="2024-12-31",
        )
        # → {1: 50_000_000_000, 2: 10_000_000_000, 3: 200_000_000_000}

        # 2. HRP 가중치에 적용
        adjusted = estimator.apply_capacity_to_weights(
            weights={1: 0.4, 2: 0.4, 3: 0.2},
            capacities=capacities,
            total_capital=100_000_000_000,
        )
    """

    def __init__(self, engine, config: CapacityConfig | None = None):
        self.engine = engine
        self.config = config or CapacityConfig()

    # ═════════════════════════════════════════════════════════════════════
    # 전략 capacity 추정
    # ═════════════════════════════════════════════════════════════════════

    def estimate_strategy_capacity(
        self,
        strategy_id: int,
        as_of_date: str,
        lookback_days: int = 60,
    ) -> dict:
        """
        단일 전략의 수용량 추정.

        방법:
          1. 전략이 거래한 종목 목록 조회 (최근 trades 또는 holdings)
          2. 각 종목의 평균 ADV 계산 (벤치마크 prices에서)
          3. capacity = Σ (ADV × max_pct × holding_period) × safety_buffer

        Returns:
            {
              "strategy_id": int,
              "capacity_krw": float,
              "n_universe_tickers": int,
              "avg_adv_krw": float,
              "available": bool,
            }
        """
        if not self.engine:
            return self._fallback_capacity(strategy_id)

        try:
            # 전략의 universe (종목 목록) — strategies 테이블의 graph_json 참조
            # 또는 trades 테이블에서 최근 거래 종목 추출
            with self.engine.connect() as conn:
                # graph_json에서 ticker 추출 시도
                row = conn.execute(text(
                    "SELECT graph_json FROM strategies WHERE id = :sid"
                ), {"sid": strategy_id}).fetchone()
                if not row:
                    return self._fallback_capacity(strategy_id)

                graph = row._mapping["graph_json"]
                tickers = self._extract_tickers_from_graph(graph)

                if not tickers:
                    return self._fallback_capacity(strategy_id)

                # 각 ticker의 평균 거래대금 (close × volume)
                advs = []
                for ticker in tickers[:30]:    # 최대 30개 종목
                    adv_row = conn.execute(text("""
                        SELECT AVG(close * volume) as adv
                        FROM benchmark_prices
                        WHERE ticker = :t
                          AND trade_date <= :d
                          AND trade_date >= date(:d, :lb)
                    """), {"t": ticker, "d": as_of_date, "lb": f"-{lookback_days} days"}).fetchone()
                    if adv_row and adv_row._mapping["adv"]:
                        advs.append(float(adv_row._mapping["adv"]))

                if not advs:
                    return self._fallback_capacity(strategy_id)

                avg_adv = float(np.mean(advs))
                n_tickers = len(advs)

                # capacity = Σᵢ (ADVᵢ × max_pct × holding_period) × safety_buffer
                total_capacity = sum(advs) * self.config.max_pct_of_adv \
                                  * self.config.holding_period_days \
                                  * self.config.safety_buffer

                return {
                    "strategy_id":         strategy_id,
                    "capacity_krw":        round(total_capacity, 0),
                    "n_universe_tickers":  n_tickers,
                    "avg_adv_krw":         round(avg_adv, 0),
                    "max_pct_of_adv":      self.config.max_pct_of_adv,
                    "holding_period_days": self.config.holding_period_days,
                    "available":           True,
                }
        except Exception as e:
            logger.warning(f"Capacity estimation failed for sid={strategy_id}: {e}")
            return self._fallback_capacity(strategy_id)

    def estimate_capacities(
        self, strategy_ids: list[int], as_of_date: str,
    ) -> dict:
        """여러 전략의 capacity 일괄 추정."""
        return {
            sid: self.estimate_strategy_capacity(sid, as_of_date)
            for sid in strategy_ids
        }

    # ═════════════════════════════════════════════════════════════════════
    # 가중치에 capacity 적용
    # ═════════════════════════════════════════════════════════════════════

    def apply_capacity_to_weights(
        self,
        weights: dict,
        capacities: dict,
        total_capital: float,
    ) -> dict:
        """
        HRP 가중치 → capacity 적용 → 재정규화.

        알고리즘:
          1. each strategy: desired_value = weight × total_capital
          2. if desired_value > capacity: cap → 잔여 = desired - capacity
          3. 잔여를 capacity 여유 있는 전략들에 비례 분배
          4. 모두 cap에 도달 시 cash_buffer로 보관

        Args:
            weights:        {sid: weight_pct}
            capacities:     {sid: {"capacity_krw": float, ...}}
            total_capital:  전체 운영 자본 KRW

        Returns:
            {
              "adjusted_weights":    {sid: weight},
              "cash_buffer_pct":     0~1,
              "capacity_utilization": {sid: 사용/capacity},
              "capped_strategies":   [...],
              "reallocations":       [...],
            }
        """
        if not weights or total_capital <= 0:
            return self._empty_adjust(weights)

        adjusted = {}
        capped_sids = []
        unused_capacity = {}     # 여유분이 있는 전략들

        for sid, w in weights.items():
            desired_value = w * total_capital
            cap_info = capacities.get(sid) or capacities.get(int(sid))
            if not cap_info or not cap_info.get("available"):
                # capacity 정보 없음 → 그대로 사용
                adjusted[sid] = w
                continue

            capacity_krw = cap_info.get("capacity_krw", 0)
            if capacity_krw <= 0:
                adjusted[sid] = w
                continue

            if desired_value > capacity_krw:
                # Cap 적용
                actual_value = capacity_krw
                actual_weight = actual_value / total_capital
                adjusted[sid] = actual_weight
                capped_sids.append({
                    "sid":              sid,
                    "desired_weight":   round(w, 4),
                    "capped_weight":    round(actual_weight, 4),
                    "lost_weight":      round(w - actual_weight, 4),
                    "capacity_krw":     capacity_krw,
                    "desired_value_krw": round(desired_value, 0),
                })
            else:
                # 여유 있음
                adjusted[sid] = w
                unused_capacity[sid] = (capacity_krw - desired_value) / total_capital

        # 잔여 weight 합산
        total_weight = sum(adjusted.values())
        excess = 1.0 - total_weight

        reallocations = []
        if excess > 0.001 and unused_capacity:
            # 여유 있는 전략들에 비례 분배
            total_unused = sum(unused_capacity.values())
            if total_unused > 0:
                redistributable = min(excess, total_unused)
                for sid, free_capacity_pct in unused_capacity.items():
                    add = redistributable * (free_capacity_pct / total_unused)
                    adjusted[sid] += add
                    reallocations.append({
                        "sid": sid, "added_weight": round(add, 4),
                    })
                excess -= redistributable

        # 마지막 잔여는 cash_buffer
        cash_buffer = max(0, excess)

        # 활용률 계산
        utilization = {}
        for sid, w in adjusted.items():
            cap_info = capacities.get(sid) or capacities.get(int(sid))
            if cap_info and cap_info.get("available") and cap_info.get("capacity_krw", 0) > 0:
                utilization[sid] = round(
                    (w * total_capital) / cap_info["capacity_krw"], 3
                )

        return {
            "adjusted_weights":      adjusted,
            "cash_buffer_pct":       round(cash_buffer, 4),
            "capacity_utilization":  utilization,
            "capped_strategies":     capped_sids,
            "reallocations":         reallocations,
            "total_capital_krw":     total_capital,
        }

    # ═════════════════════════════════════════════════════════════════════
    # Helpers
    # ═════════════════════════════════════════════════════════════════════

    @staticmethod
    def _extract_tickers_from_graph(graph_json) -> list[str]:
        """전략 graph_json에서 ticker 목록 추출."""
        import json
        try:
            if isinstance(graph_json, str):
                graph = json.loads(graph_json)
            else:
                graph = graph_json or {}

            tickers = set()
            for node in graph.get("nodes", []):
                # 다양한 node type에서 ticker 추출 시도
                params = node.get("params", {}) or node.get("data", {})
                for key in ["ticker", "symbol", "universe", "tickers"]:
                    val = params.get(key)
                    if val:
                        if isinstance(val, list):
                            tickers.update(str(v) for v in val)
                        elif isinstance(val, str):
                            tickers.add(val)
            return sorted(tickers)
        except Exception:
            return []

    @staticmethod
    def _fallback_capacity(sid) -> dict:
        """capacity 추정 실패 시 무한대 가정 (제약 없음)."""
        return {
            "strategy_id":         sid,
            "capacity_krw":        float("inf"),
            "n_universe_tickers":  0,
            "avg_adv_krw":         0,
            "available":           False,
            "message":             "capacity 데이터 부족 — 무제약 가정",
        }

    @staticmethod
    def _empty_adjust(weights) -> dict:
        return {
            "adjusted_weights":     weights,
            "cash_buffer_pct":      0,
            "capacity_utilization": {},
            "capped_strategies":    [],
            "reallocations":        [],
        }
