"""검정력 산출 ★"무엇을 답할 수 있었나" 를 판정 옆에 싣는다★ (A1)
==============================================================================
감사(`7313371`)가 낸 최상위 통계 부채: **어떤 관문도 MDE·검정력을 보고하지
않는다.** M1~M5 는 양성 통제에서 심은 효과 1× 의 검출률이 40% 인데 "불통과" 만
적었다 — 관문이 고장난 것이 아니라 **찾을 힘이 없었다**는 사실이 리포트에
없었다.

★의존성을 뒤집었다★ 이 모듈은 하네스를 import 하지 않고 **시행 함수를 주입**
받는다. 그래서 합성 시행으로 규칙 자체를 정확히 검사할 수 있고, 하네스가 바뀌어도
깨지지 않는다.

★"492 자산-월" 은 독립 표본이 아니다★ 실측에서 자산간 상관이 N 과 무관하게
~0.58 로 고정이었다 — 국면은 공통인자라 유효 관측이 월당 ~1개다. `effective_n`
이 그 사실을 수치로 만든다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.research_power import (  # noqa: E402
    DEFAULT_TARGET_POWER,
    design_effect,
    detection_rate,
    effective_n,
    mde_from_curve,
    mean_pairwise_correlation,
    power_curve,
    power_report,
    wilson_interval,
)


# ══════════════════════════════════════════════════════════════════════════
# ★유효 표본 — 자산을 늘려도 검정력이 안 늘어난 이유★
# ══════════════════════════════════════════════════════════════════════════
def test_the_design_effect_grows_with_the_common_factor_correlation():
    assert design_effect(6, 0.0) == pytest.approx(1.0)
    assert design_effect(6, 0.58) == pytest.approx(3.9)
    assert design_effect(1, 0.58) == pytest.approx(1.0)


def test_a_negative_mean_correlation_does_not_buy_extra_sample():
    """★음의 상관이 표본을 늘려 준다고 주장하지 않는다★ — 보수적으로 1 에서 자른다.

    설계효과 < 1 은 "N·T 보다 많은 독립 관측" 을 뜻하는데, 그것은 이 관문이
    사려던 증거가 아니다. 미상보다 나쁜 것은 유리한 쪽으로 지어낸 값이다.
    """
    assert design_effect(6, -0.5) == pytest.approx(1.0)


def test_effective_n_is_far_below_the_naive_asset_month_count():
    """★실측 계약★ 6자산·84개월·ρ̄=0.58 → 504 가 아니라 ~129 (≈1.54·T)."""
    n_eff = effective_n(84, 6, 0.58)
    assert n_eff == pytest.approx(504 / 3.9, rel=1e-9)
    assert n_eff == pytest.approx(129.23, abs=0.01)
    assert n_eff < 504 / 3


def test_adding_assets_barely_moves_the_effective_sample_at_fixed_correlation():
    """★자산 말고 개월★ — 6→50 자산이 사는 것과 84→180 개월이 사는 것."""
    base = effective_n(84, 6, 0.58)
    more_assets = effective_n(84, 50, 0.58)
    more_months = effective_n(180, 6, 0.58)
    assert more_assets / base < 1.5          # 8배 자산이 1.5배도 못 산다
    assert more_months / base == pytest.approx(180 / 84, rel=1e-9)


def test_an_unknown_correlation_yields_an_unknown_effective_sample():
    """★미상 ≠ 0 · 미상 ≠ 무상관★"""
    assert design_effect(6, None) is None
    assert effective_n(84, 6, None) is None


def test_mean_pairwise_correlation_reads_the_off_diagonal_only():
    rng = np.random.default_rng(0)
    common = rng.normal(0, 1, 500)
    m = np.column_stack([common + rng.normal(0, 1, 500) for _ in range(4)])
    rho = mean_pairwise_correlation(m)
    assert 0.35 < rho < 0.65                 # 대각선 1.0 이 섞이면 훨씬 높아진다
    ind = rng.normal(0, 1, (500, 4))
    assert abs(mean_pairwise_correlation(ind)) < 0.15


def test_a_single_column_has_no_pairwise_correlation():
    """★짝이 없으면 상관도 없다 — 1.0 이 아니다.★"""
    assert mean_pairwise_correlation(np.zeros((100, 1))) is None


# ══════════════════════════════════════════════════════════════════════════
# 검출률 — ★미상 ≠ 실패★
# ══════════════════════════════════════════════════════════════════════════
def test_detection_rate_counts_only_resolved_trials():
    d = detection_rate([True, False, None, True, None])
    assert d["n"] == 5 and d["n_resolved"] == 3 and d["n_unknown"] == 2
    assert d["n_detected"] == 2
    assert d["rate"] == pytest.approx(2 / 3)


def test_all_unknown_trials_give_an_unknown_rate_with_a_reason():
    """★0% 가 아니다★ — 못 돌린 것과 못 찾은 것은 다른 진술이다."""
    d = detection_rate([None, None])
    assert d["rate"] is None
    assert d["reason"]


@pytest.mark.parametrize("outcomes,expected", [
    ([True] * 5, 1.0), ([False] * 5, 0.0), ([True, False], 0.5)])
def test_detection_rate_spans_both_extremes(outcomes, expected):
    """★상수를 내는 구현을 배제한다★ (§42 *probabilities hard-coded*)."""
    assert detection_rate(outcomes)["rate"] == pytest.approx(expected)


# ══════════════════════════════════════════════════════════════════════════
# ★5시드의 노이즈를 숨기지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_interval_is_much_wider_for_five_trials_than_five_hundred():
    """★§42 *confidence hard-coded*★ — 표본 수에 반응하지 않으면 구간이 아니다."""
    lo5, hi5 = wilson_interval(4, 5)
    lo500, hi500 = wilson_interval(400, 500)
    assert (hi5 - lo5) > 4 * (hi500 - lo500)
    assert 0.0 <= lo5 < 0.8 < hi5 <= 1.0


def test_the_interval_stays_inside_zero_and_one_at_the_extremes():
    assert wilson_interval(0, 5)[0] == pytest.approx(0.0)
    assert wilson_interval(5, 5)[1] == pytest.approx(1.0)


def test_no_trials_means_no_interval():
    assert wilson_interval(0, 0) is None


# ══════════════════════════════════════════════════════════════════════════
# 검정력 곡선과 MDE — ★주입된 시행으로 규칙만 검사한다★
# ══════════════════════════════════════════════════════════════════════════
def _step_trial(threshold: float):
    """척도가 임계 이상이면 반드시 검출되는 결정론적 시행."""
    return lambda scale, seed: scale >= threshold


def test_the_curve_is_ordered_by_scale_and_carries_the_rate():
    curve = power_curve(_step_trial(2.0), scales=[3.0, 1.0, 2.0], seeds=[0, 1])
    assert [c["scale"] for c in curve] == [1.0, 2.0, 3.0]
    assert [c["rate"] for c in curve] == [0.0, 1.0, 1.0]


def test_the_mde_is_the_smallest_scale_reaching_the_target_power():
    curve = power_curve(_step_trial(2.0), scales=[1.0, 2.0, 3.0], seeds=range(5))
    m = mde_from_curve(curve)
    assert m["mde"] == pytest.approx(2.0)
    assert m["bracket"] == [pytest.approx(1.0), pytest.approx(2.0)]
    assert m["target_power"] == DEFAULT_TARGET_POWER
    assert m["monotone"] is True


def test_an_unreached_target_is_reported_as_unknown_not_as_the_largest_scale():
    """★§42 *fallback converted to success*★

    탐색 범위 안에서 목표에 도달하지 못했으면 MDE 는 **미상**이다. 탐색한 최대
    척도를 MDE 라고 적으면 "이 정도면 찾을 수 있다" 는 거짓 주장이 된다.
    """
    curve = power_curve(_step_trial(99.0), scales=[1.0, 2.0, 3.0], seeds=range(5))
    m = mde_from_curve(curve)
    assert m["mde"] is None
    assert m["reason"] and "도달" in m["reason"]
    assert m["searched_max"] == pytest.approx(3.0)
    assert m["max_rate"] == pytest.approx(0.0)


def test_reaching_the_target_at_the_smallest_scale_is_flagged_as_a_bound():
    """★상한이 아니라 하한을 봤다★ — 진짜 MDE 는 더 작을 수 있다."""
    curve = power_curve(_step_trial(0.0), scales=[1.0, 2.0], seeds=range(5))
    m = mde_from_curve(curve)
    assert m["mde"] == pytest.approx(1.0)
    assert m["at_search_floor"] is True
    assert m["bracket"] == [None, pytest.approx(1.0)]   # 아래쪽 끝을 모른다


def test_a_non_monotone_curve_is_declared_not_smoothed():
    """★실측 곡선은 40/80/0/80/60 이었다★ — 보간해 놓고 매끈한 척하지 않는다."""
    curve = [{"scale": 1.0, "rate": 0.4}, {"scale": 2.0, "rate": 0.8},
             {"scale": 3.0, "rate": 0.0}, {"scale": 4.0, "rate": 0.8}]
    m = mde_from_curve(curve)
    assert m["monotone"] is False
    assert m["mde"] == pytest.approx(2.0)      # 첫 교차를 쓴다
    assert m["crossings"] == 3


def test_a_curve_with_no_resolved_rate_gives_no_mde():
    m = mde_from_curve([{"scale": 1.0, "rate": None}])
    assert m["mde"] is None and m["reason"]


def test_the_mde_is_never_interpolated_between_grid_points():
    """★재지 않은 정밀도를 지어내지 않는다★

    1× 에서 60%, 2× 에서 100% 라면 격자가 말해 주는 것은 "1× 로는 부족하고 2× 면
    충분하다" 뿐이다. 선형 보간으로 "MDE = 1.5" 라고 적으면 시험하지 않은 척도의
    검정력을 주장하는 것이다. 시험한 척도를 적고 참값이 든 구간을 함께 낸다.
    """
    curve = [{"scale": 1.0, "rate": 0.6}, {"scale": 2.0, "rate": 1.0}]
    m = mde_from_curve(curve)
    assert m["mde"] == pytest.approx(2.0)
    assert m["bracket"] == [pytest.approx(1.0), pytest.approx(2.0)]
    assert m["at_search_floor"] is False


def test_a_trial_that_raises_is_not_silently_counted_as_not_detected():
    """★침묵 폴백 금지★ 예외는 "못 찾았다" 가 아니다 — 신호로 남아야 한다."""
    def boom(scale, seed):
        raise RuntimeError("패널 생성 실패")
    with pytest.raises(RuntimeError):
        power_curve(boom, scales=[1.0], seeds=[0])


# ══════════════════════════════════════════════════════════════════════════
# 리포트 블록 — 모든 관문이 실을 형식
# ══════════════════════════════════════════════════════════════════════════
def test_the_report_carries_mde_power_and_n_eff_together():
    curve = power_curve(_step_trial(2.0), scales=[1.0, 2.0, 3.0], seeds=range(5))
    r = power_report(curve=curve, observed_scale=1.0,
                     n_obs=84, n_assets=6, rho_bar=0.58)
    assert r["mde"] == pytest.approx(2.0)
    assert r["power"] == pytest.approx(0.0)          # 관측 척도에서의 검출률
    assert r["n_eff"] == pytest.approx(129.23, abs=0.01)
    assert r["design_effect"] == pytest.approx(3.9)
    assert r["target_power"] == DEFAULT_TARGET_POWER
    assert r["power_ci"] is not None


def test_an_observed_scale_off_the_grid_gives_unknown_power_with_a_reason():
    """★격자에 없는 척도의 검정력을 지어내지 않는다★"""
    curve = power_curve(_step_trial(2.0), scales=[1.0, 2.0], seeds=range(3))
    r = power_report(curve=curve, observed_scale=1.5,
                     n_obs=84, n_assets=6, rho_bar=0.58)
    assert r["power"] is None
    assert r["reasons"]["power"]


def test_the_report_satisfies_the_required_field_check():
    """★A2 와의 계약★ — 이 블록을 그대로 실으면 리포트가 완전해진다."""
    from src.engine.research_verdict import require_power_fields
    curve = power_curve(_step_trial(2.0), scales=[1.0, 2.0], seeds=range(3))
    r = power_report(curve=curve, observed_scale=1.0,
                     n_obs=84, n_assets=6, rho_bar=0.58)
    assert require_power_fields(r) == []
    unknown = power_report(curve=[{"scale": 1.0, "rate": None}],
                           observed_scale=1.0, n_obs=84, n_assets=6, rho_bar=None)
    assert unknown["mde"] is None and unknown["n_eff"] is None
    assert require_power_fields(unknown) == []       # 전부 사유가 붙어 있다
