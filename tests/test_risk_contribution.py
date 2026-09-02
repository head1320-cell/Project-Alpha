"""오일러 리스크 기여 + ENB 정직성 (P4-b)
==============================================================================
설계: 계획 `P4-b` · 상위 `docs/specs/2026-08-30-macro-to-portfolio-architecture-review.md`

★배분 리포트의 `risk_contributions` 는 추천 포트폴리오를 설명하지 않았다★ —
`PortfolioAnalyzer(returns, weights=user_w)` 로 계산한 **사용자의 현재 비중**이고
비중을 안 주면 **등가중**으로 떨어진다. 바로 옆 `enb` 는 **최적화된** 비중과
**최적화기의** Σ 를 쓴다. 두 진단이 서로 다른 포트폴리오를 나란히 설명하면서
어느 쪽도 그렇다고 말하지 않았다.

★오일러 항등식이 이 모듈의 계약이다★ σ_p 는 w 에 1차 동차이므로
`Σᵢ wᵢ·∂σ/∂wᵢ = σ_p` 가 **정확히** 성립한다. 상수를 박거나 지워도 통과하는
테스트가 아니다 — 공식이 조금이라도 어긋나면 깨진다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.allocation_studio import (  # noqa: E402
    _erc_weights,
    _max_sharpe_w,
    effective_number_of_bets,
    enb_report,
    risk_contributions,
)


def _psd(n: int, rho: float = 0.3, seed: int = 0) -> np.ndarray:
    """상관 rho·단위분산의 PSD 공분산."""
    C = np.full((n, n), rho)
    np.fill_diagonal(C, 1.0)
    return C


# ── 오일러 분해 ───────────────────────────────────────────────────────────
def test_the_contributions_sum_to_the_portfolio_volatility():
    """★오일러★ σ_p 는 1차 동차라 Σ wᵢ·∂σ/∂wᵢ = σ_p 가 **정확히** 성립한다."""
    n = 5
    S = _psd(n, 0.4)
    w = np.array([0.30, 0.25, 0.20, 0.15, 0.10])
    rc = risk_contributions(w, S)
    assert rc["portfolio_volatility"] == pytest.approx(
        float(np.sum(rc["contribution"])), rel=1e-12)


def test_the_percentages_sum_to_one():
    """짝 — 백분율은 σ_p 로 정규화된 같은 양이다."""
    rc = risk_contributions(np.array([0.5, 0.3, 0.2]), _psd(3, 0.2))
    assert float(np.sum(rc["pct"])) == pytest.approx(1.0, rel=1e-12)


def test_the_marginal_is_the_derivative_of_volatility():
    """★수치 미분과 맞춘다★ — 공식을 베끼지 않고 **뜻**을 검사한다."""
    S = _psd(4, 0.35)
    w = np.array([0.4, 0.3, 0.2, 0.1])

    def vol(x):
        return float(np.sqrt(x @ S @ x))

    rc = risk_contributions(w, S)
    h = 1e-6
    for i in range(4):
        e = np.zeros(4)
        e[i] = h
        numeric = (vol(w + e) - vol(w - e)) / (2 * h)
        assert rc["marginal"][i] == pytest.approx(numeric, rel=1e-5)


def test_an_uncorrelated_equal_weight_book_contributes_equally():
    rc = risk_contributions(np.ones(4) / 4, np.eye(4))
    assert np.allclose(rc["pct"], 0.25, atol=1e-12)


def test_a_concentrated_book_is_dominated_by_one_asset():
    """짝 — 항상 균등을 내는 구현을 배제한다."""
    rc = risk_contributions(np.array([0.97, 0.01, 0.01, 0.01]), np.eye(4))
    assert rc["pct"][0] > 0.99
    assert rc["max_pct"] == pytest.approx(float(np.max(rc["pct"])), rel=1e-12)


# ── ★리스크패리티 산출이 정말 균등한가★ — 이것이 이 도구의 존재 이유다 ────
def test_the_risk_parity_solver_really_does_equalise_contributions():
    """`_erc_weights` 는 동일 리스크 기여를 **주장한다**. 검사할 수단이 없었다."""
    S = _psd(5, 0.45)
    rc = risk_contributions(_erc_weights(S), S)
    assert np.std(rc["pct"]) < 1e-3, f"기여가 균등하지 않다: {rc['pct']}"


def test_the_max_sharpe_solver_does_not_equalise_contributions():
    """★짝★ 균등이 최적화기와 무관하게 늘 나오는 것이면 위 테스트는 공허하다."""
    n = 5
    S = _psd(n, 0.45)
    mu = np.array([0.12, 0.02, 0.09, 0.03, 0.15])
    w = _max_sharpe_w(mu, S, n)
    assert w is not None, "SLSQP 가 없으면 이 짝을 확인할 수 없다"
    rc = risk_contributions(w, S)
    assert np.std(rc["pct"]) > 1e-2, "최대샤프인데 기여가 균등하다 — 의심스럽다"


# ── ★미상 ≠ 0★ ───────────────────────────────────────────────────────────
def test_a_portfolio_with_no_measurable_risk_is_unknown_not_zero():
    """σ_p 를 못 구하면 기여는 **0 이 아니라 미상**이다."""
    rc = risk_contributions(np.ones(3) / 3, np.zeros((3, 3)))
    assert rc["portfolio_volatility"] is None
    assert rc["contribution"] is None and rc["pct"] is None
    assert rc["reason"] and rc["reason"].strip()


def test_a_normal_covariance_still_produces_numbers():
    """짝 — 항상 미상이라 답하는 구현을 배제한다."""
    rc = risk_contributions(np.ones(3) / 3, _psd(3))
    assert rc["portfolio_volatility"] > 0
    assert rc["reason"] is None


def test_a_tiny_negative_variance_is_clamped_not_nan():
    """★수치 안전 (CLAUDE.md §6)★ PSD 행렬에서도 wᵀΣw 가 미세 음수가 될 수 있다.

    가드가 없으면 `sqrt` 가 NaN 을 내고, NaN 은 조용히 퍼진다.
    """
    S = np.array([[1.0, 1.0], [1.0, 1.0]])       # 특이 — 상쇄 포트폴리오
    rc = risk_contributions(np.array([0.5, -0.5]), S)
    assert rc["portfolio_volatility"] is None    # NaN 이 아니라 미상
    assert rc["reason"] and rc["reason"].strip()


def test_the_zero_weight_asset_contributes_nothing():
    rc = risk_contributions(np.array([0.5, 0.5, 0.0]), _psd(3, 0.2))
    assert rc["pct"][2] == pytest.approx(0.0, abs=1e-12)


# ── ENB — ★실패를 최대 분산투자라고 부르지 않는다★ ────────────────────────
def test_a_valid_book_reports_an_enb_inside_its_bounds():
    rep = enb_report(np.ones(4) / 4, np.eye(4))
    assert 1.0 - 1e-9 <= rep["enb"] <= 4.0 + 1e-9
    assert rep["reason"] is None


def test_an_uncomputable_enb_is_unknown_not_maximally_diversified():
    """★가장 위험한 방향의 오류★ 예전에는 실패하면 `float(n)` 을 돌려줬다 —
    계산이 안 됐는데 **완전히 분산됐다**고 주장하는 값이다."""
    rep = enb_report(np.ones(3) / 3, np.zeros((3, 3)))
    assert rep["enb"] is None
    assert rep["reason"] and rep["reason"].strip()
    assert effective_number_of_bets(np.ones(3) / 3, np.zeros((3, 3))) is None


def test_enb_still_falls_with_correlation():
    """기존 계약은 그대로다 — 상관이 있으면 실질 베팅 수가 준다."""
    n = 4
    w = np.ones(n) / n
    assert enb_report(w, _psd(n, 0.9))["enb"] < enb_report(w, np.eye(n))["enb"]


def test_a_nan_covariance_is_unknown_rather_than_silently_nan():
    """★클램프가 막는 것은 음수가 아니라 NaN 이다★

    `NaN <= floor` 는 `False` 라 가드가 없으면 그대로 통과해 `sqrt(NaN)` 이
    되고, 기여가 전부 NaN 인 채로 **조용히** 리포트에 실린다.
    """
    S = np.array([[1.0, np.nan], [np.nan, 1.0]])
    rc = risk_contributions(np.array([0.5, 0.5]), S)
    assert rc["portfolio_volatility"] is None
    assert rc["reason"] and rc["reason"].strip()


def test_an_indefinite_quadratic_form_is_clamped_to_zero():
    """★음수 분산을 그대로 흘리지 않는다★ (`sqrt` 안전)."""
    from src.engine.allocation_studio import _portfolio_variance
    S = np.array([[1.0, -2.0], [-2.0, 1.0]])      # 부정부호
    assert _portfolio_variance(np.array([1.0, 1.0]), S) == 0.0


def test_a_malformed_covariance_reports_a_reason_not_a_number():
    """★짝: ENB 예외 경로★ 실패해도 `N` 을 내지 않는다."""
    rep = enb_report(np.ones(3) / 3, np.ones((3, 2)))   # 정사각이 아니다
    assert rep["enb"] is None
    assert rep["reason"] and rep["reason"].strip()
