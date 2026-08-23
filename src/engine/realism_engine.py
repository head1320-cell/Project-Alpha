"""
Stage 12 Production Realism Patch
=====================================
Stage 11의 MultiStrategyBacktester에 5가지 위험 통제 hook을 적용하는 wrapping 모듈.

기존 코드를 수정하지 않고 monkey-patch 형태로 확장:
  - BacktestConfig 확장 (RealismConfig)
  - 시뮬레이션 루프에 5단계 hook 주입
  - 결과에 5종 추가 분해 (capacity_loss / impact_cost / cash_yield / ppc_truncation / regime_adj)

Usage:
    from src.engine.realism_engine import RealisticBacktester, RealismConfig

    bt = RealisticBacktester(engine)
    config = RealismConfig(
        strategy_ids=[1, 2, 3],
        start_date="2023-01-01", end_date="2024-12-31",
        # ─ 새 옵션 ─
        enable_market_impact=True,
        enable_cash_yield=True,
        enable_buying_power_check=True,
        enable_capacity_constraint=True,
        enable_regime_adaptive=True,
        # 미세 조정
        avg_adv_krw=50_000_000_000,
        weighted_alpha=0.7,
        max_pct_of_adv=0.05,
    )
    result = bt.run(config)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# RealismConfig — Stage 11 BacktestConfig + 5가지 토글
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RealismConfig:
    # Stage 11 기존 옵션
    strategy_ids:           list[int] = field(default_factory=list)
    start_date:             str = ""
    end_date:               str = ""
    initial_capital:        float = 1_000_000
    allocation_method:      str = "hrp_macro"
    rebalance_policy:       str = "monthly"
    netting_enabled:        bool = True
    macro_overlay_enabled:  bool = True
    commission_rate:        float = 0.00015
    slippage_rate:          float = 0.0005
    lookback_days:          int = 252
    max_weight:             float = 0.50
    min_weight:             float = 0.02
    run_name:               str | None = None

    # ─ Stage 12 신규 토글 ──────────────────────────────────────────────
    enable_market_impact:        bool = True
    enable_cash_yield:           bool = True
    enable_buying_power_check:   bool = True
    enable_capacity_constraint:  bool = False  # 종목 정보 필요해 기본 OFF
    enable_regime_adaptive:      bool = True

    # ─ 파라미터 ─
    avg_adv_krw:                 float = 50_000_000_000   # 평균 ADV 가정
    weighted_alpha:              float = 0.7              # 가중 α (대형주 위주)
    max_pct_of_adv:              float = 0.05
    holding_period_days:         int = 5
    default_rf_annual:           float = 0.035
    cash_floor:                  float = 0.0
    cautious_risk_threshold:     float = 50.0
    defensive_risk_threshold:    float = 70.0
    defensive_hard_cap:          float = 0.30
    defensive_cash_buffer:       float = 0.30


# ═══════════════════════════════════════════════════════════════════════════════
# RealisticBacktester
# ═══════════════════════════════════════════════════════════════════════════════

class RealisticBacktester:
    """
    Stage 11 MultiStrategyBacktester에 5가지 realism hook을 적용한 wrapping 클래스.

    Stage 11 코드를 import하여 base로 사용하고, _simulate 메서드만 override.
    """

    def __init__(self, db_engine):
        self.engine = db_engine

        # Stage 11 base
        from src.engine.multi_strategy_backtest import (
            BacktestConfig,
            DailyRecord,
            MultiStrategyBacktester,
        )
        self.BacktestConfig = BacktestConfig
        self.DailyRecord = DailyRecord
        self.base = MultiStrategyBacktester(db_engine)

        # Stage 12 modules
        from src.engine.cash_management import BuyingPowerValidator, CashRateProvider, CashYieldCalculator
        from src.engine.liquidity_capacity import LiquidityCapacityEstimator
        from src.engine.market_impact import MarketImpactModel
        from src.engine.regime_adaptive_allocator import RegimeAdaptiveAllocator

        self.impact_model = MarketImpactModel()
        self.rate_provider = CashRateProvider(db_engine)
        self.cash_calc = CashYieldCalculator(self.rate_provider)
        self.buying_power = BuyingPowerValidator()
        self.capacity_estimator = LiquidityCapacityEstimator(db_engine)
        self.adaptive_allocator = RegimeAdaptiveAllocator(self.base.allocator)

    # ═════════════════════════════════════════════════════════════════════
    # 메인 진입점
    # ═════════════════════════════════════════════════════════════════════

    def run(self, config: RealismConfig) -> dict:
        """5가지 hook이 적용된 통합 백테스트 실행."""
        t_start = time.perf_counter()

        # Stage 11 config로 변환 (기본 검증 위해)
        bt_config = self.BacktestConfig(
            strategy_ids=config.strategy_ids,
            start_date=config.start_date, end_date=config.end_date,
            initial_capital=config.initial_capital,
            allocation_method=config.allocation_method,
            rebalance_policy=config.rebalance_policy,
            netting_enabled=config.netting_enabled,
            macro_overlay_enabled=config.macro_overlay_enabled,
            commission_rate=config.commission_rate,
            slippage_rate=config.slippage_rate,
            lookback_days=config.lookback_days,
            max_weight=config.max_weight, min_weight=config.min_weight,
            run_name=config.run_name,
        )

        validation = self.base._validate_config(bt_config)
        if not validation["ok"]:
            return {"success": False, "message": validation["error"]}

        try:
            data = self.base._load_data(bt_config)
        except Exception as e:
            return {"success": False, "message": f"데이터 로드 실패: {e}"}

        if data["returns_matrix"].empty:
            return {"success": False, "message": "Returns matrix 비어있음"}

        # 시뮬레이션 — Stage 12 hook 적용
        try:
            daily_records, realism_stats = self._simulate_with_realism(config, bt_config, data)
        except Exception as e:
            logger.error(f"Realism simulation failed: {e}", exc_info=True)
            return {"success": False, "message": f"시뮬레이션 실패: {e}"}

        if not daily_records:
            return {"success": False, "message": "시뮬레이션 결과 없음"}

        # 요약 (Stage 11 메서드 활용)
        summary = self.base._compute_summary(daily_records, bt_config)
        summary["realism_adjustments"] = realism_stats

        duration = time.perf_counter() - t_start

        return {
            "success":             True,
            "config":              config.__dict__,
            "summary":             summary,
            "realism_stats":       realism_stats,
            "daily_records":       [self.base._record_to_dict(r) for r in daily_records],
            "strategy_names":      data["strategy_names"],
            "n_trading_days":      len(daily_records),
            "duration_seconds":    round(duration, 3),
        }

    # ═════════════════════════════════════════════════════════════════════
    # 핵심 시뮬레이션 (5 hook 적용)
    # ═════════════════════════════════════════════════════════════════════

    def _simulate_with_realism(
        self, config: RealismConfig, bt_config, data,
    ) -> tuple[list, dict]:
        """Stage 11 _simulate를 모방하되 5단계 hook 주입."""
        returns_matrix = data["returns_matrix"]
        strategies = data["strategies"]
        sids = config.strategy_ids

        rebalance_dates = self.base._compute_rebalance_dates(
            list(returns_matrix.index), config.rebalance_policy,
        )

        equity = config.initial_capital
        max_equity = equity
        n_str = len(sids)
        current_weights = {int(sid): 1.0/n_str for sid in sids}
        current_base_weights = current_weights.copy()
        current_macro_adj = {int(sid): 0.0 for sid in sids}
        current_regime = None
        current_systemic_risk = None
        current_cash_buffer = 0.0    # Stage 12: 적응형 모드에서 cash buffer

        daily_records = []

        # Stage 12 누적 통계
        stats = {
            "total_market_impact_cost":     0.0,   # 시장 충격 추가 비용
            "total_cash_yield":             0.0,   # 현금 이자 수익
            "total_buying_power_truncations": 0,    # PPC 컷오프 횟수
            "total_capacity_reallocations":  0,
            "regime_mode_days": {"normal": 0, "cautious": 0, "defensive": 0},
            "ewma_active_days":             0,
            "hard_cap_active_days":         0,
            "breakdown_detected_days":      0,
        }

        for t, date in enumerate(returns_matrix.index):
            rebalanced_today = False
            adaptive_mode = "normal"

            # ── 리밸런싱 ───────────────────────────────────────────────
            should_rebal = (
                date in rebalance_dates
                or (config.rebalance_policy == "regime_change" and current_regime is None)
            )

            if should_rebal and t > 0:
                past_returns = returns_matrix.iloc[:t]
                if len(past_returns) >= 20:
                    try:
                        # Stage 9 risk_score 조회 (PIT-safe)
                        risk_score = self._get_systemic_risk_pit(data["macro_df"], date)

                        # Hook ⑤: Regime-Adaptive Allocator
                        if config.enable_regime_adaptive:
                            alloc_result = self.adaptive_allocator.compute(
                                returns_matrix=past_returns,
                                method=config.allocation_method,
                                strategies=strategies,
                                as_of_date=str(date.date()),
                                lookback_days=config.lookback_days,
                                max_weight=config.max_weight,
                                min_weight=config.min_weight,
                                systemic_risk_score=risk_score,
                            )
                            adaptive_mode = alloc_result.get("adaptive_mode", "normal")
                            if alloc_result.get("ewma_applied"):
                                stats["ewma_active_days"] += 1
                            if alloc_result.get("hard_cap_applied"):
                                stats["hard_cap_active_days"] += 1
                            if alloc_result.get("breakdown_detected"):
                                stats["breakdown_detected_days"] += 1
                            current_cash_buffer = alloc_result.get("cash_buffer_pct", 0)
                        else:
                            alloc_result = self.base.allocator.compute(
                                returns_matrix=past_returns,
                                method=config.allocation_method,
                                strategies=strategies,
                                as_of_date=str(date.date()),
                                lookback_days=config.lookback_days,
                                max_weight=config.max_weight,
                                min_weight=config.min_weight,
                            )
                            current_cash_buffer = 0.0

                        if alloc_result.get("available"):
                            current_weights = {int(k): float(v) for k, v in alloc_result["weights"].items()}
                            current_base_weights = {int(k): float(v) for k, v in alloc_result.get("base_weights", {}).items()}
                            current_macro_adj = {int(k): float(v) for k, v in alloc_result.get("macro_adjustments", {}).items()}
                            current_regime = alloc_result.get("regime")
                            current_systemic_risk = alloc_result.get("systemic_risk_score") or risk_score
                            rebalanced_today = True

                            # Hook ①: Capacity Constraint
                            if config.enable_capacity_constraint:
                                capacities = self.capacity_estimator.estimate_capacities(
                                    sids, str(date.date()),
                                )
                                cap_adjusted = self.capacity_estimator.apply_capacity_to_weights(
                                    current_weights, capacities, equity,
                                )
                                current_weights = cap_adjusted["adjusted_weights"]
                                stats["total_capacity_reallocations"] += len(cap_adjusted["capped_strategies"])
                                current_cash_buffer = max(current_cash_buffer, cap_adjusted["cash_buffer_pct"])

                            # 누락된 sid 채우기
                            for sid in sids:
                                if int(sid) not in current_weights:
                                    current_weights[int(sid)] = 0.0
                                    current_base_weights[int(sid)] = 0.0
                                    current_macro_adj[int(sid)] = 0.0
                    except Exception as e:
                        logger.warning(f"{date.date()}: 리밸런싱 실패 {e}")

            # 모드 카운팅
            stats["regime_mode_days"][adaptive_mode] += 1

            # ── 일별 수익률 ─────────────────────────────────────────────
            day_returns = returns_matrix.iloc[t].to_dict()
            invested_ratio = sum(current_weights.values())

            # 그날 포트폴리오 수익률 (투자 부분만)
            portfolio_ret = sum(
                current_weights.get(int(sid), 0) * day_returns.get(sid, 0)
                for sid in sids
            )

            # Attribution
            alloc_diff = sum(
                (current_weights.get(int(sid), 0) - 1/n_str) * day_returns.get(sid, 0)
                for sid in sids
            )
            macro_effect = sum(
                current_macro_adj.get(int(sid), 0) * day_returns.get(sid, 0)
                for sid in sids
            )

            # ── 거래 비용 + Hook ② Market Impact ───────────────────────
            turnover = 0.0
            cost_effect = 0.0
            impact_cost = 0.0
            netting_savings = 0.0

            if rebalanced_today and t > 0:
                prev_w = daily_records[-1].weights if daily_records else current_weights
                turnover = sum(
                    abs(current_weights.get(int(sid), 0) - prev_w.get(int(sid), 0))
                    for sid in sids
                )
                # 선형 비용 (기본)
                total_rate = config.commission_rate + config.slippage_rate
                linear_cost = -turnover * total_rate

                # Hook ②: Market Impact (Square Root Law)
                if config.enable_market_impact and turnover > 0:
                    impact = self.impact_model.turnover_based_impact(
                        turnover_pct=turnover * 100,
                        portfolio_equity=equity,
                        avg_adv_krw=config.avg_adv_krw,
                        avg_volatility=0.018,
                        weighted_alpha=config.weighted_alpha,
                    )
                    impact_cost = -impact["cost_pct"]
                    stats["total_market_impact_cost"] += abs(impact_cost) * equity

                cost_effect = linear_cost + impact_cost

                # Hook ④: Buying Power Check (구매력 검증)
                if config.enable_buying_power_check:
                    # Net buy turnover 추정
                    weight_increases = sum(
                        max(0, current_weights.get(int(sid), 0) - prev_w.get(int(sid), 0))
                        for sid in sids
                    )
                    net_buy_value = weight_increases * equity
                    available_cash = (1 - sum(prev_w.values())) * equity + (
                        sum(max(0, prev_w.get(int(sid), 0) - current_weights.get(int(sid), 0)) for sid in sids) * equity
                    )
                    if net_buy_value > available_cash > 0:
                        # 컷오프 발생
                        scaling = available_cash / net_buy_value
                        (1 - scaling) * weight_increases
                        # 가중치 축소 (간단화)
                        for sid in current_weights:
                            if current_weights[sid] > prev_w.get(sid, 0):
                                diff = current_weights[sid] - prev_w.get(sid, 0)
                                current_weights[sid] = prev_w.get(sid, 0) + diff * scaling
                        stats["total_buying_power_truncations"] += 1

                # Netting 효과 (기존 Stage 11)
                if config.netting_enabled:
                    estimated_raw = turnover * 1.5
                    netting_savings = (estimated_raw - turnover) * total_rate * equity

            # ── Hook ③: Cash Yield ────────────────────────────────────
            cash_yield = 0.0
            if config.enable_cash_yield:
                cash_y = self.cash_calc.daily_yield(
                    invested_ratio=invested_ratio,
                    as_of_date=date,
                    cash_floor=config.cash_floor,
                )
                cash_yield = cash_y["cash_return_pct"]
                stats["total_cash_yield"] += cash_yield * equity

            # ── 최종 net return ──────────────────────────────────────
            net_return = portfolio_ret + cost_effect + cash_yield
            equity_new = equity * (1 + net_return)
            max_equity = max(max_equity, equity_new)
            drawdown = (equity_new / max_equity - 1) * 100
            cum_return = (equity_new / config.initial_capital - 1) * 100

            record = self.DailyRecord(
                date=date, portfolio_equity=equity_new,
                portfolio_return=net_return,
                cumulative_return=cum_return,
                drawdown_pct=drawdown,
                regime=current_regime,
                systemic_risk=current_systemic_risk,
                allocation_effect=alloc_diff, selection_effect=0,
                macro_effect=macro_effect,
                netting_effect=netting_savings/equity if equity > 0 else 0,
                cost_effect=cost_effect + cash_yield,
                num_trades=int(round(turnover * len(sids))) if rebalanced_today else 0,
                turnover_pct=turnover * 100,
                netting_savings=netting_savings, rebalanced=rebalanced_today,
                weights=current_weights.copy(),
                base_weights=current_base_weights.copy(),
                macro_adj=current_macro_adj.copy(),
                strategy_returns=day_returns,
            )
            daily_records.append(record)
            equity = equity_new

        # 통계 정리
        n_days = len(daily_records)
        if n_days > 0:
            stats["avg_market_impact_bps_per_rebalance"] = round(
                stats["total_market_impact_cost"] / max(1, sum(1 for r in daily_records if r.rebalanced))
                / config.initial_capital * 10000, 2
            )
            stats["cash_yield_annualized_pct"] = round(
                stats["total_cash_yield"] / config.initial_capital * (252 / n_days) * 100, 3
            )
        stats["mode_distribution_pct"] = {
            k: round(v / n_days * 100, 1) for k, v in stats["regime_mode_days"].items() if n_days > 0
        }

        return daily_records, stats

    # ═════════════════════════════════════════════════════════════════════
    # PIT-safe systemic risk 조회
    # ═════════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_systemic_risk_pit(macro_df: pd.DataFrame, as_of_date: pd.Timestamp) -> float | None:
        """t일 이전 매크로 데이터로 systemic risk score 계산 (PIT-safe)."""
        if macro_df.empty:
            return None
        try:
            from src.engine.regime_model import MultiRegimeModel
            if "date" not in macro_df.columns:
                return None
            past = macro_df[macro_df["date"] < as_of_date]
            if past.empty:
                return None
            regime_info = MultiRegimeModel.classify_at_date(past, str(as_of_date.date()))
            if regime_info:
                return float(regime_info.get("systemic_risk_score", 0) or 0)
            return None
        except Exception:
            return None
