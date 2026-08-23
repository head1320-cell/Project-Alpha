"""팩터 리스크 모델 — Σ = BΣ_fB' + D (벤치마크 문서 §13)

★이 파일이 거는 것★
  1. ★항상 양정부호★ 자산수가 관측수를 넘어도 그렇다 — 표본 공분산은 그 지점에서
     특이해진다. 이것이 §13 이 말하는 구조적 이점이고, **대조로** 못박는다.
  2. ★결합 베타다★ 단변량이면 상관된 팩터의 공통 변동을 중복 흡수한다
     (P3-4 에서 103,809%).
  3. ★조립을 성분까지 잰다★ 합·재구성만 재는 가드는 이 세션에서 네 번 뚫렸다 —
     B 의 각 행과 D 의 각 원소를 따로 확인한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from types import SimpleNamespace  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.factor_exposure import FACTOR_PROXIES  # noqa: E402
from src.engine.factor_risk_model import (  # noqa: E402
    MONTHS_PER_YEAR,
    asset_covariance,
    build_factor_risk_model,
    compare_to_sample,
)

SEED = 20260823


def _months(n: int) -> list[str]:
    return [f"{2019 + (i // 12):04d}-{(i % 12) + 1:02d}" for i in range(n)]


def _series_map(n: int = 60, seed: int = SEED) -> dict:
    """모든 팩터의 첫 후보를 채운 합성 계열(비율 폭발을 피해 0 을 안 지난다)."""
    rng = np.random.default_rng(seed)
    ms = _months(n)
    out = {}
    for cands in FACTOR_PROXIES.values():
        lvl = 100.0 + np.cumsum(rng.normal(0.0, 1.2, n))
        out[cands[0]] = SimpleNamespace(timestamps=ms, values=list(lvl))
    return out


def _fake_assets(n_assets: int, n_months: int = 60, seed: int = 3):
    """`_asset_monthly_returns` 를 대체할 합성 자산 수익률."""
    rng = np.random.default_rng(seed)
    ms = _months(n_months)
    codes = [f"A{i:03d}" for i in range(n_assets)]
    series = {c: {m: float(v) for m, v in zip(ms, rng.normal(0.0, 0.05, n_months),
                                              strict=True)} for c in codes}
    return codes, series


def _build(monkeypatch, n_assets: int, n_months: int = 60, **kw) -> dict:
    codes, series = _fake_assets(n_assets, n_months)
    monkeypatch.setattr("src.engine.factor_risk_model._asset_monthly_returns",
                        lambda cs, months: ({c: series[c] for c in cs if c in series}, []))
    return build_factor_risk_model(codes, series_map=_series_map(n_months), **kw)


# ── 1. ★항상 양정부호★ ────────────────────────────────────────────────────
@pytest.mark.parametrize("n_assets", [2, 5, 20])
def test_the_model_covariance_is_positive_definite(monkeypatch, n_assets):
    m = _build(monkeypatch, n_assets)
    assert m["available"] is True, m.get("reason")
    d = m["diagnostics"]
    assert d["min_eigenvalue"] > 0
    # ★플래그가 실제 고유값과 **일치**해야 한다★ 앞 판본은 둘을 따로 단언해서,
    # 플래그를 항상 True 로 만드는 변이가 green 이었다 — 보고값이 계산값을
    # 따라가는지는 그 둘을 **묶어서** 재야 잡힌다.
    assert d["positive_definite"] == bool(d["min_eigenvalue"] > 0)
    # 실제로 Σ 를 다시 분해해도 같은 판정이 나온다.
    eig = np.linalg.eigvalsh(np.asarray(m["cov_monthly"]))
    assert d["positive_definite"] == bool(eig.min() > 0)
    assert d["min_eigenvalue"] == pytest.approx(float(eig.min()), rel=1e-9)


def test_it_stays_positive_definite_when_assets_exceed_observations(monkeypatch):
    """★§13 의 핵심 주장★ 표본 공분산은 특이해지는데 팩터 모형은 아니다.

    이것이 "more scalable and interpretable" 의 **구조적** 근거다.
    """
    n_months = 30
    m = _build(monkeypatch, n_assets=40, n_months=n_months)
    assert m["available"] is True, m.get("reason")
    assert m["diagnostics"]["n_assets"] == 40
    assert m["diagnostics"]["positive_definite"] is True

    # 대조 — 같은 자산 수·관측 수의 표본 공분산은 특이하다.
    rng = np.random.default_rng(1)
    R = rng.normal(0.0, 0.05, (n_months, 40))
    sample = np.cov(R, rowvar=False)
    assert np.linalg.eigvalsh(sample).min() < 1e-12, "대조군이 특이하지 않으면 비교가 무의미하다"


def test_specific_risk_is_what_keeps_it_invertible(monkeypatch):
    """D 가 없으면 BΣ_fB' 는 랭크가 팩터 수로 제한되어 특이해진다."""
    m = _build(monkeypatch, n_assets=20)
    B, Sf = np.asarray(m["B"]), np.asarray(m["factor_cov"])
    without_d = B @ Sf @ B.T
    assert np.linalg.eigvalsh(without_d).min() < 1e-10, "D 없이는 특이하다"
    assert m["diagnostics"]["min_eigenvalue"] > 0, "D 를 더하면 양정부호다"


# ── 2. ★조립을 성분까지 잰다★ ────────────────────────────────────────────
def test_the_covariance_is_exactly_b_sf_bt_plus_d(monkeypatch):
    m = _build(monkeypatch, n_assets=5)
    B, Sf, D = np.asarray(m["B"]), np.asarray(m["factor_cov"]), np.asarray(m["D"])
    assert np.allclose(np.asarray(m["cov_monthly"]), B @ Sf @ B.T + np.diag(D),
                       atol=1e-15)


def test_each_beta_row_matches_the_joint_solution(monkeypatch):
    """★결합 베타다★ 단변량으로 바꾸면 여기서 걸린다."""
    from src.engine.factor_exposure import resolve_proxies
    codes, series = _fake_assets(3)
    sm = _series_map()
    monkeypatch.setattr("src.engine.factor_risk_model._asset_monthly_returns",
                        lambda cs, months: ({c: series[c] for c in cs if c in series}, []))
    m = build_factor_risk_model(codes, series_map=sm)
    assert m["available"] is True, m.get("reason")

    res = resolve_proxies(sm)["resolved"]
    factors = m["factors"]
    common = set.intersection(*[set(res[f]["changes"]) for f in factors])
    for i, code in enumerate(m["codes"]):
        shared = sorted(set(series[code]) & common)
        y = np.array([series[code][mm] for mm in shared])
        X = np.array([[res[f]["changes"][mm] for f in factors] for mm in shared])
        coef, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(shared)), X]), y,
                                   rcond=None)
        assert np.allclose(np.asarray(m["B"])[i], coef[1:], atol=1e-8), code


def test_each_specific_variance_is_the_dof_adjusted_residual(monkeypatch):
    """★자유도 보정★ 보정 없이 나누면 D 가 체계적으로 작아진다."""
    from src.engine.factor_exposure import resolve_proxies
    codes, series = _fake_assets(3)
    sm = _series_map()
    monkeypatch.setattr("src.engine.factor_risk_model._asset_monthly_returns",
                        lambda cs, months: ({c: series[c] for c in cs if c in series}, []))
    m = build_factor_risk_model(codes, series_map=sm)
    res = resolve_proxies(sm)["resolved"]
    factors = m["factors"]
    common = set.intersection(*[set(res[f]["changes"]) for f in factors])
    for i, code in enumerate(m["codes"]):
        shared = sorted(set(series[code]) & common)
        y = np.array([series[code][mm] for mm in shared])
        X = np.array([[res[f]["changes"][mm] for f in factors] for mm in shared])
        A = np.column_stack([np.ones(len(shared)), X])
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ coef
        dof = len(shared) - len(factors) - 1
        assert np.asarray(m["D"])[i] == pytest.approx(float((resid ** 2).sum() / dof),
                                                      rel=1e-9), code
        # 보정 없는 값(÷n)보다 반드시 크다.
        assert np.asarray(m["D"])[i] > float((resid ** 2).mean())


def test_each_asset_reports_its_own_dof_and_factor_share(monkeypatch):
    m = _build(monkeypatch, n_assets=4)
    for row in m["assets"]:
        assert row["dof"] == row["n_months"] - m["diagnostics"]["n_factors"] - 1
        assert 0.0 <= row["factor_share_pct"] <= 100.0
        assert row["specific_variance"] > 0


# ── 3. ★0 으로 채우지 않는다★ ────────────────────────────────────────────
def test_an_asset_without_prices_is_excluded_with_a_reason(monkeypatch):
    codes, series = _fake_assets(3)
    monkeypatch.setattr("src.engine.factor_risk_model._asset_monthly_returns",
                        lambda cs, months: ({c: series[c] for c in cs[:2]}, [cs[2]]))
    m = build_factor_risk_model(codes, series_map=_series_map())
    assert m["available"] is True
    assert m["codes"] == codes[:2]
    assert codes[2] in m["excluded"] and m["excluded"][codes[2]]
    assert np.asarray(m["B"]).shape[0] == 2, "0 베타로 채우지 않는다"


def test_a_thin_asset_is_excluded_not_zero_filled(monkeypatch):
    """★0 베타는 '노출이 없다' 는 주장이다★ 실제로는 '추정하지 못했다' 이다."""
    codes, series = _fake_assets(2)
    thin = {k: v for k, v in list(series[codes[1]].items())[:5]}
    series[codes[1]] = thin
    monkeypatch.setattr("src.engine.factor_risk_model._asset_monthly_returns",
                        lambda cs, months: ({c: series[c] for c in cs}, []))
    m = build_factor_risk_model(codes, series_map=_series_map())
    assert m["codes"] == [codes[0]]
    assert "자유도" in m["excluded"][codes[1]]


def test_no_usable_asset_is_a_reason(monkeypatch):
    monkeypatch.setattr("src.engine.factor_risk_model._asset_monthly_returns",
                        lambda cs, months: ({}, list(cs)))
    m = build_factor_risk_model(["X"], series_map=_series_map())
    assert m["available"] is False and m["reason"]


def test_empty_codes_are_refused():
    assert build_factor_risk_model([])["available"] is False


# ── 4. ★단위★ ────────────────────────────────────────────────────────────
def test_annualisation_uses_twelve_not_two_hundred_fifty_two(monkeypatch):
    """★월별 데이터다★ ×252 로 하면 변동성이 4.6배 부풀려진다."""
    m = _build(monkeypatch, n_assets=3)
    monthly = np.asarray(m["cov_monthly"])
    annual = asset_covariance(m)
    assert np.allclose(annual, monthly * MONTHS_PER_YEAR)
    assert MONTHS_PER_YEAR == 12
    assert m["units"] == "monthly"


def test_annualise_false_returns_the_monthly_matrix(monkeypatch):
    m = _build(monkeypatch, n_assets=3)
    assert np.allclose(asset_covariance(m, annualize=False), m["cov_monthly"])


def test_an_unavailable_model_yields_no_covariance():
    assert asset_covariance({"available": False}) is None


# ── 5. ★표본과의 비교를 보고하되 우월을 주장하지 않는다★ ────────────────
def test_the_comparison_reports_both_and_claims_neither(monkeypatch):
    m = _build(monkeypatch, n_assets=4)
    rng = np.random.default_rng(2)
    sample = np.cov(rng.normal(0.0, 0.05, (60, 4)), rowvar=False)
    cmp = compare_to_sample(m, sample)
    assert cmp["available"] is True
    assert len(cmp["model_vol"]) == len(cmp["sample_vol"]) == 4
    assert "어느 쪽이 옳다고 말하지 않습니다" in cmp["note"]
    assert cmp["max_abs_diff"] >= 0


def test_a_shape_mismatch_in_the_comparison_is_refused(monkeypatch):
    m = _build(monkeypatch, n_assets=4)
    assert compare_to_sample(m, np.eye(3))["available"] is False


def test_the_method_declares_joint_estimation(monkeypatch):
    m = _build(monkeypatch, n_assets=3)
    assert m["method"] == "joint_ols_factor_model"
    assert "양정부호" in m["note"]
