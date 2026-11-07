"""뷰 신뢰도 — ★스칼라 휴리스틱 대신 Ω 를 분해해 계산한다★ (MS1-a 커밋 3)
==============================================================================
계획: `docs/plans/2026-08-25-macro-vnext-plan.md` §1.5.3 · §1.5.4 · §1.10.0 I7

현행 프로덕션은 `conf = 50 × (1 − λ)` 다. `conf = 50` 은 `build_user_views` 에서
`scale = 1`, 즉 `Ω = diag(P τΣ Pᵀ)` — He–Litterman 중립점이라 **앵커 자체는
원칙적이다.** 검증된 적 없는 것은 `(1 − λ)` 곱이다.

Ω 는 **뷰 오차의 공분산**이라는 정해진 의미가 있으므로 추측하지 않고 구성한다:

    Ω = 국면 불확실성(D) + μ̂ 추정오차(Σ_within × 12/n_months) + 잔여 모델리스크(Ξ)

★I7 — 이 테스트 묶음의 핵심★ `Ξ` 를 "안 쟀으니 0" 으로 두면 Ω 가 작아지고 신뢰도가
**올라간다.** 재지 않을수록 뷰가 강해지는 구조다. 그래서 미측정은 0이 아니라
**선언된 보수적 하한**으로 표현한다.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.engine.conditional_market import (
    RESIDUAL_MEASURED,
    RESIDUAL_POLICY_FLOOR,
    RESIDUAL_POLICY_MEASURED,
    RESIDUAL_UNMEASURED,
    implied_confidence,
    view_omega_terms,
)

TAU = 0.05
# 3자산 통제 fixture — 계획 §1.5.4 의 표와 같은 값이다.
SIGMA_DIAG = np.array([0.16, 0.04, 0.07]) ** 2      # 연율 분산
D_DIAG = np.array([0.0047, 0.0002, 0.0008])         # 국면 간 산포 (π̄ 기준)


def _terms(n_months, residual=None):
    return view_omega_terms(regime_diag=D_DIAG, sigma_within_diag=SIGMA_DIAG,
                            n_months=n_months, residual_diag=residual)


# ══════════════════════════════════════════════════════════════════════════
# 분해의 대수 — 항의 합이 전체다
# ══════════════════════════════════════════════════════════════════════════
def test_omega_terms_sum_to_total():
    """세 항의 합이 보고된 Ω 와 정확히 같다 — 어느 항이 뷰를 죽이는지 보이게."""
    t = _terms(32)
    total = (np.asarray(t["terms"]["regime"])
             + np.asarray(t["terms"]["estimation"])
             + np.asarray(t["terms"]["residual"]))
    np.testing.assert_allclose(t["omega_diag"], total, rtol=0, atol=1e-18)


def test_estimation_term_uses_months_not_trading_days():
    """★독립 관측은 영업일이 아니라 개월★ — 한 달의 21영업일은 국면 라벨 하나를 공유한다.

    영업일로 나눴다면 추정오차가 21배 작아져 신뢰도가 터무니없이 높아진다.
    """
    t = _terms(32)
    np.testing.assert_allclose(t["terms"]["estimation"],
                               SIGMA_DIAG * (12.0 / 32.0), rtol=0, atol=1e-18)


# ══════════════════════════════════════════════════════════════════════════
# ★I7★ 미측정 잔여 리스크를 0 으로 쓰지 않는다
# ══════════════════════════════════════════════════════════════════════════
def test_unmeasured_residual_is_not_zero():
    """★I7★ 미측정이면 잔여항이 0 이 아니고, 신뢰도가 **엄격히 낮아진다**.

    0 으로 두면 Ω 가 작아져 conf 가 올라간다 — 재지 않을수록 확신이 커지는 구조다.
    실측: n=32 에서 8.22(Ξ=0) → 5.08(하한).
    """
    t = _terms(32)
    assert t["residual_risk"] == RESIDUAL_UNMEASURED
    assert t["residual_policy"] == RESIDUAL_POLICY_FLOOR
    assert np.all(np.asarray(t["terms"]["residual"]) > 0.0)

    zero = _terms(32, residual=np.zeros(3))
    conf_floor = implied_confidence(t["omega_diag"], SIGMA_DIAG, tau=TAU)
    conf_zero = implied_confidence(zero["omega_diag"], SIGMA_DIAG, tau=TAU)
    assert np.all(conf_floor < conf_zero - 1e-9), (
        f"미측정이 Ξ=0 보다 확신이 낮아야 한다: {conf_floor} vs {conf_zero}")
    assert conf_floor[0] == pytest.approx(5.08, abs=0.05)
    assert conf_zero[0] == pytest.approx(8.22, abs=0.05)


def test_residual_floor_is_max_of_measured_terms():
    """하한은 **실제로 잰 항들 중 최대**다 — 선언된 보수적 가정이지 추정이 아니다."""
    t = _terms(32)
    expected = np.maximum(D_DIAG, SIGMA_DIAG * (12.0 / 32.0))
    np.testing.assert_allclose(t["terms"]["residual"], expected, rtol=0, atol=1e-18)


def test_residual_floor_does_not_vanish_with_sample():
    """★표본이 늘어도 잔여 리스크가 0 으로 수렴하지 않는다★

    n=120 에서 하한이 추정항(0.00256)이 아니라 국면항(0.0047)으로 넘어간다 —
    모델리스크는 표본을 늘려 없앨 수 있는 종류가 아니라는 성질이 값에 남는다.
    """
    small, large = _terms(15), _terms(120)
    assert small["terms"]["residual"][0] == pytest.approx(SIGMA_DIAG[0] * (12.0 / 15.0))
    assert large["terms"]["residual"][0] == pytest.approx(D_DIAG[0])
    assert large["terms"]["residual"][0] > 0.0


def test_measured_residual_replaces_the_floor_and_is_declared():
    """실측하면 하한을 **대체**하고 그 사실을 필드가 말한다."""
    measured = np.array([0.001, 0.00005, 0.0002])
    t = _terms(32, residual=measured)
    np.testing.assert_allclose(t["terms"]["residual"], measured, rtol=0, atol=1e-18)
    assert t["residual_risk"] == RESIDUAL_MEASURED
    assert t["residual_policy"] == RESIDUAL_POLICY_MEASURED


def test_residual_policy_is_declared_in_response():
    t = _terms(32)
    for key in ("residual_risk", "residual_policy", "terms", "omega_diag",
                "n_months", "note"):
        assert key in t
    assert "0" in t["note"] or "측정" in t["note"]


# ══════════════════════════════════════════════════════════════════════════
# 신뢰도의 방향 — 표본이 늘면 오르고, 국면이 흐리면 내린다
# ══════════════════════════════════════════════════════════════════════════
def test_more_months_raises_confidence():
    """★T20★ 표본이 늘면 추정오차가 줄어 신뢰도가 오른다.

    ★상수 휴리스틱(`50×(1−λ)`)이면 여기서 red 다★ — 표본이 네 배가 되어도 값이
    변하지 않기 때문이다. 실측 방향: 15개월 2.73 → 60개월 7.89.
    """
    confs = [implied_confidence(_terms(n)["omega_diag"], SIGMA_DIAG, tau=TAU)[0]
             for n in (15, 32, 60, 120)]
    assert confs == sorted(confs), f"단조 증가해야 한다: {confs}"
    assert confs[0] == pytest.approx(2.73, abs=0.05)
    assert confs[2] == pytest.approx(7.89, abs=0.05)


def test_regime_dispersion_term_lowers_confidence():
    """국면 간 산포가 커지면 뷰가 약해진다 — 국면을 모를수록 확신을 줄인다."""
    base = implied_confidence(_terms(32)["omega_diag"], SIGMA_DIAG, tau=TAU)
    wide = view_omega_terms(regime_diag=D_DIAG * 5.0,
                            sigma_within_diag=SIGMA_DIAG, n_months=32)
    assert np.all(implied_confidence(wide["omega_diag"], SIGMA_DIAG, tau=TAU) < base)


def test_current_production_heuristic_is_far_more_confident():
    """★현행은 계산된 뷰 오차분산이 정당화하는 것보다 훨씬 확신한다★

    이 테스트는 프로덕션 상수를 고정하려는 것이 아니라 **격차를 기록**한다 —
    분해가 왜 필요한지가 숫자로 남아 있어야 한다.
    """
    legacy = 50.0 * (1.0 - 0.2)                      # λ=0.2 일 때의 현행 값
    decomposed = implied_confidence(_terms(32)["omega_diag"], SIGMA_DIAG, tau=TAU)[0]
    assert legacy > decomposed * 5.0


def test_confidence_is_clamped_to_valid_range():
    """`build_user_views` 가 받는 범위(0~100)를 벗어나지 않는다."""
    tiny = view_omega_terms(regime_diag=np.zeros(3),
                            sigma_within_diag=SIGMA_DIAG * 1e-9, n_months=10_000)
    c = implied_confidence(tiny["omega_diag"], SIGMA_DIAG, tau=TAU)
    assert np.all(c > 0.0) and np.all(c <= 100.0)

    huge = view_omega_terms(regime_diag=D_DIAG * 1e6,
                            sigma_within_diag=SIGMA_DIAG, n_months=12)
    c2 = implied_confidence(huge["omega_diag"], SIGMA_DIAG, tau=TAU)
    assert np.all(c2 >= 0.0)


def test_neutral_omega_maps_to_fifty():
    """★He–Litterman 중립점의 좌표를 못박는다★ Ω = τΣ 이면 conf = 50.

    현행 `_CONDITIONAL_MAX_CONFIDENCE = 50.0` 이 임의의 노브가 아니라 이 지점이라는
    사실이 코드에 남아 있어야 한다.
    """
    np.testing.assert_allclose(
        implied_confidence(TAU * SIGMA_DIAG, SIGMA_DIAG, tau=TAU),
        np.full(3, 50.0), rtol=0, atol=1e-9)


def test_zero_or_negative_inputs_are_refused():
    """음수 분산은 계산하지 않는다 — 조용히 절댓값을 취하지 않는다."""
    with pytest.raises(ValueError):
        view_omega_terms(regime_diag=np.array([-1.0, 0.0, 0.0]),
                         sigma_within_diag=SIGMA_DIAG, n_months=32)
    with pytest.raises(ValueError):
        view_omega_terms(regime_diag=D_DIAG, sigma_within_diag=SIGMA_DIAG,
                         n_months=0)
