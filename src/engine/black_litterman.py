"""Black-Litterman 단일 출처 — ★두 벌이 9%p 다른 비중을 냈다★ (P2′)
==============================================================================
설계: `docs/superpowers/specs/2026-08-30-black-litterman-single-source-design.md`

★이 모듈이 생긴 이유★ BL 이 두 벌 있었고, `allocation_studio.bl_posterior` 의
독스트링이 *"risk_allocations.s_black_litterman 과 동일 공식"* 이라고 적고 있었다.
**틀렸다.** Ω 구성이 달랐다:

| | `allocation_studio` | `risk_allocations` |
|---|---|---|
| 신뢰도 스케일링 | 있음 `(100−conf)/conf` | ★없음★ |
| 바닥 | `max(diag, 1e-10)` | 없음 |
| ridge | `1e-10` | `1e-8` |

실측(시드 30개, 동일 뷰): 신뢰도 스케일링 유무가 `max|Δw| = 9.07%p` 를 만든다 —
무거래 밴드 최소값(1.00%p)의 **9배**다. ridge 차이는 0.0001%p 로 무의미하다.
둘 다 프로덕션이고 `s_black_litterman` 은 사용자가 고르는 전략이다.

★두 동작을 **선언된 인자**로 가른다★ — `confidences=None` 이 스케일링 없음,
값을 주면 스케일링. 지금은 복사본이 **우연히** 갈라져 있고 아무도 그 사실을 모른다.

★사후 공분산은 진단 전용이다★ 최적화기에 연결해도 비중 변화가 0.70%p 로 밴드
아래라 거래가 한 건도 발생하지 않는다(실측). `_opt` 이 long-only·합=1 이라
"포지션이 작아진다" 는 서사도 성립하지 않고, 방향조차 일정하지 않았다(30시드에서
18/12). 그래서 연결하지 않고, **연결하지 않았다는 사실을 `convention` 이 신고한다**
— 안 그러면 누군가 "빠뜨렸네" 하고 측정 없이 연결한다.
"""

from __future__ import annotations

from typing import Any

import numpy as np

#: 사전 불확실성. 두 호출부가 이미 쓰던 값이다.
TAU_DEFAULT = 0.05
#: Ω 대각 ridge. `risk_allocations` 는 1e-8 이었으나 실측 차이가 7.5e-7 로
#: P1 에서 관측한 CPU 흔들림과 같은 자릿수라 작은 쪽으로 통일한다.
RIDGE_DEFAULT = 1e-10
#: Ω 대각 바닥 — ★분산이 0 인 뷰에서 `Ω⁻¹` 가 터지는 것을 막는다★ (수치 안전).
OMEGA_FLOOR = 1e-10

#: 사후 공분산을 최적화기에 연결하지 않은 이유. `convention` 에 실린다.
POSTERIOR_COV_REASON = (
    "진단 전용입니다 — 최적화기에 연결해도 비중 변화가 0.70%p 로 무거래 밴드"
    "(1.00~4.19%p) 아래라 거래가 발생하지 않습니다. 연결하려면 밴드보다 큰 "
    "효과를 먼저 보이고 배분 정책 변경 승인을 받아야 합니다(CLAUDE.md §3)."
)


def bl_omega(P, sigma, *, tau: float = TAU_DEFAULT,
             confidences=None, ridge: float = RIDGE_DEFAULT,
             floor: float = OMEGA_FLOOR) -> np.ndarray:
    """뷰 불확실성 Ω — He-Litterman 기저 `diag(P τΣ Pᵀ)`.

    `confidences` 를 주면 Idzorek 계열로 `(100−conf)/max(conf,1)` 배 한다 —
    ★50 이 중립점★(배율 1.0)이고, 높을수록 Ω 가 좁아져 사후가 뷰 쪽으로 간다.
    `None` 이면 스케일링하지 않는다.

    ★바닥을 유지한다★ 분산이 0 인 뷰(예: 상수 계열)에서 `Ω⁻¹` 가 터진다.
    """
    P = np.asarray(P, dtype=float)
    S = np.asarray(sigma, dtype=float)
    base = np.maximum(np.diag(P @ (float(tau) * S) @ P.T).copy(), float(floor))
    if confidences is not None:
        conf = np.asarray(list(confidences), dtype=float)
        base = base * np.maximum((100.0 - conf) / np.maximum(conf, 1.0), 1e-4)
    return np.diag(base) + np.eye(P.shape[0]) * float(ridge)


def bl_posterior_mean(pi, sigma, P, Q, omega, *,
                      tau: float = TAU_DEFAULT) -> np.ndarray:
    """BL 사후 기대수익 `[(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ [(τΣ)⁻¹π + PᵀΩ⁻¹Q]`.

    극한이 계약이다 — `Ω→0` 이면 `P μ → Q`(뷰), `Ω→∞` 면 `μ → π`(사전).
    """
    S = np.asarray(sigma, dtype=float)
    P = np.asarray(P, dtype=float)
    tauS = float(tau) * S
    inv_tauS = np.linalg.inv(tauS)
    inv_om = np.linalg.inv(np.asarray(omega, dtype=float))
    return np.linalg.solve(inv_tauS + P.T @ inv_om @ P,
                           inv_tauS @ np.asarray(pi, dtype=float)
                           + P.T @ inv_om @ np.asarray(Q, dtype=float))


def bl_posterior_cov(sigma, P, omega, *,
                     tau: float = TAU_DEFAULT) -> np.ndarray:
    """★진단 전용★ 사후 수익 공분산 `Σ + [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹`.

    ★최적화기에 넣지 않는다★ — 이유는 `POSTERIOR_COV_REASON`. `Σ ⪯ Σ_post ⪯
    (1+τ)Σ` 이고 max-Sharpe(합=1)는 Σ 의 균등배수에 불변이라, 효과는 M 의
    **비균등 부분**에서만 나온다. 실측으로 그 크기가 밴드 아래였다.
    """
    S = np.asarray(sigma, dtype=float)
    P = np.asarray(P, dtype=float)
    tauS = float(tau) * S
    M = np.linalg.inv(np.linalg.inv(tauS)
                      + P.T @ np.linalg.inv(np.asarray(omega, dtype=float)) @ P)
    return S + M


def bl_solve(pi, sigma, P, Q, *, tau: float = TAU_DEFAULT, confidences=None,
             ridge: float = RIDGE_DEFAULT,
             floor: float = OMEGA_FLOOR) -> dict[str, Any]:
    """사후 평균·공분산·Ω 와 ★그것들을 만든 관례★ (P1 패턴).

    관례를 산출과 함께 싣지 않으면 두 리포트의 BL 비중을 비교할 수 없다 —
    이 모듈이 생긴 원인이 정확히 그것이었다.
    """
    om = bl_omega(P, sigma, tau=tau, confidences=confidences, ridge=ridge,
                  floor=floor)
    return {
        "mean": bl_posterior_mean(pi, sigma, P, Q, om, tau=tau),
        "posterior_cov": bl_posterior_cov(sigma, P, om, tau=tau),
        "omega": om,
        "convention": {
            "tau": float(tau), "ridge": float(ridge),
            "omega_floor": float(floor),
            "confidence_scaling": confidences is not None,
            "omega_base": "he_litterman_diag",
            # ★의도적 비연결을 관측 가능하게★
            "posterior_cov_used_in_optimizer": False,
            "posterior_cov_reason": POSTERIOR_COV_REASON,
            "declared": True,
        },
    }
