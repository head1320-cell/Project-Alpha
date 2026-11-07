"""`shrinkage_lambda` 계약 — ★dict 를 조용히 0.0 으로 읽지 않는다★ (T3 선행)
==============================================================================
전달계층 감사(`docs/specs/2026-08-25-transmission-layer-audit.md` §3)가 찾은 결함:

`conditional_moments` 는 **단일 국면**이라 `float` 을 내는데,
`regime_mixture_moments` 는 **국면별 dict** 를 냈다. 소비자
(`allocation_backtest._regime_override_at`)는
`float(lam) if isinstance(lam, (int, float)) else 0.0` 이라 **dict 면 조용히 0.0** 이
되고, 그러면 `conf = 50 × (1 − 0) = 50` — **최대 신뢰도**가 매 리밸런싱에 박힌다.

★"모르면 0" 은 여기서 최악의 기본값이다★ λ=0 은 "수축이 전혀 필요 없다 =
표본이 완벽하다" 는 뜻이고, 그것이 뷰를 **가장 강하게** 만든다. 즉 **읽지 못한 것이
확신을 최대로 올린다.** 잔여 모델리스크의 `Ξ=0` 과 정확히 같은 계열의 오류다.

그래서 이 계약은 셋을 요구한다:
1. 혼합도 **스칼라 집계값**을 낸다 — 소비자가 dict 를 만나지 않는다.
2. 집계 **의미를 값으로 선언**한다(`shrinkage_lambda_aggregate`).
3. 국면별 상세는 **버리지 않는다**(`shrinkage_lambda_by_regime`).
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.engine.conditional_market import (  # noqa: E402
    LAMBDA_AGGREGATE_PI_WEIGHTED,
    conditional_moments,
    regime_mixture_moments,
    resolve_shrinkage_lambda,
)

REGIMES = ["A", "B"]


def _frame(months: int = 30, n: int = 3, seed: int = 4):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=months * 21, freq="C")
    df = pd.DataFrame(rng.normal(0.0, 0.01, (len(idx), n)), index=idx,
                      columns=[f"X{i}" for i in range(n)])
    seen = sorted({d.strftime("%Y-%m") for d in idx})
    by_month = {m: ("A" if i % 2 == 0 else "B") for i, m in enumerate(seen)}
    return df, by_month


def _mix(h: int = 1):
    df, by_month = _frame()
    P = [[0.7, 0.3], [0.4, 0.6]]
    pi = np.array([1.0, 0.0])
    pis = [dict(zip(REGIMES, pi @ np.linalg.matrix_power(np.array(P), j), strict=True))
           for j in range(1, h + 1)]
    return regime_mixture_moments(df, by_month, pis, P, REGIMES, h_hold=h), df, by_month


# ══════════════════════════════════════════════════════════════════════════
# 1) 두 산출자가 같은 타입을 낸다
# ══════════════════════════════════════════════════════════════════════════
def test_single_regime_returns_scalar():
    df, by_month = _frame()
    cond = conditional_moments(df, by_month, "A")
    assert cond["available"] is True
    assert isinstance(cond["shrinkage_lambda"], float)


def test_mixture_also_returns_a_scalar():
    """★소비자가 dict 를 만나지 않는다★ — 이것이 결함의 직접적 수정이다."""
    mix, _, _ = _mix()
    assert mix["available"] is True
    assert isinstance(mix["shrinkage_lambda"], float), \
        f"혼합이 아직 {type(mix['shrinkage_lambda']).__name__} 를 낸다"
    assert 0.0 <= mix["shrinkage_lambda"] <= 1.0


def test_mixture_declares_the_aggregate_semantics():
    """★집계 방식을 값으로 선언한다★ — 소비자가 '평균이겠거니' 하지 않게."""
    mix, _, _ = _mix()
    assert mix["shrinkage_lambda_aggregate"] == LAMBDA_AGGREGATE_PI_WEIGHTED


def test_mixture_keeps_the_per_regime_detail():
    """집계했다고 국면별 값을 버리지 않는다 — 어느 국면이 얇은지가 사라지면 안 된다."""
    mix, _, _ = _mix()
    by = mix["shrinkage_lambda_by_regime"]
    assert isinstance(by, dict) and by
    assert all(isinstance(v, float) for v in by.values())


def test_aggregate_equals_pi_weighted_mean_of_the_parts():
    """★선언한 의미대로 계산됐는지 손으로 확인한다★ — 이름만 붙이는 것을 막는다."""
    mix, _, _ = _mix()
    by = mix["shrinkage_lambda_by_regime"]
    pi_bar = mix["pi_bar"]
    mass = sum(pi_bar[r] for r in by)
    expected = sum(pi_bar[r] * by[r] for r in by) / mass
    assert mix["shrinkage_lambda"] == pytest.approx(expected, abs=1e-12)


def test_onehot_mixture_matches_the_single_regime_value():
    """★극한 일치★ π 가 한 국면에 몰리면 집계값이 그 국면의 λ 와 같아야 한다."""
    df, by_month = _frame()
    P = [[1.0, 0.0], [0.4, 0.6]]                       # A 가 흡수
    pis = [{"A": 1.0, "B": 0.0}]
    mix = regime_mixture_moments(df, by_month, pis, P, REGIMES, h_hold=1)
    hard = conditional_moments(df, by_month, "A")
    assert mix["shrinkage_lambda"] == pytest.approx(hard["shrinkage_lambda"], abs=1e-12)


# ══════════════════════════════════════════════════════════════════════════
# 2) ★"모르면 0" 을 금지한다★
# ══════════════════════════════════════════════════════════════════════════
def test_resolver_accepts_a_float():
    assert resolve_shrinkage_lambda({"shrinkage_lambda": 0.25}) == pytest.approx(0.25)


def test_resolver_refuses_a_dict_instead_of_defaulting_to_zero():
    """★핵심★ dict 를 만나면 **0.0 으로 떨어지지 않고 올린다**.

    0.0 은 "수축 불필요 = 표본이 완벽" 이라는 뜻이라 뷰를 **가장 강하게** 만든다.
    읽지 못한 것이 확신을 최대로 올리는 구조를 만들지 않는다.
    """
    with pytest.raises(ValueError) as e:
        resolve_shrinkage_lambda({"shrinkage_lambda": {"A": 0.1, "B": 0.2}})
    assert "집계" in str(e.value) or "스칼라" in str(e.value)


@pytest.mark.parametrize("bad", [None, "0.3", [0.1], float("nan")])
def test_resolver_refuses_other_unreadable_values(bad):
    with pytest.raises(ValueError):
        resolve_shrinkage_lambda({"shrinkage_lambda": bad})


def test_resolver_clamps_to_unit_interval():
    assert resolve_shrinkage_lambda({"shrinkage_lambda": 1.4}) == pytest.approx(1.0)
    assert resolve_shrinkage_lambda({"shrinkage_lambda": -0.2}) == pytest.approx(0.0)


def test_both_producers_are_readable_by_the_resolver():
    """짝 — 두 산출자 모두 리졸버를 통과해야 한다(가드가 전부를 막지 않도록)."""
    df, by_month = _frame()
    assert resolve_shrinkage_lambda(conditional_moments(df, by_month, "A")) >= 0.0
    mix, _, _ = _mix()
    assert resolve_shrinkage_lambda(mix) >= 0.0
