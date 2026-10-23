"""P3-2 — 백테스트 실현수익의 팩터 귀인

★이 파일이 거는 것★
  1. 항등식: α 기여 + 팩터 기여 = 산술 합계.
  2. ★합만 재지 않는다★ 각 β 가 결합 해와 일치하고, 심은 팩터가 실제로 잡히며,
     기여가 서로 다르다. (이 세션에서 "합만 재는 가드" 가 **두 번** 뚫렸다 —
     역스트레스·P3-4 둘 다 '균등 배분' 변이가 green 이었다.)
  3. ★산술 합과 복리를 같은 것처럼 내지 않는다★
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.backtest_attribution import (  # noqa: E402
    MIN_MONTHS,
    VIF_WARN,
    factor_attribution,
    monthly_returns_from_result,
)

SEED = 20260823


def _months(n: int) -> list[str]:
    return [f"{2020 + (i // 12):04d}-{(i % 12) + 1:02d}" for i in range(n)]


def _resolved(n: int = 60, seed: int = SEED, corr: float = 0.0,
              names=("alpha_f", "beta_f", "gamma_f")) -> dict:
    """상관을 조절할 수 있는 합성 팩터. `corr` 이 크면 첫 둘이 붙는다."""
    rng = np.random.default_rng(seed)
    ms = _months(n)
    base = {nm: rng.normal(0.0, 0.02, n) for nm in names}
    if corr > 0:
        a, b = names[0], names[1]
        base[b] = corr * base[a] + np.sqrt(1 - corr ** 2) * base[b]
    return {nm: {"series": nm.upper(), "transform": "pct",
                 "changes": dict(zip(ms, v, strict=True))}
            for nm, v in base.items()}


def _returns_from(resolved: dict, loads: dict, alpha: float = 0.001,
                  noise: float = 0.0, seed: int = 5) -> dict:
    """★팩터를 **심어서** 만든 수익률★ 무엇이 잡혀야 하는지 알고 잰다."""
    rng = np.random.default_rng(seed)
    ms = sorted(next(iter(resolved.values()))["changes"])
    out = {}
    for m in ms:
        v = alpha + sum(b * resolved[f]["changes"][m] for f, b in loads.items())
        if noise:
            v += rng.normal(0.0, noise)
        out[m] = v
    return out


def _result(returns: dict) -> dict:
    return {"monthly_returns": [
        {"year": int(m[:4]), "month": int(m[5:]), "return_pct": v * 100.0}
        for m, v in returns.items()]}


# ── 1. ★항등식★ ───────────────────────────────────────────────────────────
def test_alpha_and_factors_add_up_to_the_arithmetic_total():
    res = _resolved()
    a = factor_attribution(_returns_from(res, {"alpha_f": 1.5}), res)
    assert a["available"] is True, a["reason"]
    assert (a["alpha_contribution_pct"] + a["factor_contribution_pct"]
            == pytest.approx(a["arithmetic_total_pct"], abs=1e-3))
    assert abs(a["identity_residual_pct"]) < 1e-6


def test_the_identity_residual_is_reported_not_assumed():
    """0 이 아니면 그 자체가 결함 신호다 — 출력에 싣는다."""
    res = _resolved()
    a = factor_attribution(_returns_from(res, {"beta_f": -0.8}), res)
    assert "identity_residual_pct" in a


# ── 2. ★합이 아니라 각 항을 잰다★ ────────────────────────────────────────
def test_each_beta_matches_the_joint_least_squares_solution():
    """★균등 배분·단변량으로 바꿔도 합은 맞을 수 있다★ 각 항을 못박는다."""
    res = _resolved()
    loads = {"alpha_f": 1.2, "gamma_f": -0.7}
    rets = _returns_from(res, loads, noise=0.003)
    a = factor_attribution(rets, res)

    order = [r["factor"] for r in a["rows"]]
    ms = sorted(set(rets) & set(res[order[0]]["changes"]))
    y = np.array([rets[m] for m in ms])
    X = np.array([[res[f]["changes"][m] for f in order] for m in ms])
    coef, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(ms)), X]), y, rcond=None)

    got = np.array([r["beta"] for r in a["rows"]])
    assert np.allclose(got, coef[1:], atol=1e-5), (got, coef[1:])
    assert a["alpha_monthly"] == pytest.approx(coef[0], abs=1e-6)


def test_the_planted_factor_is_the_one_that_shows_up():
    """★심은 것이 잡혀야 한다★ 균등 배분이면 이 구분이 사라진다."""
    res = _resolved()
    a = factor_attribution(_returns_from(res, {"beta_f": 3.0}, alpha=0.0), res)
    top = a["rows"][0]
    assert top["factor"] == "beta_f", [r["factor"] for r in a["rows"]]
    assert top["beta"] == pytest.approx(3.0, rel=0.05)


def test_contributions_are_not_all_equal():
    res = _resolved()
    a = factor_attribution(_returns_from(res, {"alpha_f": 2.0}, noise=0.002), res)
    vals = [r["contribution_pct"] for r in a["rows"]]
    assert len({round(v, 9) for v in vals}) == len(vals), vals


def test_a_factor_with_no_loading_contributes_almost_nothing():
    res = _resolved()
    a = factor_attribution(_returns_from(res, {"alpha_f": 2.0}, alpha=0.0), res)
    other = next(r for r in a["rows"] if r["factor"] == "gamma_f")
    planted = next(r for r in a["rows"] if r["factor"] == "alpha_f")
    assert abs(other["contribution_pct"]) < abs(planted["contribution_pct"]) / 50


def test_returns_unrelated_to_factors_are_mostly_alpha():
    """팩터와 무관하면 α 가 거의 전부여야 한다."""
    res = _resolved()
    rng = np.random.default_rng(3)
    ms = sorted(res["alpha_f"]["changes"])
    rets = {m: 0.004 + float(rng.normal(0, 0.001)) for m in ms}
    a = factor_attribution(rets, res)
    assert abs(a["alpha_contribution_pct"]) > abs(a["factor_contribution_pct"]) * 5
    assert a["diagnostics"]["r_squared"] < 0.3


# ── 3. ★다중공선성을 라벨한다★ ──────────────────────────────────────────
def test_correlated_factors_are_flagged_as_collinear():
    """★실측★ `duration`–`credit` 이 0.82 로 붙어 +14.3/−8.3%p 로 상쇄됐다.
    결합 적합은 멀쩡해도 **개별 귀인은 불안정**하다."""
    res = _resolved(corr=0.95)
    a = factor_attribution(_returns_from(res, {"alpha_f": 1.0}, noise=0.002), res)
    flagged = [r for r in a["rows"] if r["collinear"]]
    assert flagged, {r["factor"]: r["vif"] for r in a["rows"]}
    for r in flagged:
        assert r["vif"] > VIF_WARN
        assert "개별 값으로 읽지 마십시오" in r["collinear_reason"]


def test_independent_factors_are_not_flagged():
    """★짝★ 전부 상쇄주의라고 하면 위 테스트도 green 이다."""
    res = _resolved(corr=0.0)
    a = factor_attribution(_returns_from(res, {"alpha_f": 1.0}, noise=0.002), res)
    assert not any(r["collinear"] for r in a["rows"])
    assert a["diagnostics"]["max_vif"] < VIF_WARN


def test_the_diagnostics_report_the_sample_shape():
    res = _resolved()
    d = factor_attribution(_returns_from(res, {"alpha_f": 1.0}), res)["diagnostics"]
    assert d["n_factors"] == 3
    assert d["dof"] == d["n_months"] - d["n_factors"] - 1
    assert d["obs_per_param"] == pytest.approx(
        d["n_months"] / (d["n_factors"] + 1), abs=0.01)
    assert d["condition_number"] > 0


# ── 4. ★산술 합 ≠ 복리★ ─────────────────────────────────────────────────
def test_both_totals_are_reported_and_differ():
    """★같은 것처럼 내면 거짓이다★ 실측에서 산술 +0.920% vs 복리 −2.157%."""
    res = _resolved()
    rng = np.random.default_rng(9)
    ms = sorted(res["alpha_f"]["changes"])
    rets = {m: float(rng.normal(0.0, 0.08)) for m in ms}   # 큰 변동 → 복리 격차
    a = factor_attribution(rets, res)
    assert a["arithmetic_total_pct"] != a["compound_total_pct"]
    assert a["compounding_gap_pct"] == pytest.approx(
        a["compound_total_pct"] - a["arithmetic_total_pct"], abs=1e-3)
    assert "산술 합" in a["note"]


def test_the_identity_closes_on_the_arithmetic_total_not_the_compound_one():
    res = _resolved()
    rng = np.random.default_rng(4)
    ms = sorted(res["alpha_f"]["changes"])
    rets = {m: float(rng.normal(0.0, 0.08)) for m in ms}
    a = factor_attribution(rets, res)
    assert (a["alpha_contribution_pct"] + a["factor_contribution_pct"]
            == pytest.approx(a["arithmetic_total_pct"], abs=1e-3))


# ── 5. 낼 수 없으면 사유 ────────────────────────────────────────────────
def test_too_few_shared_months_is_a_reason():
    res = _resolved(n=MIN_MONTHS - 1)
    a = factor_attribution(_returns_from(res, {"alpha_f": 1.0}), res)
    assert a["available"] is False and "공통으로 갖는 달" in a["reason"]


def test_insufficient_degrees_of_freedom_is_refused():
    """★모수보다 관측이 겨우 많으면 계수를 내지 않는다★"""
    names = tuple(f"f{i}" for i in range(24))
    res = _resolved(n=26, names=names)
    a = factor_attribution(_returns_from(res, {"f0": 1.0}), res, min_months=10)
    assert a["available"] is False and "자유도" in a["reason"]


def test_empty_inputs_are_reasons():
    assert factor_attribution({}, _resolved())["available"] is False
    assert factor_attribution({"2021-01": 0.01}, {})["available"] is False


# ── 6. `bt_*` 결과 읽기 ─────────────────────────────────────────────────
def test_monthly_returns_are_read_from_a_backtest_result():
    res = _resolved()
    rets = _returns_from(res, {"alpha_f": 1.0})
    out = monthly_returns_from_result(_result(rets))
    assert out["available"] is True
    assert out["n_months"] == len(rets) and out["skipped_rows"] == 0
    first = sorted(rets)[0]
    assert out["returns"][first] == pytest.approx(rets[first], abs=1e-9)


def test_a_missing_monthly_block_is_a_reason_not_an_empty_dict():
    """★빈 dict 면 '팩터가 0을 설명했다' 와 '잴 것이 없었다' 가 같아 보인다★"""
    out = monthly_returns_from_result({"statistics": {}})
    assert out["available"] is False and "월별 수익률이 없습니다" in out["reason"]


def test_an_empty_list_is_a_reason():
    assert monthly_returns_from_result({"monthly_returns": []})["available"] is False


def test_a_missing_result_is_a_reason():
    assert monthly_returns_from_result(None)["available"] is False


def test_malformed_rows_are_counted_not_silently_dropped():
    good = {"year": 2021, "month": 3, "return_pct": 1.5}
    out = monthly_returns_from_result({"monthly_returns": [
        good, {"year": 2021, "month": 13, "return_pct": 1.0},
        {"year": 2021, "return_pct": 1.0}, {"year": 2021, "month": 4,
                                            "return_pct": "x"}]})
    assert out["available"] is True
    assert out["n_months"] == 1 and out["skipped_rows"] == 3


def test_all_malformed_rows_is_a_reason():
    out = monthly_returns_from_result({"monthly_returns": [{"bad": 1}, {"bad": 2}]})
    assert out["available"] is False and "하나도 읽지 못했습니다" in out["reason"]


def test_correlation_is_labelled_as_not_causation():
    res = _resolved()
    a = factor_attribution(_returns_from(res, {"alpha_f": 1.0}), res)
    assert "인과가 아닙니다" in a["causality"]
    assert a["method"] == "joint_ols_monthly"
