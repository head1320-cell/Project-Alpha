"""
Regime-Adaptive Allocator — 상관관계 붕괴 대응
======================================================
헤지펀드의 무덤: "위기 시 모든 상관관계는 1로 수렴한다" (Cars, 1987 / Brunnermeier, 2009)
2020 코로나 패닉, 2008 리먼 사태, 2022 LDI 위기 — 평소 다르게 움직이던 자산들이 일제히 폭락.

기존 HRP의 약점:
  · 252일 등가중 상관관계 사용 → 변화 감지 늦음
  · 평시 데이터에 weighted → 위기 시 무용지물

해결책 (3단계 모드):
  NORMAL (risk ≤ 50)    : 표준 HRP+Macro (Stage 10 그대로)
  CAUTIOUS (50 < risk ≤ 70) : EWMA covariance (λ=0.85) → 최근 가중치 ↑
  DEFENSIVE (risk > 70) : Hard cap 30%/strategy + cash_buffer 30%

EWMA Covariance:
  Σ_t = λ × Σ_{t-1} + (1-λ) × (r_t - μ)(r_t - μ)^T

  λ=0.85 → 절반 무게 ~5일 (5일 이내 데이터가 50%)
  λ=0.94 → 절반 무게 ~11일 (RiskMetrics 표준)
  λ=0.97 → 절반 무게 ~22일

상관관계 붕괴 자동 감지:
  · 클러스터 수 < 2 → "all-in-one" 경고 (모든 전략이 한 묶음)
  · 평균 상관 > 0.7 → 분산 효과 상실
  · 최대 eigenvalue / 총 분산 > 0.6 → 단일 인자 지배

Stage 10 MultiStrategyAllocator를 wrapping하여 사용 — 비파괴적 확장.
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
class AdaptiveConfig:
    """국면 적응형 설정."""
    # 모드 임계값
    cautious_risk_threshold:    float = 50.0
    defensive_risk_threshold:   float = 70.0

    # CAUTIOUS 모드
    ewma_lambda:                float = 0.85    # 0.85 → 5일 절반 무게
    ewma_min_periods:           int = 30        # 최소 30일 필요

    # DEFENSIVE 모드
    defensive_hard_cap:         float = 0.30    # 전략당 최대 30%
    defensive_cash_buffer:      float = 0.30    # 현금 30% 강제 보유
    defensive_max_weight_clip:  float = 0.25    # 평시 max_weight 25%로 더 엄격

    # 상관관계 붕괴 감지
    breakdown_avg_corr_threshold:    float = 0.70
    breakdown_max_eigenvalue_ratio:  float = 0.60


# ═══════════════════════════════════════════════════════════════════════════════
# RegimeAdaptiveAllocator
# ═══════════════════════════════════════════════════════════════════════════════

class RegimeAdaptiveAllocator:
    """
    Stage 10 allocator wrapping with regime-adaptive logic.

    Usage:
        base_allocator = MultiStrategyAllocator(engine)
        adaptive = RegimeAdaptiveAllocator(base_allocator)

        result = adaptive.compute(
            returns_matrix=returns,
            method="hrp_macro",
            strategies=strategies,
            as_of_date="2024-12-31",
            systemic_risk_score=72,   # ← Stage 9에서 가져온 값
        )

        # result에 추가 필드:
        # · adaptive_mode: 'normal' | 'cautious' | 'defensive'
        # · ewma_applied: bool
        # · hard_cap_applied: bool
        # · breakdown_detected: bool
        # · adaptive_diagnostics: {...}
    """

    def __init__(self, base_allocator, config: AdaptiveConfig | None = None):
        self.base = base_allocator
        self.config = config or AdaptiveConfig()

    # ═════════════════════════════════════════════════════════════════════
    # 메인 진입점
    # ═════════════════════════════════════════════════════════════════════

    def compute(
        self,
        returns_matrix: pd.DataFrame,
        method: str = "hrp_macro",
        strategies: list | None = None,
        as_of_date: str | None = None,
        lookback_days: int = 252,
        max_weight: float = 0.50,
        min_weight: float = 0.02,
        systemic_risk_score: float | None = None,
    ) -> dict:
        """
        Regime-adaptive 가중치 계산.

        Args:
            systemic_risk_score:  Stage 9 출력 (0~100, None이면 normal 모드)
            그 외 인자: Stage 10 allocator와 동일
        """
        # 모드 결정
        mode, diagnostics = self._determine_mode(returns_matrix, systemic_risk_score)
        diagnostics["systemic_risk_score"] = systemic_risk_score

        # 기본 가중치 계산
        if mode == "defensive":
            return self._defensive_mode(
                returns_matrix, strategies, as_of_date,
                self.config.defensive_max_weight_clip, min_weight,
                diagnostics,
            )
        elif mode == "cautious":
            return self._cautious_mode(
                returns_matrix, method, strategies, as_of_date,
                lookback_days, max_weight, min_weight, diagnostics,
            )
        else:
            return self._normal_mode(
                returns_matrix, method, strategies, as_of_date,
                lookback_days, max_weight, min_weight, diagnostics,
            )

    # ═════════════════════════════════════════════════════════════════════
    # 모드별 구현
    # ═════════════════════════════════════════════════════════════════════

    def _normal_mode(self, returns_matrix, method, strategies, as_of_date,
                      lookback_days, max_weight, min_weight, diagnostics) -> dict:
        """평시 — 표준 Stage 10 allocator 호출."""
        result = self.base.compute(
            returns_matrix=returns_matrix, method=method,
            strategies=strategies, as_of_date=as_of_date,
            lookback_days=lookback_days,
            max_weight=max_weight, min_weight=min_weight,
        )
        result["adaptive_mode"] = "normal"
        result["ewma_applied"] = False
        result["hard_cap_applied"] = False
        result["breakdown_detected"] = diagnostics.get("breakdown_detected", False)
        result["adaptive_diagnostics"] = diagnostics
        return result

    def _cautious_mode(self, returns_matrix, method, strategies, as_of_date,
                        lookback_days, max_weight, min_weight, diagnostics) -> dict:
        """
        위험 ↑ — EWMA 공분산으로 최근 데이터 가중치 강화.

        구현: returns_matrix를 EWMA-weighted version으로 변환하여 allocator에 전달.
        """
        ewma_returns = self._apply_ewma_weighting(
            returns_matrix, self.config.ewma_lambda,
        )

        result = self.base.compute(
            returns_matrix=ewma_returns, method=method,
            strategies=strategies, as_of_date=as_of_date,
            lookback_days=min(lookback_days, 90),    # 짧은 lookback 강제
            max_weight=max_weight * 0.85,             # 평시 max의 85%
            min_weight=min_weight,
        )
        result["adaptive_mode"] = "cautious"
        result["ewma_applied"] = True
        result["ewma_lambda"] = self.config.ewma_lambda
        result["hard_cap_applied"] = False
        result["breakdown_detected"] = diagnostics.get("breakdown_detected", False)
        result["adaptive_diagnostics"] = diagnostics
        return result

    def _defensive_mode(self, returns_matrix, strategies, as_of_date,
                         max_weight_clip, min_weight, diagnostics) -> dict:
        """
        위기 ↑↑ — Hard cap + Cash buffer + EWMA.

        알고리즘:
          1. EWMA-weighted returns (매우 짧은 lookback 60일)
          2. 균등 가중 시작점 = 1/N
          3. inverse-vol 조정 (변동성 가장 낮은 전략에 약간 더)
          4. Hard cap 적용 (max 30%/strategy)
          5. Cash buffer 30% 강제 확보 → 총 weight = 0.7
        """
        n_str = len([c for c in returns_matrix.columns])
        if n_str == 0:
            return {"available": False, "message": "전략 없음"}

        # EWMA로 최근 데이터 강조
        ewma_returns = self._apply_ewma_weighting(
            returns_matrix, self.config.ewma_lambda * 0.95,   # 더 강한 EWMA
        )

        # 변동성 (역수로 가중치)
        vols = ewma_returns.tail(60).std()
        if (vols == 0).any() or vols.isna().any():
            # Fallback: 균등
            inv_vol = pd.Series(1/n_str, index=returns_matrix.columns)
        else:
            inv_vol = 1 / vols
            inv_vol = inv_vol / inv_vol.sum()

        # 가용 weight = 1 - cash_buffer
        available_weight = 1.0 - self.config.defensive_cash_buffer

        # Hard cap 적용
        raw_weights = inv_vol * available_weight
        hard_cap = self.config.defensive_hard_cap

        # cap 적용 + 잔여 재분배
        capped = {}
        excess = 0.0
        non_capped = []
        for col, w in raw_weights.items():
            if w > hard_cap:
                capped[col] = hard_cap
                excess += (w - hard_cap)
            else:
                capped[col] = w
                non_capped.append(col)

        # 잔여를 cap 미달 전략들에 비례 분배
        if excess > 0 and non_capped:
            non_cap_total = sum(capped[c] for c in non_capped)
            if non_cap_total > 0:
                for col in non_capped:
                    add = excess * (capped[col] / non_cap_total)
                    new_w = min(capped[col] + add, hard_cap)
                    capped[col] = new_w

        # 최종 정규화 (available_weight 합으로)
        total = sum(capped.values())
        if total > 0:
            scale = available_weight / total
            final_weights = {col: w * scale for col, w in capped.items()}
        else:
            final_weights = {col: 0 for col in capped}

        # min_weight 필터
        final_weights = {k: (v if v >= min_weight else 0)
                          for k, v in final_weights.items()}

        # int key 변환 (strategy_id가 int일 경우)
        cleaned_weights = {}
        for k, v in final_weights.items():
            try:
                cleaned_weights[int(k)] = float(v)
            except (ValueError, TypeError):
                cleaned_weights[k] = float(v)

        # 메타데이터
        result = {
            "available":              True,
            "weights":                cleaned_weights,
            "base_weights":           cleaned_weights.copy(),
            "macro_adjustments":      {k: 0.0 for k in cleaned_weights},
            "method":                 "defensive_inverse_vol",
            "regime":                 "PANIC",      # Stage 9 통상 패닉
            "systemic_risk_score":    diagnostics.get("systemic_risk_score"),
            "cash_buffer_pct":        self.config.defensive_cash_buffer,
            "adaptive_mode":          "defensive",
            "ewma_applied":           True,
            "ewma_lambda":            self.config.ewma_lambda * 0.95,
            "hard_cap_applied":       True,
            "hard_cap_value":         hard_cap,
            "breakdown_detected":     diagnostics.get("breakdown_detected", False),
            "adaptive_diagnostics":   diagnostics,
            "diagnostics": {
                "n_observations":     len(ewma_returns),
                "mode":               "defensive",
                "available_weight":   available_weight,
                "excess_redistributed": round(excess, 4),
            },
        }
        return result

    # ═════════════════════════════════════════════════════════════════════
    # 모드 결정 + 상관관계 붕괴 감지
    # ═════════════════════════════════════════════════════════════════════

    def _determine_mode(
        self,
        returns_matrix: pd.DataFrame,
        systemic_risk_score: float | None,
    ) -> tuple[str, dict]:
        """
        Stage 9 risk score + 자체 상관관계 분석으로 모드 결정.

        Returns:
            (mode, diagnostics)
        """
        diagnostics = self._analyze_correlation_health(returns_matrix)

        # systemic_risk_score 우선
        if systemic_risk_score is not None:
            if systemic_risk_score >= self.config.defensive_risk_threshold:
                return "defensive", diagnostics
            elif systemic_risk_score >= self.config.cautious_risk_threshold:
                return "cautious", diagnostics

        # 자체 상관관계 붕괴 감지로도 모드 결정 가능
        if diagnostics["breakdown_detected"]:
            if diagnostics["avg_correlation"] > 0.85:
                return "defensive", diagnostics
            elif diagnostics["avg_correlation"] > 0.70:
                return "cautious", diagnostics

        return "normal", diagnostics

    @staticmethod
    def _analyze_correlation_health(returns_matrix: pd.DataFrame) -> dict:
        """
        상관관계 매트릭스 건강도 분석.

        Returns:
            {
              "avg_correlation": float,
              "max_correlation": float,
              "n_strategies": int,
              "max_eigenvalue_ratio": float,
              "single_factor_dominance": bool,
              "breakdown_detected": bool,
            }
        """
        if returns_matrix.empty or returns_matrix.shape[1] < 2:
            return {
                "avg_correlation": 0, "max_correlation": 0,
                "n_strategies": returns_matrix.shape[1],
                "max_eigenvalue_ratio": 0,
                "single_factor_dominance": False,
                "breakdown_detected": False,
            }

        try:
            # 최근 60일 상관 (가장 최근의 행동 분석)
            recent = returns_matrix.tail(60).dropna()
            if len(recent) < 20:
                return {
                    "avg_correlation": 0, "max_correlation": 0,
                    "n_strategies": returns_matrix.shape[1],
                    "max_eigenvalue_ratio": 0,
                    "single_factor_dominance": False,
                    "breakdown_detected": False,
                    "message": "데이터 부족",
                }

            corr = recent.corr().values
            n = corr.shape[0]

            # 대각선 제외 평균
            mask = ~np.eye(n, dtype=bool)
            avg_corr = float(np.abs(corr[mask]).mean())
            max_corr = float(np.abs(corr[mask]).max())

            # PCA: 최대 eigenvalue 비율
            eigenvalues = np.linalg.eigvalsh(corr)
            max_eig_ratio = float(eigenvalues[-1] / eigenvalues.sum()) if eigenvalues.sum() > 0 else 0

            single_factor = max_eig_ratio > 0.6
            breakdown = (avg_corr > 0.7) or single_factor

            return {
                "avg_correlation":          round(avg_corr, 3),
                "max_correlation":          round(max_corr, 3),
                "n_strategies":             n,
                "max_eigenvalue_ratio":     round(max_eig_ratio, 3),
                "single_factor_dominance":  single_factor,
                "breakdown_detected":       breakdown,
            }
        except Exception as e:
            logger.warning(f"Correlation analysis failed: {e}")
            return {
                "avg_correlation": 0, "max_correlation": 0,
                "n_strategies": returns_matrix.shape[1],
                "max_eigenvalue_ratio": 0,
                "single_factor_dominance": False,
                "breakdown_detected": False,
                "error": str(e),
            }

    # ═════════════════════════════════════════════════════════════════════
    # EWMA Weighting
    # ═════════════════════════════════════════════════════════════════════

    @staticmethod
    def _apply_ewma_weighting(
        returns_matrix: pd.DataFrame, lambda_decay: float,
    ) -> pd.DataFrame:
        """
        EWMA로 returns를 weighted version으로 변환.

        새 returns'[i] = returns[i] × weight[i]
        weight[i] = (1-λ) × λ^(N-i) → 최근 데이터가 무겁고 과거는 가벼움

        결과의 covariance는 EWMA covariance와 동일.
        """
        if returns_matrix.empty:
            return returns_matrix

        N = len(returns_matrix)
        # weights normalize so sum = N (so variance preserved on average)
        weights = np.array([
            (1 - lambda_decay) * (lambda_decay ** (N - 1 - i))
            for i in range(N)
        ])
        if weights.sum() == 0:
            return returns_matrix
        weights = weights * N / weights.sum()
        weights = np.sqrt(weights)    # variance에 들어가도록 sqrt

        weighted = returns_matrix.copy()
        for col in weighted.columns:
            weighted[col] = weighted[col].values * weights

        return weighted
