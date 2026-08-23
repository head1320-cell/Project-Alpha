"""국면조건부 μ/Σ 엔진 계약 (P2.5 커밋 ①)

이 엔진의 존재 이유는 하나다 — `allocation_studio.optimize` 가 쓰는 μ/Σ 가
**무조건부**라서 국면이 비중에 한 번도 닿지 않는다는 것. 그러므로 첫 테스트는
성능도 형태도 아니고 **"국면을 바꾸면 숫자가 실제로 달라지는가"** 다. 이것이
빨갛지 않으면 배선은 도장만 찍는 것이다.

두 번째 테스트는 그 짝이다 — 라벨이 하나뿐이면 기존 무조건부 경로와 **정확히**
일치해야 한다. 둘을 함께 걸어야 "달라진다" 가 잡음이 아님이 증명된다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.engine.conditional_market import (
    conditional_moments,
    regime_by_month_from_path,
)

ASSETS = ["A", "B", "C", "D"]


def _frame(n_months: int = 24, per_month: int = 21, seed: int = 7,
           mean_by_month=None, n_assets: int = len(ASSETS)) -> pd.DataFrame:
    """월별 평균을 심을 수 있는 합성 일별 수익률 — 인덱스는 실제 영업일."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n_months * per_month)
    names = [f"A{i}" for i in range(n_assets)] if n_assets != len(ASSETS) else ASSETS
    R = rng.normal(0.0, 0.01, size=(len(idx), len(names)))
    df = pd.DataFrame(R, index=idx, columns=names)
    if mean_by_month:
        for i, ts in enumerate(idx):
            shift = mean_by_month.get(ts.strftime("%Y-%m"))
            if shift is not None:
                df.iloc[i] += shift
    return df


def _labels(df: pd.DataFrame, assign) -> dict[str, str]:
    """월 → 국면. `assign(month_index)` 가 라벨을 준다."""
    months = sorted({ts.strftime("%Y-%m") for ts in df.index})
    return {m: assign(i) for i, m in enumerate(months)}


# ── 1. ★국면을 바꾸면 μ 가 실제로 달라진다★ ─────────────────────────────────
def test_changing_the_regime_actually_changes_mu():
    df = _frame(n_months=24)
    by_month = _labels(df, lambda i: "Goldilocks" if i % 2 == 0 else "Stagflation")
    # 국면별로 **다른** 평균을 심는다 — 심은 대로 나와야 한다.
    planted = {m: (0.004 if r == "Goldilocks" else -0.003)
               for m, r in by_month.items()}
    df = _frame(n_months=24, mean_by_month=planted)

    good = conditional_moments(df, by_month, "Goldilocks")
    bad = conditional_moments(df, by_month, "Stagflation")

    assert good["available"] and bad["available"], (good["reason"], bad["reason"])
    assert np.all(good["mu"] > 0.0), good["mu"]
    assert np.all(bad["mu"] < 0.0), bad["mu"]
    # 도장만 찍는 배선이면 이 차이가 0 이 된다.
    assert np.abs(good["mu"] - bad["mu"]).min() > 0.5, "국면 간 μ 차이가 사라졌다"

    # 무조건부 평균은 둘 사이 어딘가 — 어느 쪽과도 같지 않아야 한다.
    uncond = df.values.mean(axis=0) * 252.0
    assert not np.allclose(good["mu"], uncond)
    assert not np.allclose(bad["mu"], uncond)


# ── 2. ★짝★ 라벨이 하나면 무조건부 추정과 일치한다 ──────────────────────────
def test_single_label_degenerates_to_the_unconditional_estimate():
    """조건부를 끄는 것과 같은 상태 — 기존 `optimize()` 경로와 **정확히** 같아야 한다."""
    from src.engine.risk_allocations import _cov

    df = _frame(n_months=18, seed=11)
    by_month = _labels(df, lambda i: "Goldilocks")

    out = conditional_moments(df, by_month, "Goldilocks")
    assert out["available"], out["reason"]

    R = df.values
    np.testing.assert_allclose(out["mu"], R.mean(axis=0) * 252.0, rtol=0, atol=1e-15)
    # ★같은 추정량이어야 한다★ `optimize()` 는 `_cov(R) * 252.0` 을 쓴다.
    np.testing.assert_allclose(out["sigma"], _cov(R) * 252.0, rtol=1e-12, atol=1e-18)
    assert out["n_months"] == 18
    assert out["unlabeled_obs"] == 0


# ── 3. ★표본이 얇으면 숫자가 아니라 사유★ ───────────────────────────────────
def test_thin_sample_returns_a_reason_not_numbers():
    df = _frame(n_months=12, seed=3)
    # 마지막 한 달만 희귀 국면 — 21행, 4자산 × 요구 8.0 = 32행 하한 미달.
    months = sorted({ts.strftime("%Y-%m") for ts in df.index})
    by_month = {m: ("Stagflation" if m == months[-1] else "Goldilocks") for m in months}

    out = conditional_moments(df, by_month, "Stagflation", min_obs_per_asset=8.0)

    assert out["available"] is False
    assert out["mu"] is None and out["sigma"] is None
    assert out["reason"]
    # ★몇 개였는지 안 적으면 왜 막혔는지 되짚을 수 없다★
    assert out["n_obs_by_regime"]["Stagflation"] == out["n_obs"] > 0
    assert out["n_obs_by_regime"]["Goldilocks"] > out["n_obs"]
    assert out["min_obs_required"] == 32
    assert str(out["n_obs"]) in out["reason"]


def test_the_floor_is_not_a_formality():
    """하한을 낮추면 같은 입력이 통과한다 — 게이트가 실제로 막고 있다는 증거."""
    df = _frame(n_months=12, seed=3)
    months = sorted({ts.strftime("%Y-%m") for ts in df.index})
    by_month = {m: ("Stagflation" if m == months[-1] else "Goldilocks") for m in months}

    assert conditional_moments(df, by_month, "Stagflation",
                               min_obs_per_asset=8.0)["available"] is False
    assert conditional_moments(df, by_month, "Stagflation",
                               min_obs_per_asset=3.0)["available"] is True


# ── 4. Σ 는 양의 준정부호 · 수축은 표본이 얇을수록 강하다 ────────────────────
def test_sigma_is_positive_semidefinite():
    df = _frame(n_months=24, seed=5)
    by_month = _labels(df, lambda i: "Goldilocks" if i % 2 == 0 else "Reflation")
    out = conditional_moments(df, by_month, "Goldilocks")

    S = out["sigma"]
    assert out["available"]
    np.testing.assert_allclose(S, S.T, rtol=0, atol=0)     # 정확히 대칭
    assert float(np.linalg.eigvalsh(S).min()) >= -1e-12


def _correlated_frame(n_months: int, n_assets: int = 8, seed: int = 17) -> pd.DataFrame:
    """상관·이분산이 있는 합성 수익률 — **목표행렬이 틀린** 현실적 표본.

    ★i.i.d. 등분산으로 재면 안 된다★ Ledoit-Wolf 의 목표는 스케일 단위행렬이므로
    무상관·등분산 표본에서는 목표가 **정확히 맞고**, 그러면 관측이 늘수록 λ→1 로
    간다(‖S−F‖²→0). 그것은 추정량이 옳게 도는 것이지 "얇을수록 강하다" 의
    반례가 아니다. 실제 자산은 상관되어 있으므로 그 조건에서 재야 한다.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n_months * 21)
    beta = rng.uniform(0.6, 1.4, size=n_assets)          # 공통인자 노출
    vol = rng.uniform(0.005, 0.03, size=n_assets)        # 이분산
    f = rng.normal(0.0, 0.012, size=(len(idx), 1))
    eps = rng.normal(0.0, 1.0, size=(len(idx), n_assets)) * vol
    R = f @ beta.reshape(1, -1) + eps
    return pd.DataFrame(R, index=idx, columns=[f"A{i}" for i in range(n_assets)])


def test_shrinkage_is_stronger_when_the_sample_is_thinner():
    """★λ 가 '표본이 얇다' 는 자백이다★ 하한을 통과했다고 충분한 것은 아니다."""
    thin = _correlated_frame(n_months=2)
    thick = _correlated_frame(n_months=40)

    lam_thin = conditional_moments(
        thin, _labels(thin, lambda i: "Goldilocks"), "Goldilocks")["shrinkage_lambda"]
    lam_thick = conditional_moments(
        thick, _labels(thick, lambda i: "Goldilocks"), "Goldilocks")["shrinkage_lambda"]

    assert lam_thin is not None and lam_thick is not None
    assert lam_thin > lam_thick, (lam_thin, lam_thick)


def test_correlation_breakdown_is_diagnosed_on_the_regime_sample():
    """진단은 `.tail(60)`(최근성)이 아니라 **국면 표본**에 대해 계산된다."""
    df = _correlated_frame(n_months=24)
    out = conditional_moments(df, _labels(df, lambda i: "Goldilocks"), "Goldilocks")
    d = out["diagnostics"]
    assert d["n_assets"] == 8
    assert 0.0 <= d["avg_correlation"] <= 1.0
    # 단일 공통인자를 심었으므로 최대 고유값이 지배해야 한다.
    assert d["max_eigenvalue_ratio"] > 0.3


def test_explicit_shrinkage_is_honoured_and_reported():
    df = _frame(n_months=18, seed=23)
    by_month = _labels(df, lambda i: "Goldilocks")

    zero = conditional_moments(df, by_month, "Goldilocks", shrinkage="none")
    full = conditional_moments(df, by_month, "Goldilocks", shrinkage=1.0)

    assert zero["shrinkage_lambda"] is None and zero["method"] == "sample"
    assert full["shrinkage_lambda"] == 1.0 and full["method"] == "shrunk_fixed"
    # λ=1 이면 목표행렬(스케일 단위행렬)만 남는다 — 비대각이 0.
    off = full["sigma"] - np.diag(np.diag(full["sigma"]))
    assert np.abs(off).max() < 1e-15


# ── 5. 라벨 없는 달은 버리고 그 수를 보고한다 ───────────────────────────────
def test_unlabelled_months_are_dropped_and_counted():
    df = _frame(n_months=12, seed=31)
    months = sorted({ts.strftime("%Y-%m") for ts in df.index})
    # 앞 4개월에는 라벨이 없다 — 조용히 섞이면 안 된다.
    by_month = {m: "Goldilocks" for m in months[4:]}

    out = conditional_moments(df, by_month, "Goldilocks")

    assert out["available"]
    assert out["n_months"] == 8
    assert out["unlabeled_obs"] == int(
        sum(1 for ts in df.index if ts.strftime("%Y-%m") in months[:4]))
    assert out["unlabeled_obs"] > 0
    # 라벨 있는 달만 들어갔다 — 전체 평균과 다르다.
    labeled_only = df[[ts.strftime("%Y-%m") in months[4:] for ts in df.index]]
    np.testing.assert_allclose(out["mu"], labeled_only.values.mean(axis=0) * 252.0,
                               rtol=0, atol=1e-15)


def test_path_placeholder_labels_are_dropped_not_guessed():
    """`_month_labels` 는 시계열이 짧으면 앞을 `T-3` 으로 채운다 — 날짜가 아니다."""
    points = [
        {"t": "T-2", "regime": "Goldilocks"},
        {"t": "2024-01", "regime": "Reflation"},
        {"t": "2024-02", "regime": "Stagflation"},
        {"t": "2024-03", "regime": None},
    ]
    by_month, dropped = regime_by_month_from_path(points)
    assert by_month == {"2024-01": "Reflation", "2024-02": "Stagflation"}
    assert dropped == 2


# ── 입력이 없을 때도 사유로 답한다 (조용한 폴백 금지) ────────────────────────
@pytest.mark.parametrize("kwargs", [
    {"returns_df": None},
    {"regime_by_month": None},
    {"current_regime": None},
    {"current_regime": "Nonexistent"},
])
def test_missing_inputs_answer_with_a_reason(kwargs):
    df = _frame(n_months=12, seed=41)
    args = {
        "returns_df": df,
        "regime_by_month": _labels(df, lambda i: "Goldilocks"),
        "current_regime": "Goldilocks",
    }
    args.update(kwargs)
    out = conditional_moments(**args)
    assert out["available"] is False
    assert out["mu"] is None
    assert out["reason"]
