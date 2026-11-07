"""P3-4 — Company 팩터 노출 → 포트폴리오 팩터 리스크

★이 파일이 거는 것★
  1. 팩터 기여의 합이 팩터 설명분산과 같다(분해의 정합성).
  2. ★초과 설명을 0 으로 자르지 않는다★ 단변량 베타는 공통 변동을 중복 흡수해
     설명분산이 총분산을 넘을 수 있다 — 그것은 사실이지 결함이 아니고,
     자르면 "팩터가 전부 설명한다" 로 잘못 읽힌다.
  3. ★총분산이 없으면 비율을 주장하지 않는다★
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.factor_risk import portfolio_factor_risk  # noqa: E402

FACTORS = ["equity", "duration", "usd"]


def _cov(scale: float = 1.0) -> dict:
    rng = np.random.default_rng(11)
    A = rng.normal(0.0, 1.0, (3, 3))
    S = (A @ A.T) * 1e-4 * scale
    return {"available": True, "factors": list(FACTORS), "cov": S,
            "sd": np.sqrt(np.diag(S)), "n_months": 60,
            "span": ["2021-01", "2025-12"], "shrinkage_lambda": 0.3,
            "degenerate": False}


def _exposure(resolvable: float = 100.0, **betas) -> dict:
    b = {"equity": 1.0, "duration": -0.5, "usd": 0.3}
    b.update(betas)
    return {"available": True, "by_factor": {
        f: {"available": True, "exposure": v, "series": f.upper(),
            "coverage_pct": 100.0, "resolvable_pct": resolvable}
        for f, v in b.items()}}


# ── 1. 분해의 정합성 ───────────────────────────────────────────────────────
def test_factor_contributions_sum_to_the_factor_variance():
    r = portfolio_factor_risk(_exposure(), _cov())
    assert r["available"] is True, r["reason"]
    total = sum(row["variance_contribution"] for row in r["rows"])
    assert total == pytest.approx(r["factor_variance"], rel=1e-6)


def test_the_shares_sum_to_one_hundred_percent():
    r = portfolio_factor_risk(_exposure(), _cov())
    shares = sum(row["share_of_factor_pct"] for row in r["rows"])
    assert shares == pytest.approx(100.0, abs=0.05)


def test_rows_are_sorted_by_contribution():
    r = portfolio_factor_risk(_exposure(), _cov())
    mags = [abs(row["variance_contribution"]) for row in r["rows"]]
    assert mags == sorted(mags, reverse=True)


def test_a_bigger_exposure_raises_the_factor_variance():
    small = portfolio_factor_risk(_exposure(equity=0.5), _cov())["factor_variance"]
    big = portfolio_factor_risk(_exposure(equity=5.0), _cov())["factor_variance"]
    assert big > small


def test_the_volatility_is_the_root_of_the_variance():
    r = portfolio_factor_risk(_exposure(), _cov())
    assert r["factor_volatility"] == pytest.approx(
        np.sqrt(r["factor_variance"]), rel=1e-4)


# ── 2. ★초과 설명을 자르지 않는다★ ───────────────────────────────────────
def test_over_explanation_is_reported_rather_than_clamped():
    """★실측★ 단위 혼재 결함이 있을 때 고유분산이 −2.43 이었다.

    0 으로 자르면 "팩터가 100% 설명한다" 로 읽히는데, 그것은 사실이 아니라
    단변량 추정의 한계다.
    """
    r = portfolio_factor_risk(_exposure(), _cov(), total_variance=1e-9)
    assert r["over_explained"] is True
    assert r["idiosyncratic_variance"] < 0, "음수를 그대로 보고한다"
    assert r["idiosyncratic_share_pct"] < 0
    assert "중복 흡수" in r["share_reason"]


def test_a_normal_sample_has_positive_idiosyncratic_risk():
    """★짝★ 전부 초과 설명이라고 하면 위 테스트도 green 이다."""
    r = portfolio_factor_risk(_exposure(), _cov(), total_variance=1.0)
    assert r["over_explained"] is False
    assert r["idiosyncratic_variance"] > 0
    assert 0.0 <= r["factor_share_pct"] <= 100.0
    assert r["share_reason"] is None


def test_the_two_shares_add_to_one_hundred():
    r = portfolio_factor_risk(_exposure(), _cov(), total_variance=1.0)
    assert (r["factor_share_pct"] + r["idiosyncratic_share_pct"]
            == pytest.approx(100.0, abs=0.05))


# ── 3. ★없으면 주장하지 않는다★ ─────────────────────────────────────────
def test_without_total_variance_no_share_is_claimed():
    r = portfolio_factor_risk(_exposure(), _cov())
    assert r["factor_variance"] > 0, "팩터 분산은 낼 수 있다"
    assert r["factor_share_pct"] is None
    assert r["idiosyncratic_variance"] is None
    assert r["over_explained"] is None
    assert r["share_reason"]


def test_a_zero_total_variance_is_a_reason_not_a_division():
    r = portfolio_factor_risk(_exposure(), _cov(), total_variance=0.0)
    assert r["factor_share_pct"] is None and r["share_reason"]


def test_an_unavailable_exposure_propagates_its_reason():
    r = portfolio_factor_risk({"available": False, "reason": "노출 없음"}, _cov())
    assert r["available"] is False and r["reason"] == "노출 없음"


def test_an_unavailable_covariance_propagates_its_reason():
    r = portfolio_factor_risk(_exposure(), {"available": False, "reason": "표본 부족"})
    assert r["available"] is False and r["reason"] == "표본 부족"


def test_no_usable_factor_is_a_reason():
    e = _exposure()
    for row in e["by_factor"].values():
        row["available"] = False
    assert portfolio_factor_risk(e, _cov())["available"] is False


def test_factors_without_exposure_are_excluded_and_named():
    e = _exposure()
    e["by_factor"]["usd"] = {"available": False, "reason": "베타 없음"}
    r = portfolio_factor_risk(e, _cov())
    assert "usd" not in r["factors_used"] and "usd" in r["factors_unused"]
    total = sum(row["variance_contribution"] for row in r["rows"])
    assert total == pytest.approx(r["factor_variance"], rel=1e-6)


# ── 4. ★잡음 위의 분해★ ──────────────────────────────────────────────────
def test_insignificant_betas_make_the_decomposition_untrustworthy():
    r = portfolio_factor_risk(_exposure(resolvable=0.0), _cov())
    q = r["beta_quality"]
    assert q["mean_resolvable_pct"] == 0.0 and q["trustworthy"] is False


def test_significant_betas_are_trustworthy():
    """★짝★"""
    q = portfolio_factor_risk(_exposure(resolvable=100.0), _cov())["beta_quality"]
    assert q["trustworthy"] is True


def test_the_method_declares_its_univariate_limitation():
    r = portfolio_factor_risk(_exposure(), _cov())
    assert r["method"] == "univariate_beta_factor_model"
    assert "단변량" in r["note"]


# ── 5. 포트폴리오 월별 수익률 ────────────────────────────────────────────
def test_the_portfolio_series_declares_fixed_weights():
    from src.engine.factor_risk import portfolio_monthly_returns
    out = portfolio_monthly_returns({"005930": 60.0, "000660": 40.0})
    if not out["available"]:
        pytest.skip(f"이 환경에서 월별 수익률을 낼 수 없다: {out['reason']}")
    assert out["variance"] > 0
    assert out["coverage_pct"] == pytest.approx(100.0, abs=0.01)
    assert "고정으로 가정" in out["note"]


def test_zero_weights_are_refused():
    from src.engine.factor_risk import portfolio_monthly_returns
    out = portfolio_monthly_returns({"005930": 0.0})
    assert out["available"] is False and out["reason"]


def test_an_unknown_code_is_reported_as_missing():
    from src.engine.factor_risk import portfolio_monthly_returns
    out = portfolio_monthly_returns({"005930": 50.0, "없는종목ZZ": 50.0})
    if not out["available"]:
        pytest.skip("이 환경에서 월별 수익률을 낼 수 없다")
    # 커버리지가 100% 미만이면 누락을 반드시 명명한다.
    if out["coverage_pct"] < 100.0:
        assert out["missing"]


# ── 6. ★합이 아니라 **각 항**을 잰다★ ────────────────────────────────────
def test_each_contribution_is_the_marginal_one_not_an_equal_split():
    """★변이 프로브가 두 번째로 드러낸 같은 구멍★

    앞 판본은 "기여 합 = 팩터분산" 만 봤다. **균등 배분**도 그 합을 만족하므로
    `contrib = factor_var/n` 으로 바꿔도 green 이었다. 역스트레스에서 겪은 것과
    똑같은 실수다 — 합만 재는 가드는 항이 여럿인 분해에서 가드가 아니다.
    """
    S = _cov()
    e = _exposure()
    r = portfolio_factor_risk(e, S)

    order = [row["factor"] for row in r["rows"]]
    idx = [S["factors"].index(f) for f in order]
    M = np.asarray(S["cov"])[np.ix_(idx, idx)]
    beta = np.array([e["by_factor"][f]["exposure"] for f in order])
    expected = beta * (M @ beta)

    got = np.array([row["variance_contribution"] for row in r["rows"]])
    assert np.allclose(got, expected, rtol=1e-6), (got, expected)


def test_the_contributions_are_not_all_equal():
    """★균등 배분이면 전부 같다★ 노출이 다른데 기여가 같을 수는 없다."""
    r = portfolio_factor_risk(_exposure(), _cov())
    vals = [row["variance_contribution"] for row in r["rows"]]
    assert len({round(v, 12) for v in vals}) == len(vals), vals


def test_a_zero_exposure_factor_contributes_nothing():
    """짝 — 노출이 0 인 팩터의 기여는 0 이어야 한다(균등 배분이면 0 이 아니다)."""
    r = portfolio_factor_risk(_exposure(usd=0.0), _cov())
    usd = next(row for row in r["rows"] if row["factor"] == "usd")
    assert usd["variance_contribution"] == pytest.approx(0.0, abs=1e-15)
