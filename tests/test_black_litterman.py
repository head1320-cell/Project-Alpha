"""BL 단일 출처 — ★두 벌이 9%p 다른 비중을 냈다★ (P2′)
==============================================================================
설계: `docs/superpowers/specs/2026-08-30-black-litterman-single-source-design.md`

`allocation_studio.bl_posterior` 의 독스트링은 "risk_allocations.s_black_litterman
과 동일 공식" 이라고 적혀 있었다. ★틀렸다.★ Ω 구성이 다르다 — 한쪽만 뷰 신뢰도로
스케일링하고, 바닥과 ridge 도 다르다. 실측하면 같은 뷰에서 **9.07%p** 다른 비중이
나온다(무거래 밴드 최소 1.00%p 의 9배). 둘 다 프로덕션이다.

★Σ_post 는 진단으로만 낸다★ 최적화기에 연결해도 비중 변화가 0.70%p 로 밴드 아래라
거래가 발생하지 않는다 — 측정된 사실이고, `convention` 이 그 결정을 신고한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.black_litterman import (  # noqa: E402
    OMEGA_FLOOR,
    RIDGE_DEFAULT,
    TAU_DEFAULT,
    bl_omega,
    bl_posterior_cov,
    bl_posterior_mean,
    bl_solve,
)


def _case(seed=7, n=6):
    rng = np.random.default_rng(seed)
    A = rng.normal(0, 1, (n, n))
    S = (A @ A.T) / n * 0.04 + np.eye(n) * 0.01
    w_mkt = np.ones(n) / n
    pi = 2.5 * S @ w_mkt
    P = np.zeros((2, n)); P[0, 0] = 1; P[0, 1] = -1; P[1, 2] = 1
    Q = np.array([0.03, 0.02])
    return S, pi, P, Q, n


# ══════════════════════════════════════════════════════════════════════════
# ★두 벌이 갈라진 지점 — 신뢰도 스케일링★
# ══════════════════════════════════════════════════════════════════════════
def test_confidence_scaling_materially_changes_the_weights():
    """★9%p — 무거래 밴드(최소 1.00%p)의 9배★

    `allocation_studio` 는 Ω 를 뷰 신뢰도로 스케일링하고 `risk_allocations` 는
    하지 않았다. 독스트링은 "동일 공식" 이라고 적었다. 이 테스트가 그 주장을
    영구히 반증한다.
    """
    from src.engine.allocation_studio import _max_sharpe_w
    S, pi, P, Q, n = _case()
    plain = bl_omega(P, S, tau=TAU_DEFAULT)
    scaled = bl_omega(P, S, tau=TAU_DEFAULT, confidences=[25.0, 25.0])
    w_a = _max_sharpe_w(bl_posterior_mean(pi, S, P, Q, plain, tau=TAU_DEFAULT), S, n)
    w_b = _max_sharpe_w(bl_posterior_mean(pi, S, P, Q, scaled, tau=TAU_DEFAULT), S, n)
    assert np.abs(w_a - w_b).max() > 0.01, "밴드보다 작으면 갈라져도 티가 안 난다"


def test_no_confidence_means_no_scaling():
    """★짝★ — `confidences=None` 은 `s_black_litterman` 의 현행 동작이다."""
    S, _pi, P, _Q, _n = _case()
    a = bl_omega(P, S, tau=TAU_DEFAULT)
    b = bl_omega(P, S, tau=TAU_DEFAULT, confidences=None)
    assert np.allclose(a, b)


def test_a_fifty_percent_confidence_is_the_neutral_point():
    """`(100−conf)/conf` 이므로 conf=50 이면 배율 1.0 — 스케일링 없음과 같다."""
    S, _pi, P, _Q, _n = _case()
    plain = bl_omega(P, S, tau=TAU_DEFAULT)
    neutral = bl_omega(P, S, tau=TAU_DEFAULT, confidences=[50.0, 50.0])
    assert np.allclose(plain, neutral)


def test_higher_confidence_narrows_omega():
    """★확신할수록 Ω 가 작아진다★ — 그래야 사후가 뷰 쪽으로 간다."""
    S, _pi, P, _Q, _n = _case()
    sure = bl_omega(P, S, tau=TAU_DEFAULT, confidences=[90.0, 90.0])
    unsure = bl_omega(P, S, tau=TAU_DEFAULT, confidences=[10.0, 10.0])
    assert np.diag(sure).max() < np.diag(unsure).min()


# ══════════════════════════════════════════════════════════════════════════
# 사후 평균 — ★극한이 계약이다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_certain_view_pulls_the_posterior_onto_the_view():
    """Ω→0 이면 `P μ_post → Q`."""
    S, pi, P, Q, _n = _case()
    tiny = bl_omega(P, S, tau=TAU_DEFAULT) * 1e-8
    mu = bl_posterior_mean(pi, S, P, Q, tiny, tau=TAU_DEFAULT)
    assert np.allclose(P @ mu, Q, atol=1e-4)


def test_a_worthless_view_leaves_the_prior_alone():
    """★짝★ Ω→∞ 면 사후가 사전(π)으로 돌아간다."""
    S, pi, P, Q, _n = _case()
    huge = bl_omega(P, S, tau=TAU_DEFAULT) * 1e12
    mu = bl_posterior_mean(pi, S, P, Q, huge, tau=TAU_DEFAULT)
    assert np.allclose(mu, pi, atol=1e-6)


# ══════════════════════════════════════════════════════════════════════════
# ★사후 공분산 — 진단 전용★
# ══════════════════════════════════════════════════════════════════════════
def test_the_posterior_covariance_is_bounded_by_the_prior_and_tau():
    """`Σ ⪯ Σ_post ⪯ (1+τ)Σ` — M 은 PSD 이고 최대 τΣ 다."""
    S, _pi, P, _Q, _n = _case()
    om = bl_omega(P, S, tau=TAU_DEFAULT)
    post = bl_posterior_cov(S, P, om, tau=TAU_DEFAULT)
    lo = np.linalg.eigvalsh(post - S).min()
    hi = np.linalg.eigvalsh((1 + TAU_DEFAULT) * S - post).min()
    assert lo >= -1e-12, "Σ_post 가 Σ 보다 작다 — M 이 PSD 가 아니다"
    assert hi >= -1e-12, "Σ_post 가 (1+τ)Σ 를 넘는다"


def test_a_zero_tau_leaves_the_covariance_untouched():
    """★짝★ τ=0 이면 사전에 불확실성이 없으므로 `Σ_post = Σ`."""
    S, _pi, P, _Q, _n = _case()
    om = bl_omega(P, S, tau=1e-12)
    assert np.allclose(bl_posterior_cov(S, P, om, tau=1e-12), S, atol=1e-8)


def test_a_certain_view_shrinks_the_posterior_toward_the_prior():
    """Ω→0 이면 뷰 방향의 불확실성이 사라져 `Σ_post` 가 `Σ` 에 가까워진다."""
    S, _pi, P, _Q, _n = _case()
    base = bl_omega(P, S, tau=TAU_DEFAULT)
    sure = bl_posterior_cov(S, P, base * 1e-8, tau=TAU_DEFAULT)
    unsure = bl_posterior_cov(S, P, base * 1e8, tau=TAU_DEFAULT)
    assert np.abs(sure - S).max() < np.abs(unsure - S).max()


# ══════════════════════════════════════════════════════════════════════════
# ★관례가 산출과 함께 다닌다 (P1 패턴)★
# ══════════════════════════════════════════════════════════════════════════
def test_the_solve_declares_its_convention():
    S, pi, P, Q, _n = _case()
    out = bl_solve(pi, S, P, Q, tau=TAU_DEFAULT, confidences=[30.0, 70.0])
    c = out["convention"]
    assert c["tau"] == TAU_DEFAULT
    assert c["ridge"] == RIDGE_DEFAULT
    assert c["omega_floor"] == OMEGA_FLOOR
    assert c["confidence_scaling"] is True
    assert c["declared"] is True


def test_the_convention_declares_that_the_posterior_cov_is_not_used():
    """★의도적 비연결을 관측 가능하게 만든다★

    Σ_post 를 최적화기에 연결해도 비중 변화가 0.70%p 로 무거래 밴드(1.00~4.19%p)
    아래라 거래가 발생하지 않는다. 이 사실을 신고하지 않으면 누군가 "빠뜨렸네"
    하고 **측정 없이** 연결한다.
    """
    S, pi, P, Q, _n = _case()
    c = bl_solve(pi, S, P, Q, tau=TAU_DEFAULT)["convention"]
    assert c["posterior_cov_used_in_optimizer"] is False
    assert c["posterior_cov_reason"], "비연결 사유가 없다"
    assert "%p" in c["posterior_cov_reason"] or "밴드" in c["posterior_cov_reason"]


def test_the_solve_returns_both_moments_and_the_omega():
    S, pi, P, Q, n = _case()
    out = bl_solve(pi, S, P, Q, tau=TAU_DEFAULT)
    assert out["mean"].shape == (n,)
    assert out["posterior_cov"].shape == (n, n)
    assert out["omega"].shape == (len(Q), len(Q))


def test_the_confidence_scaling_flag_reflects_the_input():
    S, pi, P, Q, _n = _case()
    assert bl_solve(pi, S, P, Q, tau=TAU_DEFAULT)[
        "convention"]["confidence_scaling"] is False


# ══════════════════════════════════════════════════════════════════════════
# 수치 안전 — ★분산이 0 인 뷰에서 터지지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_view_with_no_prior_variance_is_floored_not_infinite():
    """바닥이 없으면 `Ω⁻¹` 가 터진다 (CLAUDE.md 수치 안전)."""
    n = 4
    S = np.zeros((n, n))
    P = np.zeros((1, n)); P[0, 0] = 1
    om = bl_omega(P, S, tau=TAU_DEFAULT)
    assert np.all(np.isfinite(om))
    assert np.diag(om).min() >= OMEGA_FLOOR * 0.99


def test_the_omega_is_positive_definite():
    S, _pi, P, _Q, _n = _case()
    om = bl_omega(P, S, tau=TAU_DEFAULT, confidences=[99.9, 99.9])
    assert np.linalg.eigvalsh(om).min() > 0


# ══════════════════════════════════════════════════════════════════════════
# ★두 호출부의 값이 바뀌지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_studio_matches_the_shared_source():
    """`allocation_studio.bl_posterior` 는 얇은 위임이어야 한다."""
    from src.engine.allocation_studio import bl_posterior
    S, pi, P, Q, _n = _case()
    om = bl_omega(P, S, tau=TAU_DEFAULT)
    assert np.allclose(bl_posterior(pi, S, P, Q, om, TAU_DEFAULT),
                       bl_posterior_mean(pi, S, P, Q, om, tau=TAU_DEFAULT))


def test_unifying_the_ridge_changes_almost_nothing():
    """★공개하는 유일한 변경★ `risk_allocations` 의 ridge 1e-8 → 1e-10.

    실측 `max|Δw| = 7.5e-7` 로 P1 에서 관측한 CPU 흔들림(~6e-7)과 같은 자릿수다.
    그 자리에서 비트 동일을 고집하는 것은 의미가 없다 — 크기를 못 박고 공개한다.
    """
    from src.engine.allocation_studio import _max_sharpe_w
    S, pi, P, Q, n = _case()
    base = np.diag(np.maximum(np.diag(P @ (TAU_DEFAULT * S) @ P.T), OMEGA_FLOOR))
    old = base + np.eye(len(Q)) * 1e-8
    new = base + np.eye(len(Q)) * RIDGE_DEFAULT
    w_old = _max_sharpe_w(bl_posterior_mean(pi, S, P, Q, old, tau=TAU_DEFAULT), S, n)
    w_new = _max_sharpe_w(bl_posterior_mean(pi, S, P, Q, new, tau=TAU_DEFAULT), S, n)
    assert np.abs(w_old - w_new).max() < 1e-5


def test_tau_changes_the_posterior_mean():
    """★τ 는 사전 불확실성이다 — 무시되면 뷰의 상대 무게가 달라진다★

    변이 V4(τ 무시)가 살아남아서 찾았다. τ 테스트가 Ω 와 Σ_post 에만 있었고
    **사후 평균**에는 없었다.
    """
    S, pi, P, Q, _n = _case()
    om = bl_omega(P, S, tau=TAU_DEFAULT)
    lo = bl_posterior_mean(pi, S, P, Q, om, tau=0.01)
    hi = bl_posterior_mean(pi, S, P, Q, om, tau=0.50)
    assert not np.allclose(lo, hi), "τ 가 사후 평균에 아무 영향을 주지 않는다"
    # τ 가 클수록 사전이 약해지므로 사후가 뷰 쪽으로 더 간다.
    assert np.abs(P @ hi - Q).max() < np.abs(P @ lo - Q).max()


def test_the_omega_floor_is_a_live_parameter():
    """★바닥이 ridge 에 가려져 있었다★

    변이 V5(바닥 제거)가 살아남았다 — 바닥과 ridge 가 둘 다 `1e-10` 이라
    제로분산 뷰에서 ridge 만으로도 양수가 나왔기 때문이다. 바닥이 **실제로
    작동하는지**는 ridge 보다 큰 값을 줘야 보인다.
    """
    n = 4
    S = np.zeros((n, n))
    P = np.zeros((1, n)); P[0, 0] = 1
    tight = bl_omega(P, S, tau=TAU_DEFAULT, floor=OMEGA_FLOOR)
    loose = bl_omega(P, S, tau=TAU_DEFAULT, floor=1e-6)
    assert loose[0, 0] > tight[0, 0] * 100, "바닥이 Ω 를 움직이지 않는다"
    assert loose[0, 0] >= 1e-6


# ══════════════════════════════════════════════════════════════════════════
# ★두 호출부가 정말 단일 출처를 쓰는가 — 구조로 강제한다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_studio_does_not_build_its_own_omega():
    """★변이 V12 가 이것 없이 살아남았다★

    복사본이 되살아나면 **값이 같아도** 갈라질 씨앗이 다시 심긴다 — 실제로
    그렇게 9%p 가 벌어졌다. 값 테스트로는 잡히지 않으므로 구조를 본다
    (P1 의 `test_the_backtest_no_longer_computes_ratios_inline` 과 같은 이유).
    """
    import inspect

    from src.engine.allocation_studio import build_user_views
    src = inspect.getsource(build_user_views)
    assert "bl_omega" in src, "단일 출처를 부르지 않는다"
    assert "np.diag(base" not in src and "_np.diag" not in src, (
        "Ω 를 여기서 다시 만들고 있다")


def test_the_regime_strategy_passes_no_confidence():
    """★변이 V13 이 이것 없이 살아남았다★

    `s_black_litterman` 은 매크로 틸트 맵이라 **뷰별 신뢰도가 없다**. 신뢰도를
    켜면 없는 정보를 지어내는 것이고, 실측상 9%p 를 움직인다.


    ★산문이 아니라 코드를 본다★ 처음에는 `"confidences=None" in src` 로 걸었는데
    바로 위 **주석**에 그 문자열이 있어서 변이가 살아남았다 — `adj_close` 가드에서
    겪은 것과 같은 함정이다. AST 로 `bl_omega(...)` 호출의 키워드 인자를 본다.
    """
    import ast
    import inspect
    import textwrap

    from src.engine.risk_allocations import s_black_litterman
    tree = ast.parse(textwrap.dedent(inspect.getsource(s_black_litterman)))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if getattr(fn, "id", None) != "bl_omega" and getattr(fn, "attr", None) != "bl_omega":
            continue
        for kw in node.keywords:
            if kw.arg == "confidences":
                found.append(isinstance(kw.value, ast.Constant) and kw.value.value is None)
    assert found, "`bl_omega` 를 `confidences=` 없이 부른다 — 기본값에 기대면 안 된다"
    assert all(found), (
        "신뢰도 인자가 명시적으로 None 이 아니다 — 없는 정보를 지어낼 수 있다")


def test_the_optimizer_never_receives_the_posterior_covariance():
    """★정적 강제★ Σ_post 는 진단이다 — 최적화기에 들어가면 배분 정책 변경이고
    CLAUDE.md §3 별도 승인 사항이다. 측정 없이 연결되는 것을 막는다."""
    import inspect

    import src.engine.allocation_studio as st
    src = inspect.getsource(st)
    assert "posterior_cov" not in src, (
        "allocation_studio 가 사후 공분산을 쓴다 — 밴드보다 큰 효과를 먼저 "
        "보이고 별도 승인을 받아야 한다")
