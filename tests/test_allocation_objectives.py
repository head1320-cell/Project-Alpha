"""AAS Phase 2 — Optimize objectives (max_div/min_cvar) + Meucci ENB (Explain)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402

from src.engine.allocation_studio import (  # noqa: E402
    MODELS,
    effective_number_of_bets,
    weights_for_model,
)


def _R(seed=5, n=4, days=400):
    rng = np.random.default_rng(seed)
    sd = np.array([0.008, 0.012, 0.01, 0.016])[:n]
    return rng.standard_normal((days, n)) * sd + 0.0003


def test_new_models_registered():
    assert "max_div" in MODELS and "min_cvar" in MODELS


def test_max_div_long_only_sum1():
    R = _R()
    w = weights_for_model("max_div", R)
    assert abs(w.sum() - 1.0) < 1e-6
    assert (w >= -1e-9).all()
    assert np.all(np.isfinite(w))


def test_min_cvar_long_only_sum1():
    R = _R()
    w = weights_for_model("min_cvar", R)
    assert abs(w.sum() - 1.0) < 1e-6
    assert (w >= -1e-9).all()
    # min_cvar 는 저변동 자산에 더 실어야 함(자산0=최저 vol) — 정성 방향
    assert w[0] >= w[3] - 0.2


def test_enb_bounds_and_extremes():
    n = 4
    # 무상관·등분산 + 등가중 → ENB ≈ N
    S = np.eye(n)
    w_eq = np.ones(n) / n
    enb_eq = effective_number_of_bets(w_eq, S)
    assert enb_eq > n - 0.5   # ≈ n
    assert enb_eq <= n + 1e-6
    # 완전 집중 → ENB ≈ 1
    w_conc = np.array([1.0, 0, 0, 0])
    assert abs(effective_number_of_bets(w_conc, S) - 1.0) < 1e-6
    # 상관이 있으면 ENB < Neff(비중 기준)
    C = np.full((n, n), 0.9)
    np.fill_diagonal(C, 1.0)
    enb_corr = effective_number_of_bets(w_eq, C)
    assert enb_corr < n   # 상관으로 실질 베팅 수 감소
