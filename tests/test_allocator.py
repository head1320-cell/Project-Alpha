"""BG2 · 전략 배분기 — ★새로 짜지 않는다, 이미 있는 계산을 쓴다★ (R2 복원)
==============================================================================
스펙 §4.2 · 대상 `src/engine/allocator.py` · 재사용
`allocation_studio._inverse_vol_w` · `risk_allocations._hrp_weights` ·
`RegimeAdaptiveAllocator._cap_and_redistribute`

## 거는 것

- 같은 입력이면 **기존 구현과 같은 가중**(골든 — 복제가 아니라 재사용).
- 상한은 ★재정규화하지 않는다★(B2) — 여유가 없으면 남는 몫은 현금이다.
- ★조용히 실패하지 않는다★ — 표본 부족·변동성 0·`hrp_macro`(R4 전)는
  `available: False` + 사유. 엔진은 그것을 말없이 삼키므로 문이 따로 막는다(BG5).
- 매크로가 없는 방법이라 `macro_adjustments` 는 **구조적으로** 비어 있다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.engine.allocator import MultiStrategyAllocator


def _returns(n=120, k=3, seed=7, vols=(0.01, 0.02, 0.04)) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    data = {i + 1: rng.normal(0, vols[i % len(vols)], n) for i in range(k)}
    return pd.DataFrame(data, index=idx)


def _alloc(R, method="inverse_vol", **kw):
    kw.setdefault("lookback_days", 252)
    kw.setdefault("max_weight", 1.0)
    kw.setdefault("min_weight", 0.0)
    return MultiStrategyAllocator(None).compute(
        returns_matrix=R, method=method, strategies=[], as_of_date="2024-06-01", **kw)


# ── 기존 구현과 같은 답 ─────────────────────────────────────────────

def test_inverse_vol_matches_the_existing_implementation():
    from src.engine.allocation_studio import _inverse_vol_w
    R = _returns()
    out = _alloc(R, "inverse_vol")
    ref = _inverse_vol_w(R.values)
    assert out["available"] is True
    assert [out["weights"][c] for c in R.columns] == pytest.approx(list(ref))


def test_hrp_matches_the_existing_implementation():
    from src.engine.risk_allocations import _hrp_weights
    R = _returns()
    out = _alloc(R, "hrp")
    ref = _hrp_weights(np.cov(R.values, rowvar=False))
    ref = ref / ref.sum()
    assert out["available"] is True
    assert [out["weights"][c] for c in R.columns] == pytest.approx(list(ref))


def test_lower_volatility_gets_more_weight():
    out = _alloc(_returns(), "inverse_vol")
    w = out["weights"]
    assert w[1] > w[2] > w[3]


def test_the_contract_keys_are_all_there():
    out = _alloc(_returns(), "hrp")
    for k in ("available", "weights", "base_weights", "macro_adjustments",
              "regime", "method", "n_obs"):
        assert k in out, k
    assert out["base_weights"] == out["weights"]
    assert out["macro_adjustments"] == {}
    assert out["regime"] is None
    assert sum(out["weights"].values()) == pytest.approx(1.0)
    assert all(isinstance(k, int) for k in out["weights"])


def test_the_lookback_window_is_the_tail():
    """★창은 끝에서부터★ — 앞쪽 변동성을 바꿔도 창 밖이면 가중이 같다."""
    R = _returns(n=200)
    R2 = R.copy()
    R2.iloc[:50, 0] *= 10
    a = _alloc(R, "inverse_vol", lookback_days=100)["weights"]
    b = _alloc(R2, "inverse_vol", lookback_days=100)["weights"]
    assert a == pytest.approx(b)
    assert _alloc(R2, "inverse_vol", lookback_days=200)["weights"][1] != pytest.approx(a[1])


# ── 상·하한 ──────────────────────────────────────────────────────────

def test_the_cap_binds_and_the_excess_moves_to_the_others():
    out = _alloc(_returns(), "inverse_vol", max_weight=0.45)
    w = out["weights"]
    assert max(w.values()) <= 0.45 + 1e-9
    assert sum(w.values()) == pytest.approx(1.0)
    assert out["cap_binding"] >= 1


def test_an_impossible_cap_leaves_cash_instead_of_renormalizing():
    """★B2 규율★ — 전략 둘에 상한 0.3 이면 60% 만 투자하고 40% 는 현금이다."""
    out = _alloc(_returns(k=2), "inverse_vol", max_weight=0.3)
    w = out["weights"]
    assert max(w.values()) <= 0.3 + 1e-9
    assert sum(w.values()) == pytest.approx(0.6)
    assert out["cash_weight"] == pytest.approx(0.4)


def test_the_floor_lifts_small_weights():
    out = _alloc(_returns(vols=(0.005, 0.02, 0.2)), "inverse_vol", min_weight=0.15)
    w = out["weights"]
    assert min(w.values()) >= 0.15 - 1e-9
    assert sum(w.values()) == pytest.approx(1.0)


def test_an_impossible_floor_is_refused():
    out = _alloc(_returns(k=3), "inverse_vol", min_weight=0.4)
    assert out["available"] is False and "min_weight" in out["reason"]


# ── ★조용히 실패하지 않는다★ ──────────────────────────────────────────

def test_too_few_observations_is_unavailable_with_a_reason():
    out = _alloc(_returns(n=15), "hrp")
    assert out["available"] is False and out["reason"]
    assert out["weights"] == {}


def test_enough_observations_is_available():
    """★짝★ — 항상-불가 구현 배제."""
    assert _alloc(_returns(n=20), "hrp")["available"] is True


def test_a_zero_volatility_strategy_is_refused_not_given_everything():
    """`_inverse_vol_w` 는 변동성 0 을 1e-9 로 눌러 그 전략에 거의 전부를 준다 — 조용히."""
    R = _returns()
    R[2] = 0.0
    out = _alloc(R, "inverse_vol")
    assert out["available"] is False and "변동성" in out["reason"]


def test_hrp_macro_is_unavailable_until_r4():
    out = _alloc(_returns(), "hrp_macro")
    assert out["available"] is False and "R4" in out["reason"]


def test_an_unknown_method_is_refused():
    out = _alloc(_returns(), "mvo")
    assert out["available"] is False and "mvo" in out["reason"]


def test_a_single_strategy_gets_everything_it_is_allowed():
    out = _alloc(_returns(k=1), "hrp")
    assert out["available"] is True and out["weights"] == {1: pytest.approx(1.0)}
