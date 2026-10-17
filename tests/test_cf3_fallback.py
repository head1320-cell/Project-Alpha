"""CF3 · 최적화가 대신한 것을 기록한다 — ★드러내기만, 비중은 바이트 동일★ (사용자 결정 2026-10-17)
==============================================================================
`weights_for_model` 은 최적화가 답을 못 내면 역변동성으로 **말없이** 대체한다. BL 사후 계산이 실패하면 시장 비중으로 가고,
사후는 됐는데 max-sharpe 가 실패해도 시장 비중이다(그런데 `views_applied` 는 참 — 라벨 정정은 별도 작업). CF3 는 동작을
바꾸지 않고 `optimize(...)["fallbacks"]` 에 무엇을 무엇으로 대신했는지 적는다. 숫자 불변은 `test_cf3_golden` 이 건다.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine import allocation_studio as st  # noqa: E402

NAMES = ["005930", "000660", "035420"]


def _R():
    rng = np.random.default_rng(3)
    return np.round(rng.normal(0.0004, 0.012, (400, 3)) * np.array([1.0, 1.3, 0.8]), 6)


@pytest.fixture(autouse=True)
def caps(monkeypatch):
    monkeypatch.setattr("src.data.stock_master.get_market_cap",
                        lambda code: {"005930": 400000.0, "000660": 120000.0}.get(code, 30000.0))


def _none(*a, **k):
    return None


def _boom(*a, **k):
    raise np.linalg.LinAlgError("강제 실패")


# ── 추적 함수 ────────────────────────────────────────────────────────────────

def test_traced_records_the_inverse_vol_fallback(monkeypatch):
    monkeypatch.setattr(st, "_opt", _none)
    R = _R()
    w, rec = st.weights_for_model_traced("mvo", R)
    np.testing.assert_array_equal(w, st._inverse_vol_w(R))
    assert rec["used"] == "inverse_vol" and rec["model"] == "mvo"
    assert rec["reason"]


def test_traced_records_nothing_when_solved():
    """짝 — 풀리면 기록이 없다."""
    R = _R()
    w, rec = st.weights_for_model_traced("mvo", R)
    assert rec is None
    np.testing.assert_array_equal(w, st.weights_for_model("mvo", R))


@pytest.mark.parametrize("model,patch", [("mvo", ("_opt", _none)), ("min_var", ("_opt", _none)),
                                         ("mv_utility", ("_opt", _none)), ("hrp", None), ("risk_parity", None)])
def test_weights_for_model_is_traced_first_element(monkeypatch, model, patch):
    """API·값 불변 — `weights_for_model` 은 추적 함수의 첫 값과 같다(대체가 있든 없든)."""
    if patch:
        monkeypatch.setattr(st, patch[0], patch[1])
    R = _R()
    np.testing.assert_array_equal(st.weights_for_model(model, R), st.weights_for_model_traced(model, R)[0])


def test_hrp_failure_is_recorded(monkeypatch):
    monkeypatch.setattr("src.engine.risk_allocations._hrp_weights", _boom)
    _, rec = st.weights_for_model_traced("hrp", _R())
    assert rec and rec["used"] == "inverse_vol" and rec["model"] == "hrp"


# ── optimize ─────────────────────────────────────────────────────────────────

def test_optimize_records_the_optimized_fallback(monkeypatch):
    monkeypatch.setattr(st, "_opt", _none)
    out = st.optimize("mvo", NAMES, _R())
    [f] = out["fallbacks"]
    assert f["stage"] == "optimized" and f["used"] == "inverse_vol" and f["model"] == "mvo"
    assert f["affects_weights"] is True


def test_optimize_without_fallback_has_no_key():
    """짝 — 대체가 없으면 키도 없다(응답 모양이 바뀌지 않는다)."""
    assert "fallbacks" not in st.optimize("mvo", NAMES, _R())


VIEW = [{"assets": ["005930"], "direction": 1, "magnitude_pct": 4.0, "confidence": 60}]


def test_bl_posterior_failure_is_recorded_and_affects_bl(monkeypatch):
    monkeypatch.setattr(st, "bl_posterior", _boom)
    out = st.optimize("bl", NAMES, _R(), views=VIEW)
    [f] = out["fallbacks"]
    assert f["stage"] == "view_applied" and f["used"] == "market" and f["affects_weights"] is True
    assert "LinAlgError" in f["reason"]
    assert out["views_applied"] is False


def test_bl_posterior_failure_under_mvo_does_not_touch_the_weights(monkeypatch):
    """짝 — mvo 의 최종 비중은 생각 단계를 쓰지 않는다: 기록은 남되 비중에 닿지 않는다."""
    monkeypatch.setattr(st, "bl_posterior", _boom)
    out = st.optimize("mvo", NAMES, _R(), views=VIEW)
    [f] = out["fallbacks"]
    assert f["stage"] == "view_applied" and f["affects_weights"] is False


def test_bl_max_sharpe_failure_is_recorded_without_changing_the_label(monkeypatch):
    """사후는 됐는데 max-sharpe 가 실패 — 시장 비중이 최종이다. `views_applied` 는 지금 그대로 참(라벨 정정은 별도 작업)."""
    monkeypatch.setattr(st, "_opt", _none)
    out = st.optimize("bl", NAMES, _R(), views=VIEW)
    stages = {f["stage"]: f for f in out["fallbacks"]}
    assert stages["view_applied"]["used"] == "market" and stages["view_applied"]["affects_weights"] is True
    assert out["views_applied"] is True
    np.testing.assert_array_equal(out["weights"], out["flow"]["market"])
