"""예측 결합 — 단일 forecast 를 믿지 않는다 (Brief §6)

★이 파일이 거는 것★
  1. ★독립 가정이 정밀도를 부풀린다★ 실측: 올바른 ρ 로는 이득 0.0~0.1%,
     독립으로 두면 **22~23%** 를 주장한다. 없는 정보를 만들어 내는 것이다.
  2. ★상관된 예측은 공짜 정밀도를 주지 않는다★ ρ 가 높을수록 가장 정밀한
     하나로 수렴하고, 결합 SE 가 최선 개별 SE 보다 **작아지지 않는다**.
  3. ★결합값이 입력 범위를 벗어나지 않는다★ 교과서 GLS 는 벗어난다(실측
     ρ=0.99 에서 가중 [3.92, −2.92], 결합 μ −7.5%).
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.forecast_combination import (  # noqa: E402
    COLLAPSE_WEIGHT,
    combine_forecasts,
    correlation_from_windows,
    overlap_correlation,
)

MU_A = np.array([0.10, 0.05])
SE_A = np.array([0.166, 0.20])
MU_B = np.array([0.16, 0.09])
SE_B = np.array([0.200, 0.25])


def _pair(mu_a=MU_A, se_a=SE_A, mu_b=MU_B, se_b=SE_B) -> list[dict]:
    return [{"name": "a", "mu": mu_a, "se": se_a},
            {"name": "b", "mu": mu_b, "se": se_b}]


def _rho(r: float) -> np.ndarray:
    C = np.full((2, 2), r)
    np.fill_diagonal(C, 1.0)
    return C


# ── 1. ★상관을 무시하면 정밀도가 부풀려진다★ ────────────────────────────
def test_assuming_independence_overstates_the_precision_gain():
    """★실측★ 올바른 ρ=0.8165 로는 이득 0.0~0.1%, 독립 가정은 22~23%."""
    indep = combine_forecasts(_pair())
    aware = combine_forecasts(_pair(), correlation=_rho(0.8165))
    assert indep["available"] and aware["available"]
    for i in range(len(MU_A)):
        assert indep["precision_gain_pct"][i] > aware["precision_gain_pct"][i], i
    assert indep["assumed_independent"] is True
    assert "부풀려집니다" in indep["correlation_note"]


def test_a_supplied_correlation_makes_no_independence_claim():
    """★짝★ 상관을 주면 독립을 주장하지 않는다."""
    out = combine_forecasts(_pair(), correlation=_rho(0.5))
    assert out["assumed_independent"] is False
    assert out["correlation_note"] is None


# ── 2. ★공짜 정밀도는 없다★ ─────────────────────────────────────────────
@pytest.mark.parametrize("rho", [0.0, 0.3, 0.6, 0.9, 0.99, 1.0])
def test_the_combined_error_never_beats_the_best_single_forecast(rho):
    """★이것이 무너지면 없는 정보를 만든 것이다★"""
    out = combine_forecasts(_pair(), correlation=_rho(rho))
    best = np.minimum(SE_A, SE_B)
    assert np.all(np.asarray(out["se"]) <= best + 1e-9), (out["se"], best)


@pytest.mark.parametrize("rho", [0.0, 0.3, 0.6, 0.9, 0.99, 1.0])
def test_the_combined_mu_stays_inside_the_input_range(rho):
    """★교과서 GLS 는 벗어난다★ ρ=0.99 에서 −7.5%(입력 10%·16% 바깥)였다."""
    out = combine_forecasts(_pair(), correlation=_rho(rho))
    lo, hi = np.minimum(MU_A, MU_B), np.maximum(MU_A, MU_B)
    mu = np.asarray(out["mu"])
    assert np.all(mu >= lo - 1e-9) and np.all(mu <= hi + 1e-9), (mu, lo, hi)


def test_high_correlation_collapses_onto_the_most_precise_forecast():
    """상관된 예측은 하나 이상의 정보를 주지 않는다."""
    out = combine_forecasts(_pair(), correlation=_rho(0.99))
    assert out["mean_weights"]["a"] > out["mean_weights"]["b"], out["mean_weights"]
    assert out["mean_weights"]["a"] >= COLLAPSE_WEIGHT
    assert out["collapsed_to"] == ["a"]
    assert np.allclose(out["se"], SE_A, atol=1e-6), "최선 개별 SE 로 수렴한다"


def test_independent_forecasts_do_give_a_real_gain():
    """★짝★ 항상 이득이 0 이면 결합할 이유가 없다."""
    out = combine_forecasts(_pair(), correlation=_rho(0.0))
    assert all(g > 5.0 for g in out["precision_gain_pct"]), out["precision_gain_pct"]
    assert out["collapsed_to"] is None
    assert out["effective_forecasts"] > 1.5


def test_the_weights_are_non_negative_and_sum_to_one():
    """★음수 가중이 GLS 를 무너뜨린 원인이다★"""
    for rho in (0.0, 0.5, 0.95, 1.0):
        out = combine_forecasts(_pair(), correlation=_rho(rho))
        cols = np.array([out["weights"][n] for n in out["names"]])
        assert np.all(cols >= -1e-9), (rho, cols)
        assert np.allclose(cols.sum(axis=0), 1.0, atol=1e-6), (rho, cols)


def test_effective_forecasts_falls_as_correlation_rises():
    lo = combine_forecasts(_pair(), correlation=_rho(0.0))["effective_forecasts"]
    hi = combine_forecasts(_pair(), correlation=_rho(0.99))["effective_forecasts"]
    assert lo > hi and hi == pytest.approx(1.0, abs=0.1)


# ── 3. ★겹침에서 상관을 계산한다★ ───────────────────────────────────────
def test_the_overlap_correlation_formula():
    """★실측★ 트레일링 36개월 · 국면 24개월 · 겹침 24 → ρ = 0.8165."""
    out = overlap_correlation(36, 24, 24)
    assert out["available"] is True
    assert out["rho"] == pytest.approx(24 / np.sqrt(36 * 24), abs=1e-4)
    assert out["rho"] == pytest.approx(0.8165, abs=1e-3)


def test_no_overlap_means_no_correlation():
    assert overlap_correlation(36, 24, 0)["rho"] == 0.0


def test_full_overlap_of_equal_windows_is_one():
    assert overlap_correlation(24, 24, 24)["rho"] == pytest.approx(1.0)


def test_an_impossible_overlap_is_refused():
    assert overlap_correlation(10, 5, 8)["available"] is False
    assert overlap_correlation(0, 5, 0)["available"] is False


def test_windows_build_the_correlation_matrix():
    fc = [{"name": "trailing", "months": {f"2021-{i:02d}" for i in range(1, 13)}},
          {"name": "conditional", "months": {f"2021-{i:02d}" for i in range(1, 7)}}]
    out = correlation_from_windows(fc)
    assert out["available"] is True
    assert out["matrix"][0, 1] == pytest.approx(6 / np.sqrt(12 * 6), abs=1e-4)
    assert out["pairs"][0]["n_shared"] == 6


def test_a_missing_window_is_reported_not_assumed_independent():
    """★창을 모르면 독립이라고 **주장**하지 않는다★"""
    fc = [{"name": "a", "months": {"2021-01"}}, {"name": "b"}]
    out = correlation_from_windows(fc)
    assert out["pairs"][0]["available"] is False
    assert "창을 알 수 없어" in out["pairs"][0]["reason"]


# ── 4. 낼 수 없으면 사유 ────────────────────────────────────────────────
def test_no_usable_forecast_is_a_reason():
    assert combine_forecasts([])["available"] is False
    assert combine_forecasts([{"name": "x"}])["available"] is False


def test_mismatched_shapes_are_refused():
    bad = [{"name": "a", "mu": MU_A, "se": SE_A},
           {"name": "b", "mu": np.array([0.1]), "se": np.array([0.2])}]
    assert combine_forecasts(bad)["available"] is False


def test_a_zero_standard_error_is_refused():
    """SE=0 이면 그 예측이 확실하다는 뜻인데, 추정된 예측에 그런 것은 없다."""
    bad = [{"name": "a", "mu": MU_A, "se": np.array([0.0, 0.2])},
           {"name": "b", "mu": MU_B, "se": SE_B}]
    assert combine_forecasts(bad)["available"] is False


def test_non_finite_forecasts_are_refused():
    bad = [{"name": "a", "mu": np.array([np.nan, 0.05]), "se": SE_A},
           {"name": "b", "mu": MU_B, "se": SE_B}]
    assert combine_forecasts(bad)["available"] is False


def test_a_single_forecast_passes_through():
    out = combine_forecasts([{"name": "only", "mu": MU_A, "se": SE_A}])
    assert out["available"] is True
    assert np.allclose(out["mu"], MU_A) and np.allclose(out["se"], SE_A)
    assert out["effective_forecasts"] == pytest.approx(1.0)


def test_a_wrong_correlation_shape_is_refused():
    out = combine_forecasts(_pair(), correlation=np.eye(3))
    assert out["available"] is False and "모양" in out["reason"]


def test_the_method_declares_the_constraint():
    out = combine_forecasts(_pair(), correlation=_rho(0.5))
    assert out["method"] == "nonnegative_min_variance"
    assert "음수로 두지 않습니다" in out["note"]
