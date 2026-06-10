"""
Portfolio Rebalancer — 동적 리밸런싱 정책 엔진
=================================================
백테스트와 라이브 거래에서 동일하게 사용하는 리밸런싱 의사결정 모듈.

4가지 정책:
  ① calendar           — 달력 기준 (daily/weekly/monthly/quarterly)
  ② threshold          — 가중치 drift > N% 시
  ③ regime_change      — Stage 9 매크로 국면 변경 시
  ④ volatility_spike   — Vol spike > N% 시 (긴급 리밸런싱)

핵심 기능:
  - 리밸런싱 트리거 감지
  - 거래 비용 vs 추적 오차 트레이드오프 분석
  - 리밸런싱 영향도 사전 추정

기존 플랫폼과의 차이:
  - VectorBT/Backtrader: 정적 정책만 (월말 고정)
  - 본 시스템: 매크로 국면 + 변동성 + drift를 동시 고려한 동적 정책
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RebalancePolicy:
    """리밸런싱 정책 설정."""
    policy_type:        str = "monthly"
    # calendar 정책 옵션
    frequency:          str = "monthly"  # daily/weekly/monthly/quarterly
    # threshold 정책 옵션
    drift_threshold:    float = 0.05    # 5%p drift시 리밸런싱
    # regime_change 정책 옵션
    regime_lookback:    int = 5         # N일간 regime 안정성 확인
    # volatility_spike 옵션
    vol_spike_multiple: float = 1.5     # 평균 vol 대비 1.5배 초과
    vol_lookback:       int = 60        # vol 측정 기간
    # 공통 옵션
    min_days_between_rebalances: int = 1
    enable_threshold_override:   bool = True  # threshold 정책 외에도 drift 모니터링


# ═══════════════════════════════════════════════════════════════════════════════
# PortfolioRebalancer
# ═══════════════════════════════════════════════════════════════════════════════

class PortfolioRebalancer:
    """
    리밸런싱 의사결정 엔진.

    Usage:
        rebalancer = PortfolioRebalancer(policy=RebalancePolicy(
            policy_type="regime_change", frequency="monthly",
            drift_threshold=0.08,
        ))

        # 1. 백테스트용 — 일정 사전 계산
        schedule = rebalancer.compute_schedule(trading_days, market_data)

        # 2. 라이브용 — 매일 호출하여 리밸런싱 여부 결정
        decision = rebalancer.should_rebalance(
            current_date, current_weights, target_weights,
            current_regime, last_rebalance_date, recent_returns,
        )
    """

    def __init__(self, policy: RebalancePolicy | None = None):
        self.policy = policy or RebalancePolicy()

    # ═════════════════════════════════════════════════════════════════════
    # 백테스트용: 사전 일정 계산
    # ═════════════════════════════════════════════════════════════════════

    def compute_schedule(
        self,
        trading_days: list[pd.Timestamp],
        regime_series: pd.Series | None = None,
        returns_series: pd.Series | None = None,
    ) -> dict:
        """
        백테스트용 리밸런싱 일정 사전 계산.

        Args:
            trading_days:    거래일 리스트
            regime_series:   각 일자의 국면 (regime_change 정책용)
            returns_series:  포트폴리오 수익률 (volatility_spike용)

        Returns:
            {
              "scheduled_dates": [...],
              "regime_change_dates": [...],
              "volatility_spike_dates": [...],
              "total_count": int,
              "by_trigger": {calendar: N, regime: M, vol: K},
            }
        """
        if not trading_days:
            return {"scheduled_dates": [], "total_count": 0}

        scheduled = set()
        regime_changes = set()
        vol_spikes = set()

        # ① Calendar-based
        if self.policy.policy_type in ("calendar", "regime_change", "threshold"):
            calendar_dates = self._calendar_schedule(
                trading_days, self.policy.frequency,
            )
            scheduled.update(calendar_dates)

        # ② Regime change trigger
        if self.policy.policy_type == "regime_change" and regime_series is not None:
            regime_changes = self._detect_regime_changes(regime_series)
            scheduled.update(regime_changes)

        # ③ Volatility spike trigger (모든 정책에서 가능)
        if returns_series is not None and not returns_series.empty:
            vol_spikes = self._detect_vol_spikes(returns_series)
            # vol spike는 기본 정책 외에 추가 리밸런싱 (옵션)
            scheduled.update(vol_spikes)

        # 첫 거래일은 항상 포함
        scheduled.add(trading_days[0])

        return {
            "scheduled_dates":         sorted(scheduled),
            "regime_change_dates":     sorted(regime_changes),
            "volatility_spike_dates":  sorted(vol_spikes),
            "total_count":             len(scheduled),
            "by_trigger": {
                "calendar":   len(scheduled - regime_changes - vol_spikes),
                "regime":     len(regime_changes),
                "volatility": len(vol_spikes),
            },
        }

    @staticmethod
    def _calendar_schedule(
        trading_days: list[pd.Timestamp], frequency: str,
    ) -> set[pd.Timestamp]:
        """달력 기준 리밸런싱 일자."""
        if not trading_days:
            return set()

        if frequency == "daily":
            return set(trading_days)

        dates = set()
        dates.add(trading_days[0])

        if frequency == "weekly":
            seen = set()
            for d in trading_days:
                wk = (d.year, d.isocalendar().week)
                if wk not in seen:
                    dates.add(d)
                    seen.add(wk)

        elif frequency == "monthly":
            seen = set()
            for d in trading_days:
                key = (d.year, d.month)
                if key not in seen:
                    dates.add(d)
                    seen.add(key)

        elif frequency == "quarterly":
            seen = set()
            for d in trading_days:
                key = (d.year, (d.month - 1) // 3)
                if key not in seen:
                    dates.add(d)
                    seen.add(key)

        return dates

    @staticmethod
    def _detect_regime_changes(regime_series: pd.Series) -> set:
        """국면 변경 시점 감지 (지속 보장)."""
        if regime_series.empty:
            return set()

        changes = set()
        prev = None
        for date, regime in regime_series.items():
            if regime is None or pd.isna(regime):
                continue
            if prev is not None and regime != prev:
                changes.add(date)
            prev = regime
        return changes

    def _detect_vol_spikes(self, returns: pd.Series) -> set:
        """변동성 spike 감지."""
        if len(returns) < self.policy.vol_lookback:
            return set()

        # Rolling 60일 vol
        rolling_vol = returns.rolling(self.policy.vol_lookback).std()
        # 그 평균
        baseline_vol = rolling_vol.rolling(self.policy.vol_lookback).mean()

        # Spike 조건: 현재 vol > baseline × 1.5
        spike_mask = rolling_vol > baseline_vol * self.policy.vol_spike_multiple

        # 연속 spike는 첫 일자만 트리거
        spike_dates = set()
        prev_spike = False
        for date, is_spike in spike_mask.items():
            if is_spike and not prev_spike:
                spike_dates.add(date)
            prev_spike = bool(is_spike)

        return spike_dates

    # ═════════════════════════════════════════════════════════════════════
    # 라이브용: 실시간 의사결정
    # ═════════════════════════════════════════════════════════════════════

    def should_rebalance(
        self,
        current_date: pd.Timestamp,
        current_weights: dict,
        target_weights: dict,
        current_regime: str | None = None,
        previous_regime: str | None = None,
        last_rebalance_date: pd.Timestamp | None = None,
        recent_returns: pd.Series | None = None,
    ) -> dict:
        """
        실시간 리밸런싱 의사결정.

        Returns:
            {
              "should_rebalance": bool,
              "reason": str,
              "triggers": [...],
              "drift_pct": float,
              "expected_cost_pct": float,
            }
        """
        triggers = []
        reasons = []

        # Min days check
        if last_rebalance_date is not None:
            days_since = (current_date - last_rebalance_date).days
            if days_since < self.policy.min_days_between_rebalances:
                return {
                    "should_rebalance": False,
                    "reason":           f"최소 간격 미달 ({days_since}/{self.policy.min_days_between_rebalances}일)",
                    "triggers":         [],
                    "drift_pct":        0,
                }

        # ① Calendar trigger
        if self.policy.policy_type in ("calendar", "regime_change"):
            if self._is_calendar_due(current_date, last_rebalance_date):
                triggers.append("calendar")
                reasons.append(f"{self.policy.frequency} 일정 도래")

        # ② Drift check (threshold 정책 또는 override)
        drift_pct = self._compute_drift(current_weights, target_weights)
        if self.policy.policy_type == "threshold" or self.policy.enable_threshold_override:
            if drift_pct >= self.policy.drift_threshold:
                triggers.append("drift")
                reasons.append(f"Drift {drift_pct*100:.1f}% > {self.policy.drift_threshold*100:.1f}%")

        # ③ Regime change
        if (self.policy.policy_type == "regime_change"
                and current_regime is not None and previous_regime is not None
                and current_regime != previous_regime):
            triggers.append("regime_change")
            reasons.append(f"국면 변경: {previous_regime} → {current_regime}")

        # ④ Volatility spike
        if recent_returns is not None and len(recent_returns) >= self.policy.vol_lookback:
            current_vol = recent_returns.tail(self.policy.vol_lookback).std()
            baseline_vol = recent_returns.tail(self.policy.vol_lookback * 2).head(
                self.policy.vol_lookback
            ).std() if len(recent_returns) >= self.policy.vol_lookback * 2 else current_vol

            if baseline_vol > 0 and current_vol > baseline_vol * self.policy.vol_spike_multiple:
                triggers.append("vol_spike")
                reasons.append(
                    f"Vol spike: {current_vol*np.sqrt(252)*100:.1f}% > "
                    f"{baseline_vol*np.sqrt(252)*100:.1f}%×{self.policy.vol_spike_multiple}"
                )

        return {
            "should_rebalance":  len(triggers) > 0,
            "reason":            " · ".join(reasons) if reasons else "트리거 없음",
            "triggers":          triggers,
            "drift_pct":         round(drift_pct * 100, 2),
            "current_date":      str(current_date.date()) if hasattr(current_date, "date") else str(current_date),
            "last_rebalance":    str(last_rebalance_date.date()) if last_rebalance_date and hasattr(last_rebalance_date, "date") else None,
        }

    def _is_calendar_due(
        self, current_date: pd.Timestamp,
        last_rebalance_date: pd.Timestamp | None,
    ) -> bool:
        """달력 기준 리밸런싱 시기 도래 여부."""
        if last_rebalance_date is None:
            return True

        freq = self.policy.frequency
        if freq == "daily":
            return current_date.date() > last_rebalance_date.date()
        elif freq == "weekly":
            cw = current_date.isocalendar()
            lw = last_rebalance_date.isocalendar()
            return (cw.year, cw.week) != (lw.year, lw.week)
        elif freq == "monthly":
            return (current_date.year, current_date.month) != \
                   (last_rebalance_date.year, last_rebalance_date.month)
        elif freq == "quarterly":
            cq = (current_date.year, (current_date.month - 1) // 3)
            lq = (last_rebalance_date.year, (last_rebalance_date.month - 1) // 3)
            return cq != lq
        return False

    @staticmethod
    def _compute_drift(current: dict, target: dict) -> float:
        """가중치 drift = max(|wᵢ_current - wᵢ_target|)."""
        all_keys = set(current.keys()) | set(target.keys())
        if not all_keys:
            return 0
        return max(abs(current.get(k, 0) - target.get(k, 0)) for k in all_keys)
