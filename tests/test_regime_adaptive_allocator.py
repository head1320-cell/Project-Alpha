"""국면 적응형 배분기 ★특성화 테스트★ — 프로덕션 경로인데 테스트가 0개였다 (B1)
==============================================================================
감사: `docs/specs/2026-08-29-macro-research-architecture-audit.md`

## 왜 이 파일이 생겼나

도달성 실사에서 `regime_adaptive_allocator` 가 **CORE(프로덕션 경로) · 테스트 0개**
로 나왔다. `stage12_routes` 와 `realism_engine` 이 부른다. 이 코드는 **실제 비중을
움직이는데** 무엇을 하는지 못 박은 곳이 없었다.

★이 파일은 동작을 바꾸지 않는다★ — 지금 무엇을 하는지 **특성화**한다. 정책
변경은 별도 승인 사항이고, 여기서 하는 것은 그 정책을 관측 가능하게 만드는 일뿐이다.

## ★읽다가 찾은 결함 — 선언된 손잡이가 죽어 있었다★

`AdaptiveConfig` 는 `breakdown_avg_corr_threshold=0.70` 과
`breakdown_max_eigenvalue_ratio=0.60` 을 선언하는데, `_analyze_correlation_health`
는 **`0.7`·`0.6` 을 인라인 상수로** 쓴다. 즉 설정을 바꿔도 아무 일이 일어나지
않는다 — 만다트 §42 의 *confidence hard-coded* 변이 계열이다. 기본값에서는 두 값이
일치하므로 **동작은 한 자리도 바뀌지 않는다**(짝 테스트로 증명).
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.engine.regime_adaptive_allocator import (  # noqa: E402
    AdaptiveConfig,
    RegimeAdaptiveAllocator,
)


class FakeBase:
    """Stage 10 allocator 대역 — ★넘어온 인자를 그대로 기록한다★"""

    def __init__(self):
        self.calls: list[dict] = []

    def compute(self, **kw):
        self.calls.append(kw)
        cols = list(kw["returns_matrix"].columns)
        return {"available": True, "method": kw.get("method"),
                "weights": {c: 1.0 / len(cols) for c in cols}}


def _returns(n_days=250, n_cols=4, rho=0.0, seed=0) -> pd.DataFrame:
    """상관 `rho` 의 수익 행렬 — 상관 건강도 분기를 정확히 겨눈다."""
    rng = np.random.default_rng(seed)
    common = rng.normal(0, 0.01, n_days)
    out = {}
    for i in range(n_cols):
        idio = rng.normal(0, 0.01, n_days)
        out[f"S{i}"] = np.sqrt(rho) * common + np.sqrt(1 - rho) * idio
    return pd.DataFrame(out, index=pd.bdate_range("2024-01-01", periods=n_days))


@pytest.fixture
def alloc():
    base = FakeBase()
    return RegimeAdaptiveAllocator(base), base


# ══════════════════════════════════════════════════════════════════════════
# 모드 선택 — ★systemic_risk_score 가 우선한다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("score,mode", [
    (None, "normal"), (0.0, "normal"), (49.9, "normal"),
    (50.0, "cautious"), (69.9, "cautious"),
    (70.0, "defensive"), (100.0, "defensive"),
])
def test_the_risk_score_selects_the_mode_at_the_declared_thresholds(alloc, score, mode):
    """경계값을 정확히 건다 — 50 과 70 은 **포함**이다."""
    a, _ = alloc
    out = a.compute(returns_matrix=_returns(), systemic_risk_score=score)
    assert out["adaptive_mode"] == mode


def test_every_mode_reports_the_same_adaptive_keys(alloc):
    """★모든 분기가 같은 키를 낸다★ — 소비자가 `.get()` 으로 읽다가 `None` 을
    거짓으로 취급하지 않게(레지스트리 `not_ingested` 와 같은 규율)."""
    a, _ = alloc
    for score in (None, 55.0, 80.0):
        out = a.compute(returns_matrix=_returns(), systemic_risk_score=score)
        for k in ("adaptive_mode", "ewma_applied", "hard_cap_applied",
                  "breakdown_detected", "adaptive_diagnostics"):
            assert k in out, (score, k)
        assert out["adaptive_diagnostics"]["systemic_risk_score"] == score


# ══════════════════════════════════════════════════════════════════════════
# ★모드마다 기반 배분기에 다른 인자가 간다★
# ══════════════════════════════════════════════════════════════════════════
def test_normal_mode_passes_the_callers_arguments_through(alloc):
    a, base = alloc
    a.compute(returns_matrix=_returns(), max_weight=0.5, lookback_days=252,
              systemic_risk_score=None)
    assert base.calls[-1]["max_weight"] == 0.5
    assert base.calls[-1]["lookback_days"] == 252


def test_cautious_mode_shortens_the_lookback_and_tightens_max_weight(alloc):
    """★현행 정책을 못 박는다★ — lookback ≤ 90, max_weight × 0.85."""
    a, base = alloc
    a.compute(returns_matrix=_returns(), max_weight=0.5, lookback_days=252,
              systemic_risk_score=55.0)
    call = base.calls[-1]
    assert call["lookback_days"] == 90
    assert call["max_weight"] == pytest.approx(0.5 * 0.85)


def test_cautious_mode_reweights_the_returns_it_hands_down(alloc):
    """EWMA 는 **행렬을 바꿔서** 넘긴다 — 원본이 그대로 가면 모드가 무의미하다."""
    a, base = alloc
    R = _returns()
    a.compute(returns_matrix=R, systemic_risk_score=55.0)
    passed = base.calls[-1]["returns_matrix"]
    assert passed.shape == R.shape
    assert not np.allclose(passed.values, R.values)
    assert a.compute(returns_matrix=R, systemic_risk_score=55.0)["ewma_lambda"] == 0.85


def test_the_ewma_weighting_puts_more_weight_on_recent_observations():
    """★최근이 무겁다★ 이것이 뒤집히면 CAUTIOUS 가 정반대 일을 한다."""
    R = pd.DataFrame({"S0": np.ones(100)},
                     index=pd.bdate_range("2024-01-01", periods=100))
    w = RegimeAdaptiveAllocator._apply_ewma_weighting(R, 0.85)["S0"].values
    assert w[-1] > w[0]
    assert np.all(np.diff(w) > 0)


def test_the_ewma_preserves_the_average_scale():
    """가중치 합을 N 으로 정규화한다 — 분산이 통째로 줄어들면 안 된다."""
    R = _returns(n_days=200, n_cols=1)
    w = RegimeAdaptiveAllocator._apply_ewma_weighting(R, 0.85)
    assert w.shape == R.shape
    assert float(np.mean((w.values / R.values) ** 2)) == pytest.approx(1.0, rel=0.05)


# ══════════════════════════════════════════════════════════════════════════
# DEFENSIVE — ★현금 버퍼와 상한★
# ══════════════════════════════════════════════════════════════════════════
def test_defensive_mode_holds_back_the_cash_buffer(alloc):
    """★비중 합이 1 이 아니라 1 − 현금버퍼다★ 이것이 이 모드의 존재 이유다."""
    a, _ = alloc
    out = a.compute(returns_matrix=_returns(n_cols=4), systemic_risk_score=85.0)
    assert out["adaptive_mode"] == "defensive"
    assert out["cash_buffer_pct"] == 0.30
    assert sum(out["weights"].values()) == pytest.approx(0.70, abs=1e-6)


def _uneven_vol(n_days=200, seed=1) -> pd.DataFrame:
    """★변동성이 크게 다른 4전략★ — inverse-vol 이 저변동성 전략에 몰려
    상한이 **실제로 물게** 만든다. 등변동성으로는 상한이 아예 안 걸려서
    "상한 삭제" 변이가 살아남는다(D7 이 그것을 찾아냈다)."""
    rng = np.random.default_rng(seed)
    vols = [0.002, 0.02, 0.02, 0.02]
    return pd.DataFrame(
        {f"S{i}": rng.normal(0, v, n_days) for i, v in enumerate(vols)},
        index=pd.bdate_range("2024-01-01", periods=n_days))


def test_the_hard_cap_actually_binds_on_a_concentrated_allocation(alloc):
    """★상한이 무는 경우를 겨눈다★ — 저변동성 전략이 상한에 정확히 눌린다.

    이 테스트가 없으면 상한을 통째로 지워도 스위트가 통과한다(변이 D7).
    등변동성에서는 inverse-vol 이 이미 상한 아래라 상한이 할 일이 없기 때문이다.
    """
    a, _ = alloc
    out = a.compute(returns_matrix=_uneven_vol(), systemic_risk_score=85.0)
    w = out["weights"]
    assert max(w.values()) == pytest.approx(0.30, abs=1e-9)   # 정확히 상한에 눌렸다
    assert sum(w.values()) == pytest.approx(0.70, abs=1e-6)   # 현금버퍼는 지켜진다
    assert out["adaptive_diagnostics"] is not None


def test_the_cap_does_not_bind_when_the_allocation_is_already_spread(alloc):
    """★짝★ 항상 0.30 을 내는 구현을 배제한다 — 고르게 퍼지면 상한 아래다."""
    a, _ = alloc
    out = a.compute(returns_matrix=_returns(n_cols=6), systemic_risk_score=85.0)
    assert max(out["weights"].values()) < 0.30 - 1e-3


def test_the_hard_cap_is_undone_by_the_final_renormalisation(alloc):
    """★결함을 특성화한다 — 고치지 않는다★

    `_defensive_mode` 는 상한을 적용한 뒤 `scale = available_weight / total` 로
    **다시 정규화**한다. 모든 전략이 상한에 걸리면 total 이 상한×N 이라 그 스케일이
    상한을 정확히 **되돌린다**:

        전략 1개 → 0.70 (선언 상한 0.30)
        전략 2개 → 0.35 씩

    그런데 `hard_cap_applied: True` 를 보고한다 — ★거짓 보고★. 위기 모드가 정확히
    집중된 경우에 상한을 잃는다.

    ★고치는 것은 배분 정책 변경이라 별도 승인 사항이다.★ 여기서는 현행을 못 박아
    누가 조용히 바꾸지 못하게 하고, 감사에 결함으로 올린다.
    """
    a, _ = alloc
    one = a.compute(returns_matrix=_returns(n_cols=1), systemic_risk_score=85.0)
    two = a.compute(returns_matrix=_returns(n_cols=2), systemic_risk_score=85.0)
    assert max(one["weights"].values()) == pytest.approx(0.70)
    assert max(two["weights"].values()) == pytest.approx(0.35)
    # ★거짓 보고까지 못 박는다★ — 상한이 안 걸렸는데 걸렸다고 적는다.
    assert one["hard_cap_applied"] is True
    assert one["hard_cap_value"] == 0.30


def test_defensive_mode_does_not_call_the_base_allocator(alloc):
    """★기반 배분기를 우회한다★ — 자체 inverse-vol 로 짠다. 정책 사실이다."""
    a, base = alloc
    a.compute(returns_matrix=_returns(), systemic_risk_score=85.0)
    assert base.calls == []


def test_defensive_mode_refuses_an_empty_universe(alloc):
    a, _ = alloc
    out = a.compute(returns_matrix=pd.DataFrame(), systemic_risk_score=85.0)
    assert out["available"] is False and out["message"]


# ══════════════════════════════════════════════════════════════════════════
# 상관 건강도 — ★자체 감지로도 모드가 바뀐다★
# ══════════════════════════════════════════════════════════════════════════
def test_high_correlation_alone_can_trigger_a_defensive_mode(alloc):
    """점수가 없어도 상관이 무너지면 방어로 간다 — 두 경로가 다 살아 있다."""
    a, _ = alloc
    out = a.compute(returns_matrix=_returns(rho=0.97, seed=3),
                    systemic_risk_score=None)
    assert out["adaptive_diagnostics"]["avg_correlation"] > 0.85
    assert out["adaptive_mode"] == "defensive"


def test_low_correlation_stays_normal(alloc):
    """★짝★ 항상 방어로 가는 구현을 배제한다."""
    a, _ = alloc
    out = a.compute(returns_matrix=_returns(rho=0.0, seed=4),
                    systemic_risk_score=None)
    assert out["adaptive_mode"] == "normal"


def test_insufficient_data_does_not_manufacture_a_correlation(alloc):
    """★현행 동작을 못 박는다★ 20일 미만이면 상관을 내지 않고 사유를 단다.

    다만 `avg_correlation: 0` 은 "상관이 0" 과 구분되지 않는다 — 감사에 적어 둔
    `미상 ≠ 0` 부채이고, **여기서 고치지 않는다**(모드 선택이 바뀐다).
    """
    a, _ = alloc
    d = RegimeAdaptiveAllocator._analyze_correlation_health(_returns(n_days=10))
    assert d["breakdown_detected"] is False
    assert d.get("message") == "데이터 부족"
    out = a.compute(returns_matrix=_returns(n_days=10), systemic_risk_score=None)
    assert out["adaptive_mode"] == "normal"


def test_a_single_strategy_has_no_correlation_to_analyse():
    d = RegimeAdaptiveAllocator._analyze_correlation_health(_returns(n_cols=1))
    assert d["n_strategies"] == 1 and d["breakdown_detected"] is False


# ══════════════════════════════════════════════════════════════════════════
# ★선언된 손잡이가 실제로 일해야 한다★ (읽다가 찾은 결함)
# ══════════════════════════════════════════════════════════════════════════
def test_the_declared_breakdown_thresholds_are_actually_used():
    """★`AdaptiveConfig` 의 임계가 죽어 있었다★

    `breakdown_avg_corr_threshold`·`breakdown_max_eigenvalue_ratio` 를 선언해 두고
    `_analyze_correlation_health` 는 `0.7`·`0.6` 을 **인라인 상수**로 썼다. 설정을
    바꿔도 아무 일이 없었다 — 만다트 §42 의 *confidence hard-coded* 계열이다.
    """
    R = _returns(rho=0.30, seed=7)
    loose = AdaptiveConfig(breakdown_avg_corr_threshold=0.99,
                           breakdown_max_eigenvalue_ratio=0.99)
    strict = AdaptiveConfig(breakdown_avg_corr_threshold=0.01,
                            breakdown_max_eigenvalue_ratio=0.01)
    a_loose = RegimeAdaptiveAllocator(FakeBase(), loose)
    a_strict = RegimeAdaptiveAllocator(FakeBase(), strict)
    d_loose = a_loose.correlation_health(R)
    d_strict = a_strict.correlation_health(R)
    assert d_loose["breakdown_detected"] is False
    assert d_strict["breakdown_detected"] is True
    # 판정만 다르고 **관측치는 같다** — 임계는 관례이지 측정이 아니다.
    assert d_loose["avg_correlation"] == d_strict["avg_correlation"]


def test_the_default_config_reproduces_the_previous_hard_coded_behaviour():
    """★짝 — 동작 불변의 증거★ 기본값에서는 예전 인라인 상수와 **같은 판정**이다."""
    R = _returns(rho=0.30, seed=7)
    a = RegimeAdaptiveAllocator(FakeBase())
    d = a.correlation_health(R)
    old = (d["avg_correlation"] > 0.7) or (d["max_eigenvalue_ratio"] > 0.6)
    assert d["breakdown_detected"] is old
    assert AdaptiveConfig().breakdown_avg_corr_threshold == 0.70
    assert AdaptiveConfig().breakdown_max_eigenvalue_ratio == 0.60


def test_the_static_helper_still_works_for_existing_callers():
    """★기존 호출부를 깨지 않는다★ — 정적 헬퍼는 기본 임계로 그대로 돈다."""
    R = _returns(rho=0.30, seed=7)
    stat = RegimeAdaptiveAllocator._analyze_correlation_health(R)
    inst = RegimeAdaptiveAllocator(FakeBase()).correlation_health(R)
    assert stat == inst
