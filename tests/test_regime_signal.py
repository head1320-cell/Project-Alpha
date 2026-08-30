"""③ 신호 수준 관문 — ★국면이 **다음 달** 수익을 설명하는가★ (A4)
==============================================================================
감사가 낸 부채: 신호 수준(③) 관문이 **하중이 아니고**, 국면→자산수익 관문은
아예 없었다. 배분 성과(④)로만 판정하면 국면 정보가 없어도 비용·제약 구조가
Sharpe 를 움직여 통과할 수 있다.

★동시대와 선행을 반드시 가른다★

| 지평 | 묻는 것 | 어느 질문 |
|---|---|---|
| `horizon=0` 동시대 | 라벨 t 가 수익 t 를 설명하는가 | ①정보 표현력 |
| `horizon=1` **선행** | 라벨 t 가 수익 **t+1** 을 설명하는가 | ★③예측 스킬★ |

합성 패널에서 둘이 비슷하게 나오는 이유는 국면 과정이 **지속적**이기 때문이다
(`_P_TRUE` 대각 0.65~0.75). 그 사실을 모른 채 동시대 η² 을 "예측력" 으로 읽으면
정확히 만다트가 금지한 혼동이다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.engine.regime_signal import (  # noqa: E402
    HORIZON_CONTEMPORANEOUS,
    HORIZON_FORWARD,
    align,
    eta_squared,
    monthly_matrix,
)


# ══════════════════════════════════════════════════════════════════════════
# η² 자체 — ★규칙을 정확한 수로 검사한다★
# ══════════════════════════════════════════════════════════════════════════
def test_perfectly_separated_groups_explain_everything():
    m = np.array([[1.0], [1.0], [-1.0], [-1.0]])
    assert eta_squared(["A", "A", "B", "B"], m) == pytest.approx(1.0)


def test_labels_that_carry_no_information_explain_nothing():
    """★짝★ — 언제나 큰 값을 내는 구현을 배제한다."""
    # 값은 크게 움직이지만 라벨이 그 움직임과 **정렬되지 않는다** —
    # 두 그룹의 평균이 똑같이 0 이라 국면 간 제곱합이 0 이다.
    m = np.array([[1.0], [1.0], [-1.0], [-1.0]])
    assert eta_squared(["A", "B", "A", "B"], m) == pytest.approx(0.0, abs=1e-12)


def test_a_single_label_explains_nothing():
    """국면이 하나뿐이면 국면 간 차이가 없다 — ★0 이지 미상이 아니다★."""
    m = np.array([[1.0], [-1.0], [2.0], [0.5]])
    assert eta_squared(["A"] * 4, m) == pytest.approx(0.0, abs=1e-12)


def test_each_asset_is_demeaned_before_pooling():
    """★자산 간 수준 차이가 η² 로 새지 않는다★

    두 자산의 평균이 크게 다르면, 디민하지 않고 풀링할 경우 라벨과 무관한
    자산 효과가 국면 간 제곱합으로 흘러든다.
    """
    m = np.array([[100.0, 0.0], [100.0, 0.0], [100.0, 0.0], [100.0, 0.0]])
    assert eta_squared(["A", "A", "B", "B"], m) is None      # 분산이 0 → 미상


def test_a_constant_panel_has_no_variance_to_explain():
    """★미상 ≠ 0★ 설명할 분산이 없으면 비율이 정의되지 않는다."""
    assert eta_squared(["A", "B"], np.zeros((2, 3))) is None


def test_too_few_observations_are_unknown_not_zero():
    assert eta_squared(["A"], np.array([[1.0]])) is None
    assert eta_squared([], np.zeros((0, 2))) is None


def test_mismatched_lengths_are_refused():
    """★조용히 자르지 않는다★ — 길이가 안 맞으면 정렬이 틀린 것이다."""
    with pytest.raises(ValueError):
        eta_squared(["A", "B"], np.zeros((3, 2)))


def test_eta_squared_stays_between_zero_and_one():
    rng = np.random.default_rng(0)
    for _ in range(20):
        m = rng.normal(0, 1, (40, 4))
        lab = list(rng.choice(["A", "B", "C"], 40))
        v = eta_squared(lab, m)
        assert 0.0 <= v <= 1.0


# ══════════════════════════════════════════════════════════════════════════
# 월 집계
# ══════════════════════════════════════════════════════════════════════════
def _daily(n_months=6, n_assets=3, seed=0):
    idx = pd.bdate_range("2020-01-01", periods=n_months * 21, freq="C")
    rng = np.random.default_rng(seed)
    return rng.normal(0, 0.01, (len(idx), n_assets)), list(idx)


def test_monthly_returns_sum_the_daily_ones_within_each_month():
    R, dates = _daily()
    m = monthly_matrix(R, dates)
    months = sorted({d.strftime("%Y-%m") for d in dates})
    assert m.shape == (len(months), R.shape[1])
    first = np.array([d.strftime("%Y-%m") for d in dates]) == months[0]
    assert m[0] == pytest.approx(R[first].sum(axis=0))


def test_monthly_rows_are_ordered_by_month():
    R, dates = _daily(n_months=8)
    m = monthly_matrix(R, dates)
    assert len(m) == len({d.strftime("%Y-%m") for d in dates})


# ══════════════════════════════════════════════════════════════════════════
# ★정렬 — ①정보 표현력과 ③예측 스킬을 가르는 한 줄★
# ══════════════════════════════════════════════════════════════════════════
def test_the_contemporaneous_horizon_pairs_a_label_with_its_own_month():
    lab = ["A", "B", "C", "D"]
    m = np.arange(8.0).reshape(4, 2)
    ls, ms = align(lab, m, horizon=HORIZON_CONTEMPORANEOUS)
    assert ls == lab
    assert np.array_equal(ms, m)


def test_the_forward_horizon_pairs_a_label_with_the_next_month():
    """★PIT★ 라벨 t 는 t 시점에 알 수 있는 것이고 수익은 t+1 이다."""
    lab = ["A", "B", "C", "D"]
    m = np.arange(8.0).reshape(4, 2)
    ls, ms = align(lab, m, horizon=HORIZON_FORWARD)
    assert ls == ["A", "B", "C"]
    assert np.array_equal(ms, m[1:])
    assert len(ls) == len(ms) == 3


def test_the_forward_horizon_never_uses_a_future_label():
    """★짝 — 미래 관측 도입 변이를 죽인다★ (만다트 §42)

    선행 정렬에서 마지막 라벨은 짝지을 수익이 없으므로 **버려진다**. 라벨을
    그대로 두고 수익만 밀면 라벨 t 가 수익 t 를 보는 셈이 된다.
    """
    lab = ["A", "B", "C", "D"]
    m = np.arange(8.0).reshape(4, 2)
    ls, ms = align(lab, m, horizon=HORIZON_FORWARD)
    assert "D" not in ls
    assert not np.array_equal(ms[0], m[0])       # 첫 수익이 밀렸다


def test_a_longer_horizon_drops_more_rows():
    lab = list("ABCDE")
    m = np.arange(10.0).reshape(5, 2)
    for h in (0, 1, 2, 3):
        ls, ms = align(lab, m, horizon=h)
        assert len(ls) == len(ms) == 5 - h


def test_a_horizon_longer_than_the_panel_yields_nothing():
    ls, ms = align(list("AB"), np.zeros((2, 2)), horizon=5)
    assert ls == [] and len(ms) == 0


def test_a_negative_horizon_is_refused():
    """★음의 지평은 미래 라벨로 과거를 설명하는 것이다 — 룩어헤드.★"""
    with pytest.raises(ValueError):
        align(list("AB"), np.zeros((2, 2)), horizon=-1)
