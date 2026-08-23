"""역스트레스 — −15% 를 만들려면 무엇이 일어나야 하는가 (Brief §12)

★이 파일이 거는 것★
  1. ★역산이 실제로 목표를 맞힌다★ 기여 합계 = 목표 손실.
  2. ★거리를 반드시 함께 낸다★ 충격만 내면 현실성을 알 수 없다.
  3. ★잡음 위에 선 시나리오를 '흔하다' 로 읽지 않게 한다★ 거리와 베타 품질은
     다른 질문이다 — 거리가 작아도 베타가 구분되지 않으면 못 믿는다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.reverse_stress import (  # noqa: E402
    DEFAULT_LOSS_PCT,
    MIN_MONTHS,
    factor_covariance,
    reverse_stress,
)

FACTORS = ["equity", "duration", "usd"]


def _resolved(n_months: int = 60, seed: int = 20260823) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    for i, f in enumerate(FACTORS):
        vals = rng.normal(0.0, 0.01 * (i + 1), n_months)
        months = [f"{2021 + (j // 12)}-{(j % 12) + 1:02d}" for j in range(n_months)]
        out[f] = {"series": f.upper(), "transform": "pct",
                  "changes": dict(zip(months, vals, strict=True))}
    return out


def _exposure(**betas) -> dict:
    b = {"equity": 1.0, "duration": -0.5, "usd": 0.3}
    b.update(betas)
    return {"available": True, "by_factor": {
        f: {"available": True, "exposure": v, "series": f.upper(),
            "transform": "pct", "coverage_pct": 100.0, "resolvable_pct": 100.0}
        for f, v in b.items()}}


@pytest.fixture(scope="module")
def cov() -> dict:
    c = factor_covariance(_resolved())
    assert c["available"] is True, c["reason"]
    return c


# ── 1. ★역산이 목표를 맞힌다★ ────────────────────────────────────────────
def test_the_contributions_add_up_to_the_target_loss(cov):
    """★닫힌 해의 정합성★ β's = L 이 실제로 성립하는지."""
    for loss in (-5.0, -15.0, -30.0, 8.0):
        r = reverse_stress(_exposure(), cov, loss_pct=loss)
        assert r["available"] is True, r["reason"]
        total = sum(s["contribution_pct"] for s in r["shocks"])
        # 기여는 4자리로 반올림돼 나가므로 항 수만큼 잔차가 쌓인다(≈1e-4).
        assert total == pytest.approx(loss, abs=1e-3), (loss, total)


def test_a_bigger_loss_needs_a_bigger_shock(cov):
    small = reverse_stress(_exposure(), cov, loss_pct=-5.0)
    big = reverse_stress(_exposure(), cov, loss_pct=-20.0)
    for a, b in zip(small["shocks"], big["shocks"], strict=True):
        assert abs(b["shock"]) > abs(a["shock"])


def test_the_shocks_are_sorted_by_contribution(cov):
    r = reverse_stress(_exposure(), cov, loss_pct=DEFAULT_LOSS_PCT)
    mags = [abs(s["contribution_pct"]) for s in r["shocks"]]
    assert mags == sorted(mags, reverse=True)


def test_a_zero_target_is_refused(cov):
    assert reverse_stress(_exposure(), cov, loss_pct=0.0)["available"] is False


# ── 2. ★거리를 반드시 함께 낸다★ ─────────────────────────────────────────
def test_the_distance_is_reported_with_every_scenario(cov):
    """★충격만 내면 '이게 현실적인가' 를 알 수 없다★"""
    r = reverse_stress(_exposure(), cov, loss_pct=-15.0)
    assert r["distance"] > 0
    assert r["plausibility"]["label"] in ("routine", "plausible", "severe", "extreme")
    assert r["plausibility"]["sigma"] == r["distance"]
    assert r["plausibility"]["text"]


def test_the_distance_scales_linearly_with_the_loss(cov):
    """d = |L| / sqrt(β'Σβ) — 손실이 2배면 거리도 2배."""
    a = reverse_stress(_exposure(), cov, loss_pct=-10.0)["distance"]
    b = reverse_stress(_exposure(), cov, loss_pct=-20.0)["distance"]
    assert b == pytest.approx(a * 2.0, rel=1e-3)


def test_a_smaller_exposure_makes_the_same_loss_more_extreme(cov):
    """★노출이 작으면 같은 손실을 내려면 더 큰 사건이 필요하다★"""
    big = reverse_stress(_exposure(equity=2.0), cov, loss_pct=-15.0)["distance"]
    small = reverse_stress(_exposure(equity=0.2), cov, loss_pct=-15.0)["distance"]
    assert small > big


def test_each_shock_is_expressed_in_standard_deviations(cov):
    r = reverse_stress(_exposure(), cov, loss_pct=-15.0)
    for s in r["shocks"]:
        assert s["shock_in_sd"] is not None
        assert np.sign(s["shock_in_sd"]) == np.sign(s["shock"]) or s["shock"] == 0


@pytest.mark.parametrize("sigma,label", [
    (0.5, "routine"), (1.5, "plausible"), (2.5, "severe"), (5.0, "extreme")])
def test_the_plausibility_labels_have_boundaries(sigma, label):
    from src.engine.reverse_stress import _plausibility
    assert _plausibility(sigma)["label"] == label


# ── 3. ★잡음 위에 선 시나리오★ ──────────────────────────────────────────
def test_a_scenario_built_on_insignificant_betas_says_so(cov):
    """★거리가 작아도 베타를 못 믿으면 시나리오도 못 믿는다★

    이 둘은 **다른 질문**이다 — 거리는 "충격이 얼마나 큰가", 베타 품질은
    "그 노출을 믿을 수 있는가".
    """
    e = _exposure()
    for row in e["by_factor"].values():
        row["resolvable_pct"] = 0.0
    r = reverse_stress(e, cov, loss_pct=-15.0)
    q = r["beta_quality"]
    assert q["available"] is True
    assert q["mean_resolvable_pct"] == 0.0
    assert q["trustworthy"] is False
    assert "잡음으로 만든 충격은 잡음입니다" in q["note"]


def test_resolvable_betas_are_reported_as_trustworthy(cov):
    """★짝★ 전부 못 믿는다고 하면 위 테스트도 green 이다."""
    q = reverse_stress(_exposure(), cov, loss_pct=-15.0)["beta_quality"]
    assert q["mean_resolvable_pct"] == 100.0 and q["trustworthy"] is True


# ── 4. 공분산 ─────────────────────────────────────────────────────────────
def test_only_shared_months_are_used():
    """★계열마다 구간이 다른데 그냥 붙이면 다른 달을 비교하게 된다★"""
    res = _resolved()
    res["usd"]["changes"] = {m: v for i, (m, v) in
                             enumerate(res["usd"]["changes"].items()) if i >= 20}
    c = factor_covariance(res)
    assert c["available"] is True
    assert c["n_months"] == 40
    assert "공통 월" in c["note"]


def test_a_thin_overlap_is_a_reason_not_a_matrix():
    res = _resolved(n_months=MIN_MONTHS + 1)
    res["usd"]["changes"] = dict(list(res["usd"]["changes"].items())[:5])
    c = factor_covariance(res)
    assert c["available"] is False and "공통으로 갖는 달" in c["reason"]


def test_a_single_factor_cannot_form_a_covariance():
    res = {"equity": _resolved()["equity"]}
    assert factor_covariance(res)["available"] is False


def test_a_fully_shrunk_covariance_is_flagged_as_degenerate():
    """★λ=1 이면 상관구조가 지워진 것이다★ 숫자는 나오지만 뜻이 다르다."""
    c = factor_covariance(_resolved(), shrinkage=1.0)
    assert c["shrinkage_lambda"] == pytest.approx(1.0)
    assert c["degenerate"] is True
    r = reverse_stress(_exposure(), c, loss_pct=-15.0)
    assert r["degenerate_covariance"] is True


def test_a_healthy_covariance_is_not_flagged(cov):
    assert cov["degenerate"] is False
    assert reverse_stress(_exposure(), cov,
                          loss_pct=-15.0)["degenerate_covariance"] is False


# ── 5. 낼 수 없는 경우는 사유 ────────────────────────────────────────────
def test_a_zero_exposure_book_cannot_be_reverse_stressed(cov):
    """★노출이 0 이면 어떤 충격도 손실을 만들지 못한다★ 0 을 지어내지 않는다."""
    r = reverse_stress(_exposure(equity=0.0, duration=0.0, usd=0.0), cov,
                       loss_pct=-15.0)
    assert r["available"] is False and "β'Σβ" in r["reason"]


def test_factors_without_exposure_are_excluded_and_named(cov):
    e = _exposure()
    e["by_factor"]["usd"] = {"available": False, "reason": "베타 없음"}
    r = reverse_stress(e, cov, loss_pct=-15.0)
    assert r["available"] is True
    assert "usd" not in r["factors_used"] and "usd" in r["factors_unused"]
    assert sum(s["contribution_pct"] for s in r["shocks"]) == pytest.approx(-15.0, abs=1e-3)


def test_an_unavailable_exposure_propagates_its_reason(cov):
    r = reverse_stress({"available": False, "reason": "노출 없음"}, cov)
    assert r["available"] is False and r["reason"] == "노출 없음"


def test_an_unavailable_covariance_propagates_its_reason():
    r = reverse_stress(_exposure(), {"available": False, "reason": "표본 부족"})
    assert r["available"] is False and r["reason"] == "표본 부족"


def test_the_answer_is_labelled_as_not_unique(cov):
    """★같은 손실을 내는 조합은 무수히 많다★ 유일한 답인 척하지 않는다."""
    r = reverse_stress(_exposure(), cov, loss_pct=-15.0)
    assert "무수히 많습니다" in r["note"]
    assert r["method"] == "min_mahalanobis_shock"


# ── 6. ★제약이 아니라 **최적성**을 잰다★ ─────────────────────────────────
def _mahalanobis(s: np.ndarray, S: np.ndarray) -> float:
    return float(np.sqrt(s @ np.linalg.inv(S) @ s))


def test_the_chosen_shock_is_the_most_plausible_one(cov):
    """★변이 프로브가 드러낸 구멍★

    앞 판본은 "기여 합계 = 목표 손실" 만 봤다. 그런데 **균등 분배**도 그 제약을
    만족한다(β's = L) — 공분산을 통째로 무시한 해가 green 으로 통과했다.
    이 함수의 요점은 제약이 아니라 **그중 가장 그럴듯한 것**을 고르는 것이다.
    """
    e = _exposure()
    r = reverse_stress(e, cov, loss_pct=-15.0)
    order = r["factors_used"]
    idx = [cov["factors"].index(f) for f in order]
    S = np.asarray(cov["cov"])[np.ix_(idx, idx)]
    beta = np.array([e["by_factor"][f]["exposure"] for f in order])

    chosen = np.array([next(s["shock"] for s in r["shocks"] if s["factor"] == f)
                       for f in order])
    # 제약을 만족하는 **다른** 해 — 균등 분배(프로브가 쓴 바로 그것).
    equal = np.full_like(beta, -0.15 / beta.sum())
    assert float(beta @ equal) == pytest.approx(-0.15, abs=1e-9), "대조군도 제약은 만족한다"

    assert _mahalanobis(chosen, S) < _mahalanobis(equal, S), (
        "선택된 충격이 더 그럴듯하지 않다 — 최적성이 깨졌다")


def test_the_shock_is_proportional_to_sigma_beta(cov):
    """★닫힌 해의 형태★ s* ∝ Σβ — 방향이 공분산에 의해 정해진다."""
    e = _exposure()
    r = reverse_stress(e, cov, loss_pct=-15.0)
    order = r["factors_used"]
    idx = [cov["factors"].index(f) for f in order]
    S = np.asarray(cov["cov"])[np.ix_(idx, idx)]
    beta = np.array([e["by_factor"][f]["exposure"] for f in order])

    chosen = np.array([next(s["shock"] for s in r["shocks"] if s["factor"] == f)
                       for f in order])
    Sb = S @ beta
    ratios = chosen / Sb
    # `shock` 은 6자리로 반올림돼 나가고 값이 1e-4 규모라 상대오차가 ~5e-3 까지
    # 생긴다 — 재는 것은 **비례성**이지 부동소수 정확도가 아니다.
    assert np.allclose(ratios, ratios[0], rtol=1e-3), (
        f"s 가 Σβ 에 비례하지 않는다: {ratios}")


def test_the_reported_distance_matches_the_actual_shock(cov):
    """거리가 장식이 아니라 실제 해의 거리인지."""
    e = _exposure()
    r = reverse_stress(e, cov, loss_pct=-15.0)
    order = r["factors_used"]
    idx = [cov["factors"].index(f) for f in order]
    S = np.asarray(cov["cov"])[np.ix_(idx, idx)]
    chosen = np.array([next(s["shock"] for s in r["shocks"] if s["factor"] == f)
                       for f in order])
    assert _mahalanobis(chosen, S) == pytest.approx(r["distance"], rel=1e-3)
