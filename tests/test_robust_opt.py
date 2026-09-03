"""로버스트 최적화 — μ 를 얼마나 모르는지를 최적화에 넣는다 (Brief §8.3)

★이 파일이 거는 것★
  1. ★불확실성을 **잰다**★ SE·|μ|/SE 를 내고, 0과 구분되지 않는 μ 를 그렇다고 말한다.
  2. ★κ 가 커질수록 **분산**된다★ 이것이 로버스트의 정의다. 첫 구현이 정확히
     반대(100% 집중)로 갔으므로 이 성질을 단조성으로 못박는다.
  3. ★박스가 아니라 타원체★ 박스는 실측에서 HHI 0.616→0.578 로 거의 안 움직였다.

합성 수익률을 쓰되 **성질**을 잰다 — 특정 숫자가 아니라 단조성·수렴을 본다.
실데이터 검산은 `test_robust_opt_wiring.py` 가 한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.robust_opt import (  # noqa: E402
    KAPPA_PRESETS,
    mu_standard_errors,
    robust_weights,
    uncertainty_scalar,
)

NAMES = ["A", "B", "C", "D"]
SEED = 20260823


def _returns(n_days: int = 756, n: int = 4, seed: int = SEED,
             drift=(0.0008, 0.0004, 0.0002, 0.0000)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0, 0.012, size=(n_days, n))
    common = rng.normal(0.0, 0.008, size=(n_days, 1))
    return base + common + np.array(drift[:n])


def _hhi(w) -> float:
    return float((np.asarray(w) ** 2).sum())


# ── 1. ★불확실성을 잰다★ ──────────────────────────────────────────────────
def test_the_standard_error_of_the_mean_is_reported():
    est = mu_standard_errors(_returns())
    assert est["available"] is True
    assert len(est["se"]) == 4 and np.all(est["se"] > 0)
    assert est["years"] == pytest.approx(3.0, abs=0.01)


def test_a_longer_sample_shrinks_the_standard_error():
    """★표본이 길수록 덜 모른다★ SE ∝ 1/√T 가 실제로 성립하는지."""
    short = mu_standard_errors(_returns(252))["se"].mean()
    long = mu_standard_errors(_returns(1008))["se"].mean()
    assert long < short
    assert long == pytest.approx(short / 2.0, rel=0.25), "1/√T 스케일"


def test_assets_whose_mean_is_indistinguishable_from_zero_are_flagged():
    """★|μ|/SE < 2 면 그 μ 에 비중을 거는 것은 잡음에 거는 것이다★

    ★앞 판본은 `n_resolvable == sum(resolvable)` 만 봤다★ 그것은 전부 True 로
    만들어도 성립하는 **공허한 단언**이었고 변이 프로브가 green 으로 그것을
    드러냈다. 실제 분류를 못박는다 — 이 표본은 [T, T, F, F] 로 갈린다.
    """
    est = mu_standard_errors(_returns())
    t, res = est["t"], est["resolvable"]
    assert len(res) == 4

    # ★섞여 있어야 한다★ 전부 True 나 전부 False 면 분류가 일어나지 않은 것이다.
    assert any(res) and not all(res), (list(t), res)
    for ti, ri in zip(t, res, strict=True):
        assert ri == bool(ti >= 2.0), f"t={ti} 인데 resolvable={ri}"
    assert est["n_resolvable"] == sum(res)
    assert "0과 구분되지 않습니다" in est["note"]


def test_a_pure_noise_asset_is_never_resolvable():
    """★짝★ 드리프트가 0 인 자산은 구분되지 않아야 한다."""
    est = mu_standard_errors(_returns(drift=(0.0, 0.0, 0.0, 0.0), seed=7))
    assert est["n_resolvable"] == 0, list(est["t"])


def test_a_strong_signal_is_resolvable():
    """★짝의 짝★ 신호가 충분히 크면 구분된다 — 전부 False 로 만들어도 안 된다."""
    est = mu_standard_errors(_returns(drift=(0.010, 0.0, 0.0, 0.0)))
    assert est["resolvable"][0] is True
    assert est["t"][0] > 5.0


def test_a_tiny_sample_is_a_reason_not_a_number():
    assert mu_standard_errors(np.zeros((1, 4)))["available"] is False


def test_the_uncertainty_scalar_spans_zero_to_one():
    assert uncertainty_scalar(np.array([10.0, 10.0])) == 0.0, "확신하면 0"
    assert uncertainty_scalar(np.array([0.0, 0.0])) == 1.0, "정보 없으면 1"
    mid = uncertainty_scalar(np.array([1.0, 1.0]))
    assert 0.0 < mid < 1.0
    assert uncertainty_scalar(np.array([])) == 1.0


# ── 2. ★κ 가 커질수록 분산된다★ ───────────────────────────────────────────
def test_more_uncertainty_means_more_diversification():
    """★로버스트의 정의★ 첫 구현은 정확히 반대로 갔다(100% 한 종목).

    `μ̂ − κ` 를 max-Sharpe 에 넣으면 위험 페널티가 없어 순위만 보고 집중한다.
    로버스트는 평균-분산 **효용**을 최대화해야 한다.
    """
    R = _returns()
    hhis = []
    for k in (0.0, 1.0, 1.645, 2.576, 5.0):
        out = robust_weights(NAMES, R, kappa=k)
        assert out["available"] is True, out["reason"]
        hhis.append(_hhi(out["weights"]))
    assert hhis == sorted(hhis, reverse=True), f"단조 감소해야 한다: {hhis}"
    assert hhis[0] - hhis[-1] > 0.05, f"거의 안 움직이면 박스와 같다: {hhis}"


def test_it_converges_toward_equal_weight():
    """μ 를 전혀 못 믿으면 μ 를 쓰지 않는 배분으로 간다."""
    out = robust_weights(NAMES, _returns(), kappa=50.0)
    assert out["available"] is True
    assert _hhi(out["weights"]) == pytest.approx(1.0 / len(NAMES), abs=0.02)
    assert out["collapsed_to_equal_weight"] is True


def test_the_collapse_is_announced_not_hidden():
    """★숫자만 보면 '최적화했다' 로 읽힌다★ 실제로는 μ 를 안 쓰기로 한 것이다."""
    R = _returns()
    assert robust_weights(NAMES, R, kappa=0.0)["collapsed_to_equal_weight"] is False
    assert robust_weights(NAMES, R, kappa=50.0)["collapsed_to_equal_weight"] is True


def test_kappa_zero_reproduces_the_non_robust_solution():
    """★짝★ κ=0 이면 페널티가 없으므로 평문 평균-분산과 같아야 한다."""
    out = robust_weights(NAMES, _returns(), kappa=0.0)
    assert out["concentration"]["hhi"] == pytest.approx(
        out["concentration"]["hhi_naive"], abs=1e-6)


def test_a_robust_run_reports_how_much_it_moved_from_naive():
    out = robust_weights(NAMES, _returns(), kappa=2.576)
    c = out["concentration"]
    assert c["hhi"] < c["hhi_naive"], "로버스트가 평문보다 분산돼야 한다"
    assert c["hhi_equal_weight"] == pytest.approx(0.25)


def test_the_effective_number_of_bets_is_reused_not_reinvented():
    """★§8.4 는 이미 있다★ `effective_number_of_bets` 를 다시 짜지 않는다."""
    lo = robust_weights(NAMES, _returns(), kappa=0.0)["concentration"]["enb"]
    hi = robust_weights(NAMES, _returns(), kappa=2.576)["concentration"]["enb"]
    assert hi > lo, "분산될수록 베팅 유효개수가 늘어야 한다"
    assert 1.0 <= lo <= len(NAMES) and 1.0 <= hi <= len(NAMES)


def test_an_asset_excluded_by_naive_mu_comes_back_as_uncertainty_grows():
    """★μ 를 못 믿으면 어느 자산도 완전히 배제하지 않는다★"""
    R = _returns(drift=(0.0010, 0.0005, 0.0002, -0.0004))
    naive = robust_weights(NAMES, R, kappa=0.0)["weights"]
    rob = robust_weights(NAMES, R, kappa=5.0)["weights"]
    worst = int(np.argmin(naive))
    assert rob[worst] > naive[worst]


# ── 3. 계약과 정직성 ───────────────────────────────────────────────────────
def test_weights_are_a_long_only_simplex():
    w = robust_weights(NAMES, _returns(), kappa=1.645)["weights"]
    assert np.all(w >= -1e-9)
    assert w.sum() == pytest.approx(1.0, abs=1e-6)


def test_the_presets_read_as_confidence_levels():
    assert KAPPA_PRESETS["none"] == 0.0
    assert KAPPA_PRESETS["medium"] == pytest.approx(1.6449, abs=1e-3)   # 90%
    assert KAPPA_PRESETS["high"] == pytest.approx(2.5758, abs=1e-3)     # 99%
    assert KAPPA_PRESETS["low"] < KAPPA_PRESETS["medium"] < KAPPA_PRESETS["high"]


def test_a_negative_kappa_is_refused():
    assert robust_weights(NAMES, _returns(), kappa=-1.0)["available"] is False


def test_a_non_positive_delta_is_refused():
    assert robust_weights(NAMES, _returns(), delta=0.0)["available"] is False


def test_a_shape_mismatch_is_a_reason_not_a_crash():
    out = robust_weights(NAMES, _returns(n=3), kappa=1.0)
    assert out["available"] is False and "모양" in out["reason"]


def test_a_supplied_covariance_is_used():
    """조건부 Σ 를 그대로 받는다 — P2.5 와 같은 주입 지점."""
    R = _returns()
    tight = np.eye(4) * 0.0004
    out = robust_weights(NAMES, R, kappa=1.0, s_override=tight)
    assert out["available"] is True
    base = robust_weights(NAMES, R, kappa=1.0)
    assert not np.allclose(out["weights"], base["weights"])


def test_every_asset_reports_its_own_mu_se_and_t():
    out = robust_weights(NAMES, _returns(), kappa=1.645)
    for key in ("mu_annual", "se_annual", "mu_over_se"):
        assert set(out[key]) == set(NAMES), key
    assert out["uncertainty"] == pytest.approx(
        uncertainty_scalar(np.array([out["mu_over_se"][n] for n in NAMES])), abs=1e-3)
