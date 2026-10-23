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
        # · hard_cap_applied: bool — ★상한이 실제로 물었을 때만 True★
        # · hard_cap_binding_count: int — 상한에 걸린 전략 수
        # · cash_buffer_pct: float — ★실제 현금★ (설정 하한은 cash_buffer_floor_pct)
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

    @staticmethod
    def _cap_and_redistribute(
        raw: dict, cap: float, *, max_passes: int = 50, tol: float = 1e-12,
    ) -> tuple[dict, float, int]:
        """전략당 상한을 적용하고 초과분을 **상한 미달 전략에 현재 비중 비례로**
        재분배한다. 여유가 없으면 남는 몫은 **현금**이 된다.

        ★재정규화하지 않는다 (B2)★ 이전 구현은 상한을 적용한 뒤
        `available_weight / total` 로 다시 정규화해서, 모든 전략이 상한에 걸리면
        그 스케일이 상한을 **정확히 되돌렸다**(전략 1개 → 0.70, 2개 → 0.35).
        그러면서 `hard_cap_applied: True` 를 보고했다 — 위기 모드가 가장 집중된
        경우에 정확히 자기 안전장치를 잃는 거짓 보고였다. 현금 버퍼는 목표가
        아니라 **하한**이고, 30% 상한을 지키면서 전략 1개에 70% 를 넣을 방법은
        없다.

        ★수렴할 때까지 반복한다★ 1패스로는 재분배가 다른 전략을 상한 위로 밀어
        올린 뒤 그 초과분을 잘라 **버린다**(이전에는 재정규화가 그것을 몰래
        되살렸다). 반복하면 남은 여유를 끝까지 쓴다.

        ★재분배 규칙은 바꾸지 않았다★ "현재 비중 비례" 그대로다. "잔여 여유
        비례" 로 갈아타면 최대·합은 같은데 비상한 전략들의 비중만 조용히 바뀐다.

        반환: `(비중, 재분배된 초과분 총합, 상한에 걸린 전략 수)`.
        """
        w = {c: float(v) for c, v in raw.items()}
        moved = 0.0
        for _ in range(max_passes):
            excess = sum(max(0.0, v - cap) for v in w.values())
            if excess <= tol:
                break
            moved += excess
            w = {c: min(v, cap) for c, v in w.items()}
            room = [c for c in w if w[c] < cap - tol]
            base_total = sum(w[c] for c in room)
            if not room or base_total <= tol:
                break                      # 여유 없음 → 나머지는 현금
            for c in room:
                w[c] += excess * (w[c] / base_total)
        w = {c: min(v, cap) for c, v in w.items()}
        binding = sum(1 for v in w.values() if v >= cap - 1e-9)
        return w, moved, binding

    def _defensive_mode(self, returns_matrix, strategies, as_of_date,
                         max_weight_clip, min_weight, diagnostics) -> dict:
        """
        위기 ↑↑ — Hard cap + Cash buffer + EWMA.

        알고리즘:
          1. EWMA-weighted returns (매우 짧은 lookback 60일)
          2. 균등 가중 시작점 = 1/N
          3. inverse-vol 조정 (변동성 가장 낮은 전략에 약간 더)
          4. Hard cap 적용 (max 30%/strategy) — ★재정규화 없음(B2)★
          5. Cash buffer 30% 는 **하한**. 상한이 여러 전략을 묶으면 투자되는 몫이
             0.7 보다 **작아지고** 남는 몫은 현금이 된다. `cash_buffer_pct` 는
             실제 현금, `cash_buffer_floor_pct` 가 설정 하한이다.
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

        # Hard cap 적용 — ★재정규화하지 않는다(B2)★
        raw_weights = {c: float(w) for c, w in (inv_vol * available_weight).items()}
        hard_cap = self.config.defensive_hard_cap

        capped, excess, binding_count = self._cap_and_redistribute(
            raw_weights, hard_cap,
        )
        final_weights = capped

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

        # ★실제로 투자된 몫과 실제 현금 — 설정값이 아니다★
        invested = sum(cleaned_weights.values())
        cash_pct = round(1.0 - invested, 6)

        # 메타데이터
        result = {
            "available":              True,
            "weights":                cleaned_weights,
            "base_weights":           cleaned_weights.copy(),
            "macro_adjustments":      {k: 0.0 for k in cleaned_weights},
            "method":                 "defensive_inverse_vol",
            "regime":                 "PANIC",      # Stage 9 통상 패닉
            "systemic_risk_score":    diagnostics.get("systemic_risk_score"),
            "cash_buffer_pct":        cash_pct,
            "cash_buffer_floor_pct":  self.config.defensive_cash_buffer,
            "adaptive_mode":          "defensive",
            "ewma_applied":           True,
            "ewma_lambda":            self.config.ewma_lambda * 0.95,
            "hard_cap_applied":       bool(binding_count > 0),
            "hard_cap_binding_count": int(binding_count),
            "hard_cap_value":         hard_cap,
            "breakdown_detected":     diagnostics.get("breakdown_detected", False),
            "adaptive_diagnostics":   diagnostics,
            "diagnostics": {
                "n_observations":     len(ewma_returns),
                "mode":               "defensive",
                "available_weight":   available_weight,
                "excess_redistributed": round(excess, 4),
                "capacity_shortfall": round(available_weight - invested, 6),
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
        # ★설정 임계를 실제로 쓴다★ 예전에는 인라인 상수라 설정이 죽어 있었다.
        diagnostics = self.correlation_health(returns_matrix)

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

    def correlation_health(self, returns_matrix: pd.DataFrame) -> dict:
        """이 인스턴스의 **설정 임계**로 상관 건강도를 판정한다.

        ★선언된 손잡이가 죽어 있었다★ `AdaptiveConfig` 는
        `breakdown_avg_corr_threshold`(0.70)와 `breakdown_max_eigenvalue_ratio`
        (0.60)를 선언하는데, 판정은 `0.7`·`0.6` 을 **인라인 상수**로 썼다. 설정을
        바꿔도 아무 일이 일어나지 않았다 — 선언과 동작이 다른 결함이다.

        ★기본값에서는 동작이 한 자리도 바뀌지 않는다★ 두 값이 인라인 상수와
        같기 때문이고, 짝 테스트가 그것을 증명한다. 관측치(`avg_correlation` ·
        `max_eigenvalue_ratio`)는 임계와 무관하게 같다 — 임계는 **관례**이지
        측정이 아니다.
        """
        return self._analyze_correlation_health(
            returns_matrix,
            avg_corr_threshold=self.config.breakdown_avg_corr_threshold,
            max_eig_ratio_threshold=self.config.breakdown_max_eigenvalue_ratio,
        )

    @staticmethod
    def _analyze_correlation_health(
        returns_matrix: pd.DataFrame,
        avg_corr_threshold: float = 0.7,
        max_eig_ratio_threshold: float = 0.6,
    ) -> dict:
        """
        상관관계 매트릭스 건강도 분석.

        임계 기본값은 예전 인라인 상수와 같다 — ★기존 호출부가 깨지지 않는다★.

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

            single_factor = max_eig_ratio > float(max_eig_ratio_threshold)
            breakdown = (avg_corr > float(avg_corr_threshold)) or single_factor

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
